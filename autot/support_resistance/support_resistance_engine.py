"""
File: support_resistance_engine.py
Project: AutoT

Purpose:
    Detect nearby support and resistance levels using
    recent pivot highs and pivot lows.
"""

import pandas as pd


class SupportResistanceEngine:
    """
    Calculates nearby support and resistance levels
    for swing-trade evaluation.
    """

    @staticmethod
    def calculate(
        data: pd.DataFrame,
        signal: str,
        lookback: int = 60,
        pivot_window: int = 3,
    ) -> dict:

        if len(data) < lookback + (pivot_window * 2):
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

        recent_highs = high_series.iloc[-lookback:]
        recent_lows = low_series.iloc[-lookback:]

        pivot_highs = []
        pivot_lows = []

        for i in range(
            pivot_window,
            len(recent_highs) - pivot_window,
        ):
            current_high = recent_highs.iloc[i]

            high_window = recent_highs.iloc[
                i - pivot_window:
                i + pivot_window + 1
            ]

            if current_high == high_window.max():
                pivot_highs.append(float(current_high))

            current_low = recent_lows.iloc[i]

            low_window = recent_lows.iloc[
                i - pivot_window:
                i + pivot_window + 1
            ]

            if current_low == low_window.min():
                pivot_lows.append(float(current_low))

        supports = [
            level
            for level in pivot_lows
            if level < latest_close
        ]

        resistances = [
            level
            for level in pivot_highs
            if level > latest_close
        ]

        nearest_support = (
            max(supports)
            if supports
            else 0.0
        )

        nearest_resistance = (
            min(resistances)
            if resistances
            else 0.0
        )

        if nearest_support > 0:
            distance_to_support = (
                (latest_close - nearest_support)
                / latest_close
                * 100
            )
        else:
            distance_to_support = 0.0

        if nearest_resistance > 0:
            distance_to_resistance = (
                (nearest_resistance - latest_close)
                / latest_close
                * 100
            )
        else:
            distance_to_resistance = 0.0

        signal = signal.upper()

        if signal == "BUY":

            if nearest_resistance == 0.0:
                score = 85.0
                label = "OPEN_SPACE"

            elif distance_to_resistance <= 1.0:
                score = 60.0
                label = "BREAKOUT_ZONE"

            elif distance_to_resistance <= 3.0:
                score = 40.0
                label = "NEAR_RESISTANCE"

            elif distance_to_resistance <= 5.0:
                score = 60.0
                label = "LIMITED_ROOM"

            elif distance_to_resistance <= 8.0:
                score = 80.0
                label = "GOOD_ROOM"

            else:
                score = 100.0
                label = "EXCELLENT_ROOM"

        elif signal == "SELL":

            if nearest_support == 0.0:
                score = 85.0
                label = "OPEN_SPACE"

            elif distance_to_support <= 1.0:
                score = 60.0
                label = "BREAKDOWN_ZONE"

            elif distance_to_support <= 3.0:
                score = 40.0
                label = "NEAR_SUPPORT"

            elif distance_to_support <= 5.0:
                score = 60.0
                label = "LIMITED_ROOM"

            elif distance_to_support <= 8.0:
                score = 80.0
                label = "GOOD_ROOM"

            else:
                score = 100.0
                label = "EXCELLENT_ROOM"

        else:
            score = 0.0
            label = "NO_TRADE"

        return {
            "nearest_support": round(
                nearest_support,
                2,
            ),
            "nearest_resistance": round(
                nearest_resistance,
                2,
            ),
            "distance_to_support_percent": round(
                distance_to_support,
                2,
            ),
            "distance_to_resistance_percent": round(
                distance_to_resistance,
                2,
            ),
            "support_resistance_score": score,
            "support_resistance_label": label,
        }