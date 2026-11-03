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

    def __init__(self, parameters=None):
        from autot.settings.models import EmaRsi
        self.parameters = parameters or EmaRsi()

    def generate_signal(self, data: pd.DataFrame) -> dict:
        if data.empty:
            return {
                "signal": "HOLD",
                "reason": "No data available.",
                "confidence": 0.0,
            }

        if ("EMA_20", "") not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing EMA_20 data.",
                "confidence": 0.0,
            }

        if ("EMA_50", "") not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing EMA_50 data.",
                "confidence": 0.0,
            }

        if ("RSI", "") not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing RSI data.",
                "confidence": 0.0,
            }

        latest_row = data.iloc[-1]

        ema_20 = latest_row[("EMA_20", "")]
        ema_50 = latest_row[("EMA_50", "")]
        rsi = latest_row[("RSI", "")]

        if pd.isna(ema_20) or pd.isna(ema_50) or pd.isna(rsi):
            return {
                "signal": "HOLD",
                "reason": "Invalid EMA/RSI indicator data.",
                "confidence": 0.0,
            }

        if ema_20 > ema_50 and rsi > self.parameters.buy_threshold:
            return {
                "signal": "BUY",
                "reason": (
                    f"EMA{self.parameters.fast} {ema_20:.2f} is above EMA{self.parameters.slow} {ema_50:.2f} "
                    f"and RSI {rsi:.2f} is above {self.parameters.buy_threshold:g}."
                ),
                "confidence": 0.75,
            }

        if ema_20 < ema_50 or rsi < self.parameters.sell_threshold:
            return {
                "signal": "SELL",
                "reason": (
                    f"EMA{self.parameters.fast} {ema_20:.2f}, EMA{self.parameters.slow} {ema_50:.2f}, "
                    f"RSI {rsi:.2f}. Bearish EMA or weak RSI condition."
                ),
                "confidence": 0.75,
            }

        return {
            "signal": "HOLD",
            "reason": (
                f"EMA{self.parameters.fast} {ema_20:.2f}, EMA{self.parameters.slow} {ema_50:.2f}, "
                f"RSI {rsi:.2f}. No clear EMA/RSI signal."
            ),
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "EMA_RSI_Strategy"
