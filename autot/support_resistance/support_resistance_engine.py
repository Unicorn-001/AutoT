"""
File: support_resistance_engine.py
Project: AutoT

Purpose:
    Estimate nearby support and resistance levels for
    swing-trade opportunity evaluation.
"""

import pandas as pd


class SupportResistanceEngine:
    """
    Calculates simple recent support/resistance levels
    and evaluates the available trading room.
    """

    @staticmethod
    def calculate(
        data: pd.DataFrame,
        signal: str,
        lookback: int = 20,
    ) -> dict:

        if len(data) < lookback:
            return {
                "nearest_support": 0.0,
                "nearest_resistance": 0.0,
                "distance_to_support_percent": 0.0,
                "distance_to_resistance_percent": 0.0,
                "support_resistance_score": 0.0,
                "support_resistance_label": "INSUFFICIENT_DATA",
            }

        close_series = data["Close"]
        high_series = data["High"]
        low_series = data["Low"]

        # Handle possible DataFrame columns from yfinance.
        if isinstance(close_series, pd.DataFrame):
            close_series = close_series.iloc[:, 0]

        if isinstance(high_series, pd.DataFrame):
            high_series = high_series.iloc[:, 0]

        if isinstance(low_series, pd.DataFrame):
            low_series = low_series.iloc[:, 0]

        close_series = pd.to_numeric(
            close_series,
            errors="coerce",
        )

        high_series = pd.to_numeric(
            high_series,
            errors="coerce",
        )

        low_series = pd.to_numeric(
            low_series,
            errors="coerce",
        )

        latest_close = float(close_series.iloc[-1])

        # Exclude current candle so today's price does not
        # become its own support/resistance level.
        previous_highs = high_series.iloc[-lookback - 1:-1]
        previous_lows = low_series.iloc[-lookback - 1:-1]

        if previous_highs.empty or previous_lows.empty:
            return {
                "nearest_support": 0.0,
                "nearest_resistance": 0.0,
                "distance_to_support_percent": 0.0,
                "distance_to_resistance_percent": 0.0,
                "support_resistance_score": 0.0,
                "support_resistance_label": "INSUFFICIENT_DATA",
            }

        nearest_support = float(previous_lows.min())
        nearest_resistance = float(previous_highs.max())

        distance_to_support = (
            (latest_close - nearest_support)
            / latest_close
            * 100
        )

        distance_to_resistance = (
            (nearest_resistance - latest_close)
            / latest_close
            * 100
        )

        signal = signal.upper()

        if signal == "BUY":
            available_room = distance_to_resistance
        elif signal == "SELL":
            available_room = distance_to_support
        else:
            available_room = 0.0

        if available_room >= 10:
            score = 100.0
            label = "EXCELLENT_ROOM"
        elif available_room >= 7:
            score = 85.0
            label = "GOOD_ROOM"
        elif available_room >= 5:
            score = 70.0
            label = "ACCEPTABLE_ROOM"
        elif available_room >= 3:
            score = 50.0
            label = "LIMITED_ROOM"
        elif available_room > 0:
            score = 25.0
            label = "NEAR_KEY_LEVEL"
        else:
            score = 10.0
            label = "LEVEL_BROKEN"

        return {
            "nearest_support": round(nearest_support, 2),
            "nearest_resistance": round(nearest_resistance, 2),
            "distance_to_support_percent": round(
                distance_to_support, 2
            ),
            "distance_to_resistance_percent": round(
                distance_to_resistance, 2
            ),
            "support_resistance_score": score,
            "support_resistance_label": label,
        }