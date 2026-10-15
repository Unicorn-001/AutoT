"""Streamlit entry point for the AutoT scanner."""

import logging
from dataclasses import asdict

import streamlit as st

# Apply before application imports as well as runtime initialization failures.
st.set_option("client.showErrorDetails", "none")

from autot.application.scanner_service import run_scan
from autot.application.scan_display import render_scan_results
from autot.market_data.market_data_manager import MarketDataManager
from autot.performance.performance_tracker import PerformanceTracker
from autot.settings.configuration_manager import ConfigurationManager
from autot.runtime import initialize_runtime
from autot.universe.index_definitions import COUNTRIES, INDICES, indices_for_country
from autot.universe.index_provider import IndexUniverseProvider
from autot.universe.nasdaq_provider import UniverseLoadError
from autot.universe.providers import ProviderUniverseLoader, UploadedCSVProvider
from main import analyse_stock


LOGGER = logging.getLogger(__name__)


def main():
    st.set_page_config(page_title="AutoT", layout="wide")
    st.title("AutoT")
    st.caption("Scan stocks and review ranked results and trade opportunities.")

    try:
        initialize_runtime()
        config = ConfigurationManager()
        default_top_n = max(1, config.get_int("TOP_N_STOCKS", 10))
    except (OSError, ValueError, KeyError):
        LOGGER.exception("Unable to initialize AutoT runtime/configuration")
        st.error("Unable to initialize AutoT. Ask the operator to check configuration and AUTOT_DATA_DIR permissions; details are in the server logs.")
        return

    source = st.selectbox("Universe mode", ["Market Index", "Upload CSV"], key="universe_mode")
    definition = None
    benchmark_symbol = "SPY"
    if source == "Market Index":
        country = st.selectbox("Market", COUNTRIES, key="market")
        index_id = st.selectbox(
            "Index", [d.index_id for d in indices_for_country(country)],
            format_func=lambda value: INDICES[value].index_name, key=f"index_{country}",
        )
        definition = INDICES[index_id]
        benchmark_symbol = definition.benchmark_symbol
    else:
        benchmark_symbol = st.selectbox(
            "Benchmark", ["SPY", "^FTSE", "^NSEI"], key="custom_benchmark",
            help="Choose the benchmark for your custom universe. Supply Yahoo-compatible tickers in the CSV.",
        )
    with st.form("scan_settings"):
        uploaded = None
        if source == "Upload CSV":
            uploaded = st.file_uploader(
                "Universe CSV", type=["csv"], max_upload_size=1,
                help="UTF-8 CSV with a symbol column; up to 1 MB and 10,000 symbols. Processed in memory.",
            )
        period = st.text_input("Backtest period", value=config.get_string("BACKTEST_PERIOD"))
        interval = st.text_input("Interval", value=config.get_string("BACKTEST_INTERVAL"))
        top_n = st.number_input("Number of top stocks", min_value=1, value=default_top_n, step=1)
        submitted = st.form_submit_button("Run Scan")

    if submitted:
        settings = {
            "universe": definition.index_id if definition else source, "period": period.strip(),
            "interval": interval.strip(), "top_n": int(top_n), "benchmark_symbol": benchmark_symbol,
        }
        if not all(settings[key] for key in ("period", "interval")):
            st.error("Enter a backtest period and interval.")
            return

        universe_loader = None
        if source == "Upload CSV":
            if uploaded is None:
                st.error("Upload a CSV with a symbol column before running the scan.")
                return
            try:
                # Validate before clearing the last completed scan; only safe,
                # fixed validation messages from this provider reach the browser.
                result = UploadedCSVProvider(uploaded.getvalue()).load()
            except ValueError as error:
                st.error(str(error))
                return
            universe_loader = ProviderUniverseLoader(UploadedCSVProvider(uploaded.getvalue()))

        st.session_state.pop("scan", None)
        status = st.empty()
        loaded = st.empty()
        progress = st.progress(0.0)
        errors = []
        diagnostics = {}

        def on_stage(stage, details):
            messages = {
                "loading_universe": "Loading universe…",
                "loading_market_data": "Downloading market data…",
                "analysing": "Analysing stocks…",
                "ranking": "Ranking results…",
            }
            if stage == "universe_loaded":
                loaded.info(f"Loaded {details['count']} symbols")
            elif stage in messages:
                status.info(messages[stage])

        def on_success(count, total, symbol):
            progress.progress((count + len(errors)) / total if total else 0.0)
            status.info(f"Completed {count} / {total}: {symbol}")

        def on_error(symbol, error):
            LOGGER.error("Analysis failed for %s", symbol, exc_info=(type(error), error, error.__traceback__))
            errors.append(f"{symbol}: Analysis failed; see server logs.")

        try:
            if definition:
                universe_loader = ProviderUniverseLoader(IndexUniverseProvider(
                    definition.index_id,
                    cache_dir=config.get_string("UNIVERSE_CACHE_DIR") or None,
                ))
            scan = run_scan(
                **settings,
                tracker=PerformanceTracker(),
                analyse_func=analyse_stock,
                universe_loader=universe_loader,
                batch_data_loader=MarketDataManager.get_batch_stock_data,
                benchmark_data_loader=MarketDataManager.get_stock_data,
                on_success=on_success,
                on_error=on_error,
                on_stage=on_stage,
                diagnostics=diagnostics,
            )
        except UniverseLoadError:
            LOGGER.exception("AutoT universe unavailable")
            status.error("Unable to fetch the selected index constituents and no valid cached list is available. Check connectivity or choose Upload CSV.")
            progress.empty()
            return
        except Exception:
            LOGGER.exception("AutoT scan failed")
            status.error("Scan failed. Check the universe source, market-data settings and server logs.")
            progress.empty()
            for message in errors:
                st.warning(f"Analysis failed for {message}")
            return

        progress.progress(1.0)
        status.success("Scan complete")
        loaded.empty()
        for failure in diagnostics.get("failures", []):
            if failure["reason"] != "No usable market data returned; cause unverified":
                failure["reason"] = "Analysis failed; see server logs."
        metadata = asdict(universe_loader.result) if universe_loader.result else {}
        metadata.update(
            benchmark_symbol=settings["benchmark_symbol"],
            benchmark_display_name=definition.benchmark_display_name if definition else "",
        )
        st.session_state["scan"] = {"outputs": scan, "settings": settings, "errors": errors,
                                    "diagnostics": diagnostics, "universe_metadata": metadata}

    saved = st.session_state.get("scan")
    if saved is None:
        return
    render_scan_results(saved)


if __name__ == "__main__":
    main()
