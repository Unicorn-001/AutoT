"""
File: test_decision_engine.py
Project: AutoT

Purpose:
    Regression tests for the central DecisionEngine.
"""

import pytest

from autot.decision_engine.decision_engine import DecisionEngine


def make_consensus(buy, sell, hold, final_signal):
    return {
        "buy_score": buy,
        "sell_score": sell,
        "hold_score": hold,
        "final_signal": final_signal,
    }


def test_strong_buy_remains_buy():
    consensus = make_consensus(
        buy=80.0,
        sell=10.0,
        hold=10.0,
        final_signal="BUY",
    )

    decision = DecisionEngine.decide(consensus)

    assert decision["final_signal"] == "BUY"
    assert decision["confidence"] == 80.0
    assert decision["agreement"] == 87.5


def test_strong_sell_remains_sell():
    consensus = make_consensus(
        buy=10.0,
        sell=80.0,
        hold=10.0,
        final_signal="SELL",
    )

    decision = DecisionEngine.decide(consensus)

    assert decision["final_signal"] == "SELL"
    assert decision["confidence"] == 80.0
    assert decision["agreement"] == 87.5


def test_low_confidence_buy_becomes_hold():
    consensus = make_consensus(
        buy=54.0,
        sell=23.0,
        hold=23.0,
        final_signal="BUY",
    )

    decision = DecisionEngine.decide(consensus)

    assert decision["final_signal"] == "HOLD"
    assert decision["confidence"] == 54.0
    assert "below minimum threshold" in decision["decision_reason"]


def test_low_confidence_sell_becomes_hold():
    consensus = make_consensus(
        buy=23.0,
        sell=54.0,
        hold=23.0,
        final_signal="SELL",
    )

    decision = DecisionEngine.decide(consensus)

    assert decision["final_signal"] == "HOLD"
    assert decision["confidence"] == 54.0
    assert "below minimum threshold" in decision["decision_reason"]


def test_signal_at_minimum_confidence_is_allowed():
    consensus = make_consensus(
        buy=55.0,
        sell=25.0,
        hold=20.0,
        final_signal="BUY",
    )

    decision = DecisionEngine.decide(consensus)

    assert decision["final_signal"] == "BUY"
    assert decision["confidence"] == 55.0


def test_zero_scores_produce_safe_hold():
    consensus = make_consensus(
        buy=0.0,
        sell=0.0,
        hold=0.0,
        final_signal="HOLD",
    )

    decision = DecisionEngine.decide(consensus)

    assert decision["final_signal"] == "HOLD"
    assert decision["confidence"] == 0.0
    assert decision["agreement"] == 0.0


def test_agreement_uses_difference_between_top_two_scores():
    consensus = make_consensus(
        buy=60.0,
        sell=30.0,
        hold=10.0,
        final_signal="BUY",
    )

    decision = DecisionEngine.decide(consensus)

    assert decision["agreement"] == pytest.approx(50.0)
