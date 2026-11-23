# Continuous operation and restart recovery

These examples are inactive templates. Nothing is installed or enabled by this change.
Use one host and one persistent local-disk `AUTOT_DATA_DIR` shared by the UI and workers.
Do not delete SQLite databases, sidecars or lock files to restart. Never use ephemeral
storage for paper trades. Older Web V1 notes in DEPLOYMENT.md predate these durable services.

## Local operations

From the checkout, with its virtual environment activated:

```sh
python -m autot.ops status
python -m autot.ops check
python -m autot.ops validate --service paper
python -m autot.ops validate --service scanner
python -m autot.ops validate --service web
python -m autot.paper_monitor
python -m autot.daily_scanner
python -m streamlit run web_app.py
```

`status` reads state. `check` also runs SQLite quick_check; neither repairs state or
calls market providers. `validate` additionally probes storage using temporary files,
checks service configuration and duplicate ownership, and exits nonzero on errors.
Missing databases are explicitly reported, not created: they may mean first startup
or a wrong data root. Provision the root yourself and verify its identity before launch.
Validation is a point-in-time check; lifetime service locks remain authoritative.
`--once` on the existing monitor/scanner is actual work, not a health check.

System Health shows the same startup/recovery diagnostics. Pending/open counts, last
runs and heartbeats are separate from live lock ownership. A leftover lock file is
normal: the kernel releases ownership on exit/crash; files must never be unlinked.
Only the lock holder performs recovery writes. No PID-based killing or lock deletion
is needed. Detection is local to the host, not a distributed lease.

## What survives

- `paper_trading/ledger.sqlite3`: pending/open/closed trades, reservations, immutable
  snapshots, audit events, processed-bar checkpoints, runs and notification outbox.
  Monitor startup immediately checks active trades using existing completed-bar rules.
  Committed state and events are transactional; replay starts after saved checkpoints.
  Interrupted scheduled run metadata is marked interrupted without deleting trades.
- `scanner/scans.sqlite3`: requests, results/history, schedule keys, heartbeat and outbox.
  Startup reconciles orphan runs under the worker lock. A consumed scheduled slot is
  not retried automatically, even after failure. Only today's eligible slot catches up;
  earlier missed sessions are not backfilled. Use an explicit manual scan when needed.
  Queued children have a 120-second startup grace and live-PID guard.
- `settings/settings.sqlite3`: saved configuration and profiles. Services must be enabled
  there; default settings disable background monitoring/scanning.
- `real_trade_journal/real_trade_journal.sqlite3`: independent journal; unchanged here.

Streamlit browser/session state does not survive a server restart. Persisted scanner
results remain available. UI restart does not stop independently launched workers.
The optional `python -m autot.notifications` worker retries the paper outbox; scanner
outbox delivery belongs to the scanner. Delivery is at-least-once: a remote acceptance
followed by a crash before local acknowledgement can produce a duplicate notification.

## Shutdown and failure

Ctrl+C/SIGTERM asks monitor, scanner and notification loops to finish current work,
then release locks; monitor/scanner persist STOPPED. Normal shutdown does not turn a
successful scan into FAILED. Provider requests or lock waits may delay this shutdown.
SIGKILL/power loss cannot write STOPPED; trust lock ownership over historical PID/phase.
Restart resumes durable work, subject to provider intraday-history availability. Missing
history continues to require review through existing paper rules; no fills are invented.
No watchdog or bounded provider-call cancellation has been added.

## Linux/systemd preparation (manual, on the future target only)

Review `systemd/*.service` and `autot.env.example`. Replace `/opt/autot`, virtualenv
path and service account if needed. Provision `/var/lib/autot` owned by `autot`, install
compatible dependencies into `/opt/autot/venv`, and copy the environment file to
`/etc/autot/autot.env` with restricted access. Restore/verify existing data before start.
Validate all three services as the service user with the same environment.

The templates use network-online ordering and restart on failure with a 15-second
backoff and systemd start-rate limits. Workers are independent; no UI ordering is
required. A finite 10-minute stop timeout allows in-flight work to finish, then systemd
may force termination; adjust after measuring real scans. On a forced kill, next startup
uses normal crash recovery. Streamlit detached manual workers remain in its cgroup;
service stop signals the whole group. For long scans increase TimeoutStopSec.

Logs go to journald (`journalctl -u autot-paper-monitor -f`, similarly for other units).
Detached UI scan output also uses `scanner/worker.log`; configure rotation on the target.
Configure journald retention, disk monitoring, private access/authentication/TLS, clock
synchronization and host sleep prevention. Check SQLite backup/restore with services
stopped (or use SQLite online backup); copying a live DB alone can omit WAL state.
Do not copy a developer .env or caches containing credentials into deployment bundles.

Before installation, run `systemd-analyze verify` on the Linux target, test SIGTERM and
reboot recovery with an isolated data copy, and verify network/provider access. These
units have not been installed, activated or Linux-tested on this Mac.
