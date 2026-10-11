# AutoT

## Local web scanner

From the project root, activate the existing virtual environment and install dependencies:

```sh
source venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run web_app.py
```

The web scanner uses defaults from `data_storage/config/app_settings.csv`.
Choose **Online US Stocks** or **Custom CSV** (the existing default), period, interval and shortlist size,
then select **Run Scan**. Results remain in the current browser session until the next scan.
Ranked results, the top shortlist and trade opportunities come from the shared scanner service.
The web app does not execute trades or write CLI reports. The CLI remains available with
`python main.py`.

Online US Stocks combines Nasdaq Trader's official HTTPS
[nasdaqlisted.txt](https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt) and
[otherlisted.txt](https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt), using the
[Symbol Directory definitions](https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs).
It removes footer rows, malformed/blank symbols, ETFs, test issues and known non-normal
Nasdaq financial-status codes (D/E/Q/G/H/J/K). It also excludes clearly identified
warrants, bundled units, rights, preferred/preference securities (including depositary
preferred shares), and debt securities such as notes, bonds and debentures.
Rules use documented ACT/CQS suffixes and explicit security-description phrases;
an issuer name containing words such as Preferred, Bond or Rights is not sufficient.
Common/ordinary shares, equity ADRs, REIT/trust common shares and partnership common
units remain eligible. Nasdaq ticker endings W/U/R alone are never treated as security types.
See [Nasdaq's symbol conventions](https://www.nasdaqtrader.com/trader.aspx?id=CQSsymbolconvention).
Class A/B dot notation becomes Yahoo hyphen notation (BRK.B → BRK-B, BF.A → BF-A).
Other suffixes remain unchanged rather than guessing Yahoo equivalents; some of those
securities may have no usable Yahoo price data and follow the existing scanner skip behavior.

The separate JSON universe cache lives at `data_storage/universe_cache` relative to the
project directory, independent of the process working directory. Set optional
`UNIVERSE_CACHE_DIR` in the settings CSV to override it (relative paths use the project root).
A fresh cache avoids downloads for 24 hours. Refresh failure uses a validated older cache
and logs a warning; without a usable cache the provider raises a clear error. Each successful
refresh atomically replaces the cache only after both files parse successfully.
Cache schema version 2 invalidates earlier caches that included non-common-equity securities.
Provider results retain source/normalized symbol pairs, security names and counts for downloaded rows
(including footers), filtered rows, duplicates and final symbols, plus cache/stale flags.
These diagnostics are logged; the UI shows the symbol count.

Reusable usage with the existing scanner: inject
`ProviderUniverseLoader(NasdaqTraderProvider())` as `universe_loader` into `run_scan()`.
`CustomCSVProvider(path)` wraps the unchanged CSV loader; existing CLI/CSV calls still work.

Yahoo downloads keep yfinance's persistent timezone, cookie and ISIN caches in
`data_storage/yfinance_cache`, resolved from the project directory for both CLI and
Streamlit. AutoT creates this ignored directory and initializes the databases once
before download workers start, using yfinance's supported cache-location API.
This avoids dependence on writable access to the user-level `py-yfinance` cache.
SQLite WAL and Peewee's thread-local connections remain enabled. Cache setup errors
include the absolute location and stop before downloading, rather than silently
disabling caching or reporting the problem as missing stock prices.
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

SPY is downloaded and validated before universe prices. Recognized DNS, SQLite,
TLS, timeout and rate-limit failures stop downloads without individual retry
fan-out. A batch with at least four insufficient datasets and at least half
its symbols unavailable also stops with the cause marked unverified. Isolated
insufficient data gets one retry; it is never classified as delisted by AutoT.
Infrastructure exceptions retain usable datasets in `partial_data` for explicit
recovery; the scanner reports failure rather than silently ranking partial data.
These lifecycle changes address demonstrated resource retention; the earlier
fatal Streamlit failure has not yet been conclusively reproduced.
