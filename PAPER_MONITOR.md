# Automatic Paper Monitoring / Scheduler V1

The monitor runs the same bounded `PaperTradingService.update_positions()` pass
as **Update Paper Positions**. It checks only already confirmed `PENDING_ENTRY`
and `OPEN` paper trades, including both FORWARD_TEST and RESEARCH trades. It never
scans, selects opportunities, confirms trades, changes strategy signals/weights,
changes admission or sizing rules, or sends broker orders.

## Architecture and configuration

`python -m autot.paper_monitor` is a separate foreground process. Streamlit only
shows configuration, status and commands. Browser refresh/closure does not start,
stop or keep the monitor alive. No Streamlit background thread or daemon button
is installed. A threading Event is used solely as an interruptible wait primitive;
the monitor executes synchronously on one thread.

Settings → Monitoring:

- `paper_monitor_enabled`: **false by default**, including old saved settings.
- `paper_update_interval_minutes`: existing positive interval, default **5**.
- `daily_scan_enabled`: remains reserved; it does not run Scanner.

Old settings revisions are verified using their original signed shape, then the
missing enabled flag defaults to false in memory. Saved revisions are not rewritten.
Monitoring settings do not change the strategy profile/configuration hash.
Settings are reloaded before cycles and during waits. Disabling ends the process
after the current pass or within 15 seconds while waiting. Re-enabling requires
starting the external process again. Corrupt/unreadable settings stop startup or
the running loop visibly, instead of silently using an unsafe fallback.

## Run manually on macOS

Use the same virtual environment and `AUTOT_DATA_DIR` as the UI. From a terminal:

```bash
cd /Users/sreedevpv/projects/AutoT
source venv/bin/activate
python -m autot.paper_monitor --status
```

Enable **Paper monitor enabled** and save in Settings → Monitoring before using:

```bash
# One scheduled pass; requires the saved enabled flag too.
python -m autot.paper_monitor --once

# Continuous foreground service; stop using Ctrl+C.
python -m autot.paper_monitor
```

These are operator commands, not installation-time actions. Starting an enabled
monitor immediately runs a valid pass over existing pending/open trades. It can
fill a previously confirmed pending trade; it cannot create or confirm a trade.
A disabled launch does not even initialize the paper ledger. `--status` reads
existing storage without migrations or provider requests, even if monitoring is OFF.
Exit codes: 0 normal/disabled/no work, 1 failed one-shot or unexpected fatal error,
2 another monitor owns the lock. A partial one-shot returns 0; inspect its JSON
status and warning/error counts. Fatal exceptions print a traceback.

For an isolated sandbox, set `AUTOT_DATA_DIR` to a separate directory before any
commands. Do not point tests at the operator database. Tests use isolated fixtures
and offline providers; subprocess tests use empty isolated ledgers.

## Single instance, manual compatibility and timing

Two advisory POSIX `flock` files sit alongside the resolved database path:
`ledger.sqlite3.monitor.lock` protects the automatic process lifetime, and
`ledger.sqlite3.update.lock` serializes every manual and scheduled update pass.
A second automatic process exits with a clear message. Manual updates remain
available and wait for an active pass to finish. Existing SQLite transactions,
revision checks, capital reservations and atomic audit writes still apply to all
trade mutations, including concurrent confirmations and manual close requests.

Locks are released by the OS on close, normal exit or crash/SIGKILL; leftover files
are harmless and need no PID/lease timeout. **Do not delete lock files**, replace
the database, or run older code that bypasses these locks while workers are live.
Use one canonical database path on one local filesystem. V1 targets macOS/Linux;
it does not support Windows, multi-host locks, network filesystems or hard-link
aliases to a database.

The first pass is immediate. Subsequent starts follow a monotonic fixed cadence;
missed slots are skipped. A seven-minute pass at a five-minute interval runs next
at minute ten, never concurrently at minute five and never as a backlog burst.
A live interval change starts a fresh wait using the new interval. Heartbeat and
settings checks wake at most every 15 seconds during waits. There is no busy loop.
Ctrl+C/SIGTERM requests shutdown after the current bounded pass and releases both
locks; it does not interrupt an in-progress SQLite mutation.

