"""
File: test_strategy_manager.py
Project: AutoT

Purpose:
    Test strategy execution and result collection.
"""

import pandas as pd

from autot.strategies.manager.strategy_manager import StrategyManager
from autot.strategies.manager.strategy_consensus import calculate_consensus_signal


class FakeStrategy:
    def __init__(self, name, result):
        self.name = name
        self.result = result

    def generate_signal(self, data):
        if isinstance(self.result, dict):
            return self.result.copy()
        return self.result

    def get_name(self):
        return self.name


class FakeRegistry:
    def __init__(self, strategies):
        self.strategies = strategies

    def get_all(self):
        return self.strategies


def test_manager_runs_all_strategies_and_adds_names():
    manager = StrategyManager()

    manager.registry = FakeRegistry([
        FakeStrategy(
            "Strategy_A",
            {
                "signal": "BUY",
                "reason": "Buy condition met.",
                "confidence": 0.80,
            },
        ),
        FakeStrategy(
            "Strategy_B",
            {
                "signal": "SELL",
                "reason": "Sell condition met.",
                "confidence": 0.70,
            },
        ),
    ])

    data = pd.DataFrame({"Close": [100.0]})

    results = manager.run_all(data)

    assert len(results) == 2

    assert results[0] == {
        "signal": "BUY",
        "reason": "Buy condition met.",
        "confidence": 0.80,
        "strategy": "Strategy_A",
    }

    assert results[1] == {
        "signal": "SELL",
        "reason": "Sell condition met.",
        "confidence": 0.70,
        "strategy": "Strategy_B",
    }


def test_manager_converts_legacy_string_result():
    manager = StrategyManager()

    manager.registry = FakeRegistry([
        FakeStrategy("Legacy_Strategy", "BUY"),
    ])

    data = pd.DataFrame({"Close": [100.0]})

    results = manager.run_all(data)

    assert results == [
        {
            "signal": "BUY",
            "reason": "Legacy strategy result.",
            "confidence": 0.5,
            "strategy": "Legacy_Strategy",
        }
    ]


def test_manager_returns_empty_list_when_no_strategies_registered():
    manager = StrategyManager()
    manager.registry = FakeRegistry([])

    data = pd.DataFrame({"Close": [100.0]})

    results = manager.run_all(data)

    assert results == []


class FailingStrategy:
    def get_name(self):
        return "Failing_Strategy"

    def generate_signal(self, data):
        raise RuntimeError("Simulated strategy failure")


def test_manager_continues_when_one_strategy_fails():
    manager = StrategyManager()

    manager.registry = FakeRegistry([
        FailingStrategy(),
        FakeStrategy(
            "Working_Strategy",
            {
                "signal": "BUY",
                "reason": "Valid signal.",
                "confidence": 0.80,
            },
        ),
    ])

    data = pd.DataFrame({"Close": [100.0]})

    results = manager.run_all(data)

    assert len(results) == 2

    assert results[0]["signal"] == "HOLD"
    assert results[0]["confidence"] == 0.0
    assert results[0]["strategy"] == "Failing_Strategy"

    assert results[1]["signal"] == "BUY"
    assert results[1]["confidence"] == 0.80
    assert results[1]["strategy"] == "Working_Strategy"


def test_manager_results_feed_consensus_correctly():
    manager = StrategyManager()

    manager.registry = FakeRegistry([
        FakeStrategy(
            "Buy_Strategy_1",
            {
                "signal": "BUY",
                "reason": "Buy signal.",
                "confidence": 0.80,
            },
        ),
        FakeStrategy(
            "Buy_Strategy_2",
            {
                "signal": "BUY",
                "reason": "Buy signal.",
                "confidence": 0.70,
            },
        ),
        FakeStrategy(
            "Sell_Strategy",
            {
                "signal": "SELL",
                "reason": "Sell signal.",
                "confidence": 0.60,
            },
        ),
    ])

    data = pd.DataFrame({"Close": [100.0]})

    strategy_results = manager.run_all(data)
    consensus = calculate_consensus_signal(strategy_results)

    assert consensus["buy_votes"] == 2
    assert consensus["sell_votes"] == 1
    assert consensus["hold_votes"] == 0
    assert consensus["buy_score"] == 1.5
    assert consensus["sell_score"] == 0.6
    assert consensus["final_signal"] == "BUY"


def test_manager_results_feed_consensus_correctly():
    manager = StrategyManager()

    manager.registry = FakeRegistry([
        FakeStrategy(
            "Buy_Strategy_1",
            {
                "signal": "BUY",
                "reason": "Buy signal.",
                "confidence": 0.80,
            },
        ),
        FakeStrategy(
            "Buy_Strategy_2",
            {
                "signal": "BUY",
                "reason": "Buy signal.",
                "confidence": 0.70,
            },
        ),
        FakeStrategy(
            "Sell_Strategy",
            {
                "signal": "SELL",
                "reason": "Sell signal.",
                "confidence": 0.60,
            },
        ),
    ])

    data = pd.DataFrame({"Close": [100.0]})

    strategy_results = manager.run_all(data)
    consensus = calculate_consensus_signal(strategy_results)

    assert consensus["buy_votes"] == 2
    assert consensus["sell_votes"] == 1
    assert consensus["hold_votes"] == 0
    assert consensus["buy_score"] == 1.5
    assert consensus["sell_score"] == 0.6
    assert consensus["final_signal"] == "BUY"
