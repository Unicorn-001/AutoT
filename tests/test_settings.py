"""Settings safety, durability, profile history and captured checkpoint equivalence."""
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest
from pydantic import ValidationError

from autot.settings.models import AutoTSettings, SettingsState, TradeSettingsSnapshot, configuration_hash
from autot.settings.store import SettingsStore, SettingsConflict, SettingsWarning
from autot.settings.context import bind_analysis
from autot.strategies.manager.strategy_manager import StrategyManager
from autot.strategy_weights.strategy_weight_engine import StrategyWeightEngine
from autot.indicators.technical_indicators import add_all_indicators
from autot.application.scanner_service import build_scan_rankings
from autot.performance.performance_tracker import PerformanceTracker
from tests.settings_data import prices
from main import analyse_stock


def changed(settings=None, **sections):
    raw = (settings or AutoTSettings()).model_dump()
    for name, updates in sections.items():
        raw[name].update(updates)
    return AutoTSettings.model_validate(raw)


@pytest.mark.parametrize('kind', ['up', 'down', 'flat', 'reversal'])
def test_exact_checkpoint_strategy_and_scanner_outputs(kind, monkeypatch, tmp_path):
    monkeypatch.setenv('AUTOT_DATA_DIR', str(tmp_path))
    fixture = json.loads((Path(__file__).parent / 'fixtures/settings_baseline_8b08e3c.json').read_text())[kind]
    row, decision = bind_analysis(analyse_stock, AutoTSettings())('TEST', prices(kind), prices('up','SPY'), PerformanceTracker())
    # All calculated fields, text reasons, sizing, quality and backtest scores are exact.
    assert row == fixture['row']
    assert asdict(decision) == fixture['decision']
    assert build_scan_rankings([row], 10) == build_scan_rankings([fixture['row']], 10)


@pytest.mark.parametrize('section,updates', [
    ('risk', {'risk_per_trade_percent': -1}), ('risk', {'risk_per_trade_percent': 101}),
    ('risk', {'maximum_position_percent': 101}), ('risk', {'maximum_simultaneous_positions': 0}),
    ('risk', {'risk_per_trade_percent': 3, 'maximum_total_portfolio_risk_percent': 2.5, 'enforce_portfolio_risk_limit': True}),
    ('scanner', {'country': 'India', 'index': 'sp500'}), ('news', {'max_articles': -1}),
    ('monitoring', {'paper_update_interval_minutes': 0}), ('advanced', {'same_bar_rule': 'TARGET_FIRST'}),
    ('strategies', {'EMA_RSI': {'fast': 50, 'slow': 20}}),
    ('strategies', {'MACD': {'fast': 26, 'slow': 26}}),
    ('strategies', {'BOLLINGER': {'deviation': -1}}),
    ('strategies', {'SUPERTREND': {'multiplier': 0}}),
    ('strategies', {'BREAKOUT': {'lookback': 0}}),
    ('strategies', {'ADX': {'weight': -1}}),
    ('strategies', {'MACD': {'weight': float('nan')}}),
    ('strategies', {'STOCHASTIC': {'oversold': 90, 'overbought': 80}}),
])
def test_invalid_settings_rejected(section, updates):
    with pytest.raises(ValidationError):
        changed(**{section: updates})


def test_no_secrets_or_unknown_fields():
    with pytest.raises(ValidationError):
        AutoTSettings.model_validate({'api_key': 'not-a-real-key'})


def test_disabled_weight_and_parameter_changes():
    data = add_all_indicators(prices('up'))
    defaults = StrategyManager(AutoTSettings().strategies).run_all(data)
    modified = changed(strategies={'MACD': {'enabled': False}, 'BREAKOUT': {'weight': 2.0}})
    results = StrategyManager(modified.strategies).run_all(data)
    assert len(results) == 9 and not any(r['strategy'] == 'MACD_Strategy' for r in results)
    weighted = StrategyWeightEngine.apply_weights(results, 'STRONG_UPTREND', modified.strategies)
    breakout = next(r for r in weighted if r['strategy'] == 'Breakout_Strategy')
    assert breakout['weight'] == 2 and breakout['confidence'] == round(breakout['original_confidence'] * 2, 4)
    parameters = changed(strategies={'EMA_RSI': {'fast': 5, 'slow': 60, 'buy_threshold': 100, 'sell_threshold': 0},
                                      'MACD': {'fast': 5}, 'BOLLINGER': {'deviation': 3}})
    other_data = add_all_indicators(prices('up'), parameters.strategies)
    assert not data.equals(other_data)
    assert StrategyManager(parameters.strategies).run_all(other_data)[0]['signal'] == 'HOLD'
    assert defaults[0]['signal'] == 'BUY'


