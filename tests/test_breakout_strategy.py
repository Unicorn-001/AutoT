"""
File: test_breakout_strategy.py
Project: AutoT

Purpose:
    Regression tests for the breakout trading strategy.
"""

import pandas as pd
import pytest

from autot.strategies.breakout_strategy_class import BreakoutStrategy


def make_breakout_data(
    latest_close: float,
    previous_high: float = 110.0,
    previous_low: float = 90.0,
    lookback_period: int = 20,
) -> pd.DataFrame:
    """
    Create deterministic price data for breakout tests.
    """

    periods = lookback_period + 1

    close = [100.0] * periods
    high = [105.0] * periods
    low = [95.0] * periods

    # Set the previous lookback range.
    high[-2] = previous_high
    low[-2] = previous_low

    # Latest close is the value evaluated for breakout.
    close[-1] = latest_close

    return pd.DataFrame(
        {
            "Close": close,
            "High": high,
            "Low": low,
        }
    )


def test_breakout_buy_signal():
    strategy = BreakoutStrategy(lookback_period=20)

    data = make_breakout_data(
        latest_close=111.0,
        previous_high=110.0,
        previous_low=90.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.8
    assert "broke above" in result["reason"]


def test_breakout_sell_signal():
    strategy = BreakoutStrategy(lookback_period=20)

    data = make_breakout_data(
        latest_close=89.0,
        previous_high=110.0,
        previous_low=90.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.8
    assert "broke below" in result["reason"]


def test_breakout_hold_signal():
    strategy = BreakoutStrategy(lookback_period=20)

    data = make_breakout_data(
        latest_close=100.0,
        previous_high=110.0,
        previous_low=90.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5
    assert "within previous" in result["reason"]


def test_breakout_insufficient_data():
    strategy = BreakoutStrategy(lookback_period=20)

    data = pd.DataFrame(
        {
            "Close": [100.0] * 20,
            "High": [105.0] * 20,
            "Low": [95.0] * 20,
        }
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == (
        "Not enough data for breakout calculation."
    )


# =========================================================
# Breakout boundaries
# =========================================================

def test_breakout_equal_to_previous_high_is_hold():
    strategy = BreakoutStrategy(lookback_period=20)

    data = make_breakout_data(
        latest_close=110.0,
        previous_high=110.0,
        previous_low=90.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_breakout_equal_to_previous_low_is_hold():
    strategy = BreakoutStrategy(lookback_period=20)

    data = make_breakout_data(
        latest_close=90.0,
        previous_high=110.0,
        previous_low=90.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


# =========================================================
# Breakout input validation
# =========================================================

def test_breakout_missing_close_column():
    strategy = BreakoutStrategy()

    data = make_breakout_data(latest_close=111.0)
    data = data.drop(columns=["Close"])

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "Missing Close data."


def test_breakout_missing_high_column():
    strategy = BreakoutStrategy()

    data = make_breakout_data(latest_close=111.0)
    data = data.drop(columns=["High"])

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "Missing High data."


def test_breakout_missing_low_column():
    strategy = BreakoutStrategy()

    data = make_breakout_data(latest_close=89.0)
    data = data.drop(columns=["Low"])

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "Missing Low data."


def test_breakout_nan_latest_close():
    strategy = BreakoutStrategy()

    data = make_breakout_data(latest_close=float("nan"))

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "Invalid latest close price."


def test_breakout_zero_latest_close():
    strategy = BreakoutStrategy()

    data = make_breakout_data(latest_close=0.0)

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "Invalid latest close price."


def test_breakout_negative_latest_close():
    strategy = BreakoutStrategy()

    data = make_breakout_data(latest_close=-1.0)

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "Invalid latest close price."


def test_breakout_invalid_lookback_period():
    with pytest.raises(ValueError):
        BreakoutStrategy(lookback_period=0)
