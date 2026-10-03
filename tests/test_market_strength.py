"""
Regression tests for AutoT market-strength engines.
"""

import pandas as pd
import pytest

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


# =========================================================
# Support / Resistance
# =========================================================

from autot.support_resistance.support_resistance_engine import (
    SupportResistanceEngine,
)


def make_support_resistance_data(
    latest_close=100.0,
    resistance=110.0,
    support=90.0,
    periods=70,
):
    """
    Create deterministic OHLC data containing one clear
    pivot support and one clear pivot resistance.
    """

    close = [100.0] * periods

    # Use non-flat background values so ordinary points
    # are not falsely detected as pivots.
    high = [
        100.5 + (i * 0.001)
        for i in range(periods)
    ]
    low = [
        99.5 + (i * 0.001)
        for i in range(periods)
    ]

    # Create one clear pivot high.
    high[-20] = resistance

    # Create one clear pivot low.
    low[-40] = support

    close[-1] = latest_close

    return pd.DataFrame(
        {
            "Close": close,
            "High": high,
            "Low": low,
        }
    )

def test_support_resistance_buy_with_excellent_room():
    data = make_support_resistance_data(
        latest_close=100.0,
        resistance=110.0,
        support=90.0,
    )

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["nearest_support"] == 90.0
    assert result["nearest_resistance"] == 110.0
    assert result["distance_to_support_percent"] == 10.0
    assert result["distance_to_resistance_percent"] == 10.0
    assert result["support_resistance_score"] == 100.0
    assert result["support_resistance_label"] == "EXCELLENT_ROOM"


def test_support_resistance_buy_near_resistance():
    data = make_support_resistance_data(
        latest_close=100.0,
        resistance=102.0,
        support=90.0,
    )

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["nearest_resistance"] == 102.0
    assert result["distance_to_resistance_percent"] == 2.0
    assert result["support_resistance_score"] == 40.0
    assert result["support_resistance_label"] == "NEAR_RESISTANCE"


def test_support_resistance_sell_with_excellent_room():
    data = make_support_resistance_data(
        latest_close=100.0,
        resistance=110.0,
        support=90.0,
    )

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="SELL",
    )

    assert result["nearest_support"] == 90.0
    assert result["distance_to_support_percent"] == 10.0
    assert result["support_resistance_score"] == 100.0
    assert result["support_resistance_label"] == "EXCELLENT_ROOM"


def test_support_resistance_sell_near_support():
    data = make_support_resistance_data(
        latest_close=100.0,
        resistance=110.0,
        support=98.0,
    )

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="SELL",
    )

    assert result["nearest_support"] == 98.0
    assert result["distance_to_support_percent"] == 2.0
    assert result["support_resistance_score"] == 40.0
    assert result["support_resistance_label"] == "NEAR_SUPPORT"


def test_support_resistance_hold_returns_no_trade():
    data = make_support_resistance_data()

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="HOLD",
    )

    assert result["support_resistance_score"] == 0.0
    assert result["support_resistance_label"] == "NO_TRADE"


def test_support_resistance_insufficient_data():
    data = make_support_resistance_data(
        periods=60,
    )

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["nearest_support"] == 0.0
    assert result["nearest_resistance"] == 0.0
    assert result["support_resistance_score"] == 0.0
    assert result["support_resistance_label"] == "INSUFFICIENT_DATA"


# =========================================================
# Support/Resistance scoring boundaries
# =========================================================

def test_support_resistance_buy_exact_boundaries():
    cases = [
        (101.0, 60.0, "BREAKOUT_ZONE"),
        (103.0, 40.0, "NEAR_RESISTANCE"),
        (105.0, 60.0, "LIMITED_ROOM"),
        (108.0, 80.0, "GOOD_ROOM"),
    ]

    for resistance, expected_score, expected_label in cases:
        data = make_support_resistance_data(
            latest_close=100.0,
            resistance=resistance,
            support=90.0,
        )

        result = SupportResistanceEngine.calculate(
            data=data,
            signal="BUY",
        )

        assert result["nearest_resistance"] == resistance
        assert result["support_resistance_score"] == expected_score
        assert result["support_resistance_label"] == expected_label


