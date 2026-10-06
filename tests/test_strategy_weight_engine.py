"""
File: test_strategy_weight_engine.py
Project: AutoT

Purpose:
    Regression tests for market-regime-based strategy weighting.
"""

from autot.strategy_weights.strategy_weight_engine import StrategyWeightEngine


def test_unknown_market_regime_uses_neutral_weight():
    strategy_results = [
        {
            "strategy": "EMA_RSI_Strategy",
            "signal": "BUY",
            "reason": "Test signal.",
            "confidence": 0.75,
        }
    ]

    weighted_results = StrategyWeightEngine.apply_weights(
        strategy_results,
        "UNKNOWN_REGIME",
    )

    assert len(weighted_results) == 1
    assert weighted_results[0]["original_confidence"] == 0.75
    assert weighted_results[0]["weight"] == 1.0
    assert weighted_results[0]["confidence"] == 0.75


def test_known_regime_applies_configured_and_default_weights():
    strategy_results = [
        {
            "strategy": "EMA_RSI_Strategy",
            "signal": "BUY",
            "reason": "Test signal.",
            "confidence": 0.75,
        },
        {
            "strategy": "Bollinger_Strategy",
            "signal": "HOLD",
            "reason": "Test signal.",
            "confidence": 0.80,
        },
        {
            "strategy": "ADX_Strategy",
            "signal": "BUY",
            "reason": "Test signal.",
            "confidence": 0.60,
        },
    ]

    weighted_results = StrategyWeightEngine.apply_weights(
        strategy_results,
        "STRONG_UPTREND",
    )

    assert len(weighted_results) == 3

    assert weighted_results[0]["strategy"] == "EMA_RSI_Strategy"
    assert weighted_results[0]["original_confidence"] == 0.75
    assert weighted_results[0]["weight"] == 1.20
    assert weighted_results[0]["confidence"] == 0.90

    assert weighted_results[1]["strategy"] == "Bollinger_Strategy"
    assert weighted_results[1]["original_confidence"] == 0.80
    assert weighted_results[1]["weight"] == 0.90
    assert weighted_results[1]["confidence"] == 0.72

    assert weighted_results[2]["strategy"] == "ADX_Strategy"
    assert weighted_results[2]["original_confidence"] == 0.60
    assert weighted_results[2]["weight"] == 1.0
    assert weighted_results[2]["confidence"] == 0.60


def test_weighting_does_not_modify_original_results():
    strategy_results = [
        {
            "strategy": "EMA_RSI_Strategy",
            "signal": "BUY",
            "reason": "Test signal.",
            "confidence": 0.75,
        }
    ]

    original_result = strategy_results[0].copy()

    StrategyWeightEngine.apply_weights(
        strategy_results,
        "STRONG_UPTREND",
    )

    assert strategy_results[0] == original_result
    assert "weight" not in strategy_results[0]
    assert "original_confidence" not in strategy_results[0]


def test_empty_strategy_results_returns_empty_list():
    weighted_results = StrategyWeightEngine.apply_weights(
        [],
        "STRONG_UPTREND",
    )

    assert weighted_results == []
