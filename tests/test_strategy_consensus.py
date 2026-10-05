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

def test_weighted_buy_signal():
    results = [
        {"signal": "BUY", "confidence": 0.80},
        {"signal": "BUY", "confidence": 0.70},
        {"signal": "SELL", "confidence": 0.60},
    ]

    consensus = calculate_consensus_signal(results)

    assert consensus["final_signal"] == "BUY"
    assert consensus["buy_votes"] == 2
    assert consensus["sell_votes"] == 1
    assert consensus["hold_votes"] == 0
    assert consensus["buy_score"] == 1.5
    assert consensus["sell_score"] == 0.6
    assert consensus["hold_score"] == 0.0


def test_equal_buy_sell_scores_return_hold():
    results = [
        {"signal": "BUY", "confidence": 0.75},
        {"signal": "SELL", "confidence": 0.75},
    ]

    consensus = calculate_consensus_signal(results)

    assert consensus["final_signal"] == "HOLD"
    assert consensus["buy_votes"] == 1
    assert consensus["sell_votes"] == 1
    assert consensus["hold_votes"] == 0
    assert consensus["buy_score"] == 0.75
    assert consensus["sell_score"] == 0.75
    assert consensus["hold_score"] == 0.0


def test_hold_score_can_win_consensus():
    results = [
        {"signal": "HOLD", "confidence": 0.80},
        {"signal": "HOLD", "confidence": 0.70},
        {"signal": "BUY", "confidence": 0.60},
    ]

    consensus = calculate_consensus_signal(results)

    assert consensus["final_signal"] == "HOLD"
    assert consensus["buy_votes"] == 1
    assert consensus["sell_votes"] == 0
    assert consensus["hold_votes"] == 2
    assert consensus["buy_score"] == 0.6
    assert consensus["sell_score"] == 0.0
    assert consensus["hold_score"] == 1.5


def test_confidence_weight_can_outweigh_vote_count():
    results = [
        {"signal": "BUY", "confidence": 0.20},
        {"signal": "BUY", "confidence": 0.20},
        {"signal": "SELL", "confidence": 0.90},
    ]

    consensus = calculate_consensus_signal(results)

    assert consensus["buy_votes"] == 2
    assert consensus["sell_votes"] == 1
    assert consensus["buy_score"] == 0.4
    assert consensus["sell_score"] == 0.9
    assert consensus["final_signal"] == "SELL"


def test_missing_confidence_defaults_to_half():
    results = [
        {"signal": "BUY"},
        {"signal": "SELL", "confidence": 0.40},
    ]

    consensus = calculate_consensus_signal(results)

    assert consensus["buy_votes"] == 1
    assert consensus["sell_votes"] == 1
    assert consensus["buy_score"] == 0.5
    assert consensus["sell_score"] == 0.4
    assert consensus["final_signal"] == "BUY"


def test_empty_strategy_results_return_hold():
    consensus = calculate_consensus_signal([])

    assert consensus["final_signal"] == "HOLD"
    assert consensus["buy_votes"] == 0
    assert consensus["sell_votes"] == 0
    assert consensus["hold_votes"] == 0
    assert consensus["buy_score"] == 0.0
    assert consensus["sell_score"] == 0.0
    assert consensus["hold_score"] == 0.0


def test_invalid_signal_does_not_count_as_hold():
    results = [
        {"signal": "INVALID", "confidence": 0.90},
    ]

    consensus = calculate_consensus_signal(results)

    assert consensus["final_signal"] == "HOLD"
    assert consensus["buy_votes"] == 0
    assert consensus["sell_votes"] == 0
    assert consensus["hold_votes"] == 0
    assert consensus["buy_score"] == 0.0
    assert consensus["sell_score"] == 0.0
    assert consensus["hold_score"] == 0.0