def test_support_resistance_sell_exact_boundaries():
    cases = [
        (99.0, 60.0, "BREAKDOWN_ZONE"),
        (97.0, 40.0, "NEAR_SUPPORT"),
        (95.0, 60.0, "LIMITED_ROOM"),
        (92.0, 80.0, "GOOD_ROOM"),
    ]

    for support, expected_score, expected_label in cases:
        data = make_support_resistance_data(
            latest_close=100.0,
            resistance=110.0,
            support=support,
        )

        result = SupportResistanceEngine.calculate(
            data=data,
            signal="SELL",
        )

        assert result["nearest_support"] == support
        assert result["support_resistance_score"] == expected_score
        assert result["support_resistance_label"] == expected_label


def test_support_resistance_buy_open_space():
    data = make_support_resistance_data(
        latest_close=120.0,
        resistance=110.0,
        support=90.0,
    )

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["nearest_resistance"] == 0.0
    assert result["distance_to_resistance_percent"] == 0.0
    assert result["support_resistance_score"] == 85.0
    assert result["support_resistance_label"] == "OPEN_SPACE"


def test_support_resistance_sell_open_space():
    data = make_support_resistance_data(
        latest_close=80.0,
        resistance=110.0,
        support=90.0,
    )

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="SELL",
    )

    assert result["nearest_support"] == 0.0
    assert result["distance_to_support_percent"] == 0.0
    assert result["support_resistance_score"] == 85.0
    assert result["support_resistance_label"] == "OPEN_SPACE"


def test_support_resistance_signal_is_case_insensitive():
    data = make_support_resistance_data(
        latest_close=100.0,
        resistance=110.0,
        support=90.0,
    )

    upper = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    lower = SupportResistanceEngine.calculate(
        data=data,
        signal="buy",
    )

    assert lower == upper


def test_support_resistance_unsupported_signal_returns_no_trade():
    data = make_support_resistance_data()

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="INVALID",
    )

    assert result["support_resistance_score"] == 0.0
    assert result["support_resistance_label"] == "NO_TRADE"


# =========================================================
# Support/Resistance input validation
# =========================================================

def test_support_resistance_missing_close_column():
    data = make_support_resistance_data()
    data = data.drop(columns=["Close"])

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["support_resistance_score"] == 0.0
    assert result["support_resistance_label"] == "NO_CLOSE_DATA"


def test_support_resistance_missing_high_column():
    data = make_support_resistance_data()
    data = data.drop(columns=["High"])

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["support_resistance_score"] == 0.0
    assert result["support_resistance_label"] == "NO_HIGH_DATA"


def test_support_resistance_missing_low_column():
    data = make_support_resistance_data()
    data = data.drop(columns=["Low"])

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["support_resistance_score"] == 0.0
    assert result["support_resistance_label"] == "NO_LOW_DATA"


def test_support_resistance_zero_latest_close():
    data = make_support_resistance_data()
    data.loc[data.index[-1], "Close"] = 0.0

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["support_resistance_score"] == 0.0
    assert result["support_resistance_label"] == "INVALID_CLOSE_PRICE"


def test_support_resistance_negative_latest_close():
    data = make_support_resistance_data()
    data.loc[data.index[-1], "Close"] = -100.0

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["support_resistance_score"] == 0.0
    assert result["support_resistance_label"] == "INVALID_CLOSE_PRICE"


def test_support_resistance_nan_latest_close():
    data = make_support_resistance_data()
    data.loc[data.index[-1], "Close"] = float("nan")

    result = SupportResistanceEngine.calculate(
        data=data,
        signal="BUY",
    )

    assert result["support_resistance_score"] == 0.0
    assert result["support_resistance_label"] == "INVALID_CLOSE_PRICE"


def test_support_resistance_invalid_lookback():
    data = make_support_resistance_data()

    with pytest.raises(ValueError):
        SupportResistanceEngine.calculate(
            data=data,
            signal="BUY",
            lookback=0,
        )


def test_support_resistance_invalid_pivot_window():
    data = make_support_resistance_data()

    with pytest.raises(ValueError):
        SupportResistanceEngine.calculate(
            data=data,
            signal="BUY",
            pivot_window=0,
        )
