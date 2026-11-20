"""Durable audit projection and isolated delivery: python -m autot.notifications --once."""
import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

from autot.paper_trade.locking import database_lock
from autot.settings.store import SettingsStore

LOGGER = logging.getLogger(__name__)
MAX_ATTEMPTS = 10
EVENTS = {
    'ENTRY_FILLED': 'PAPER_ENTRY_OPENED', 'TARGET_HIT': 'PAPER_TRADE_TARGET',
    'STOP_HIT': 'PAPER_TRADE_STOP', 'MANUAL_CLOSE_EXECUTED': 'PAPER_TRADE_MANUAL_CLOSE',
    'REVIEW_REQUIRED': 'PAPER_REVIEW_REQUIRED',
}


def now():
    return datetime.now(timezone.utc)


def initialize(db):
    """Called during ledger schema setup; never backfill pre-installation history."""
    db.execute('''CREATE TABLE IF NOT EXISTS notification_checkpoint (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), event_id INTEGER NOT NULL,
        run_floor INTEGER NOT NULL)''')
    db.execute('''INSERT OR IGNORE INTO notification_checkpoint
        SELECT 1, COALESCE((SELECT MAX(event_id) FROM paper_trade_events),0),
        COALESCE((SELECT MAX(rowid) FROM paper_update_runs),0)''')
    db.execute('''CREATE TABLE IF NOT EXISTS notification_runs (run_id TEXT PRIMARY KEY)''')
    db.execute('''CREATE TABLE IF NOT EXISTS notification_health (
        scope TEXT PRIMARY KEY, failed INTEGER NOT NULL)''')
    initialize_outbox(db)


def initialize_outbox(db):
    """Shared research/trading delivery schema; no paper ledger dependency."""
    db.execute('''CREATE TABLE IF NOT EXISTS notification_outbox (
        notification_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, created_at TEXT NOT NULL,
        trade_id TEXT, symbol TEXT, currency TEXT, payload_json TEXT NOT NULL,
        delivery_status TEXT NOT NULL DEFAULT 'PENDING'
            CHECK(delivery_status IN ('PENDING','DELIVERED','FAILED_RETRYABLE','FAILED_FINAL')),
        attempt_count INTEGER NOT NULL DEFAULT 0, last_attempt_at TEXT, delivered_at TEXT,
        error_category TEXT, next_attempt_at TEXT, last_failure_at TEXT)''')
    db.execute('CREATE INDEX IF NOT EXISTS notification_delivery ON notification_outbox(delivery_status, next_attempt_at)')


def enqueue(db, key, kind, payload, created_at, trade_id=None, symbol=None, currency=None):
    db.execute('''INSERT OR IGNORE INTO notification_outbox
        (notification_id,event_type,created_at,trade_id,symbol,currency,payload_json)
        VALUES (?,?,?,?,?,?,?)''',
        (key, kind, created_at, trade_id, symbol, currency, json.dumps(payload)))


def health(db, scope, failed, key, prefix, payload, created_at):
    previous = db.execute('SELECT failed FROM notification_health WHERE scope=?', (scope,)).fetchone()
    was_failed = bool(previous and previous[0])
    if failed != was_failed:
        enqueue(db, key + ':' + prefix, prefix + ('_FAILURE' if prefix == 'PROVIDER' else '_FAILED')
                if failed else prefix + '_RECOVERED', payload, created_at)
    db.execute('INSERT INTO notification_health VALUES (?,?) ON CONFLICT(scope) '
               'DO UPDATE SET failed=excluded.failed', (scope, int(failed)))


