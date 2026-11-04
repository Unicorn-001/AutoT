# Portfolio Risk Engine V1

Portfolio Risk evaluates **new paper-trade admission** after scanner opportunity
generation and before confirmation. It returns a validated `PortfolioRiskDecision`
with `ALLOW` or `REJECT`, all rejection reasons, warnings, Decimal amounts,
counts, effective risk settings and captured settings/profile metadata.
It never reduces quantity or changes strategies, indicators, signals, confidence,
agreement, regime, scores, rankings, stops, targets or execution rules.

## Integration and persistence

- `autot/portfolio_risk/models.py` defines validated ledger views, account input,
  exposure summaries and admission decisions. Monetary arithmetic uses Decimal;
  JSON serialization preserves decimal strings.
- `autot/portfolio_risk/engine.py` evaluates supplied snapshots without I/O.
- `PaperTradingService.preview_admission(opportunity, settings_state=..., **context)`
  uses the existing snapshot builder and sizing engine, then a consistent read
  transaction. It creates no account, reservation, trade or audit event.
- `PaperTradingService.confirm(...)` retains existing confirmation-key and
  opportunity identity deduplication. It checks new exposures again under
  `Ledger.confirm`'s `BEGIN IMMEDIATE` transaction, including account creation,
  risk evaluation, reservation and creation audit event in the same transaction.
  A stale ALLOW preview is never permission to bypass current limits.
- Rejections raise `PortfolioRiskRejected`, a `ValueError` subclass with the typed
  decision in `.result`. All policy failures are returned together. Malformed
  inputs or corrupt settings/hash metadata raise validation errors before admission.
- Accepted new Settings-based trades store `portfolio_risk_decision` in their
  original snapshot. Settings/profile activation and execution updates cannot
  alter that decision through the application. Rejected confirmations append to
  `paper_trade_rejections` (UUID, recording time, confirmation key, full proposed
  snapshot, typed decision including reasons, portfolio and settings metadata).
  A savepoint rolls back any tentative account creation; the rejection commits
  under the same write lock before `PortfolioRiskRejected` is raised. Audit-write
  failure fails the request and rolls back everything. Each attempted confirmation
  is recorded, including retries; previews are read-only and are not recorded.
  The additive table is created on ledger initialization without updating old
  trades or trade events. Rejections never enter performance calculations.
- `Ledger.portfolio_exposures(settings_state, when=...)` returns typed summaries
  from one read transaction for existing USD, GBP and INR accounts. Dashboard
  limits describe the active profile; a delayed scan uses its own captured profile
  when confirmed. New-account capital remains a Settings default only.

## Capital basis and modes

Each currency is independent. No currency conversion, leverage, short proceeds,
extra research capital or mixed-currency total is introduced.

```
realized equity = base capital + realized P&L
available capital = realized equity - reserved notional
reserved notional = sum(reference price × quantity for PENDING_ENTRY)
                  + sum(fill price × quantity for OPEN)
```

Unrealized P&L is shown separately and does not finance new trades. Both BUY and
SELL reserve full notional. Available-capital checking is always enforced, with
an exact-equality boundary accepted. Fill-time available-capital checks remain
unchanged.

Position-size and portfolio-risk percentage limits keep the **account base
capital** basis used by Settings V1 and the existing sizing calculator. The
exposure view labels this explicitly; the displayed equity is not the denominator
for these limits. On a 10,000 account a 30% maximum accepts a planned 3,000 position
but rejects 4,995, without silently changing quantity.

Reservations, simultaneous positions and aggregate planned stop risk cover **both
modes together** within each currency account, preserving Settings V1's shared
account model. A forward limit therefore includes research exposure deliberately.
Research also obeys the captured profile's limits. Performance and signal identity
remain mode-separated; daily admission counts are mode-specific as described below.

## Enforced rules

The existing Settings risk model is the sole source of configured limits. Its
baseline optional enforcement switches remain off. BUY/SELL controls and minimum
R:R use their existing values (both sides enabled, minimum R:R zero at baseline).

| Check | Admission rule |
| --- | --- |
| Available funds | Proposed full notional must fit available account capital. |
| Trade sizing | Match the unchanged `PositionSizeCalculator` output for configured risk %, account capital, reference price and stop. Validate quantity, displayed risk budget/risk per share and exact notional. |
| Position size | If `enforce_position_limit`, planned notional ≤ base capital × maximum position %. |
| Simultaneous positions | If `enforce_positions_limit`, existing PENDING_ENTRY + OPEN count must be below maximum. CLOSED/CANCELLED do not consume slots. |
| Total planned risk | If `enforce_portfolio_risk_limit`, existing planned stop risk + proposal stop risk ≤ base capital × maximum total portfolio risk %. |
| Minimum R:R | Calculate planned reward / risk from the snapshot's signal price, stop and target. Reject below the configured minimum. Do not use a later fill or trust a contradictory reported ratio. |
| Side | Reject BUY when `allow_buy` is false; likewise SELL. |
| Daily creation count | If `enforce_daily_trade_limit`, mode-specific local-date count must be below maximum. |

Whole-share rounding and the existing sizing calculator's full-capital quantity
cap are unchanged. No new sizing formula is introduced. The calculator's displayed
risk budget and risk/share are rounded to two decimals; planned portfolio risk
uses the exact original signal-to-stop distance multiplied by quantity. This
avoids understating risk for pence-priced shares or sub-cent stop distances.

For **new trades**, risk % must match the captured profile (or active profile for
API calls without a captured state). This deliberately tightens Settings V1's
legacy unscoped API sizing-override path. Such callers must save a profile for the
desired risk first. Existing trade overrides and idempotent confirmations retain
their original snapshots; they are never resized or relabeled.

