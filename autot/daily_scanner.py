"""Independent research scanner: python -m autot.daily_scanner [--once | --status]."""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, time, timezone
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time as monotonic_time
from zoneinfo import ZoneInfo

from autot.application.scan_store import ScanStore, stamp
from autot.paper_trade.locking import database_lock, MonitorAlreadyRunning, lock_path
from autot.paper_trade.sessions import MARKETS, SessionCalendar
from autot.runtime import data_dir, PROJECT_ROOT
from autot.settings.models import SettingsState, configuration_hash
from autot.settings.store import SettingsStore
from autot.universe.index_definitions import INDICES

LOGGER = logging.getLogger(__name__)


def load_state():
    store = SettingsStore()
    state = store.load()
    if store.warning:
        raise ValueError('Resolve settings storage warning before scanning.')
    return state


def request_from_state(state):
    s = state.settings.scanner
    d = INDICES[s.index]
    return dict(universe=s.index, market=d.market, period=s.history_period, interval=s.interval,
                top_n=s.top_ranked_count, benchmark_symbol=d.benchmark_symbol,
                quality_threshold=state.settings.monitoring.daily_scan_quality_threshold,
                state=state.model_dump(mode='json'))


def slot(request, now, calendar=None):
    """Today's market-local slot, bounded by close plus provider publication buffer."""
    calendar = calendar or SessionCalendar()
    market = request['market']
    day = now.astimezone(ZoneInfo(MARKETS[market][1])).date()
    bounds = calendar.bounds(market, day)
    if not bounds or request['interval'] != '1d':
        return day.isoformat(), None
    local_time = time.fromisoformat(request['state']['settings']['monitoring']['daily_scan_time_local'])
    due = datetime.combine(day, local_time, ZoneInfo(MARKETS[market][1])).astimezone(timezone.utc)
    return day.isoformat(), max(due, bounds[1] + timedelta(minutes=30))


def next_slot(request, now):
    for offset in range(8):
        _, due = slot(request, now + timedelta(days=offset))
        if due and due > now:
            return due.isoformat()
    return None


def schedule_key(request, session):
    profile = request['state']['profile']
    # Editing presentation/lookback/universe must not silently rerun the same
    # market/session/profile. An explicit manual rerun remains available.
    return configuration_hash(dict(market=request['market'], session=session,
                                   profile_id=profile['profile_id'],
                                   profile_version=profile['profile_version'],
                                   profile_hash=profile['configuration_hash']))


def execute_scan(request, diagnostics, on_stage):
    """Only composition here: all download, analysis and ranking remain authoritative."""
    from autot.application.scanner_service import run_scan
    from autot.market_data.market_data_manager import MarketDataManager
    from autot.performance.performance_tracker import PerformanceTracker
    from autot.paper_trade.scan_context import observe_analysis
    from autot.universe.providers import ProviderUniverseLoader, UploadedCSVProvider
    from autot.universe.index_provider import IndexUniverseProvider
    from autot.settings.configuration_manager import ConfigurationManager
    from autot.runtime import configure_certificates
    from main import analyse_stock
    configure_certificates()
    state = SettingsState.model_validate(request['state'])
    definition = INDICES.get(request['universe'])
    provider = (UploadedCSVProvider(request['csv'].encode()) if 'csv' in request else
                IndexUniverseProvider(request['universe'], cache_dir=ConfigurationManager().get_string('UNIVERSE_CACHE_DIR') or None))
    loader = ProviderUniverseLoader(provider)
    contexts = {}
    settings = {k: request[k] for k in ('universe', 'period', 'interval', 'top_n', 'benchmark_symbol')}
    def on_error(symbol, error):
        LOGGER.error('Analysis failed for %s', symbol, exc_info=(type(error), error, error.__traceback__))

    analysis = observe_analysis(analyse_stock, contexts, interval=request['interval'], market=request['market'])
    if request.get('session'):
        original_analysis = analysis
        def analysis(symbol, data, benchmark, tracker):
            for frame in (data, benchmark):
                if str(frame.index[-1].date()) != request['session']:
                    raise ValueError('Completed session candle unavailable')
            return original_analysis(symbol, data, benchmark, tracker)

    outputs = run_scan(**settings, tracker=PerformanceTracker(),
        analyse_func=analysis,
        universe_loader=loader, batch_data_loader=lambda **kw: MarketDataManager.get_batch_stock_data(**kw,
            on_progress=lambda details: on_stage('loading_market_data', details)),
        benchmark_data_loader=MarketDataManager.get_stock_data, diagnostics=diagnostics,
        settings_state=state, on_stage=on_stage, on_error=on_error,
        on_success=lambda count, total, symbol: on_stage('analysing', {'symbols_analyzed': count}))
    for failure in diagnostics.get('failures', []):
        if failure['reason'] != 'No usable market data returned; cause unverified':
            failure['reason'] = 'Analysis failed; see server logs.'
    # Decisions are transient objects; confirmation reconstructs from the persisted row/context.
    outputs.pop('trade_decisions', None)
    metadata = asdict(loader.result) if loader.result else {}
    metadata.update(benchmark_symbol=request['benchmark_symbol'],
                    benchmark_display_name=definition.benchmark_display_name if definition else '')
    settings['quality_threshold'] = request['quality_threshold']
    return dict(outputs=outputs, settings=settings, diagnostics=diagnostics, errors=[],
                universe_metadata=metadata, paper_signal_context=contexts, settings_state=request['state'])


