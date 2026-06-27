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

    Logic:
        BUY  when EMA20 > EMA50 and RSI > 50
        SELL when EMA20 < EMA50 or RSI < 45
        HOLD otherwise
    """

    def generate_signal(self, data: pd.DataFrame) -> str:
        """
        Generate BUY, SELL, or HOLD signal.
        """

        if data.empty:
            return "HOLD"

        latest_row = data.iloc[-1]

        ema_20 = latest_row[("EMA_20", "")]
        ema_50 = latest_row[("EMA_50", "")]
        rsi = latest_row[("RSI", "")]
        if ema_20 > ema_50 and rsi > 50:
            return "BUY"

        if ema_20 < ema_50 or rsi < 45:
            return "SELL"

        return "HOLD"

    def get_name(self) -> str:
        """
        Return strategy name.
        """

        return "EMA_RSI_Strategy"