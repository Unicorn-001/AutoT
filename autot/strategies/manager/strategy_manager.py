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

    def run_all(self, data: pd.DataFrame) -> list[dict]:
        """
        Execute every registered strategy.
        """

        results = []

        for strategy in self.registry.get_all():
            strategy_result = strategy.generate_signal(data)

            if isinstance(strategy_result, str):
                strategy_result = {
                    "signal": strategy_result,
                    "reason": "Legacy strategy result.",
                    "confidence": 0.5,
                }

            strategy_result["strategy"] = strategy.get_name()
            results.append(strategy_result)

        return results