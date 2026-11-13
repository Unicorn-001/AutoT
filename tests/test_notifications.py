"""Offline notification contracts; runtime isolation is enforced by conftest."""
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest

from autot import notifications as n
from autot.paper_trade import audit
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.intraday import HistoryUnavailable
from autot.settings.models import Notifications, SettingsState, canonical, configuration_hash
from autot.settings.store import SettingsStore
from tests.test_prospective_paper import setup, confirm, bar, OPEN, BAR, Provider
from tests.test_paper_monitor import monitor

ENABLED = Notifications(notifications_enabled=True)


def rows(ledger):
    return n.read_status(ledger.path)['history']


def opened(setup):
    service, provider, clock = setup
    trade = confirm(service)
    provider.bars = [bar()]
    clock[0] = OPEN + BAR
    service.update_positions()
    n.project(service.ledger)
    return service, provider, clock, trade


@pytest.mark.parametrize('high,low,event', [(104,96,None), (112,96,'PAPER_TRADE_TARGET'), (104,94,'PAPER_TRADE_STOP')])
def test_lifecycle_and_idempotency(setup, high, low, event):
    service, provider, clock = setup
    trade = confirm(service)
    provider.bars = [bar(h=high,l=low)]
    clock[0] = OPEN + BAR
    service.update_positions()
    n.project(service.ledger)
    expected = {'PAPER_ENTRY_OPENED'} | ({event} if event else set())
    assert {r['event_type'] for r in rows(service.ledger)} == expected
    before = rows(service.ledger)
    n.project(service.ledger)
    service.update_positions()
    n.project(service.ledger)
    assert rows(service.ledger) == before
    entry = next(r for r in before if r['event_type']=='PAPER_ENTRY_OPENED')
    assert 'BUY opened' in n.message(entry)
    assert 'Target: 110' in n.message(entry) and 'Stop: 95' in n.message(entry)
    # Replaying the same authoritative lifecycle identity cannot create another row.
    e = next(e for e in service.ledger.events(trade['trade_id']) if e['event_type']=='ENTRY_FILLED')
    with service.ledger.connection() as db:
        audit.append(db, service.ledger.get(trade['trade_id']),
                     dict(event_type='ENTRY_FILLED', event_time=e['event_time'], bar_time=e['bar_time']),
                     revision_before=e['revision_before'], revision_after=e['revision_after'])
        db.execute('UPDATE notification_checkpoint SET event_id=0')
    n.project(service.ledger)
    assert rows(service.ledger) == before


def test_manual_close(setup):
    service, provider, clock, trade = opened(setup)
    service.request_manual_close(trade['trade_id'])
    provider.bars.append(bar(stamp=OPEN+BAR))
    clock[0] = OPEN+2*BAR
    service.update_positions()
    n.project(service.ledger)
    assert rows(service.ledger)[0]['event_type'] == 'PAPER_TRADE_MANUAL_CLOSE'


def test_failure_recovery_no_spam(setup):
    service, provider, clock = setup
    confirm(service)
    clock[0] = OPEN+BAR
    def fail(*a, **kw):
        raise HistoryUnavailable('secret should never appear')
    provider.get_intraday_bars = fail
    monitor(service).run(once=True)
    monitor(service).run(once=True)
    assert {r['event_type'] for r in rows(service.ledger)} == {
        'PAPER_REVIEW_REQUIRED', 'PROVIDER_FAILURE', 'PAPER_MONITOR_FAILED'}
    assert len(rows(service.ledger)) == 3
    service.provider = Provider([bar()])
    monitor(service).run(once=True)
    monitor(service).run(once=True)
    kinds = [r['event_type'] for r in rows(service.ledger)]
    assert kinds.count('PROVIDER_RECOVERED') == kinds.count('PAPER_MONITOR_RECOVERED') == 1
    assert 'secret' not in json.dumps(rows(service.ledger))


