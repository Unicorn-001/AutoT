# Notifications V1

Notifications observe paper trading; they never select or confirm trades or alter execution policy.

## Architecture and installation boundary

Trade transitions and their append-only `paper_trade_events` are committed together by the existing ledger. A separate projection reads committed audit events into `notification_outbox`. Outbox inserts and the projection checkpoint commit atomically. A failed projection rolls back only notification work; the audit remains available for retry.

Ledger schema initialization creates a checkpoint at the current maximum audit event ID and update-run row ID. **Pre-installation history is excluded**, including baseline migration events. No production migration or replay is part of development/testing. On the first normal startup with this version, only new events beyond that checkpoint are eligible. An update run already present at installation is excluded from health projection.

New events are retained even while delivery is disabled. Enabling notifications later sends this post-installation backlog. Disabling pauses delivery without deleting pending records. Review the Notifications panel before enabling.

## Events

| Audit evidence | Notification |
| --- | --- |
| ENTRY_FILLED | PAPER_ENTRY_OPENED |
| TARGET_HIT (including gap targets) | PAPER_TRADE_TARGET |
| STOP_HIT (including gap stops) | PAPER_TRADE_STOP |
| MANUAL_CLOSE_EXECUTED | PAPER_TRADE_MANUAL_CLOSE |
| REVIEW_REQUIRED | PAPER_REVIEW_REQUIRED |
| Failed/partial scheduled run | PAPER_MONITOR_FAILED |
| Subsequent successful scheduled run | PAPER_MONITOR_RECOVERED |
| DATA_UNAVAILABLE in a completed run | PROVIDER_FAILURE |
| Subsequent verified bar processing without DATA_UNAVAILABLE | PROVIDER_RECOVERED |

Persistent health state suppresses repeated failures and recoveries. Provider state is scoped by provider name. No-work cycles do not prove recovery. A partial run with review warnings keeps the monitor unhealthy. Provider recovery requires actual processed bars, and provider failure requires provider audit evidence; unrelated persistence failures do not become provider failures. Interrupted scheduled runs recovered by the monitor produce monitor failure notifications. Pending creation/cancellation alerts are not included in V1.

## Persistent outbox

The paper ledger contains `notification_outbox`, `notification_checkpoint`, `notification_runs`, and `notification_health`. Outbox fields include notification ID, event type, created time, trade ID, symbol, currency, an allowlisted small JSON payload, delivery status, attempt count, last attempt, delivered time, error category, next attempt, and last failure time.

Trade notification IDs derive from the audit idempotency key. Health notification IDs derive from the run and scope. Unique primary keys prevent duplicate projection. Completed run IDs are tracked separately so a still-running earlier run is not lost when a later run finishes.

Messages include entry/exit prices and currency, quantity, stop/target, and realized P&L as applicable. Review messages point to the journal. Neither raw exceptions nor full trade/provider payloads enter notifications.

## Delivery and retries

`NotificationChannel.send(notification)` is the adapter contract. `ConsoleChannel` logs the concise message and stable notification ID at INFO level. The selected channel is CONSOLE; no network credentials are required.

A local POSIX dispatcher lock serializes delivery across processes. The monitor/worker processing boundary skips delivery when another dispatcher owns the lock. Each attempt is recorded before sending, with the SQLite transaction closed before calling the channel. Successful sends become DELIVERED and are skipped subsequently. Ordinary exceptions become FAILED_RETRYABLE with the safe category CHANNEL_FAILURE. Retry delay starts at 30 seconds, doubles, and caps at one hour. Delivery stops after 10 total attempts (including interrupted attempts), recording FAILED_FINAL with RETRY_EXHAUSTED; exhausted messages require operator review. `FinalDeliveryError` records FAILED_FINAL with PERMANENT_REJECTION and stops automatic retries. Last failure time remains available after a successful retry.

Delivery uses **at-least-once attempt semantics within the retry budget**, not guaranteed receipt or exactly-once delivery: a crash after external acceptance but before the success commit can repeat a send. Future remote adapters must pass `notification_id` as an idempotency key where supported. Console logging cannot eliminate that crash window. A send failure never updates trades or rolls back their committed transitions.

## Settings, CLI, and monitor

Settings → Notifications exposes:

- `notifications_enabled`: false by default.
- `notification_channel`: CONSOLE.

Existing signed settings revisions load with notifications disabled, without rewriting history or changing strategy profile hashes.

```sh
python -m autot.notifications --once
python -m autot.notifications
```

`--once` projects and delivers up to 100 eligible messages. Continuous mode repeats every 30 seconds; Ctrl-C exits. Disabled startup exits without initializing the ledger. Use `AUTOT_DATA_DIR` to select isolated data when testing.

`python -m autot.paper_monitor` and `--once` retain their existing operation. After each scheduled update, including an update that raises after recording a failed run, the monitor projects and delivers outside the trade update transaction/lock. Notification exceptions are caught at this boundary and logged with a fixed safe message. Projection can run while delivery is disabled. The standalone worker also picks up manual UI lifecycle events; without a worker these are picked up by the next monitor cycle. The UI does not launch workers or send messages.

The paper dashboard's Notifications panel shows enabled/disabled, channel, pending count (including retryable), last delivery, last failure, and up to 50 recent notifications. Status reads do not migrate or create a database.

## Future adapters

Email, Telegram, and push/webhook implementations can implement `NotificationChannel` and be selected through a future validated channel factory. They should use bounded timeouts, externally supplied secrets, remote idempotency where supported, and classify permanent versus retryable failures. No credentials or placeholder network sends are included in V1. Multiple-channel fan-out would require per-channel delivery state before enabling it.

## Verification

All tests inherit isolated `AUTOT_DATA_DIR` fixtures. Notification tests cover lifecycle mapping, health recovery, idempotent projection, retry, dispatcher serialization, console output, transaction isolation, legacy installation boundaries, disabled startup, and signed-settings compatibility. Existing paper-monitor, strategy-analysis, portfolio-risk, and full-suite tests remain applicable. Do not run test commands or CLI probes against live paper data.