## Planned risk versus execution gaps

For pending and open exposures:

```
planned risk = abs(snapshotted signal price - snapshotted stop) × quantity
fill-adjusted risk = abs(fill price - snapshotted stop) × quantity
```

For pending trades fill-adjusted risk uses the reference price. Admission compares
**planned** risk to the configured limit, as requested for V1. It never regenerates
old strategy values from current parameters. The exposure view shows fill-adjusted
stop risk separately and warns when it differs. Gaps may exceed planned risk or
position limits; V1 does not resize, liquidate or reject an already filled position.
The existing strict fill-time capital check, next-session entry, completed 5-minute
execution and same-bar STOP-first behavior are unchanged.

## Daily date and mode semantics

Daily limits count successful new confirmations on the **calendar date of creation
in the trade market's timezone**, using `MARKETS` session metadata:

| Market | Currency | Timezone |
| --- | --- | --- |
| US | USD | America/New_York |
| UK | GBP | Europe/London |
| India | INR | Asia/Kolkata |

DST comes from `zoneinfo`. Browser time, UTC date, signal date and eventual fill
date do not define the bucket. After-hours/weekend confirmations count on their
actual local creation date; they are not moved to the next session. This is an
admission-rate limit, not a limit on next-session fills. Holidays and shortened
sessions retain the existing calendar limitations.

Counts include pending, open, closed and cancelled confirmations: cancellation
does not buy another admission slot that day. Retries returning an existing trade
and rejected attempts do not count again. Counts are scoped to currency, market,
local date and mode, across profiles so renaming/activating a profile cannot erase
the count. Pre-settings records with unknown mode count conservatively in the
forward bucket only, without changing their stored provenance. These semantics
replace Settings V1's shared-mode UTC-day admission count.

## Operator workflow and limits

Use Settings to select a profile and enable desired limits, then run a fresh scan.
Select a paper opportunity and Calculate quantity to inspect its Portfolio Risk
preview. Confirm Paper Trade performs the authoritative recheck. A REJECT reports
the reason and proposed totals; it does not silently alter the trade. Existing
historical records do not acquire fabricated admission decisions.

Paper Trading's Portfolio Risk / Exposure view shows one section per existing
currency account, with disabled limits labeled explicitly. It uses the active
mode for daily counts and all modes for shared exposure. It performs no provider
calls and creates no update runs. The existing performance journal still excludes
RESEARCH from the default forward view.

V1 has no size reduction, continuous limit enforcement, cross-currency risk,
correlation/sector limits, buying-power model or automated trading. Accepted decisions are snapshots, not guarantees about future fills.

## Validation

`tests/test_portfolio_risk.py` covers exact boundaries, the 4,995/30% example,
multiple rejection reasons, sizing tampering and Decimal precision, pending/open
exposures, cancellations/closed trades, currency and mode isolation, shared capital,
market-local midnight and DST, concurrent capital/position/risk/daily-limit races,
stale previews, idempotency, immutable accepted decisions and legacy provenance.
`tests/test_portfolio_risk_web.py` exercises preview/rejection and the exposure view
without a web server or live data. Existing scanner baseline fixtures and paper
execution/performance regressions remain part of the full test suite.


## Audit review and future interfaces

Paper Trading exposes the latest 100 rejected confirmation attempts with symbol,
mode, currency, reasons and the full typed decision. The database retains all
attempts. Journal rows show planned position %, trade risk %, total planned risk
and position count after admission. Historical rows show `PRE_PORTFOLIO_RISK` at
read time only. The Confirm button is disabled after a rejected preview; the
service remains authoritative if a browser submits a stale or forged request.

Settings lists configured values and ENFORCED/INACTIVE status. Changes take effect
after Save; existing scans retain their captured profile.

`FuturePortfolioControls` is an inactive typed V2 interface, deliberately outside
the Settings V1 hash/schema. It reserves daily realized loss %, drawdown %,
trading halt, sector, industry, correlation group and beta fields. V1 never reads
these fields for admission. V2 requires explicit data provenance, exposure
aggregation and halt/reset semantics before activating any such controls.

## Manual checks without changing historical trades

Use a separate disposable data directory via `AUTOT_DATA_DIR` for manual work;
never copy or edit the historical ledger. Set a new USD account to 10,000 and save
a profile with risk/trade 0.5%, maximum position 30%, maximum positions 5 and
maximum total portfolio risk 2.5%. Enable all three maximum-limit switches. Run a
fresh scan after every profile change; use different signal identities for new
confirmations. The examples below describe planned signal snapshots, not edits
to strategy outputs. If live scan candidates do not match, the offline tests
exercise these exact boundaries using synthetic opportunities.

- Allowed: entry 100, stop 95, target 110 gives 10 shares, value 1,000 and risk 50.
- Position rejected: entry 99.9, stop 98.901, target 101.898 gives 50 shares and
  value 4,995, exceeding 3,000. Confirm is disabled after Calculate quantity.
- Capital rejected: in a fresh disposable account, entry 100, stop 98, target
  104 gives 25 shares, value 2,500 and risk 50. Four distinct confirmations reserve
  all 10,000. A fifth requires 2,500 with zero available, while its proposed five
  positions and risk 250 still meet the other limits.
- Position count rejected: in another fresh disposable account, entry 100, stop
  70, target 160 gives one share, value 100 and risk 30 after whole-share rounding.
  Five distinct confirmations consume five slots and risk 150. A sixth exceeds
  the position count while value 600 and risk 180 remain within other limits.

No monitoring, cancellation or modification of historical trades is needed.
