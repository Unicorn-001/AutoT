"""
File: atr_strategy_class.py
Project: AutoT

Purpose:
    ATR volatility strategy using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class AtrStrategy(StrategyInterface):
    """
    ATR volatility strategy.

    Logic:
        BUY  when ATR is above ATR moving average and close > EMA20
        SELL when ATR is above ATR moving average and close < EMA20
        HOLD otherwise
    """

    def __init__(self, parameters=None):
        from autot.settings.models import Atr
        self.parameters = parameters or Atr()

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

        if ("ATR", "") not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing ATR data.",
                "confidence": 0.0,
            }

        if len(data) < self.parameters.average_period:
            return {
                "signal": "HOLD",
                "reason": "Insufficient data for ATR average.",
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

        if pd.isna(close):
            return {
                "signal": "HOLD",
                "reason": "Close data is invalid.",
                "confidence": 0.0,
            }
        ema_20 = latest_row[("EMA_20", "")]

        if pd.isna(ema_20):
            return {
                "signal": "HOLD",
                "reason": "EMA_20 data is invalid.",
                "confidence": 0.0,
            }
        atr = latest_row[("ATR", "")]

        if pd.isna(atr):
            return {
                "signal": "HOLD",
                "reason": "ATR data is invalid.",
                "confidence": 0.0,
            }

        atr_average = data[("ATR", "")].rolling(window=self.parameters.average_period).mean().iloc[-1]

        if pd.isna(atr_average):
            return {
                "signal": "HOLD",
                "reason": "ATR average is invalid.",
                "confidence": 0.0,
            }

        if atr > atr_average and close > ema_20:
            return {
                "signal": "BUY",
                "reason": (
                    f"ATR {atr:.2f} is above average {atr_average:.2f}, "
                    "and price is above EMA20."
                ),
                "confidence": 0.7,
            }

        if atr > atr_average and close < ema_20:
            return {
                "signal": "SELL",
                "reason": (
                    f"ATR {atr:.2f} is above average {atr_average:.2f}, "
                    "and price is below EMA20."
                ),
                "confidence": 0.7,
            }

        return {
            "signal": "HOLD",
            "reason": (
                f"ATR {atr:.2f} is not above average {atr_average:.2f}."
            ),
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "ATR_Strategy"
