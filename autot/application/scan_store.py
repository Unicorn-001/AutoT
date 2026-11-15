"""Durable research jobs, results and notification outbox, separate from paper capital."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from autot.runtime import data_dir


def stamp():
    return datetime.now(timezone.utc).isoformat()


def json_value(value):
    """Normalize numpy scalars and nonfinite research values without inventing prices."""
    import math
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if hasattr(value, 'item'):
        return json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class ScanStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / 'scanner' / 'scans.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS scan_runs (scan_run_id TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS scanner_status (name TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            from autot.notifications import initialize_outbox
            initialize_outbox(db)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, request, trigger='MANUAL', session=None, key=None):
        run = dict(scan_run_id=uuid.uuid4().hex, trigger_type=trigger, started_at=None,
                   completed_at=None, status='QUEUED', request=request, market=request['market'],
                   universe=request['universe'], profile=request['state']['profile'],
                   session=session, schedule_key=key, symbols_fetched=0, symbols_analyzed=0,
                   symbols_failed=0, opportunities_count=0, error_category=None, failures=[],
                   result_location=None, requested_at=stamp())
        with self.connection() as db:
            db.execute('INSERT INTO scan_runs VALUES (?,?,NULL)', (run['scan_run_id'], json.dumps(run)))
        return run

    def save(self, run, result=None):
        with self.connection() as db:
            db.execute('UPDATE scan_runs SET payload=?, result=COALESCE(?,result) WHERE scan_run_id=?',
                       (json.dumps(json_value(run), allow_nan=False),
                        json.dumps(json_value(result), allow_nan=False) if result is not None else None,
                        run['scan_run_id']))

    def runs(self):
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM scan_runs ORDER BY rowid DESC')]

    def get(self, run_id):
        return next(r for r in self.runs() if r['scan_run_id'] == run_id)

    def latest(self):
        with self.connection() as db:
            row = db.execute("SELECT result FROM scan_runs WHERE result IS NOT NULL ORDER BY (json_extract(payload,'$.status') IN ('SUCCESS','PARTIAL')) DESC, json_extract(payload,'$.completed_at') DESC, rowid DESC LIMIT 1").fetchone()
            return json.loads(row[0]) if row else None

    def heartbeat(self, name, phase, next_run=None):
        import os
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO scanner_status VALUES (?,?)',
                       (name, json.dumps(dict(phase=phase, heartbeat=stamp(), pid=os.getpid(), next_expected_run=next_run))))
