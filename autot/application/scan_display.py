"""Presentation of existing scan outputs; no trading calculations."""

import logging
import sqlite3

import pandas as pd
import streamlit as st
from datetime import datetime, timezone


@st.fragment(run_every="2s")
def render_scan_status():
    """Poll durable worker state without rerunning or blocking the workspace."""
    from autot.daily_scanner import read_status

    try:
        status = read_status()
    except ValueError:
        st.warning('Scanner status unavailable until the settings storage warning is resolved.')
        return
    except (KeyError, TypeError, OSError, sqlite3.Error):
        logging.getLogger(__name__).exception('Unable to read scan status')
        st.warning('Scan status unavailable. Check server logs; you can continue using this workspace.')
        return
    run = status.get('last_run')
    if not run:
        st.caption('Scan status: Idle')
        return

    outcome = run['status']
    phase = run.get('phase')
    labels = {
        'QUEUED': 'Queued / starting', 'SUCCESS': 'Completed',
        'PARTIAL': 'Partial — completed with skipped / failed symbols',
        'FAILED': 'Failed', 'NO_WORK': 'Completed — no symbols to scan',
    }
    phases = {
        'STARTING': 'Starting', 'loading_universe': 'Loading universe',
        'universe_loaded': 'Starting market-data fetch',
        'loading_market_data': 'Fetching market data',
        'analysing': 'Analyzing symbols', 'ranking': 'Ranking / finalizing',
    }
    label = labels.get(outcome, phases.get(phase, 'Starting'))
    active = outcome in ('QUEUED', 'RUNNING')
    with st.status(f'Scan: {label}', expanded=active,
                   state='running' if active else 'error' if outcome == 'FAILED' else 'complete'):
        st.caption(f"{run['trigger_type']} · {run['universe']} · Requested: {run['requested_at']}")
        total = run.get('symbols_total')
        if total is None and not active:
            total = run.get('symbols_fetched')
        analyzed = run.get('symbols_analyzed', 0)
        failed = run.get('symbols_failed', 0)
        if phase == 'loading_market_data' and active:
            processed = run.get('symbols_fetched', 0)
            text = f'Market-data fetch: {processed}'
        else:
            processed = analyzed + failed
            text = f'Symbols processed: {processed}'
        if total is not None:
            text += f' / {total}'
        st.caption(f'{text} · {analyzed} analyzed · {failed} skipped / failed')
        # This measures symbol work in the named phase, never elapsed time or
        # overall completion (ranking/persistence may still be in progress).
        if total and 0 <= processed <= total and phase in ('loading_market_data', 'analysing', 'ranking'):
            st.progress(processed / total, text=text)
        if active:
            st.caption('Updates automatically. You can switch workspaces while the scan runs.')
        elif run.get('completed_at'):
            st.caption(f"Finished: {run['completed_at']}. Refresh scan status/results to load results.")
    if outcome == 'FAILED':
        st.error('Scan failed. Check the universe source, market-data settings and server logs.')


OPPORTUNITY_COLUMNS = [
    "symbol", "signal", "confidence", "agreement", "market_regime",
    "entry_price", "stop_loss", "take_profit", "risk_reward_ratio",
    "historical_score", "trade_quality",
]


def opportunity_table(rows):
    return pd.DataFrame(rows).rename(columns={
        "score": "historical_score",
        "trade_quality_score": "trade_quality",
    }).reindex(columns=OPPORTUNITY_COLUMNS)


def qualification_explanation(row):
    details = []
    if row.get("market_regime") is not None:
        details.append(str(row["market_regime"]).replace("_", " ").capitalize())
    for field, label in (("confidence", "confidence"), ("agreement", "agreement")):
        if row.get(field) is not None:
            details.append(f"{row[field]:.2f}% {label}")
    if row.get("risk_reward_ratio") is not None:
        details.append(f"risk/reward {row['risk_reward_ratio']:.2f}")
    if row.get("trade_quality_score") is not None:
        details.append(f"trade quality {row['trade_quality_score']:.2f} (minimum 70)")
    return f"{row['symbol']} — {row['signal']}: " + (", ".join(details) or "No additional calculated details available") + "."


