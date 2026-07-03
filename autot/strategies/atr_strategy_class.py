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
        atr = latest_row[("ATR", "")]

        atr_average = data[("ATR", "")].rolling(window=20).mean().iloc[-1]

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