def test_delivery_retry_and_trade_isolation(setup):
    service, _, _, trade = opened(setup)
    before = service.ledger.get(trade['trade_id'])
    attempts = []
    class Channel:
        def send(self, notification):
            # A writer succeeds during delivery: no SQLite trade lock is held.
            with service.ledger.connection() as db:
                db.execute('BEGIN IMMEDIATE')
            attempts.append(notification['notification_id'])
            if len(attempts) == 1:
                raise OSError('credential=secret')
    channel = Channel()
    assert n.deliver(service.ledger, settings=ENABLED, channel=channel, clock=lambda: OPEN) == 0
    failed = rows(service.ledger)[0]
    assert failed['delivery_status'] == 'FAILED_RETRYABLE' and failed['attempt_count'] == 1
    assert failed['error_category'] == 'CHANNEL_FAILURE'
    assert 'secret' not in json.dumps(failed)
    assert n.deliver(service.ledger, settings=ENABLED, channel=channel, clock=lambda: OPEN) == 0
    assert n.deliver(service.ledger, settings=ENABLED, channel=channel, clock=lambda: OPEN+BAR) == 1
    assert n.deliver(service.ledger, settings=ENABLED, channel=channel, clock=lambda: OPEN+BAR) == 0
    status = n.read_status(service.ledger.path)
    assert status['pending'] == 0 and status['last_delivered']['attempt_count'] == 2
    assert status['last_failed'] is not None
    assert service.ledger.get(trade['trade_id']) == before


def test_disabled_console_and_concurrent_delivery(setup, caplog):
    service, *_ = opened(setup)
    assert n.deliver(service.ledger) == 0
    assert rows(service.ledger)[0]['attempt_count'] == 0
    with caplog.at_level(logging.INFO, logger=n.__name__):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: n.deliver(service.ledger, settings=ENABLED), range(2)))
    assert sum(results) == 1
    assert caplog.text.count('BUY opened') == 1


def test_projection_failure_replays_without_rollback(setup, monkeypatch):
    service, *_ = opened(setup)
    before = service.ledger.all()
    with service.ledger.connection() as db:
        db.execute('DELETE FROM notification_outbox')
        db.execute('UPDATE notification_checkpoint SET event_id=0')
    original = n.enqueue
    def fail(*a, **kw):
        original(*a, **kw)
        raise sqlite3.OperationalError('injected')
    monkeypatch.setattr(n, 'enqueue', fail)
    assert n.process(service.ledger) == 0
    assert not rows(service.ledger)
    assert service.ledger.all() == before
    monkeypatch.setattr(n, 'enqueue', original)
    n.project(service.ledger)
    assert len(rows(service.ledger)) == 1


def test_install_excludes_history_preserves_trades(setup):
    service, *_ = opened(setup)
    before = service.ledger.all()
    with service.ledger.connection() as db:
        for table in ('notification_outbox','notification_checkpoint','notification_health','notification_runs'):
            db.execute('DROP TABLE ' + table)
    migrated = Ledger(service.ledger.path)
    n.project(migrated)
    assert rows(migrated) == []
    assert migrated.all() == before


def test_legacy_settings_unchanged_and_cli_disabled(tmp_path):
    state = SettingsState(settings_version=1).model_dump(mode='json')
    state['settings'].pop('notifications')
    path = tmp_path/'settings.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE revisions(version INTEGER,payload TEXT,hash TEXT)')
        db.execute('INSERT INTO revisions VALUES (1,?,?)', (canonical(state), configuration_hash(state)))
    before = path.read_bytes()
    store = SettingsStore(path)
    assert not store.load().settings.notifications.notifications_enabled
    assert not store.warning and before == path.read_bytes()
    from autot.runtime import data_dir
    assert n.main(['--once']) == 0
    assert not data_dir().exists()


def test_runtime_never_uses_production_data():
    from autot.runtime import data_dir
    assert data_dir().resolve() != Path(__file__).resolve().parents[1]/'data_storage'
    ledger = Ledger()
    assert ledger.path.is_relative_to(data_dir())
    assert not ledger.all()


