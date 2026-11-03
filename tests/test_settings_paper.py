"""Configuration provenance, legacy preservation, risk admission and mode separation."""
from datetime import timedelta
import json
import sqlite3

import pytest
from pydantic import ValidationError

from autot.paper_trade.ledger import Ledger
from autot.paper_trade.service import PaperTradingService, build_snapshot, initial_state
from autot.paper_trade.performance import PerformanceService
from autot.settings.models import SettingsState, TradeSettingsSnapshot
from autot.settings.store import SettingsStore
from tests.test_settings import changed
from tests.test_prospective_paper import opportunity, CREATED, OPEN, BAR, Provider, bar


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOT_DATA_DIR', str(tmp_path))
    store = SettingsStore()
    provider = Provider()
    now = [CREATED]
    ledger = Ledger()
    service = PaperTradingService(ledger, provider, clock=lambda: now[0])
    return store, service, provider, now


def create(service, state, *, key='one', symbol='AAPL', side='BUY', **overrides):
    context = dict(market='US', index_name='S&P 500', signal_time=CREATED-timedelta(hours=1),
                   timeframe='1d', quote_currency='USD', capital=10000,
                   risk_percent=state.settings.risk.risk_per_trade_percent,
                   metadata={'benchmark_symbol': 'SPY'})
    context.update(overrides)
    return service.confirm(key, opportunity(side, symbol), settings_state=state, **context)


def test_trade_keeps_scan_profile_despite_later_activation(environment):
    store, service, provider, now = environment
    scan_state = store.save(changed(risk={'risk_per_trade_percent': .5}), expected_version=0, profile_name='Swing')
    newer = store.save(changed(scan_state.settings, risk={'risk_per_trade_percent': .7}), expected_version=1)
    trade = create(service, scan_state)
    snapshot = TradeSettingsSnapshot.model_validate({k: trade[k] for k in TradeSettingsSnapshot.model_fields})
    assert snapshot.settings_version == 1
    assert snapshot.strategy_profile_version == 1
    assert snapshot.strategy_config_hash == scan_state.profile.configuration_hash
    assert snapshot.trading_settings.risk.risk_per_trade_percent == .5
    assert trade['quantity'] == 10
    assert snapshot.execution_risk_percent == .5
    assert store.load() == newer
    provider.bars = [bar(h=112)]
    now[0] = OPEN + BAR
    service.update_positions()
    restarted = Ledger(service.ledger.path).get(trade['trade_id'])
    assert restarted['status'] == 'CLOSED'
    assert all(restarted[k] == trade[k] for k in TradeSettingsSnapshot.model_fields)
    with pytest.raises(ValidationError):
        snapshot.trading_settings.risk.risk_per_trade_percent = 9
    with pytest.raises(ValueError, match='Risk differs'):
        create(service, scan_state, key='mismatch', symbol='MSFT', risk_percent=1)


def test_legacy_trades_are_labeled_only_when_read(environment):
    _, service, _, _ = environment
    snapshot = build_snapshot(opportunity(), market='US', index_name='Old', signal_time=CREATED-timedelta(hours=1),
                              timeframe='1d', quote_currency='USD', capital=10000, risk_percent=1,
                              metadata={}, created_at=CREATED, calendar=service.calendar)
    old = service.ledger.confirm('old', snapshot, initial_state())
    with service.ledger.connection() as db:
        before = [tuple(r) for r in db.execute('SELECT * FROM trades')]
        events_before = [tuple(r) for r in db.execute('SELECT * FROM paper_trade_events')]
    restarted = Ledger(service.ledger.path)
    trade = restarted.get(old['trade_id'])
    assert trade['configuration_source'] == 'PRE_SETTINGS_BASELINE'
    assert 'strategy_config_hash' not in trade and 'mode' not in trade and 'trading_settings' not in trade
    assert PerformanceService(restarted).report(group_by='strategy_config_hash')['segments'].keys() == {None}
    with restarted.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM trades')] == before
        assert [tuple(r) for r in db.execute('SELECT * FROM paper_trade_events')] == events_before
        assert 'configuration_source' not in json.loads(before[0][2])


