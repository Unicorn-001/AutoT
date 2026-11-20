# Prospective Paper Trading V1

This workflow consumes qualified AutoT daily opportunities and records forward
simulations. It does not connect a broker, execute real trades, train strategies,
or change scanner formulas, scores, rankings, benchmarks or download workers.

## Audit and reuse

The existing CLI chain is `trading.PaperTrader -> PaperBroker -> PaperExecution ->
PaperPortfolio`. It opens BUY positions immediately at a supplied price, closes
whole long positions, and saves JSON portfolio/open-journal state plus CSV trade
journals under the legacy working-directory-relative `data_storage/processed`.
It lacks pending orders, shorts, market currencies and intraday catch-up.
`broker/alpaca_client.py` and `paper_trade/paper_trader.py` were empty placeholders.
There was no `utils/financial_validation.py` at checkpoint `958916a`.

The share-based `PositionSizeCalculator` is reused directly. The older
`risk.position_sizing` returns monetary allocation from percentage stop distance;
it is not a second share-sizing implementation for this workflow. Existing
`calculate_risk_reward_ratio` validates directional stop/target geometry; the
original scanner ratio is preserved. Long/short P&L now has one shared helper,
also called by the legacy portfolio, trader and journal. Their long P&L formula
and external behavior are unchanged. Legacy files are not migrated or merged.

## State, snapshots and storage

`PENDING_ENTRY -> OPEN -> CLOSED`, or `PENDING_ENTRY -> CANCELLED` before its
eligible session starts or when the fill-time risk check rejects entry. A trade may
fill and close in the same processed bar.
`review_required` is a flag, not another lifecycle state.

`AUTOT_DATA_DIR/paper_trading/ledger.sqlite3` persists independently of browsers,
Streamlit reruns and restarts. Keep the data root on persistent local disk for
computer restarts; ephemeral hosting storage cannot provide that guarantee.
Confirmation uses a versioned canonical identity: normalized scanner symbol, market,
index name, side, UTC signal timestamp and signal timeframe. Source download and
benchmark metadata are excluded so refreshing universe metadata cannot bypass
protection. Prices, sizing, creation time and execution state are not identity.
SQLite uniquely indexes `(opportunity_id, intent_key)`. Ordinary confirmations
reuse an existing pending/open trade, or preserved terminal history if none is
active. Reopening even a closed/cancelled signal requires explicit consent.
**Create another paper trade** opens a separate review with an additional intent;
its confirmation key is retained across submissions. Ordinary selection, refresh,
rerun and restart never grant that override. The original unique confirmation key
also protects retries of an explicit addition.

Lookup, available-capital validation and insertion run under `BEGIN IMMEDIATE`.
Reservations are derived from committed pending/open rows, so reuse does not
reserve again and a failed insert cannot leave a reservation. This applies across
independent ledger connections/processes on the same SQLite database.

On first use, existing snapshots receive identities in a transactional migration.
The first row for each signal gets the default intent; any pre-existing duplicate
gets a `legacy:<trade_id>` intent and an operator-log warning. No snapshot, state,
confirmation key, reservation or historical record is deleted or changed by the
migration. Default confirmation checks all intents for that signal before creating
anything. Existing duplicate reservations remain until manually resolved.
Revision checks stop overlapping workers or manual actions overwriting each other.
No network request runs inside the ledger's write transaction.

Each record stores a separately immutable signal snapshot and mutable execution
state. The snapshot includes identity, created/signal times, source/benchmark
metadata, original opportunity, market/index, currency, side, reference price,
stop, target, ratio, confidence, agreement, regime, historical score, trade quality,
sizing inputs, quantity, intended value and eligibility time. Monitoring never
recalculates these fields. Fill, mark, exit, P&L, watermark, ambiguity and review
fields are separate. Decimal values are persisted as text without float round trips.

Web-side observation records the date of the actual final scanner input candle.
It does not replace, filter or mutate scanner input or output. Paper confirmation
requires `1d` and a candle already complete at scan observation time. A scan using
an incomplete daily candle remains viewable but cannot create a paper trade;
rerun after the session closes. Existing browser scans without provenance must
also be rerun. This rule applies to the paper boundary, not scanner behavior.

## Sizing and currency