class DailyScanner:
    def __init__(self, store=None, *, executor=execute_scan, state=load_state,
                 clock=lambda: datetime.now(timezone.utc), stop=None):
        self.store = store or ScanStore()
        self.executor, self.state, self.clock = executor, state, clock
        self.stop = stop if stop is not None else threading.Event()

    def notify(self, run):
        from autot.notifications import enqueue, deliver
        kinds = {'SUCCESS': 'COMPLETED', 'PARTIAL': 'PARTIAL', 'FAILED': 'FAILED'}
        if run['trigger_type'] != 'SCHEDULED' or run['status'] not in kinds:
            return
        try:
            with self.store.connection() as db:
                enqueue(db, 'scan:' + run['scan_run_id'], 'DAILY_SCAN_' + kinds[run['status']],
                        dict(market=run['market'], universe=INDICES[run['universe']].index_name if run['universe'] in INDICES else run['universe'], analyzed=run['symbols_analyzed'],
                             opportunities=run['opportunities_count'], top_opportunity=run.get('top_opportunity'),
                             error_category=run['error_category']), run['completed_at'])
            deliver(self.store, blocking=False)
        except Exception:
            LOGGER.warning('Scan notification unavailable; scan history retained for replay.', exc_info=True)

    def recover(self):
        """Recover only while holding the same lock used for the entire worker life."""
        try:
            with database_lock(self.store.path, 'scan', blocking=False):
                return self._recover_locked()
        except MonitorAlreadyRunning:
            return []

    def _recover_locked(self):
        recovered = []
        for previous in self.store.runs():
            if previous['status'] not in ('RUNNING', 'QUEUED'):
                continue
            # A queued child may still be starting. RUNNING workers always own
            # the execution lock, so its absence is stronger evidence than age.
            if previous['status'] == 'QUEUED':
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous['requested_at'])).total_seconds()
                if age < 120 or process_alive(previous.get('worker_pid')):
                    continue
            previous.update(status='FAILED', error_category='WORKER_INTERRUPTED', completed_at=stamp())
            self.store.save(previous)
            recovered.append(previous['scan_run_id'])
        return recovered

    def work(self, run):
        with database_lock(self.store.path, 'scan', blocking=False):
            self._recover_locked()
            run = self.store.get(run['scan_run_id'])
            if run['status'] != 'QUEUED':
                return run
            run.update(status='RUNNING', started_at=stamp(), heartbeat_at=stamp(), worker_pid=os.getpid())
            self.store.save(run)
            diagnostics = {}
            last_write = 0.0
            def stage(phase, details):
                nonlocal last_write
                changed_phase = run.get('phase') != phase
                run['phase'] = phase
                for key in ('symbols_fetched', 'symbols_analyzed', 'symbols_failed'):
                    if key in details:
                        run[key] = details[key]
                if phase == 'universe_loaded':
                    run['symbols_total'] = details['count']
                if changed_phase or monotonic_time.monotonic() - last_write >= 2:
                    run['heartbeat_at'] = stamp()
                    self.store.save(run)
                    self.store.heartbeat('worker', phase)
                    last_write = monotonic_time.monotonic()
            try:
                stage('STARTING', {})
                saved = self.executor(run['request'], diagnostics, stage)
                outputs = saved['outputs']
                rows = outputs['results']
                run['symbols_fetched'] = len(outputs['symbols'])
                run['symbols_analyzed'] = len(rows)
                run['symbols_failed'] = run['symbols_fetched'] - len(rows)
                run['failures'] = diagnostics.get('failures', [])
                opportunities = [r for r in outputs['trade_opportunities'] if r.get('trade_quality_score', 0) >= run['request']['quality_threshold']]
                run['opportunities_count'] = len(opportunities)
                outputs['trade_opportunities'] = opportunities
                if opportunities:
                    top = opportunities[0]
                    run['top_opportunity'] = f"{top['symbol']} {top['signal']} · quality {top['trade_quality_score']:.2f}"
                run['status'] = ('PARTIAL' if run['symbols_failed'] else 'SUCCESS') if rows else ('FAILED' if outputs['symbols'] else 'NO_WORK')
                if run['status'] == 'FAILED':
                    run['error_category'] = 'NO_USABLE_RESULTS'
                run.update(completed_at=stamp(), result_location='scan_runs:' + run['scan_run_id'])
                saved['scan_run_id'] = run['scan_run_id']
                saved['completed_at'] = run['completed_at']
                self.store.save(run, saved)
            except BaseException as error:
                run.update(status='FAILED', completed_at=stamp(),
                           error_category='INTERRUPTED' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'SCAN_FAILED',
                           failures=[dict(symbol=f['symbol'], reason='Scan failed; see worker logs.')
                                     for f in diagnostics.get('failures', [])])
                run['symbols_failed'] = max(run['symbols_failed'], len(run['failures']))
                self.store.save(run)
                if not isinstance(error, Exception):
                    raise
                LOGGER.exception('Scan failed')
            finally:
                self.store.heartbeat('worker', 'STOPPED')
                self.notify(run)
            return run

    def once(self, request=None):
        request = request or request_from_state(self.state())
        with database_lock(self.store.path, 'submission', blocking=False):
            self.recover()
            self.ensure_available()
            return self.work(self.store.create(request))

    def ensure_available(self):
        if active(self.store.path, 'scan') or any(r['status'] in ('QUEUED', 'RUNNING') for r in self.store.runs()):
            raise MonitorAlreadyRunning('A scan is already submitted or running.')

    def cycle(self):
        # Share admission with manual submissions. A busy worker is normal:
        # leave the scheduled slot unconsumed and retry on the next cycle.
        try:
            with database_lock(self.store.path, 'submission', blocking=False):
                if active(self.store.path, 'scan'):
                    return None
                self.recover()
                if any(r['status'] == 'QUEUED' and r['trigger_type'] == 'MANUAL'
                       for r in self.store.runs()):
                    return None
                return self._cycle_locked()
        except MonitorAlreadyRunning:
            return None

    def _cycle_locked(self):
        state = self.state()
        if not state.settings.monitoring.daily_scan_enabled:
            return None
        request = request_from_state(state)
        now = self.clock()
        session, due = slot(request, now)
        key = schedule_key(request, session)
        # One attempt per daily slot, including failure; no network retry storm.
        previous = next((r for r in self.store.runs() if r['schedule_key'] == key), None)
        if previous:
            if previous['status'] == 'QUEUED':
                return self.work(previous)
            return None
        if due and now < due:
            if any(r['session'] == session and r['error_category'] == 'SESSION_NOT_COMPLETE_OR_NOT_DUE' for r in self.store.runs()):
                return None
            run = self.store.create(request, 'SCHEDULED', session)
            run.update(status='SKIPPED', completed_at=stamp(), error_category='SESSION_NOT_COMPLETE_OR_NOT_DUE')
            self.store.save(run)
            return run
        request['session'] = session
        run = self.store.create(request, 'SCHEDULED', session, key)
        if not due:
            run.update(status='SKIPPED', completed_at=stamp(), error_category='INELIGIBLE_SESSION_OR_INTERVAL')
            self.store.save(run)
            return run
        return self.work(run)

    def run(self):
        with database_lock(self.store.path, 'scheduler', blocking=False):
            try:
                try:
                    with database_lock(self.store.path, 'scan', blocking=False):
                        self._recover_locked()
                except MonitorAlreadyRunning:
                    pass  # A live manual scan owns its run state.
                # Replay missed notification projection after crash; enqueue is idempotent.
                for run in self.store.runs():
                    self.notify(run)
                while not self.stop.is_set():
                    state = self.state()
                    if not state.settings.monitoring.daily_scan_enabled:
                        break
                    self.cycle()
                    # Delivery retries only inspect the local outbox, never market data.
                    try:
                        from autot.notifications import deliver
                        deliver(self.store, blocking=False)
                    except Exception:
                        LOGGER.warning('Scan notification delivery unavailable')
                    self.store.heartbeat('scheduler', 'WAITING', next_slot(request_from_state(state), self.clock()))
                    self.stop.wait(15)
            finally:
                self.store.heartbeat('scheduler', 'STOPPED')


