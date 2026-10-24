"""Offline persistence, migration, concurrency and update-run audit contracts."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from autot.paper_trade import audit
from autot.paper_trade.intraday import HistoryUnavailable
from autot.paper_trade.ledger import Ledger, ConcurrentUpdate
from autot.paper_trade.service import PaperTradingService, STATE_FIELDS
from tests.test_prospective_paper import setup, confirm, bar, OPEN, BAR, CREATED, Provider


def kinds(ledger, trade):
    return [e['event_type'] for e in ledger.events(trade['trade_id'])]


def legacy_copy(service, path):
    """Copy only the exact V1 schema/data, without audit tables."""
    with service.ledger.connection() as source, sqlite3.connect(path) as dest:
        for table in ('accounts', 'trades'):
            sql = source.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
            dest.execute(sql)
            rows = source.execute('SELECT * FROM ' + table).fetchall()
            for row in rows:
                dest.execute('INSERT INTO ' + table + ' VALUES (' + ','.join('?' for _ in row) + ')', tuple(row))
        dest.execute('CREATE UNIQUE INDEX trade_intent_unique ON trades(opportunity_id, intent_key)')


def test_legacy_migration_preserves_all_rows_ids_and_baselines_once(setup, tmp_path):
    service, provider, now = setup
    first = confirm(service)
    confirm(service, side='SELL', key='short')
    cancelled = confirm(service, key='cancel', create_another=True)
    service.cancel(cancelled['trade_id'])
    provider.bars = [bar(h=112)]
    now[0] = OPEN + BAR
    service.update_positions()
    path = tmp_path / 'legacy.db'
    legacy_copy(service, path)
    with sqlite3.connect(path) as db:
        before = db.execute('SELECT * FROM trades').fetchall()
        accounts = db.execute('SELECT * FROM accounts').fetchall()
    with ThreadPoolExecutor(max_workers=4) as pool:
        ledgers = list(pool.map(lambda _: Ledger(path), range(4)))
    ledger = ledgers[0]
    with ledger.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM trades')] == before
        assert [tuple(r) for r in db.execute('SELECT * FROM accounts')] == accounts
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    for t in ledger.all():
        events = ledger.events(t['trade_id'])
        assert len(events) == 1
        e = events[0]
        assert e['event_type'] == 'AUDIT_BASELINE_CREATED'
        assert e['event_time'] == e['recorded_at']
        assert json.loads(e['payload_json']) == t
        assert e['revision_before'] == e['revision_after'] == t['revision']
    assert ledger.get(first['trade_id'])['trade_id'] == first['trade_id']
    assert ledger.all() == Ledger(path).all()
    assert all(len(Ledger(path).events(t['trade_id'])) == 1 for t in ledger.all())


def test_migration_failure_rolls_back_schema_and_baselines(setup, tmp_path, monkeypatch):
    service, _, _ = setup
    confirm(service)
    path = tmp_path / 'legacy.db'
    legacy_copy(service, path)
    original = audit.append
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('injected migration failure')
    monkeypatch.setattr(audit, 'append', fail)
    with pytest.raises(RuntimeError):
        Ledger(path)
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='paper_trade_events'").fetchall()
        assert db.execute('SELECT count(*) FROM trades').fetchone()[0] == 1
    monkeypatch.setattr(audit, 'append', original)
    assert len(Ledger(path).all()) == 1


def test_created_and_cancel_are_atomic_idempotent_events(setup):
    service, _, _ = setup
    t = confirm(service)
    assert kinds(service.ledger, t) == ['TRADE_CREATED']
    assert confirm(service, key='another-review')['trade_id'] == t['trade_id']
    service.cancel(t['trade_id'])
    service.cancel(t['trade_id'])
    assert kinds(service.ledger, t) == ['TRADE_CREATED', 'TRADE_CANCELLED']


@pytest.mark.parametrize('side,high,low,exit_kind', [
    ('BUY', 112, 96, 'TARGET_HIT'), ('BUY', 104, 94, 'STOP_HIT'),
    ('SELL', 104, 89, 'TARGET_HIT'), ('SELL', 106, 96, 'STOP_HIT')])
def test_fill_then_exit_event_sequence(setup, side, high, low, exit_kind):
    service, provider, now = setup
    t = confirm(service, side)
    provider.bars = [bar()]
    now[0] = OPEN + BAR
    opened = service.update_positions()[0]
    assert kinds(service.ledger, t) == ['TRADE_CREATED', 'ENTRY_ELIGIBLE', 'ENTRY_BAR_PROCESSED',
                                      'ENTRY_FILLED', 'POSITION_CHECKED', 'POSITION_UPDATED']
    provider.bars.append(bar(h=high, l=low, stamp=OPEN + BAR))
    now[0] = OPEN + 2 * BAR
    closed = service.update_positions()[0]
    assert kinds(service.ledger, t)[-3:] == ['POSITION_CHECKED', exit_kind, 'TRADE_CLOSED']
    events = service.ledger.events(t['trade_id'])
    assert events[-1]['realized_pnl'] == closed['realized_pnl']
    assert events[-1]['status_before'] == 'OPEN' and events[-1]['status_after'] == 'CLOSED'
    assert events[-1]['revision_before'] == opened['revision']
    assert events[-1]['revision_after'] == closed['revision']
    assert events[-1]['update_run_id'] == service.ledger.recent_runs()[0]['run_id']


def test_same_bar_fill_and_stop_first_audit(setup):
    service, provider, now = setup
    t = confirm(service)
    provider.bars = [bar(h=112, l=94)]
    now[0] = OPEN + BAR
    closed = service.update_positions()[0]
    assert closed['intrabar_sequence_ambiguous']
    events = service.ledger.events(t['trade_id'])
    fill = next(e for e in events if e['event_type'] == 'ENTRY_FILLED')
    assert fill['status_before'] == 'PENDING_ENTRY' and fill['status_after'] == 'OPEN'
    assert kinds(service.ledger, t)[-2:] == ['STOP_HIT', 'TRADE_CLOSED']
    assert json.loads(events[-1]['payload_json'])['intrabar_sequence_ambiguous']


def test_manual_close_events(setup):
    service, provider, now = setup
    t = confirm(service)
    provider.bars = [bar()]
    now[0] = OPEN + BAR
    service.update_positions()
    service.request_manual_close(t['trade_id'])
    service.request_manual_close(t['trade_id'])
    provider.bars.append(bar(o=103, l=100, stamp=OPEN + BAR))
    now[0] = OPEN + 2 * BAR
    service.update_positions()
    types = kinds(service.ledger, t)
    assert types.count('MANUAL_CLOSE_REQUESTED') == 1
    assert types[-2:] == ['MANUAL_CLOSE_EXECUTED', 'TRADE_CLOSED']


@pytest.mark.parametrize('missing', [True, False])
def test_review_failure_and_repeated_failure_events(setup, missing):
    service, provider, now = setup
    t = confirm(service)
    if not missing:
        def fail(*args, **kwargs):
            raise HistoryUnavailable('private secret')
        provider.get_intraday_bars = fail
    now[0] = OPEN + BAR
    service.update_positions()
    events = service.ledger.events(t['trade_id'])
    types = kinds(service.ledger, t)
    assert 'REVIEW_REQUIRED' in types
    assert ('MISSING_EXPECTED_BAR' if missing else 'DATA_UNAVAILABLE') in types
    assert 'ENTRY_FILLED' not in types
    service.update_positions()
    restarted = PaperTradingService(Ledger(service.ledger.path), provider, clock=lambda: now[0])
    restarted.update_positions()
    assert restarted.ledger.events(t['trade_id']) == events
    runs = service.ledger.recent_runs()
    assert len(runs) == 3
    assert all(r['status'] == ('PARTIAL' if missing else 'FAILED') for r in runs)
    assert 'private secret' not in json.dumps(events)


def test_repeated_bars_restart_and_no_due_run(setup):
    service, provider, now = setup
    t = confirm(service)
    provider.bars = [bar()]
    now[0] = OPEN + BAR
    service.update_positions()
    before = service.ledger.events(t['trade_id'])
    service.update_positions()
    restarted = PaperTradingService(Ledger(service.ledger.path), provider, clock=lambda: now[0])
    restarted.update_positions()
    assert restarted.ledger.events(t['trade_id']) == before
    runs = service.ledger.recent_runs()
    assert len(runs) == 3 and all(r['status'] == 'SUCCESS' for r in runs)
    assert runs[0]['bars_processed'] == runs[1]['bars_processed'] == 0
    assert runs[2]['bars_processed'] == 1 and runs[2]['trades_opened'] == 1
    assert all(r['completed_at'] and r['trigger_type'] == 'MANUAL' for r in runs)


@pytest.mark.parametrize('operation', ['create', 'fill', 'close', 'cancel', 'manual'])
def test_event_insert_failure_rolls_back_state(setup, monkeypatch, operation):
    service, provider, now = setup
    t = confirm(service)
    provider.bars = [bar()]
    if operation in ('close', 'manual'):
        now[0] = OPEN + BAR
        t = service.update_positions()[0]
    before = service.ledger.all()
    events = service.ledger.events(t['trade_id'])
    original = audit.append
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.IntegrityError('injected event failure')
    monkeypatch.setattr(audit, 'append', fail)
    with pytest.raises(sqlite3.IntegrityError):
        if operation == 'create':
            confirm(service, key='new', create_another=True)
        elif operation == 'cancel':
            service.cancel(t['trade_id'])
        elif operation == 'manual':
            service.request_manual_close(t['trade_id'])
        else:
            if operation == 'close':
                provider.bars.append(bar(h=112, stamp=OPEN + BAR))
            now[0] = OPEN + (2 if operation == 'close' else 1) * BAR
            service.update_positions()
    assert service.ledger.all() == before
    assert service.ledger.events(t['trade_id']) == events
    if operation in ('fill', 'close'):
        assert service.ledger.recent_runs()[0]['status'] == 'FAILED'


def test_append_only_and_foreign_keys(setup):
    service, _, _ = setup
    t = confirm(service)
    for sql in ('DELETE FROM paper_trade_events', "UPDATE paper_trade_events SET reason='changed'"):
        with pytest.raises(sqlite3.IntegrityError, match='append-only'), service.ledger.connection() as db:
            db.execute(sql)
    assert len(service.ledger.events(t['trade_id'])) == 1


def test_partial_run_preserves_first_trade_and_audits_error(setup):
    service, provider, now = setup
    confirm(service)
    confirm(service, side='SELL', key='second')
    calls = []
    def fetch(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise HistoryUnavailable('offline')
        return Provider([bar()]).get_intraday_bars(*args, **kwargs)
    provider.get_intraday_bars = fetch
    now[0] = OPEN + BAR
    service.update_positions()
    run = service.ledger.recent_runs()[0]
    assert run['status'] == 'PARTIAL' and run['trades_considered'] == 2
    assert run['trades_opened'] == 1 and run['bars_processed'] == 1
    assert run['errors_count'] == 1 and run['warnings_count'] == 1


def test_fatal_run_marked_failed(setup, monkeypatch):
    service, _, _ = setup
    def fail():
        raise RuntimeError('unreadable')
    monkeypatch.setattr(service.ledger, 'all', fail)
    with pytest.raises(RuntimeError):
        service.update_positions()
    run = service.ledger.recent_runs()[0]
    assert run['status'] == 'FAILED' and run['completed_at']
    assert json.loads(run['summary_json'])['aborted']


def test_interrupted_run_remains_running_not_success(setup):
    service, _, _ = setup
    service.ledger.start_run('Offline', CREATED.isoformat())
    run = Ledger(service.ledger.path).recent_runs()[0]
    assert run['status'] == 'RUNNING' and run['completed_at'] is None


def test_stale_writer_cannot_append_events(setup):
    service, _, _ = setup
    t = confirm(service)
    service.cancel(t['trade_id'])
    before = service.ledger.events(t['trade_id'])
    state = {key: t[key] for key in STATE_FIELDS}
    with pytest.raises(ConcurrentUpdate):
        service.ledger.update(t, state, events=[audit.event('POSITION_CHECKED', state, when=OPEN.isoformat())])
    assert service.ledger.events(t['trade_id']) == before


def test_concurrent_monitors_only_commit_one_bar_event_set(setup):
    from threading import Barrier
    service, provider, now = setup
    trade = confirm(service)
    barrier = Barrier(2)
    def fetch(*args, **kwargs):
        barrier.wait(timeout=5)
        return Provider([bar()]).get_intraday_bars(*args, **kwargs)
    provider.get_intraday_bars = fetch
    services = [PaperTradingService(Ledger(service.ledger.path), provider, clock=lambda: OPEN + BAR)
                for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda s: s.update_positions(), services))
    types = kinds(service.ledger, trade)
    assert types.count('ENTRY_FILLED') == types.count('POSITION_CHECKED') == 1
    runs = service.ledger.recent_runs()
    assert {r['status'] for r in runs} == {'SUCCESS', 'PARTIAL'}
    assert sum(r['bars_processed'] for r in runs) == 1


def test_pending_baseline_gets_only_genuine_future_events(setup, tmp_path):
    service, provider, now = setup
    trade = confirm(service)
    path = tmp_path / 'legacy.db'
    legacy_copy(service, path)
    service.ledger = Ledger(path)
    assert kinds(service.ledger, trade) == ['AUDIT_BASELINE_CREATED']
    provider.bars = [bar()]
    now[0] = OPEN + BAR
    service.update_positions()
    types = kinds(service.ledger, trade)
    assert types.count('AUDIT_BASELINE_CREATED') == 1
    assert 'TRADE_CREATED' not in types and 'ENTRY_FILLED' in types
    assert len(service.ledger.events(trade['trade_id'])) == len(Ledger(path).events(trade['trade_id']))


def test_successful_same_bar_close_run_counts(setup):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(h=112)]
    now[0] = OPEN + BAR
    service.update_positions()
    run = service.ledger.get_run(service.last_update_run_id)
    assert run['status'] == 'SUCCESS'
    assert run['trades_updated'] == run['trades_opened'] == run['trades_closed'] == run['bars_processed'] == 1


def test_failed_gap_capital_check_does_not_leave_fill_events(setup):
    service, provider, now = setup
    for i in range(5):
        confirm(service, key=str(i), create_another=True)
    provider.bars = [bar(o=102, l=100)]
    now[0] = OPEN + BAR
    service.update_positions()
    for trade in service.ledger.all():
        assert trade['status'] == 'PENDING_ENTRY'
        assert kinds(service.ledger, trade) == ['TRADE_CREATED', 'REVIEW_REQUIRED']
    run = service.ledger.get_run(service.last_update_run_id)
    assert run['status'] == 'FAILED' and run['bars_processed'] == 0


def test_controlled_event_type_and_trade_reference(setup):
    service, _, _ = setup
    t = confirm(service)
    item = audit.event('POSITION_CHECKED', t, when=OPEN.isoformat())
    with pytest.raises(ValueError), service.ledger.connection() as db:
        audit.append(db, t, dict(item, event_type='BOGUS'), revision_before=0, revision_after=1)
    with pytest.raises(sqlite3.IntegrityError), service.ledger.connection() as db:
        audit.append(db, dict(t, trade_id='missing'), item, revision_before=0, revision_after=1)