The UI exposes account capital, risk percent, reference price, stop distance,
calculated whole-share quantity, risk budget and estimated value. It calls the
existing calculator: the lesser of risk-budget/absolute-stop-distance quantity
and capital/reference-price quantity, rounded down to whole shares. No new sizing
formula is introduced. Calculate quantity before confirming; changed inputs
require a new preview. Quantity stays fixed after confirmation.

Accounts are separated into US/USD, UK/GBP and India/INR. The first confirmation
sets that currency's capital; subsequent confirmations use it. Pending entries
reserve intended notional; open positions reserve filled notional. SELL positions
reserve full notional as collateral, without crediting imaginary short proceeds.
Available capital is initial capital plus realized P&L minus these reservations;
unrealized P&L is shown separately. No mixed total or FX conversion exists.
An unaffordable gap fill leaves the trade pending and flagged for review.
Sizing risk is an estimate at the signal price, not a guarantee after a gap.

Yahoo London quotes commonly use GBp/GBX (pence). The UK review requires verifying
the scanner quote unit (GBp or GBP). Pence reference/stop/target and intraday prices
are converted to GBP by multiplying by 0.01; the original opportunity is retained
unchanged. Provider quote currency must match the confirmed scale before execution.
Other quotation currencies are blocked rather than converted implicitly.

This is a forward-testing ledger, not a full brokerage account model. It does not
model commissions, spreads, slippage, borrow availability/fees, interest, margin
calls or settlement. Aggregate legacy CLI daily-loss/position-count limits are not
automatically applied to this separate ledger. It enforces finite positive sizing,
directional price geometry and per-currency capital reservations. P&L is gross
simulated P&L and can differ substantially from real trading.

## Entry and exit rules

Confirmation never fills at the daily reference price. The eligible session is
the first session whose opening is strictly after confirmation and signal close.
A confirmation during a session waits for the next session; before opening it
may use that day's upcoming session. Completed 5-minute bars only are processed.
The opening bar must be present to establish a safe starting point; missing opening
history does not authorize using an arbitrary later bar as the entry.

Fill at the first eligible bar's OPEN. Record that bar's start time as `filled_at`.
Stop and target levels are the original snapshot levels. Evaluate every bar in
timestamp order, including the entry bar:

1. A gap at OPEN through the stop exits at OPEN, never the unreachable stop level.
2. A gap at OPEN through the target also exits at OPEN, an observed execution price.
3. A previously requested manual close executes at the first subsequent bar OPEN
   at or after the request time (unless a gap stop/target applies at that open).
4. Otherwise BUY stops use LOW <= stop and targets HIGH >= target. SELL stops use
   HIGH >= stop and targets LOW <= target. Touches fill at the level.
5. If both levels are touched within one bar and the open did not establish the
   sequence, STOP wins. Persist `intrabar_sequence_ambiguous=True` and its reason.

If entry itself gaps beyond a level, fill and exit at that same open. No fictional
gain from the prior close or target is credited. Exact intrabar event times are
unknown: `closed_at` records the containing bar's start, not a claimed tick time.
BUY P&L is `(mark or exit - fill) * quantity`; SELL reverses the price difference.
Both unrealized and realized calculations use fill, never reference price.

Manual close is a request, not a fabricated fill at a stale price. Catch-up events
before the request still take precedence. Cancellation is allowed before the
eligible session starts; afterward update first so cancellation cannot erase a
historical fill that has not yet been processed.

## Sessions and catch-up

