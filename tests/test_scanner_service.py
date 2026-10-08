"""
File: test_scanner_service.py
Project: AutoT

Purpose:
    Regression tests for reusable scanner application services.
"""

from autot.application.scanner_service import build_scan_rankings, run_batch_analysis

import pytest

from autot.application.scanner_service import run_scan


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


@pytest.mark.parametrize("with_callbacks", [False, True])
def test_run_scan_orchestrates_loaders_analysis_and_rankings(with_callbacks):
    symbols = ["AAA", "BBB", "FAIL", "MISSING"]
    batch_data = {symbol: object() for symbol in symbols if symbol != "MISSING"}
    benchmark = object()
    failure = ValueError("Analysis failed")
    loader_calls = []
    tracker_calls = []
    stages = []
    successes = []
    errors = []
    expected_results = {
        "AAA": make_result("AAA", "HOLD", 90.0, 95.0, 99.0),
        "BBB": make_result("BBB", "BUY", 50.0, 80.0, 85.0),
    }
    expected_decisions = {symbol: object() for symbol in expected_results}

    class Tracker:
        def start(self, name):
            tracker_calls.append(("start", name))

        def stop(self, name):
            tracker_calls.append(("stop", name))

    tracker = Tracker()

    def load_symbols(universe):
        assert tracker_calls == []
        loader_calls.append(("universe", universe))
        return symbols

    def load_batch(*, symbols, period, interval):
        assert tracker_calls == [("start", "Batch Download")]
        loader_calls.append(("batch", symbols, period, interval))
        return batch_data

    def load_benchmark(*args):
        assert tracker_calls == [("start", "Batch Download")]
        loader_calls.append(("benchmark", *args))
        return benchmark

    def analyse(symbol, data, benchmark_data, supplied_tracker):
        assert data is batch_data[symbol]
        assert benchmark_data is benchmark
        assert supplied_tracker is tracker
        if symbol == "FAIL":
            raise failure
        return expected_results[symbol], expected_decisions[symbol]

    callbacks = {}
    if with_callbacks:
        callbacks = {
            "on_stage": lambda stage, details: stages.append((stage, details)),
            "on_success": lambda count, total, symbol: successes.append(
                (count, total, symbol)
            ),
            "on_error": lambda symbol, error: errors.append((symbol, error)),
        }

    scan = run_scan(
        universe="test_universe.csv",
        period="1y",
        interval="1d",
        top_n=1,
        tracker=tracker,
        analyse_func=analyse,
        universe_loader=load_symbols,
        batch_data_loader=load_batch,
        benchmark_data_loader=load_benchmark,
        max_workers=1,
        **callbacks,
    )

    assert loader_calls == [
        ("universe", "test_universe.csv"),
        ("batch", symbols, "1y", "1d"),
        ("benchmark", "SPY", "1y", "1d"),
    ]
    assert set(scan) == {
        "symbols", "results", "trade_decisions", "ranked_results",
        "top_results", "trade_opportunities",
    }
    assert scan["symbols"] is symbols
    assert sorted(result["symbol"] for result in scan["results"]) == ["AAA", "BBB"]
    assert scan["trade_decisions"] == expected_decisions
    assert scan["ranked_results"] == [expected_results["AAA"], expected_results["BBB"]]
    assert [result["rank"] for result in scan["ranked_results"]] == [1, 2]
    assert scan["top_results"] == [expected_results["AAA"]]
    assert scan["trade_opportunities"] == [expected_results["BBB"]]
    assert scan["trade_opportunities"][0]["trade_rank"] == 1
    assert tracker_calls == [
        ("start", "Batch Download"),
        ("stop", "Batch Download"),
        ("start", "Analyse Stocks"),
        ("stop", "Analyse Stocks"),
    ]
    if with_callbacks:
        assert stages == [
            ("loading_universe", {}),
            ("universe_loaded", {"count": 4}),
            ("loading_market_data", {}),
            ("analysing", {}),
            ("ranking", {}),
        ]
        assert successes == [
            (index, 4, result["symbol"])
            for index, result in enumerate(scan["results"], start=1)
        ]
        assert errors == [("FAIL", failure)]


@pytest.mark.parametrize("failing_loader", ["universe", "batch", "benchmark"])
def test_run_scan_propagates_loader_exceptions(failing_loader):
    failure = ValueError("Loader failed")
    tracker_calls = []

    class Tracker:
        def start(self, name):
            tracker_calls.append(("start", name))

        def stop(self, name):
            tracker_calls.append(("stop", name))

    def load(name, value):
        def loader(*args, **kwargs):
            if name == failing_loader:
                raise failure
            return value
        return loader

    def analyse(*args):
        pytest.fail("Analysis must not run after a loader failure")

    with pytest.raises(ValueError) as caught:
        run_scan(
            universe="test_universe.csv",
            period="1y",
            interval="1d",
            top_n=1,
            tracker=Tracker(),
            analyse_func=analyse,
            universe_loader=load("universe", ["AAA"]),
            batch_data_loader=load("batch", {"AAA": object()}),
            benchmark_data_loader=load("benchmark", object()),
            max_workers=1,
        )

    assert caught.value is failure
    assert tracker_calls == (
        [] if failing_loader == "universe" else [
            ("start", "Batch Download"),
            ("stop", "Batch Download"),
        ]
    )


def test_run_scan_stops_analysis_timer_when_batch_analysis_raises():
    tracker_calls = []

    class Tracker:
        def start(self, name):
            tracker_calls.append(("start", name))

        def stop(self, name):
            tracker_calls.append(("stop", name))

    with pytest.raises(ValueError):
        run_scan(
            universe="test_universe.csv",
            period="1y",
            interval="1d",
            top_n=1,
            tracker=Tracker(),
            analyse_func=lambda *args: ({}, None),
            universe_loader=lambda universe: ["AAA"],
            batch_data_loader=lambda **kwargs: {"AAA": object()},
            benchmark_data_loader=lambda *args: object(),
            max_workers=0,
        )

    assert tracker_calls == [
        ("start", "Batch Download"),
        ("stop", "Batch Download"),
        ("start", "Analyse Stocks"),
        ("stop", "Analyse Stocks"),
    ]
