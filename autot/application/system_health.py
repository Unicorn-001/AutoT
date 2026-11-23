"""Read-only operational projection of existing durable service state."""
from contextlib import closing
from datetime import datetime, timezone
import json
import logging
import sqlite3

from autot.daily_scanner import active
from autot.paper_monitor import HEARTBEAT_SECONDS, read_status as paper_status
from autot.runtime import data_dir
from autot.settings.store import SettingsStore

# Waiting loops emit every 15 seconds; allow three missed observations for
# scheduling/write jitter. This is not a deadline for progress-driven scan work.
HEARTBEAT_GRACE_SECONDS = 3 * HEARTBEAT_SECONDS
SCANNER_WORK_PHASES = {
    'STARTING', 'loading_universe', 'universe_loaded', 'loading_market_data',
    'analysing', 'ranking',
}
READ_ERRORS = (OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError)


def scanner_status():
    path = data_dir() / 'scanner' / 'scans.sqlite3'
    worker = active(path, 'scan')
    scheduler = active(path, 'scheduler')
    result = dict(process_status='ACTIVE' if worker or scheduler else 'NOT DETECTED',
                  worker_active=worker, scheduler_active=scheduler,
                  heartbeat=None, phase=None, last_run=None, recent_issues=[])
    if not path.exists():
        return result
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
        db.execute('BEGIN')
        runs = [json.loads(row[0]) for row in db.execute(
            'SELECT payload FROM scan_runs ORDER BY rowid DESC LIMIT 20')]
        for run in runs:
            if not isinstance(run, dict) or not isinstance(run.get('status'), str):
                raise ValueError('Invalid scan run')
        result['last_run'] = runs[0] if runs else None
        result['recent_issues'] = [r for r in runs if r['status'] in ('FAILED', 'PARTIAL')]
        rows = dict(db.execute('SELECT name, payload FROM scanner_status'))
        name = 'worker' if worker else 'scheduler'
        if not worker and not scheduler:
            # Retain the most recent recorded heartbeat even after shutdown.
            payloads = [json.loads(value) for value in rows.values()]
            payload = max(payloads, key=lambda p: p.get('heartbeat') or '', default={})
        else:
            payload = json.loads(rows.get(name, '{}'))
        for key in ('heartbeat', 'phase', 'pid', 'next_expected_run'):
            result[key] = payload.get(key)
    return result


def classify(status, now, *, service):
    """Return an evidence-based state and a short explanation."""
    if status.get('unavailable'):
        return 'ATTENTION', 'Persisted status is unavailable; inspect storage/server logs.'
    if status.get('configured') is None:
        return 'ATTENTION', 'Monitoring configuration could not be verified.'
    running = status['process_status'] == 'ACTIVE'
    run = status.get('last_run') or {}
    if not running:
        if status.get('configured') or status.get('heartbeat') or run:
            return 'STOPPED', 'No service lock is held on this host.'
        return 'IDLE', 'Disabled with no prior service activity recorded.'
    try:
        heartbeat = datetime.fromisoformat(status['heartbeat'])
        age = (now - heartbeat).total_seconds()
        if age < -30:
            return 'ATTENTION', 'Heartbeat is ahead of the current clock.'
    except (TypeError, ValueError, KeyError):
        return 'ATTENTION', 'Active process has no valid timestamped heartbeat.'
    if status.get('phase') == 'STOPPED':
        return 'ATTENTION', 'Held process lock conflicts with the recorded STOPPED phase.'
    if run.get('status') in ('FAILED', 'PARTIAL') or run.get('errors_count') or run.get('warnings_count'):
        return 'ATTENTION', 'Latest run recorded a failure or warnings.'
    phase = status.get('phase')
    if service == 'scanner' and status.get('worker_active') and phase in SCANNER_WORK_PHASES:
        if run.get('status') != 'RUNNING':
            return 'ATTENTION', 'Worker lock/phase conflicts with the latest persisted run.'
        if age > HEARTBEAT_GRACE_SECONDS:
            return 'RUNNING', (
                f'Worker lock is held; last progress was {int(age)} seconds ago. '
                'Progress is unverified: provider calls do not emit heartbeats and no completion deadline is recorded.')
        return 'HEALTHY', 'Worker lock is held and scan progress is recent.'

    # next_expected_run describes scheduled work, not process liveness. Even a
    # future slot cannot excuse a missing periodic heartbeat while WAITING.
    if phase == 'WAITING':
        if age > HEARTBEAT_GRACE_SECONDS:
            return 'ATTENTION', 'Waiting service has missed its periodic heartbeats.'
        if status.get('next_expected_run') is not None:
            try:
                due = datetime.fromisoformat(status['next_expected_run'])
                overdue = (now - due).total_seconds()
            except (TypeError, ValueError):
                return 'ATTENTION', 'Next expected run timestamp is invalid.'
            if overdue > HEARTBEAT_GRACE_SECONDS:
                return 'ATTENTION', 'Next expected run is overdue despite a held process lock.'
        return 'IDLE', 'Process heartbeat is fresh; waiting for the next cycle.'

    if service == 'paper' and phase == 'UPDATING':
        # UPDATING heartbeats mark cycle start, not a periodic pulse. Use the
        # configured update cadence plus heartbeat grace to flag missed cycles.
        deadline_seconds = status['interval_minutes'] * 60 + HEARTBEAT_GRACE_SECONDS
        if age > deadline_seconds:
            return 'ATTENTION', 'Paper update has exceeded its configured cadence plus heartbeat grace.'
    elif age > HEARTBEAT_GRACE_SECONDS:
        return 'ATTENTION', 'Heartbeat is stale for this service phase.'
    return 'HEALTHY', 'Process lock is held and timing is within the service cadence.'


def snapshot(*, now=None, integrity=False):
    now = now or datetime.now(timezone.utc)
    store = SettingsStore()
    config = store.load().settings.monitoring
    result = dict(checked_at=now.isoformat(), data_directory=str(data_dir()),
                  settings_warning=store.warning, monitoring=config)
    for name, reader, enabled in (
        ('scanner', scanner_status, config.daily_scan_enabled),
        ('paper', lambda: paper_status(settings=config), config.paper_monitor_enabled),
    ):
        try:
            status = reader()
            # Reject malformed persisted shapes before passing them to the UI.
            for key in ('last_run', 'last_failure'):
                if status.get(key) is not None and not isinstance(status[key], dict):
                    raise ValueError('Invalid run')
            if name == 'paper':
                for key in ('pending', 'open'):
                    if type(status[key]) is not int or status[key] < 0:
                        raise ValueError('Invalid trade count')
        except READ_ERRORS:
            logging.getLogger(__name__).exception('Unable to read %s health status', name)
            status = dict(unavailable=True, process_status='UNKNOWN', pending=None, open=None)
        status['configured'] = enabled if not store.warning else None
        status['health'], status['reason'] = classify(status, now, service=name)
        result[name] = status
    from autot.application.recovery import diagnostics
    result['recovery'] = diagnostics(now=now, integrity=integrity)
    return result
