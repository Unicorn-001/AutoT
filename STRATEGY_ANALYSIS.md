# Paper Trading Validation & Strategy Improvement V1

AutoT's existing strategy configuration remains the control. This feature learns
from **closed prospective paper trades**, without changing any indicators,
parameters, weights, confidence/agreement/quality/ranking formulas, stops,
targets, admission policy, execution rules or fills. No optimiser, automatic
profile creation, tuning or promotion is included.

## Architecture and evidence

`autot/strategy_analysis/models.py` defines typed `StrategyFeature`,
`TradeFeatureSnapshot`, `StrategyContribution` and `ExperimentProposal` models.
`snapshot.py` serializes existing weighted scan results; it never runs strategy
calculations. `service.py` builds descriptive cohorts using the consistent
trade/event read in `PerformanceService`. All analytics and CSV exports are
read-only; there is no analysis database migration.

`main.analyse_stock` adds one output field, `strategy_features`, without changing
existing output values. Settings checkpoint tests compare every previous field
and decision against the original fixtures. NEW paper confirmations validate and
persist the feature snapshot alongside the immutable original opportunity. The
ledger's existing settings snapshot retains profile ID, name, version and
configuration hash. Existing trade records are never backfilled or rewritten.

The snapshot contains all ten registered strategies: stable ID, enabled state,
original BUY/SELL/HOLD vote, actual effective weight, configured regime weight,
manual weight override, original confidence and weighted confidence. Disabled
strategies have no evaluated signal or effective weight; they are not HOLD.
Weighted confidence is the existing weighted strategy result, not a newly
invented attribution of final confidence. The snapshot also retains the existing
symbol, market, index, side, signal time, regime, confidence, agreement,
trade quality, historical score, risk/reward, prices and sizing fields.

Snapshots are versioned, validate finite weights and unique IDs, and bound V1 to
ten strategy entries. Partial programmatic/older scan inputs remain partial;
missing information is never filled from today's settings. Legacy original
opportunities sometimes contain five stored votes; those exact votes can be
analysed with unavailable weights, independently of the full snapshot count.

## Scope and metrics

The default is **FORWARD_TEST** with an explicit **RESEARCH** selector.
Trades without a stored mode appear only in **UNKNOWN_LEGACY**. This stricter
policy differs from the older Performance journal, which includes pre-settings
trades in its forward view. No unknown-mode trade silently enters the new
forward statistics. Pending, open and cancelled trades are excluded.

Every cohort is separated by USD, GBP or INR. The low-level metrics function
rejects mixed currencies; exports carry currency, mode and selected profile
identities. Profile selection uses ID, name, version **and** configuration hash.
The UI explicitly labels the all-profiles comparison and warns when cohorts
contain multiple configurations. A pooled comparison is not a controlled trial.

Metrics include counts, wins/losses/breakeven, win rate, positive gross profit and
positive gross loss magnitude, net P&L, profit factor, average P&L/expectancy,
average return, average win, signed average loss, payoff ratio, best/worst P&L,
average holding seconds, average MFE/MAE per share and percent, evidence counts,
and realized-close drawdown.

- Win rate counts breakevens in the denominator.
- Expectancy = net realized P&L / closed trades, in the cohort currency.
- Return = realized P&L / (actual fill price × quantity) × 100; means are
  unweighted arithmetic means, not a portfolio return.
- Profit factor = gross profit / gross loss magnitude; unavailable without
  losses (not infinity). Payoff = average win / absolute average loss; unavailable
  without both wins and losses. Zero is retained when meaningful.
- Holding time uses stored execution timestamps.
- MFE/MAE reuse durable processed-bar audit evidence. Missing history is
  UNAVAILABLE, never zero. Intrabar stop/target exits provide known-movement lower
  bounds; the report counts these separately. Per-share movement is not total
  position profit. Means include only supported observations, with sample counts.
- Drawdown is peak-to-trough decline in the cumulative **realized closed-trade
  P&L curve**, starting at zero and ordered by close timestamp. Simultaneous
  closes are batched. It is a currency amount for the selected cohort, **not**
  mark-to-market account drawdown, percentage equity drawdown or intratrade risk.

## Cohorts and combinations

BUY/SELL and the three known regimes (STRONG_UPTREND, STRONG_DOWNTREND,
SIDEWAYS_OR_WEAK_TREND) have separate summaries. Other regimes are `unknown`.
Every regime summary includes BUY/SELL counts and supported excursion metrics.

A strategy contribution is aligned when its recorded vote equals the final trade
direction, opposed when it votes the opposite direction, and held when it votes
HOLD. Disabled and unavailable votes are separate. Strategy × regime cohorts use
the same rules. Missing legacy strategies are absent, not assumed to hold.

