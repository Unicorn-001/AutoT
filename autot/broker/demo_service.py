"""Manual shadow execution of persisted paper intents; paper storage is read-only."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from uuid import uuid4

from autot.runtime import data_dir
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.fill_risk import recheck
from autot.market_context.assessment import assess
from autot.market_context.store import MarketContextStore
from autot.utils.financial_validation import decimal_value as D
from .execution_store import ExecutionStore, encode
from .external import ExternalBroker, QuoteProvider, InstrumentResolver
from .etoro.client import Client, BrokerError
from .etoro.market import EtoroQuoteProvider
from .etoro.broker import EtoroDemoBroker


def now():
    return datetime.now(timezone.utc)


class DemoService:
    def __init__(self, client=None, store=None, paper_path=None, *,
                 broker: ExternalBroker | None = None, quotes: QuoteProvider | None = None,
                 resolver: InstrumentResolver | None = None):
        self.client = client or Client()
        from .etoro.market import Resolver
        self.broker: ExternalBroker = broker or EtoroDemoBroker(self.client)
        self.resolver: InstrumentResolver = resolver or Resolver(self.client)
        self.quotes: QuoteProvider = quotes or EtoroQuoteProvider(self.client, self.resolver)
        self.store = store or ExecutionStore()
        self.paper_path = Path(paper_path) if paper_path else data_dir() / 'paper_trading' / 'ledger.sqlite3'

    def paper_snapshot(self):
        if not self.paper_path.exists():
            return [], {}
        with sqlite3.connect(self.paper_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            return [Ledger.decode(r) for r in db.execute('SELECT * FROM trades')], Ledger._summaries(db)

    @staticmethod
    def scanner_link(trade):
        """Recover provenance without changing legacy paper snapshots or scans.

        Multiple matching scans are retained as candidates, never guessed.
        The paper signal identity remains authoritative for legacy intents.
        """
        path = data_dir() / 'scanner' / 'scans.sqlite3'
        matches = []
        if path.exists():
            with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
                for run_id, raw in db.execute('SELECT scan_run_id, result FROM scan_runs WHERE result IS NOT NULL'):
                    saved = json.loads(raw)
                    context = saved.get('paper_signal_context', {}).get(trade['symbol'], {})
                    if context.get('signal_time') != trade['signal_time']:
                        continue
                    for index, opportunity in enumerate(saved.get('outputs', {}).get('trade_opportunities', [])):
                        if opportunity == trade.get('original_opportunity'):
                            matches.append(dict(scanner_run_id=run_id, opportunity_id=str(index)))
        return matches

    def submit(self, paper_trade_id, *, confirmed=False):
        if confirmed is not True or self.client.config.mode != 'demo':
            raise BrokerError('Explicit manual DEMO confirmation is required.')
        # Serialize competing confirmations, including preflight checks. Unknown or
        # pending orders block additional exposure until explicitly reconciled.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload FROM executions WHERE paper_trade_id=?', (paper_trade_id,)).fetchone()
            if existing:
                return json.loads(existing[0])
            records = [json.loads(r[0]) for r in db.execute('SELECT payload FROM executions')]
            if any(r['broker_status'] in ('INTENDED', 'UNKNOWN', 'SUBMITTED', 'PENDING', 'PARTIAL')
                   or r.get('close_status') in ('INTENDED', 'UNKNOWN', 'SUBMITTED', 'PENDING', 'PARTIAL')
                   for r in records):
                raise BrokerError('Reconcile outstanding broker intent before another submission.')
            trades, summaries = self.paper_snapshot()
            trade = next((t for t in trades if t['trade_id'] == paper_trade_id), None)
            if not trade or trade['market'] != 'US' or trade['side'] != 'BUY' or trade['status'] not in ('PENDING_ENTRY', 'OPEN'):
                raise BrokerError('Select an active US BUY paper intent. Opening shorts is disabled.')
            instrument = self.resolver.resolve(trade['symbol'])
            self.resolver.require_us_stock(instrument)
            self.broker.require_underlying(instrument['instrumentId'])
            quote = self.quotes.quote(trade['symbol'], trade['side'])
            stamp = now()
            if quote.quote_timestamp is None or not 0 <= (stamp - quote.quote_timestamp).total_seconds() <= 300:
                raise BrokerError('Fresh timestamped executable quote is required (maximum age 300 seconds).')
            links = self.scanner_link(trade)
            link = links[0] if len(links) == 1 else dict(scanner_run_id=None, opportunity_id=paper_trade_id)
            assessment = assess(symbol=trade['symbol'], side=trade['side'], reference_entry=trade['signal_price'],
                stop_loss=trade['stop_loss'], take_profit=trade['take_profit'], original_rr=trade['risk_reward_ratio'],
                current_price=quote.price, source=quote.source,
                **link)
            assessment.update(quote.audit(quote.price))
            MarketContextStore().save(assessment)
            check = recheck(trade, quote.price, trades, summaries['USD'],
                            checked_at=stamp.isoformat(), fill_time=stamp.isoformat())
            if assessment['decision'] == 'REJECT' or check['decision'] != 'ACCEPT':
                raise BrokerError('Current market context/risk check rejected or requires resizing. No order sent.')
            account = self.broker.account()
            # Existing broker holdings must correspond to this journal. Unknown
            # exposure cannot safely be treated as an empty demo portfolio.
            known = {p for r in records for p in r.get('position_ids', [])}
            if any(account.get(k) for k in ('mirrors', 'orders', 'ordersForOpen', 'ordersForClose', 'ordersForCloseMultiple')):
                raise BrokerError('Unreconciled demo portfolio activity; review in eToro first.')
            positions = account.get('positions')
            if positions is None or any(p.get('positionId') not in known for p in positions):
                raise BrokerError('Untracked demo positions; portfolio risk cannot be verified.')
            notional = quote.price * trade['quantity']
            if D(account.get('credit'), positive=True) < notional:
                raise BrokerError('Insufficient demo credit.')
            # All tracked broker positions must still have active paper exposure.
            active_ids = {t['trade_id'] for t in trades if t['status'] in ('PENDING_ENTRY', 'OPEN')}
            if any(r['paper_trade_id'] not in active_ids and set(r.get('position_ids', [])) &
                   {p['positionId'] for p in positions} for r in records):
                raise BrokerError('Broker/paper exposure diverged; reconcile before adding exposure.')
            broker_trades = []
            for p in positions:
                matched = next(r for r in records if p['positionId'] in r.get('position_ids', []))
                quantity = D(p['units'], positive=True)
                if quantity != quantity.to_integral_value() or p.get('isBuy') is not True or p.get('leverage') != 1:
                    raise BrokerError('Broker exposure cannot be mapped safely to current AutoT risk rules.')
                broker_trades.append(dict(trade_id=str(p['positionId']), currency='USD', market='US',
                    mode=matched.get('mode'), created_at=matched['submitted_at'], status='OPEN',
                    signal_price=str(p['openRate']), fill_price=str(p['openRate']),
                    stop_loss=str(p['stopLossRate']), quantity=int(quantity)))
            reserved = sum((D(t['fill_price']) * t['quantity'] for t in broker_trades), D(0))
            # Closed/rejected broker intents still count toward the existing
            # confirmation-day daily policy, just as they do in the paper ledger.
            open_position_ids = {p['positionId'] for p in positions}
            for r in records:
                if not set(r.get('position_ids', [])) & open_position_ids:
                    broker_trades.append(dict(trade_id=r['intent_key'], currency='USD', market='US',
                        mode=r.get('mode'), created_at=r['submitted_at'], status='CLOSED',
                        signal_price=r['reference_entry'], fill_price=None,
                        stop_loss=r['stop'], quantity=r['intended_quantity']))
            # Preserve AutoT's configured capital/risk budget, independently check
            # actual broker exposures, and separately enforce broker cash above.
            capital = D(trade['account_capital'])
            broker_summary = dict(currency='USD', capital=capital, realized_pnl=D(0), unrealized_pnl=D(0),
                reserved=reserved + D(trade['signal_price']) * trade['quantity'],
                available=capital - reserved - D(trade['signal_price']) * trade['quantity'])
            broker_check = recheck(dict(trade, created_at=stamp.isoformat()), quote.price, broker_trades,
                broker_summary, checked_at=stamp.isoformat(), fill_time=stamp.isoformat())
            if broker_check['decision'] != 'ACCEPT':
                raise BrokerError('Current broker exposure failed AutoT risk validation.')
            if (now() - quote.quote_timestamp).total_seconds() > 300:
                raise BrokerError('Quote expired during preflight. Fetch a new quote and confirm again.')
            payload = self.broker.prepare_order(instrument_id=instrument['instrumentId'],
                quantity=trade['quantity'], stop=trade['stop_loss'], target=trade['take_profit'])
            key, request_id = str(uuid4()), str(uuid4())
            record = dict(intent_key=key, request_id=request_id, paper_trade_id=paper_trade_id,
                scanner_run_id=assessment['scanner_run_id'], opportunity_id=assessment['opportunity_id'],
                scanner_candidates=links, signal_time=trade['signal_time'], signal_timeframe=trade['signal_timeframe'],
                mode=trade.get('mode'),
                symbol=trade['symbol'], intended_side=trade['side'], reference_entry=trade['signal_price'],
                stop=trade['stop_loss'], target=trade['take_profit'], intended_quantity=trade['quantity'],
                intended_notional=str(notional), instrument_id=instrument['instrumentId'], broker_order_id=None,
                submitted_at=stamp.isoformat(), broker_status='INTENDED', fill_price=None, filled_at=None,
                filled_quantity=None, filled_notional=None, rejection_reason=None, cancellation_reason=None,
                fees=None, position_ids=[], risk_check=check, broker_risk_check=broker_check,
                market_context=assessment, order_payload=payload)
            db.execute('INSERT INTO executions VALUES (?,?,?,?)', (key, request_id, paper_trade_id, encode(record)))
            db.execute('INSERT INTO execution_events(intent_key,payload) VALUES (?,?)', (key, encode(record)))
        try:
            response = self.broker.submit(payload, request_id=request_id, confirmed=confirmed)
            if not response.get('orderId'):
                raise BrokerError('Missing broker order ID; reconcile by request ID.', uncertain=True)
            return self.store.update(key, dict(broker_order_id=response['orderId'], broker_status='SUBMITTED',
                                               submission_response={'orderId': response['orderId'], 'referenceId': response.get('referenceId')}))
        except BrokerError as error:
            return self.store.update(key, dict(broker_status='UNKNOWN' if error.uncertain else 'REJECTED',
                                               rejection_reason=str(error)))

    def reconcile(self, key):
        record = self.store.get(key)
        result = self.broker.lookup(order_id=record['broker_order_id']) if record['broker_order_id'] else self.broker.lookup(reference_id=record['request_id'])
        if result.get('asset', {}).get('instrumentId') != record['instrument_id']:
            raise BrokerError('Broker response instrument mismatch.')
        if record['broker_order_id'] is not None and result.get('orderId') != record['broker_order_id']:
            raise BrokerError('Broker response order identity mismatch.')
        status = result.get('status', {})
        states = {1: 'PENDING', 2: 'PENDING', 3: 'FILLED', 4: 'REJECTED', 5: 'PARTIAL',
                  6: 'PENDING', 7: 'CANCELLED', 8: 'EXPIRED', 9: 'PARTIAL',
                  10: 'PARTIAL', 11: 'PENDING', 12: 'PENDING'}
        changes = dict(broker_order_id=result.get('orderId'), broker_status=states.get(status.get('id'), 'UNKNOWN'),
                       broker_status_detail=status, total_costs=result.get('totalCosts'),
                       rejection_reason=status.get('errorMessage') if status.get('id') in (4, 10) else None,
                       cancellation_reason=(status.get('errorMessage') or status.get('name'))
                           if status.get('id') in (7, 8, 9) else None)
        executions = result.get('positionExecutions', [])
        changes['position_ids'] = [p['positionId'] for p in executions]
        opening = [p['openingData'] for p in executions if p.get('openingData')]
        if opening:
            quantity = sum((D(p['units'], positive=True) for p in opening), D(0))
            notional = sum((D(p['units']) * D(p['avgPrice'], positive=True) for p in opening), D(0))
            changes.update(filled_quantity=str(quantity), filled_notional=str(notional), fill_price=str(notional / quantity),
                           filled_at=max(p['executionTime'] for p in opening),
                           fees=str(sum((D(p['fees']) for p in opening), D(0)))
                               if all(p.get('fees') is not None for p in opening) else None,
                           actual_stops=[p.get('stopLossRate') for p in executions],
                           actual_targets=[p.get('takeProfitRate') for p in executions])
            asset = result.get('asset', {})
            if asset.get('settlementType', '').lower() != 'real' or asset.get('leverage') != 1:
                changes.update(broker_status='UNKNOWN', execution_review_reason=
                    'Filled settlement/leverage differs from required underlying X1; review directly in eToro.')
        return self.store.update(key, self.client.clean(changes))

    def close(self, key, *, confirmed=False):
        """Close one tracked, fully filled position; never convert SELL into a short."""
        if confirmed is not True or self.client.config.mode != 'demo':
            raise BrokerError('Explicit manual DEMO close confirmation is required.')
        record = self.store.get(key)
        if record.get('close_request_id'):
            return record
        record = self.reconcile(key)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = json.loads(db.execute('SELECT payload FROM executions WHERE intent_key=?', (key,)).fetchone()[0])
            if record.get('close_request_id'):
                return record
            if record['broker_status'] != 'FILLED' or len(record['position_ids']) != 1:
                raise BrokerError('V1 close requires one fully filled tracked position.')
            position_id = record['position_ids'][0]
            if any(type(value) is not int or value <= 0 for value in (position_id, record['instrument_id'])):
                raise BrokerError('Valid tracked demo position and instrument IDs are required.')
            positions = self.broker.positions()
            matches = [p for p in positions if p.get('positionId') == position_id]
            position = matches[0] if len(matches) == 1 else None
            if not position or position.get('isBuy') is not True or position.get('leverage') != 1:
                raise BrokerError('Tracked long X1 position is not open.')
            if (type(position.get('positionId')) is not int or type(position.get('instrumentId')) is not int
                    or position.get('instrumentId') != record['instrument_id']
                    or D(position['units'], positive=True) != D(record['filled_quantity'], positive=True)):
                raise BrokerError('Position changed; review in eToro before closing.')
            stamp = now()
            # Closing verified existing exposure is not an entry decision. The
            # position-specific full-close route cannot open/reverse a short;
            # its execution price is learned through reconciliation, not a quote.
            record.update(close_request_id=str(uuid4()), close_submitted_at=stamp.isoformat(),
                          close_status='INTENDED', close_intended_side='SELL', close_reference=None,
                          close_position_id=position_id, close_instrument_id=record['instrument_id'],
                          close_intended_quantity=str(D(position['units'], positive=True)))
            db.execute('UPDATE executions SET payload=? WHERE intent_key=?', (encode(record), key))
            db.execute('INSERT INTO execution_events(intent_key,payload) VALUES (?,?)', (key, encode(record)))
        try:
            response = self.broker.close_position(position_id, record['instrument_id'],
                request_id=record['close_request_id'], confirmed=confirmed)
            order_id = response.get('orderForClose', {}).get('orderID')
            if not order_id:
                raise BrokerError('Close response missing ID; verify in eToro. Do not resubmit.', uncertain=True)
            return self.store.update(key, dict(close_order_id=order_id, close_status='SUBMITTED'))
        except BrokerError as error:
            return self.store.update(key, dict(close_status='UNKNOWN' if error.uncertain else 'REJECTED',
                                               close_error=str(error)))

    def reconcile_close(self, key):
        record = self.store.get(key)
        if not record.get('close_order_id'):
            raise BrokerError('No close order ID available; inspect eToro manually. Automatic resubmission is disabled.')
        response = self.broker.lookup_close(record['close_order_id'])
        if response.get('instrumentID') != record['instrument_id'] or response.get('orderID') != record['close_order_id']:
            raise BrokerError('Close order identity mismatch.')
        status = response.get('statusID')
        changes = dict(close_status={3: 'FILLED', 4: 'REJECTED', 7: 'CANCELLED', 8: 'EXPIRED',
                                     9: 'PARTIAL', 10: 'PARTIAL'}.get(status, 'PENDING'),
                       close_error=response.get('errorMessage'))
        rows = [p for p in response.get('positions', []) if p.get('occurred') and p.get('rate') is not None]
        if any(p.get('positionID') not in record['position_ids'] for p in rows):
            raise BrokerError('Unexpected position in close execution.')
        quantity = sum((D(p['units'], positive=True) for p in rows), D(0))
        if rows:
            proceeds = sum((D(p['units']) * D(p['rate'], positive=True) for p in rows), D(0))
            changes.update(closed_quantity=str(quantity), exit_price=str(proceeds / quantity),
                           close_executions=rows)
            if status == 3 and quantity == D(record['filled_quantity']):
                changes.update(closed_at=max(p['occurred'] for p in rows),
                               realized_pnl=str(proceeds - D(record['filled_notional'])), pnl_basis='gross, before fees')
        return self.store.update(key, self.client.clean(changes))


def compare(paper, broker):
    result = dict(paper_trade_id=paper['trade_id'], broker_order_id=broker.get('broker_order_id'))
    for name, left, right in [('entry_difference', paper.get('fill_price'), broker.get('fill_price')),
                              ('quantity_difference', paper.get('quantity'), broker.get('filled_quantity'))]:
        result[name] = str(D(right) - D(left)) if left is not None and right is not None else None
    result['timing_difference_seconds'] = ((datetime.fromisoformat(broker['filled_at'].replace('Z', '+00:00')) -
        datetime.fromisoformat(paper['filled_at'].replace('Z', '+00:00'))).total_seconds()
        if paper.get('filled_at') and broker.get('filled_at') else None)
    for name, field in [('stop', 'stop_loss'), ('target', 'take_profit')]:
        result[name + '_differences'] = [str(D(v) - D(paper[field])) if v is not None else None
                                         for v in broker.get('actual_' + name + 's', [])]
    result['realized_pnl_difference'] = (str(D(broker['realized_pnl']) - D(paper['realized_pnl']))
        if paper.get('status') == 'CLOSED' and broker.get('closed_at') and broker.get('realized_pnl') is not None else None)
    return result
