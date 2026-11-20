"""Durable prospective ledger, separate from the legacy CLI portfolio.

Immutable signal snapshots and mutable execution state are stored separately.
Transactions protect confirmations/reservations; revision checks protect workers
from overwriting concurrent monitor/manual actions. Money is JSON decimal text.
"""

from contextlib import contextmanager
import json
import logging
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from autot.paper_trade.sessions import utc
from autot.paper_trade import audit
from autot.runtime import data_dir
from autot.utils.financial_validation import decimal_value as D


def opportunity_identity(snapshot):
    """Versioned canonical signal identity; excludes sizing and execution state.

    Universe download/source/benchmark metadata is not identity: a refreshed
    constituent source must not turn the same market/index candle into a new signal.
    """
    return json.dumps([
        "signal-v1", snapshot["symbol"], snapshot["market"], snapshot["index_name"],
        snapshot["side"], utc(snapshot["signal_time"]).isoformat(), snapshot["signal_timeframe"],
        *(["RESEARCH"] if snapshot.get("mode") == "RESEARCH" else []),
    ], separators=(",", ":"), ensure_ascii=True)


class ConcurrentUpdate(ValueError):
    pass


class Ledger:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "paper_trading" / "ledger.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            # Concurrent first opens can race on the journal-mode upgrade;
            # SQLite does not consistently apply busy_timeout to this PRAGMA.
            deadline = time.monotonic() + 10
            while True:
                try:
                    db.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as error:
                    if 'locked' not in str(error).lower() or time.monotonic() >= deadline:
                        raise
                    time.sleep(.01)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    currency TEXT PRIMARY KEY, capital TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY, confirmation_key TEXT NOT NULL UNIQUE,
                    snapshot TEXT NOT NULL, state TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0);
            """)
            # Serialize schema upgrade with confirmations and other constructors.
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("BEGIN IMMEDIATE")
            columns = {r["name"] for r in db.execute("PRAGMA table_info(trades)")}
            if "opportunity_id" not in columns:
                db.execute("ALTER TABLE trades ADD COLUMN opportunity_id TEXT NOT NULL DEFAULT ''")
                db.execute("ALTER TABLE trades ADD COLUMN intent_key TEXT NOT NULL DEFAULT 'default'")
                seen = set()
                for row in db.execute("SELECT * FROM trades ORDER BY rowid").fetchall():
                    identity = opportunity_identity(json.loads(row["snapshot"]))
                    intent = "default" if identity not in seen else "legacy:" + row["trade_id"]
                    if identity in seen:
                        logging.getLogger(__name__).warning(
                            "Preserved pre-existing duplicate paper trade %s; review manually.", row["trade_id"])
                    seen.add(identity)
                    db.execute("UPDATE trades SET opportunity_id=?, intent_key=? WHERE trade_id=?",
                               (identity, intent, row["trade_id"]))
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS trade_intent_unique "
                       "ON trades(opportunity_id, intent_key)")
            audit.initialize(db, self.decode)
            from autot.notifications import initialize
            initialize(db)
            db.execute("""CREATE TABLE IF NOT EXISTS paper_trade_rejections (
                decision_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL,
                confirmation_key TEXT NOT NULL, proposal_json TEXT NOT NULL,
                decision_json TEXT NOT NULL)""")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise sqlite3.IntegrityError("Paper ledger foreign key check failed.")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(row):
        snapshot = json.loads(row["snapshot"])
        snapshot.setdefault("configuration_source", "PRE_SETTINGS_BASELINE")
        state = json.loads(row['state'])
        state.setdefault('fill_time_risk_check', None)
        check = state['fill_time_risk_check']
        if check and check['decision'] in ('ACCEPT', 'RESIZE'):
            snapshot['quantity'] = check['approved_quantity']
        return dict(snapshot, **state,
                    trade_id=row["trade_id"], revision=row["revision"],
                    confirmation_key=row["confirmation_key"],
                    opportunity_id=row["opportunity_id"], intent_key=row["intent_key"])

    def all(self):
        with self.connection() as db:
            return [self.decode(r) for r in db.execute("SELECT * FROM trades ORDER BY rowid")]

    def get(self, trade_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM trades WHERE trade_id=?", (trade_id,)).fetchone()
            if row is None:
                raise ValueError("Paper trade not found.")
            return self.decode(row)

    def by_confirmation(self, key):
        with self.connection() as db:
            row = db.execute("SELECT * FROM trades WHERE confirmation_key=?", (key,)).fetchone()
            return self.decode(row) if row else None

    @staticmethod
    def _by_opportunity(db, identity):
        # Prefer a live position (including preserved legacy duplicates or explicit
        # additions). Terminal history is still idempotent: reopening needs consent.
        return db.execute(
            "SELECT * FROM trades WHERE opportunity_id=? "
            "ORDER BY CASE WHEN json_extract(state, '$.status') IN ('PENDING_ENTRY', 'OPEN') "
            "THEN 0 ELSE 1 END, rowid LIMIT 1", (identity,)).fetchone()

    def by_opportunity(self, snapshot):
        with self.connection() as db:
            row = self._by_opportunity(db, opportunity_identity(snapshot))
            return self.decode(row) if row else None

    @staticmethod
    def _summaries(db):
        summaries = {r["currency"]: {"currency": r["currency"], "capital": D(r["capital"]),
                     "reserved": D(0), "realized_pnl": D(0), "unrealized_pnl": D(0)}
                     for r in db.execute("SELECT * FROM accounts")}
        for row in db.execute("SELECT * FROM trades"):
            t = Ledger.decode(row)
            s = summaries[t["currency"]]
            s["realized_pnl"] += D(t["realized_pnl"])
            s["unrealized_pnl"] += D(t["unrealized_pnl"])
            if t["status"] in ("PENDING_ENTRY", "OPEN"):
                s["reserved"] += D(t["fill_price"] or t["signal_price"]) * t["quantity"]
        for s in summaries.values():
            s["available"] = s["capital"] + s["realized_pnl"] - s["reserved"]
        return summaries

    def summaries(self):
        with self.connection() as db:
            return self._summaries(db)

    def preview_admission(self, snapshot):
        """Advisory read only. Confirmation always checks again under the write lock."""
        from autot.portfolio_risk.engine import evaluate_admission
        with self.connection() as db:
            db.execute('BEGIN')
            summary = self._summaries(db).get(snapshot['currency'])
            if summary is None:
                summary = dict(currency=snapshot['currency'], capital=D(snapshot['account_capital']),
                               realized_pnl=D(0), unrealized_pnl=D(0), reserved=D(0),
                               available=D(snapshot['account_capital']))
            trades = [self.decode(r) for r in db.execute('SELECT * FROM trades')]
            return evaluate_admission(snapshot, trades, summary)

    def portfolio_exposures(self, settings_state, *, when):
        """Consistent read of all currency accounts; no account creation or updates."""
        from autot.portfolio_risk.engine import portfolio_exposure
        from autot.paper_trade.sessions import MARKETS
        from autot.settings.models import SettingsState, TradeSettingsSnapshot
        state = SettingsState.model_validate(settings_state.model_dump(mode='json'))
        config = TradeSettingsSnapshot.from_state(state)
        with self.connection() as db:
            db.execute('BEGIN')
            summaries = self._summaries(db)
            trades = [self.decode(r) for r in db.execute('SELECT * FROM trades')]
            return [portfolio_exposure(trades, summaries[currency], settings_snapshot=config,
                                       market=market, mode=config.mode, when=when)
                    for market, (currency, *_) in MARKETS.items() if currency in summaries]

    @contextmanager
    def _admission_transaction(self, key, snapshot):
        """Commit rejected attempts without creating accounts, trades or trade events."""
        from autot.portfolio_risk.models import PortfolioRiskRejected
        rejection = None
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('SAVEPOINT admission')
            try:
                yield db
            except PortfolioRiskRejected as error:
                db.execute('ROLLBACK TO admission')
                db.execute('INSERT INTO paper_trade_rejections VALUES (?, ?, ?, ?, ?)',
                           (str(uuid4()), audit.timestamp(), key,
                            json.dumps(snapshot, allow_nan=False), error.result.model_dump_json()))
                rejection = error
            db.execute('RELEASE admission')
        # Raise only after the rejection audit commits. The write lock covers both
        # the evaluated portfolio and its recorded decision, even on rejection.
        if rejection is not None:
            raise rejection

    def rejections(self, limit=100):
        from autot.portfolio_risk.models import RiskRejection
        with self.connection() as db:
            return [RiskRejection.model_validate(dict(
                decision_id=r['decision_id'], recorded_at=r['recorded_at'],
                confirmation_key=r['confirmation_key'],
                proposal=json.loads(r['proposal_json']), decision=json.loads(r['decision_json'])))
                for r in db.execute('SELECT * FROM paper_trade_rejections ORDER BY rowid DESC LIMIT ?', (limit,))]

    def confirm(self, key, snapshot, state, *, create_another=False):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ValueError("A confirmation event key is required.")
        identity = opportunity_identity(snapshot)
        intent = "additional:" + key if create_another else "default"
        with self._admission_transaction(key, snapshot) as db:
            previous = db.execute("SELECT * FROM trades WHERE confirmation_key=?", (key,)).fetchone()
            if previous:
                return self.decode(previous)
            if not create_another:
                previous = self._by_opportunity(db, identity)
                if previous:
                    return self.decode(previous)
            currency, capital = snapshot["currency"], snapshot["account_capital"]
            db.execute("INSERT OR IGNORE INTO accounts VALUES (?, ?)", (currency, capital))
            summary = self._summaries(db)[currency]
            from autot.settings.trade_policy import enforce_admission
            decision = enforce_admission(snapshot, [self.decode(r) for r in db.execute('SELECT * FROM trades')], summary)
            if snapshot.get('configuration_source') == 'SETTINGS_V1':
                snapshot = dict(snapshot, portfolio_risk_decision=decision.model_dump(mode='json'))
            trade_id = str(uuid4())
            db.execute("INSERT INTO trades "
                       "(trade_id, confirmation_key, snapshot, state, revision, opportunity_id, intent_key) "
                       "VALUES (?, ?, ?, ?, 0, ?, ?)",
                       (trade_id, key, json.dumps(snapshot, allow_nan=False),
                        json.dumps(state, allow_nan=False), identity, intent))
            trade = self.decode(db.execute("SELECT * FROM trades WHERE trade_id=?", (trade_id,)).fetchone())
            audit.append(db, trade, audit.event("TRADE_CREATED", state, when=snapshot["created_at"]),
                         revision_before=None, revision_after=0)
            return trade

    def update(self, trade, state, *, events=(), run_id=None, evaluator=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute('SELECT * FROM trades WHERE trade_id=?', (trade['trade_id'],)).fetchone()
            if current is None or current['revision'] != trade['revision']:
                raise ConcurrentUpdate('Trade changed during monitoring; retry the update.')
            def fill_recheck(price, fill_time):
                from autot.paper_trade.fill_risk import recheck
                return recheck(trade, price,
                               [self.decode(r) for r in db.execute('SELECT * FROM trades')],
                               self._summaries(db)[trade['currency']],
                               checked_at=audit.timestamp(), fill_time=fill_time)
            if evaluator is not None:
                state = evaluator(fill_recheck)
            elif trade['status'] == 'PENDING_ENTRY' and state.get('fill_price') is not None:
                check = fill_recheck(state['fill_price'], state['filled_at'])
                state = dict(state, fill_time_risk_check=check)
                if check['decision'] == 'REJECT':
                    from autot.paper_trade.service import initial_state
                    state = dict(initial_state(), status='CANCELLED',
                                 cancelled_at=check['rechecked_at'], fill_time_risk_check=check,
                                 exit_reason='FILL_TIME_REJECTED: ' + check['reason'])
                    events = ()
                elif check['decision'] == 'RESIZE':
                    from autot.portfolio.pnl import calculate_pnl
                    quantity = check['approved_quantity']
                    for field, price in (('realized_pnl', state.get('exit_price')),
                                         ('unrealized_pnl', state.get('current_price') if state['status'] == 'OPEN' else None)):
                        state[field] = str(calculate_pnl(D(state['fill_price']), D(price), quantity,
                                                        trade['side'])) if price is not None else '0'
                    events = ()  # Rebuild required transitions with approved P&L.
            changed = db.execute("UPDATE trades SET state=?, revision=revision+1 WHERE trade_id=? AND revision=?",
                                 (json.dumps(state, allow_nan=False), trade["trade_id"], trade["revision"]))
            if changed.rowcount != 1:
                raise ConcurrentUpdate("Trade changed during monitoring; retry the update.")
            items = list(events)
            kinds = {e['event_type'] for e in items}
            # Required transitions are enforced at the persistence boundary too.
            required = []
            if not trade.get('fill_price') and state.get('fill_price'):
                required.append(('ENTRY_FILLED', state['filled_at']))
            if trade['status'] != 'CLOSED' and state['status'] == 'CLOSED':
                reason = state['exit_reason']
                required.append(('STOP_HIT' if reason in ('STOP', 'GAP_STOP') else
                                 'TARGET_HIT' if reason in ('TARGET', 'GAP_TARGET') else
                                 'MANUAL_CLOSE_EXECUTED', state['closed_at']))
                required.append(('TRADE_CLOSED', state['closed_at']))
            if trade['status'] != 'CANCELLED' and state['status'] == 'CANCELLED':
                required.append(('TRADE_CANCELLED', state['cancelled_at']))
            if not trade.get('manual_close_requested_at') and state.get('manual_close_requested_at'):
                required.append(('MANUAL_CLOSE_REQUESTED', state['manual_close_requested_at']))
            if state['review_required'] and (not trade['review_required'] or
                                             trade['review_reason'] != state['review_reason']):
                required.append(('REVIEW_REQUIRED', audit.timestamp()))
            for kind, when in required:
                if kind not in kinds:
                    items.append(audit.event(kind, state, when=when, before=trade['status'],
                                             reason=state.get('review_reason') if kind == 'REVIEW_REQUIRED'
                                             else state.get('exit_reason')))
            check = state.get('fill_time_risk_check')
            audit_trade = dict(trade, quantity=check['approved_quantity']) if check else trade
            for item in items:
                audit.append(db, audit_trade, item, revision_before=trade['revision'],
                             revision_after=trade['revision'] + 1, run_id=run_id)
        return self.get(trade["trade_id"])


    def events(self, trade_id):
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM paper_trade_events WHERE trade_id=? ORDER BY event_id", (trade_id,))]

    def start_run(self, provider, started_at, source="MANUAL"):
        run_id = str(uuid4())
        with self.connection() as db:
            db.execute("INSERT INTO paper_update_runs "
                       "(run_id, started_at, trigger_type, provider, status, summary_json) "
                       "VALUES (?, ?, ?, ?, 'RUNNING', '{}')", (run_id, started_at, source, provider))
        return run_id

    def finish_run(self, run_id, counts, status, summary):
        with self.connection() as db:
            db.execute("UPDATE paper_update_runs SET " + ','.join(k + '=?' for k in counts) +
                       ", completed_at=?, status=?, summary_json=? WHERE run_id=? AND status='RUNNING'",
                       (*counts.values(), audit.timestamp(), status, json.dumps(summary), run_id))

    def get_run(self, run_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM paper_update_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("Paper update run not found.")
            return dict(row)

    def recent_runs(self, limit=50):
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM paper_update_runs ORDER BY rowid DESC LIMIT ?", (limit,))]

    def active_trades(self):
        with self.connection() as db:
            return [self.decode(r) for r in db.execute(
                "SELECT * FROM trades WHERE json_extract(state, '$.status') "
                "IN ('PENDING_ENTRY','OPEN') ORDER BY rowid")]

    def monitor_heartbeat(self, payload):
        with self.connection() as db:
            db.execute('INSERT INTO paper_monitor_status VALUES (1, ?) '
                       'ON CONFLICT(singleton) DO UPDATE SET payload=excluded.payload',
                       (json.dumps(payload),))

    def recover_monitor_runs(self):
        # Called only by the new exclusive monitor owner after a crash/restart.
        with self.connection() as db:
            db.execute("UPDATE paper_update_runs SET status='FAILED', completed_at=?, "
                       "errors_count=errors_count+1, summary_json=? "
                       "WHERE trigger_type='SCHEDULED' AND status='RUNNING'",
                       (audit.timestamp(), json.dumps({'error_category': 'PROCESS_INTERRUPTED'})))
