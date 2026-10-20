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
eligible session starts. A trade may fill and close in the same processed bar.
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

## Future worker boundary

The intended architecture is **Streamlit UI + scheduled daily scanner + separate
5-minute paper monitor worker**. A future worker constructs `Ledger`, an injected
provider and authoritative calendar, then calls
`PaperTradingService(...).update_positions()` once per scheduled run. Keep scheduling,
deployment, credentials and alerting outside Streamlit and outside this engine.
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
