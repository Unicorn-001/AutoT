"""
Regression tests for the AutoT Bollinger Bands strategy.
"""

import pandas as pd

from autot.strategies.bollinger_strategy_class import BollingerStrategy


def make_bollinger_data(
    close: float,
    upper_band: float,
    lower_band: float,
) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("BB_UPPER", ""),
            ("BB_LOWER", ""),
        ]
    )

    return pd.DataFrame(
        [[close, upper_band, lower_band]],
        columns=columns,
    )


def test_bollinger_buy_below_lower_band():
    strategy = BollingerStrategy()
    data = make_bollinger_data(
        close=90.0,
        upper_band=110.0,
        lower_band=95.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.65
    assert "at or below lower Bollinger Band" in result["reason"]


def test_bollinger_sell_above_upper_band():
    strategy = BollingerStrategy()
    data = make_bollinger_data(
        close=115.0,
        upper_band=110.0,
        lower_band=95.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.65
    assert "at or above upper Bollinger Band" in result["reason"]


def test_bollinger_hold_between_bands():
    strategy = BollingerStrategy()
    data = make_bollinger_data(
        close=100.0,
        upper_band=110.0,
        lower_band=95.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5
    assert "between Bollinger Bands" in result["reason"]


def test_bollinger_empty_data():
    strategy = BollingerStrategy()

    result = strategy.generate_signal(pd.DataFrame())

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "No data available."


# =========================================================
# Band boundary behaviour
# =========================================================

def test_bollinger_exactly_at_lower_band_is_buy():
    strategy = BollingerStrategy()

    data = make_bollinger_data(
        close=95.0,
        upper_band=110.0,
        lower_band=95.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.65


def test_bollinger_exactly_at_upper_band_is_sell():
    strategy = BollingerStrategy()

    data = make_bollinger_data(
        close=110.0,
        upper_band=110.0,
        lower_band=95.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.65


# =========================================================
# Missing indicator data
# =========================================================

def test_bollinger_missing_upper_band_returns_hold():
    strategy = BollingerStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("BB_LOWER", ""),
        ]
    )

    data = pd.DataFrame(
        [[100.0, 95.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_bollinger_missing_lower_band_returns_hold():
    strategy = BollingerStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("BB_UPPER", ""),
        ]
    )

    data = pd.DataFrame(
        [[100.0, 110.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Column ordering
# =========================================================

def test_bollinger_close_does_not_need_to_be_first_column():
    strategy = BollingerStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("BB_UPPER", ""),
            ("BB_LOWER", ""),
            ("Close", "TEST"),
        ]
    )

    data = pd.DataFrame(
        [[110.0, 95.0, 90.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.65


def test_bollinger_missing_close_returns_hold():
    strategy = BollingerStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("BB_UPPER", ""),
            ("BB_LOWER", ""),
        ]
    )

    data = pd.DataFrame(
        [[110.0, 95.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0
    assert result["reason"] == "Missing Close data."


# =========================================================
# Invalid / NaN data
# =========================================================

def test_bollinger_nan_close_returns_hold():
    strategy = BollingerStrategy()

    data = make_bollinger_data(
        close=float("nan"),
        upper_band=110.0,
        lower_band=95.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_bollinger_nan_upper_band_returns_hold():
    strategy = BollingerStrategy()

    data = make_bollinger_data(
        close=100.0,
        upper_band=float("nan"),
        lower_band=95.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_bollinger_nan_lower_band_returns_hold():
    strategy = BollingerStrategy()

    data = make_bollinger_data(
        close=100.0,
        upper_band=110.0,
        lower_band=float("nan"),
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Latest row behaviour
# =========================================================

def test_bollinger_uses_latest_row():
    strategy = BollingerStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("BB_UPPER", ""),
            ("BB_LOWER", ""),
        ]
    )

    data = pd.DataFrame(
        [
            [90.0, 110.0, 95.0],   # BUY
            [115.0, 110.0, 95.0],  # SELL - latest row
        ],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.65
