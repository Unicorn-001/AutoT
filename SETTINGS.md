# Settings & Strategy Profiles V1

Settings live independently of Streamlit in `autot/settings/models.py` (Pydantic models),
`store.py` (persistence), `context.py` (one configuration per scan), and
`trade_policy.py` (compatibility entry point to the Portfolio Risk admission engine). All models reject unknown fields,
non-finite numbers and invalid ranges. Nested configuration is immutable. Public
service boundaries revalidate even model copies made without validation.

## Storage and recovery

`AUTOT_DATA_DIR/settings/settings.sqlite3` stores append-only settings revisions,
profile versions, and change records. SQLite `BEGIN IMMEDIATE` transactions and
`synchronous=FULL` commit profiles, revisions and history together. Update/delete
triggers protect all three tables. Optimistic revision checks reject stale saves.
Loads are read-only; an unused baseline requires no settings file. Schema version
is currently 1. Future schemas must have an explicit migration; unsupported or
invalid snapshots cannot become active.

Each full revision has an integrity hash. A damaged revision falls back to the last
valid revision with a warning; an unreadable database or no valid revision falls
back to the protected baseline with a warning. New web scans and unscoped paper
confirmations are blocked while the storage warning remains. An explicit save
can recover a damaged latest revision without overwriting it. A physically damaged
database needs operator repair from backup. The warning is surfaced through
`SettingsStore.warning` and `SettingsWarning` outside Streamlit too. Valid, previously
captured scan snapshots remain usable independently of subsequent settings storage.

No API-key, credential, provider token or arbitrary extension fields are accepted.
Secrets stay in the existing environment configuration. Do not put secrets in names
or change notes. Runtime databases are excluded from Git by `data_storage/`; an
external `AUTOT_DATA_DIR` is the operator's responsibility to back up/protect.

## Configurable sections

- **General:** `FORWARD_TEST` or `RESEARCH`.
- **Scanner:** country/index, history period, interval, top ranked count, optional
  displayed opportunity limit. Baseline: United States / S&P 500, 5y, 1d, 10 ranked,
  all opportunities. The display limit does not change qualification or rankings.
- **Strategies:** enable/disable, optional weight replacement, existing per-regime
  weights, and advanced indicator parameters for all ten existing strategies.
- **Consensus:** minimum confidence 55%, minimum agreement 0% (no extra gate).
  Voting, rounding, confidence and agreement formulas are unchanged.
- **Risk:** risk per trade, optional maximum position value/count/portfolio risk/
  daily creations, minimum R:R, allowed sides, acknowledgement requirement.
- **Paper trading:** USD, GBP and INR starting capital defaults for NEW accounts,
  each 10,000 in its own currency. Existing capital/balances are never changed.
- **News:** enabled, general news, official disclosures, recent window days (7),
  maximum articles (50). Placeholders only: no effect until the other branch merges.
- **Monitoring:** update interval (5 minutes), daily scan enabled (false).
  Placeholders only: no scheduling, threads, workers or automatic execution.
- **Advanced:** read-only 5m execution, next-session-open fills, STOP-first same-bar
  ambiguity, SessionCalendar, Yahoo data, PAPER execution and ledger path policy.

The old configuration modules expose baseline compatibility values; supported
runtime settings come from typed models. The legacy CSV loader is retained for
CLI universe/cache options. After saving Settings V1, CLI history/interval/top-count
settings come from the centralized configuration. Web scanner defaults come from
Settings V1. CSV values are not silently imported into a trading profile.

## Registry and actual baseline defaults

`autot/strategies/registry/strategy_registry.py` owns metadata, stable IDs, display
names, version `1`, descriptions, parameter schemas, default parameters and advanced
parameter names. Its configured metadata includes enablement and weights. The
existing strategy classes and indicator functions remain the execution source.
All ten strategies are enabled in **AutoT Current / Baseline v1**.

| Strategy ID | Advanced baseline parameters |
| --- | --- |
| EMA_RSI | EMA 20/50, RSI 14, BUY RSI >50, SELL bearish EMA or RSI <45 |
| MACD | Fast 12, slow 26, signal 9; existing pandas EWM calculation |
| BOLLINGER | Period 20, deviation 2; existing sample standard deviation |
| BREAKOUT | Previous 20 bars; no additional confirmation parameter exists |
| SUPERTREND | Rolling ATR period 10, multiplier 3; existing simplified band condition |
| ADX | Indicator period 14, directional threshold >25 |
| VOLUME_SPIKE | Volume average 20, ratio >=2; shared EMA trend |
| MOMENTUM | Price difference over 10 bars |
| ATR | Indicator period 14, ATR average period 20; shared EMA trend |
| STOCHASTIC | Period 14, smoothing 3, oversold 20, overbought 80 |

