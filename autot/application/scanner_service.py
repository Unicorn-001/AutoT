"""
File: scanner_service.py
Project: AutoT

Purpose:
    Reusable scan orchestration for CLI and web interfaces.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed


def run_scan(
    *,
    universe: str,
    period: str,
    interval: str,
    top_n: int,
    tracker,
    analyse_func,
    universe_loader,
    batch_data_loader,
    benchmark_data_loader,
    benchmark_symbol: str = "SPY",
    max_workers: int = 8,
    on_success=None,
    on_error=None,
    on_stage=None,
    diagnostics=None,
) -> dict:
    """Load, analyse and rank symbols using supplied dependencies.

    Optional diagnostics collects usable-data counts and failure reasons without
    changing return keys or existing callbacks. Missing loader entries have an
    unverified cause; the batch loader does not expose individual rejections.
    """
    if diagnostics is not None:
        diagnostics.clear()
    if on_stage is not None:
        on_stage("loading_universe", {})
    symbols = universe_loader(universe)
    if on_stage is not None:
        on_stage("universe_loaded", {"count": len(symbols)})

    tracker.start("Batch Download")
    try:
        if on_stage is not None:
            on_stage("loading_market_data", {})
        try:
            benchmark_data = benchmark_data_loader(benchmark_symbol, period, interval)
            if benchmark_data is None or (
                hasattr(benchmark_data, "empty")
                and (benchmark_data.empty or len(benchmark_data.dropna()) < 50)
            ):
                raise ValueError(f"Insufficient usable market data for {benchmark_symbol} benchmark")
        except Exception as error:
            raise ValueError(
                f"{benchmark_symbol} benchmark preflight failed; universe download not started: {error}"
            ) from error
        batch_data = batch_data_loader(
            symbols=symbols,
            period=period,
            interval=interval,
        )
    finally:
        tracker.stop("Batch Download")

    tracker.start("Analyse Stocks")
    analysis_error = on_error
    if diagnostics is not None:
        diagnostics.update(
            usable_market_data_count=sum(symbol in batch_data for symbol in symbols),
            failures=[
                {"symbol": symbol, "reason": "No usable market data returned; cause unverified"}
                for symbol in symbols if symbol not in batch_data
            ],
        )

        def analysis_error(symbol, error):
            diagnostics["failures"].append({
                "symbol": symbol, "reason": f"Analysis failed: {error}",
            })
            if on_error is not None:
                on_error(symbol, error)

    try:
        if on_stage is not None:
            on_stage("analysing", {})
        results, trade_decisions = run_batch_analysis(
            symbols,
            batch_data,
            benchmark_data,
            tracker,
            analyse_func,
            max_workers=max_workers,
            on_success=on_success,
            on_error=analysis_error,
        )
    finally:
        tracker.stop("Analyse Stocks")

    if on_stage is not None:
        on_stage("ranking", {})
    ranked_results, top_results, trade_opportunities = build_scan_rankings(
        results,
        top_n,
    )

    return {
        "symbols": symbols,
        "results": results,
        "trade_decisions": trade_decisions,
        "ranked_results": ranked_results,
        "top_results": top_results,
        "trade_opportunities": trade_opportunities,
    }


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
