"""
File: macd_strategy_class.py
Project: AutoT

Purpose:
    MACD strategy implemented using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class MacdStrategy(StrategyInterface):
    """
    MACD trading strategy.
    """

    def generate_signal(self, data: pd.DataFrame) -> dict:
        if data.empty:
            return {
                "signal": "HOLD",
                "reason": "No data available.",
                "confidence": 0.0,
            }

        latest_row = data.iloc[-1]

        macd = latest_row[("MACD", "")]
        macd_signal = latest_row[("MACD_SIGNAL", "")]

        if macd > macd_signal:
            return {
                "signal": "BUY",
                "reason": (
                    f"MACD {macd:.2f} is above signal line "
                    f"{macd_signal:.2f}."
                ),
                "confidence": 0.7,
            }

        if macd < macd_signal:
            return {
                "signal": "SELL",
                "reason": (
                    f"MACD {macd:.2f} is below signal line "
                    f"{macd_signal:.2f}."
                ),
                "confidence": 0.7,
            }

        return {
            "signal": "HOLD",
            "reason": (
                f"MACD {macd:.2f} is equal to signal line "
                f"{macd_signal:.2f}."
            ),
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "MACD_Strategy"