"""Offline Streamlit form tests; no server, market download or real ledger access."""
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

from autot.settings.store import SettingsStore
from tests.test_settings import changed

APP = str(Path(__file__).resolve().parents[1] / 'web_app.py')


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOT_DATA_DIR', str(tmp_path))
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value('Settings').run()
    return app


def by_label(elements, label):
    return next(e for e in elements if e.label == label)


def test_settings_renders_protected_baseline_and_no_save_on_rerun(app):
    assert not app.exception and not app.error
    assert any('AutoT Current / Baseline v1' in s.value for s in app.subheader)
    assert any('performance results non-comparable' in w.value for w in app.warning)
    assert any('no effect' in i.value for i in app.info)
    assert any('NEW currency accounts' in i.value for i in app.info)
    assert not SettingsStore().path.exists()
    by_label(app.number_input, 'Risk per trade percent').set_value(.5).run()
    assert SettingsStore().load().settings.risk.risk_per_trade_percent == 1
    assert not SettingsStore().path.exists()


def test_save_new_profile_and_version_then_restart(app):
    by_label(app.text_input, 'Profile name (renaming creates a new version)').set_value('US Swing')
    by_label(app.number_input, 'Risk per trade percent').set_value(.5)
    by_label(app.checkbox, 'Enforce position limit').check()
    by_label(app.checkbox, 'Enforce positions limit').check()
    by_label(app.button, 'Save Settings').click().run()
    assert not app.exception and not app.error
    saved = SettingsStore().load()
    assert saved.profile.profile_name == 'US Swing' and saved.profile.profile_version == 1
    assert saved.settings.risk.risk_per_trade_percent == .5
    assert saved.settings.risk.maximum_position_percent == 30
    assert saved.settings.risk.maximum_simultaneous_positions == 5
    assert saved.settings.risk.enforce_position_limit and saved.settings.risk.enforce_positions_limit
    by_label(app.number_input, 'Risk per trade percent').set_value(.6)
    by_label(app.button, 'Save Settings').click().run()
    assert not app.exception and not app.error
    assert SettingsStore().load().profile.profile_version == 2
    assert SettingsStore().profiles()[1] == saved.profile
    restarted = AppTest.from_file(APP).run()
    restarted.radio[0].set_value('Settings').run()
    assert not restarted.exception
    assert any('US Swing v2' in s.value for s in restarted.subheader)
    assert len(SettingsStore().history()) == 2


def test_invalid_save_and_reset_do_not_change_active_config(app):
    by_label(app.number_input, 'Risk per trade percent').set_value(-1)
    by_label(app.button, 'Save Settings').click().run()
    assert not app.exception and app.error
    assert SettingsStore().load().settings.risk.risk_per_trade_percent == 1
    assert not SettingsStore().path.exists()
    by_label(app.selectbox, 'Section to reset').set_value('risk')
    by_label(app.button, 'Reset Section').click().run()
    assert not app.exception
    assert by_label(app.number_input, 'Risk per trade percent').value == 1
    assert not SettingsStore().path.exists()


def test_activate_profile_and_restore_are_explicit(app):
    store = SettingsStore()
    custom = store.save(changed(risk={'risk_per_trade_percent': .5}), expected_version=0, profile_name='Swing')
    app.run()
    by_label(app.selectbox, 'Saved profile version').set_value(0)
    by_label(app.button, 'Activate profile').click().run()
    assert not app.exception and not app.error
    assert store.load().profile.builtin
    assert store.load().settings.risk.risk_per_trade_percent == 1
    assert custom.profile in store.profiles()
    count = len(store.history())
    by_label(app.button, 'Restore All Defaults').click().run()
    assert len(store.history()) == count


