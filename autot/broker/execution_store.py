"""Separate broker journal. Intent is durable before network submission."""
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from autot.runtime import data_dir


def encode(value):
    return json.dumps(value, default=str, allow_nan=False)


class ExecutionStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / 'broker' / 'executions.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS executions (
                    intent_key TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                    paper_trade_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS execution_events (
                    event_id INTEGER PRIMARY KEY, intent_key TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def all(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM executions ORDER BY rowid DESC')]

    def get(self, key):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM executions WHERE intent_key=?', (key,)).fetchone()
        if not row:
            raise ValueError('Broker execution not found.')
        return json.loads(row[0])

    def update(self, key, changes):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM executions WHERE intent_key=?', (key,)).fetchone()
            record = json.loads(row[0])
            record.update(changes)
            db.execute('UPDATE executions SET payload=? WHERE intent_key=?', (encode(record), key))
            db.execute('INSERT INTO execution_events(intent_key,payload) VALUES (?,?)', (key, encode(changes)))
        return record