def active(path, kind):
    import fcntl
    try:
        with lock_path(path, kind).open('r') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except FileNotFoundError:
        pass
    return False


def process_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_status():
    import sqlite3
    path = data_dir() / 'scanner' / 'scans.sqlite3'
    state = load_state()
    result = dict(configured=state.settings.monitoring.daily_scan_enabled,
                  process_status='ACTIVE' if active(path, 'scheduler') or active(path, 'scan') else 'NOT DETECTED',
                  phase=None, heartbeat=None, last_run=None, last_success=None, last_failure=None,
                  next_expected_run=next_slot(request_from_state(state), datetime.now(timezone.utc)),
                  last_scanned_market_session=None, latest_results_timestamp=None)
    if not result['configured']:
        result['next_expected_run'] = None
    if not path.exists():
        return result
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        runs = [json.loads(r[0]) for r in db.execute('SELECT payload FROM scan_runs ORDER BY rowid DESC')]
        # PARTIAL is a usable completed scan; interruptions are recorded as FAILED.
        for key, statuses in [('last_run', None), ('last_success', ('SUCCESS', 'PARTIAL')), ('last_failure', ('FAILED',))]:
            result[key] = next((r for r in runs if statuses is None or r['status'] in statuses), None)
        completed = sorted((r for r in runs if r['status'] in ('SUCCESS', 'PARTIAL')),
                           key=lambda r: r['completed_at'], reverse=True)
        if completed:
            result['latest_results_timestamp'] = completed[0]['completed_at']
            result['last_scanned_market_session'] = next((r['session'] for r in completed if r['session']), None)
        name = 'worker' if active(path, 'scan') else 'scheduler'
        row = db.execute('SELECT payload FROM scanner_status WHERE name=?', (name,)).fetchone()
        if row:
            result.update(json.loads(row[0]))
    finally:
        db.close()
    if result['process_status'] != 'ACTIVE':
        result['next_expected_run'] = None
    if not result['configured']:
        result['next_expected_run'] = None
    from autot.notifications import read_status as notification_status
    result['notifications'] = notification_status(path)
    return result


