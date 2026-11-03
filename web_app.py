"""Streamlit entry point for the AutoT scanner."""

import logging
from dataclasses import asdict

import streamlit as st

# Apply before application imports as well as runtime initialization failures.
st.set_option("client.showErrorDetails", "none")

from autot.application.scanner_service import run_scan
from autot.application.scan_display import render_scan_results
from autot.application.paper_display import render_paper_dashboard, render_opportunity_actions
from autot.paper_trade.scan_context import observe_analysis
from autot.market_data.market_data_manager import MarketDataManager
from autot.performance.performance_tracker import PerformanceTracker
from autot.settings.configuration_manager import ConfigurationManager
from autot.settings.store import SettingsStore
from autot.application.settings_display import render_settings
from autot.runtime import initialize_runtime
from autot.universe.index_definitions import COUNTRIES, INDICES, indices_for_country, normalize_country_index_selection
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
    except (OSError, ValueError, KeyError):
        LOGGER.exception("Unable to initialize AutoT runtime/configuration")
        st.error("Unable to initialize AutoT. Ask the operator to check configuration and AUTOT_DATA_DIR permissions; details are in the server logs.")
        return

    store = SettingsStore()
    active = store.load()
    if store.warning:
        st.warning(store.warning)
    workspace = st.radio("Workspace", ["Scanner", "Paper Trading", "Settings"], horizontal=True)
    if workspace == 'Settings':
        render_settings()
        return
    if workspace == "Paper Trading":
        render_paper_dashboard()
        return

    source = st.selectbox("Universe mode", ["Market Index", "Upload CSV"], key="universe_mode")
    definition = None
    benchmark_symbol = "SPY"
    if source == "Market Index":
        country = st.selectbox("Market", COUNTRIES, index=list(COUNTRIES).index(active.settings.scanner.country), key="market")
        choices = [d.index_id for d in indices_for_country(country)]
        selected_index = normalize_country_index_selection(
            country, st.session_state.get('scanner_index', active.settings.scanner.index))
        if 'scanner_index' in st.session_state and st.session_state['scanner_index'] != selected_index:
            st.session_state['scanner_index'] = selected_index
        index_id = st.selectbox(
            "Index", choices, index=choices.index(selected_index),
            format_func=lambda value: INDICES[value].index_name, key="scanner_index",
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
        period = st.text_input("Backtest period", value=active.settings.scanner.history_period)
        interval = st.text_input("Interval", value=active.settings.scanner.interval)
        top_n = st.number_input("Number of top stocks", min_value=1, value=active.settings.scanner.top_ranked_count, step=1)
        submitted = st.form_submit_button("Run Scan")

    if submitted:
        if store.warning:
            st.error("Resolve the settings warning in Settings before starting a new scan.")
            return
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
        paper_signal_context = {}

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
                analyse_func=observe_analysis(analyse_stock, paper_signal_context, interval=settings["interval"],
                                              market=definition.market if definition else None),
                universe_loader=universe_loader,
                batch_data_loader=MarketDataManager.get_batch_stock_data,
                benchmark_data_loader=MarketDataManager.get_stock_data,
                on_success=on_success,
                on_error=on_error,
                on_stage=on_stage,
                diagnostics=diagnostics,
                settings_state=active,
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
                                    "diagnostics": diagnostics, "universe_metadata": metadata,
                                    "paper_signal_context": paper_signal_context, "settings_state": active.model_dump(mode="json")}

    saved = st.session_state.get("scan")
    if saved is None:
        return
    render_scan_results(saved)
    render_opportunity_actions(saved)


if __name__ == "__main__":
    main()
