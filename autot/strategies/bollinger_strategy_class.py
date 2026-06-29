"""
File: bollinger_strategy_class.py
Project: AutoT

Purpose:
    Bollinger Bands strategy using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class BollingerStrategy(StrategyInterface):
    """
    Bollinger Bands strategy.
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
        upper_band = latest_row[("BB_UPPER", "")]
        lower_band = latest_row[("BB_LOWER", "")]

        if close <= lower_band:
            return {
                "signal": "BUY",
                "reason": (
                    f"Close {close:.2f} is at or below lower Bollinger Band "
                    f"{lower_band:.2f}."
                ),
                "confidence": 0.65,
            }

        if close >= upper_band:
            return {
                "signal": "SELL",
                "reason": (
                    f"Close {close:.2f} is at or above upper Bollinger Band "
                    f"{upper_band:.2f}."
                ),
                "confidence": 0.65,
            }

        return {
            "signal": "HOLD",
            "reason": (
                f"Close {close:.2f} is between Bollinger Bands "
                f"{lower_band:.2f} and {upper_band:.2f}."
            ),
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "Bollinger_Strategy"