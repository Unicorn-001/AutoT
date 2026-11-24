"""Streamlit entry point for the AutoT scanner."""

import logging

import streamlit as st

# Apply before application imports as well as runtime initialization failures.
st.set_option("client.showErrorDetails", "none")

from autot.application.scan_display import render_scan_results, render_scan_status
from autot.application.real_trade_journal_display import render_real_trade_journal
from autot.application.paper_display import render_paper_dashboard, render_opportunity_actions
from autot.settings.configuration_manager import ConfigurationManager
from autot.settings.store import SettingsStore
from autot.application.settings_display import render_settings
from autot.runtime import initialize_runtime
from autot.universe.index_definitions import COUNTRIES, INDICES, indices_for_country, normalize_country_index_selection
from autot.universe.providers import UploadedCSVProvider


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
    workspace = st.radio("Workspace", ["Scanner", "Paper Trading", "Broker / eToro Demo", "Real Trade Journal", "Settings", "System Health / Status"], horizontal=True)
    if workspace == 'Broker / eToro Demo':
        from autot.application.broker_display import render_broker
        render_broker()
        return
    if workspace == "System Health / Status":
        from autot.application.system_health_display import render_system_health
        render_system_health()
        return
    render_scan_status()
    if workspace == "Real Trade Journal":
        render_real_trade_journal()
        return
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

        if source == "Upload CSV":
            if uploaded is None:
                st.error("Upload a CSV with a symbol column before running the scan.")
                return
            try:
                # Validate before submitting; only safe,
                # fixed validation messages from this provider reach the browser.
                UploadedCSVProvider(uploaded.getvalue()).load()
            except ValueError as error:
                st.error(str(error))
                return

        from autot.daily_scanner import launch, request_from_state
        request = request_from_state(active)
        request.update(settings)
        request['market'] = definition.market if definition else {'SPY': 'US', '^FTSE': 'UK', '^NSEI': 'IN'}[benchmark_symbol]
        if uploaded is not None:
            request['csv'] = uploaded.getvalue().decode('utf-8-sig')
        try:
            launch(request)
        except Exception:
            LOGGER.exception('Unable to launch scan')
            st.error('Unable to start scan. A scan may already be running; check scanner status.')
        else:
            st.rerun()

    from autot.application.scan_store import ScanStore
    st.button('Refresh scan status/results')
    persisted = ScanStore().latest()
    if persisted is not None:
        st.session_state['scan'] = persisted
        st.caption(f"Displayed results completed: {persisted.get('completed_at', 'Unknown')}")

    saved = st.session_state.get("scan")
    if saved is None:
        return
    render_scan_results(saved)
    render_opportunity_actions(saved)


if __name__ == "__main__":
    main()
