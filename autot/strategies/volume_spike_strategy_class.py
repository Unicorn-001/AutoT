"""
File: volume_spike_strategy_class.py
Project: AutoT

Purpose:
    Volume spike strategy using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class VolumeSpikeStrategy(StrategyInterface):
    """
    Volume spike confirmation strategy.
    """

    def generate_signal(self, data: pd.DataFrame) -> dict:
        if data.empty:
            return {
                "signal": "HOLD",
                "reason": "No data available.",
                "confidence": 0.0,
            }

        required_columns = [
            ("EMA_20", ""),
            ("VOLUME_RATIO", ""),
        ]

        if any(column not in data.columns for column in required_columns):
            return {
                "signal": "HOLD",
                "reason": "Missing volume spike data.",
                "confidence": 0.0,
            }

        latest_row = data.iloc[-1]

        close_columns = [
            column for column in data.columns
            if column[0] == "Close"
        ]

        if not close_columns:
            return {
                "signal": "HOLD",
                "reason": "Missing Close data.",
                "confidence": 0.0,
            }

        close = latest_row[close_columns[0]]
        ema_20 = latest_row[("EMA_20", "")]
        volume_ratio = latest_row[("VOLUME_RATIO", "")]

        if pd.isna(close) or pd.isna(ema_20) or pd.isna(volume_ratio):
            return {
                "signal": "HOLD",
                "reason": "Volume spike data is invalid.",
                "confidence": 0.0,
            }

        if volume_ratio >= 2.0 and close > ema_20:
            return {
                "signal": "BUY",
                "reason": (
                    f"Volume is {volume_ratio:.2f}x average and price is above EMA20."
                ),
                "confidence": 0.75,
            }

        if volume_ratio >= 2.0 and close < ema_20:
            return {
                "signal": "SELL",
                "reason": (
                    f"Volume is {volume_ratio:.2f}x average and price is below EMA20."
                ),
                "confidence": 0.75,
            }

        return {
            "signal": "HOLD",
            "reason": f"Volume ratio {volume_ratio:.2f} does not show a strong spike.",
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "Volume_Spike_Strategy"