## Execution and recovery

Execution remains **5m / NEXT_SESSION_OPEN / STOP_FIRST**. The shared service
checks `SessionCalendar.completed_starts()` before provider requests, and evaluates
only a contiguous chronological prefix of completed bars. Incomplete current
candles cannot fill or exit positions. No active trades produces `NO_WORK` with
zero provider requests. Before eligibility, or outside sessions with no outstanding
completed bars, the provider is not called. Catch-up can still be necessary after
market close, so there is no blanket off-hours suppression.

Restart uses persisted `last_checked_at + 5m` (or `eligible_at` for a pending entry).
It processes intervening completed bars in chronological order. Repeated passes
over the same bars do not duplicate fills, exits, realized P&L or lifecycle events.
Unresolved missing bars stop progress and retain review-required behavior; the
monitor never skips a missing bar or fabricates prices. Review flags clear only
when the shared service can verify the data again.

Provider/history/quote/capital verification failures record FAILED/PARTIAL and
review evidence without inventing execution. Later intervals retry normally.
Yahoo's existing bounded connection/read timeouts and history limits are unchanged;
this intraday adapter has no immediate retry loop, and the scheduler adds none.
Successful changes for other trades in a partial run remain committed. Unexpected
programming/storage failures escape the loop and terminate visibly. On restart,
the exclusive owner marks abandoned SCHEDULED RUNNING records FAILED with
`PROCESS_INTERRUPTED`; manual run history is preserved.

## Run history and status

`paper_update_runs` remains the sole run-history table. Its schema migration
widens source/status constraints without changing run IDs, counts, timestamps,
event references, trade snapshots or trade state. It records MANUAL/SCHEDULED,
start/completion time, provider, checked/updated/opened/closed counts, bars,
review warnings/errors and a summary/error category. Statuses are RUNNING,
SUCCESS, PARTIAL, FAILED and NO_WORK. `completed_at` is the finish timestamp.

A singleton `paper_monitor_status` row stores process PID, phase, heartbeat and
next expected run; it is current process metadata, not another run-history table.
The Paper Trading **Paper Monitor** panel and JSON `--status` show:

- Configured ON/OFF independently of process ACTIVE/NOT DETECTED.
- Interval, pending/open counts, heartbeat, phase and next expected run.
- Last scheduled run, last SUCCESS, and last FAILED/PARTIAL run.

ACTIVE is determined by the OS lock, not the enabled flag or a stale PID.
It proves ownership, not progress: the heartbeat updates at cycle boundaries and
every 15 seconds while waiting, but does not advance during a long provider call
or while waiting for a manual update lock. A stale heartbeat with an active lock
requires investigation. Next expected run is unavailable while updating or when
no process is detected. Status is a point-in-time observation; refresh the UI to
see changes. NO_WORK is a normal completed idle cycle, not a failure. It updates
the last scheduled run and heartbeat but neither last SUCCESS nor last failure.
`last_success` intentionally remains null until a scheduled SUCCESS exists, and
later NO_WORK cycles preserve that earlier SUCCESS. SUCCESS can include active
trades with no completed bars due; it does not promise a fill or processed bar.

## Known limitations and future work

The existing local weekday SessionCalendar remains the source of truth. Holidays
and shortened sessions are not newly modeled; missing expected bars require
review. Yahoo's finite intraday history window can prevent full recovery after a
long outage. An authoritative holiday calendar and more durable historical data
are future work.

**FILL-TIME RISK RECHECK** is a future enhancement: after receiving an actual fill,
recompute stop risk and optionally reduce size or reject entry. Next-session gaps
can make actual fill-adjusted stop risk materially different from planned stop
risk. Scheduler V1 deliberately retains current sizing/execution and capital
checks; it does not implement this enhancement or rewrite existing trades.

For future 24/7 operation, run this same foreground CLI under launchd/systemd or
one supervised container with a persistent local volume and the same settings
and ledger directory. Add restart backoff, log rotation and stale-heartbeat
alerts. Deploy a single owner, stop old workers before upgrades, and test backup
and recovery. No supervisor, automatic startup or remote deployment is installed
by V1. Multi-host operation would require a different coordination design.
