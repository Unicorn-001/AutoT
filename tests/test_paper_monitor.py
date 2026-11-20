"""Offline scheduler integration; every ledger and subprocess uses AUTOT_DATA_DIR."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from autot.paper_monitor import PaperMonitor, main, read_status
from autot.paper_trade.intraday import HistoryUnavailable
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.locking import database_lock, monitor_active
from autot.paper_trade.service import PaperTradingService
from autot.settings.models import Monitoring, AutoTSettings
from autot.settings.store import SettingsStore
from tests.test_prospective_paper import setup, confirm, bar, Provider, CREATED, OPEN, BAR


def enabled():
    return Monitoring(paper_monitor_enabled=True)


def monitor(service, **kwargs):
    return PaperMonitor(service, settings=enabled, **kwargs)


def test_once_no_work_no_network_and_status(setup):
    service, provider, _ = setup
    run = monitor(service).run(once=True)
    assert run['status'] == 'NO_WORK' and run['trigger_type'] == 'SCHEDULED'
    assert run['completed_at'] and not provider.calls
    assert not service.ledger.all()
    status = read_status(service.ledger.path, settings=enabled())
    assert status['configured'] and status['process_status'] == 'NOT DETECTED'
    assert status['heartbeat'] and status['phase'] == 'STOPPED'
    assert status['last_run']['run_id'] == run['run_id']
    assert status['last_success'] is None and status['last_failure'] is None


def test_no_work_preserves_previous_scheduled_success(setup):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(h=111)]
    now[0] = OPEN + BAR
    success = monitor(service).run(once=True)
    assert success['status'] == 'SUCCESS' and success['trades_closed'] == 1
    calls = len(provider.calls)
    idle = monitor(service).run(once=True)
    status = read_status(service.ledger.path, settings=enabled())
    assert idle['status'] == 'NO_WORK' and idle['errors_count'] == 0
    assert len(provider.calls) == calls
    assert status['last_run']['run_id'] == idle['run_id']
    assert status['last_success']['run_id'] == success['run_id']
    assert status['last_failure'] is None


def test_disabled_default_and_legacy_settings(setup):
    service, provider, _ = setup
    assert not AutoTSettings.model_validate({'monitoring': {'paper_update_interval_minutes': 5}}).monitoring.paper_monitor_enabled
    assert PaperMonitor(service, settings=Monitoring).run(once=True) is None
    assert not service.ledger.recent_runs() and not provider.calls
    assert not monitor_active(service.ledger.path)


@pytest.mark.parametrize('bars, expected, reason', [
    ([bar()], 'OPEN', None), ([bar(l=94)], 'CLOSED', 'STOP'),
    ([bar(h=111)], 'CLOSED', 'TARGET'), ([bar(h=111, l=94)], 'CLOSED', 'STOP'),
])
def test_once_pending_execution_and_repeat_idempotency(setup, bars, expected, reason):
    service, provider, now = setup
    trade = confirm(service)
    provider.bars = bars
    now[0] = OPEN + BAR
    run = monitor(service).run(once=True)
    saved = service.ledger.get(trade['trade_id'])
    assert saved['status'] == expected and saved['exit_reason'] == reason
    assert run['trades_opened'] == 1
    events = service.ledger.events(trade['trade_id'])
    summaries = service.ledger.summaries()
    monitor(service).run(once=True)
    assert service.ledger.get(trade['trade_id']) == saved
    assert service.ledger.events(trade['trade_id']) == events
    assert service.ledger.summaries() == summaries
    assert len(service.ledger.all()) == 1


def test_restart_catches_up_open_position_in_order(setup):
    service, provider, now = setup
    trade = confirm(service)
    provider.bars = [bar()]
    now[0] = OPEN + BAR
    monitor(service).run(once=True)
    provider.bars += [bar(c=102, stamp=OPEN+BAR), bar(h=112, stamp=OPEN+2*BAR)]
    restarted = PaperTradingService(Ledger(service.ledger.path), provider, clock=lambda: OPEN+3*BAR)
    run = monitor(restarted).run(once=True)
    assert run['bars_processed'] == 2 and run['trades_closed'] == 1
    assert provider.calls[-1][1] == OPEN + BAR
    saved = restarted.ledger.get(trade['trade_id'])
    assert saved['closed_at'] == (OPEN+2*BAR).isoformat()
    stamps = [e['bar_time'] for e in restarted.ledger.events(trade['trade_id']) if e['event_type']=='POSITION_CHECKED']
    assert stamps == [str((OPEN+i*BAR).isoformat()) for i in range(3)]


def test_incomplete_and_not_yet_eligible_avoid_network(setup):
    service, provider, now = setup
    confirm(service)
    for stamp in (CREATED, OPEN, OPEN+BAR-timedelta(seconds=1)):
        now[0] = stamp
        monitor(service).run(once=True)
    assert not provider.calls
    provider.bars = [bar(), bar(h=112, stamp=OPEN+BAR)]
    now[0] = OPEN + BAR
    monitor(service).run(once=True)
    assert service.ledger.all()[0]['status'] == 'OPEN'


def test_failure_recovery_and_missing_bar_review(setup):
    service, provider, now = setup
    trade = confirm(service)
    now[0] = OPEN + 2*BAR
    def fail(*a, **k):
        raise HistoryUnavailable('temporary provider failure')
    provider.get_intraday_bars = fail
    assert monitor(service).run(once=True)['status'] == 'FAILED'
    failed = service.ledger.get(trade['trade_id'])
    assert failed['review_required'] and failed['fill_price'] is None
    assert failed['last_checked_at'] is None
    service.provider = Provider([bar(stamp=OPEN+BAR)])
    assert monitor(service).run(once=True)['status'] == 'PARTIAL'
    missing = service.ledger.get(trade['trade_id'])
    assert missing['review_required'] and missing['last_checked_at'] is None
    events = service.ledger.events(trade['trade_id'])
    monitor(service).run(once=True)
    assert service.ledger.events(trade['trade_id']) == events
    service.provider.bars = [bar(), bar(stamp=OPEN+BAR)]
    assert monitor(service).run(once=True)['status'] == 'SUCCESS'
    assert not service.ledger.get(trade['trade_id'])['review_required']
    status = read_status(service.ledger.path, settings=enabled())
    assert status['last_success']['status'] == 'SUCCESS'
    assert status['last_failure']['status'] == 'PARTIAL'


def test_manual_and_scheduled_updates_serialize(setup):
    service, provider, now = setup
    trade = confirm(service)
    now[0] = OPEN + BAR
    entered, release, manual_started = threading.Event(), threading.Event(), threading.Event()
    def fetch(*a, **k):
        entered.set()
        assert release.wait(5)
        return Provider([bar()]).get_intraday_bars(*a, **k)
    provider.get_intraday_bars = fetch
    other = PaperTradingService(Ledger(service.ledger.path), provider, clock=lambda: now[0])
    def manual():
        manual_started.set()
        return other.update_positions()
    with ThreadPoolExecutor(max_workers=2) as pool:
        scheduled = pool.submit(monitor(service).run, once=True)
        try:
            assert entered.wait(5)
            manual_job = pool.submit(manual)
            assert manual_started.wait(5)
            assert not manual_job.done()
            assert len(service.ledger.recent_runs()) == 1
        finally:
            release.set()
        assert scheduled.result()['status'] == 'SUCCESS'
        manual_job.result()
    events = service.ledger.events(trade['trade_id'])
    assert sum(e['event_type']=='ENTRY_FILLED' for e in events) == 1
    assert sum(e['event_type']=='POSITION_CHECKED' for e in events) == 1
    assert {r['trigger_type'] for r in service.ledger.recent_runs()} == {'MANUAL','SCHEDULED'}
    assert all(r['status']=='SUCCESS' for r in service.ledger.recent_runs())


class VirtualTime:
    def __init__(self):
        self.seconds = 0
        self.stopped = False
        self.waits = []
        self.on_wait = lambda: None
    def monotonic(self):
        return self.seconds
    def clock(self):
        return CREATED + timedelta(seconds=self.seconds)
    def is_set(self):
        return self.stopped
    def wait(self, seconds):
        assert 0 < seconds <= 15
        self.waits.append(seconds)
        self.seconds += seconds
        self.on_wait()
        return self.stopped


@pytest.mark.parametrize('duration,expected', [(10, [0,300,600]), (420, [0,600,1200])])
def test_continuous_cadence_skips_overrun_without_drift(setup, duration, expected):
    service, _, _ = setup
    timer = VirtualTime()
    starts = []
    original = service.update_positions
    def update(**kwargs):
        starts.append(timer.seconds)
        original(**kwargs)
        timer.seconds += duration
        if len(starts) == 3:
            timer.stopped = True
    service.update_positions = update
    monitor(service, stop=timer, monotonic=timer.monotonic, clock=timer.clock).run()
    assert starts == expected and timer.waits
    assert not monitor_active(service.ledger.path)


def test_disable_while_waiting_and_live_heartbeat(setup):
    service, _, _ = setup
    timer = VirtualTime()
    config = [enabled()]
    observed = []
    def wait():
        observed.append(read_status(service.ledger.path, settings=config[0]))
        config[0] = Monitoring()
    timer.on_wait = wait
    PaperMonitor(service, settings=lambda: config[0], stop=timer,
                 monotonic=timer.monotonic, clock=timer.clock).run()
    assert len(service.ledger.recent_runs()) == 1
    assert observed[0]['process_status'] == 'ACTIVE'
    assert observed[0]['next_expected_run'] == (CREATED+timedelta(minutes=5)).isoformat()
    assert observed[0]['phase'] == 'WAITING'


def test_fatal_error_terminates_and_releases_lock(setup):
    service, provider, now = setup
    confirm(service)
    now[0] = OPEN+BAR
    def fatal(*a, **k):
        raise RuntimeError('programming defect')
    provider.get_intraday_bars = fatal
    with pytest.raises(RuntimeError, match='programming defect'):
        monitor(service).run()
    assert not monitor_active(service.ledger.path)
    assert service.ledger.recent_runs()[0]['status'] == 'FAILED'
    assert read_status(service.ledger.path, settings=enabled())['phase'] == 'STOPPED'


def test_interrupted_scheduled_runs_recovered_without_touching_manual(setup):
    service, _, _ = setup
    scheduled = service.ledger.start_run('fixture', CREATED.isoformat(), 'SCHEDULED')
    manual = service.ledger.start_run('fixture', CREATED.isoformat())
    monitor(service).run(once=True)
    assert service.ledger.get_run(scheduled)['status'] == 'FAILED'
    assert json.loads(service.ledger.get_run(scheduled)['summary_json'])['error_category'] == 'PROCESS_INTERRUPTED'
    assert service.ledger.get_run(manual)['status'] == 'RUNNING'


def test_cli_disabled_and_status_do_not_create_database(capsys):
    from autot.runtime import data_dir
    assert main(['--status']) == 0
    assert json.loads(capsys.readouterr().out)['process_status'] == 'NOT DETECTED'
    assert main(['--once']) == 0
    assert 'disabled' in capsys.readouterr().out
    assert not data_dir().exists()


def save_enabled():
    settings = AutoTSettings(monitoring=enabled())
    SettingsStore().save(settings, expected_version=0)


@pytest.mark.parametrize('shutdown', ['graceful', 'crash'])
def test_real_process_single_instance_and_recovery(shutdown):
    # Child CLI inherits the autouse fixture's isolated AUTOT_DATA_DIR.
    from autot.runtime import data_dir
    assert data_dir() != Path(__file__).resolve().parents[1] / 'data_storage'
    save_enabled()
    command = [sys.executable, '-m', 'autot.paper_monitor']
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            status = read_status()
            if status['phase']=='WAITING':
                break
            assert child.poll() is None
            time.sleep(.02)
        else:
            pytest.fail('Monitor did not become ready')
        second = subprocess.run(command+['--once'], capture_output=True, text=True, timeout=10)
        assert second.returncode == 2 and 'Another paper monitor' in second.stderr
        assert read_status()['process_status'] == 'ACTIVE'
        child.send_signal(signal.SIGINT if shutdown=='graceful' else signal.SIGKILL)
        child.communicate(timeout=10)
        assert child.returncode == (0 if shutdown=='graceful' else -signal.SIGKILL)
        assert read_status()['process_status'] == 'NOT DETECTED'
        restarted = subprocess.run(command+['--once'], capture_output=True, text=True, timeout=10)
        assert restarted.returncode == 0
        assert json.loads(restarted.stdout)['status'] == 'NO_WORK'
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)


def test_run_schema_migration_preserves_history_and_trade_bytes(setup):
    service, provider, now = setup
    trade = confirm(service)
    provider.bars = [bar()]
    now[0] = OPEN+BAR
    service.update_positions()
    with service.ledger.connection() as db:
        before = [tuple(r) for r in db.execute('SELECT * FROM trades')]
        events = [tuple(r) for r in db.execute('SELECT * FROM paper_trade_events')]
        runs = [tuple(r) for r in db.execute('SELECT * FROM paper_update_runs')]
        schema = db.execute("SELECT sql FROM sqlite_master WHERE name='paper_update_runs'").fetchone()[0]
        legacy = schema.replace('paper_update_runs', 'old_runs', 1).replace(
            "trigger_type IN ('MANUAL','SCHEDULED')", "trigger_type = 'MANUAL'").replace(
            ",'NO_WORK'", '')
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        db.execute(legacy)
        db.execute('INSERT INTO old_runs SELECT * FROM paper_update_runs')
        db.execute('DROP TABLE paper_update_runs')
        db.execute('ALTER TABLE old_runs RENAME TO paper_update_runs')
    migrated = Ledger(service.ledger.path)
    with migrated.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM trades')] == before
        assert [tuple(r) for r in db.execute('SELECT * FROM paper_trade_events')] == events
        assert [tuple(r) for r in db.execute('SELECT * FROM paper_update_runs')] == runs
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    monitor(PaperTradingService(migrated, provider, clock=lambda: now[0])).run(once=True)
    assert migrated.events(trade['trade_id']) == service.ledger.events(trade['trade_id'])


def test_legacy_settings_hash_loads_without_rewriting_or_enabling(tmp_path):
    from autot.settings.models import SettingsState, canonical, configuration_hash
    state = SettingsState(settings_version=1).model_dump(mode='json')
    state['settings']['monitoring'].pop('paper_monitor_enabled')
    path = tmp_path/'legacy-settings.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE revisions (version INTEGER, payload TEXT, hash TEXT)')
        db.execute('INSERT INTO revisions VALUES (1, ?, ?)', (canonical(state), configuration_hash(state)))
    before = path.read_bytes()
    store = SettingsStore(path)
    loaded = store.load()
    assert not store.warning and loaded.settings_version == 1
    assert not loaded.settings.monitoring.paper_monitor_enabled
    assert path.read_bytes() == before


def test_settings_enable_persists_without_profile_hash_change():
    store = SettingsStore()
    before = store.load()
    save_enabled()
    after = store.load()
    assert after.settings.monitoring.paper_monitor_enabled
    assert after.profile == before.profile


def test_monitor_preserves_snapshots_analysis_and_admission(setup, monkeypatch):
    from autot.strategy_analysis.service import StrategyAnalysisService
    from tests.test_strategy_analysis import seed
    from autot.application import scanner_service
    service, provider, now = setup
    closed = seed(service.ledger)
    trade = confirm(service)
    before_analysis = StrategyAnalysisService(service.ledger).report()
    with service.ledger.connection() as db:
        snapshots = [tuple(r) for r in db.execute('SELECT trade_id,snapshot FROM trades ORDER BY rowid')]
    def forbidden(*a, **k):
        pytest.fail('Monitor attempted scanner/confirmation/admission')
    monkeypatch.setattr(service, 'confirm', forbidden)
    monkeypatch.setattr(service.ledger, 'confirm', forbidden)
    monkeypatch.setattr(service, 'preview_admission', forbidden)
    monkeypatch.setattr(scanner_service, 'build_scan_rankings', forbidden)
    monkeypatch.setattr(scanner_service, 'run_scan', forbidden)
    provider.bars = [bar()]
    now[0] = OPEN+BAR
    monitor(service).run(once=True)
    assert len(service.ledger.all()) == 2
    with service.ledger.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT trade_id,snapshot FROM trades ORDER BY rowid')] == snapshots
    assert service.ledger.get(closed['trade_id']) == closed
    assert StrategyAnalysisService(service.ledger).report() == before_analysis
    assert service.ledger.get(trade['trade_id'])['quantity'] == trade['quantity']


def test_monitor_preserves_gap_capital_protection(setup):
    service, provider, now = setup
    for i in range(5):
        confirm(service, key=str(i), create_another=True)
    provider.bars = [bar(o=102, l=100)]
    now[0] = OPEN+BAR
    run = monitor(service).run(once=True)
    assert run['status'] == 'SUCCESS'
    assert all(t['fill_price'] == '102' and t['quantity'] == 14 for t in service.ledger.all())
    assert service.ledger.summaries()['USD']['reserved'] == 7140


def test_interval_change_reschedules_and_no_work_never_scans(setup):
    service, _, _ = setup
    timer = VirtualTime()
    config = [enabled()]
    starts = []
    original = service.update_positions
    def update(**kwargs):
        starts.append(timer.seconds)
        original(**kwargs)
        if len(starts) == 2:
            timer.stopped = True
    service.update_positions = update
    def wait():
        config[0] = Monitoring(paper_monitor_enabled=True, paper_update_interval_minutes=1)
    timer.on_wait = wait
    PaperMonitor(service, settings=lambda: config[0], stop=timer,
                 monotonic=timer.monotonic, clock=timer.clock).run()
    assert starts == [0, 75]


def test_continuous_recovers_on_later_cycle(setup):
    service, provider, now = setup
    confirm(service)
    now[0] = OPEN+BAR
    timer = VirtualTime()
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise HistoryUnavailable('temporary')
        timer.stopped = True
        return Provider([bar()]).get_intraday_bars(*args, **kwargs)
    provider.get_intraday_bars = fetch
    monitor(service, stop=timer, monotonic=timer.monotonic, clock=timer.clock).run()
    assert [r['status'] for r in service.ledger.recent_runs()] == ['SUCCESS', 'FAILED']
    assert timer.seconds == 300 and service.ledger.all()[0]['status'] == 'OPEN'


def test_scheduled_process_waits_for_manual_update_lock():
    save_enabled()
    ledger = Ledger()
    command = [sys.executable, '-m', 'autot.paper_monitor', '--once']
    child = None
    try:
        with database_lock(ledger.path, 'update'):
            child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic()+10
            while time.monotonic()<deadline:
                if read_status()['phase'] == 'UPDATING':
                    break
                assert child.poll() is None
                time.sleep(.02)
            else:
                pytest.fail('Child did not reach the update lock')
            assert child.poll() is None
            assert not ledger.recent_runs()
        out, err = child.communicate(timeout=10)
        assert child.returncode == 0, err
        assert json.loads(out)['status'] == 'NO_WORK'
        assert not monitor_active(ledger.path)
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
