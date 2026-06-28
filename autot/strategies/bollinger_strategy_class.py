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

    Logic:
        BUY  when close <= lower band
        SELL when close >= upper band
        HOLD otherwise
    """

    def generate_signal(self, data: pd.DataFrame) -> str:
        if data.empty:
            return "HOLD"

        latest_row = data.iloc[-1]

        close = latest_row[("Close", data.columns[0][1])]
        upper_band = latest_row[("BB_UPPER", "")]
        lower_band = latest_row[("BB_LOWER", "")]

        if close <= lower_band:
            return "BUY"

        if close >= upper_band:
            return "SELL"

        return "HOLD"

    def get_name(self) -> str:
        return "Bollinger_Strategy"