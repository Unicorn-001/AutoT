"""
File: supertrend_strategy_class.py
Project: AutoT

Purpose:
    SuperTrend strategy using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class SuperTrendStrategy(StrategyInterface):
    """
    SuperTrend trading strategy.
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
        lower_band = latest_row[("SUPERTREND_LOWER", "")]
        direction = latest_row[("SUPERTREND_DIRECTION", "")]

        if direction:
            return {
                "signal": "BUY",
                "reason": (
                    f"Close {close:.2f} is above SuperTrend lower band "
                    f"{lower_band:.2f}, indicating bullish trend."
                ),
                "confidence": 0.75,
            }

        return {
            "signal": "SELL",
            "reason": (
                f"Close {close:.2f} is below SuperTrend trend condition, "
                "indicating bearish trend."
            ),
            "confidence": 0.75,
        }

    def get_name(self) -> str:
        return "SuperTrend_Strategy"