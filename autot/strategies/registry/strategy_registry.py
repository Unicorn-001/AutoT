"""
File: strategy_registry.py
Project: AutoT

Purpose:
    Central registry for all available trading strategies.
"""

from autot.strategies.ema_rsi_strategy_class import EmaRsiStrategy
from autot.strategies.macd_strategy_class import MacdStrategy


class StrategyRegistry:
    """
    Registry of trading strategies.
    """

    def __init__(self) -> None:
        self._strategies = [
            EmaRsiStrategy(),
            MacdStrategy(),
        ]

    def get_all(self):
        """
        Return all registered strategies.
        """
        return self._strategies

    def get_names(self):
        """
        Return strategy names.
        """
        return [strategy.get_name() for strategy in self._strategies]