"""Validated manual journal with immutable signal snapshots and isolated SQLite storage.

Decimals are persisted as strings, timestamps as offset-aware UTC ISO 8601.
No quantities, FX rates, leverage, fills, or cash P&L are inferred from prices.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from autot.runtime import data_dir
from autot.utils.financial_validation import decimal_value

SNAPSHOT_FIELDS = (
    'scan_run_id', 'signal_timestamp', 'signal', 'market_regime', 'confidence',
    'agreement', 'trade_quality', 'historical_score', 'autot_entry_price',
    'autot_stop_loss', 'autot_take_profit', 'autot_risk_reward_ratio',
    'autot_execution_model',
)
EXECUTION_FIELDS = (
    'investment_amount', 'investment_currency', 'actual_entry_price', 'entry_timestamp',
    'actual_exit_price', 'exit_timestamp', 'exit_reason', 'gross_pnl', 'fees',
    'net_pnl', 'pnl_currency', 'notes',
    'real_order_type', 'execution_match_status', 'execution_mismatch_reason',
    'actual_market_open_price',
)
NUMBERS = {'confidence', 'agreement', 'trade_quality', 'historical_score',
           'autot_entry_price', 'autot_stop_loss', 'autot_take_profit',
           'autot_risk_reward_ratio', 'investment_amount', 'actual_entry_price',
           'actual_exit_price', 'gross_pnl', 'fees', 'net_pnl', 'actual_market_open_price'}
POSITIVE = {'autot_entry_price', 'autot_stop_loss', 'autot_take_profit',
            'autot_risk_reward_ratio', 'investment_amount', 'actual_entry_price', 'actual_exit_price', 'actual_market_open_price'}
ORDER_TYPES = ('MARKET', 'LIMIT', 'STOP', 'OTHER')
MATCH_STATUSES = ('UNKNOWN', 'MATCHED', 'MISMATCHED')

EXIT_REASONS = ('STOP_LOSS', 'TAKE_PROFIT', 'MANUAL', 'CANCELLED', 'OTHER')


def utc(value):
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError('Timestamp must include a timezone (Z or +00:00 for UTC).')
        return dt.astimezone(timezone.utc).isoformat()
    except (AttributeError, TypeError) as error:
        raise ValueError('Invalid timestamp.') from error


def now():
    return datetime.now(timezone.utc).isoformat()


def validate(record):
    record = dict(record)
    for field in ('symbol', 'broker'):
        if not isinstance(record[field], str) or not record[field].strip():
            raise ValueError(f'{field} is required.')
        record[field] = record[field].strip()
    record['symbol'] = record['symbol'].upper()
    if record['side'] not in ('BUY', 'SELL'):
        raise ValueError('side must be BUY or SELL.')
    for field in (*SNAPSHOT_FIELDS, *EXECUTION_FIELDS):
        value = record.get(field)
        if value == '' or value is None:
            record[field] = None
        elif field in NUMBERS:
            number = decimal_value(value, positive=field in POSITIVE)
            if field == 'fees' and number < 0:
                raise ValueError('fees cannot be negative.')
            record[field] = str(number)
        elif field.endswith('timestamp'):
            record[field] = utc(value)
        elif not isinstance(value, str):
            raise ValueError(f'{field} must be text.')
    # Classification is explicit: neither order type nor price proximity proves a match.
    record['execution_match_status'] = record['execution_match_status'] or 'UNKNOWN'
    if record['execution_match_status'] not in MATCH_STATUSES:
        raise ValueError('Invalid execution match status.')
    if record['real_order_type'] is not None and record['real_order_type'] not in ORDER_TYPES:
        raise ValueError('Invalid real order type.')
    for field in ('investment_currency', 'pnl_currency'):
        if record[field] is not None:
            record[field] = record[field].strip().upper()
            if not re.fullmatch('[A-Z]{3}', record[field]):
                raise ValueError(f'{field} must be a three-letter currency code.')
    if record['investment_amount'] is not None and not record['investment_currency']:
        raise ValueError('Investment currency is required with investment amount.')
    if any(record[k] is not None for k in ('gross_pnl', 'fees', 'net_pnl')) and not record['pnl_currency']:
        raise ValueError('P&L currency is required with P&L or fees.')
    if record['exit_reason'] is not None and record['exit_reason'] not in EXIT_REASONS:
        raise ValueError('Invalid exit reason.')
    if record['actual_exit_price'] is not None and record['actual_entry_price'] is None:
        raise ValueError('An actual exit price requires an actual entry price.')
    if record['entry_timestamp'] and record['exit_timestamp'] and datetime.fromisoformat(record['exit_timestamp']) < datetime.fromisoformat(record['entry_timestamp']):
        raise ValueError('Exit timestamp cannot precede entry timestamp.')
    return record


def metrics(record):
    """Missing data stays missing; price returns exclude fees, FX and leverage."""
    def number(key):
        return Decimal(record[key]) if record.get(key) is not None else None
    entry, actual, exit_price = (number(k) for k in ('autot_entry_price', 'actual_entry_price', 'actual_exit_price'))
    result = dict.fromkeys(('entry_slippage_absolute', 'entry_slippage_percent',
                           'planned_stop_distance_percent', 'planned_target_distance_percent',
                           'actual_return_percent', 'return_basis', 'holding_duration_seconds', 'net_pnl',
                           'gap_from_signal_to_open_absolute', 'gap_from_signal_to_open_percent'))
    market_open = number('actual_market_open_price')
    if entry is not None and market_open is not None:
        result['gap_from_signal_to_open_absolute'] = str(market_open - entry)
        result['gap_from_signal_to_open_percent'] = str((market_open - entry) / entry * 100)
    if entry is not None and actual is not None:
        result['entry_slippage_absolute'] = str(actual - entry)
        result['entry_slippage_percent'] = str((actual - entry) / entry * 100)
    for source, target in (('autot_stop_loss', 'planned_stop_distance_percent'),
                           ('autot_take_profit', 'planned_target_distance_percent')):
        if entry is not None and number(source) is not None:
            result[target] = str(abs(number(source) - entry) / entry * 100)
    net = number('net_pnl')
    if net is None and number('gross_pnl') is not None and number('fees') is not None:
        net = number('gross_pnl') - number('fees')
    result['net_pnl'] = str(net) if net is not None else None
    investment = number('investment_amount')
    if net is not None and investment is not None and record['investment_currency'] == record['pnl_currency']:
        result['actual_return_percent'] = str(net / investment * 100)
        result['return_basis'] = 'Net P&L / investment (same currency)'
    elif actual is not None and exit_price is not None:
        direction = 1 if record['side'] == 'BUY' else -1
        result['actual_return_percent'] = str(direction * (exit_price - actual) / actual * 100)
        result['return_basis'] = 'Price return only (excludes fees, FX and leverage)'
    if record.get('entry_timestamp') and record.get('exit_timestamp'):
        result['holding_duration_seconds'] = (datetime.fromisoformat(record['exit_timestamp']) - datetime.fromisoformat(record['entry_timestamp'])).total_seconds()
    return result


def status(record):
    if record['exit_reason'] == 'CANCELLED':
        return 'CANCELLED'
    if record['actual_entry_price'] is not None and record['actual_exit_price'] is not None and record['exit_reason']:
        return 'CLOSED'
    return 'OPEN / INCOMPLETE'


class RealTradeJournal:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / 'real_trade_journal' / 'real_trade_journal.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError('Unsupported real journal schema version.')
            db.execute('''CREATE TABLE IF NOT EXISTS real_trades (
                journal_trade_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                broker TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                snapshot TEXT NOT NULL, execution TEXT NOT NULL)''')
            # V2 adds optional JSON fields. Preserve all V1 payloads and timestamps;
            # decode supplies missing defaults without rewriting historical records.
            if version < 2:
                db.execute('PRAGMA user_version = 2')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            raise KeyError('Real trade not found.')
        record = dict(row)
        record.update(json.loads(record.pop('snapshot')))
        record.update(json.loads(record.pop('execution')))
        for field in (*SNAPSHOT_FIELDS, *EXECUTION_FIELDS):
            record.setdefault(field, None)
        record['execution_match_status'] = record['execution_match_status'] or 'UNKNOWN'
        return record

    def create(self, *, symbol, side, broker, snapshot=None, **execution):
        if set(snapshot or {}) - set(SNAPSHOT_FIELDS) or set(execution) - set(EXECUTION_FIELDS):
            raise ValueError('Unknown journal field.')
        record = validate(dict(symbol=symbol, side=side, broker=broker, **(snapshot or {}), **execution))
        record.update(journal_trade_id=uuid4().hex, created_at=now())
        record['updated_at'] = record['created_at']
        with self.connection() as db:
            db.execute('INSERT INTO real_trades VALUES (?,?,?,?,?,?,?,?)', (
                *(record[k] for k in ('journal_trade_id', 'symbol', 'side', 'broker', 'created_at', 'updated_at')),
                json.dumps({k: record[k] for k in SNAPSHOT_FIELDS}),
                json.dumps({k: record[k] for k in EXECUTION_FIELDS})))
        return self.get(record['journal_trade_id'])

    def get(self, trade_id):
        with self.connection() as db:
            return self.decode(db.execute('SELECT * FROM real_trades WHERE journal_trade_id=?', (trade_id,)).fetchone())

    def list(self):
        with self.connection() as db:
            return [self.decode(row) for row in db.execute('SELECT * FROM real_trades ORDER BY created_at DESC, journal_trade_id')]

    def update(self, trade_id, **execution):
        if set(execution) - set(EXECUTION_FIELDS):
            raise ValueError('Only real execution fields can be updated; identity and signal snapshot are immutable.')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            record = self.decode(db.execute('SELECT * FROM real_trades WHERE journal_trade_id=?', (trade_id,)).fetchone())
            record = validate(dict(record, **execution))
            db.execute('UPDATE real_trades SET execution=?, updated_at=? WHERE journal_trade_id=?',
                       (json.dumps({k: record[k] for k in EXECUTION_FIELDS}), now(), trade_id))
        return self.get(trade_id)

    def cancel(self, trade_id):
        return self.update(trade_id, exit_reason='CANCELLED')

    def delete(self, trade_id):
        with self.connection() as db:
            if not db.execute('DELETE FROM real_trades WHERE journal_trade_id=?', (trade_id,)).rowcount:
                raise KeyError('Real trade not found.')