def render_scan_results(saved):
    scan, settings = saved["outputs"], saved["settings"]
    diagnostics = saved.get("diagnostics", {})
    metadata = saved.get("universe_metadata", {})
    total, analysed = len(scan["symbols"]), len(scan["results"])
    failed = total - analysed
    if metadata.get("index_id"):
        st.write(f"Market: {metadata['country']} · Selected universe: {metadata['index_name']}")
        fetched = datetime.fromtimestamp(metadata["fetched_at"], timezone.utc).strftime("%d %b %Y %H:%M UTC")
        status = "Stale cache" if metadata["stale"] else "Cache (within 24h TTL)" if metadata["cached"] else "Live"
        st.caption(f"Source: {metadata['source']} · Fetched: {fetched} · Status: {status}")
        for warning in metadata.get("warnings", []):
            if metadata["stale"] and "stale cache" in warning:
                st.warning(warning)
            else:
                st.caption(warning)
    name = metadata.get("index_name") or settings['universe']
    st.caption(f"Results for {name} · {settings['period']} · {settings['interval']}")
    benchmark_symbol = metadata.get("benchmark_symbol", settings.get("benchmark_symbol", "SPY"))
    benchmark_name = metadata.get("benchmark_display_name")
    benchmark_label = f"{benchmark_name} ({benchmark_symbol})" if benchmark_name else benchmark_symbol
    st.caption(f"Relative-strength benchmark: {benchmark_label}")
    metrics = [("Constituents fetched" if metadata.get("index_id") else "Universe loaded", total)]
    if "usable_market_data_count" in diagnostics:
        metrics.append(("Usable market data", diagnostics["usable_market_data_count"]))
    metrics.extend([
        ("Successfully analysed", analysed), ("Skipped / failed", failed),
        ("Trade opportunities", len(scan["trade_opportunities"])),
    ])
    for column, (label, value) in zip(st.columns(len(metrics)), metrics):
        column.metric(label, value)
    if failed:
        st.warning(f"{analysed} of {total} symbols were successfully analysed. {failed} symbols were skipped or failed.")
        with st.expander(f"Skipped / failed symbols ({failed})"):
            st.dataframe(pd.DataFrame(diagnostics.get("failures", []), columns=["symbol", "reason"]), hide_index=True)

    st.subheader("Trade Opportunities")
    threshold = settings.get("quality_threshold", 70)
    st.caption(f"BUY / SELL results with trade quality ≥ {threshold:g}, ordered by opportunity score.")
    from autot.settings.models import SettingsState
    limit = (SettingsState.model_validate(saved['settings_state']).settings.scanner.top_trade_opportunity_count
             if saved.get('settings_state') else None)
    displayed_opportunities = scan['trade_opportunities'][:limit]
    if scan["trade_opportunities"]:
        st.dataframe(opportunity_table(displayed_opportunities), hide_index=True)
        with st.expander("Why this qualified", expanded=True):
            for row in displayed_opportunities:
                st.write(qualification_explanation(row))
        from autot.application.market_context_display import render_market_context
        for index, row in enumerate(displayed_opportunities):
            render_market_context(saved, index, row)
    else:
        st.info("No actionable BUY or SELL opportunities in this scan.")

    st.divider()
    with st.expander(f"Top {settings['top_n']} by historical score"):
        st.caption("Subset of ranked results by score; may include HOLD signals.")
        if scan["top_results"]:
            st.dataframe(pd.DataFrame(scan["top_results"]), hide_index=True)
        else:
            st.info("No stocks were successfully analysed.")
    with st.expander("Full Ranked Results"):
        if scan["ranked_results"]:
            st.dataframe(pd.DataFrame(scan["ranked_results"]), hide_index=True)
        else:
            st.info("No stocks were successfully analysed.")
