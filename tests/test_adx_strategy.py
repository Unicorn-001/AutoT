import pandas as pd

from autot.strategies.adx_strategy_class import AdxStrategy


def make_adx_data(
    adx: float,
    di_plus: float,
    di_minus: float,
) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples(
        [
            ("ADX", ""),
            ("DI_PLUS", ""),
            ("DI_MINUS", ""),
        ]
    )

    return pd.DataFrame(
        [[adx, di_plus, di_minus]],
        columns=columns,
    )


def test_adx_buy_when_strong_bullish_trend():
    strategy = AdxStrategy()

    data = make_adx_data(
        adx=30.0,
        di_plus=25.0,
        di_minus=15.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.75


def test_adx_sell_when_strong_bearish_trend():
    strategy = AdxStrategy()

    data = make_adx_data(
        adx=30.0,
        di_plus=15.0,
        di_minus=25.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.75


def test_adx_hold_when_trend_is_not_strong():
    strategy = AdxStrategy()

    data = make_adx_data(
        adx=20.0,
        di_plus=25.0,
        di_minus=15.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_adx_empty_data_returns_hold():
    strategy = AdxStrategy()

    data = pd.DataFrame()

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Boundary conditions
# =========================================================

def test_adx_exactly_25_returns_hold():
    strategy = AdxStrategy()

    data = make_adx_data(
        adx=25.0,
        di_plus=30.0,
        di_minus=10.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


# =========================================================
# Missing indicator data
# =========================================================

def test_adx_missing_adx_returns_hold():
    strategy = AdxStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("DI_PLUS", ""),
            ("DI_MINUS", ""),
        ]
    )

    data = pd.DataFrame(
        [[25.0, 15.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_adx_missing_di_plus_returns_hold():
    strategy = AdxStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("ADX", ""),
            ("DI_MINUS", ""),
        ]
    )

    data = pd.DataFrame(
        [[30.0, 15.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_adx_missing_di_minus_returns_hold():
    strategy = AdxStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("ADX", ""),
            ("DI_PLUS", ""),
        ]
    )

    data = pd.DataFrame(
        [[30.0, 25.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Invalid / NaN indicator data
# =========================================================

def test_adx_nan_adx_returns_hold():
    strategy = AdxStrategy()

    data = make_adx_data(
        adx=float("nan"),
        di_plus=25.0,
        di_minus=15.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_adx_nan_di_plus_returns_hold():
    strategy = AdxStrategy()

    data = make_adx_data(
        adx=30.0,
        di_plus=float("nan"),
        di_minus=15.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_adx_nan_di_minus_returns_hold():
    strategy = AdxStrategy()

    data = make_adx_data(
        adx=30.0,
        di_plus=25.0,
        di_minus=float("nan"),
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_adx_equal_directional_indicators_returns_hold():
    strategy = AdxStrategy()

    data = make_adx_data(
        adx=30.0,
        di_plus=20.0,
        di_minus=20.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_adx_uses_latest_row():
    strategy = AdxStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("ADX", ""),
            ("DI_PLUS", ""),
            ("DI_MINUS", ""),
        ]
    )

    data = pd.DataFrame(
        [
            [30.0, 25.0, 15.0],  # Older row -> BUY
            [30.0, 15.0, 25.0],  # Latest row -> SELL
        ],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.75
