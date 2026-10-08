"""
File: test_scanner_service.py
Project: AutoT

Purpose:
    Regression tests for reusable scanner application services.
"""

from autot.application.scanner_service import build_scan_rankings


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
