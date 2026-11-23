"""Offline diagnostics against real durable stores and held service locks."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from autot.application.scan_store import ScanStore
from autot.application.system_health import snapshot
from autot.daily_scanner import request_from_state
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.locking import database_lock
from autot.runtime import data_dir
from autot.settings.store import SettingsStore

NOW = datetime.now(timezone.utc)


def scanner(phase='analysing', age=0, outcome='RUNNING'):
    store = ScanStore()
    run = store.create(request_from_state(SettingsStore().load()))
    run.update(status=outcome, heartbeat_at=NOW.isoformat())
    store.save(run)
    with store.connection() as db:
        db.execute('INSERT INTO scanner_status VALUES (?, ?)', ('worker', json.dumps(dict(
            phase=phase, heartbeat=(NOW - timedelta(seconds=age)).isoformat()))))
    return store, run


def test_healthy_and_read_only():
    store, run = scanner()
    ledger = Ledger()
    ledger.monitor_heartbeat(dict(phase='UPDATING', heartbeat=NOW.isoformat()))
    with database_lock(store.path, 'scan'), database_lock(ledger.path, 'monitor'):
        view = snapshot(now=NOW)
    assert view['scanner']['health'] == view['paper']['health'] == 'HEALTHY'
    assert store.get(run['scan_run_id']) == run


def test_stopped_process_does_not_recover_job():
    store, run = scanner()
    assert snapshot(now=NOW)['scanner']['health'] == 'STOPPED'
    assert store.get(run['scan_run_id'])['status'] == 'RUNNING'


@pytest.mark.parametrize('age', [-60])
def test_stale_or_future_heartbeat(age):
    store, _ = scanner(age=age)
    with database_lock(store.path, 'scan'):
        assert snapshot(now=NOW)['scanner']['health'] == 'ATTENTION'


def test_no_prior_runs_and_missing_storage():
    view = snapshot(now=NOW)
    assert view['scanner']['health'] == view['paper']['health'] == 'IDLE'
    assert view['scanner']['last_run'] is None
    assert view['paper']['pending'] == view['paper']['open'] == 0
    assert not data_dir().exists()


def test_configured_but_never_started():
    store = SettingsStore()
    settings = store.load().settings
    settings = settings.model_copy(update={'monitoring': settings.monitoring.model_copy(
        update={'paper_monitor_enabled': True})})
    store.save(settings, expected_version=0)
    assert snapshot(now=NOW)['paper']['health'] == 'STOPPED'


def test_waiting_is_idle_and_failure_needs_attention():
    store, run = scanner(phase='WAITING')
    with database_lock(store.path, 'scan'):
        assert snapshot(now=NOW)['scanner']['health'] == 'IDLE'
        run['status'] = 'PARTIAL'
        store.save(run)
        assert snapshot(now=NOW)['scanner']['health'] == 'ATTENTION'


def test_pending_and_open_counts_survive_new_reads():
    path = data_dir() / 'paper_trading' / 'ledger.sqlite3'
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE trades (state TEXT)')
        db.executemany('INSERT INTO trades VALUES (?)', [(json.dumps(dict(status=s)),) for s in
                       ['PENDING_ENTRY', 'PENDING_ENTRY', 'OPEN', 'CLOSED', 'CANCELLED']])
    for _ in range(2):
        paper = snapshot(now=NOW)['paper']
        assert (paper['pending'], paper['open']) == (2, 1)


@pytest.mark.parametrize('relative,key', [('scanner/scans.sqlite3', 'scanner'),
                                         ('paper_trading/ledger.sqlite3', 'paper')])
def test_corrupt_database(relative, key):
    path = data_dir() / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b'not a database')
    view = snapshot(now=NOW)
    assert view[key]['health'] == 'ATTENTION'
    assert view[key]['unavailable']
    assert path.read_bytes() == b'not a database'
    if key == 'paper':
        assert view[key]['pending'] is None


@pytest.mark.parametrize('payload', ['{', '[]', '{"status": null}'])
def test_corrupt_scanner_payload(payload):
    store, _ = scanner()
    with store.connection() as db:
        db.execute('UPDATE scan_runs SET payload=?', (payload,))
    assert snapshot(now=NOW)['scanner']['health'] == 'ATTENTION'


def test_corrupt_paper_heartbeat():
    ledger = Ledger()
    ledger.monitor_heartbeat([])
    assert snapshot(now=NOW)['paper']['health'] == 'ATTENTION'


def test_invalid_heartbeat():
    ledger = Ledger()
    ledger.monitor_heartbeat(dict(heartbeat='invalid', phase='WAITING'))
    with database_lock(ledger.path, 'monitor'):
        assert snapshot(now=NOW)['paper']['health'] == 'ATTENTION'


def test_workspace_and_restart_do_not_recover_scans(monkeypatch):
    from autot import daily_scanner
    def forbidden():
        raise AssertionError('Health page must not invoke recovering status reader')
    monkeypatch.setattr(daily_scanner, 'read_status', forbidden)
    store, run = scanner()
    for _ in range(2):
        app = AppTest.from_string('from autot.application.system_health_display import render_system_health\nrender_system_health()').run()
        assert not app.exception
        assert any(m.value == 'STOPPED' for m in app.metric)
        assert any(str(data_dir()) in code.value for code in app.code)
    assert store.get(run['scan_run_id']) == run


def test_workspace_navigation():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'web_app.py')).run()
    app.radio[0].set_value('System Health / Status').run()
    assert not app.exception
    assert any(s.value == 'System Health / Status' for s in app.subheader)
    assert [m.value for m in app.metric] == ['IDLE', 'IDLE', '0', '0']


def test_corrupt_settings_is_not_reported_as_healthy():
    path = data_dir() / 'settings' / 'settings.sqlite3'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'broken')
    with pytest.warns(UserWarning):
        view = snapshot(now=NOW)
    assert view['settings_warning']
    assert view['scanner']['health'] == view['paper']['health'] == 'ATTENTION'


def test_corrupt_storage_workspace_still_renders():
    path = data_dir() / 'paper_trading' / 'ledger.sqlite3'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'broken')
    app = AppTest.from_string('from autot.application.system_health_display import render_system_health\nrender_system_health()').run()
    assert not app.exception
    assert [m.value for m in app.metric] == ['IDLE', 'ATTENTION', 'Unavailable', 'Unavailable']


@pytest.mark.parametrize('phase', ['loading_universe', 'loading_market_data', 'analysing'])
def test_long_running_scan_is_not_falsely_stale(phase):
    store, run = scanner(phase=phase, age=600)
    with database_lock(store.path, 'scan'):
        view = snapshot(now=NOW)['scanner']
        assert view['process_status'] == 'ACTIVE'
        assert view['health'] == 'RUNNING'
        assert 'Progress is unverified' in view['reason']
    assert snapshot(now=NOW)['scanner']['health'] == 'STOPPED'
    assert store.get(run['scan_run_id']) == run


@pytest.mark.parametrize('age,due_seconds,expected', [
    (10, 3600, 'IDLE'), (180, 3600, 'ATTENTION'), (10, -60, 'ATTENTION'),
])
def test_scheduler_timing(age, due_seconds, expected):
    store = ScanStore()
    with store.connection() as db:
        db.execute('INSERT INTO scanner_status VALUES (?, ?)', ('scheduler', json.dumps(dict(
            phase='WAITING', heartbeat=(NOW - timedelta(seconds=age)).isoformat(),
            next_expected_run=(NOW + timedelta(seconds=due_seconds)).isoformat()))))
    with database_lock(store.path, 'scheduler'):
        assert snapshot(now=NOW)['scanner']['health'] == expected


@pytest.mark.parametrize('phase,age,due_seconds,expected', [
    ('WAITING', 10, 240, 'IDLE'),
    ('WAITING', 180, 240, 'ATTENTION'),
    ('WAITING', 10, -60, 'ATTENTION'),
    ('UPDATING', 180, None, 'HEALTHY'),
    ('UPDATING', 346, None, 'ATTENTION'),
])
def test_paper_monitor_timing(phase, age, due_seconds, expected):
    ledger = Ledger()
    ledger.monitor_heartbeat(dict(
        phase=phase, heartbeat=(NOW - timedelta(seconds=age)).isoformat(),
        next_expected_run=(NOW + timedelta(seconds=due_seconds)).isoformat()
        if due_seconds is not None else None))
    with database_lock(ledger.path, 'monitor'):
        assert snapshot(now=NOW)['paper']['health'] == expected
    assert snapshot(now=NOW)['paper']['health'] == 'STOPPED'


def test_paper_update_uses_configured_cadence():
    settings_store = SettingsStore()
    settings = settings_store.load().settings
    settings = settings.model_copy(update={'monitoring': settings.monitoring.model_copy(
        update={'paper_update_interval_minutes': 10})})
    settings_store.save(settings, expected_version=0)
    ledger = Ledger()
    ledger.monitor_heartbeat(dict(phase='UPDATING', heartbeat=(NOW - timedelta(seconds=500)).isoformat()))
    with database_lock(ledger.path, 'monitor'):
        assert snapshot(now=NOW)['paper']['health'] == 'HEALTHY'