def project(ledger):
    """Projection and checkpoint commit together; audit remains authoritative on failure."""
    with ledger.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        checkpoint = db.execute('SELECT * FROM notification_checkpoint').fetchone()
        for row in db.execute('SELECT * FROM paper_trade_events WHERE event_id>? ORDER BY event_id',
                              (checkpoint['event_id'],)).fetchall():
            kind = EVENTS.get(row['event_type'])
            if kind:
                state = json.loads(row['payload_json'])
                snapshot = json.loads(db.execute('SELECT snapshot FROM trades WHERE trade_id=?',
                                                (row['trade_id'],)).fetchone()[0])
                payload = {k: state.get(k, snapshot.get(k)) for k in
                           ('side', 'fill_price', 'exit_price', 'quantity', 'stop_loss',
                            'take_profit', 'realized_pnl')}
                payload['quantity'] = row['quantity']
                enqueue(db, 'audit:' + row['idempotency_key'], kind, payload, row['recorded_at'],
                        row['trade_id'], row['symbol'], row['currency'])
            if row['event_type'] in ('ENTRY_FILLED', 'TRADE_CANCELLED'):
                check = json.loads(row['payload_json']).get('fill_time_risk_check')
                if check and check['decision'] in ('RESIZE', 'REJECT'):
                    enqueue(db, 'fill-risk:' + row['trade_id'], 'PAPER_FILL_RISK_' + check['decision'],
                            check, row['recorded_at'], row['trade_id'], row['symbol'], row['currency'])
            db.execute('UPDATE notification_checkpoint SET event_id=?', (row['event_id'],))
        runs = db.execute('''SELECT * FROM paper_update_runs WHERE rowid>? AND status!='RUNNING'
            AND run_id NOT IN (SELECT run_id FROM notification_runs) ORDER BY rowid''',
                          (checkpoint['run_floor'],)).fetchall()
        for run in runs:
            evidence = {r[0] for r in db.execute('SELECT event_type FROM paper_trade_events WHERE update_run_id=?',
                                                (run['run_id'],))}
            payload = {'provider': run['provider'], 'error_category': 'UPDATE_UNVERIFIED'}
            if 'DATA_UNAVAILABLE' in evidence:
                health(db, 'provider:' + run['provider'], True, run['run_id'], 'PROVIDER', payload, run['completed_at'])
            elif evidence & {'POSITION_CHECKED', 'ENTRY_BAR_PROCESSED'}:
                health(db, 'provider:' + run['provider'], False, run['run_id'], 'PROVIDER',
                       {'provider': run['provider']}, run['completed_at'])
            if run['trigger_type'] == 'SCHEDULED':
                if run['status'] in ('FAILED', 'PARTIAL'):
                    health(db, 'monitor', True, run['run_id'], 'PAPER_MONITOR', payload, run['completed_at'])
                elif run['status'] == 'SUCCESS':
                    health(db, 'monitor', False, run['run_id'], 'PAPER_MONITOR', {}, run['completed_at'])
            db.execute('INSERT INTO notification_runs VALUES (?)', (run['run_id'],))


def message(notification):
    p = json.loads(notification['payload_json'])
    kind = notification['event_type']
    if kind in ('PAPER_FILL_RISK_RESIZE', 'PAPER_FILL_RISK_REJECT'):
        return (f"{notification['symbol']} fill-time risk: {p['decision']}\n"
                f"Reason: {p['reason']}\n"
                f"Qty: {p['planned_quantity']} -> {p['approved_quantity']}\n"
                f"Fill: {p['actual_fill_price']} {notification['currency']}\n"
                f"Risk: {p['actual_total_risk']} -> {p['approved_total_risk']} {notification['currency']}")
    if notification['trade_id']:
        title = {'PAPER_ENTRY_OPENED': f"{p.get('side', '')} opened", 'PAPER_TRADE_TARGET': 'TARGET reached',
                 'PAPER_TRADE_STOP': 'STOP reached', 'PAPER_TRADE_MANUAL_CLOSE': 'manually closed',
                 'PAPER_REVIEW_REQUIRED': 'review required'}[kind]
        lines = [f"{notification['symbol']} {title}"]
        if kind == 'PAPER_REVIEW_REQUIRED':
            lines.append('Review the paper journal before taking action.')
        else:
            lines.append(f"Entry: {p.get('fill_price')} {notification['currency']}")
            if kind == 'PAPER_ENTRY_OPENED':
                lines.extend([f"Qty: {p.get('quantity')}", f"Stop: {p.get('stop_loss')}",
                              f"Target: {p.get('take_profit')}"])
            else:
                lines.extend([f"Exit: {p.get('exit_price')}", f"Realized P&L: {p.get('realized_pnl')} {notification['currency']}"])
    elif kind.startswith('DAILY_SCAN_'):
        lines = ['AutoT ' + kind.replace('_', ' ').lower(),
                 f"Market: {p.get('market')}", f"Universe: {p.get('universe')}",
                 f"Analyzed: {p.get('analyzed')}", f"Trade opportunities: {p.get('opportunities')}"]
        if p.get('top_opportunity'):
            lines.append('Top opportunity: ' + p['top_opportunity'])
        if p.get('error_category'):
            lines.append('Error category: ' + p['error_category'])
    else:
        lines = [kind.replace('_', ' ').capitalize()]
        if p.get('provider'):
            lines.append('Provider: ' + p['provider'])
        if p.get('error_category'):
            lines.extend(['Error category: ' + p['error_category'], 'Next scheduled cycle will retry.'])
    return '\n'.join(lines)


