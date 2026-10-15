# Web V1 deployment readiness

No deployment or authentication is configured by this change. The deployment target
must supply private access, TLS termination, and a writable data directory when the
checkout is read-only. Do not expose this scanner as an unauthenticated public service.

## Runtime paths and storage

`AUTOT_DATA_DIR` is the only new AutoT environment variable. It is optional; the default
is `data_storage` under the application directory, resolved using the installed source
location, not the shell's working directory. Relative overrides also resolve from that
directory; absolute overrides can point outside the checkout. Set it before starting
Python and restart the server to change it: Yahoo caches are initialized once per process.

For a read-only checkout, set `AUTOT_DATA_DIR` to a writable host-provided directory.
An ephemeral directory is sufficient for Web V1. There is deliberately no silent fallback
to a second storage root if permissions are wrong. Startup probes actual write access
and shows a safe operator-facing error if initialization fails.

| Location under data root | Use |
| --- | --- |
| `yfinance_cache/` | SQLite timezone, cookie and ISIN databases; WAL/SHM sidecars |
| `universe_cache/` | Nasdaq JSON cache and temporary files for atomic replacement |
| `config/app_settings.csv` | Optional operator-provided settings; read only by AutoT |
| `processed/` and `processed/history/` | CLI scan report exports only; not written by the web app |

Web startup creates the data root and the two cache directories. It opens and removes
a temporary probe file in each to verify writability. A scan writes only the caches.
Existing `UNIVERSE_CACHE_DIR` settings can still override the Nasdaq cache separately;
relative values resolve from the application directory. The provider creates that
directory on use. Avoid carrying an old override into a host where it is not writable.

The Nasdaq provider keeps its existing filtering, 24-hour TTL and validated stale-cache
fallback. Deleting ephemeral data loses caches; it does not lose a Web V1 portfolio,
because the web scanner does not execute or persist trades. No stale fallback exists
after the cached file has been lost. Yahoo cache contents include cookies: treat the
data root as private runtime data and exclude it from deployment bundles/backups shared
with others. Use local disk suitable for SQLite WAL, not a shared network filesystem.

Completed results live in Streamlit session state and survive normal widget reruns.
They are not durable across process restarts or a lost browser session. Multiple server
replicas do not share session results; session routing is the host's responsibility.

The CLI's existing **paper-trading** persistence under `data_storage/processed` and its
working-directory semantics are deliberately unchanged. `AUTOT_DATA_DIR` relocates scan
caches, settings and scan reports, not paper portfolios/journals. Continue running the
paper-trading CLI from the project root with persistent storage. Deploying that workflow
would require a separate persistence review; it is outside Web V1 readiness.

## Configuration and certificates

A fresh checkout no longer needs an ignored local settings CSV to start. Defaults are
Market Index / United States / S&P 500 in the browser, `5y`, `1d`, and top `10`.
The CLI retains its built-in CSV default. An existing settings CSV under the
selected data root takes precedence unchanged. A missing explicitly requested settings
file still raises an error. Trading configuration/constants are not changed.

Before network use, AutoT initializes `SSL_CERT_FILE`, `CURL_CA_BUNDLE`, and
`REQUESTS_CA_BUNDLE` from `certifi.where()` **only when none of those variables or
`SSL_CERT_DIR` is already present**. If any is supplied, including an empty value,
AutoT leaves the entire CA configuration untouched. This avoids inserting a new variable
that could shadow a deliberate fallback or a corporate trust store. In that case the
operator must ensure their configuration covers each library they use. No verification
is disabled, and no Homebrew/macOS certificate path is embedded in the application.

