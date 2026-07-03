"""
File: strategy_registry.py
Project: AutoT

Purpose:
    Central registry for all available trading strategies.
"""

from autot.config.strategy_settings import ENABLED_STRATEGIES
from autot.strategies.ema_rsi_strategy_class import EmaRsiStrategy
from autot.strategies.macd_strategy_class import MacdStrategy
from autot.strategies.bollinger_strategy_class import BollingerStrategy
from autot.strategies.breakout_strategy_class import BreakoutStrategy
from autot.strategies.supertrend_strategy_class import SuperTrendStrategy
from autot.strategies.adx_strategy_class import AdxStrategy
from autot.strategies.volume_spike_strategy_class import VolumeSpikeStrategy


class StrategyRegistry:
    """
    Registry of trading strategies.
    """

    def __init__(self) -> None:
        self._strategies = []

        if ENABLED_STRATEGIES.get("EMA_RSI", False):
            self._strategies.append(EmaRsiStrategy())

        if ENABLED_STRATEGIES.get("MACD", False):
            self._strategies.append(MacdStrategy())
        if ENABLED_STRATEGIES.get("BOLLINGER", False):
            self._strategies.append(BollingerStrategy())
        if ENABLED_STRATEGIES.get("BREAKOUT", False):
            self._strategies.append(BreakoutStrategy())
        if ENABLED_STRATEGIES.get("SUPERTREND", False):
            self._strategies.append(SuperTrendStrategy())
        if ENABLED_STRATEGIES.get("ADX", False):
            self._strategies.append(AdxStrategy())
        if ENABLED_STRATEGIES.get("VOLUME_SPIKE", False):
            self._strategies.append(VolumeSpikeStrategy())

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