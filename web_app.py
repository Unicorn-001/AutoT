"""Local Streamlit entry point for the AutoT scanner."""

import pandas as pd
import streamlit as st

from autot.application.scanner_service import run_scan
from autot.market_data.market_data_manager import MarketDataManager
from autot.performance.performance_tracker import PerformanceTracker
from autot.settings.configuration_manager import ConfigurationManager
from autot.universe.universe_loader import load_universe
from autot.universe.nasdaq_provider import NasdaqTraderProvider
from autot.universe.providers import ProviderUniverseLoader
from main import analyse_stock


def main():
    st.set_page_config(page_title="AutoT", layout="wide")
    st.title("AutoT")
    st.caption("Scan stocks and review ranked results and trade opportunities.")

    try:
        config = ConfigurationManager()
        default_top_n = max(1, config.get_int("TOP_N_STOCKS", 10))
    except (OSError, ValueError, KeyError) as error:
        st.error(f"Unable to load configuration: {error}")
        return

    source = st.selectbox("Universe source", ["Online US Stocks", "Custom CSV"], index=1)
    with st.form("scan_settings"):
        universe = "Online US Stocks"
        if source == "Custom CSV":
            universe = st.text_input(
                "Universe CSV", value=config.get_string("ACTIVE_UNIVERSE"),
                help="Path to a CSV containing a symbol column, relative to the project root.",
            )
        period = st.text_input("Backtest period", value=config.get_string("BACKTEST_PERIOD"))
        interval = st.text_input("Interval", value=config.get_string("BACKTEST_INTERVAL"))
        top_n = st.number_input("Number of top stocks", min_value=1, value=default_top_n, step=1)
        submitted = st.form_submit_button("Run Scan")

    if submitted:
        settings = {
            "universe": universe.strip(), "period": period.strip(),
            "interval": interval.strip(), "top_n": int(top_n),
        }
        if not all(settings[key] for key in ("universe", "period", "interval")):
            st.error("Enter a universe CSV, backtest period and interval.")
            return

        st.session_state.pop("scan", None)
        status = st.empty()
        loaded = st.empty()
        progress = st.progress(0.0)
        errors = []

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
            errors.append(f"{symbol}: {error}")

        try:
            universe_loader = load_universe
            if source == "Online US Stocks":
                universe_loader = ProviderUniverseLoader(NasdaqTraderProvider(
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
            )
        except Exception as error:
            status.error(f"Scan failed: {error}. Check the universe source and market-data settings.")
            progress.empty()
            for message in errors:
                st.warning(f"Analysis failed for {message}")
            return

        progress.progress(1.0)
        status.success("Scan complete")
        loaded.empty()
        st.session_state["scan"] = {"outputs": scan, "settings": settings, "errors": errors}

    saved = st.session_state.get("scan")
    if saved is None:
        return
    scan = saved["outputs"]
    settings = saved["settings"]
    st.caption(
        f"Results for {settings['universe']} · {settings['period']} · {settings['interval']}"
    )
    st.metric("Symbols loaded", len(scan["symbols"]))
    st.caption(f"Successfully analysed {len(scan['results'])} / {len(scan['symbols'])} symbols")
    for message in saved["errors"]:
        st.warning(f"Analysis failed for {message}")
    if len(scan["results"]) < len(scan["symbols"]):
        st.warning("Some symbols were skipped or failed analysis; results are partial.")

    st.subheader("Ranked Results")
    if scan["ranked_results"]:
        st.dataframe(pd.DataFrame(scan["ranked_results"]), hide_index=True)
        st.subheader(f"Top {settings['top_n']} Stocks")
        st.dataframe(pd.DataFrame(scan["top_results"]), hide_index=True)
    else:
        st.info("No stocks were successfully analysed.")

    st.divider()
    st.subheader("Trade Opportunities")
    if scan["trade_opportunities"]:
        st.dataframe(pd.DataFrame(scan["trade_opportunities"]), hide_index=True)
    else:
        st.info("No actionable BUY or SELL opportunities in this scan.")


if __name__ == "__main__":
    main()
