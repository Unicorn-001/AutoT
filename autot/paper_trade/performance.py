"""Read-only forward journal. Decimal arithmetic; no FX or execution decisions."""

import json

from autot.paper_trade.sessions import utc
from autot.utils.financial_validation import decimal_value as D


def actual_fill_rr(trade):
    if trade.get('status') not in ('OPEN', 'CLOSED') or not trade.get('filled_at'):
        return None
    try:
        fill, stop, target = (D(trade.get(k)) for k in ('fill_price', 'stop_loss', 'take_profit'))
        if trade.get('side') == 'BUY':
            risk, reward = fill - stop, target - fill
        elif trade.get('side') == 'SELL':
            risk, reward = stop - fill, fill - target
        else:
            return None
        return reward / risk if risk > 0 and reward >= 0 else None
    except ValueError:
        return None


def excursions(trade, events):
    """Known in-position extrema, excluding unknown post-exit bar movement.

    Whole OHLC is valid for bars held through close. On an exit bar only OPEN
    and the execution price are known in-position; intrabar exits are lower
    bounds, never claimed tick-accurate extrema.
    """
    unavailable = dict(mfe=None, mae=None, mfe_percent=None, mae_percent=None,
                       excursion_note='Unavailable: no complete durable bar evidence')
    if not any(e['event_type'] == 'ENTRY_FILLED' for e in events):
        if any(e['event_type'] == 'AUDIT_BASELINE_CREATED' for e in events):
            unavailable['excursion_note'] = 'Unavailable for pre-audit trade'
        return unavailable
    bars = [e for e in events if e['event_type'] == 'POSITION_CHECKED']
    if not bars or bars[0]['bar_time'] != trade['filled_at'] or bars[-1]['bar_time'] != trade['last_checked_at']:
        return unavailable
    fill = D(trade['fill_price'])
    high = low = fill
    bounded = False
    for bar in bars:
        if bar['status_after'] == 'CLOSED':
            # Gaps/manual closes occur at OPEN. Level touches have unknown order
            # relative to the bar's other extreme, so retain only known prices.
            values = (D(bar['bar_open']), D(bar['price']))
            state = json.loads(bar['payload_json'])
            bounded = state.get('exit_reason') in ('STOP', 'TARGET')
        else:
            values = (D(bar['bar_high']), D(bar['bar_low']))
        high, low = max(high, *values), min(low, *values)
    mfe, mae = (high - fill, fill - low) if trade['side'] == 'BUY' else (fill - low, high - fill)
    return dict(mfe=mfe, mae=mae, mfe_percent=mfe / fill * 100, mae_percent=mae / fill * 100,
                excursion_note='Known movement lower bound; exit-bar order unknown' if bounded
                else 'Completed in-position bars; exit-at-open movement only')


def journal_entry(trade, events):
    t = trade
    filled = t['fill_price'] is not None
    closed = t['status'] == 'CLOSED'
    fill = D(t['fill_price']) if filled else None
    signal = D(t['signal_price'])
    slippage = ((fill - signal) if t['side'] == 'BUY' else (signal - fill)) / signal * 100 if filled else None
    holding = None
    if closed:
        delta = utc(t['closed_at']) - utc(t['filled_at'])
        holding = D(delta.days * 86400 + delta.seconds) + D(delta.microseconds) / 1000000
    pnl = D(t['realized_pnl']) if closed else D(t['unrealized_pnl']) if filled else None
    return dict(trade=t, trade_id=t['trade_id'], currency=t['currency'], pnl=pnl,
                outcome=('PROFIT' if pnl > 0 else 'LOSS' if pnl < 0 else 'BREAKEVEN') if closed else t['status'],
                return_percent=pnl / (fill * t['quantity']) * 100 if filled else None,
                signal_rr=D(t['risk_reward_ratio']), actual_rr=actual_fill_rr(t),
                entry_slippage_percent=slippage, holding_seconds=holding, **excursions(t, events))


def average(values):
    values = [v for v in values if v is not None]
    return sum(values, D(0)) / len(values) if values else None


def summarize(entries):
    groups = {}
    for entry in entries:
        groups.setdefault(entry['currency'], []).append(entry)
    result = {}
    for currency, rows in groups.items():
        closed = [r for r in rows if r['trade']['status'] == 'CLOSED']
        wins = [r['pnl'] for r in closed if r['pnl'] > 0]
        losses = [r['pnl'] for r in closed if r['pnl'] < 0]
        profit, loss = sum(wins, D(0)), sum(losses, D(0))
        result[currency] = dict(
            completed_trades=len(closed), winners=len(wins), losers=len(losses),
            breakeven=len(closed) - len(wins) - len(losses),
            win_rate=D(len(wins)) / len(closed) * 100 if closed else None,
            gross_profit=profit, gross_loss=loss, net_realized_pnl=profit + loss,
            average_win=average(wins), average_loss=average(losses),
            profit_factor=profit / abs(loss) if loss else None,
            profit_factor_note='No losing trades' if not loss else None,
            average_return_percent=average(r['return_percent'] for r in closed),
            best_trade=max(closed, key=lambda r: r['pnl']) if closed else None,
            worst_trade=min(closed, key=lambda r: r['pnl']) if closed else None,
            average_holding_seconds=average(r['holding_seconds'] for r in closed),
            average_signal_rr=average(r['signal_rr'] for r in closed),
            average_actual_rr=average(r['actual_rr'] for r in closed),
            average_entry_slippage_percent=average(r['entry_slippage_percent'] for r in closed))
    return result


class PerformanceService:
    def __init__(self, ledger):
        self.ledger = ledger

    def report(self, *, mode='FORWARD_TEST', filters=None, group_by=None):
        allowed = {'strategy_profile_id', 'strategy_profile_name', 'strategy_profile_version',
                   'strategy_config_hash', 'mode', 'market', 'index_name', 'side', 'market_regime',
                   'configuration_source'}
        if mode not in ('FORWARD_TEST', 'RESEARCH', 'PRE_SETTINGS_BASELINE', 'ALL'):
            raise ValueError('Invalid performance mode.')
        if set(filters or {}) - allowed or (group_by is not None and group_by not in allowed):
            raise ValueError('Unsupported performance segmentation field.')
        # One read snapshot prevents a concurrent monitor separating fills/evidence.
        with self.ledger.connection() as db:
            db.execute('BEGIN')
            trades = [self.ledger.decode(r) for r in db.execute('SELECT * FROM trades ORDER BY rowid')]
            events = {}
            for row in db.execute('SELECT * FROM paper_trade_events ORDER BY event_id'):
                events.setdefault(row['trade_id'], []).append(dict(row))
        if mode == 'FORWARD_TEST':
            trades = [t for t in trades if t.get('mode') in (None, 'FORWARD_TEST')]
        elif mode == 'PRE_SETTINGS_BASELINE':
            trades = [t for t in trades if t.get('configuration_source') == 'PRE_SETTINGS_BASELINE']
        elif mode != 'ALL':
            trades = [t for t in trades if t.get('mode') == mode]
        trades = [t for t in trades if all(t.get(k) == v for k, v in (filters or {}).items())]
        journal = [journal_entry(t, events.get(t['trade_id'], [])) for t in trades]
        groups = {}
        if group_by:
            for entry in journal:
                groups.setdefault(entry['trade'].get(group_by), []).append(entry)
        segments = {key: summarize(rows) for key, rows in groups.items()}
        result = dict(journal=journal, performance=summarize(journal), events=events)
        if group_by:
            result["segments"] = segments
        return result
