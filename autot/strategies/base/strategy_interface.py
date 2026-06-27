"""
File: strategy_interface.py
Project: AutoT

Purpose:
    Define the standard interface for all AutoT strategies.
"""

from abc import ABC, abstractmethod

import pandas as pd


class StrategyInterface(ABC):
    """
    Base class for all trading strategies.
    """

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> str:
        """
        Generate trading signal.

        Returns:
            BUY, SELL, or HOLD
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """
        Return strategy name.
        """
        pass