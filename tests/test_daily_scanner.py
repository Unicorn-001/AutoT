"""Offline service boundaries; every persistence test inherits isolated AUTOT_DATA_DIR."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

import pytest

from autot import daily_scanner as ds
from autot.application.scan_store import ScanStore
from autot.settings.models import SettingsState
from autot.paper_trade.locking import database_lock, MonitorAlreadyRunning


def enabled(**updates):
    data = SettingsState().model_dump(mode='json')
    data['settings']['monitoring'].update(daily_scan_enabled=True, **updates)
    return SettingsState.model_validate(data)


def now(hour=23, day=13):
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc)


def executor(request, diagnostics, stage):
    stage('universe_loaded', {'count': 1})
    row = dict(symbol='AAA', signal='BUY', score=80, confidence=75, agreement=80,
               trade_quality_score=76.05, opportunity_score=90, strategy_features={'version': 1})
    return dict(outputs=dict(symbols=['AAA'], results=[row], ranked_results=[row], top_results=[row],
                             trade_opportunities=[row]), diagnostics=diagnostics,
                settings={k: request[k] for k in ('universe', 'period', 'interval', 'top_n')},
                settings_state=request['state'])


def scanner(**kwargs):
    return ds.DailyScanner(executor=executor, state=enabled, clock=lambda: now(), **kwargs)


def test_once_cli(monkeypatch, capsys):
    service = scanner()
    monkeypatch.setattr(ds, 'DailyScanner', lambda: service)
    assert ds.main(['--once']) == 0
    run = json.loads(capsys.readouterr().out)
    assert run['trigger_type'] == 'MANUAL'
    assert run['status'] == 'SUCCESS'


def test_success_profile_reload_and_manual_rerun():
    service = scanner()
    first = service.once()
    second = service.once()
    assert first['scan_run_id'] != second['scan_run_id']
    assert len(ScanStore().runs()) == 2
    assert first['profile'] == enabled().profile.model_dump(mode='json')
    assert first['symbols_analyzed'] == first['symbols_fetched'] == 1
    assert first['top_opportunity'] == 'AAA BUY · quality 76.05'
    assert ScanStore().latest()['outputs']['results'][0]['strategy_features'] == {'version': 1}


def test_partial_and_failed_preserve_previous_results():
    service = scanner()
    def partial(req, diag, stage):
        saved = executor(req, diag, stage)
        saved['outputs']['symbols'].append('BBB')
        diag['failures'] = [{'symbol': 'BBB', 'reason': 'No usable data'}]
        return saved
    service.executor = partial
    run = service.once()
    assert run['status'] == 'PARTIAL'
    assert run['symbols_failed'] == 1 and run['failures'][0]['symbol'] == 'BBB'
    saved = ScanStore().latest()
    service.executor = lambda *a: (_ for _ in ()).throw(OSError('network'))
    failure = service.once()
    assert failure['status'] == 'FAILED'
    assert ScanStore().latest() == saved


def test_all_failed_is_failure_and_empty_is_no_work():
    service = scanner()
    def empty(req, diag, stage):
        saved = executor(req, diag, stage)
        for key in ('results', 'ranked_results', 'top_results', 'trade_opportunities'):
            saved['outputs'][key] = []
        return saved
    service.executor = empty
    assert service.once()['status'] == 'FAILED'
    def no_universe(*args):
        saved = empty(*args)
        saved['outputs']['symbols'] = []
        return saved
    service.executor = no_universe
    assert service.once()['status'] == 'NO_WORK'


@pytest.mark.parametrize('outcomes', [
    ['PARTIAL'],
    ['SUCCESS', 'PARTIAL'],
    ['PARTIAL', 'SUCCESS'],
    ['FAILED', 'PARTIAL'],
    ['PARTIAL', 'FAILED'],
    ['FAILED', 'SUCCESS', 'PARTIAL', 'NO_WORK', 'SKIPPED', 'QUEUED', 'RUNNING'],
])
def test_status_usable_completions_and_failures(outcomes):
    store = ScanStore()
    expected_success = expected_failure = None
    for index, outcome in enumerate(outcomes):
        run = store.create(ds.request_from_state(enabled()))
        run.update(status=outcome, completed_at=f'2026-11-13T12:{index:02d}:00+00:00',
                   symbols_fetched=2, symbols_analyzed=1 if outcome == 'PARTIAL' else 2,
                   symbols_failed=1 if outcome == 'PARTIAL' else 0,
                   failures=[{'symbol': 'BBB', 'reason': 'No usable data'}] if outcome == 'PARTIAL' else [])
        store.save(run)
        if outcome in ('SUCCESS', 'PARTIAL'):
            expected_success = run
        elif outcome == 'FAILED':
            expected_failure = run
        # A held worker lock prevents recovery from changing active fixture runs.
        with database_lock(store.path, 'scan'):
            status = ds.read_status()
        assert status['last_run'] == run
        assert status['last_success'] == expected_success
        assert status['last_failure'] == expected_failure
        assert ScanStore().get(run['scan_run_id']) == run
        assert status['latest_results_timestamp'] == (
            expected_success['completed_at'] if expected_success else None)


def test_disabled_and_cli_does_not_create_storage(monkeypatch):
    monkeypatch.setattr(ds, 'load_state', SettingsState)
    assert ds.main([]) == 0
    assert not (ds.data_dir() / 'scanner').exists()
    service = scanner()
    service.state = SettingsState
    assert service.cycle() is None
    assert not service.store.runs()


def test_close_guard_and_local_time():
    req = ds.request_from_state(enabled(daily_scan_time_local='12:00'))
    session, due = ds.slot(req, now(20))
    assert session == '2026-11-13'
    assert due == now(21).replace(minute=30)
    service = scanner()
    service.state = lambda: enabled(daily_scan_time_local='12:00')
    service.clock = lambda: now(20)
    assert service.cycle()['status'] == 'SKIPPED'
    assert service.cycle() is None
    service.clock = lambda: now(22)
    assert service.cycle()['status'] == 'SUCCESS'
    assert service.cycle() is None


@pytest.mark.parametrize('day,interval', [(14, '1d'), (13, '1h')])
def test_unsuitable_session_skipped(day, interval):
    raw = enabled().model_dump(mode='json')
    raw['settings']['scanner']['interval'] = interval
    state = SettingsState.model_validate(raw)
    service = scanner()
    service.state = lambda: state
    service.clock = lambda: now(day=day)
    assert service.cycle()['status'] == 'SKIPPED'


def test_duplicate_after_restart_and_failure_waits_next_day():
    service = scanner()
    # 22:00 New York = next UTC day 03:00; use an earlier configured slot.
    service.state = lambda: enabled(daily_scan_time_local='17:00')
    assert service.cycle()['status'] == 'SUCCESS'
    restarted = scanner()
    restarted.state = service.state
    assert restarted.cycle() is None
    assert restarted.once()['trigger_type'] == 'MANUAL'
    restarted.clock = lambda: now(day=16)
    restarted.executor = lambda *a: (_ for _ in ()).throw(OSError())
    assert restarted.cycle()['status'] == 'FAILED'
    assert restarted.cycle() is None
    restarted.clock = lambda: now(day=17)
    assert restarted.cycle()['status'] == 'FAILED'


def test_continuous_loop_and_ctrl_c_release():
    class Stop:
        stopped = False
        def is_set(self):
            return self.stopped
        def wait(self, seconds):
            assert seconds == 15
            self.stopped = True
    service = scanner(stop=Stop())
    service.state = lambda: enabled(daily_scan_time_local='17:00')
    service.run()
    assert service.store.runs()[0]['status'] == 'SUCCESS'
    assert not ds.active(service.store.path, 'scheduler')
    service.stop = threading.Event()
    service.cycle = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        service.run()
    assert not ds.active(service.store.path, 'scheduler')


def test_execution_lock_and_interrupt_recovery():
    service = scanner()
    def interrupted(*args):
        assert ds.active(service.store.path, 'scan')
        with pytest.raises(MonitorAlreadyRunning):
            with database_lock(service.store.path, 'scan', blocking=False):
                pass
        raise KeyboardInterrupt()
    service.executor = interrupted
    with pytest.raises(KeyboardInterrupt):
        service.once()
    assert not ds.active(service.store.path, 'scan')
    assert service.store.runs()[0]['error_category'] == 'INTERRUPTED'
    status = ds.read_status()
    assert status['last_failure'] == service.store.runs()[0]
    assert status['last_success'] is None


def test_two_scheduler_processes_prevented():
    service = scanner()
    with database_lock(service.store.path, 'scheduler'):
        with pytest.raises(MonitorAlreadyRunning):
            service.run()


@pytest.mark.parametrize('busy', ['scan', 'submission', 'queued_manual'])
def test_scheduler_waits_for_manual_scan_without_consuming_session(busy):
    service = scanner()
    service.state = lambda: enabled(daily_scan_time_local='17:00')
    class Stop:
        stopped = False
        def is_set(self):
            return self.stopped
        def wait(self, seconds):
            assert seconds == 15
            self.stopped = True
    service.stop = Stop()
    if busy == 'queued_manual':
        manual = service.store.create(ds.request_from_state(service.state()))
        service.run()
        assert service.store.runs() == [manual]
        service.work(manual)
    else:
        with database_lock(service.store.path, busy):
            service.run()
        assert service.store.runs() == []
    assert service.stop.stopped
    scheduled = service.cycle()
    assert scheduled['status'] == 'SUCCESS'
    assert scheduled['trigger_type'] == 'SCHEDULED'
    assert service.cycle() is None
    assert service.once()['status'] == 'SUCCESS'


@pytest.mark.parametrize('status', ['SUCCESS', 'PARTIAL', 'FAILED'])
def test_notifications_and_delivery_failure(monkeypatch, status):
    from autot import notifications
    service = scanner()
    service.state = lambda: enabled(daily_scan_time_local='17:00')
    def outcome(req, diag, stage):
        if status == 'FAILED':
            raise OSError()
        saved = executor(req, diag, stage)
        if status == 'PARTIAL':
            saved['outputs']['symbols'].append('BBB')
        return saved
    service.executor = outcome
    monkeypatch.setattr(notifications, 'deliver', lambda *a, **k: (_ for _ in ()).throw(OSError()))
    run = service.cycle()
    assert run['status'] == status
    with service.store.connection() as db:
        event = dict(db.execute('SELECT * FROM notification_outbox').fetchone())
    assert event['event_type'] == 'DAILY_SCAN_' + ('COMPLETED' if status == 'SUCCESS' else status)
    assert 'Market: US' in notifications.message(event)
    if status != 'FAILED':
        assert 'AAA BUY · quality 76.05' in notifications.message(event)


def test_no_paper_capital_broker_or_production_changes(monkeypatch):
    from autot.paper_trade.ledger import Ledger
    from autot.broker.paper_broker import PaperBroker
    def forbidden(*args, **kwargs):
        pytest.fail('Research must not access paper trades/capital/broker')
    monkeypatch.setattr(Ledger, '__init__', forbidden)
    monkeypatch.setattr(PaperBroker, '__init__', forbidden)
    service = scanner()
    service.state = lambda: enabled(daily_scan_time_local='17:00')
    service.cycle()
    assert not (ds.data_dir() / 'paper_trading').exists()
    assert service.store.path.is_relative_to(ds.data_dir())


def test_detached_launch_and_status(monkeypatch):
    calls = []
    monkeypatch.setattr(ds.subprocess, 'Popen', lambda *args, **kwargs: calls.append((args, kwargs)))
    job = ds.launch(ds.request_from_state(enabled()))
    args, kwargs = calls[0]
    assert args[0][-2:] == ['--job', job]
    assert kwargs['start_new_session'] is True
    assert kwargs['env']['AUTOT_DATA_DIR'] == str(ds.data_dir())
    assert ScanStore().get(job)['status'] == 'QUEUED'
    assert ds.read_status()['process_status'] == 'NOT DETECTED'
    with database_lock(ScanStore().path, 'scan'):
        assert ds.read_status()['process_status'] == 'ACTIVE'


def test_status_read_only():
    assert ds.read_status()['process_status'] == 'NOT DETECTED'
    assert not (ds.data_dir() / 'scanner').exists()


def test_navigation_restart_loads_completed_results(monkeypatch):
    from streamlit.testing.v1 import AppTest
    service = scanner()
    service.once()
    monkeypatch.setattr(ds, 'launch', lambda *a: pytest.fail('Viewing must not scan'))
    app = AppTest.from_file(str(ds.PROJECT_ROOT / 'web_app.py')).run()
    assert not app.exception
    assert app.session_state['scan']['outputs']['results'][0]['symbol'] == 'AAA'
    app.radio[0].set_value('Settings').run()
    app.radio[0].set_value('Scanner').run()
    assert app.session_state['scan']['outputs']['results'][0]['symbol'] == 'AAA'
    restarted = AppTest.from_file(str(ds.PROJECT_ROOT / 'web_app.py')).run()
    assert restarted.session_state['scan']['outputs']['results'][0]['symbol'] == 'AAA'


def test_stale_candle_rejected_by_shared_scanner(monkeypatch):
    import pandas as pd
    import main
    from autot.market_data.market_data_manager import MarketDataManager
    from autot.universe.index_provider import IndexUniverseProvider
    from autot.universe.providers import UniverseResult
    frame = pd.DataFrame({'Close': range(60)}, index=pd.date_range(end='2026-11-12', periods=60))
    monkeypatch.setattr(IndexUniverseProvider, 'load', lambda _: UniverseResult(['AAA'], 'Fixture', 1, 0))
    monkeypatch.setattr(MarketDataManager, 'get_stock_data', lambda *a: frame)
    monkeypatch.setattr(MarketDataManager, 'get_batch_stock_data', lambda **k: {'AAA': frame})
    monkeypatch.setattr(main, 'analyse_stock', lambda *a: pytest.fail('Stale candle must not be analyzed'))
    service = ds.DailyScanner(state=lambda: enabled(daily_scan_time_local='17:00'), clock=lambda: now())
    run = service.cycle()
    assert run['status'] == 'FAILED'
    assert run['failures'][0]['symbol'] == 'AAA'
    assert run['symbols_failed'] == 1


def test_recover_abandoned_run_and_notification_replay(monkeypatch):
    from autot import notifications
    service = scanner()
    req = ds.request_from_state(enabled())
    run = service.store.create(req, 'SCHEDULED', '2026-11-12', 'old')
    run.update(status='RUNNING', started_at='2026-11-12T23:00:00+00:00')
    service.store.save(run)
    class Stop:
        def is_set(self):
            return True
    service.stop = Stop()
    service.run()
    assert service.store.get(run['scan_run_id'])['status'] == 'FAILED'
    service.run()
    with service.store.connection() as db:
        assert db.execute('SELECT count(*) FROM notification_outbox').fetchone()[0] == 1


def test_projection_failure_preserves_completed_run_and_replays(monkeypatch):
    from autot import notifications
    original = notifications.enqueue
    service = scanner()
    service.state = lambda: enabled(daily_scan_time_local='17:00')
    monkeypatch.setattr(notifications, 'enqueue', lambda *a, **k: (_ for _ in ()).throw(OSError()))
    run = service.cycle()
    assert run['status'] == 'SUCCESS'
    assert service.store.latest()['scan_run_id'] == run['scan_run_id']
    monkeypatch.setattr(notifications, 'enqueue', original)
    service.notify(run)
    with service.store.connection() as db:
        assert db.execute('SELECT count(*) FROM notification_outbox').fetchone()[0] == 1


def test_cross_process_lock(tmp_path):
    import subprocess
    import sys
    service = scanner()
    script = '''
import sys
from autot.paper_trade.locking import database_lock, MonitorAlreadyRunning
try:
    with database_lock(sys.argv[1], 'scan', blocking=False):
        sys.exit(3)
except MonitorAlreadyRunning:
    sys.exit(0)
'''
    with database_lock(service.store.path, 'scan'):
        result = subprocess.run([sys.executable, '-c', script, str(service.store.path)],
                                cwd=ds.PROJECT_ROOT, timeout=10)
    assert result.returncode == 0


def test_existing_paper_database_bytes_untouched():
    path = ds.data_dir() / 'paper_trading' / 'ledger.sqlite3'
    path.parent.mkdir(parents=True)
    sentinel = b'Existing paper data must never be opened or migrated by research'
    path.write_bytes(sentinel)
    service = scanner()
    service.state = lambda: enabled(daily_scan_time_local='17:00')
    service.cycle()
    assert path.read_bytes() == sentinel


def test_quality_filter_does_not_modify_ranked_rows():
    service = scanner()
    service.state = lambda: enabled(daily_scan_quality_threshold=80)
    run = service.once()
    saved = service.store.latest()
    assert run['opportunities_count'] == 0
    assert saved['outputs']['trade_opportunities'] == []
    assert saved['outputs']['ranked_results'][0]['signal'] == 'BUY'
    assert saved['outputs']['ranked_results'][0]['trade_quality_score'] == 76.05


@pytest.mark.parametrize('month,utc_hour', [(7, 2), (11, 3)])
def test_market_timezone_dst(month, utc_hour):
    req = ds.request_from_state(enabled())
    instant = datetime(2026, month, 13, 12, tzinfo=timezone.utc)
    _, due = ds.slot(req, instant)
    assert due.day == 14 and due.hour == utc_hour


def test_scanner_configuration_edit_does_not_repeat_same_session_profile():
    service = scanner()
    service.state = lambda: enabled(daily_scan_time_local='17:00')
    assert service.cycle()['status'] == 'SUCCESS'
    raw = service.state().model_dump(mode='json')
    raw['settings']['scanner'].update(history_period='1y', top_ranked_count=20, index='nasdaq100')
    service.state = lambda: SettingsState.model_validate(raw)
    assert service.cycle() is None
    assert service.once()['status'] == 'SUCCESS'


@pytest.mark.parametrize('mid_scan', [False, True])
def test_hard_worker_death_status_recovers_once(mid_scan):
    import os
    import subprocess
    import sys
    script = '''
import os
from autot.daily_scanner import DailyScanner, request_from_state
from autot.settings.models import SettingsState
def die(request, diagnostics, stage):
    if MID:
        stage('analysing', dict(symbols_fetched=3, symbols_analyzed=1, symbols_failed=1))
    os._exit(9)
DailyScanner(executor=die).once(request_from_state(SettingsState()))
'''.replace('MID', repr(mid_scan))
    child = subprocess.run([sys.executable, '-c', script], cwd=ds.PROJECT_ROOT, timeout=15)
    assert child.returncode == 9
    store = ScanStore()
    before = store.runs()[0]
    assert before['status'] == 'RUNNING'
    assert before['symbols_fetched'] == (3 if mid_scan else 0)
    status = ds.read_status()
    recovered = status['last_run']
    assert recovered['status'] == 'FAILED'
    assert recovered['error_category'] == 'WORKER_INTERRUPTED'
    assert status['last_failure'] == recovered
    assert status['last_success'] is None
    assert recovered['scan_run_id'] == before['scan_run_id']
    assert ds.read_status()['last_run'] == recovered
    assert len(store.runs()) == 1
    assert scanner().once()['status'] == 'SUCCESS'


def test_old_heartbeat_with_live_lock_and_pid_is_not_recovered():
    import os
    service = scanner()
    run = service.store.create(ds.request_from_state(enabled()))
    run.update(status='RUNNING', heartbeat_at='2000-01-01T00:00:00+00:00')
    service.store.save(run)
    with database_lock(service.store.path, 'scan'):
        assert service.recover() == []
        assert ds.read_status()['last_run']['status'] == 'RUNNING'
    run['worker_pid'] = os.getpid()
    service.store.save(run)
    # A PID without the worker's lifetime lock is not proof of ownership (PID reuse).
    assert service.recover() == [run['scan_run_id']]


def test_durable_batched_progress_and_cli_lifecycle(monkeypatch, capsys):
    service = scanner()
    ticks = iter([1., 2., 5., 8.])
    monkeypatch.setattr(ds.monotonic_time, 'monotonic', lambda: next(ticks))
    def progress(req, diag, stage):
        initial = service.store.runs()[0]
        assert initial['status'] == 'RUNNING'
        stage('analysing', dict(symbols_fetched=3, symbols_analyzed=1, symbols_failed=1))
        first = service.store.runs()[0]
        stage('analysing', dict(symbols_fetched=3, symbols_analyzed=2, symbols_failed=1))
        last = service.store.runs()[0]
        assert last['symbols_analyzed'] == 2
        assert last['symbols_fetched'] == 3 and last['symbols_failed'] == 1
        assert last['heartbeat_at'] >= first['heartbeat_at'] >= initial['heartbeat_at']
        return executor(req, diag, lambda *a: None)
    service.executor = progress
    monkeypatch.setattr(ds, 'DailyScanner', lambda: service)
    assert ds.main(['--once']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'SUCCESS'


def test_duplicate_queued_launch_and_launch_error_log(monkeypatch):
    calls = []
    class Child:
        pid = None
    def launch(*a, **kw):
        calls.append(kw)
        kw['stderr'].write(b'worker diagnostic\n')
        return Child()
    monkeypatch.setattr(ds.subprocess, 'Popen', launch)
    job = ds.launch(ds.request_from_state(enabled()))
    with pytest.raises(MonitorAlreadyRunning):
        ds.launch(ds.request_from_state(enabled()))
    assert len(calls) == 1
    assert calls[0]['stdout'] is calls[0]['stderr']
    assert calls[0]['stdin'] == ds.subprocess.DEVNULL
    assert calls[0]['start_new_session']
    assert job in (ScanStore().path.parent / 'worker.log').read_text()
    assert 'worker diagnostic' in (ScanStore().path.parent / 'worker.log').read_text()
    run = ScanStore().get(job)
    run.update(requested_at='2000-01-01T00:00:00+00:00')
    ScanStore().save(run)
    assert ds.read_status()['last_run']['status'] == 'FAILED'
    def fail(*a, **kw):
        raise OSError('sensitive detail')
    monkeypatch.setattr(ds.subprocess, 'Popen', fail)
    with pytest.raises(OSError):
        ds.launch(ds.request_from_state(enabled()))
    failure = ScanStore().runs()[0]
    assert failure['error_category'] == 'LAUNCH_FAILED'
    assert 'sensitive detail' not in json.dumps(failure)


def test_recovery_preserves_paper_and_settings_bytes():
    from autot.settings.store import SettingsStore
    SettingsStore().load()
    service = scanner()
    paper = ds.data_dir() / 'paper_trading' / 'ledger.sqlite3'
    paper.parent.mkdir(parents=True)
    paper.write_bytes(b'untouchable ledger')
    paths = [p for p in ds.data_dir().rglob('*') if p.is_file() and 'scanner' not in str(p)]
    before = {p: p.read_bytes() for p in paths}
    run = service.store.create(ds.request_from_state(enabled()))
    run.update(status='RUNNING')
    service.store.save(run)
    ds.read_status()
    assert all(p.read_bytes() == data for p, data in before.items())