def test_new_capital_defaults_never_change_existing_accounts(environment):
    store, service, _, _ = environment
    first = create(service, store.load())
    balances = service.ledger.summaries()
    new = store.save(changed(paper_trading={'usd_base_capital': 50000, 'gbp_base_capital': 20000}), expected_version=0)
    assert service.ledger.summaries() == balances
    assert service.ledger.get(first['trade_id']) == first
    with pytest.raises(ValueError, match='existing paper account capital'):
        create(service, new, key='new', symbol='MSFT', capital=50000)
    create(service, new, key='new', symbol='MSFT', capital=10000)
    uk = create(service, new, key='uk', symbol='AZN.L', market='UK', quote_currency='GBP', capital=new.settings.paper_trading.gbp_base_capital)
    assert uk['account_capital'] == '20000.0'
    assert service.ledger.summaries()['USD']['capital'] == 10000


@pytest.mark.parametrize('risk,side,message', [
    ({'allow_buy': False}, 'BUY', 'disabled'), ({'allow_sell': False}, 'SELL', 'disabled'),
    ({'minimum_risk_reward': 2.1}, 'BUY', 'risk/reward'),
    ({'enforce_position_limit': True, 'maximum_position_percent': 10}, 'BUY', 'position percent'),
    ({'enforce_portfolio_risk_limit': True, 'maximum_total_portfolio_risk_percent': 1}, 'BUY', 'portfolio risk'),
    ({'enforce_positions_limit': True, 'maximum_simultaneous_positions': 1}, 'BUY', 'simultaneous'),
    ({'enforce_daily_trade_limit': True, 'maximum_new_trades_per_day': 1}, 'BUY', 'UTC day'),
])
def test_opt_in_limits_transactional_rejection(environment, risk, side, message):
    store, service, _, _ = environment
    create(service, store.load())
    state = store.save(changed(risk=risk), expected_version=0)
    balances = service.ledger.summaries()
    events = service.ledger.events(service.ledger.all()[0]['trade_id'])
    with pytest.raises(ValueError, match=message):
        create(service, state, key='rejected', symbol='MSFT', side=side)
    assert len(service.ledger.all()) == 1 and service.ledger.summaries() == balances
    assert service.ledger.events(service.ledger.all()[0]['trade_id']) == events


def test_new_restrictions_are_disabled_in_baseline(environment):
    store, service, _, _ = environment
    # 40% notional is permitted under pre-settings rules, despite the suggested 30% limit.
    trade = create(service, store.load(), risk_percent=1, capital=10000)
    assert not trade['trading_settings']['risk']['enforce_position_limit']
    for i in range(4):
        create(service, store.load(), key=f'additional-{i}', symbol=f'AAA{i}')
    assert service.ledger.summaries()['USD']['available'] == 0


def test_research_identity_capital_and_performance_segmentation(environment):
    store, service, provider, now = environment
    forward = create(service, store.load())
    research_state = store.save(changed(general={'mode': 'RESEARCH'}), expected_version=0)
    research = create(service, research_state, key='research')  # Same signal, separate identity.
    assert research['trade_id'] != forward['trade_id']
    assert research['opportunity_id'] != forward['opportunity_id']
    assert service.ledger.summaries()['USD']['reserved'] == 4000
    assert create(service, research_state, key='duplicate')['trade_id'] == research['trade_id']
    provider.bars = [bar(h=112)]
    now[0] = OPEN+BAR
    service.update_positions()
    performance = PerformanceService(service.ledger)
    assert performance.report()['performance']['USD']['completed_trades'] == 1
    assert performance.report(mode='RESEARCH')['performance']['USD']['completed_trades'] == 1
    for field in ('strategy_profile_id','strategy_profile_version','strategy_config_hash','mode','market','index_name','side','market_regime'):
        report = performance.report(mode='ALL', group_by=field)
        assert sum(v['USD']['completed_trades'] for v in report['segments'].values()) == 2
        value = research[field]
        filtered = performance.report(mode='ALL', filters={field: value})
        assert all(e['trade'][field] == value for e in filtered['journal'])
    with pytest.raises(ValueError):
        performance.report(group_by='unknown')


def test_invalid_trade_snapshot_rejected_at_ledger_boundary(environment):
    store, service, _, _ = environment
    first = create(service, store.load())
    bad = dict(first, strategy_config_hash='invalid')
    with pytest.raises(ValueError):
        service.ledger.confirm('bad', bad, initial_state(), create_another=True)
    assert len(service.ledger.all()) == 1


def test_research_cannot_bypass_shared_account_limits(environment):
    store, service, _, _ = environment
    create(service, store.load())
    research = store.save(changed(general={'mode': 'RESEARCH'}, risk={
        'enforce_positions_limit': True, 'maximum_simultaneous_positions': 1}), expected_version=0)
    with pytest.raises(ValueError, match='simultaneous'):
        create(service, research, key='research')
    assert len(service.ledger.all()) == 1