def test_profile_versions_restart_rename_duplicate_and_activate(tmp_path):
    store = SettingsStore(tmp_path / 'settings.sqlite3')
    original = store.load()
    first = store.save(changed(risk={'risk_per_trade_percent': .5}), expected_version=0, profile_name='US Swing')
    second = store.save(changed(first.settings, strategies={'MACD': {'fast': 10}}), expected_version=1)
    assert first.profile.profile_version == 1 and second.profile.profile_version == 2
    assert first.profile.profile_id == second.profile.profile_id
    renamed = store.save(second.settings, expected_version=2, profile_name='US Swing Renamed')
    assert renamed.profile.profile_version == 3
    duplicate = store.save(renamed.settings, expected_version=3, new_profile=True, profile_name='Research Copy')
    assert duplicate.profile.profile_version == 1
    assert duplicate.profile.parent_profile_id == first.profile.profile_id
    restarted = SettingsStore(store.path)
    assert restarted.load() == duplicate
    assert restarted.profiles()[1] == first.profile
    restored = restarted.activate(first.profile.profile_id, 1, expected_version=4)
    assert restored.profile == first.profile and restored.settings.risk.risk_per_trade_percent == .5
    baseline = restarted.activate('autot-baseline', 1, expected_version=5)
    assert baseline.settings == original.settings and baseline.profile == original.profile
    assert len(store.history()) == 6
    assert store.save(baseline.settings, expected_version=6) == baseline
    assert len(store.history()) == 6
    with pytest.raises(ValueError, match='Duplicate'):
        store.save(baseline.settings, expected_version=6, profile_name='Overwrite baseline')


def test_profile_immutable_in_memory_and_database(tmp_path):
    store = SettingsStore(tmp_path / 'settings.db')
    state = store.save(AutoTSettings(), expected_version=0, new_profile=True, profile_name='Copy')
    with pytest.raises(ValidationError):
        state.profile.configuration.risk.risk_per_trade_percent = 2
    with sqlite3.connect(store.path) as db:
        for table in ('profiles', 'revisions', 'changes'):
            with pytest.raises(sqlite3.IntegrityError, match='append-only'):
                db.execute(f'DELETE FROM {table}')


def test_atomic_save_rolls_back_profile_revision_and_audit(tmp_path):
    store = SettingsStore(tmp_path / 'settings.db')
    first = store.save(changed(risk={'risk_per_trade_percent': .5}), expected_version=0)
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON changes BEGIN SELECT RAISE(ABORT, 'disk test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.save(changed(first.settings, risk={'risk_per_trade_percent': .6}), expected_version=1)
    assert store.load() == first and len(store.profiles()) == 2 and len(store.history()) == 1


def test_optimistic_concurrency_no_lost_update(tmp_path):
    store = SettingsStore(tmp_path / 'settings.db')
    def save(risk):
        try:
            return store.save(changed(risk={'risk_per_trade_percent': risk}), expected_version=0)
        except SettingsConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [.4, .6]))
    assert sum(r is not None for r in results) == 1
    assert len(store.history()) == 1


