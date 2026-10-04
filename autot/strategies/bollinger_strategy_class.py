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

        if ("BB_UPPER", "") not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing BB_UPPER data.",
                "confidence": 0.0,
            }

        if ("BB_LOWER", "") not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing BB_LOWER data.",
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
        upper_band = latest_row[("BB_UPPER", "")]
        lower_band = latest_row[("BB_LOWER", "")]

        if pd.isna(close) or pd.isna(upper_band) or pd.isna(lower_band):
            return {
                "signal": "HOLD",
                "reason": "Invalid Bollinger Band data.",
                "confidence": 0.0,
            }

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