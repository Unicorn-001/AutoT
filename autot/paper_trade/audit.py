"""Append-only audit primitives. Callers own the surrounding SQLite transaction."""

from datetime import datetime, timezone
from hashlib import sha256
import json


EVENT_TYPES = (
    "AUDIT_BASELINE_CREATED", "TRADE_CREATED", "TRADE_CANCELLED", "ENTRY_ELIGIBLE",
    "ENTRY_BAR_PROCESSED", "ENTRY_FILLED", "POSITION_CHECKED", "POSITION_UPDATED",
    "STOP_HIT", "TARGET_HIT", "MANUAL_CLOSE_REQUESTED", "MANUAL_CLOSE_EXECUTED",
    "TRADE_CLOSED", "REVIEW_REQUIRED", "DATA_UNAVAILABLE", "MISSING_EXPECTED_BAR",
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def initialize(db, decode):
    # Individual DDL statements deliberately avoid executescript's implicit commit.
    kinds = ','.join("'" + kind + "'" for kind in EVENT_TYPES)
    db.execute(f"""CREATE TABLE IF NOT EXISTS paper_trade_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id TEXT NOT NULL REFERENCES trades(trade_id),
        event_type TEXT NOT NULL CHECK(event_type IN ({kinds})),
        event_time TEXT NOT NULL, recorded_at TEXT NOT NULL,
        symbol TEXT NOT NULL, market TEXT NOT NULL, currency TEXT NOT NULL,
        status_before TEXT, status_after TEXT NOT NULL,
        revision_before INTEGER, revision_after INTEGER NOT NULL,
        bar_time TEXT, bar_open TEXT, bar_high TEXT, bar_low TEXT, bar_close TEXT,
        price TEXT, quantity INTEGER NOT NULL, realized_pnl TEXT, unrealized_pnl TEXT,
        reason TEXT, data_source TEXT,
        update_run_id TEXT REFERENCES paper_update_runs(run_id),
        idempotency_key TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS paper_update_runs (
        run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
        trigger_type TEXT NOT NULL CHECK(trigger_type IN ('MANUAL','SCHEDULED')),
        trades_considered INTEGER NOT NULL DEFAULT 0,
        trades_updated INTEGER NOT NULL DEFAULT 0,
        trades_opened INTEGER NOT NULL DEFAULT 0,
        trades_closed INTEGER NOT NULL DEFAULT 0,
        bars_processed INTEGER NOT NULL DEFAULT 0,
        warnings_count INTEGER NOT NULL DEFAULT 0,
        errors_count INTEGER NOT NULL DEFAULT 0,
        provider TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCESS','PARTIAL','FAILED','NO_WORK')),
        summary_json TEXT NOT NULL)""")
    # Rebuild only run metadata to widen legacy CHECK constraints. The caller
    # disables FK enforcement before its atomic schema transaction; event links
    # keep their original table name, run IDs and row order.
    schema = db.execute("SELECT sql FROM sqlite_master WHERE name='paper_update_runs'").fetchone()[0]
    if "SCHEDULED" not in schema:
        replacement = schema.replace('paper_update_runs', 'paper_update_runs_v2', 1).replace(
            "trigger_type = 'MANUAL'", "trigger_type IN ('MANUAL','SCHEDULED')").replace(
            "'RUNNING','SUCCESS','PARTIAL','FAILED'", "'RUNNING','SUCCESS','PARTIAL','FAILED','NO_WORK'")
        db.execute(replacement)
        db.execute('INSERT INTO paper_update_runs_v2 SELECT * FROM paper_update_runs ORDER BY rowid')
        db.execute('DROP TABLE paper_update_runs')
        db.execute('ALTER TABLE paper_update_runs_v2 RENAME TO paper_update_runs')
    db.execute("""CREATE TABLE IF NOT EXISTS paper_monitor_status (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS paper_events_trade ON paper_trade_events(trade_id, event_id)")
    for action in ('UPDATE', 'DELETE'):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS paper_events_no_{action.lower()}
            BEFORE {action} ON paper_trade_events BEGIN
            SELECT RAISE(ABORT, 'Paper trade events are append-only'); END""")
    recorded = timestamp()
    for row in db.execute("SELECT * FROM trades WHERE NOT EXISTS "
                          "(SELECT 1 FROM paper_trade_events e WHERE e.trade_id=trades.trade_id)").fetchall():
        trade = decode(row)
        append(db, trade, dict(event_type="AUDIT_BASELINE_CREATED", event_time=recorded,
                              identity="baseline", payload=trade),
               revision_before=trade['revision'], revision_after=trade['revision'], recorded_at=recorded)


def event(kind, state, *, when, before=None, bar=None, scale=None, reason=None, identity=None):
    result = dict(event_type=kind, event_time=when, status_before=before,
                  status_after=state['status'], price=state.get('exit_price') or state.get('current_price'),
                  realized_pnl=state['realized_pnl'], unrealized_pnl=state['unrealized_pnl'],
                  reason=reason, data_source=state.get('data_source'), payload=dict(state))
    if identity is not None:
        result['identity'] = identity
    if bar is not None:
        result.update(bar_time=bar.timestamp.isoformat(), **{
            'bar_' + k: str(getattr(bar, k) * scale) for k in ('open', 'high', 'low', 'close')})
    return result


def append(db, trade, item, *, revision_before, revision_after, run_id=None, recorded_at=None):
    item = dict(item)
    kind = item['event_type']
    if kind not in EVENT_TYPES:
        raise ValueError('Unknown paper audit event type.')
    identity = item.pop('identity', None)
    if identity is None:
        identity = item.get('bar_time') or f'revision:{revision_after}'
    key = sha256(json.dumps([trade['trade_id'], kind, identity], separators=(',', ':')).encode()).hexdigest()
    values = dict(trade_id=trade['trade_id'], event_type=kind,
                  event_time=item['event_time'], recorded_at=recorded_at or timestamp(),
                  symbol=trade['symbol'], market=trade['market'], currency=trade['currency'],
                  status_before=item.get('status_before', trade['status']),
                  status_after=item.get('status_after', trade['status']),
                  revision_before=revision_before, revision_after=revision_after,
                  quantity=trade['quantity'], update_run_id=run_id, idempotency_key=key,
                  payload_json=json.dumps(item.pop('payload', {}), allow_nan=False))
    for key in ('bar_time', 'bar_open', 'bar_high', 'bar_low', 'bar_close', 'price',
                'realized_pnl', 'unrealized_pnl', 'reason', 'data_source'):
        values[key] = item.get(key)
    columns = ','.join(values)
    db.execute(f"INSERT INTO paper_trade_events ({columns}) VALUES ({','.join('?' for _ in values)}) "
               "ON CONFLICT(idempotency_key) DO NOTHING", tuple(values.values()))
