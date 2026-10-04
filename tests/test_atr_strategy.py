import pandas as pd

from autot.strategies.atr_strategy_class import AtrStrategy


def make_atr_data(
    latest_atr: float,
    close: float,
    ema_20: float,
) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("EMA_20", ""),
            ("ATR", ""),
        ]
    )

    rows = []

    # Previous 19 rows use ATR = 10.
    for _ in range(19):
        rows.append([100.0, 100.0, 10.0])

    # Latest row controls the signal.
    rows.append([close, ema_20, latest_atr])

    return pd.DataFrame(
        rows,
        columns=columns,
    )


def test_atr_buy_when_volatility_high_and_price_above_ema():
    strategy = AtrStrategy()

    data = make_atr_data(
        latest_atr=20.0,
        close=110.0,
        ema_20=100.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.7


def test_atr_sell_when_volatility_high_and_price_below_ema():
    strategy = AtrStrategy()

    data = make_atr_data(
        latest_atr=20.0,
        close=90.0,
        ema_20=100.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.7


def test_atr_hold_when_atr_is_not_above_average():
    strategy = AtrStrategy()

    data = make_atr_data(
        latest_atr=10.0,
        close=110.0,
        ema_20=100.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_atr_empty_data_returns_hold():
    strategy = AtrStrategy()

    data = pd.DataFrame()

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Boundary conditions
# =========================================================

def test_atr_equal_to_average_returns_hold():
    strategy = AtrStrategy()

    data = make_atr_data(
        latest_atr=10.0,
        close=110.0,
        ema_20=100.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_atr_close_equal_to_ema_returns_hold():
    strategy = AtrStrategy()

    data = make_atr_data(
        latest_atr=20.0,
        close=100.0,
        ema_20=100.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


# =========================================================
# Missing indicator data
# =========================================================

def test_atr_missing_ema_returns_hold():
    strategy = AtrStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("ATR", ""),
        ]
    )

    data = pd.DataFrame(
        [[100.0, 10.0]] * 20,
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_atr_missing_atr_returns_hold():
    strategy = AtrStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("EMA_20", ""),
        ]
    )

    data = pd.DataFrame(
        [[100.0, 100.0]] * 20,
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Insufficient history
# =========================================================

def test_atr_insufficient_history_returns_hold():
    strategy = AtrStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("EMA_20", ""),
            ("ATR", ""),
        ]
    )

    data = pd.DataFrame(
        [[110.0, 100.0, 10.0]] * 19,
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Close column handling
# =========================================================

def test_atr_close_column_does_not_need_to_be_first():
    strategy = AtrStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("EMA_20", ""),
            ("Close", "TEST"),
            ("ATR", ""),
        ]
    )

    rows = []

    for _ in range(19):
        rows.append([100.0, 100.0, 10.0])

    rows.append([100.0, 110.0, 20.0])

    data = pd.DataFrame(
        rows,
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.7


def test_atr_missing_close_returns_hold():
    strategy = AtrStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("EMA_20", ""),
            ("ATR", ""),
        ]
    )

    data = pd.DataFrame(
        [[100.0, 10.0]] * 20,
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Invalid numeric data
# =========================================================

def test_atr_nan_close_returns_hold():
    strategy = AtrStrategy()

    data = make_atr_data(
        latest_atr=20.0,
        close=float("nan"),
        ema_20=100.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_atr_nan_ema_returns_hold():
    strategy = AtrStrategy()

    data = make_atr_data(
        latest_atr=20.0,
        close=110.0,
        ema_20=float("nan"),
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_atr_nan_atr_returns_hold():
    strategy = AtrStrategy()

    data = make_atr_data(
        latest_atr=float("nan"),
        close=110.0,
        ema_20=100.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_atr_nan_in_history_returns_hold():
    strategy = AtrStrategy()

    data = make_atr_data(
        latest_atr=20.0,
        close=110.0,
        ema_20=100.0,
    )

    # Corrupt one ATR value inside the 20-period averaging window.
    data.loc[5, ("ATR", "")] = float("nan")

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Latest row handling
# =========================================================

def test_atr_uses_latest_row():
    strategy = AtrStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("EMA_20", ""),
            ("ATR", ""),
        ]
    )

    rows = []

    # First 19 rows keep the ATR baseline low.
    for _ in range(19):
        rows.append([100.0, 100.0, 10.0])

    # Penultimate row looks like a SELL.
    rows.append([90.0, 100.0, 20.0])

    # Latest row looks like a BUY.
    rows.append([110.0, 100.0, 20.0])

    data = pd.DataFrame(
        rows,
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.7