| Strategy | Strong uptrend | Strong downtrend | Sideways / weak |
| --- | ---: | ---: | ---: |
| EMA + RSI | 1.20 | 1.20 | 1.00 |
| MACD | 1.20 | 1.20 | 1.00 |
| Bollinger | 0.90 | 0.90 | 1.20 |
| Breakout | 1.10 | 1.10 | 0.85 |
| Supertrend | 1.20 | 1.20 | 0.90 |
| ADX | 1.00 | 1.00 | 1.00 |
| Volume Spike | 1.00 | 1.00 | 1.10 |
| Momentum | 1.15 | 1.15 | 0.90 |
| ATR | 1.00 | 1.00 | 1.00 |
| Stochastic | 0.90 | 0.90 | 1.20 |

The optional weight is `null` by default: use this existing regime table, with 1.0
for unknown regimes. Enabling a weight override substitutes that value for the
regime lookup. The formula remains `round(original_confidence * weight, 4)`.
Votes and consensus scores use the original implementation. A disabled strategy
contributes no vote; enabled weight zero still contributes a vote but zero score,
consistent with the original weighting formula. All-disabled produces HOLD.

Indicator columns retain their legacy names. EMA parameters are shared by the
trend, ATR and volume strategies and supporting calculations. Changing them also
changes those shared inputs. Fixed scanner ranking/support/quality formulas,
stop/target percentages (2/4), execution semantics and historical backtest rules
are not editable in this release. Backtest RSI rules remain their existing 50/45;
custom live parameters do not imply a matching strategy-specific backtest.

## Profiles, hashes and history

Profiles include ID, name, version, timezone-aware creation/update timestamps,
parent ID, configuration hash, and typed strategy/consensus/risk snapshots. Every
custom edit or rename creates the next version. Duplicating creates a new ID at
v1 with a parent reference. Activating a saved version preserves all its trading
settings while retaining scanner, capital, mode and other application sections.
The built-in baseline cannot be edited, renamed or deleted in place. Changing its
trading settings creates a custom profile. Historical profiles are immutable even
before they are referenced by trades. There is no profile deletion API in V1.

Configuration hashes are SHA-256 of sorted-key, compact, ASCII JSON from validated
models. All defaults are materialized and numeric types normalized before hashing.
Equivalent trading configurations hash identically, regardless of profile name,
ID, version, timestamp or input key order. A profile hash covers strategies,
consensus and risk. Full settings revisions have a separate full-state integrity
hash. Mode, scanner defaults and new-account capital are outside the profile hash.

Successful saves/activations record UUID change ID, UTC timestamp, old/new full
settings configuration hashes, profile ID/version and optional note. A rename or
activation may have equal configuration hashes while retaining distinct profile
identity. Reruns and no-op saves do not add history. Revision numbers monotonically
increase, including after recovery from an invalid revision.

## Paper-trade snapshots and migration

A web scan captures one immutable SettingsState before analysis, bound separately
inside each worker. Paper drafts retain that scan state. Saving or activating a
profile later cannot relabel an earlier opportunity. Run a new scan to use a new
profile. API callers confirming delayed signals must pass the captured
`settings_state` to `PaperTradingService.confirm`.

Every new service-created trade persists settings revision, profile ID/name/version,
profile hash, `configuration_source=SETTINGS_V1`, mode, validated trading settings,
and execution risk percent. Its existing snapshot already includes market, index,
regime, direction, capital, actual quantity and sizing risk. The UI locks risk to
the scan's profile; mismatched profile sizing is rejected. API callers without a
captured state use the active profile. Portfolio Risk V1 now requires their sizing
risk to match that profile too; Settings V1 previously allowed explicit overrides.
Existing override snapshots are retained unchanged. New integration code should
always pass captured settings and matching risk. Accepted new trades also capture
a typed `portfolio_risk_decision`. Previews are read-only; rejected confirmations
append a separate rejection audit without creating trades or trade events.

