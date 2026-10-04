import pandas as pd

from autot.strategies.supertrend_strategy_class import SuperTrendStrategy


def make_supertrend_data(
    close: float,
    lower_band: float,
    direction: bool,
) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("SUPERTREND_LOWER", ""),
            ("SUPERTREND_DIRECTION", ""),
        ]
    )

    return pd.DataFrame(
        [[close, lower_band, direction]],
        columns=columns,
    )


def test_supertrend_buy_when_direction_is_bullish():
    strategy = SuperTrendStrategy()

    data = make_supertrend_data(
        close=105.0,
        lower_band=100.0,
        direction=True,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.75


def test_supertrend_sell_when_direction_is_bearish():
    strategy = SuperTrendStrategy()

    data = make_supertrend_data(
        close=95.0,
        lower_band=100.0,
        direction=False,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.75


def test_supertrend_empty_data_returns_hold():
    strategy = SuperTrendStrategy()

    data = pd.DataFrame()

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Missing indicator data
# =========================================================

def test_supertrend_missing_lower_band_returns_hold():
    strategy = SuperTrendStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("SUPERTREND_DIRECTION", ""),
        ]
    )

    data = pd.DataFrame(
        [[105.0, True]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_supertrend_missing_direction_returns_hold():
    strategy = SuperTrendStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("SUPERTREND_LOWER", ""),
        ]
    )

    data = pd.DataFrame(
        [[105.0, 100.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_supertrend_close_does_not_need_to_be_first_column():
    strategy = SuperTrendStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("SUPERTREND_LOWER", ""),
            ("SUPERTREND_DIRECTION", ""),
            ("Close", "TEST"),
        ]
    )

    data = pd.DataFrame(
        [[100.0, True, 105.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.75


def test_supertrend_missing_close_returns_hold():
    strategy = SuperTrendStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("SUPERTREND_LOWER", ""),
            ("SUPERTREND_DIRECTION", ""),
        ]
    )

    data = pd.DataFrame(
        [[100.0, True]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Invalid / NaN data
# =========================================================

def test_supertrend_nan_close_returns_hold():
    strategy = SuperTrendStrategy()

    data = make_supertrend_data(
        close=float("nan"),
        lower_band=100.0,
        direction=True,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_supertrend_nan_lower_band_returns_hold():
    strategy = SuperTrendStrategy()

    data = make_supertrend_data(
        close=105.0,
        lower_band=float("nan"),
        direction=True,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_supertrend_nan_direction_returns_hold():
    strategy = SuperTrendStrategy()

    data = make_supertrend_data(
        close=105.0,
        lower_band=100.0,
        direction=float("nan"),
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_supertrend_uses_latest_row():
    strategy = SuperTrendStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("SUPERTREND_LOWER", ""),
            ("SUPERTREND_DIRECTION", ""),
        ]
    )

    data = pd.DataFrame(
        [
            [105.0, 100.0, True],
            [95.0, 100.0, False],
        ],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.75