def test_scanner_uses_saved_defaults(app):
    SettingsStore().save(changed(scanner={'country': 'India', 'index': 'nifty100', 'history_period': '1y',
                                        'top_ranked_count': 7}), expected_version=0)
    app.radio[0].set_value('Scanner').run()
    assert not app.exception
    assert by_label(app.selectbox, 'Market').value == 'India'
    assert by_label(app.selectbox, 'Index').value == 'nifty100'
    assert by_label(app.text_input, 'Backtest period').value == '1y'
    assert by_label(app.number_input, 'Number of top stocks').value == 7


def test_global_restore_confirmation_save_and_history(app):
    from autot.settings.models import AutoTSettings
    from autot.paper_trade.ledger import Ledger
    from autot.paper_trade.service import PaperTradingService
    from tests.test_settings_paper import create
    from tests.test_prospective_paper import Provider, CREATED

    store = SettingsStore()
    custom = store.save(changed(
        general={'mode': 'RESEARCH'}, scanner={'country': 'India', 'index': 'nifty200'},
        strategies={'MACD': {'fast': 8}}, consensus={'minimum_confidence': 70},
        risk={'risk_per_trade_percent': .5}, paper_trading={'usd_base_capital': 20000},
        news={'enabled': True}, monitoring={'daily_scan_enabled': True}), expected_version=0)
    ledger = Ledger()
    create(PaperTradingService(ledger, Provider(), clock=lambda: CREATED), custom)
    with ledger.connection() as db:
        ledger_before = list(db.iterdump())
    profiles_before, history_before = store.profiles(), store.history()
    app.run()
    by_label(app.number_input, 'Risk per trade percent').set_value(.7).run()
    draft_before = app.session_state['settings_draft']
    by_label(app.button, 'Restore All Defaults').click().run()
    assert any('Historical trades and saved profiles will not be changed.' in w.value for w in app.warning)
    by_label(app.button, 'Cancel').click().run()
    assert app.session_state['settings_draft'] == draft_before
    assert by_label(app.number_input, 'Risk per trade percent').value == .7
    by_label(app.button, 'Restore All Defaults').click().run()
    by_label(app.button, 'Confirm Restore All Defaults').click().run()
    assert not app.exception and not app.error
    assert app.session_state['settings_draft'] == AutoTSettings().model_dump()
    assert store.load() == custom
    assert store.history() == history_before and store.profiles() == profiles_before
    by_label(app.button, 'Save Settings').click().run()
    assert not app.exception and not app.error
    assert store.load().settings == AutoTSettings()
    assert len(store.history()) == len(history_before) + 1
    assert store.history()[:-1] == history_before
    assert all(p in store.profiles() for p in profiles_before)
    with ledger.connection() as db:
        assert list(db.iterdump()) == ledger_before


@pytest.mark.parametrize('workspace,country_label,index_label', [
    ('Settings', 'Country', 'Default index (must match country)'),
    ('Scanner', 'Market', 'Index'),
])
def test_dependent_country_indices_share_registry(app, workspace, country_label, index_label):
    from autot.universe.index_definitions import indices_for_country
    app.radio[0].set_value(workspace).run()
    for country in ['United States', 'India', 'United Kingdom', 'United States']:
        by_label(app.selectbox, country_label).set_value(country).run()
        assert not app.exception
        indices = indices_for_country(country)
        selector = by_label(app.selectbox, index_label)
        assert selector.options == [i.index_name for i in indices]
        assert selector.value == indices[0].index_id
        selector.set_value(indices[-1].index_id).run()
        assert by_label(app.selectbox, index_label).value == indices[-1].index_id


def test_section_reset_preserves_other_unsaved_fields(app):
    by_label(app.number_input, 'Max articles').set_value(99).run()
    by_label(app.number_input, 'Risk per trade percent').set_value(.5).run()
    by_label(app.selectbox, 'Section to reset').set_value('risk').run()
    by_label(app.button, 'Reset Section').click().run()
    assert by_label(app.number_input, 'Risk per trade percent').value == 1
    assert by_label(app.number_input, 'Max articles').value == 99
    assert not SettingsStore().path.exists()