class NotificationChannel(Protocol):
    """Adapters must use notification_id as the remote idempotency key if supported."""
    def send(self, notification: dict) -> None: ...


class ConsoleChannel:
    def send(self, notification):
        LOGGER.info('[%s] %s', notification['notification_id'], message(notification))


class FinalDeliveryError(Exception):
    """Adapter reports a permanent rejection; exception text is never persisted."""


def configuration():
    store = SettingsStore()
    result = store.load().settings.notifications
    if store.warning:
        raise ValueError('Notification settings unavailable')
    return result


def deliver(ledger, *, settings=None, channel=None, clock=now, limit=100, blocking=True):
    config = settings if settings is not None else configuration()
    if not config.notifications_enabled:
        return 0
    channel = channel if channel is not None else ConsoleChannel()
    delivered = 0
    # Serialize dispatchers without holding a SQLite transaction during send.
    with database_lock(ledger.path, 'notifications', blocking=blocking):
        with ledger.connection() as db:
            # Includes attempts interrupted after the durable claim but before completion.
            db.execute("UPDATE notification_outbox SET delivery_status='FAILED_FINAL', "
                       "error_category='RETRY_EXHAUSTED', next_attempt_at=NULL, "
                       "last_failure_at=COALESCE(last_failure_at,last_attempt_at) "
                       "WHERE delivery_status IN ('PENDING','FAILED_RETRYABLE') AND attempt_count>=?",
                       (MAX_ATTEMPTS,))
            rows = [dict(r) for r in db.execute('''SELECT * FROM notification_outbox
                WHERE delivery_status IN ('PENDING','FAILED_RETRYABLE')
                AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY rowid LIMIT ?''',
                (clock().isoformat(), limit))]
        for row in rows:
            stamp = clock()
            attempts = row['attempt_count'] + 1
            with ledger.connection() as db:
                db.execute('UPDATE notification_outbox SET attempt_count=?, last_attempt_at=? WHERE notification_id=?',
                           (attempts, stamp.isoformat(), row['notification_id']))
            try:
                channel.send(row)
            except Exception as error:
                permanent = isinstance(error, FinalDeliveryError)
                final = permanent or attempts >= MAX_ATTEMPTS
                status = 'FAILED_FINAL' if final else 'FAILED_RETRYABLE'
                category = 'PERMANENT_REJECTION' if permanent else 'RETRY_EXHAUSTED' if final else 'CHANNEL_FAILURE'
                retry = None if final else (stamp + timedelta(seconds=min(3600, 30 * 2 ** min(attempts - 1, 7)))).isoformat()
                with ledger.connection() as db:
                    db.execute('UPDATE notification_outbox SET delivery_status=?, error_category=?, next_attempt_at=?, last_failure_at=? '
                               'WHERE notification_id=?', (status, category, retry, stamp.isoformat(), row['notification_id']))
            else:
                with ledger.connection() as db:
                    db.execute("UPDATE notification_outbox SET delivery_status='DELIVERED', delivered_at=?, "
                               'error_category=NULL, next_attempt_at=NULL WHERE notification_id=?',
                               (clock().isoformat(), row['notification_id']))
                delivered += 1
    return delivered


def process(ledger):
    """Best-effort boundary: never propagate notification failures to trading callers."""
    try:
        project(ledger)
        return deliver(ledger, blocking=False)
    except Exception:
        LOGGER.warning('Notification processing unavailable; durable audit/outbox will retry.')
        return 0


def read_status(path):
    result = dict(pending=0, last_delivered=None, last_failed=None, history=[])
    if not path.exists():
        return result
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='notification_outbox'").fetchone():
            return result
        result['pending'] = db.execute("SELECT count(*) FROM notification_outbox WHERE delivery_status IN ('PENDING','FAILED_RETRYABLE')").fetchone()[0]
        for key, clause, order in [('last_delivered', "delivered_at IS NOT NULL", 'delivered_at'),
                                   ('last_failed', 'last_failure_at IS NOT NULL', 'last_failure_at')]:
            row = db.execute(f'SELECT * FROM notification_outbox WHERE {clause} ORDER BY {order} DESC LIMIT 1').fetchone()
            result[key] = dict(row) if row else None
        result['history'] = [dict(r) for r in db.execute('SELECT * FROM notification_outbox ORDER BY rowid DESC LIMIT 50')]
        return result
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if not configuration().notifications_enabled:
        LOGGER.info('Notifications disabled')
        return 0
    from autot.paper_trade.ledger import Ledger
    ledger = Ledger()
    try:
        while True:
            process(ledger)
            if args.once:
                return 0
            time.sleep(30)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
