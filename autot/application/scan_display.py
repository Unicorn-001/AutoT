"""Presentation of existing scan outputs; no trading calculations."""

import pandas as pd
import streamlit as st
from datetime import datetime, timezone


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
    st.caption("BUY / SELL results with trade quality ≥ 70, ordered by opportunity score.")
    if scan["trade_opportunities"]:
        st.dataframe(opportunity_table(scan["trade_opportunities"]), hide_index=True)
        with st.expander("Why this qualified", expanded=True):
            for row in scan["trade_opportunities"]:
                st.write(qualification_explanation(row))
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