Old snapshots receive only the read-time label `PRE_SETTINGS_BASELINE`. No profile,
mode or detailed configuration is invented. The ledger snapshot, trade ID, P&L,
execution state and audit events are not rewritten. Low-level ledger import/fixture
paths can still preserve historical snapshots without configuration; new application
trades must go through the service. Ledger initialization adds the rejection
audit table without rewriting existing records.

## Risk and capital compatibility

Baseline risk is **1.0%**, preserving the current effective behavior. Suggested
30% position value, 5 simultaneous positions, 2.5% portfolio risk and 5 new trades
per market-local day per mode are stored but their enforcement switches default OFF. Minimum R:R is
0 (no additional admission restriction); existing price/direction validation remains.
BUY/SELL and manual acknowledgement default ON. Set risk to 0.5% and enable the
limits explicitly in a new profile to adopt them. The Settings summary lists each
configured value with ENFORCED or INACTIVE status.

Enabled admission checks run in the same serialized ledger transaction as capital
reservations. Position and portfolio-risk limits include pending entries, cover
the entire currency account across forward/research modes, and use base capital,
not marked-to-market equity. Portfolio Risk V1 sums quantity times the absolute
snapshotted signal-to-stop distance for planned risk, and reports fill-adjusted
risk separately. Daily limits count confirmations per mode and market-local date,
including cancelled creations. Pre-settings records count with forward admissions
without assigning a stored mode. No FX aggregation is attempted. See
[PORTFOLIO_RISK.md](PORTFOLIO_RISK.md) for the engine API and complete semantics.
Limits are creation-time checks: gaps can increase actual position value/risk.
The existing fill-time available-capital check remains strict and unchanged.

Changing capital defaults never recapitalizes an existing account. Recapitalization
would require a separate audited account-management action and is not implemented.
Turning off acknowledgement does not create autonomous trading: users still press
Calculate quantity and Confirm Paper Trade. No live execution path is introduced.

## Forward / research and performance

Research mode adds a separate opportunity identity, so the same signal can have a
forward and research trade. Reservations and account balances remain shared; research
cannot bypass account capital or enabled limits. Research P&L affects that shared
account balance but is excluded from the default forward performance report.

`PerformanceService.report` supports mode, typed-known filter field names and grouping
by profile ID/name/version, hash, mode, market, index, BUY/SELL and regime. Missing
legacy values stay `None`/Unknown. Default forward statistics retain pre-settings
history (without assigning it a fabricated mode); Research and Pre-settings views
are available separately. Currency totals remain separate. The journal UI provides
filters, grouped summaries and raw trade snapshots.

## UI workflow

Open Workspace → Settings. Review the active profile and risk summary. Edit the
form, enter a custom profile name and select Create / duplicate as a NEW profile.
Save Settings validates and activates one revision. For subsequent edits, leave
that checkbox off to create the next version of the same custom profile. Renaming
also versions the profile. Activate profile selects an already saved immutable
version. Reset Section changes only that draft section. Restore All Defaults asks for confirmation,
then replaces the entire draft with AutoT Current / Baseline v1 defaults. Cancel
preserves unsaved edits. Save Settings is still required; resetting writes no revision
and leaves saved profiles, historical trades, audit events and ledger balances intact.
Country changes immediately filter the index selector in both Settings and Scanner
using the index registry. An incompatible selection becomes the first registered index
for that country; validation also rejects mismatched country/index settings on save.

To start the requested forward configuration: use baseline, set risk to **0.5**,
maximum position percent **30**, maximum simultaneous positions **5**, and check
Enforce position limit / Enforce positions limit. Optionally enable the 2.5%
portfolio risk and daily creation limits. Name it `US Swing`, save as a NEW profile,
then run a fresh daily scan. Check Paper Trading → closed records to confirm the
existing MPC/MRNA P&L and IDs are unchanged. Confirm a new eligible opportunity,
then inspect Details / actions or Journal → Raw trade snapshot JSON for the profile,
version, hash, mode, settings revision and trading settings.

## Validation evidence

`tests/fixtures/settings_baseline_8b08e3c.json` was captured from audit checkpoint
`8b08e3c`, before settings changes. It contains full scanner/decision results plus
all ten strategy results, weights and consensus on deterministic up/down/sideways/
reversal datasets producing BUY, SELL and HOLD. Exact comparisons guard defaults.
Tests also cover changed parameters/weights/enablement, validation, hashes, corruption,
restart persistence, atomic rollback, concurrent saves, immutable profiles, trade
snapshots, old records, capital preservation, limits, research and performance filters,
and the Settings form without launching a Streamlit server.
