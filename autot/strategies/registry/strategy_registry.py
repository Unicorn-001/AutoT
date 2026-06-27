"""
File: strategy_registry.py
Project: AutoT

Purpose:
    Central registry for all available trading strategies.
"""

from autot.strategies.ema_rsi_strategy_class import EmaRsiStrategy


class StrategyRegistry:
    """
    Registry of trading strategies.
    """

    def __init__(self) -> None:
        self._strategies = [
            EmaRsiStrategy(),
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