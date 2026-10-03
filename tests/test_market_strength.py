"""
Regression tests for AutoT market-strength engines.
"""

import pandas as pd

from autot.trend_strength.trend_strength_engine import (
    TrendStrengthEngine,
)
from autot.volume_strength.volume_strength_engine import (
    VolumeStrengthEngine,
)


def make_trend_data(
    close,
    ema_20,
    ema_50,
    ema_200,
    adx,
):
    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
            ("EMA_20", "TEST"),
            ("EMA_50", "TEST"),
            ("EMA_200", "TEST"),
            ("ADX", "TEST"),
        ]
    )

    return pd.DataFrame(
        [[close, ema_20, ema_50, ema_200, adx]],
        columns=columns,
    )


def make_volume_data(
    latest_volume,
    previous_volume=100.0,
    periods=20,
):
    volumes = [previous_volume] * (periods - 1)
    volumes.append(latest_volume)

    columns = pd.MultiIndex.from_tuples(
        [
            ("Volume", "TEST"),
        ]
    )

    return pd.DataFrame(
        volumes,
        columns=columns,
    )


def test_very_strong_trend_scores_100():
    data = make_trend_data(
        close=120.0,
        ema_20=110.0,
        ema_50=100.0,
        ema_200=90.0,
        adx=30.0,
    )

    result = TrendStrengthEngine.calculate(data)

    assert result["trend_strength_score"] == 100.0
    assert result["trend_strength_label"] == "VERY_STRONG_TREND"


def test_no_trend_scores_zero():
    data = make_trend_data(
        close=80.0,
        ema_20=90.0,
        ema_50=100.0,
        ema_200=110.0,
        adx=10.0,
    )

    result = TrendStrengthEngine.calculate(data)

    assert result["trend_strength_score"] == 0.0
    assert result["trend_strength_label"] == "NO_TREND"


def test_adx_20_receives_partial_score():
    data = make_trend_data(
        close=80.0,
        ema_20=90.0,
        ema_50=100.0,
        ema_200=110.0,
        adx=20.0,
    )

    result = TrendStrengthEngine.calculate(data)

    assert result["trend_strength_score"] == 10.0
    assert result["trend_strength_label"] == "NO_TREND"


def test_adx_25_receives_full_adx_score():
    data = make_trend_data(
        close=80.0,
        ema_20=90.0,
        ema_50=100.0,
        ema_200=110.0,
        adx=25.0,
    )

    result = TrendStrengthEngine.calculate(data)

    assert result["trend_strength_score"] == 20.0
    assert result["trend_strength_label"] == "NO_TREND"


def test_volume_insufficient_data():
    data = make_volume_data(
        latest_volume=100.0,
        periods=19,
    )

    result = VolumeStrengthEngine.calculate(
        data,
        average_period=20,
    )

    assert result["volume_ratio"] == 0.0
    assert result["volume_strength_score"] == 0.0
    assert result["volume_strength_label"] == "INSUFFICIENT_DATA"
    assert result["volume_confirmed"] is False


def test_volume_missing_column():
    data = pd.DataFrame(
        {
            "Close": [100.0] * 20,
        }
    )

    result = VolumeStrengthEngine.calculate(
        data,
        average_period=20,
    )

    assert result["volume_ratio"] == 0.0
    assert result["volume_strength_score"] == 0.0
    assert result["volume_strength_label"] == "NO_VOLUME_DATA"
    assert result["volume_confirmed"] is False


def test_normal_volume_not_confirmed():
    data = make_volume_data(
        latest_volume=100.0,
        previous_volume=100.0,
    )

    result = VolumeStrengthEngine.calculate(data)

    assert result["volume_ratio"] == 1.0
    assert result["volume_strength_score"] == 50.0
    assert result["volume_strength_label"] == "NORMAL_VOLUME"
    assert result["volume_confirmed"] is False


def test_strong_volume_is_confirmed():
    # 19 periods at 100 + latest 200 gives:
    # average = 105
    # ratio = 200 / 105 = 1.90476...
    data = make_volume_data(
        latest_volume=200.0,
        previous_volume=100.0,
    )

    result = VolumeStrengthEngine.calculate(data)

    assert result["volume_ratio"] == 1.9
    assert result["volume_strength_score"] == 85.0
    assert result["volume_strength_label"] == "STRONG_VOLUME"
    assert result["volume_confirmed"] is True


def test_very_low_volume():
    data = make_volume_data(
        latest_volume=10.0,
        previous_volume=100.0,
    )

    result = VolumeStrengthEngine.calculate(data)

    assert result["volume_ratio"] == 0.1
    assert result["volume_strength_score"] == 10.0
    assert result["volume_strength_label"] == "VERY_LOW_VOLUME"
    assert result["volume_confirmed"] is False
