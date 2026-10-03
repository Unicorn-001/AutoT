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


# =========================================================
# Relative Strength
# =========================================================

from autot.relative_strength.relative_strength_engine import (
    RelativeStrengthEngine,
)


def make_close_data(
    start_price,
    end_price,
    periods=61,
):
    """
    Create deterministic Close-price data for the
    engine's default 60-period relative-strength lookback.
    """

    middle_count = periods - 2

    prices = (
        [start_price]
        + [start_price] * middle_count
        + [end_price]
    )

    columns = pd.MultiIndex.from_tuples(
        [
            ("Close", "TEST"),
        ]
    )

    return pd.DataFrame(
        prices,
        columns=columns,
    )


def test_relative_strength_very_strong_outperformance():
    stock_data = make_close_data(
        start_price=100.0,
        end_price=120.0,
    )

    benchmark_data = make_close_data(
        start_price=100.0,
        end_price=105.0,
    )

    result = RelativeStrengthEngine.calculate(
        stock_data=stock_data,
        benchmark_data=benchmark_data,
    )

    assert result["stock_return_percent"] == 20.0
    assert result["benchmark_return_percent"] == 5.0
    assert result["relative_strength_percent"] == 15.0
    assert result["relative_strength_score"] == 100.0
    assert (
        result["relative_strength_label"]
        == "VERY_STRONG_OUTPERFORMANCE"
    )


def test_relative_strength_outperforming():
    stock_data = make_close_data(
        start_price=100.0,
        end_price=110.0,
    )

    benchmark_data = make_close_data(
        start_price=100.0,
        end_price=105.0,
    )

    result = RelativeStrengthEngine.calculate(
        stock_data=stock_data,
        benchmark_data=benchmark_data,
    )

    assert result["stock_return_percent"] == 10.0
    assert result["benchmark_return_percent"] == 5.0
    assert result["relative_strength_percent"] == 5.0
    assert result["relative_strength_score"] == 70.0
    assert result["relative_strength_label"] == "OUTPERFORMING"


def test_relative_strength_equal_performance():
    stock_data = make_close_data(
        start_price=100.0,
        end_price=105.0,
    )

    benchmark_data = make_close_data(
        start_price=100.0,
        end_price=105.0,
    )

    result = RelativeStrengthEngine.calculate(
        stock_data=stock_data,
        benchmark_data=benchmark_data,
    )

    assert result["stock_return_percent"] == 5.0
    assert result["benchmark_return_percent"] == 5.0
    assert result["relative_strength_percent"] == 0.0
    assert result["relative_strength_score"] == 55.0
    assert (
        result["relative_strength_label"]
        == "SLIGHTLY_OUTPERFORMING"
    )


def test_relative_strength_underperforming():
    stock_data = make_close_data(
        start_price=100.0,
        end_price=95.0,
    )

    benchmark_data = make_close_data(
        start_price=100.0,
        end_price=105.0,
    )

    result = RelativeStrengthEngine.calculate(
        stock_data=stock_data,
        benchmark_data=benchmark_data,
    )

    assert result["stock_return_percent"] == -5.0
    assert result["benchmark_return_percent"] == 5.0
    assert result["relative_strength_percent"] == -10.0
    assert result["relative_strength_score"] == 25.0
    assert result["relative_strength_label"] == "UNDERPERFORMING"


def test_relative_strength_insufficient_stock_data():
    stock_data = make_close_data(
        start_price=100.0,
        end_price=110.0,
        periods=60,
    )

    benchmark_data = make_close_data(
        start_price=100.0,
        end_price=105.0,
        periods=61,
    )

    result = RelativeStrengthEngine.calculate(
        stock_data=stock_data,
        benchmark_data=benchmark_data,
    )

    assert result["stock_return_percent"] == 0.0
    assert result["benchmark_return_percent"] == 0.0
    assert result["relative_strength_percent"] == 0.0
    assert result["relative_strength_score"] == 0.0
    assert (
        result["relative_strength_label"]
        == "INSUFFICIENT_DATA"
    )


def test_relative_strength_custom_lookback():
    stock_data = make_close_data(
        start_price=100.0,
        end_price=115.0,
        periods=21,
    )

    benchmark_data = make_close_data(
        start_price=100.0,
        end_price=105.0,
        periods=21,
    )

    result = RelativeStrengthEngine.calculate(
        stock_data=stock_data,
        benchmark_data=benchmark_data,
        lookback=20,
    )

    assert result["stock_return_percent"] == 15.0
    assert result["benchmark_return_percent"] == 5.0
    assert result["relative_strength_percent"] == 10.0
    assert result["relative_strength_score"] == 85.0
    assert (
        result["relative_strength_label"]
        == "STRONG_OUTPERFORMANCE"
    )


def test_relative_strength_missing_close_column():
    stock_data = pd.DataFrame(
        {
            "Volume": [1000.0] * 61,
        }
    )

    benchmark_data = make_close_data(
        start_price=100.0,
        end_price=105.0,
    )

    result = RelativeStrengthEngine.calculate(
        stock_data=stock_data,
        benchmark_data=benchmark_data,
    )

    assert result["stock_return_percent"] == 0.0
    assert result["benchmark_return_percent"] == 0.0
    assert result["relative_strength_percent"] == 0.0
    assert result["relative_strength_score"] == 0.0
    assert result["relative_strength_label"] == "NO_CLOSE_DATA"


def test_relative_strength_zero_start_price():
    stock_data = make_close_data(
        start_price=0.0,
        end_price=100.0,
    )

    benchmark_data = make_close_data(
        start_price=100.0,
        end_price=105.0,
    )

    result = RelativeStrengthEngine.calculate(
        stock_data=stock_data,
        benchmark_data=benchmark_data,
    )

    assert result["stock_return_percent"] == 0.0
    assert result["benchmark_return_percent"] == 0.0
    assert result["relative_strength_percent"] == 0.0
    assert result["relative_strength_score"] == 0.0
    assert (
        result["relative_strength_label"]
        == "INVALID_START_PRICE"
    )
