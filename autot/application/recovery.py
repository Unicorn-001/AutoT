"""Read-only startup evidence; never initialize stores or repair trading state."""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3

from autot.daily_scanner import active, request_from_state, schedule_key, slot
from autot.paper_trade.locking import lock_path
from autot.runtime import data_dir
from autot.settings.store import SettingsStore


def diagnostics(*, now=None, integrity=False):
    now = now or datetime.now(timezone.utc)
    root = data_dir()
    result = dict(data_directory=str(root), databases={}, locks={}, errors=[], warnings=[],
                  recovery_required=False, paper_catch_up='UNKNOWN', scanner_catch_up='UNKNOWN')
    definitions = {
        'paper': ('paper_trading/ledger.sqlite3', {'trades', 'paper_update_runs', 'paper_monitor_status'}),
        'scanner': ('scanner/scans.sqlite3', {'scan_runs', 'scanner_status'}),
        'settings': ('settings/settings.sqlite3', {'revisions'}),
        'real_journal': ('real_trade_journal/real_trade_journal.sqlite3', {'real_trades'}),
    }
    runs = []
    for name, (relative, required) in definitions.items():
        path = root / relative
        record = dict(path=str(path), state='MISSING', interrupted_runs=0)
        result['databases'][name] = record
        try:
            for kind in {'paper': ('monitor', 'update'), 'scanner': ('scheduler', 'scan'), 'settings': (), 'real_journal': ()}[name]:
                held = active(path, kind)
                result['locks'][kind] = dict(path=str(lock_path(path, kind)), held=held,
                    file_exists=lock_path(path, kind).exists())
            if not path.exists():
                result['warnings'].append(f'{name} database missing: verify data root or first startup.')
                continue
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                db.execute('BEGIN')
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not required <= tables:
                    raise ValueError('Missing required tables: ' + ', '.join(sorted(required - tables)))
                if integrity and db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise ValueError('SQLite quick_check failed')
                if name == 'paper':
                    counts = dict(db.execute("SELECT json_extract(state,'$.status'), count(*) FROM trades GROUP BY 1"))
                    record.update(pending=counts.get('PENDING_ENTRY', 0), open=counts.get('OPEN', 0))
                    record['interrupted_runs'] = db.execute("SELECT count(*) FROM paper_update_runs WHERE status='RUNNING' AND trigger_type='SCHEDULED'").fetchone()[0]
                    result['paper_catch_up'] = ('CHECK_REQUIRED' if record['pending'] or record['open'] else 'NO_ACTIVE_TRADES')
                if name == 'scanner':
                    runs = [json.loads(r[0]) for r in db.execute('SELECT payload FROM scan_runs')]
                    if any(not isinstance(r, dict) or not isinstance(r.get('status'), str) for r in runs):
                        runs = []
                        raise ValueError('Invalid scan run payload')
                    record['interrupted_runs'] = sum(r['status'] in ('RUNNING', 'QUEUED') for r in runs)
                record['state'] = 'OK'
            owner = 'monitor' if name == 'paper' else 'scan'
            if record['interrupted_runs'] and not result['locks'].get(owner, {}).get('held'):
                result['recovery_required'] = True
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
            record['state'] = 'ERROR'
            result['errors'].append(f'{name}: {error}')
    store = SettingsStore()
    state = store.load()
    if store.warning:
        result['errors'].append('Settings: ' + store.warning)
    else:
        try:
            request = request_from_state(state)
            session, due = slot(request, now)
            consumed = any(r.get('schedule_key') == schedule_key(request, session) for r in runs)
            result['scanner_catch_up'] = ('UNKNOWN' if result['databases']['scanner']['state'] == 'ERROR' else
                'DISABLED' if not state.settings.monitoring.daily_scan_enabled else
                'CURRENT_SLOT_DUE' if due and now >= due and not consumed else 'NO_CURRENT_SLOT_DUE')
        except (ValueError, KeyError, TypeError) as error:
            result['errors'].append(f'Scanner schedule: {error}')
    result['warnings'].append('Paper catch-up needs provider history; offline diagnostics cannot verify available bars. Scanner does not backfill earlier sessions.')
    return result
