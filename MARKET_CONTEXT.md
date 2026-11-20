# Pre-Trade Market Context V1

An explicit, advisory assessment answers whether a persisted scanner setup remains
attractive at a manually supplied executable price. It never changes scanner
calculations/results, strategy signals or scores, original prices, paper trades,
or Fill-Time Risk Recheck. It neither places nor blocks trades.

## Architecture and storage

- `autot/market_context/assessment.py`: pure deterministic calculation and extensible
  reason-description registry. `Thresholds` is immutable and injectable, with no new
  user settings. Each assessment records its version and threshold snapshot.
- `autot/market_context/store.py`: append-only JSON snapshots in a separate SQLite
  database, with indexed scanner run and opportunity identity. The service reads
  the selected scanner run using SQLite read-only mode and resolves its opportunity
  by zero-based index in the persisted `trade_opportunities` list. It does not trust
  browser-supplied setup values.
- `autot/application/market_context_display.py`: a small expander per displayed
  scanner opportunity, called by `scan_display.py`. Manual price entry and explicit
  **Assess current price** create a new snapshot. Rerenders and restarts display the
  latest saved assessment without creating another one. No historical backfill.

Database: `${AUTOT_DATA_DIR}/market_context/market_context.sqlite3`, default
`data_storage/market_context/market_context.sqlite3`. No assessment data is written
to scanner history or `paper_trading/ledger.sqlite3`. Records contain the input
snapshot, assessment UUID, run/index linkage, UTC assessment time, optional session
and provider/source, calculations, crossed flags, decision, and reason codes.
Non-finite or unparseable numeric inputs are persisted as null and rejected.

## Formulas

For BUY: risk = current − stop; reward = target − current.
For SELL: risk = stop − current; reward = current − target.
Current R:R = reward / risk only if both are strictly positive.

- Gap absolute = abs(current − reference).
- Gap percent = gap absolute / reference × 100 (always nonnegative).
- Stop/target distance absolute = abs(current − stop/target).
- Stop/target distance percent = respective distance / current × 100.
- R:R deterioration = supplied original R:R − current R:R. The original value
  is preserved, never recalculated or replaced.
- Original directional reward = target − reference for BUY, reference − target
  for SELL.
- Reward consumed percent = max(0, directional move from reference /
  original directional reward × 100), where the move is current − reference for
  BUY and reference − current for SELL. Values can exceed 100 beyond the target.
- Stop crossed includes equality (risk ≤ 0); target crossed includes equality
  (reward ≤ 0). Distances remain absolute, with flags indicating invalidation.

A better entry price moves away from the target and improves R:R until the stop
is reached. A move toward the target consumes reward and worsens entry R:R.

## Decision precedence and defaults

REJECT overrides CAUTION, which overrides ELIGIBLE.

- REJECT: missing/non-finite/nonpositive price, entry, stop, target or original
  R:R; invalid side; missing symbol; invalid original geometry (BUY requires
  stop < entry < target, SELL requires target < entry < stop); non-finite derived
  values; current risk/reward ≤ 0; or current R:R < **1.0**.
- CAUTION: otherwise current R:R < **1.5**, gap percent ≥ **1.0%**, or reward
  consumed > **25%**.
- ELIGIBLE: otherwise (R:R ≥ 1.5, gap < 1%, consumed ≤ 25%, valid boundaries).

All applicable reasons are retained for valid numeric setups, including caution
reasons on rejected assessments. The registry can add new codes without schema
changes; unknown codes render verbatim.

| Code | Meaning |
| --- | --- |
| INVALID_MARKET_DATA | Invalid numeric input, original geometry, side, or symbol |
| INVALID_STOP_RELATIVE_TO_CURRENT | Current price reached/crossed stop |
| TARGET_ALREADY_REACHED | Current price reached/crossed target |
| RISK_REWARD_DETERIORATED | R:R below eligible threshold; do not chase |
| LARGE_GAP | Absolute gap meets caution threshold |
| REWARD_ALREADY_CONSUMED | Reward consumption exceeds threshold |
| SETUP_STILL_VALID | No reject or caution rule applies |

`DO_NOT_CHASE` is explanatory text for R:R deterioration, not a second reason code.
Assessment timestamps describe evaluation time; V1 does not verify quote age,
spread, slippage, fees, market hours, liquidity, or manual price provenance. The
optional session label is metadata only. No live provider refresh is implemented;
refresh means entering a fresh price and assessing again. Unsaved legacy/session
results cannot be assessed. The UI shows the latest assessment; all earlier
snapshots remain in the database and are accessible through `history`.

## Manual validation

For a reproducible demonstration without touching production data, run this from
the repository root. These are explicitly synthetic scanner fixtures, not a scan
or retroactive market-context assessments. Assessments are only created by clicks.

```sh
export AUTOT_DATA_DIR="$(mktemp -d /tmp/autot-market-context-demo.XXXXXX)"
venv/bin/python - <<'PYDEMO'
from autot.application.scan_store import ScanStore, stamp
store = ScanStore()
run = store.create(dict(market='US', universe='demo', state={'profile': 'demo'}))
rows = [dict(symbol=symbol, signal=side, entry_price=entry, stop_loss=stop,
             take_profit=target, risk_reward_ratio=2, confidence=80,
             agreement=80, score=80, trade_quality_score=80)
        for symbol, side, entry, stop, target in [
            ('CAH', 'BUY', 272.34, 266.8932, 283.2336),
            ('NVDA', 'SELL', 145.98, 148.8996, 140.1408)]]
run.update(status='SUCCESS', completed_at=stamp(), opportunities_count=2)
store.save(run, dict(scan_run_id=run['scan_run_id'], completed_at=run['completed_at'],
    settings=dict(universe='Synthetic manual validation', period='1y', interval='1d', top_n=10),
    outputs=dict(symbols=['CAH', 'NVDA'], results=rows, ranked_results=rows,
                 top_results=rows, trade_opportunities=rows)))
print('Demo scanner database:', store.path)
PYDEMO
venv/bin/streamlit run web_app.py
```

1. Open **Scanner** in the app and scroll to Trade Opportunities. Keep this
   terminal's `AUTOT_DATA_DIR` for restart validation. Alternatively, use production
   scanner results only if they already contain the exact setups below.
2. Expand **Pre-Trade Market Context · CAH · BUY** for reference 272.34,
   stop 266.8932, target 283.2336, original R:R 2. Enter **275.63** and click
   **Assess current price**. Expect current R:R **0.8703**, gap **1.2080%**,
   reward consumed **30.2012%**, **REJECT**, and RISK_REWARD_DETERIORATED,
   LARGE_GAP, REWARD_ALREADY_CONSUMED. The entry/stop/target/scores stay unchanged.
3. For **NVDA · SELL**, reference 145.98, stop 148.8996, target 140.1408,
   original R:R 2: enter **145.98** and assess. Expect R:R **2.0000**, gap 0%,
   consumed 0%, **ELIGIBLE**, SETUP_STILL_VALID. Enter **144.90** and assess
   again: R:R **1.1899**, gap **0.7398%**, consumed **18.4957%**, **CAUTION**,
   RISK_REWARD_DETERIORATED. Enter **144.00**: R:R **0.7877**, gap **1.3564%**,
   consumed **33.9088%**, **REJECT** and the same three reasons as CAH.
4. Reload/restart the app: the latest assessment and timestamp persist. Reloading
   alone creates no assessment. Enter a new price and click to add a new record.
   Verify original scanner results and existing paper trades are unchanged.
