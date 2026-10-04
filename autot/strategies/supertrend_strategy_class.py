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

        if ("SUPERTREND_LOWER", "") not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing SUPERTREND_LOWER data.",
                "confidence": 0.0,
            }

        if ("SUPERTREND_DIRECTION", "") not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing SUPERTREND_DIRECTION data.",
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
        lower_band = latest_row[("SUPERTREND_LOWER", "")]
        direction = latest_row[("SUPERTREND_DIRECTION", "")]

        if pd.isna(close) or pd.isna(lower_band) or pd.isna(direction):
            return {
                "signal": "HOLD",
                "reason": "Invalid SuperTrend data.",
                "confidence": 0.0,
            }

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