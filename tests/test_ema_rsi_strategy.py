"""
File: test_ema_rsi_strategy.py
Project: AutoT

Purpose:
    Regression tests for the EMA + RSI trading strategy.
"""

import pandas as pd

from autot.strategies.ema_rsi_strategy_class import EmaRsiStrategy


def make_ema_rsi_data(
    ema_20: float,
    ema_50: float,
    rsi: float,
) -> pd.DataFrame:
    """
    Create indicator data in the format expected by AutoT strategies.
    """

    columns = pd.MultiIndex.from_tuples(
        [
            ("EMA_20", ""),
            ("EMA_50", ""),
            ("RSI", ""),
        ]
    )

    return pd.DataFrame(
        [[ema_20, ema_50, rsi]],
        columns=columns,
    )


def test_ema_rsi_buy_signal():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=110.0,
        ema_50=100.0,
        rsi=60.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.75
    assert "above EMA50" in result["reason"]


def test_ema_rsi_sell_signal_bearish_ema():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=90.0,
        ema_50=100.0,
        rsi=55.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.75
    assert "Bearish EMA or weak RSI" in result["reason"]


def test_ema_rsi_sell_signal_weak_rsi():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=110.0,
        ema_50=100.0,
        rsi=40.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.75


def test_ema_rsi_hold_signal():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=110.0,
        ema_50=100.0,
        rsi=47.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5
    assert "No clear EMA/RSI signal" in result["reason"]


def test_ema_rsi_empty_data():
    strategy = EmaRsiStrategy()

    result = strategy.generate_signal(pd.DataFrame())

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "No data available."


# =========================================================
# RSI boundaries
# =========================================================

def test_ema_rsi_below_45_is_sell():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=110.0,
        ema_50=100.0,
        rsi=44.99,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"


def test_ema_rsi_exactly_45_is_hold():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=110.0,
        ema_50=100.0,
        rsi=45.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"


def test_ema_rsi_exactly_50_is_hold():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=110.0,
        ema_50=100.0,
        rsi=50.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"


def test_ema_rsi_above_50_is_buy():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=110.0,
        ema_50=100.0,
        rsi=50.01,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"


# =========================================================
# EMA boundaries
# =========================================================

def test_ema_rsi_equal_emas_with_strong_rsi_is_hold():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=100.0,
        ema_50=100.0,
        rsi=60.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_ema_rsi_equal_emas_with_weak_rsi_is_sell():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=100.0,
        ema_50=100.0,
        rsi=40.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.75


# =========================================================
# Missing indicator validation
# =========================================================

def test_ema_rsi_missing_ema20_returns_hold():
    strategy = EmaRsiStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("EMA_50", ""),
            ("RSI", ""),
        ]
    )
    data = pd.DataFrame([[100.0, 60.0]], columns=columns)

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_ema_rsi_missing_ema50_returns_hold():
    strategy = EmaRsiStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("EMA_20", ""),
            ("RSI", ""),
        ]
    )
    data = pd.DataFrame([[110.0, 60.0]], columns=columns)

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_ema_rsi_missing_rsi_returns_hold():
    strategy = EmaRsiStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("EMA_20", ""),
            ("EMA_50", ""),
        ]
    )
    data = pd.DataFrame([[110.0, 100.0]], columns=columns)

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Invalid indicator values
# =========================================================

def test_ema_rsi_nan_ema20_returns_hold():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=float("nan"),
        ema_50=100.0,
        rsi=60.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_ema_rsi_nan_ema50_returns_hold():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=110.0,
        ema_50=float("nan"),
        rsi=60.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_ema_rsi_nan_rsi_returns_hold():
    strategy = EmaRsiStrategy()

    data = make_ema_rsi_data(
        ema_20=110.0,
        ema_50=100.0,
        rsi=float("nan"),
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Latest-row behaviour
# =========================================================

def test_ema_rsi_uses_latest_row():
    strategy = EmaRsiStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("EMA_20", ""),
            ("EMA_50", ""),
            ("RSI", ""),
        ]
    )

    data = pd.DataFrame(
        [
            [90.0, 100.0, 40.0],   # Older row -> SELL
            [110.0, 100.0, 60.0],  # Latest row -> BUY
        ],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.75
