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

## Verified backups and disaster recovery

No services or timers are installed by these changes. The backup commands do not
change trading logic, initialize missing stores, or contact providers.

### Inventory and consistency

All five databases are **required** by format version 1:

| Path under AUTOT_DATA_DIR | Durable contents | SQLite mode observed |
| --- | --- | --- |
| `paper_trading/ledger.sqlite3` | Accounts, trades, reservations, immutable snapshots, audit, checkpoints, monitor runs/status, notification outbox/checkpoints/health | WAL |
| `scanner/scans.sqlite3` | Requests, history/results, schedule keys, worker status, notification outbox | DELETE |
| `market_context/market_context.sqlite3` | Saved assessments and quote provenance | DELETE |
| `real_trade_journal/real_trade_journal.sqlite3` | Independent real-trade journal | DELETE |
| `settings/settings.sqlite3` | Revisions, profiles, change history, notification/monitor configuration | DELETE |

Only paper explicitly selects WAL. Others retain their existing SQLite journal mode.
Connections are short lived and transaction based; settings uses BEGIN IMMEDIATE and
FULL synchronous writes. Paper uses 10-second SQLite waits, scanner/journal 30 seconds,
settings 10 seconds, market context SQLite's default timeout. Monitor/update,
scanner/scheduler/submission and notification advisory locks coordinate their own work;
UI settings, assessments, and journal writes do not all hold lifetime locks.

The online backup API snapshots committed SQLite content, including WAL data, without
requiring monitor/scanner shutdown. It can briefly contend with rollback-journal writers.
Each database has its own consistent snapshot, **not one simultaneous cross-database
transaction**. For an exact quiet application checkpoint, stop all writers first.
Backup attempts time out after approximately 120 seconds per database under contention.

Existing CSV/JSON files beneath `config/`, `watchlists/`, `manual_trading/`, and
`processed/` (including historical exports and legacy portfolio/open-journal state)
are included as supplemental critical files. Their inventory and hashes are compared
before/after capture; detected edits abort the whole set. Legacy nontransactional
writers must be stopped for a guaranteed coherent multi-file capture. Some old portfolio
helpers still default to checkout-relative `data_storage/processed`, regardless of
AUTOT_DATA_DIR. These paths and custom external databases/universe files must be
separately inventoried/backed up if used outside the selected root; they are not relocated
or silently merged into the runtime backup.

Excluded: `cache/` market data, `yfinance_cache/` (including cookies), `universe_cache/`,
logs, diagnostic reports, OS metadata, old `audit_checkpoint_backups/`, lock files,
and SQLite journal/WAL/SHM sidecars. The online backup merges committed database state
into standalone databases. Caches are rebuildable, although a provider may no longer
supply identical historic data. Browser session state is not persistent. Environment
secrets, code and externally managed files require a separate secured recovery plan.

### Commands

```sh
python -m autot.ops backup
python -m autot.ops backup --output /var/backups/autot
python -m autot.ops list-backups --output /var/backups/autot
python -m autot.ops verify-backup /var/backups/autot/autot-<timestamp>-<id>
python -m autot.ops restore /var/backups/autot/autot-<timestamp>-<id> --destination /var/lib/autot-restored
python -m autot.ops prune-backups --dry-run
python -m autot.ops prune-backups --keep 14 --days 30
```

`--output` selects a repository, not an individual set. The default is AUTOT_BACKUP_DIR,
or a sibling named `<data-directory-name>-backups`; never place it inside the live data
root. Use the same AUTOT_BACKUP_DIR for services and System Health. A one-off --output
is not saved as global configuration.

Sets have UTC timestamps and unique suffixes. The manifest records source root, capture
start/completion, Git commit and dirty state when available, format version, required
inventory, SHA-256 checksums, byte sizes, SQLite schema and user_version, and exclusions.
Snapshots are staged privately, verified, flushed, and renamed before being discoverable.
Errors return nonzero; a failed set is never listed as successful. A hard crash may leave
hidden `.partial-*` staging directories; inspect and remove these manually when no backup
is running. No original data is modified to repair or initialize an incomplete deployment.
A never-used store must be deliberately provisioned through its normal application flow
before the strict five-store backup succeeds; no allow-missing bypass is provided.