def launch(request):
    """Persist submission before detached launch. No UI worker threads or shell."""
    store = ScanStore()
    with database_lock(store.path, 'submission', blocking=False):
        scanner = DailyScanner(store=store)
        scanner.recover()
        scanner.ensure_available()
        run = store.create(request)
        try:
            with (store.path.parent / 'worker.log').open('ab') as log:
                log.write(("Starting scan " + run['scan_run_id'] + "\n").encode())
                log.flush()
                child = subprocess.Popen([sys.executable, '-m', 'autot.daily_scanner', '--job', run['scan_run_id']],
                                 cwd=PROJECT_ROOT, env={**os.environ, 'AUTOT_DATA_DIR': str(data_dir())},
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            # The child takes submission lock before reading this record.
            run['worker_pid'] = getattr(child, 'pid', None)
            store.save(run)
        except Exception:
            run.update(status='FAILED', error_category='LAUNCH_FAILED', completed_at=stamp())
            store.save(run)
            raise
    return run['scan_run_id']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--once', action='store_true')
    group.add_argument('--status', action='store_true')
    group.add_argument('--job', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.status:
        print(json.dumps(read_status(), indent=2))
        return 0
    if not args.once and not args.job and not load_state().settings.monitoring.daily_scan_enabled:
        print('Daily scanner disabled.')
        return 0
    scanner = DailyScanner()
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, lambda *_: scanner.stop.set())
    try:
        if args.once or args.job:
            if args.job:
                with database_lock(scanner.store.path, 'submission'):
                    job = scanner.store.get(args.job)
                run = scanner.work(job)
            else:
                run = scanner.once()
            print(json.dumps(run, indent=2))
            return 1 if run['status'] == 'FAILED' else 0
        scanner.run()
        return 0
    except MonitorAlreadyRunning:
        LOGGER.warning('Another scanner owns the execution/scheduler lock.')
        return 2
    except KeyboardInterrupt:
        return 0
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    raise SystemExit(main())
