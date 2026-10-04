import pandas as pd

from autot.strategies.stochastic_strategy_class import StochasticStrategy


def make_stochastic_data(
    stoch_k: float,
    stoch_d: float,
) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples(
        [
            ("STOCH_K", ""),
            ("STOCH_D", ""),
        ]
    )

    return pd.DataFrame(
        [[stoch_k, stoch_d]],
        columns=columns,
    )


# =========================================================
# Core signal behaviour
# =========================================================

def test_stochastic_oversold_k_above_d_returns_buy():
    strategy = StochasticStrategy()

    data = make_stochastic_data(
        stoch_k=15.0,
        stoch_d=10.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.7


def test_stochastic_overbought_k_below_d_returns_sell():
    strategy = StochasticStrategy()

    data = make_stochastic_data(
        stoch_k=85.0,
        stoch_d=90.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.7


def test_stochastic_no_reversal_returns_hold():
    strategy = StochasticStrategy()

    data = make_stochastic_data(
        stoch_k=50.0,
        stoch_d=45.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_stochastic_empty_data_returns_hold():
    strategy = StochasticStrategy()

    result = strategy.generate_signal(pd.DataFrame())

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Threshold boundaries
# =========================================================

def test_stochastic_k_equal_20_returns_hold():
    strategy = StochasticStrategy()

    data = make_stochastic_data(
        stoch_k=20.0,
        stoch_d=10.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_stochastic_k_equal_80_returns_hold():
    strategy = StochasticStrategy()

    data = make_stochastic_data(
        stoch_k=80.0,
        stoch_d=90.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


# =========================================================
# Missing data handling
# =========================================================

def test_stochastic_missing_k_returns_hold():
    strategy = StochasticStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("STOCH_D", ""),
        ]
    )

    data = pd.DataFrame(
        [[10.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_stochastic_missing_d_returns_hold():
    strategy = StochasticStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("STOCH_K", ""),
        ]
    )

    data = pd.DataFrame(
        [[15.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Invalid data handling
# =========================================================

def test_stochastic_nan_k_returns_hold_with_zero_confidence():
    strategy = StochasticStrategy()

    data = make_stochastic_data(
        stoch_k=float("nan"),
        stoch_d=10.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_stochastic_nan_d_returns_hold_with_zero_confidence():
    strategy = StochasticStrategy()

    data = make_stochastic_data(
        stoch_k=15.0,
        stoch_d=float("nan"),
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Latest row behaviour
# =========================================================

def test_stochastic_uses_latest_row():
    strategy = StochasticStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("STOCH_K", ""),
            ("STOCH_D", ""),
        ]
    )

    data = pd.DataFrame(
        [
            [85.0, 90.0],  # Earlier row would produce SELL
            [15.0, 10.0],  # Latest row should produce BUY
        ],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.7