Verification is read-only and repeatable: manifest/inventory, hashes, required tables,
schema metadata, full SQLite integrity and foreign-key checks. Extra files, sidecars,
missing files, unsupported formats and symlinks fail. `list-backups` re-verifies each set
and reports invalid sets with nonzero status. Checksums detect damage, not malicious
rewriting of both the manifest and payload; secure the repository against unauthorized
writes. Backup sets contain private trading data and should have restricted access.

System Health reads metadata only: latest successful creation time, age, repository,
and "verified at creation; not rechecked" evidence. It warns when none exists, metadata
is invalid, or age exceeds 48 hours. Explicit verification does not rewrite the backup
or persist a fresh verification timestamp; retain its CLI/journald result for auditing.

### Restore safety and disaster-recovery order

1. Select a set and run verify-backup. Recover compatible application code/dependencies
   (use manifest commit and retain any uncommitted code separately) and environment secrets.
2. Restore to a **new, nonexistent directory**. Even an existing empty directory is
   refused. There is deliberately no --force or in-place restore implementation: UI
   writers cannot reliably be excluded by existing worker locks alone. Restore refuses
   paths overlapping current AUTOT_DATA_DIR or the source backup, as well as destinations
   with held monitor/update/notifications/scan/scheduler/submission locks.
3. Restore verifies the source, stages files, verifies the staged copy, flushes and
   publishes it, and reports every restored path. The source set is left unchanged.
   Run a restore rehearsal before relying on a backup; validate counts/history offline.
4. For actual cutover, stop the UI, paper monitor, scheduler, notification worker, manual
   scanner children and legacy scripts; prevent service restart. Keep the old data root
   intact. Update AUTOT_DATA_DIR to the restored root and ensure service ownership/access.
   Never delete lock files to bypass an active writer.
5. With the new environment, run `python -m autot.ops check` and service validation.
   Review pending/open trades, scanner runs, saved settings and journal history. Restored
   heartbeats/PIDs are historical evidence only. Provider catch-up remains subject to
   available history and existing recovery rules. No backup tool invents missing fills.
6. Start services only after review; inspect System Health and recovery logs. Delivery
   is at-least-once: restoring old outbox state may resend previously delivered messages.
   Verify the next scheduled backup and retain the previous root until recovery is accepted.

Restoring into a separate fresh directory can happen while the original services run;
the later production cutover requires the manual shutdown above. There is no process
killing, automatic environment switch, schema migration, or service activation here.

### Retention and future Linux scheduling

Retention protects the newest 14 **valid** sets **or** anything newer than 30 days by
default (union of protections). Use --keep and --days to adjust; --days 0 leaves only
the count protection. --keep must be at least 1, so the newest valid set is never pruned,
even if a newer set is corrupt. Dry-run prints candidates without deleting them. Only
recognized sets that pass full verification are eligible; invalid/unknown directories
are preserved for manual investigation. Backup creation and pruning share a repository
lock. Dry-run may create this lock/repository, but does not modify any backup set.

On the future Linux host, provision `/var/backups/autot` owned by `autot` with mode 0700,
preferably on a separate disk, and set AUTOT_BACKUP_DIR in the service environment.
Review `systemd/autot-backup.service` and `.timer`: daily 03:15 UTC plus up to five minutes
jitter, after typical US close processing, with missed runs caught up on boot. Adjust
for actual workloads; backups do not depend on a Streamlit session. No automatic pruning
is embedded in the timer: first inspect dry-run output, then add a separately reviewed
retention job if desired. Monitor journal failures, free space and backup age. Run
`systemd-analyze verify` on Linux before installing/enabling these templates.

A local backup is insufficient for host/disk loss. Copy only completed, verified sets
off-machine/offsite using a secured transfer, encrypted storage, and independent retention;
verify again after transfer and rehearse restore from that copy. Choose a shorter cadence
if losing up to a day of committed activity is unacceptable. This tooling does not
provide replication, encryption/key management, automatic offsite transfer, or a global
transaction across stores.
