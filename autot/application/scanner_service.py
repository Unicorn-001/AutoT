"""
File: scanner_service.py
Project: AutoT

Purpose:
    Reusable scan orchestration for CLI and web interfaces.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed


def run_batch_analysis(
    symbols,
    batch_data,
    benchmark_data,
    tracker,
    analyse_func,
    max_workers=8,
    on_success=None,
    on_error=None,
) -> tuple[list[dict], dict]:
    """Analyse available symbols in parallel and collect completed results."""
    results = []
    trade_decisions = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {
            executor.submit(
                analyse_func,
                symbol,
                batch_data[symbol],
                benchmark_data,
                tracker,
            ): symbol
            for symbol in symbols
            if symbol in batch_data
        }

        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]

            try:
                result, decision = future.result()
                results.append(result)
                trade_decisions[symbol] = decision

                if on_success is not None:
                    on_success(len(results), len(symbols), symbol)
            except Exception as error:
                if on_error is not None:
                    on_error(symbol, error)

    return results, trade_decisions


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