def test_final_failure(setup):
    service, *_ = opened(setup)
    class Reject:
        def send(self, _):
            raise n.FinalDeliveryError('private detail')
    n.deliver(service.ledger, settings=ENABLED, channel=Reject())
    assert rows(service.ledger)[0]['delivery_status']=='FAILED_FINAL'
    assert n.deliver(service.ledger, settings=ENABLED)==0


def test_retry_budget_and_backoff(setup):
    service, *_ = opened(setup)
    before = service.ledger.all()
    calls = []
    class Fail:
        def send(self, notification):
            calls.append(notification['notification_id'])
            raise OSError('credential=secret')
    for attempt in range(1, n.MAX_ATTEMPTS + 1):
        stamp = OPEN + timedelta(hours=attempt)
        assert n.deliver(service.ledger, settings=ENABLED, channel=Fail(), clock=lambda: stamp) == 0
        row = rows(service.ledger)[0]
        assert row['attempt_count'] == attempt
        if attempt < n.MAX_ATTEMPTS:
            assert row['next_attempt_at'] == (stamp + timedelta(seconds=min(3600, 30 * 2 ** (attempt - 1)))).isoformat()
    assert row['delivery_status'] == 'FAILED_FINAL'
    assert row['error_category'] == 'RETRY_EXHAUSTED'
    assert row['next_attempt_at'] is None
    assert n.deliver(service.ledger, settings=ENABLED, channel=Fail(), clock=lambda: stamp + timedelta(days=1)) == 0
    assert len(calls) == n.MAX_ATTEMPTS
    assert service.ledger.all() == before
    assert 'secret' not in json.dumps(row)


def test_interrupted_final_attempt_is_not_resent(setup):
    service, *_ = opened(setup)
    with service.ledger.connection() as db:
        db.execute('UPDATE notification_outbox SET attempt_count=?, last_attempt_at=?',
                   (n.MAX_ATTEMPTS, OPEN.isoformat()))
    class UnexpectedSend:
        def send(self, _):
            pytest.fail('Exhausted attempt budget must not send again')
    assert n.deliver(service.ledger, settings=ENABLED, channel=UnexpectedSend()) == 0
    assert rows(service.ledger)[0]['error_category'] == 'RETRY_EXHAUSTED'


def test_busy_dispatcher_does_not_block_monitor(setup, monkeypatch):
    from autot.paper_trade.locking import database_lock
    service, provider, clock = setup
    trade = confirm(service)
    provider.bars = [bar(h=112)]
    clock[0] = OPEN + BAR
    monkeypatch.setattr(n, 'configuration', lambda: ENABLED)
    with database_lock(service.ledger.path, 'notifications'):
        assert monitor(service).run(once=True)['status'] == 'SUCCESS'
    assert service.ledger.get(trade['trade_id'])['exit_reason'] == 'TARGET'
    assert all(r['attempt_count'] == 0 for r in rows(service.ledger))


def test_monitor_send_failure_does_not_fail_trade_cycle(setup, monkeypatch):
    service, provider, clock = setup
    trade = confirm(service)
    provider.bars = [bar(h=112)]
    clock[0] = OPEN+BAR
    monkeypatch.setattr(n, 'configuration', lambda: ENABLED)
    def fail(*a):
        raise OSError('private')
    monkeypatch.setattr(n.ConsoleChannel, 'send', fail)
    assert monitor(service).run(once=True)['status'] == 'SUCCESS'
    assert service.ledger.get(trade['trade_id'])['exit_reason'] == 'TARGET'
    assert all(r['delivery_status']=='FAILED_RETRYABLE' for r in rows(service.ledger))


def test_fatal_monitor_failure_is_projected(setup):
    service, provider, clock = setup
    confirm(service)
    clock[0] = OPEN+BAR
    def fail(*a, **kw):
        raise RuntimeError('private')
    provider.get_intraday_bars = fail
    with pytest.raises(RuntimeError):
        monitor(service).run(once=True)
    assert [r['event_type'] for r in rows(service.ledger)] == ['PAPER_MONITOR_FAILED']
