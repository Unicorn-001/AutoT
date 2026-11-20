"""Offline execution-only risk checks; never touch the operator's ledger/settings."""
import json
from decimal import Decimal as D

import pytest

from autot.notifications import project, message
from autot.paper_trade.fill_risk import recheck
from autot.paper_trade.ledger import Ledger
from tests.test_settings import changed
from tests.test_settings_paper import environment, create
from tests.test_prospective_paper import OPEN, BAR, bar


def prepare(environment, side='BUY', **risk):
    store, service, provider, now = environment
    state = store.save(changed(risk={'risk_per_trade_percent': .5, **risk}), expected_version=0)
    return create(service, state, side=side)


def check(environment, trade, fill, others=()):
    ledger = environment[1].ledger
    return recheck(trade, fill, [trade, *others], ledger.summaries()['USD'],
                   checked_at=(OPEN+BAR).isoformat(), fill_time=OPEN.isoformat())


@pytest.mark.parametrize('side,prices', [('BUY', [100, 99, 102, 200, 95]),
                                        ('SELL', [100, 101, 98, 1, 105])])
@pytest.mark.parametrize('index,decision,reason,qty', [
    (0, 'ACCEPT', 'WITHIN_RISK', 10), (1, 'ACCEPT', 'WITHIN_RISK', 10),
    (2, 'RESIZE', 'GAP_INCREASED_RISK', 7),
    (3, 'REJECT', 'MINIMUM_QUANTITY_NOT_POSSIBLE', 0),
    (4, 'REJECT', 'INVALID_STOP_RELATIVE_TO_FILL', 0)])
def test_buy_sell_decisions_and_atomic_persistence(environment, side, prices, index, decision, reason, qty):
    t = prepare(environment, side)
    _, service, provider, now = environment
    with service.ledger.connection() as db:
        original = db.execute('SELECT snapshot FROM trades').fetchone()[0]
    price = prices[index]
    provider.bars = [bar(price, price, price, price)]
    now[0] = OPEN + BAR
    result = service.update_positions(source='SCHEDULED')[0]
    audit = result['fill_time_risk_check']
    assert (audit['decision'], audit['reason'], audit['approved_quantity']) == (decision, reason, qty)
    assert audit['planned_quantity'] == 10 and D(audit['planned_total_risk']) == 50
    assert audit['rechecked_at'] and audit['fill_time'] == OPEN.isoformat()
    assert result['stop_loss'] == t['stop_loss'] and result['take_profit'] == t['take_profit']
    assert Ledger(service.ledger.path).get(t['trade_id']) == result
    with service.ledger.connection() as db:
        assert db.execute('SELECT snapshot FROM trades').fetchone()[0] == original
    if decision == 'REJECT':
        assert result['status'] == 'CANCELLED' and result['fill_price'] is None
        assert result['realized_pnl'] == result['unrealized_pnl'] == '0'
        assert service.ledger.summaries()['USD']['reserved'] == 0
        from autot.paper_trade.performance import journal_entry
        assert journal_entry(result, service.ledger.events(t['trade_id']))['outcome'] == 'CANCELLED'
        assert not any(e['event_type'] == 'ENTRY_FILLED' for e in service.ledger.events(t['trade_id']))
    else:
        assert result['quantity'] == qty and D(audit['approved_total_risk']) <= 50
        assert service.ledger.summaries()['USD']['reserved'] == price*qty
    events = service.ledger.events(t['trade_id'])
    assert any(json.loads(e['payload_json']).get('fill_time_risk_check') == audit for e in events)
    assert service.update_positions()[0:1] == ([result] if result['status'] == 'OPEN' else [])
    project(service.ledger)
    project(service.ledger)
    with service.ledger.connection() as db:
        notices = [dict(r) for r in db.execute("SELECT * FROM notification_outbox WHERE event_type LIKE 'PAPER_FILL_RISK_%'")]
    assert len(notices) == int(decision != 'ACCEPT')
    if notices:
        assert reason in message(notices[0])


@pytest.mark.parametrize('percent,qty', [(.25, 3), (.5, 7), (1, 14)])
def test_configured_risk_allowance(environment, percent, qty):
    t = prepare(environment, risk_per_trade_percent=percent)
    result = check(environment, t, 102)
    assert result['approved_quantity'] == qty
    assert D(result['risk_allowance']) == D(str(percent))*100


@pytest.mark.parametrize('field,value', [('stop_loss', None), ('stop_loss', 'NaN'),
    ('stop_loss', 'Infinity'), ('signal_price', None), ('quantity', 0), ('quantity', -1),
    ('quantity', 1.5), ('quantity', True), ('side', 'INVALID')])
