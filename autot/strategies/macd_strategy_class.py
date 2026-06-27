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

    Logic:
        BUY  when MACD > Signal Line
        SELL when MACD < Signal Line
        HOLD otherwise
    """

    def generate_signal(self, data: pd.DataFrame) -> str:
        """
        Generate BUY, SELL, or HOLD signal.
        """

        if data.empty:
            return "HOLD"

        latest_row = data.iloc[-1]

        macd = latest_row[("MACD", "")]
        macd_signal = latest_row[("MACD_SIGNAL", "")]

        if macd > macd_signal:
            return "BUY"

        if macd < macd_signal:
            return "SELL"

        return "HOLD"

    def get_name(self) -> str:
        """
        Return strategy name.
        """

        return "MACD_Strategy"