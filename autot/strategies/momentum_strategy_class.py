"""
File: momentum_strategy_class.py
Project: AutoT

Purpose:
    Momentum strategy using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class MomentumStrategy(StrategyInterface):
    """
    Momentum trading strategy.
    """

    def generate_signal(self, data: pd.DataFrame) -> dict:
        if data.empty:
            return {
                "signal": "HOLD",
                "reason": "No data available.",
                "confidence": 0.0,
            }

        latest_row = data.iloc[-1]

        momentum = latest_row[("MOMENTUM", "")]

        if momentum > 0:
            return {
                "signal": "BUY",
                "reason": f"Momentum is positive at {momentum:.2f}.",
                "confidence": 0.7,
            }

        if momentum < 0:
            return {
                "signal": "SELL",
                "reason": f"Momentum is negative at {momentum:.2f}.",
                "confidence": 0.7,
            }

        return {
            "signal": "HOLD",
            "reason": "Momentum is neutral.",
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "Momentum_Strategy"