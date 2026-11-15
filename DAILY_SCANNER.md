# Automatic Daily Scanner V1

The daily scanner produces research only. It never confirms paper trades, reserves
capital, or submits orders. Human confirmation and all existing paper risk checks
remain required. Strategy calculations, weights, sizing, NEXT_SESSION_OPEN and
STOP_FIRST are unchanged.

## Architecture and UI

`autot.daily_scanner.execute_scan` composes the existing
`autot.application.scanner_service.run_scan`, `main.analyse_stock`, index providers,
universe cache and hardened MarketDataManager downloads. There is one authoritative
analysis/ranking implementation. Each run snapshots saved settings and the active
profile ID, version, hash and configuration.

Streamlit's Run Scan persists a request and starts an independent Python process.
It immediately returns; switching workspaces, disconnecting or reopening Streamlit
does not cancel that process. Refresh scan status/results to load completed results.
There are no Streamlit background threads. CSV uploads are validated and captured
in the job; the worker does not depend on the browser's uploaded-file lifetime.
A service/container restart can still terminate its children: use a persistent
service host for continuous daily scheduling.

## Settings and session timing

Settings → Monitoring:

- `daily_scan_enabled`: false by default; controls continuous scheduling only.
- `daily_scan_time_local`: `22:00`, in the selected **market's** timezone, not the
  browser/server timezone. DST follows the market's IANA timezone.
- `daily_scan_quality_threshold`: 70–100, default 70; a research display/notification
  filter on existing qualified opportunities. It never changes trading decisions.

The saved Scanner country/index supplies the daily market/universe; period,
interval and top-N come from the same saved configuration. The active strategy
profile is captured when submitting each job. UI manual form overrides apply to
that job only.

A daily session is eligible at the later of the configured local time and regular
session close plus 30 minutes. An early configured time cannot bypass the close.
Only `1d` is scheduled. Weekends/unsupported intervals record SKIPPED; checks before
the slot record one SKIPPED record per session without preventing the later run.
Scheduled analysis requires each symbol and benchmark's latest candle date to match
the intended session; stale data cannot masquerade as today's result.

The existing SessionCalendar weekday fallback is retained: no holiday or early-close
calendar is added. A holiday may therefore produce a failed run for missing current
session candles. The 30-minute buffer is not a guarantee of provider publication.
The service does not catch up historical missed sessions; a late start runs today's
eligible session, otherwise waits for the next session.

## CLI and deployment

From the AutoT checkout, using its Python environment:

```sh
python -m autot.daily_scanner --once
python -m autot.daily_scanner
python -m autot.daily_scanner --status
```

`--once` runs synchronously in the invoking process, prints the terminal run record,
and exits (1 for FAILED, 2 for an occupied scanner). It never detaches. It uses saved settings, even when scheduling is
disabled. Manual scans can run before close and use the existing candle provenance
checks for paper eligibility; they do not claim to be completed scheduled sessions.
Continuous mode requires enabling the saved setting. `--status` recovers abandoned runs in existing scanner storage, then reports status.
It does not create absent storage, fetch prices, start scans, or touch paper/settings databases. The hidden `--job ID` is used by Streamlit.
Ctrl+C/SIGTERM records an interrupted run and releases locks; in-flight provider or
thread-pool cleanup can delay exit.

For 24×7 operation, run continuous mode under launchd/systemd or a supervised
container using the checkout's virtual environment and a persistent writable
`AUTOT_DATA_DIR`. The UI and service must share that directory. Host sleep, process
termination and container suspension pause scheduling. Status distinguishes enabled
configuration from a process actually holding the scheduler/worker lock. Heartbeats
are written at scheduler waits and worker stage/progress transitions, not by a
separate heartbeat thread. Long provider calls may leave an older heartbeat.

## Persistence, concurrency and failures

`AUTOT_DATA_DIR/scanner/scans.sqlite3` contains append-only run history (each run's
state progresses from QUEUED/RUNNING to its terminal state), complete JSON research
results, scanner status and a Notifications V1 outbox. It is separate from the paper
ledger and never initializes or migrates the production paper database.

