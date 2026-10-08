"""
File: test_scanner_service.py
Project: AutoT

Purpose:
    Regression tests for reusable scanner application services.
"""

from autot.application.scanner_service import build_scan_rankings, run_batch_analysis


def make_result(
    symbol,
    signal,
    score,
    trade_quality_score,
    opportunity_score,
):
    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "trade_quality_score": trade_quality_score,
        "opportunity_score": opportunity_score,
    }


def test_build_scan_rankings_orders_historical_results():
    results = [
        make_result("AAA", "BUY", 50.0, 80.0, 70.0),
        make_result("BBB", "HOLD", 90.0, 60.0, 40.0),
        make_result("CCC", "SELL", 70.0, 75.0, 85.0),
    ]

    ranked_results, top_results, _ = build_scan_rankings(
        results,
        top_n=2,
    )

    assert [result["symbol"] for result in ranked_results] == [
        "BBB",
        "CCC",
        "AAA",
    ]

    assert [result["rank"] for result in ranked_results] == [1, 2, 3]

    assert [result["symbol"] for result in top_results] == [
        "BBB",
        "CCC",
    ]


def test_trade_opportunities_filter_and_rank_by_opportunity_score():
    results = [
        make_result("AAA", "BUY", 50.0, 80.0, 70.0),
        make_result("BBB", "HOLD", 90.0, 95.0, 99.0),
        make_result("CCC", "SELL", 70.0, 75.0, 85.0),
        make_result("DDD", "BUY", 60.0, 69.0, 95.0),
        make_result("EEE", "BUY", 65.0, 70.0, 90.0),
    ]

    _, _, trade_opportunities = build_scan_rankings(
        results,
        top_n=5,
    )

    assert [result["symbol"] for result in trade_opportunities] == [
        "EEE",
        "CCC",
        "AAA",
    ]

    assert [result["trade_rank"] for result in trade_opportunities] == [
        1,
        2,
        3,
    ]


def test_empty_results_return_empty_rankings():
    ranked_results, top_results, trade_opportunities = build_scan_rankings(
        [],
        top_n=10,
    )

    assert ranked_results == []
    assert top_results == []
    assert trade_opportunities == []


def test_equal_historical_scores_preserve_input_order():
    results = [
        make_result("CCC", "HOLD", 70.0, 60.0, 40.0),
        make_result("AAA", "HOLD", 90.0, 60.0, 40.0),
        make_result("BBB", "HOLD", 70.0, 60.0, 40.0),
    ]

    ranked_results, _, _ = build_scan_rankings(results, top_n=3)

    assert [result["symbol"] for result in ranked_results] == [
        "AAA",
        "CCC",
        "BBB",
    ]
    assert [result["rank"] for result in ranked_results] == [1, 2, 3]


def test_trade_opportunities_include_results_outside_top_results():
    results = [
        make_result("AAA", "HOLD", 90.0, 95.0, 99.0),
        make_result("BBB", "BUY", 50.0, 80.0, 85.0),
        make_result("CCC", "SELL", 40.0, 70.0, 75.0),
    ]

    _, top_results, trade_opportunities = build_scan_rankings(results, top_n=1)

    assert [result["symbol"] for result in top_results] == ["AAA"]
    assert [result["symbol"] for result in trade_opportunities] == ["BBB", "CCC"]


def test_rankings_add_ranks_to_the_callers_result_dictionaries():
    buy_result = make_result("AAA", "BUY", 50.0, 80.0, 70.0)
    hold_result = make_result("BBB", "HOLD", 90.0, 60.0, 40.0)
    sell_result = make_result("CCC", "SELL", 70.0, 75.0, 85.0)
    results = [buy_result, hold_result, sell_result]

    ranked_results, top_results, trade_opportunities = build_scan_rankings(
        results,
        top_n=2,
    )

    assert ranked_results[0] is hold_result
    assert ranked_results[1] is sell_result
    assert ranked_results[2] is buy_result
    assert top_results[0] is hold_result
    assert top_results[1] is sell_result
    assert trade_opportunities[0] is sell_result
    assert trade_opportunities[1] is buy_result
    assert [result["rank"] for result in results] == [3, 1, 2]
    assert buy_result["trade_rank"] == 2
    assert sell_result["trade_rank"] == 1
    assert "trade_rank" not in hold_result


def test_batch_analysis_collects_results_and_decisions():
    symbols = ["AAA", "BBB"]
    batch_data = {symbol: object() for symbol in symbols}
    benchmark_data = object()
    tracker = object()
    expected_results = {symbol: {"symbol": symbol} for symbol in symbols}
    expected_decisions = {symbol: object() for symbol in symbols}

    def analyse(symbol, data, benchmark, performance_tracker):
        assert data is batch_data[symbol]
        assert benchmark is benchmark_data
        assert performance_tracker is tracker
        return expected_results[symbol], expected_decisions[symbol]

    results, decisions = run_batch_analysis(
        symbols, batch_data, benchmark_data, tracker, analyse, max_workers=1,
    )

    assert sorted(result["symbol"] for result in results) == symbols
    assert decisions == expected_decisions
    for result in results:
        assert result is expected_results[result["symbol"]]


def test_batch_analysis_skips_missing_symbols_and_reports_success_counts():
    calls = []
    successes = []

    def analyse(symbol, data, benchmark, tracker):
        calls.append(symbol)
        return {"symbol": symbol}, symbol

    results, decisions = run_batch_analysis(
        ["AAA", "MISSING", "BBB"],
        {"AAA": object(), "BBB": object()},
        None,
        None,
        analyse,
        max_workers=1,
        on_success=lambda count, total, symbol: successes.append((count, total, symbol)),
    )

    assert calls == ["AAA", "BBB"]
    assert decisions == {"AAA": "AAA", "BBB": "BBB"}
    assert sorted(result["symbol"] for result in results) == ["AAA", "BBB"]
    assert successes == [
        (index, 3, result["symbol"])
        for index, result in enumerate(results, start=1)
    ]


def test_batch_analysis_continues_after_failure_and_reports_callbacks():
    failure = ValueError("Analysis failed")
    successes = []
    errors = []
    decision = object()

    def analyse(symbol, data, benchmark, tracker):
        if symbol == "FAIL":
            raise failure
        return {"symbol": symbol}, decision

    results, decisions = run_batch_analysis(
        ["FAIL", "AAA"],
        {"FAIL": object(), "AAA": object()},
        None,
        None,
        analyse,
        max_workers=1,
        on_success=lambda count, total, symbol: successes.append((count, total, symbol)),
        on_error=lambda symbol, error: errors.append((symbol, error)),
    )

    assert results == [{"symbol": "AAA"}]
    assert decisions == {"AAA": decision}
    assert successes == [(1, 2, "AAA")]
    assert errors == [("FAIL", failure)]
