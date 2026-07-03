"""
File: stochastic_strategy_class.py
Project: AutoT

Purpose:
    Stochastic oscillator strategy using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class StochasticStrategy(StrategyInterface):
    """
    Stochastic oscillator trading strategy.
    """

    def generate_signal(self, data: pd.DataFrame) -> dict:
        if data.empty:
            return {"signal": "HOLD", "reason": "No data available.", "confidence": 0.0}

        latest_row = data.iloc[-1]

        stoch_k = latest_row[("STOCH_K", "")]
        stoch_d = latest_row[("STOCH_D", "")]

        if stoch_k < 20 and stoch_k > stoch_d:
            return {
                "signal": "BUY",
                "reason": f"Stochastic K {stoch_k:.2f} is oversold and above D {stoch_d:.2f}.",
                "confidence": 0.7,
            }

        if stoch_k > 80 and stoch_k < stoch_d:
            return {
                "signal": "SELL",
                "reason": f"Stochastic K {stoch_k:.2f} is overbought and below D {stoch_d:.2f}.",
                "confidence": 0.7,
            }

        return {
            "signal": "HOLD",
            "reason": f"Stochastic K {stoch_k:.2f}, D {stoch_d:.2f} shows no clear reversal.",
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "Stochastic_Strategy"