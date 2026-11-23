"""Offline restart and operational regressions; never use the operator's data."""
import json
import os
import signal

import pytest

from autot.application.recovery import diagnostics
from autot.application.scan_store import ScanStore
from autot.daily_scanner import DailyScanner, active, request_from_state
from autot.ops import main
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.locking import database_lock, lock_path, MonitorAlreadyRunning
from autot.paper_trade.service import PaperTradingService
from autot.settings.models import SettingsState
from tests.test_paper_monitor import monitor
from tests.test_prospective_paper import setup, confirm, bar, OPEN, BAR
from tests.test_daily_scanner import scanner, executor, enabled


@pytest.mark.parametrize('initial_open', [False, True])
def test_restart_preserves_trades_and_never_replays_committed_actions(setup, initial_open):
    service, provider, clock = setup
    trade = confirm(service)
    provider.bars = [bar()]
    clock[0] = OPEN + BAR
    if initial_open:
        monitor(service).run(once=True)
    before = service.ledger.get(trade['trade_id'])
    restarted = PaperTradingService(Ledger(service.ledger.path), provider, clock=lambda: clock[0])
    assert restarted.ledger.get(trade['trade_id']) == before
    monitor(restarted).run(once=True)
    assert restarted.ledger.get(trade['trade_id'])['status'] == 'OPEN'
    provider.bars.append(bar(h=112, stamp=OPEN + BAR))
    clock[0] = OPEN + 2*BAR
    monitor(restarted).run(once=True)
    saved = restarted.ledger.get(trade['trade_id'])
    events = restarted.ledger.events(trade['trade_id'])
    assert saved['status'] == 'CLOSED'
    for _ in range(2):
        again = PaperTradingService(Ledger(service.ledger.path), provider, clock=lambda: clock[0])
        monitor(again).run(once=True)
        assert again.ledger.get(trade['trade_id']) == saved
        assert again.ledger.events(trade['trade_id']) == events
        assert len(again.ledger.all()) == 1
    assert sum(e['event_type'] == 'ENTRY_FILLED' for e in events) == 1


def test_scanner_restart_preserves_result_and_consumed_slot():
    first = scanner()
    first.state = lambda: enabled(daily_scan_time_local='17:00')
    run = first.cycle()
    assert run['status'] == 'SUCCESS'
    saved = first.store.latest()
    restarted = scanner(store=ScanStore(first.store.path))
    restarted.state = first.state
    for _ in range(2):
        assert restarted.cycle() is None
        assert restarted.store.runs() == [run]
        assert restarted.store.latest() == saved


def test_dead_lock_file_reused_without_unlinking():
    ledger = Ledger()
    path = lock_path(ledger.path, 'monitor')
    path.write_text('stale PID metadata is not ownership')
    inode = path.stat().st_ino
    with database_lock(ledger.path, 'monitor', blocking=False):
        assert active(ledger.path, 'monitor')
        with pytest.raises(MonitorAlreadyRunning):
            with database_lock(ledger.path, 'monitor', blocking=False):
                pass
    assert not active(ledger.path, 'monitor')
    assert path.stat().st_ino == inode


def test_healthy_and_missing_diagnostics_are_read_only(capsys):
    from autot.runtime import data_dir
    report = diagnostics(integrity=True)
    assert all(d['state'] == 'MISSING' for d in report['databases'].values())
    assert not data_dir().exists()
    Ledger()
    ScanStore()
    before = {p: p.read_bytes() for p in data_dir().rglob('*.sqlite3')}
    report = diagnostics(integrity=True)
    assert not report['errors'] and not report['recovery_required']
    assert report['databases']['paper']['pending'] == 0
    assert report['databases']['scanner']['state'] == 'OK'
    assert main(['check']) == 0
    assert json.loads(capsys.readouterr().out)['recovery']['errors'] == []
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize('payload', [b'not sqlite', b''])
def test_corrupt_or_empty_existing_database_is_not_silently_initialized(payload, capsys):
    from autot.runtime import data_dir
    path = data_dir() / 'paper_trading/ledger.sqlite3'
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    report = diagnostics(integrity=True)
    assert report['databases']['paper']['state'] == 'ERROR'
    assert main(['check']) == 1
    capsys.readouterr()
    assert path.read_bytes() == payload


def test_recovery_check_does_not_recover_orphan():
    store = ScanStore()
    run = store.create(request_from_state(SettingsState()))
    run['status'] = 'RUNNING'
    store.save(run)
    assert diagnostics()['recovery_required']
    assert store.get(run['scan_run_id']) == run
    DailyScanner(store).recover()
    recovered = store.get(run['scan_run_id'])
    assert recovered['status'] == 'FAILED'
    DailyScanner(store).recover()
    assert store.get(run['scan_run_id']) == recovered


@pytest.mark.parametrize('signum', [signal.SIGINT, signal.SIGTERM])
def test_scanner_signal_during_work_finishes_successfully(signum, monkeypatch):
    from autot import daily_scanner as ds
    service = scanner()
    service.state = lambda: enabled(daily_scan_time_local='17:00')
    def finish(request, diagnostics, stage):
        os.kill(os.getpid(), signum)
        return executor(request, diagnostics, stage)
    service.executor = finish
    monkeypatch.setattr(ds, 'DailyScanner', lambda: service)
    monkeypatch.setattr(ds, 'load_state', service.state)
    assert ds.main([]) == 0
    assert service.stop.is_set()
    assert service.store.runs()[0]['status'] == 'SUCCESS'
    assert not active(service.store.path, 'scheduler')
    assert not active(service.store.path, 'scan')
    with service.store.connection() as db:
        phases = [json.loads(r[0])['phase'] for r in db.execute('SELECT payload FROM scanner_status')]
    assert phases and set(phases) == {'STOPPED'}


def test_validate_rejects_duplicate_service(capsys):
    from autot.settings.store import SettingsStore
    from autot.settings.models import AutoTSettings, Monitoring
    SettingsStore().save(AutoTSettings(monitoring=Monitoring(paper_monitor_enabled=True)), expected_version=0)
    ledger = Ledger()
    with database_lock(ledger.path, 'monitor'):
        assert main(['validate', '--service', 'paper']) == 1
    assert 'already owns' in capsys.readouterr().out
    assert main(['validate', '--service', 'paper']) == 0


@pytest.mark.parametrize('signum', [signal.SIGINT, signal.SIGTERM])
def test_notification_shutdown_finishes_delivery_and_restores_handlers(signum, monkeypatch):
    from types import SimpleNamespace
    from autot import notifications
    original = signal.getsignal(signum)
    calls = []
    monkeypatch.setattr(notifications, 'configuration', lambda: SimpleNamespace(notifications_enabled=True))
    def deliver(ledger):
        os.kill(os.getpid(), signum)
        calls.append('delivery completed')
    monkeypatch.setattr(notifications, 'process', deliver)
    assert notifications.main([]) == 0
    assert calls == ['delivery completed']
    assert signal.getsignal(signum) == original
