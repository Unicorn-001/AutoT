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
from uuid import uuid4

from autot.paper_trade.sessions import utc
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
    ], separators=(",", ":"), ensure_ascii=True)


class ConcurrentUpdate(ValueError):
    pass


class Ledger:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "paper_trading" / "ledger.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    currency TEXT PRIMARY KEY, capital TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY, confirmation_key TEXT NOT NULL UNIQUE,
                    snapshot TEXT NOT NULL, state TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0);
            """)
            # Serialize schema upgrade with confirmations and other constructors.
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

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(row):
        return dict(json.loads(row["snapshot"]), **json.loads(row["state"]),
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

    def confirm(self, key, snapshot, state, *, create_another=False):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ValueError("A confirmation event key is required.")
        identity = opportunity_identity(snapshot)
        intent = "additional:" + key if create_another else "default"
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
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
            if summary["capital"] != D(capital):
                raise ValueError("Use the existing paper account capital for this currency.")
            if D(snapshot["intended_position_value"]) > summary["available"]:
                raise ValueError("Insufficient available paper capital, including pending reservations.")
            trade_id = str(uuid4())
            db.execute("INSERT INTO trades "
                       "(trade_id, confirmation_key, snapshot, state, revision, opportunity_id, intent_key) "
                       "VALUES (?, ?, ?, ?, 0, ?, ?)",
                       (trade_id, key, json.dumps(snapshot, allow_nan=False),
                        json.dumps(state, allow_nan=False), identity, intent))
            return self.decode(db.execute("SELECT * FROM trades WHERE trade_id=?", (trade_id,)).fetchone())

    def update(self, trade, state):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if trade["status"] == "PENDING_ENTRY" and state["fill_price"] is not None:
                # Both shorts and longs reserve full notional, not fictional short proceeds.
                needed = D(state["fill_price"]) * trade["quantity"] - D(trade["intended_position_value"])
                if needed > self._summaries(db)[trade["currency"]]["available"]:
                    raise ValueError("Gap fill exceeds available capital; review required.")
            changed = db.execute("UPDATE trades SET state=?, revision=revision+1 WHERE trade_id=? AND revision=?",
                                 (json.dumps(state, allow_nan=False), trade["trade_id"], trade["revision"]))
            if changed.rowcount != 1:
                raise ConcurrentUpdate("Trade changed during monitoring; retry the update.")
        return self.get(trade["trade_id"])
