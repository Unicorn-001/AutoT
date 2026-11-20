"""Admission policy at real transaction boundaries; offline isolated ledgers only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier

import pytest
from pydantic import ValidationError

from autot.paper_trade.ledger import Ledger
from autot.paper_trade.service import build_snapshot, initial_state, PaperTradingService
from autot.paper_trade.sessions import utc
from autot.portfolio_risk.models import PortfolioRiskDecision, PortfolioRiskRejected
from autot.settings.models import TradeSettingsSnapshot
from autot.utils.financial_validation import decimal_value as D
from tests.test_settings import changed
from tests.test_settings_paper import environment, create
from tests.test_prospective_paper import opportunity, CREATED, OPEN, BAR, bar


def context(state, **changes):
    result = dict(market='US', index_name='S&P 500', signal_time=CREATED-timedelta(hours=1),
                  timeframe='1d', quote_currency='USD', capital=10000,
                  risk_percent=state.settings.risk.risk_per_trade_percent, metadata={})
    result.update(changes)
    return result


def preview(service, state, row=None, **changes):
    return service.preview_admission(row or opportunity(), settings_state=state, **context(state, **changes))


def dump(ledger, *, include_rejections=True):
    with ledger.connection() as db:
        return [line for line in db.iterdump() if include_rejections or not line.startswith('INSERT INTO "paper_trade_rejections"')]


def test_preview_and_exposure_are_read_only_and_result_is_validated(environment):
    store, service, _, _ = environment
    before = dump(service.ledger)
    decision = preview(service, store.load())
    assert isinstance(decision, PortfolioRiskDecision)
    assert decision.allowed and decision.decision == 'ALLOW' and decision.reasons
    assert decision.account_capital == decision.available_capital == 10000
    assert decision.proposed_position_value == decision.post_trade_reserved_notional == 2000
    assert decision.proposed_trade_risk == decision.proposed_total_open_risk == 100
    assert decision.proposed_position_percent == 20 and decision.proposed_trade_risk_percent == 1
    assert decision.remaining_position_slots is None
    assert decision.settings_snapshot.strategy_config_hash == store.load().profile.configuration_hash
    assert PortfolioRiskDecision.model_validate_json(decision.model_dump_json()) == decision
    assert service.ledger.portfolio_exposures(store.load(), when=CREATED) == []
    assert dump(service.ledger) == before
    with pytest.raises(ValidationError):
        PortfolioRiskDecision.model_validate(dict(decision.model_dump(), decision='REJECT'))


@pytest.mark.parametrize('limit,allowed', [(30, True), (29.999, False)])
def test_position_limit_exact_boundary_and_no_resize(environment, limit, allowed):
    store, service, _, _ = environment
    state = store.save(changed(risk={'risk_per_trade_percent': 1.5, 'enforce_position_limit': True,
                                    'maximum_position_percent': limit}), expected_version=0)
    decision = preview(service, state)
    assert decision.allowed == allowed
    assert decision.proposed_position_value == 3000
    before = dump(service.ledger, include_rejections=False)
    if allowed:
        trade = create(service, state)
        assert trade['quantity'] == 30
    else:
        with pytest.raises(PortfolioRiskRejected, match='maximum position percent') as error:
            create(service, state)
        assert error.value.result == decision
        assert dump(service.ledger, include_rejections=False) == before


def test_4995_position_rejected_with_30_percent_limit(environment):
    store, service, _, _ = environment
    state = store.save(changed(risk={'enforce_position_limit': True}), expected_version=0)
    row = dict(opportunity(), entry_price='99.9', stop_loss='97.902', take_profit='103.896')
    result = preview(service, state, row)
    assert result.proposed_position_value == 4995 and not result.allowed
    assert result.proposed_position_percent == D('49.95')


def test_all_reasons_returned_and_rejection_rolls_back_account_creation(environment):
    store, service, _, _ = environment
    state = store.save(changed(risk={'allow_buy': False, 'minimum_risk_reward': 3,
                                    'enforce_position_limit': True, 'maximum_position_percent': 10}), expected_version=0)
    before = dump(service.ledger, include_rejections=False)
    with pytest.raises(PortfolioRiskRejected) as error:
        create(service, state)
    assert len(error.value.result.reasons) == 3
    assert dump(service.ledger, include_rejections=False) == before


@pytest.mark.parametrize('side,control', [('BUY', 'allow_buy'), ('SELL', 'allow_sell')])
def test_direction_and_planned_rr_do_not_use_reported_or_fill_ratio(environment, side, control):
    store, service, _, _ = environment
    state = store.save(changed(risk={control: False, 'minimum_risk_reward': 2.1}), expected_version=0)
    row = dict(opportunity(side), risk_reward_ratio=999)
    result = preview(service, state, row)
    assert not result.allowed and len(result.reasons) == 2
    assert result.planned_risk_reward == 2


def test_pending_count_and_cancel_release_but_count_daily_creation(environment):
    store, service, _, _ = environment
    state = store.save(changed(risk={'enforce_positions_limit': True, 'maximum_simultaneous_positions': 1}), expected_version=0)
    first = create(service, state)
    result = preview(service, state)
    assert not result.allowed and result.current_open_positions == result.pending_positions == 1
    assert result.remaining_position_slots == 0
    service.cancel(first['trade_id'])
    result = preview(service, state)
    assert result.allowed and result.current_open_positions == 0
    assert result.current_open_risk == result.existing_reserved_notional == 0
    assert result.new_trades_today == 1


def test_five_pending_positions_exhaust_slots_without_exhausting_capital(environment):
    store, service, _, _ = environment
    state = store.save(changed(risk={'risk_per_trade_percent': .5, 'enforce_positions_limit': True}), expected_version=0)
    for i in range(5):
        create(service, state, key=str(i), symbol=f'AAA{i}')
    result = preview(service, state)
    assert not result.allowed and result.current_open_positions == 5 and result.available_capital == 5000


def test_portfolio_risk_boundary_and_shared_modes(environment):
    store, service, _, _ = environment
    forward = store.save(changed(risk={'enforce_portfolio_risk_limit': True,
                                      'maximum_total_portfolio_risk_percent': 2}), expected_version=0)
    create(service, forward)
    research = store.save(changed(forward.settings, general={'mode': 'RESEARCH'}), expected_version=1)
    result = preview(service, research)
    assert result.allowed and result.proposed_total_open_risk == result.maximum_total_portfolio_risk == 200
    create(service, research, key='research')
    result = preview(service, forward)
    assert not result.allowed and result.proposed_total_open_risk == 300
    assert result.current_open_positions == 2 and result.existing_reserved_notional == 4000


@pytest.mark.parametrize('market,currency,symbol,unit,value', [
    ('US','USD','AAPL','USD',2000), ('UK','GBP','AZN.L','GBp',2000), ('IN','INR','M&M.NS','INR',2000),
])
def test_currency_and_quote_units_are_independent(environment, market, currency, symbol, unit, value):
    store, service, _, _ = environment
    for i in range(5):
        create(service, store.load(), key=str(i), symbol=f'AAA{i}')
    result = preview(service, store.load(), opportunity(symbol=symbol), market=market, quote_currency=unit)
    assert result.currency == currency and result.proposed_position_value == value
    assert result.available_capital == (0 if market == 'US' else 10000)
    assert result.allowed == (market != 'US')
    research = store.save(changed(general={'mode':'RESEARCH'}), expected_version=0)
    assert not preview(service, research).allowed


def test_planned_risk_and_gap_risk_are_distinct_and_never_use_current_settings(environment):
    store, service, provider, now = environment
    first = create(service, store.load())
    provider.bars = [bar(102, 104, 100, 103)]
    now[0] = OPEN + BAR
    service.update_positions()
    state = store.save(changed(risk={'risk_per_trade_percent': .5, 'enforce_portfolio_risk_limit': True,
                                    'maximum_total_portfolio_risk_percent': 1.5}), expected_version=0)
    result = preview(service, state)
    assert result.current_open_risk == 70 and result.fill_adjusted_open_risk == 98
    assert result.fill_risk_difference == 28 and result.warnings
    assert result.proposed_total_open_risk == 120 and result.allowed
    assert result.current_open_positions == result.open_positions == 1
    assert result.existing_reserved_notional == result.largest_position == 1428
    assert result.available_capital == 8572
    assert service.ledger.get(first['trade_id'])['portfolio_risk_decision']['proposed_trade_risk'] == '100'


def test_realized_equity_available_and_base_capital_limits(environment):
    store, service, provider, now = environment
    create(service, store.load())
    provider.bars = [bar(h=112)]
    now[0] = OPEN + BAR
    service.update_positions()
    result = preview(service, store.load())
    assert result.account_equity == result.available_capital == 10200
    assert result.account_capital == 10000 and result.proposed_position_percent == 20
    assert result.current_open_positions == result.current_open_risk == 0
    assert result.maximum_total_portfolio_risk == 250


@pytest.mark.parametrize('field,value', [('quantity',21), ('risk_amount','99'), ('risk_per_share','6'),
                                        ('intended_position_value','1999')])
def test_tampered_sizing_rejected_at_ledger_boundary(environment, field, value):
    store, service, _, _ = environment
    state=store.load()
    snapshot = build_snapshot(opportunity(), **context(state), created_at=CREATED, calendar=service.calendar)
    snapshot.update(TradeSettingsSnapshot.from_state(state).model_dump(mode='json'))
    snapshot[field] = value
    before = dump(service.ledger, include_rejections=False)
    with pytest.raises(PortfolioRiskRejected, match='sizing engine'):
        service.ledger.confirm('bad',snapshot, initial_state())
    assert dump(service.ledger, include_rejections=False) == before


def test_new_service_trade_cannot_override_active_profile_risk(environment):
    store, service, _, _ = environment
    store.save(changed(risk={'risk_per_trade_percent': .5}),expected_version=0)
    with pytest.raises(PortfolioRiskRejected, match='risk_per_trade_percent'):
        service.confirm('bad',opportunity(), **context(store.load(),risk_percent=1))
    assert not service.ledger.all()


def test_subcent_stop_risk_preserves_existing_calculator_precision(environment):
    store, service, _, _ = environment
    row = dict(opportunity(), entry_price='1.001', stop_loss='1.0009', take_profit='1.0012')
    result = preview(service, store.load(), row)
    assert result.allowed and result.proposed_trade_risk == D('0.9990')
    assert result.proposed_position_value == D('9999.990')


@pytest.mark.parametrize('first,second,third,market,currency,symbol', [
    ('2026-07-07T02:00:00Z','2026-07-07T03:59:59Z','2026-07-07T04:00:00Z','US','USD','AAPL'),
    ('2026-12-07T03:00:00Z','2026-12-07T04:59:59Z','2026-12-07T05:00:00Z','US','USD','AAPL'),
    ('2026-07-06T21:00:00Z','2026-07-06T22:59:59Z','2026-07-06T23:00:00Z','UK','GBP','AZN.L'),
    ('2026-07-06T17:00:00Z','2026-07-06T18:29:59Z','2026-07-06T18:30:00Z','IN','INR','M&M.NS'),
])
def test_local_midnight_and_dst_reset_daily_count(environment, first, second, third, market, currency, symbol):
    store, service, _, now = environment
    state=store.save(changed(risk={'enforce_daily_trade_limit':True,'maximum_new_trades_per_day':1}), expected_version=0)
    now[0]=utc(first)
    kwargs=dict(market=market, quote_currency=currency, signal_time=utc(first)-timedelta(hours=1))
    trade=create(service,state,symbol=symbol,**kwargs)
    service.cancel(trade['trade_id'])
    now[0]=utc(second)
    result=preview(service,state,opportunity(symbol=symbol),**kwargs)
    assert not result.allowed and result.new_trades_today == 1
    now[0]=utc(third)
    result=preview(service,state,opportunity(symbol=symbol),**kwargs)
    assert result.allowed and result.new_trades_today == 0


def test_daily_counts_are_mode_specific_but_reservations_shared(environment):
    store, service, _, _ = environment
    state=store.save(changed(risk={'enforce_daily_trade_limit':True,'maximum_new_trades_per_day':1}), expected_version=0)
    first=create(service,state)
    research=store.save(changed(state.settings,general={'mode':'RESEARCH'}),expected_version=1)
    result=preview(service,research)
    assert result.allowed and result.new_trades_today == 0 and result.current_open_positions == 1
    second=create(service,research,key='research')
    assert second['opportunity_id'] != first['opportunity_id']
    assert not preview(service,state).allowed and not preview(service,research).allowed


@pytest.mark.parametrize('risk', [
    {'enforce_positions_limit':True,'maximum_simultaneous_positions':1},
    {'enforce_portfolio_risk_limit':True,'maximum_total_portfolio_risk_percent':1},
    {'enforce_daily_trade_limit':True,'maximum_new_trades_per_day':1},
])
def test_concurrent_confirmations_recheck_inside_transaction(environment, risk):
    store, service, _, _ = environment
    state=store.save(changed(risk=risk),expected_version=0)
    assert preview(service,state).allowed
    gate=Barrier(4)
    def submit(i):
        gate.wait()
        try:
            return create(service,state,key=str(i),symbol=f'AAA{i}')
        except PortfolioRiskRejected as error:
            return error.result
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(submit,range(4)))
    assert sum(isinstance(r,dict) for r in results) == 1
    assert len(service.ledger.all()) == 1
    assert len(service.ledger.rejections()) == 3
    assert all(r.decision == 'REJECT' for r in results if isinstance(r,PortfolioRiskDecision))
    assert service.ledger.summaries()['USD']['reserved'] == 2000


def test_preview_goes_stale_and_existing_confirmation_is_idempotent(environment):
    store, service, _, _ = environment
    state=store.save(changed(risk={'enforce_positions_limit':True,'maximum_simultaneous_positions':1}),expected_version=0)
    assert preview(service,state).allowed
    first=create(service,state)
    with pytest.raises(PortfolioRiskRejected):
        create(service,state,key='two',symbol='MSFT')
    before=dump(service.ledger)
    assert create(service,state) == first
    assert create(service,state,key='fresh-review') == first
    assert dump(service.ledger) == before


def test_accepted_decision_is_immutable_history_across_profile_and_execution_updates(environment):
    store, service, provider, now = environment
    state=store.load()
    trade=create(service,state)
    recorded=deepcopy(trade['portfolio_risk_decision'])
    store.save(changed(risk={'risk_per_trade_percent':.5}),expected_version=0)
    provider.bars=[bar(h=112)]
    now[0]=OPEN+BAR
    service.update_positions()
    restarted=Ledger(service.ledger.path).get(trade['trade_id'])
    assert restarted['portfolio_risk_decision'] == recorded
    assert recorded['settings_snapshot']['strategy_config_hash'] == state.profile.configuration_hash


def test_pre_settings_records_stay_unknown_and_are_counted_conservatively(environment):
    store, service, _, _ = environment
    snapshot=build_snapshot(opportunity(),**context(store.load()),created_at=CREATED,calendar=service.calendar)
    first=service.ledger.confirm('legacy',snapshot,initial_state())
    before=dump(service.ledger)
    result=preview(service,store.load())
    assert result.new_trades_today == 1 and result.current_open_risk == 100 and result.warnings
    assert 'mode' not in first and 'portfolio_risk_decision' not in first
    assert dump(service.ledger) == before


def test_concurrent_capital_reservations_cannot_overbook(environment):
    store, service, _, _ = environment
    state=store.load()
    gate=Barrier(6)
    def submit(i):
        gate.wait()
        try:
            return create(service,state,key=str(i),symbol=f'AAA{i}')
        except PortfolioRiskRejected as error:
            return error.result
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(submit,range(6)))
    assert sum(isinstance(r,dict) for r in results) == 5
    rejection=next(r for r in results if isinstance(r,PortfolioRiskDecision))
    assert len(service.ledger.rejections()) == 1
    assert rejection.available_capital == 0 and any('Insufficient' in s for s in rejection.reasons)
    assert service.ledger.summaries()['USD']['reserved'] == 10000


def test_exact_available_capital_is_allowed(environment):
    store, service, _, _ = environment
    for i in range(4):
        create(service,store.load(),key=str(i),symbol=f'AAA{i}')
    result=preview(service,store.load())
    assert result.allowed and result.available_capital == result.proposed_position_value == 2000


@pytest.mark.parametrize('updates', [{'quantity':0},{'quantity':True},{'signal_price':'NaN'},
                                     {'risk_percent':'Infinity'},{'created_at':'2026-10-12T20:00:00'}])
def test_malformed_proposals_fail_without_mutation(environment, updates):
    store, service, _, _ = environment
    snapshot=build_snapshot(opportunity(),**context(store.load()),created_at=CREATED,calendar=service.calendar)
    snapshot.update(TradeSettingsSnapshot.from_state(store.load()).model_dump(mode='json'))
    snapshot.update(updates)
    before=dump(service.ledger)
    with pytest.raises(ValueError):
        service.ledger.confirm('bad',snapshot,initial_state())
    assert dump(service.ledger) == before


def test_rejection_audit_survives_restart_without_trade_or_trade_events(environment):
    store, service, _, _ = environment
    state = store.save(changed(risk={'allow_buy': False}), expected_version=0)
    before = dump(service.ledger, include_rejections=False)
    with pytest.raises(PortfolioRiskRejected) as caught:
        create(service, state)
    restarted = Ledger(service.ledger.path)
    rows = restarted.rejections()
    assert len(rows) == 1
    row = rows[0]
    assert row.decision == caught.value.result
    assert row.proposal.symbol == 'AAPL' and row.proposal.quantity == 20
    assert row.decision.settings_snapshot.strategy_config_hash == state.profile.configuration_hash
    assert dump(restarted, include_rejections=False) == before
    assert not restarted.all() and not restarted.summaries()


def test_rejection_audit_failure_rolls_back_everything(environment):
    store, service, _, _ = environment
    state = store.save(changed(risk={'allow_buy': False}), expected_version=0)
    with service.ledger.connection() as db:
        db.execute("CREATE TRIGGER fail_rejection BEFORE INSERT ON paper_trade_rejections BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
    before = dump(service.ledger)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match='disk failure'):
        create(service, state)
    assert dump(service.ledger) == before
