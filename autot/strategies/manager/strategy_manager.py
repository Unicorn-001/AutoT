"""
File: strategy_manager.py
Project: AutoT

Purpose:
    Execute all registered strategies and collect their signals.
"""

import pandas as pd

from autot.strategies.registry.strategy_registry import StrategyRegistry


class StrategyManager:
    """
    Runs all registered strategies.
    """

    def __init__(self) -> None:
        self.registry = StrategyRegistry()

    def run_all(
        self,
        data: pd.DataFrame,
    ) -> list[dict]:
        """
        Execute every registered strategy.

        Returns:
            List of strategy results.
        """

        results = []

        for strategy in self.registry.get_all():
            results.append(
                {
                    "strategy": strategy.get_name(),
                    "signal": strategy.generate_signal(data),
                }
            )

        return results