# Pre-Trade Market Context V1.1

An explicit, advisory assessment answers whether a persisted scanner setup remains
attractive at a manually supplied or explicitly fetched price. It never changes scanner
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
Assessment timestamps describe evaluation time. Neither version verifies executable
bid/ask, spread, slippage, fees, or liquidity. V1 records retain their original meaning. Unsaved legacy/session
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


## V1.1 automatic price retrieval

**Fetch latest price → Review/edit → Assess current price**. Fetching and rerendering
never assess or trade. Manual entry works without fetching. A failed refresh shows
a non-fatal error and preserves the previous input and quote provenance. Quotes
are scoped in Streamlit state to scanner run and opportunity; unsaved quotes do not
survive a new browser session. Saved assessment metadata survives restart and is
shown below the input.

`MarketDataManager.get_latest_quote` delegates to `market_data/quote.py`, reusing
symbol normalization and `YahooDownloadPool` (owned workers, HTTP session, error
handling and cache cleanup). No new provider stack or dependency is introduced.
Yahoo is the only configured provider supported by the existing settings model.
The request uses five days of one-minute data and selects the latest bar's close;
it does not use the historical loader's 50-row minimum or fall back to scanner data.
The existing downloader uses adjusted prices and regular-session bars. This is a
latest available **bar close**, potentially delayed, not a live executable quote;
after-hours trades are not included. The timestamp is the bar-start timestamp,
normalized by Yahoo's timezone-aware index. Naive/missing timestamps are unknown.
An empty Yahoo response cannot distinguish a nonexistent symbol from unavailable
data, so the error message states both possibilities. Provider exceptions/timeouts,
missing prices and nonpositive/nonfinite prices are handled without crashing the UI.

`Quote` holds symbol, price, optional timezone-aware timestamp, source and optional
session label. Its audit snapshot calculates age at assessment (and display) time.
`STALE_QUOTE_SECONDS = 300` is configurable in `market_data/quote.py`: stale is true
only for a known active `REGULAR` session with age strictly above the threshold.
Known closed/pre/post sessions are not stale solely because of elapsed time.
The Yahoo download supplies **no reliable current-session status**, so V1.1 leaves
the session unknown and conservatively does not mark it stale. The UI explicitly
says freshness is unverified; false does not certify freshness. No weekday/timezone
heuristic or holiday calendar is assumed. Future timestamps have unknown age.

New assessments have version `"1.1"` and additive fields: `fetched_price`,
`assessed_price` (also retained as `current_price`), `price_source`,
`quote_timestamp` (ISO 8601), `quote_age_seconds`, `stale`, `session_label`, and
`manual_override`. Override compares the numeric assessed value to the fetched
price; editing then restoring the same value is not an override. Quote metadata is
preserved on override and age is recomputed at assessment. Staleness is advisory
metadata only; existing assessment decisions and formulas remain unchanged.
Manual-only assessments have no fetched price/timestamp/age and source MANUAL.
V1 rows receive defaults on read only; no migration or retroactive rewrite occurs.

### Exact V1.1 manual validation

1. Run the synthetic fixture command above and start Streamlit with the same
   `AUTOT_DATA_DIR`. Open Scanner → Trade Opportunities → CAH's Pre-Trade Market
   Context expander.
2. Enter `275.63`, click **Assess current price**, and verify the V1 result above.
3. Click **Fetch latest price** with network access. Verify a price is prefilled
   and price, timestamp, Yahoo source, unknown session, age and freshness limitation
   appear. Confirm the last assessment's timestamp and price have not changed.
4. Click **Assess current price**. Verify the saved fetched and assessed prices
   match, manual override is False, and quote timestamp/age/source are displayed.
5. Change the price to `275.63`. Confirm editing alone saves nothing. Click
   **Assess current price**; verify the original fetched price is preserved and
   override is True (unless the fetched price itself was exactly `275.63`).
6. Open NVDA's expander and verify CAH's input and quote do not prefill NVDA.
7. Disable network, click **Fetch latest price**, and verify a non-fatal provider
   error, preserved input, and that a manual assessment still works. Restore network.
8. Restart Streamlit using the same data directory. Verify the last assessment and
   all saved audit metadata remain visible, with no extra assessment created.
9. Run `venv/bin/python -m pytest tests/test_market_context_quotes.py -q` for
   deterministic stale REGULAR, closed-session, invalid/missing quote and provider
   failure scenarios. Live Yahoo cannot reliably demonstrate known-session stale
   detection. These tests also verify scanner and paper ledger bytes stay unchanged.