def test_corrupt_revision_falls_back_with_warning_and_recovers(tmp_path):
    store = SettingsStore(tmp_path / 'settings.db')
    first = store.save(changed(risk={'risk_per_trade_percent': .5}), expected_version=0)
    second = store.save(changed(first.settings, risk={'risk_per_trade_percent': .6}), expected_version=1)
    with sqlite3.connect(store.path) as db:
        db.execute('DROP TRIGGER revisions_no_update')
        db.execute("UPDATE revisions SET payload='invalid' WHERE version=2")
    with pytest.warns(SettingsWarning, match='last valid'):
        assert store.load() == first
    with pytest.warns(SettingsWarning):
        recovered = store.save(first.settings, expected_version=1)
    assert recovered.settings_version == 3 and store.load() == recovered
    store.path.write_bytes(b'not sqlite')
    with pytest.warns(SettingsWarning, match='unreadable'):
        assert store.load() == SettingsState()


def test_hash_canonical_and_validation_before_save(tmp_path):
    a = AutoTSettings()
    b = AutoTSettings.model_validate(dict(reversed(list(a.model_dump().items()))))
    assert configuration_hash(a) == configuration_hash(b)
    assert configuration_hash(a) != configuration_hash(changed(risk={'risk_per_trade_percent': .5}))
    store = SettingsStore(tmp_path / 'settings.db')
    invalid = a.model_copy(update={'risk': a.risk.model_copy(update={'risk_per_trade_percent': -1})})
    with pytest.raises(ValidationError):
        store.save(invalid, expected_version=0)
    assert not store.path.exists()


@pytest.mark.parametrize('kind', ['up', 'down', 'flat', 'reversal'])
def test_every_strategy_vote_and_weight_matches_checkpoint(kind):
    from autot.market_regime.market_regime_detector import MarketRegimeDetector
    from autot.strategies.manager.strategy_consensus import calculate_consensus_signal
    fixture = json.loads((Path(__file__).parent / 'fixtures/settings_baseline_8b08e3c.json').read_text())[kind]
    settings = AutoTSettings()
    data = add_all_indicators(prices(kind), settings.strategies)
    raw = StrategyManager(settings.strategies).run_all(data)
    regime = MarketRegimeDetector.detect(data)['regime']
    weighted = StrategyWeightEngine.apply_weights(raw, regime, settings.strategies)
    assert raw == fixture['strategies']
    assert weighted == fixture['weighted']
    assert calculate_consensus_signal(weighted) == fixture['consensus']


def test_scan_binding_does_not_change_when_active_profile_changes(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOT_DATA_DIR', str(tmp_path))
    from autot.settings.context import analysis_settings
    store = SettingsStore()
    state = store.load()
    captured = bind_analysis(lambda: analysis_settings(), state.settings)
    store.save(changed(strategies={'MACD': {'enabled': False}}), expected_version=0)
    assert captured() == state.settings
    assert not analysis_settings().strategies.MACD.enabled


def test_consensus_thresholds_are_configurable():
    from autot.decision_engine.decision_engine import DecisionEngine
    from autot.settings.models import Consensus
    votes = dict(buy_score=6, sell_score=4, hold_score=0, final_signal='BUY')
    assert DecisionEngine.decide(votes)['final_signal'] == 'BUY'
    assert DecisionEngine.decide(votes, Consensus(minimum_confidence=65))['final_signal'] == 'HOLD'
    assert DecisionEngine.decide(votes, Consensus(minimum_agreement=40))['final_signal'] == 'HOLD'


@pytest.mark.parametrize('country,index', [
    ('United States', 'nasdaq100'), ('United Kingdom', 'ftse250'), ('India', 'nifty500'),
])
def test_scanner_selection_persists_restart(tmp_path, country, index):
    store = SettingsStore(tmp_path / 'settings.db')
    store.save(changed(scanner={'country': country, 'index': index}), expected_version=0)
    scanner = SettingsStore(store.path).load().settings.scanner
    assert (scanner.country, scanner.index) == (country, index)


def test_invalid_country_index_rejected_before_storage(tmp_path):
    baseline = AutoTSettings()
    invalid = baseline.model_copy(update={'scanner': baseline.scanner.model_copy(update={'index': 'ftse100'})})
    store = SettingsStore(tmp_path / 'settings.db')
    with pytest.raises(ValidationError, match='belonging'):
        store.save(invalid, expected_version=0)
    assert not store.path.exists()
