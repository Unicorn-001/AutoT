"""
File: ema_rsi_strategy_class.py
Project: AutoT

Purpose:
    EMA + RSI strategy implemented using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class EmaRsiStrategy(StrategyInterface):
    """
    EMA + RSI trading strategy.
    """

    def generate_signal(self, data: pd.DataFrame) -> dict:
        if data.empty:
            return {
                "signal": "HOLD",
                "reason": "No data available.",
                "confidence": 0.0,
            }

        latest_row = data.iloc[-1]

        ema_20 = latest_row[("EMA_20", "")]
        ema_50 = latest_row[("EMA_50", "")]
        rsi = latest_row[("RSI", "")]

        if ema_20 > ema_50 and rsi > 50:
            return {
                "signal": "BUY",
                "reason": (
                    f"EMA20 {ema_20:.2f} is above EMA50 {ema_50:.2f} "
                    f"and RSI {rsi:.2f} is above 50."
                ),
                "confidence": 0.75,
            }

        if ema_20 < ema_50 or rsi < 45:
            return {
                "signal": "SELL",
                "reason": (
                    f"EMA20 {ema_20:.2f}, EMA50 {ema_50:.2f}, "
                    f"RSI {rsi:.2f}. Bearish EMA or weak RSI condition."
                ),
                "confidence": 0.75,
            }

        return {
            "signal": "HOLD",
            "reason": (
                f"EMA20 {ema_20:.2f}, EMA50 {ema_50:.2f}, "
                f"RSI {rsi:.2f}. No clear EMA/RSI signal."
            ),
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "EMA_RSI_Strategy"