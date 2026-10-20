# AutoT

## Local web scanner

From the project root, activate the existing virtual environment and install dependencies:

```sh
source venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run web_app.py
```

The web scanner uses optional settings from `data_storage/config/app_settings.csv`,
with scan defaults when that file is absent. **Market Index** is the default: choose
**Market**, then **Index**, period, interval and shortlist size,
then select **Run Scan**. Results remain in the current browser session until the next scan.
Ranked results, the top shortlist and trade opportunities come from the shared scanner service.
The web app does not execute real trades or write CLI reports. The CLI remains available with
`python main.py`.

The separate **Paper Trading** workspace records prospective simulated trades from
completed daily opportunities, with durable pending entries and manual 5-minute
position updates. It never connects a real broker. See [Paper Trading V1](PAPER_TRADING.md)
for execution rules, currency handling, calendar limitations and manual checks.

See [deployment readiness and local verification](DEPLOYMENT.md) for writable storage,
certificate setup, uploads, dependency observations, and private-access assumptions.

The scanner fetches current index members online; no CSV selection or server path is
required. **Upload CSV** remains an optional custom mode with a benchmark selector.
See [index sources, normalization, cache policy and manual checks](INDEX_UNIVERSES.md).

Supported markets: United States (S&P 500, Nasdaq-100, Dow Jones Industrial Average),
United Kingdom (FTSE 100, FTSE 250), and India (NIFTY 50, NIFTY Next 50, NIFTY 100,
NIFTY 200, NIFTY 500). Completed results retain the market/index, source, fetch time,
cache status, constituent count, usable-data count, analysed/skipped counts and opportunities.

Reusable usage: inject `ProviderUniverseLoader(IndexUniverseProvider("nifty50"))`
as `universe_loader` into `run_scan()`, with `benchmark_symbol="^NSEI"`.
The scanner receives Yahoo symbols and knows nothing about websites. The legacy
Nasdaq Trader broad-US provider and CLI `CustomCSVProvider(path)` remain available.
Bundled `autot/universe/...` paths resolve from the app; other relative CLI custom paths
retain their working-directory semantics.

Yahoo downloads keep yfinance's persistent timezone, cookie and ISIN caches in
`data_storage/yfinance_cache`, resolved from the project directory for both CLI and
Streamlit. AutoT creates this ignored directory and initializes the databases once
before download workers start, using yfinance's supported cache-location API.
This avoids dependence on writable access to the user-level `py-yfinance` cache.
SQLite WAL and Peewee's thread-local connections remain enabled. Cache setup errors
include the absolute location in developer diagnostics and stop before downloading, rather than silently
disabling caching or reporting the problem as missing stock prices.
The browser shows a safe error and directs the operator to server logs.
Restart an already-running Streamlit server after installing this change so its
yfinance caches are configured before their first use.

Both CLI and Streamlit use `YAHOO_DOWNLOAD_WORKERS = 4` in
`autot/market_data/yfinance_download.py`. AutoT owns a bounded executor and
reuses its workers and one curl_cffi session across batches. Each worker downloads
one ticker through public `yf.download(threads=False)`, then closes its own
Peewee cache connections in `finally`. Worker curl handles are explicitly closed
before executor shutdown. Top-level AutoT download operations are serialized so
concurrent scans cannot exceed four active downloads or replace each other's
singleton Yahoo session. The later analysis executor is independent.

yfinance has no documented public cache-close API. The adapter in
`autot/market_data/yfinance_cache.py` confines cache-layout access to one module,
checks the pinned yfinance 1.4.1/Peewee 4.0.8 versions and expected databases,
and refuses downloads if those checks fail. Dependency upgrades require adapter
validation. It closes connections with Peewee's public `close()` API; it does
not monkeypatch yfinance, reset caches, or disable caching/SSL verification.

The selected benchmark (SPY by default for CLI scans) is downloaded and validated before universe prices. Recognized DNS, SQLite,
TLS, timeout and rate-limit failures stop downloads without individual retry
fan-out. A batch with at least four insufficient datasets and at least half
its symbols unavailable also stops with the cause marked unverified. Isolated
insufficient data gets one retry; it is never classified as delisted by AutoT.
Infrastructure exceptions retain usable datasets in `partial_data` for explicit
recovery; the scanner reports failure rather than silently ranking partial data.
These lifecycle changes address demonstrated resource retention; the earlier
fatal Streamlit failure has not yet been conclusively reproduced.
