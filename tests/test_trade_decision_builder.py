"""
File: test_trade_decision_builder.py
Project: AutoT

Purpose:
    Regression tests for the TradeDecisionBuilder.
"""

import pandas as pd
import pytest

from autot.decision.trade_decision_builder import TradeDecisionBuilder


def make_market_data(close_price=100.0):
    """
    Create minimal market data in the MultiIndex format
    expected by TradeDecisionBuilder.
    """

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("High", "TEST"),
            ("Low", "TEST"),
        ]
    )

    return pd.DataFrame(
        [
            [close_price, close_price + 2.0, close_price - 2.0],
            [close_price, close_price + 2.0, close_price - 2.0],
        ],
        columns=columns,
    )


def make_consensus(
    final_signal,
):
    """
    Create consensus scores that produce a predictable signal.
    """

    if final_signal == "BUY":
        return {
            "buy_score": 80.0,
            "sell_score": 10.0,
            "hold_score": 10.0,
            "final_signal": "BUY",
        }

    if final_signal == "SELL":
        return {
            "buy_score": 10.0,
            "sell_score": 80.0,
            "hold_score": 10.0,
            "final_signal": "SELL",
        }

    if final_signal == "HOLD":
        return {
            "buy_score": 10.0,
            "sell_score": 10.0,
            "hold_score": 80.0,
            "final_signal": "HOLD",
        }

    raise ValueError("Unsupported test signal.")


def test_buy_decision_builds_correct_trade_structure(monkeypatch):
    data = make_market_data(100.0)

    monkeypatch.setattr(
        "autot.decision.trade_decision_builder."
        "MarketRegimeDetector.detect",
        lambda data: {"regime": "TEST_REGIME"},
    )

    decision = TradeDecisionBuilder.build(
        symbol="TEST",
        data=data,
        consensus=make_consensus("BUY"),
    )

    assert decision.symbol == "TEST"
    assert decision.final_signal == "BUY"
    assert decision.market_regime == "TEST_REGIME"

    assert decision.entry_price == 100.0
    assert decision.stop_loss == pytest.approx(98.0)
    assert decision.take_profit == pytest.approx(104.0)
    assert decision.risk_reward_ratio == 2.0

    assert decision.buy_score == 80.0
    assert decision.sell_score == 10.0
    assert decision.hold_score == 10.0

    assert decision.position_size.account_size == 10000.0
    assert decision.position_size.risk_percent == 1.0
    assert decision.position_size.risk_amount == 100.0
    assert decision.position_size.risk_per_share == 2.0
    assert decision.position_size.quantity == 50
    assert decision.position_size.position_value == 5000.0
    assert decision.position_size.max_loss == 100.0


def test_sell_decision_builds_correct_trade_structure(monkeypatch):
    data = make_market_data(100.0)

    monkeypatch.setattr(
        "autot.decision.trade_decision_builder."
        "MarketRegimeDetector.detect",
        lambda data: {"regime": "TEST_REGIME"},
    )

    decision = TradeDecisionBuilder.build(
        symbol="TEST",
        data=data,
        consensus=make_consensus("SELL"),
    )

    assert decision.final_signal == "SELL"

    assert decision.entry_price == 100.0
    assert decision.stop_loss == pytest.approx(102.0)
    assert decision.take_profit == pytest.approx(96.0)
    assert decision.risk_reward_ratio == 2.0

    assert decision.position_size.risk_per_share == 2.0
    assert decision.position_size.quantity == 50
    assert decision.position_size.max_loss == 100.0


def test_hold_decision_has_no_active_trade_risk(monkeypatch):
    data = make_market_data(100.0)

    monkeypatch.setattr(
        "autot.decision.trade_decision_builder."
        "MarketRegimeDetector.detect",
        lambda data: {"regime": "TEST_REGIME"},
    )

    decision = TradeDecisionBuilder.build(
        symbol="TEST",
        data=data,
        consensus=make_consensus("HOLD"),
    )

    assert decision.final_signal == "HOLD"

    assert decision.entry_price == 100.0
    assert decision.stop_loss == 100.0
    assert decision.take_profit == 100.0
    assert decision.risk_reward_ratio == 0.0

    assert decision.position_size.risk_per_share == 0.0
    assert decision.position_size.quantity == 0
    assert decision.position_size.position_value == 0.0
    assert decision.position_size.max_loss == 0.0


def test_builder_uses_latest_close_price(monkeypatch):
    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("High", "TEST"),
            ("Low", "TEST"),
        ]
    )

    data = pd.DataFrame(
        [
            [90.0, 92.0, 88.0],
            [95.0, 97.0, 93.0],
            [100.0, 102.0, 98.0],
        ],
        columns=columns,
    )

    monkeypatch.setattr(
        "autot.decision.trade_decision_builder."
        "MarketRegimeDetector.detect",
        lambda data: {"regime": "TEST_REGIME"},
    )

    decision = TradeDecisionBuilder.build(
        symbol="TEST",
        data=data,
        consensus=make_consensus("BUY"),
    )

    assert decision.entry_price == 100.0


def test_builder_rejects_non_positive_latest_close(monkeypatch):
    data = make_market_data(0.0)

    monkeypatch.setattr(
        "autot.decision.trade_decision_builder."
        "MarketRegimeDetector.detect",
        lambda data: {"regime": "TEST_REGIME"},
    )

    with pytest.raises(ValueError):
        TradeDecisionBuilder.build(
            symbol="TEST",
            data=data,
            consensus=make_consensus("BUY"),
        )
