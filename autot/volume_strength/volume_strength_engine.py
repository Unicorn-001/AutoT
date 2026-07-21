"""
File: volume_strength_engine.py
Project: AutoT

Purpose:
    Measure current trading volume against average volume.
"""

import pandas as pd


class VolumeStrengthEngine:
    """
    Calculates volume strength for swing-trade confirmation.
    """

    @staticmethod
    def calculate(
        data: pd.DataFrame,
        average_period: int = 20,
    ) -> dict:
        if len(data) < average_period:
            return {
                "volume_ratio": 0.0,
                "volume_strength_score": 0.0,
                "volume_strength_label": "INSUFFICIENT_DATA",
                "volume_confirmed": False,
            }

        volume_columns = data.columns.get_level_values(0)

        if "Volume" not in volume_columns:
            return {
                "volume_ratio": 0.0,
                "volume_strength_score": 0.0,
                "volume_strength_label": "NO_VOLUME_DATA",
                "volume_confirmed": False,
            }

        volume_series = data["Volume"]

        if isinstance(volume_series, pd.DataFrame):
            volume_series = volume_series.iloc[:, 0]

        volume_series = pd.to_numeric(
            volume_series,
            errors="coerce",
        ).dropna()

        if len(volume_series) < average_period:
            return {
                "volume_ratio": 0.0,
                "volume_strength_score": 0.0,
                "volume_strength_label": "INSUFFICIENT_DATA",
                "volume_confirmed": False,
            }

        latest_volume = float(volume_series.iloc[-1])

        average_volume = float(
            volume_series.iloc[-average_period:].mean()
        )

        if average_volume <= 0:
            volume_ratio = 0.0
        else:
            volume_ratio = latest_volume / average_volume

        if volume_ratio >= 2.0:
            score = 100.0
            label = "VERY_STRONG_VOLUME"
        elif volume_ratio >= 1.5:
            score = 85.0
            label = "STRONG_VOLUME"
        elif volume_ratio >= 1.2:
            score = 70.0
            label = "ABOVE_AVERAGE_VOLUME"
        elif volume_ratio >= 0.8:
            score = 50.0
            label = "NORMAL_VOLUME"
        elif volume_ratio >= 0.5:
            score = 25.0
            label = "LOW_VOLUME"
        else:
            score = 10.0
            label = "VERY_LOW_VOLUME"

        return {
            "volume_ratio": round(volume_ratio, 2),
            "volume_strength_score": score,
            "volume_strength_label": label,
            "volume_confirmed": volume_ratio >= 1.2,
        }