def test_invalid_data(environment, field, value):
    t = prepare(environment)
    t[field] = value
    assert check(environment, t, 100)['reason'] == 'INVALID_EXECUTION_DATA'


@pytest.mark.parametrize('fill', [None, 'NaN', 'Infinity', '-Infinity', 0, -1, True])
def test_invalid_fill(environment, fill):
    assert check(environment, prepare(environment), fill)['reason'] == 'INVALID_EXECUTION_DATA'


@pytest.mark.parametrize('risk,reason', [
    ({'enforce_positions_limit': True, 'maximum_simultaneous_positions': 1}, 'POSITION_LIMIT'),
    ({'enforce_daily_trade_limit': True, 'maximum_new_trades_per_day': 1}, 'DAILY_TRADE_LIMIT'),
    ({'enforce_portfolio_risk_limit': True, 'maximum_total_portfolio_risk_percent': .5}, 'PORTFOLIO_RISK_LIMIT')])
def test_existing_portfolio_limits_and_self_exclusion(environment, risk, reason):
    t = prepare(environment, **risk)
    assert check(environment, t, 100)['decision'] == 'ACCEPT'
    other = dict(t, trade_id='other', status='OPEN', fill_price='101')
    assert check(environment, t, 100, [other])['reason'] == reason


def test_portfolio_uses_filled_risk_not_reference_risk(environment):
    t = prepare(environment, enforce_portfolio_risk_limit=True, maximum_total_portfolio_risk_percent=1)
    other = dict(t, trade_id='historical-open', status='OPEN', fill_price='102')
    assert check(environment, t, 100, [other])['reason'] == 'PORTFOLIO_RISK_LIMIT'


def test_capital_and_position_notional_limits(environment):
    t = prepare(environment, enforce_position_limit=True, maximum_position_percent=10)
    # Small adverse gap keeps qty 10 only with a lower quantity original plan.
    t['quantity'] = 9
    assert check(environment, t, 111)['decision'] == 'RESIZE'
    t['stop_loss'] = '100.5'
    t['signal_price'] = '101'
    t['quantity'] = 10
    assert check(environment, t, 102)['reason'] == 'POSITION_LIMIT'
    t['configuration_source'] = 'PRE_SETTINGS_BASELINE'
    t['quantity'] = 10000
    t['signal_price'] = '100'
    t['stop_loss'] = '99.999'
    # Explicit summary of a nearly fully reserved account, including own reservation.
    summary = dict(currency='USD', capital='10000', realized_pnl='0', unrealized_pnl='0',
                   reserved='10000', available='0')
    t['quantity'] = 10
    result = recheck(t, '100.001', [t], summary, checked_at=OPEN.isoformat(), fill_time=OPEN.isoformat())
    assert result['reason'] == 'INSUFFICIENT_CAPITAL'


def test_legacy_rows_not_rewritten_or_rechecked(environment):
    t = prepare(environment)
    ledger = environment[1].ledger
    # Simulate a pre-feature filled trade; opening it again must not recheck risk.
    with ledger.connection() as db:
        row = db.execute('SELECT * FROM trades').fetchone()
        state = json.loads(row['state'])
        state.pop('fill_time_risk_check', None)
        state.update(status='CLOSED', fill_price='102', filled_at=OPEN.isoformat(),
                     exit_price='95', closed_at=(OPEN+BAR).isoformat(), realized_pnl='-70')
        db.execute('UPDATE trades SET state=?', (json.dumps(state),))
    with ledger.connection() as db:
        before = tuple(db.execute('SELECT snapshot,state,revision FROM trades').fetchone())
    reopened = Ledger(ledger.path)
    historical = reopened.get(t['trade_id'])
    assert historical['fill_time_risk_check'] is None
    assert historical['quantity'] == 10 and historical['realized_pnl'] == '-70'
    assert environment[1].update_positions() == []
    with reopened.connection() as db:
        assert tuple(db.execute('SELECT snapshot,state,revision FROM trades').fetchone()) == before


def test_resized_quantity_drives_later_pnl_and_audit(environment):
    t = prepare(environment)
    _, service, provider, now = environment
    provider.bars = [bar(102, 104, 100, 103)]
    now[0] = OPEN+BAR
    result = service.update_positions()[0]
    assert result['quantity'] == 7 and result['unrealized_pnl'] == '7'
    provider.bars = [bar(103, 104, 94, 96, OPEN+BAR)]
    now[0] += BAR
    result = service.update_positions()[0]
    assert result['realized_pnl'] == '-49' and result['status'] == 'CLOSED'
    assert all(e['quantity'] == 7 for e in service.ledger.events(t['trade_id']) if e['event_type'] == 'TRADE_CLOSED')