This matches the trust controls exposed by [Requests](https://docs.python-requests.org/en/latest/user/advanced/#ssl-cert-verification)
and [curl_cffi](https://curl-cffi.readthedocs.io/en/latest/_modules/curl_cffi/requests/session.html).
An invalid explicit CA path is not silently replaced; inspect protected server logs.

## Browser universes

- **Market Index** (default): United States, United Kingdom or India, then a supported
  index. Online constituents, actual source and cache status are retained with results.
  See [index universe details](INDEX_UNIVERSES.md) for sources and limitations.
- **Upload CSV:** UTF-8 (optional BOM), required `symbol` column, at most 1 MB and
  10,000 symbols. Tickers are trimmed and uppercased; ordering and duplicates are
  retained. Empty/malformed files, blank/invalid tickers and excessive uploads are
  rejected before starting a scan. The filename is never interpreted as a server path.

Streamlit supplies [uploaded files in memory](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader).
AutoT parses the bytes without writing an upload file. Only the selected symbol list
enters the shared scanner. Browser users no longer select arbitrary server paths.
CLI `CustomCSVProvider` and arbitrary absolute/relative custom CSV paths still work;
bundled `autot/universe/...` paths now resolve relative to the app.

## Access, errors and secrets

Use an authenticated hosting platform, private network or authenticated reverse proxy
before remote exposure. Restrict concurrent access and request/upload sizes at the host
as appropriate: each scan consumes CPU and third-party network capacity. Keep Streamlit's
normal CORS/XSRF protections enabled. No hostname or port is hardcoded by AutoT.

Browser errors do not include raw configuration, filesystem or scan exceptions.
Per-symbol failures retain counts and symbols, with detailed failure information in
server logs. Unexpected Streamlit error details are disabled in the browser. Server
logs retain traceback diagnostics and may contain sensitive paths or upstream values;
restrict log access. Do not enable detailed browser errors on a public host.

The web scanner needs no broker credentials. Do not include a developer `.env`, virtual
environment, data directory or secrets file in the deployment image. The current working
tree scan found no likely non-placeholder secrets or private URLs in inspected source
and local environment configuration. The local ignored environment file contains a
placeholder candidate. This is a heuristic current-files scan, not a guarantee about
historical commits or external logs. If real credentials are ever committed, revoke/rotate
them and clean history before distribution.

Ignore rules cover `data_storage`, `.env` variants (except a deliberate `.env.example`),
`.streamlit/secrets.toml`, virtual environments, Python/pytest caches, logs and `uploads`.
An externally configured data root needs equivalent host-level exclusion and permissions.
No intentionally tracked file was removed.

## Dependencies and remaining host checks

`requirements.txt` is a broad pinned development environment. Direct scanner runtime
imports include Streamlit, pandas, numpy, ta, yfinance, curl_cffi, peewee, certifi,
requests and packaging, with their transitive dependencies. Alpaca and python-dotenv
support separate broker code; they are not needed by the Web V1 scan path. Notebook,
Jupyter, IPython, widgets and debugpy are development tooling. Matplotlib is not imported
by the current scanner. Pytest is needed for validation but is not in requirements.txt.

Recommend a separately reviewed runtime/development requirements split. This change only
adds a Darwin marker to `appnope`, the macOS-specific dependency. It does not repin or
remove other packages. Keep yfinance `1.4.1` and peewee `4.0.8`: the existing cache adapter
intentionally checks those versions. Native packages such as curl_cffi/numpy/pandas need
wheels compatible with the chosen Python, OS and architecture. Validate installation on
the actual target before deployment; local tests do not prove Linux wheel compatibility.
Validation here uses the existing Python 3.14 environment, not a fresh host installation.

Outbound HTTPS/DNS to the configured index sources (NSE, Nasdaq, LSE, Wikipedia)
and Yahoo must be permitted. A cold cache cannot make
an offline host functional. No live remote server, authentication or target-image install
has been verified by this implementation.

## Manual local verification

In a normal Terminal, from the repository root:

```sh
source venv/bin/activate
python -m streamlit run web_app.py
```

No manual certifi exports are needed in a shell with no deliberate CA overrides. Do not
unset corporate/operator trust settings just to test the defaults. Verify market-index and
upload scans, counts, trade opportunities (`historical_score` and `trade_quality`) and
the qualification explanations. Change a widget or universe source after completion
and confirm results persist without a second scan.

To simulate an external ephemeral data root and a different cwd, stop the first server,
return to the repository root in the activated environment, then run:

```sh
autot_project="$PWD"
autot_python="$autot_project/venv/bin/python"
autot_test_root="$(mktemp -d)"
printf 'Test directory: %s\n' "$autot_test_root"
printf 'symbol\nAAPL\nMSFT\n' > "$autot_test_root/upload.csv"
cd "$autot_test_root"
AUTOT_DATA_DIR="$autot_test_root/runtime" "$autot_python" -m streamlit run "$autot_project/web_app.py"
```

Choose **Upload CSV**, browse to the displayed test directory's `upload.csv`, and run a
scan. Also try a CSV without `symbol` and confirm validation stops it. Inspect the
`runtime` directory: caches should be there, with no permanent upload copy. Stop with
Ctrl-C; the one-command data-root override does not alter subsequent local launches.
The generated test directory may be deleted after the server exits.