Automatic combinations enumerate aligned pairs and triples from at most ten
stored strategies (45 pairs + 120 triples), with a default minimum of 20 closed
trades **per currency**. No exhaustive larger search is performed. Specific
combinations of 2–10 distinct IDs can be queried, including small samples. Zero
matches return no cohort; the UI explains this. Combinations overlap and do not
represent independent samples or causal strategy contributions.

`DEFAULT_BINS` generates confidence, agreement, quality, historical-score,
planned-risk %, position % and actual-fill-risk % cohorts. The service accepts
custom strictly increasing finite edges. Bins include the lower boundary and
exclude the upper boundary, with explicit underflow, open-ended final and
UNAVAILABLE groups. For example, confidence 75 belongs to `75–<80`; agreement
100 belongs to `100+`. Nothing optimises thresholds automatically.

Risk percentages use the immutable account base capital and stored prices:
planned stop distance × quantity; signal notional; or actual-fill stop distance
× quantity. Actual-fill risk is a stop-distance exposure measure, not observed
realized loss. Missing inputs yield UNAVAILABLE. No increased risk is recommended.

## Samples, observations and experiment workflow

| Closed trades | Descriptive label |
| --- | --- |
| <20 | VERY SMALL SAMPLE |
| 20–49 | SMALL SAMPLE |
| 50–99 | EARLY EVIDENCE |
| 100–149 | MORE MEANINGFUL |
| 150+ | STRONGER SAMPLE FOR REVIEW |

These labels are not significance tests or proof of profitability. The rule-based
observations compare cohort expectancy with the selected currency baseline and
use INSUFFICIENT SAMPLE or OBSERVATION wording. Cohorts overlap their baseline;
regime, side, profile and selection effects may confound any difference. Multiple
comparisons invite overfitting. These are possible candidates for human testing,
never commands to alter weights or settings.

Only admitted trades have outcomes here. Whether a filter removed profitable
trades is **unavailable** without prospective counterfactual tracking of rejected
signals. Filter-band results describe retained trades only.

`ExperimentProposal` stores hypothesis, baseline profile identity, candidate
change, reason, supporting sample, metrics, minimum required sample and status:
DRAFT → READY_FOR_RESEARCH → RESEARCH_ACTIVE → REVIEWED → PROMOTED / REJECTED.
These are tracking labels, not executable transitions. The UI exports a DRAFT
JSON after a single baseline profile is selected. V1 does not persist a proposal
registry in the trading database: keep/review the downloaded artifact, update its
status through a human review process, and authorize any separate research
implementation explicitly. Even a PROMOTED label cannot activate a profile.

## UI, completeness and exports

Paper Trading → Show Strategy Analysis opens summary metrics followed by
expandable side, regime, strategy, strategy/regime, combinations, score bands,
risk bands, profiles and observation tables. Specific combinations can be chosen
interactively. The selected trade shows signal/profile metadata, votes/weights,
portfolio admission, actual entry/exit, P&L, return, holding duration and excursion
evidence. The existing Journal receives the same selected-trade detail. Raw
snapshots remain inside expanders.

Completeness counts show closed trades, any stored strategy signals, complete
all-ten feature snapshots, MFE/MAE, complete profile metadata, historical scores,
pre-settings trades and excluded unknown-mode trades. Counts refer to the selected
scope except the explicitly named excluded-unknown-mode count. Sparse evidence
never becomes an implied negative outcome.

CSV downloads include trade-level features and outcomes, each cohort summary,
and profile comparisons. `export_csv(report, 'summary')` also supports the overall
currency summary. Missing values use UNAVAILABLE; textual spreadsheet formulas
are escaped. Exporting, selecting and rerendering never update trades or settings.

## Manual review with the existing database

From `/Users/sreedevpv/projects/AutoT`, use your usual environment and run
`streamlit run web_app.py` yourself. Keep the normal `AUTOT_DATA_DIR` setting
(or leave it unset for `data_storage`). Do not point at a fresh test directory.

1. Open Paper Trading and enable Show Strategy Analysis.
2. Start with FORWARD_TEST and inspect completeness. No eligible closed trades
   is a valid result; legacy records may have no stored mode.
3. Select UNKNOWN_LEGACY to inspect existing MRNA/MPC/ULTA evidence when those
   records lack mode metadata. Missing strategy weights and excursions should
   remain UNAVAILABLE.
4. Inspect BUY/SELL, regime, profile and band tables; query a specific combination
   if stored votes exist. Small-sample warnings should remain visible.
5. Open Closed-trade evidence or Show Performance / Journal, select a closed
   trade, and compare its stored signal, admission, fills and outcomes.
6. Download CSVs; rerender and verify trade counts and outcomes remain unchanged.
   Do not click Update Paper Positions unless you intend to advance execution.

Tests use offline supplied bars and Streamlit AppTest; development validation
does not launch Streamlit or fetch new market data.
