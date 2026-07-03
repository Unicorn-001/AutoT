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

        latest_row = data.iloc[-1]

        close = latest_row[("Close", data.columns[0][1])]
        ema_20 = latest_row[("EMA_20", "")]
        volume_ratio = latest_row[("VOLUME_RATIO", "")]

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