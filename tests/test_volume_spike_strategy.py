import pandas as pd

from autot.strategies.volume_spike_strategy_class import VolumeSpikeStrategy


def make_volume_spike_data(
    close: float,
    ema_20: float,
    volume_ratio: float,
) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("EMA_20", ""),
            ("VOLUME_RATIO", ""),
        ]
    )

    return pd.DataFrame(
        [[close, ema_20, volume_ratio]],
        columns=columns,
    )


# =========================================================
# Core signal behaviour
# =========================================================

def test_volume_spike_high_volume_above_ema_returns_buy():
    strategy = VolumeSpikeStrategy()

    data = make_volume_spike_data(
        close=105.0,
        ema_20=100.0,
        volume_ratio=2.5,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.75


def test_volume_spike_high_volume_below_ema_returns_sell():
    strategy = VolumeSpikeStrategy()

    data = make_volume_spike_data(
        close=95.0,
        ema_20=100.0,
        volume_ratio=2.5,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "SELL"
    assert result["confidence"] == 0.75


def test_volume_spike_low_volume_returns_hold():
    strategy = VolumeSpikeStrategy()

    data = make_volume_spike_data(
        close=105.0,
        ema_20=100.0,
        volume_ratio=1.5,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


def test_volume_spike_empty_data_returns_hold():
    strategy = VolumeSpikeStrategy()

    result = strategy.generate_signal(pd.DataFrame())

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Boundary behaviour
# =========================================================

def test_volume_spike_ratio_equal_2_above_ema_returns_buy():
    strategy = VolumeSpikeStrategy()

    data = make_volume_spike_data(
        close=105.0,
        ema_20=100.0,
        volume_ratio=2.0,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.75


def test_volume_spike_close_equal_ema_returns_hold():
    strategy = VolumeSpikeStrategy()

    data = make_volume_spike_data(
        close=100.0,
        ema_20=100.0,
        volume_ratio=2.5,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.5


# =========================================================
# Missing data handling
# =========================================================

def test_volume_spike_missing_ema_returns_hold():
    strategy = VolumeSpikeStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("VOLUME_RATIO", ""),
        ]
    )

    data = pd.DataFrame(
        [[105.0, 2.5]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_volume_spike_missing_volume_ratio_returns_hold():
    strategy = VolumeSpikeStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("EMA_20", ""),
        ]
    )

    data = pd.DataFrame(
        [[105.0, 100.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_volume_spike_close_lookup_does_not_depend_on_column_order():
    strategy = VolumeSpikeStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("EMA_20", ""),
            ("VOLUME_RATIO", ""),
            ("Close", "TEST"),
        ]
    )

    data = pd.DataFrame(
        [[100.0, 2.5, 105.0]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.75


def test_volume_spike_missing_close_returns_hold():
    strategy = VolumeSpikeStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("EMA_20", ""),
            ("VOLUME_RATIO", ""),
        ]
    )

    data = pd.DataFrame(
        [[100.0, 2.5]],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


# =========================================================
# Invalid data handling
# =========================================================

def test_volume_spike_nan_close_returns_hold():
    strategy = VolumeSpikeStrategy()

    data = make_volume_spike_data(
        close=float("nan"),
        ema_20=100.0,
        volume_ratio=2.5,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_volume_spike_nan_ema_returns_hold():
    strategy = VolumeSpikeStrategy()

    data = make_volume_spike_data(
        close=105.0,
        ema_20=float("nan"),
        volume_ratio=2.5,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_volume_spike_nan_volume_ratio_returns_hold():
    strategy = VolumeSpikeStrategy()

    data = make_volume_spike_data(
        close=105.0,
        ema_20=100.0,
        volume_ratio=float("nan"),
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0.0


def test_volume_spike_uses_latest_row():
    strategy = VolumeSpikeStrategy()

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("EMA_20", ""),
            ("VOLUME_RATIO", ""),
        ]
    )

    data = pd.DataFrame(
        [
            [95.0, 100.0, 2.5],   # Earlier row -> SELL
            [105.0, 100.0, 2.5],  # Latest row -> BUY
        ],
        columns=columns,
    )

    result = strategy.generate_signal(data)

    assert result["signal"] == "BUY"
    assert result["confidence"] == 0.75
