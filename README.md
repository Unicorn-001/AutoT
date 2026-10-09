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
