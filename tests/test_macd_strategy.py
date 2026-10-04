"""
Regression tests for the AutoT MACD strategy.
"""

import pandas as pd

from autot.strategies.macd_strategy_class import MacdStrategy


def make_macd_data(
    macd: float,
    macd_signal: float,
) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples(
        [
            ("MACD", ""),
            ("MACD_SIGNAL", ""),
        ]
    )

    return pd.DataFrame(
        [[macd, macd_signal]],
        columns=columns,
    )


def test_macd_buy_signal():
    strategy = MacdStrategy()
    data = make_macd_data(
        macd=2.0,
        macd_signal=1.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.7
    assert "above signal line" in result["reason"]


def test_macd_sell_signal():
    strategy = MacdStrategy()
    data = make_macd_data(
        macd=1.0,
        macd_signal=2.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.7
    assert "below signal line" in result["reason"]


def test_macd_equal_values_are_hold():
    strategy = MacdStrategy()
    data = make_macd_data(
        macd=1.0,
        macd_signal=1.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5
    assert "equal to signal line" in result["reason"]


def test_macd_empty_data():
    strategy = MacdStrategy()

    result = strategy.generate_signal(pd.DataFrame())

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "No data available."


# =========================================================
# Missing indicator data
# =========================================================

def test_macd_missing_macd_returns_hold():
    strategy = MacdStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("MACD_SIGNAL", ""),
        ]
    )

    data = pd.DataFrame(
        [[1.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_macd_missing_signal_returns_hold():
    strategy = MacdStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("MACD", ""),
        ]
    )

    data = pd.DataFrame(
        [[1.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Invalid indicator values
# =========================================================

def test_macd_nan_macd_returns_hold():
    strategy = MacdStrategy()

    data = make_macd_data(
        macd=float("nan"),
        macd_signal=1.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_macd_nan_signal_returns_hold():
    strategy = MacdStrategy()

    data = make_macd_data(
        macd=1.0,
        macd_signal=float("nan"),
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Missing indicator data
# =========================================================

def test_macd_missing_macd_returns_hold():
    strategy = MacdStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("MACD_SIGNAL", ""),
        ]
    )

    data = pd.DataFrame(
        [[1.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_macd_missing_signal_returns_hold():
    strategy = MacdStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("MACD", ""),
        ]
    )

    data = pd.DataFrame(
        [[1.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Latest-row behaviour
# =========================================================

def test_macd_uses_latest_row():
    strategy = MacdStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("MACD", ""),
            ("MACD_SIGNAL", ""),
        ]
    )

    data = pd.DataFrame(
        [
            [1.0, 2.0],  # Older row: SELL
            [2.0, 1.0],  # Latest row: BUY
        ],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.7
