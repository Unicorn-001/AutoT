"""Independent paper monitor: python -m autot.paper_monitor [--once | --status]."""
import argparse
from datetime import timedelta
import json
import logging
import math
import os
from pathlib import Path
import signal
import sqlite3
import threading
import time

from autot.paper_trade.intraday import YahooIntradayProvider
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.locking import MonitorAlreadyRunning, database_lock, monitor_active
from autot.paper_trade.service import PaperTradingService, now_utc
from autot.runtime import data_dir
from autot.settings.store import SettingsStore

LOGGER = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15


def monitoring_settings():
    store = SettingsStore()
    state = store.load()
    if store.warning:
        raise RuntimeError('Resolve the settings storage warning before running the monitor.')
    return state.settings.monitoring


def read_status(database=None, *, settings=None):
    """Read-only diagnostics: no schema migration, database creation or provider IO."""
    path = Path(database) if database else data_dir() / 'paper_trading' / 'ledger.sqlite3'
    config = settings if settings is not None else monitoring_settings()
    result = dict(configured=config.paper_monitor_enabled,
                  interval_minutes=config.paper_update_interval_minutes,
                  process_status='ACTIVE' if monitor_active(path) else 'NOT DETECTED',
                  heartbeat=None, next_expected_run=None, phase=None, pid=None,
                  pending=0, open=0, last_run=None, last_success=None, last_failure=None)
    if not path.exists():
        return result
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'paper_monitor_status' in tables:
            row = db.execute('SELECT payload FROM paper_monitor_status WHERE singleton=1').fetchone()
            if row:
                payload = json.loads(row[0])
                if not isinstance(payload, dict):
                    raise ValueError('Invalid paper monitor status payload')
                # Persisted diagnostics cannot override live lock detection/counts.
                for key in ('heartbeat', 'next_expected_run', 'phase', 'pid'):
                    result[key] = payload.get(key)
        if 'trades' in tables:
            for row in db.execute("SELECT json_extract(state, '$.status') AS status, count(*) AS n "
                                  "FROM trades GROUP BY status"):
                if row['status'] in ('PENDING_ENTRY', 'OPEN'):
                    result['pending' if row['status'] == 'PENDING_ENTRY' else 'open'] = row['n']
        if 'paper_update_runs' in tables:
            for key, clause in [('last_run', ''), ('last_success', " AND status='SUCCESS'"),
                                ('last_failure', " AND status IN ('FAILED','PARTIAL')")]:
                row = db.execute("SELECT * FROM paper_update_runs WHERE trigger_type='SCHEDULED'" +
                                 clause + ' ORDER BY rowid DESC LIMIT 1').fetchone()
                result[key] = dict(row) if row else None
    finally:
        db.close()
    if result['process_status'] != 'ACTIVE':
        result['next_expected_run'] = None
    return result


class PaperMonitor:
    """Synchronous cycles; injectable timing permits deterministic offline tests."""
    def __init__(self, service, *, settings=monitoring_settings, monotonic=time.monotonic,
                 clock=now_utc, stop=None):
        self.service = service
        self.settings = settings
        self.monotonic, self.clock = monotonic, clock
        self.stop = stop if stop is not None else threading.Event()

    def heartbeat(self, phase, next_run=None):
        self.service.ledger.monitor_heartbeat(dict(
            heartbeat=self.clock().isoformat(), pid=os.getpid(), phase=phase,
            next_expected_run=next_run.isoformat() if next_run else None))

    def cycle(self):
        LOGGER.info('Paper monitor cycle started')
        self.heartbeat('UPDATING')
        try:
            self.service.update_positions(source='SCHEDULED')
        finally:
            from autot.notifications import process
            process(self.service.ledger)
        run = self.service.ledger.get_run(self.service.last_update_run_id)
        LOGGER.log(logging.WARNING if run['status'] in ('FAILED', 'PARTIAL') else logging.INFO,
                   'Paper monitor cycle completed: %s; checked=%s opened=%s closed=%s reviews=%s errors=%s',
                   run['status'], run['trades_considered'], run['trades_opened'], run['trades_closed'],
                   run['warnings_count'], run['errors_count'])
        return run

    def run(self, *, once=False):
        config = self.settings()
        if not config.paper_monitor_enabled:
            LOGGER.info('Paper monitor disabled; enable it in Monitoring settings')
            return None
        with database_lock(self.service.ledger.path, 'monitor', blocking=False):
            LOGGER.info('Paper monitor started; lock acquired')
            try:
                self.service.ledger.recover_monitor_runs()
                due = self.monotonic()
                while not self.stop.is_set():
                    config = self.settings()
                    if not config.paper_monitor_enabled:
                        break
                    interval = config.paper_update_interval_minutes * 60
                    started = due
                    run = self.cycle()
                    if once:
                        return run
                    # Fixed cadence, skipping missed slots; never pile up or overlap.
                    elapsed = max(0, self.monotonic() - started)
                    due = started + (math.floor(elapsed / interval) + 1) * interval
                    while not self.stop.is_set():
                        remaining = max(0, due - self.monotonic())
                        self.heartbeat('WAITING', self.clock() + timedelta(seconds=remaining))
                        if remaining == 0:
                            break
                        if self.stop.wait(min(HEARTBEAT_SECONDS, remaining)):
                            break
                        refreshed = self.settings()
                        if not refreshed.paper_monitor_enabled:
                            return None
                        new_interval = refreshed.paper_update_interval_minutes * 60
                        if new_interval != interval:
                            # A changed interval begins a fresh wait, avoiding a burst.
                            interval = new_interval
                            due = self.monotonic() + interval
            finally:
                self.heartbeat('STOPPED')
                LOGGER.info('Paper monitor stopped; releasing lock')
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--once', action='store_true', help='One scheduled pass (requires enabled setting)')
    group.add_argument('--status', action='store_true', help='Read-only JSON status')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.status:
        print(json.dumps(read_status(), indent=2))
        return 0
    # Disabled startup does not initialize/migrate even the paper database.
    if not monitoring_settings().paper_monitor_enabled:
        print('Paper monitor disabled. Enable paper_monitor_enabled in Settings → Monitoring.')
        return 0
    stop = threading.Event()  # Wait primitive only; no background thread is started.
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, lambda *_: stop.set())
    try:
        monitor = PaperMonitor(PaperTradingService(Ledger(), YahooIntradayProvider()), stop=stop)
        result = monitor.run(once=args.once)
        if result:
            print(json.dumps(result, indent=2))
            return 1 if result['status'] == 'FAILED' else 0
        return 0
    except MonitorAlreadyRunning as error:
        LOGGER.error('%s', error)
        return 2
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    raise SystemExit(main())
