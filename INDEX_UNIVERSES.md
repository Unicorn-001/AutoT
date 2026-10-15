# Web V1 market-index universes

The default browser flow is **Market Index → Market → Index → Run Scan**. No CSV,
server path, or built-in constituent list is required. Upload CSV is an optional
custom mode. The CLI's CSV defaults, ordering and duplicate behavior remain unchanged.

## Architecture

- `IndexDefinition` holds country, market, index ID/name, adapter key, exchange,
  expected size and benchmark. It contains no constituent lists.
- `index_sources.py` isolates every URL and source-specific CSV/JSON/HTML parser.
- `IndexUniverseProvider(index_id).load()` validates, normalizes, deduplicates and
  caches a `UniverseResult`. `ProviderUniverseLoader` supplies its Yahoo symbols
  to the existing `run_scan()` dependency interface.
- `UniverseResult` preserves raw source symbols, Yahoo symbols, company names,
  market/index/exchange metadata, raw/filtered/duplicate counts, actual source URL,
  retrieval timestamp and warnings. Browser session state retains that result
  alongside scan settings, outputs and diagnostics.
- `scanner_service` knows no websites. Its only behavioral extension is an optional
  `benchmark_symbol` argument, defaulting to `SPY`.

## Sources and limitations

| Market | Index | Preferred source | Same-index fallback |
| --- | --- | --- | --- |
| United States | S&P 500 | [Wikipedia constituent table](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies) | Valid local cache |
| United States | Nasdaq-100 | [Nasdaq published JSON](https://api.nasdaq.com/api/quote/list-type/nasdaq100) | [Wikipedia constituent table](https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies), then cache |
| United States | Dow Jones Industrial Average | [Wikipedia constituent table](https://en.wikipedia.org/wiki/List_of_Dow_Jones_Industrial_Average_companies) | Valid local cache |
| United Kingdom | FTSE 100 | [LSE constituent table](https://www.londonstockexchange.com/indices/ftse-100/constituents/table) | [Wikipedia constituent table](https://en.wikipedia.org/wiki/FTSE_100_Index), then cache |
| United Kingdom | FTSE 250 | [LSE constituent table](https://www.londonstockexchange.com/indices/ftse-250/constituents/table) | [Wikipedia constituent table](https://en.wikipedia.org/wiki/FTSE_250_Index), then cache |
| India | NIFTY 50 | [NSE Indices CSV](https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv) | NSE Archives, then cache |
| India | NIFTY Next 50 | [NSE Indices CSV](https://www.niftyindices.com/IndexConstituent/ind_niftynext50list.csv) | NSE Archives, then cache |
| India | NIFTY 100 | [NSE Indices CSV](https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv) | NSE Archives, then cache |
| India | NIFTY 200 | [NSE Indices CSV](https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv) | NSE Archives, then cache |
| India | NIFTY 500 | [NSE Indices CSV](https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv) | NSE Archives, then cache |

The official NSE Archives URL is `https://archives.nseindia.com/content/indices/`
plus the same CSV filename. NSE members are retained across published series,
including BE/RR; the provider must not silently turn an index into an EQ-only universe.

**Fragility is explicit:** S&P 500 and Dow use unofficial Wikipedia tables; no stable,
free official machine-readable contract is assumed. Both FTSE sources are HTML and
fragile: the LSE response inspected during implementation was a JavaScript shell,
so Wikipedia is the practical fallback. Nasdaq's website JSON is an official
publisher feed but not a guaranteed API contract; it timed out in a direct probe.
Its fallback is unofficial Wikipedia. All Wikipedia sources may lag official
changes. The UI identifies an unofficial source and preferred-source failure.
NSE endpoints are official but can time out or block automated clients; no anti-bot
bypass or certificate-verification override is used.

Live retrieval means fetched now, not independently certified current membership.
The timestamp is retrieval time in UTC, not the publisher's effective/rebalance date.
Local parser probes accepted 503 S&P members, 30 Dow members, 101 Nasdaq members
(from its Wikipedia fallback), 100/250 FTSE members, and 50/50/100/200/501 NIFTY
members. These are observations, not embedded constituent lists or test expectations.
They do not establish Yahoo price availability or successful full live scans.

## Yahoo normalization

- US symbols are trimmed/uppercased; share-class dot notation becomes a hyphen:
  `AAPL → AAPL`, `BRK.B → BRK-B`, `BF.A → BF-A`.
- LSE symbols receive `.L`. Terminal punctuation is removed (`NG. → NG.L`,
  `BP. → BP.L`, `RR. → RR.L`); internal share-class dots become hyphens
  (`BT.A → BT-A.L`). `AZN → AZN.L`, `SHEL → SHEL.L`, `3IN → 3IN.L`.
- NSE symbols receive `.NS`; meaningful ampersands/hyphens survive:
  `RELIANCE → RELIANCE.NS`, `TCS → TCS.NS`, `INFY → INFY.NS`, `M&M → M&M.NS`.
- Already-normalized exchange suffixes are idempotent. BSE normalization supports
  `.BO` for future adapters, but no BSE index is offered.
- Raw symbols are retained separately. Blank/invalid symbols and missing names
  are removed, with counts; duplicates are removed after normalization.
- Upload CSV retains its existing validation semantics. Supply Yahoo-compatible
  symbols and choose its explicit benchmark; CLI CSV handling is unchanged.

## Benchmark review

Each index definition supplies its benchmark symbol and display name:

| Selected universe | Benchmark |
| --- | --- |
| S&P 500 | SPY |
| Nasdaq-100 | ^NDX |
| Dow Jones Industrial Average | ^DJI |
| FTSE 100 | ^FTSE |
| FTSE 250 | ^FTMC |
| NIFTY 50 | ^NSEI |
| NIFTY Next 50 | ^NSEI |
| NIFTY 100 | ^NSEI |
| NIFTY 200 | ^NSEI |
| NIFTY 500 | ^NSEI |

For Web V1, all five Indian universes intentionally use NIFTY 50 as their common
Indian-market benchmark. This does not represent the exact selected index for
Next 50/100/200/500. Completed-scan metadata retains both the symbol and display
name, separately from the selected universe. For example, the UI shows
`Selected universe: NIFTY 500` and `Relative-strength benchmark: NIFTY 50 (^NSEI)`.
Changing the selection without scanning preserves this completed-scan metadata.
Automated tests use offline fixtures; they do not establish live Yahoo availability.

The benchmark is used by `RelativeStrengthEngine` to compare recent returns; its
score contributes to opportunity ranking. Market regime uses the individual stock's
EMA/ADX data, not benchmark indicators. Changing the benchmark input can therefore
change relative-strength and opportunity scores; formulas, thresholds,
strategy decisions, risk calculations and position sizing are untouched.
The existing positional 60-bar comparison is unchanged; no new calendar alignment
or currency conversion was introduced. Custom uploads default to SPY but expose
SPY/^FTSE/^NSEI selection. CLI scans still default to SPY.

All benchmarks and constituent prices use the existing `MarketDataManager` and
hardened yfinance download path. Worker limits, retries, cleanup, price-cache
lifecycle, infrastructure failures and SSL verification are unchanged. Benchmark
preflight still stops the universe download if benchmark data is unavailable.

## Cache and counts

Each index has a separate versioned JSON file under
`AUTOT_DATA_DIR/universe_cache` (default `data_storage/universe_cache`). Optional
`UNIVERSE_CACHE_DIR` overrides that directory; relative paths use the project root,
not cwd. The broad-US Nasdaq Trader cache remains separate and unchanged.

A validated cache younger than 24 hours avoids a fetch. At expiry, the provider
tries configured online sources in order. Successful validation writes an atomic
replacement. If every source fails, a valid stale cache is used with a visible
warning, original source and original retrieval time; its age is never reset.
Without live data or a valid cache, scanning fails clearly. No unrelated list is
substituted. A cache-write failure preserves the live result and exposes a diagnostic.

Validation checks schema, symbol/name format, normalized uniqueness, source identity,
index identity, counts and timestamps. Cache reads revalidate raw records and
normalization. A 95%-110% size envelope accommodates modest membership transitions
and multiple classes while rejecting empty/error pages and typical pagination.
Nasdaq also checks its advertised total when present. This is a plausibility guard,
not proof of exact membership; source changes still require maintenance.

Completed scans show country/index, source, UTC retrieval time, Live/Cache/Stale
status, constituents fetched (validated unique symbols), usable market data,
successfully analysed, skipped/failed and trade opportunities. All counts come from
provider/scanner outputs. Raw row/filter/duplicate counts remain in metadata.
Changing controls does not relabel or rerun a completed scan.

## Exact manual Streamlit checks

1. From a terminal (the implementation does not start a server automatically):

   ```sh
   cd /path/to/AutoT
   source venv/bin/activate
   python -m streamlit run web_app.py
   ```

2. Open the URL printed by Streamlit. Confirm **Universe mode = Market Index**,
   **Market = United States**, **Index = S&P 500**, and no CSV/path control.
3. Change Market to **United Kingdom** and confirm only **FTSE 100 / FTSE 250**.
   Change to **India** and confirm all five NIFTY choices. Return to United States
   and confirm S&P 500 / Nasdaq-100 / Dow Jones Industrial Average.
4. Choose **India → NIFTY 50**, set period **1y**, interval **1d**, top stocks **10**,
   then **Run Scan**. Confirm `.NS` symbols, country/index, actual source, UTC fetch
   time, status and benchmark **^NSEI**. Check that analysed + skipped = constituents,
   usable data does not exceed constituents, and opportunities do not exceed analysed.
   Yahoo/source failures must be reported rather than replaced with another list.
5. Run the same scan again within 24 hours. Constituent status should be **Cache**
   with the same fetched timestamp. Price downloads retain their existing behavior.
6. Change Market/Index without pressing Run Scan. Confirm completed results still
   say **India / NIFTY 50** and persist. Run **UK → FTSE 100** and check `.L` symbols
   and **^FTSE**, then **US → Dow Jones Industrial Average** and check **^DJI**.
   Source fallback/unofficial notices should be visible beneath source metadata.
7. Create a local file `upload.csv` containing `symbol` on the first line, `AAPL`
   on the second and `MSFT` on the third. Choose **Upload CSV**, benchmark **SPY**,
   select that file in the browser and Run Scan. Confirm the two-symbol universe.
   Change controls afterward and confirm its results persist.
8. Upload a file headed `ticker` instead of `symbol`; confirm validation blocks
   the scan. Switch back to Market Index and confirm no upload is required.
9. Stop the server with **Ctrl-C**. Offline automated tests cover stale fallback,
   total failure, corruption, partial responses and cache-write failure without
   needing to interfere with network access during a manual price-data scan.
