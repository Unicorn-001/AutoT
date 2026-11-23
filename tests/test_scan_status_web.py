"""Persisted scan activity stays visible independently of workspace navigation."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from autot.application.scan_store import ScanStore
from autot.daily_scanner import request_from_state
from autot.paper_trade.locking import database_lock
from autot.settings.store import SettingsStore


APP = str(Path(__file__).resolve().parents[1] / 'web_app.py')


def create_run(**updates):
    store = ScanStore()
    run = store.create(request_from_state(SettingsStore().load()))
    run.update(updates)
    store.save(run)
    return store, run


@pytest.mark.parametrize('outcome,phase,label,processed', [
    ('QUEUED', None, 'Queued / starting', None),
    ('RUNNING', 'STARTING', 'Starting', None),
    ('RUNNING', 'loading_market_data', 'Fetching market data', 4),
    ('RUNNING', 'analysing', 'Analyzing symbols', 3),
    ('RUNNING', 'ranking', 'Ranking / finalizing', 3),
    ('SUCCESS', 'ranking', 'Completed', 3),
    ('PARTIAL', 'ranking', 'Partial', 3),
    ('FAILED', 'analysing', 'Failed', 3),
    ('NO_WORK', None, 'Completed — no symbols', None),
])
def test_status_reads_persisted_phases_and_real_counts(outcome, phase, label, processed):
    store, run = create_run(status=outcome, phase=phase, symbols_total=10,
                            symbols_fetched=4, symbols_analyzed=2, symbols_failed=1)
    # A running worker owns this lock; status reads must not interrupt it.
    with database_lock(store.path, 'scan', blocking=False):
        app = AppTest.from_file(APP).run()
        assert not app.exception
        assert label in app.status[0].label
        bars = app.get('progress')
        if processed is None:
            assert not bars
        else:
            assert bars[0].proto.value == processed * 10
        assert store.get(run['scan_run_id'])['status'] == outcome
        assert bool(app.error) == (outcome == 'FAILED')


def test_progress_survives_navigation_reruns_and_new_session(monkeypatch):
    import streamlit as st
    from autot.application import paper_display, real_trade_journal_display, settings_display
    for module, name in [(paper_display, 'render_paper_dashboard'),
                         (real_trade_journal_display, 'render_real_trade_journal'),
                         (settings_display, 'render_settings')]:
        monkeypatch.setattr(module, name, lambda: st.write('Workspace content'))
    store, run = create_run(status='RUNNING', phase='analysing', symbols_total=10,
                            symbols_analyzed=2, symbols_failed=1)
    with database_lock(store.path, 'scan', blocking=False):
        app = AppTest.from_file(APP).run()
        for workspace in ['Paper Trading', 'Real Trade Journal', 'Settings', 'Scanner']:
            app.radio[0].set_value(workspace).run()
            assert not app.exception
            assert 'Analyzing' in app.status[0].label
            assert app.get('progress')[0].proto.value == 30
        run.update(symbols_analyzed=7)
        store.save(run)
        app.run()
        assert app.get('progress')[0].proto.value == 80
        fresh = AppTest.from_file(APP).run()
        assert fresh.get('progress')[0].proto.value == 80
        assert len(store.runs()) == 1


def test_unknown_total_has_no_invented_percentage():
    store, _ = create_run(status='RUNNING', phase='analysing', symbols_analyzed=2)
    with database_lock(store.path, 'scan', blocking=False):
        app = AppTest.from_file(APP).run()
        assert not app.exception
        assert not app.get('progress')
        assert any('Symbols processed: 2' in item.value for item in app.caption)


def test_submission_displays_queued_job_without_running_scan_in_ui(monkeypatch):
    from autot import daily_scanner
    calls = []
    def launch(request):
        calls.append(request)
        return ScanStore().create(request)['scan_run_id']
    monkeypatch.setattr(daily_scanner, 'launch', launch)
    app = AppTest.from_file(APP).run()
    app.button[0].click().run()
    assert not app.exception
    assert 'Queued / starting' in app.status[0].label
    app.run()
    assert len(calls) == 1


@pytest.mark.parametrize('error', [KeyError('status'), OSError('private storage details')])
def test_status_read_failure_does_not_block_workspace(monkeypatch, error):
    from autot import daily_scanner
    def fail():
        raise error
    monkeypatch.setattr(daily_scanner, 'read_status', fail)
    app = AppTest.from_file(APP).run()
    assert not app.exception
    assert app.button[0].label == 'Run Scan'
    assert any('Scan status unavailable' in item.value for item in app.warning)
    assert 'private storage details' not in str([item.value for item in app.warning])