Results preserve every analysis row including signal, confidence, agreement, regime,
entry, stop, target, R:R, historical/quality/opportunity scores, strategy features,
universe provenance, candle context and settings/profile snapshot. Transient decision
objects are omitted; the existing explicit confirmation UI uses saved rows/context.
Nonfinite numeric results serialize as null, never as made-up prices.

SUCCESS and PARTIAL results remain viewable across restarts. A later FAILED run does
not replace the last usable result. If no usable scan has ever completed, an empty
failed scan's diagnostics can be displayed. Run records retain counts, failed symbols,
error category, timestamps, session and result reference. Detailed exception traces
are in `scanner/worker.log` for detached UI workers or the service log.

Daily scanner status reports `last_success` as the most recent SUCCESS or PARTIAL
run: both completed with usable analysis, while PARTIAL retains its symbol-level
failures and original status. `last_failure` includes only FAILED runs (including
INTERRUPTED and WORKER_INTERRUPTED errors). A PARTIAL run does not replace an earlier
failure. `last_run` still reports the latest attempt regardless of status; NO_WORK,
SKIPPED, QUEUED and RUNNING do not count as success or failure.

POSIX advisory locks serialize all scan execution, and a separate lock permits only
one continuous scheduler per database. Lock files must not be deleted while services
run. Locks are local-host protection, not distributed/NFS coordination. Manual submissions use a separate submission lock and reject duplicate QUEUED/RUNNING jobs.
Scheduled checks share the submission lock and wait while a manual job is queued
or running, leaving the session slot available for the next check.
The worker owns the execution lock for its entire RUNNING lifetime. Status inspection,
submission and scheduler startup recover RUNNING jobs only after acquiring that lock
nonblocking. Absence of the lifetime lock proves interruption, so no arbitrary heartbeat
age is needed for RUNNING recovery. An old heartbeat with a held lock is a slow active
worker, never a failed scan. PID alone is not authoritative because operating systems
reuse PIDs. Recovery marks FAILED / WORKER_INTERRUPTED, preserves history and counters,
and is idempotent. It never retries or creates a scan. Scheduled keys remain consumed.
QUEUED detached jobs get a 120-second startup grace and are recovered only when their
recorded PID no longer exists. Workers record PID and heartbeat_at on their run.
Detached stdout/stderr goes to scanner/worker.log with a run-ID launch marker.

Progress persists at stage boundaries and at most every two seconds within a stage.
symbols_total is universe size; symbols_fetched counts completed universe download
outcomes (including exhausted data failures), symbols_analyzed counts successful
analysis rows, and symbols_failed counts exhausted download/analysis failures.
Pending retries are not counted as completed downloads. Terminal SUCCESS/PARTIAL
counts reconcile against universe and result rows. Heartbeats describe observed progress,
not a timer: a blocking provider call can leave an old heartbeat while the lifetime lock
still identifies the worker as active. Abrupt termination can lose the last throttled
progress interval; recovery never invents missing counts. No Streamlit threads are used.

A durable schedule key includes market/session and profile ID/version/hash. One scheduled attempt per key prevents duplicate success and also
prevents aggressive retries after partial/provider failure. The next eligible daily
session gets a new attempt; manual reruns remain available. Changing lookback, top-N or universe does not automatically repeat a completed
market/session/profile; use a manual rerun. Waiting checks every 15 seconds read settings/status only;
they never poll/download the universe.

## Notifications

Completed scheduled runs enqueue DAILY_SCAN_COMPLETED, DAILY_SCAN_PARTIAL or
DAILY_SCAN_FAILED through the shared Notifications V1 schema and delivery adapter.
Messages contain market, universe, analyzed/opportunity counts and one top opportunity,
not result tables. Delivery respects saved notification enable/channel settings.
The outbox lives with scan research, separate from paper notifications. Run history
commits before notification processing; a channel failure cannot corrupt results.
Scheduler startup replays terminal history using idempotent notification IDs; waiting cycles retry due outbox deliveries without fetching market data. Status
includes scan notification delivery history. Notifications V1 currently uses console
logging; keep service logs accessible to the operator.
