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
from autot.strategies.momentum_strategy_class import MomentumStrategy
from autot.strategies.atr_strategy_class import AtrStrategy
from autot.strategies.stochastic_strategy_class import StochasticStrategy


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
        if ENABLED_STRATEGIES.get("MOMENTUM", False):
            self._strategies.append(MomentumStrategy())
        if ENABLED_STRATEGIES.get("ATR", False):
            self._strategies.append(AtrStrategy())
        if ENABLED_STRATEGIES.get("STOCHASTIC", False):
            self._strategies.append(StochasticStrategy())

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