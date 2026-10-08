"""
File: scanner_service.py
Project: AutoT

Purpose:
    Reusable scan orchestration for CLI and web interfaces.
"""


def build_scan_rankings(
    results: list[dict],
    top_n: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Rank scan results and identify actionable trade opportunities.
    """

    ranked_results = sorted(
        results,
        key=lambda item: item["score"],
        reverse=True,
    )

    for index, result in enumerate(ranked_results, start=1):
        result["rank"] = index

    top_results = ranked_results[:top_n]

    trade_opportunities = [
        result
        for result in results
        if result["signal"] in ["BUY", "SELL"]
        and result["trade_quality_score"] >= 70
    ]

    trade_opportunities = sorted(
        trade_opportunities,
        key=lambda item: item["opportunity_score"],
        reverse=True,
    )

    for index, result in enumerate(trade_opportunities, start=1):
        result["trade_rank"] = index

    return ranked_results, top_results, trade_opportunities
