"""
File: test_strategy_consensus.py
Project: AutoT

Purpose:
    Test the weighted strategy consensus engine.
"""

from autot.strategies.manager.strategy_consensus import calculate_consensus_signal


def test_weighted_sell_signal():
    results = [
        {"signal": "SELL", "confidence": 0.75},
        {"signal": "SELL", "confidence": 0.70},
        {"signal": "BUY", "confidence": 0.50},
    ]

    consensus = calculate_consensus_signal(results)

    assert consensus["final_signal"] == "SELL"
    assert consensus["sell_score"] == 1.45