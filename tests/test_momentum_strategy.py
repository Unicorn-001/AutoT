import pandas as pd

from autot.strategies.momentum_strategy_class import MomentumStrategy


def make_momentum_data(momentum: float) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples(
        [
            ("MOMENTUM", ""),
        ]
    )

    return pd.DataFrame(
        [[momentum]],
        columns=columns,
    )


# =========================================================
# Core signal behaviour
# =========================================================

def test_momentum_positive_returns_buy():
    strategy = MomentumStrategy()

    data = make_momentum_data(5.0)

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.7


def test_momentum_negative_returns_sell():
    strategy = MomentumStrategy()

    data = make_momentum_data(-5.0)

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.7


def test_momentum_zero_returns_hold():
    strategy = MomentumStrategy()

    data = make_momentum_data(0.0)

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_momentum_empty_data_returns_hold():
    strategy = MomentumStrategy()

    data = pd.DataFrame()

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Missing data handling
# =========================================================

def test_momentum_missing_column_returns_hold():
    strategy = MomentumStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
        ]
    )

    data = pd.DataFrame(
        [[100.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Invalid numeric data
# =========================================================

def test_momentum_nan_returns_hold():
    strategy = MomentumStrategy()

    data = make_momentum_data(float("nan"))

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Latest row handling
# =========================================================

def test_momentum_uses_latest_row():
    strategy = MomentumStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("MOMENTUM", ""),
        ]
    )

    data = pd.DataFrame(
        [
            [-10.0],
            [5.0],
        ],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.7