The replaceable `SessionCalendar` contains local regular weekday sessions using
IANA timezones: US `America/New_York`, UK `Europe/London`, India `Asia/Kolkata`.
Regular session references: [NYSE](https://www.nyse.com/trade/trading-information),
[LSE](https://www.londonstockexchange.com/personal-investing/faqs),
[NSE](https://www.nseindia.com/resources/exchange-communication-holidays).
All persisted execution times are timezone-aware UTC; local hours handle DST.

**The default helper is not a complete exchange calendar.** Holidays, special
sessions and early closes are not bundled. Inject an authoritative replacement
before unattended operation. Tests and operator integrations can supply explicit
`{(market, date): None}` holiday overrides or `(local_open, local_close)` pairs.
The browser uses the conservative default. Missing slots, including holidays or
halts, flag review and stop at the last verified bar; it never infers that a
missing weekday was a holiday. Review currently means inspect data/calendar and
retry with a corrected provider/calendar; the UI cannot override historical fills.

`last_checked_at` is the last processed bar START, not the last poll time. Updates
request from that timestamp plus five minutes (or eligibility for pending trades).
Bars are sorted logically against the expected session slots; only a contiguous
prefix is consumed. A missing middle bar prevents later exits being guessed.
Completed progress is persisted, and later updates can recover if the missing
data becomes available. Incomplete current bars are never consumed. Closed and
cancelled trades are not fetched again. Updates are safe to repeat after restart.

The injected `IntradayProvider.get_intraday_bars(symbol, start, end, interval="5m")`
returns bars, quote units and source metadata. The free Yahoo implementation uses
the public chart endpoint via Requests independently of scanner yfinance workers.
It does not access a broker or alter yfinance singleton state. It keeps certificate
verification and operator trust settings. Yahoo is not a guaranteed data contract.
The adapter refuses starts older than 59 days, a conservative bound against the
[documented 60-day intraday constraint in yfinance](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py).
Even newer data can be missing, delayed or blocked; HTTP success is not coverage.
Malformed bars, quote-unit mismatches and corporate actions returned in the window
require review. Automatic split/dividend accounting is not implemented.

## Running and manual checks

From the repository, with its environment activated:

```sh
python -m streamlit run web_app.py
```

AutoT does not start a server or background loop on import. Use persistent
`AUTOT_DATA_DIR` if its default application-local `data_storage` is unsuitable.

For each of A/B/C below:

1. In **Scanner**, choose **Market Index**, the market and index shown below.
   Use **5y / 1d**, then **Run Scan** after the market's daily candle has completed.
2. In **Paper trade a daily opportunity**, click **Paper Trade · SYMBOL** on a
   qualified BUY/SELL. If no opportunity exists, wait for a later scan or use
   another supported index; do not manufacture a signal. Disabled actions mean
   completed daily provenance is missing; rerun after close.
3. Review the immutable signal fields. Enter account capital in that market's
   account currency and risk %. Verify the quote unit and tick the acknowledgement.
   Click **Calculate quantity**, inspect quantity/value/risk, then **Confirm Paper
   Trade**. Check **Status: PENDING ENTRY**, with no fill or fill time.
4. Select **Paper Trading** in Workspace. The pending record survives refreshing
   the browser and restarting AutoT. Accounts and P&L are grouped by currency.
5. Once the next eligible session's first 5-minute bar has completed and Yahoo has
   published it, click **Update Paper Positions**. It fetches only pending/open
   trades and processes available history once. No timer is running in the UI.
6. Inspect OPEN fill, mark, last checked and P&L, or CLOSED exit/reason if a level
   was already crossed. Inspect **Snapshot / actions** for original fields, review
   and ambiguity flags. A missing-data warning is not a successful execution.
7. Leave AutoT stopped during part of a normal session, restart, then update again.
   Available contiguous bars catch up chronologically. Update again without new
   bars to confirm no duplicate fill. To close manually, choose **Request Manual
   Close**, then update after the next completed bar. To deliberately create
   another trade from the same signal, reopen its opportunity and use
   **Create another paper trade**, then calculate and confirm the separate review.

| Check | Market / example index | Currency and quote check |
| --- | --- | --- |
| A: US | United States / Nasdaq-100 | USD, USD quotes |
| B: UK | United Kingdom / FTSE 250 | GBP account; verify GBp versus GBP quotes |
| C: India | India / NIFTY 50 or NIFTY 500 | INR, INR quotes; `.NS` symbols including ampersands |

Regular weekday openings used by the helper are US 09:30 New York, UK 08:00 London,
India 09:15 Kolkata. Do not interpret a weekend/holiday update as a promise of bars.
All automated tests use offline fixtures; successful tests do not establish live
Yahoo availability or verify a real next-session fill.

## Worker boundary

The architecture is **Streamlit UI + separate paper monitor process**.
`python -m autot.paper_monitor` constructs `Ledger` and the existing provider/calendar,
then calls `PaperTradingService(...).update_positions()` per scheduled run.
Automatic daily scanning and an authoritative holiday calendar remain future work.
Scheduling, deployment, credentials and alerting stay outside Streamlit.
No strategy learning or optimization uses the results yet.

## Manual MPC duplicate correction

The read-only inspection on 2026-10-17 found two pending MPC BUY trades for the
2026-10-16 20:00 UTC daily S&P 500 signal, each with quantity 10 and reserved
USD 4780.70007324218750. Both are eligible at 2026-10-19 13:30 UTC:

- Keep `294d7e3c-c169-4a21-8885-a58e6aaf7826` (created 16:24:56 UTC).
- Cancel only `27eebe40-65b9-4de6-9546-c1d7e906d15c` (created 16:25:33 UTC).

Before the eligible session, back up the ledger with SQLite's backup facility
(or stop all app/worker connections before copying the database). In the fixed
app's **Paper Trading → Pending Entries**, expand **Snapshot / actions** for the
second exact ID, verify it is still pending with no fill, and choose **Cancel
pending entry** once. Keep the cancelled record as audit history. With no other
activity, reserved USD becomes 4780.70007324218750 and available USD becomes
5219.29992675781250; there is one pending and one cancelled MPC record. Reopening
the same scanner opportunity must reuse the retained pending record.

If the eligible session has already started, normal cancellation is intentionally
blocked. Update positions first and inspect their actual states; if the duplicate
has filled, request manual close on that exact duplicate and process the next
completed bar. Do not backdate a cancellation, alter execution prices, or delete
rows to hide a fill. This may produce realized P&L rather than the pre-entry
balances above. No correction was applied automatically during this fix.

## Paper Trading Audit & Performance V1

### Architecture and migration

The audit extension adds `paper_trade_events` and `paper_update_runs` alongside
`accounts` and `trades`. It does not change the signal, sizing, calendar, entry,
stop/target, ambiguity, gap, or manual-close execution rules. The journal and
performance service are read-only projections of stored trades and audit evidence.
No backtest results are mixed with this prospective journal.

**Pre-audit trades receive a baseline snapshot only. AutoT does not fabricate historical lifecycle events.**

At the next ledger initialization, an immediate SQLite transaction creates the
new tables, indexes and append-only triggers. Every existing trade without audit
history receives exactly one `AUDIT_BASELINE_CREATED` event containing its complete
persisted snapshot/state/identity/revision. Both event and recording timestamps
are the actual migration time, not the historical fill/exit time. The baseline
has no fabricated bar data. Existing account/trade rows, IDs, snapshots, prices,
P&L, reservations and revisions remain unchanged. There are no destructive table
rebuilds. Initialization is repeatable and serialized across connections; failed
migration rolls back its DDL and baseline inserts together.

New confirmations receive `TRADE_CREATED`, never a baseline. Updates/deletes of
events are rejected by SQLite triggers; foreign keys protect their trade/run
references on application connections. Append-only protection is an application
integrity measure, not cryptographic tamper-proofing against a database owner.
Back up the database with SQLite's backup API before first use. Do not delete or
reset the existing ledger. An SQLite backup includes committed WAL contents;
copying only the main file while the app is running may not.

### Event semantics and transactions

Controlled event types are:

- `AUDIT_BASELINE_CREATED`: current persisted state observed during migration.
- `TRADE_CREATED`, `TRADE_CANCELLED`: genuine confirmation/cancellation operations.
- `ENTRY_ELIGIBLE`: the eligible session encountered during a monitor pass.
- `ENTRY_BAR_PROCESSED`, `ENTRY_FILLED`: verified opening bar and its entry fill.
- `POSITION_CHECKED`, `POSITION_UPDATED`: each completed, contiguous processed
  bar and the resulting still-open mark. A closed bar has a check and closure
  events instead of an open-position update.
- `STOP_HIT`, `TARGET_HIT`, `TRADE_CLOSED`: the actual exit reason and closure;
  gap reasons remain `GAP_STOP`/`GAP_TARGET` and retain the observed open price.
- `MANUAL_CLOSE_REQUESTED`, `MANUAL_CLOSE_EXECUTED`: separate request and fill.
- `REVIEW_REQUIRED`: a new review condition or changed review reason.
- `DATA_UNAVAILABLE`: provider/verification failure at a required history start.
- `MISSING_EXPECTED_BAR`: an expected completed slot absent from supplied history.

Bar OHLC audit columns are Decimal text in account quote units (GBP, not GBp).
The trade's original quote units/scale remain in its immutable snapshot. Each
bar event carries the evaluated state as payload, including any ambiguity flag.
`event_time` is the logical operation time or bar start; `recorded_at` is actual
UTC persistence time. A baseline's logical time is its recording time because no
historical audit observation exists. Intrabar event times remain unknown.

Event idempotency keys are SHA-256 hashes of deterministic trade ID, event type,
and semantic identity: bar timestamp for bar events, eligibility time for
eligibility, expected history slot for missing/unavailable data, or committed
revision for non-bar state transitions. Baselines use a fixed per-trade identity.
A unique constraint enforces these keys. Repeated missing/data failures at the
same required slot are recorded once in the timeline; every retry still has its
own update-run record. A repeated unchanged review does not create another
review event. Streamlit rendering and journal reads create no monitor events.

Evaluation collects events without writing. The ledger's existing immediate
transaction checks capital and optimistic revision, updates state and inserts
all corresponding events before committing. A failed event insert rolls back
the trade update; a rejected state update cannot leave a phantom fill/exit event.
A catch-up pass may record pending → open → closed within a single revision pair.
Each event retains its intermediate status transition. The persistence boundary
also enforces required fill, close, cancellation and manual-request events.
Conflicting workers cannot append events for a rejected revision. Network calls
remain outside write transactions.

### Update runs

Every explicit **Update Paper Positions** operation first commits a unique
`RUNNING` record with trigger `MANUAL` and provider class. Even an empty/no-due
pass has a run. Rendering, refreshes and navigation do not initiate runs.
Successfully persisted bar events reference their run ID. At completion the run
records considered/changed/opened/closed trades, committed bars, warnings, errors,
completion time and a small summary with concurrent conflicts and abort status.
An entry that fills and closes in one pass counts as both opened and closed.
`trades_updated` counts changed execution/review fields, not revision-only writes.
Warnings count affected trade checks; errors count failed operations, including a
failure to persist a recovery/review state. No-due checks of trades already under
review remain warnings.

- `SUCCESS`: completed without errors or warnings, including a clean no-op pass.
- `PARTIAL`: review/missing-data/concurrency warnings, or an error after some bars
  were committed.
- `FAILED`: an error/abort with no committed bars.
- `RUNNING`: not finalized; a hard process kill or storage failure may leave it
  here. It is never silently labelled successful on restart.

Counters are finalized at normal/exceptional completion. After a hard kill,
a RUNNING record's counters may be incomplete; committed events remain the durable
operation evidence. Runs are separate from per-trade transactions, so a later
trade's failure does not erase earlier successful updates. Scheduler V1 adds an
external worker; see PAPER_MONITOR.md. Abandoned scheduled runs are explicitly
marked FAILED at restart. Empty active-trade sets now record NO_WORK.

### Performance and journal

The dashboard retains its summary-first layout. Enable **Show Performance /
Journal** to see separate USD/GBP/INR summaries, journal rows, a selectable trade's
event timeline, separate raw trade/audit JSON and the latest 50 update runs.
Existing details/actions and raw snapshots remain available.

Closed-trade summaries include completed trades, winners/losers/breakeven, win
rate, gross profit, negative gross loss, net realized P&L, average positive win,
average negative loss, profit factor, average trade return, best/worst trade by
realized P&L, mean holding duration, mean signal/actual-fill R:R and mean entry
slippage. Breakevens are included in the win-rate denominator. Returns are
unweighted trade returns using actual entry notional. Profit factor is gross
profit divided by absolute gross loss; without losses it is shown unavailable
with an explanation, not a fabricated finite value. Empty averages are unavailable.
Best/worst retain trade IDs (ties use journal order). Cancelled and pending trades
appear in the journal but are excluded from completed-trade statistics.

Signal R:R is the original stored ratio; actual R:R uses the directional distance
from fill to original stop/target. Invalid/nonpositive risk or negative reward
makes actual R:R unavailable. Neither ratio changes execution. Entry slippage is
`(fill - signal) / signal × 100` for BUY and `(signal - fill) / signal × 100`
for SELL: positive means adverse. Holding duration is exit bar-start minus fill
bar-start; it is not tick-accurate and a same-bar close has duration zero.
Decimal values are retained internally with no cent-rounding before aggregation;
only presentation rounds. Currency groups are never combined or FX-converted.

The UI explicitly states **Small sample — insufficient for strategy conclusions.**
These descriptive gross simulated statistics are not evidence of statistical
significance and do not include transaction costs or validate strategy quality.

### MFE / MAE evidence and limitations

Excursions require a genuine durable `ENTRY_FILLED` and `POSITION_CHECKED` bar
history covering the recorded position through its last watermark. Existing
closed pre-audit trades show **Unavailable for pre-audit trade**. The service
never downloads historical bars or infers excursions from a baseline. A pending
pre-audit trade can acquire genuine evidence when it later fills under audit;
an already-open pre-audit trade lacks complete entry-to-current evidence.

For a BUY, MFE is the greatest known rise above fill and MAE the greatest known
fall below fill; SELL reverses the direction. Both are nonnegative absolute
price movements per share in account currency, plus movement/fill × 100. They
are not quantity-multiplied P&L. Bars held through their close contribute high/low.
An exit-at-open contributes only that open. For stop/target intrabar exits,
only the open and executed level are provably observed while in the position;
the rest of the exit bar could occur after closure. Those excursions are labelled
**known movement lower bounds; exit-bar order unknown**. This avoids inventing
post-exit opportunity or adverse movement from full exit-bar extremes. Tick-level
exact excursions cannot be recovered from 5-minute OHLC alone. Pending trades
without bars show unavailable; completed evidence with no movement can be zero.

### Verify the existing forward ledger after first audit initialization

Use **Paper Trading → Show Performance / Journal** after starting the app yourself.
Check MRNA remains TARGET +$208.13, MPC remains STOP -$94.91, and USD net P&L is
+$113.21 (the unrounded sum is 113.21465209960962). The cancelled duplicate remains
cancelled. There should still be no open positions or reserved capital. The
initial capital metric is $10,000; available capital with these closed trades is
$10,113.21. Independently inspect IDs and event counts with read-only SQLite:

```sql
SELECT trade_id, json_extract(snapshot, '$.symbol') AS symbol,
       json_extract(state, '$.status') AS status,
       json_extract(state, '$.realized_pnl') AS realized_pnl
FROM trades ORDER BY rowid;

SELECT trade_id, event_type, COUNT(*) AS count
FROM paper_trade_events GROUP BY trade_id, event_type ORDER BY trade_id, event_type;

PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

Expected IDs:

- MPC closed: `294d7e3c-c169-4a21-8885-a58e6aaf7826`
- MPC cancelled: `27eebe40-65b9-4de6-9546-c1d7e906d15c`
- MRNA closed: `7ed3627b-568f-46fc-8c29-59a46ed03a7c`

Each of these three terminal trades must have exactly one
`AUDIT_BASELINE_CREATED` and no historical entry/stop/target/close events. Select
each timeline, refresh/restart, and confirm the baseline count remains one.

## Settings V1 and configuration provenance

See [SETTINGS.md](SETTINGS.md) for the centralized settings store, immutable profile
versions and full operator workflow. New prospective trades retain the settings
revision, profile ID/name/version, configuration hash, mode and validated trading
configuration captured by their scan. A later Save or Activate cannot rewrite those
snapshots. The actual sizing risk remains recorded explicitly. Existing trades are
labeled `PRE_SETTINGS_BASELINE` only when read; no detailed history is fabricated,
and their IDs, balances, P&L and audit events are unchanged.

USD/GBP/INR settings capital is a default for **new accounts only**. Existing account
capital is read from the ledger and never reset by Settings. Position/count/
portfolio-risk/daily-creation limits are opt-in and checked atomically at creation.
Reservations, position count and planned risk include pending exposures across
both modes within each currency account. Portfolio Risk V1 daily counts are per
mode and market-local date, including cancelled confirmations.
Gap fills retain the existing strict available-capital check and execution rules.

`RESEARCH` has separate signal identity and performance reporting, while sharing
strict account capital reservations. It receives no additional capital. Default
forward performance excludes research, retaining historical pre-settings trades
without inventing a mode. Journal filters/grouping support profile/version/hash,
mode, market/index, side and regime; unavailable historical values stay unknown.

After saving settings, run a fresh scan to use the new profile. In Paper Trading,
inspect the raw trade snapshot to verify `configuration_source`, `settings_version`,
`strategy_profile_id`, `strategy_profile_name`, `strategy_profile_version`,
`strategy_config_hash`, `mode`, `trading_settings` and `execution_risk_percent`.
News settings and daily scanning remain placeholders. Monitoring can now be
enabled for the external Paper Monitor; manual updates remain available, with
unchanged execution semantics. Monitoring is OFF by default.


## Portfolio Risk Engine V1

See [PORTFOLIO_RISK.md](PORTFOLIO_RISK.md). Calculate quantity now shows a typed
ALLOW/REJECT admission preview with explicit reasons and portfolio totals. It does
not reserve funds. Confirm Paper Trade repeats the evaluation inside the serialized
ledger transaction and rejects without creating an account, trade, trade event or
reservation when any enforced limit fails. Accepted Settings-based trades retain
the decision and configuration metadata in their immutable signal snapshot.
Rejected confirmations append a separate durable risk audit, reviewable under
Rejected paper confirmations. A rejected preview disables Confirm Paper Trade.
Journal rows include planned admission metrics; legacy rows are labeled
PRE_PORTFOLIO_RISK at read time.

Paper Trading shows per-currency Portfolio Risk / Exposure alongside the existing
accounts and positions: realized equity, available funds, reserved notional,
pending/open counts, planned risk, configured risk ceiling, fill-adjusted stop risk,
largest position, remaining slots, and the active mode's daily admission count.
Limits marked “not enforced” do not restrict admission. Percentage limits retain
the existing base-capital basis; displayed equity includes realized P&L only.
Exposure across research and forward positions remains shared; performance views
retain their existing mode separation. Neither previews nor this view updates
prices, executes trades, or rewrites historical records.

## Strategy Analysis V1

Paper Trading now has a separate **Show Strategy Analysis** area with closed-trade
outcomes, strategy alignment, pairs/triples, regime and BUY/SELL comparisons,
score/risk bands, profile comparison, completeness, observations and CSV exports.
New scan opportunities retain a typed snapshot of all available strategy votes
and their actual weights; confirmations persist it without recalculating signals.
Existing trades are not rewritten. Journal selections now show strategy evidence,
profile metadata, admission, fills and excursion coverage together.

The new analysis defaults to explicit `FORWARD_TEST` records. `RESEARCH` and
`UNKNOWN_LEGACY` are separate selections; unlike the older Performance journal,
unknown historical modes are excluded from forward statistics. All monetary
summaries remain currency-separated. MFE/MAE require durable bar evidence;
realized-close drawdown is not mark-to-market equity drawdown. Observations never
change settings. Experiment ideas can be exported as DRAFT JSON, without creating
or activating profiles. See [STRATEGY_ANALYSIS.md](STRATEGY_ANALYSIS.md) for metrics,
legacy limitations, sample warnings and manual review instructions.

## Automatic Paper Monitor V1

See [PAPER_MONITOR.md](PAPER_MONITOR.md) for the external CLI, configuration,
locking, status and recovery details. `python -m autot.paper_monitor` calls the
same `PaperTradingService.update_positions()` implementation as **Update Paper
Positions**. Both paths serialize using a process-safe update lock and preserve
existing SQLite transactions, capital checks and audit idempotency. Monitoring
is OFF by default and never scans or confirms new trades. The UI only shows
status and external startup commands; browser lifetime does not control monitoring.

Run history now distinguishes MANUAL and SCHEDULED and records NO_WORK when no
pending/open trades exist. Existing trade snapshots, fills, stops, targets and
historical audit records are preserved. Execution remains completed 5m bars,
NEXT_SESSION_OPEN and STOP_FIRST, with the existing weekday-calendar limitations.

Future **FILL-TIME RISK RECHECK**: next-session gaps can materially change actual
stop risk versus planned risk. A future version may recompute risk at fill and
optionally reduce size/reject entry. Scheduler V1 does not change sizing or
forward-test execution rules.

## Fill-Time Risk Recheck V1

Execution is now `confirmation -> NEXT_SESSION_OPEN price -> risk recheck ->
ACCEPT / RESIZE / REJECT -> open only if approved`. Scanner and signal calculations,
fill model, original stop and target are unchanged. Already filled historical trades
are never rechecked or recalculated.

The check runs in the ledger's `BEGIN IMMEDIATE` transaction, after fetching bars
and before opening or calculating P&L. It uses the existing currency account's base
capital and the trade's captured risk settings (including the configured 0.5% where
applicable), not today's potentially different active profile. Pre-settings pending
records use their stored risk percentage. There is no new capital model.

- BUY risk/share: `fill - original_stop`; planned risk/share: `reference - original_stop`.
- SELL risk/share: `original_stop - fill`; planned risk/share: `original_stop - reference`.
- Planned total risk: `planned_risk_per_share * planned_quantity`.
- Unadjusted actual risk: `actual_risk_per_share * planned_quantity`.
- Allowance: `account_base_capital * captured_risk_percent / 100`.
- Approved quantity: `min(planned_quantity, floor(allowance / actual_risk_per_share))`.
- Approved risk: `actual_risk_per_share * approved_quantity`.

All calculations use Decimal, with no added risk tolerance or rounding-up allowance.
Favorable gaps never increase quantity. Invalid/missing/non-finite prices, an invalid
quantity, nonpositive directional stop risk, or inability to afford one risk-valid
share reject the entry. Existing enabled position-count, position-notional, portfolio
risk and daily admission limits are also enforced. Portfolio risk uses actual fill
risk for existing open trades and reference risk for pending trades. The candidate
is excluded from counts to avoid counting its reservation twice. Daily limits retain
the existing confirmation-day, market-local, mode-specific semantics; filling a
previously confirmed trade does not consume a second daily admission. Full notional
must fit available capital after releasing the candidate's original reservation.
Portfolio/capital failures reject; V1 only resizes to the per-trade risk allowance.

The new optional `state.fill_time_risk_check` JSON object stores the reference,
planned quantity/risk, executable price/risk, approved quantity/risk, allowance,
decision/reason, fill time and wall-clock recheck time. No SQL table migration or
historical backfill is needed: old rows read with a null check. The immutable snapshot
retains planned quantity; decoded trade quantity is approved quantity after execution,
so reservation, P&L and later exits use the approved size. Existing append-only fill
or cancellation events retain the decision payload in the same transaction.

Rejections use `CANCELLED` with `FILL_TIME_REJECTED: <reason>`, no fill or P&L, and no
remaining reservation. They are not losses. Paper Trading details show a **Fill-Time
Risk Check** table, and history retains the reason. The existing notification outbox
projects RESIZE/REJECT notices once per trade; delivery uses existing notification
settings and workers. No new notification service is required.

### Controlled manual validation (isolated ledger)

From the repository root, run these commands in a fresh terminal. This creates only
a temporary test account and uses supplied bars, without reading or changing the
operator's historical ledger. The fixture helpers supply a qualified BUY reference
100, stop 95, target 110, USD capital 10,000 and a fixed clock.

```sh
export AUTOT_DATA_DIR="$(mktemp -d /private/tmp/autot-fill-check.XXXXXX)"
venv/bin/python - <<'PY'
import json
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.service import PaperTradingService
from autot.settings.store import SettingsStore
from tests.test_settings import changed
from tests.test_settings_paper import create
from tests.test_prospective_paper import CREATED, OPEN, BAR, Provider, bar

store = SettingsStore()
state = store.save(changed(risk={'risk_per_trade_percent': .5}), expected_version=0)
ledger = Ledger()
provider = Provider()
clock = [CREATED]
service = PaperTradingService(ledger, provider, clock=lambda: clock[0])
for key, symbol, opening in [('resize', 'AAPL', 102), ('reject', 'MSFT', 95)]:
    clock[0] = CREATED
    trade = create(service, state, key=key, symbol=symbol)
    provider.bars = [bar(opening, opening, opening, opening)]
    clock[0] = OPEN + BAR
    service.update_positions()
    saved = Ledger(ledger.path).get(trade['trade_id'])
    print(key, saved['status'], json.dumps(saved['fill_time_risk_check'], indent=2))
print('Account:', ledger.summaries()['USD'])
print('Temporary ledger:', ledger.path)
PY
venv/bin/streamlit run web_app.py
```

1. Check `resize`: OPEN, planned 10 shares/$50 risk, fill 102, actual risk/share 7,
   unadjusted risk $70, approved 7 shares/$49 risk; stop 95 and target 110 unchanged.
2. Check `reject`: CANCELLED, `INVALID_STOP_RELATIVE_TO_FILL`, approved quantity/risk
   zero, no fill/P&L. Account reservation is $714 from AAPL only; available is $9,286.
3. In the temporary UI choose **Paper Trading**, expand AAPL and MSFT details and
   inspect the nine Fill-Time Risk Check fields. Inspect Performance / Journal:
   MSFT is cancelled, not a losing completed trade. Do not request live market updates
   for these synthetic bars.
4. Restart Streamlit with the same `AUTOT_DATA_DIR`; values and audit should persist.
   Stop it and close this terminal when finished to discard the environment override.

Automated equivalents: `venv/bin/python -m pytest tests/test_fill_time_risk.py -q`.
