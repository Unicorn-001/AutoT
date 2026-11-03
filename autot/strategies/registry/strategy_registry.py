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

from dataclasses import dataclass
from autot.settings.models import Strategies


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: str
    display_name: str
    implementation: type
    description: str
    version: str = '1'

    @property
    def default_parameters(self):
        return getattr(Strategies(), self.strategy_id)

    @property
    def parameter_schema(self):
        return type(self.default_parameters).model_json_schema()

    @property
    def advanced_parameters(self):
        return tuple(k for k in type(self.default_parameters).model_fields
                     if k not in ('enabled', 'weight', 'regime_weights'))

    def configured(self, settings):
        config = getattr(settings, self.strategy_id)
        return dict(strategy_id=self.strategy_id, display_name=self.display_name,
                    enabled=config.enabled, weight=config.weight,
                    regime_weights=config.regime_weights.model_dump(),
                    parameter_schema=self.parameter_schema,
                    default_parameters=self.default_parameters.model_dump(),
                    advanced_parameters=self.advanced_parameters,
                    description=self.description, version=self.version)


REGISTRY = (
    StrategyMetadata('EMA_RSI', 'EMA + RSI', EmaRsiStrategy, 'EMA trend and RSI thresholds.'),
    StrategyMetadata('MACD', 'MACD', MacdStrategy, 'MACD versus signal line.'),
    StrategyMetadata('BOLLINGER', 'Bollinger Bands', BollingerStrategy, 'Price at outer bands.'),
    StrategyMetadata('BREAKOUT', 'Breakout', BreakoutStrategy, 'Close beyond previous high or low.'),
    StrategyMetadata('SUPERTREND', 'Supertrend', SuperTrendStrategy, 'Existing rolling ATR band condition.'),
    StrategyMetadata('ADX', 'ADX', AdxStrategy, 'Directional movement in a strong trend.'),
    StrategyMetadata('VOLUME_SPIKE', 'Volume Spike', VolumeSpikeStrategy, 'Volume ratio and EMA trend.'),
    StrategyMetadata('MOMENTUM', 'Momentum', MomentumStrategy, 'Sign of price momentum.'),
    StrategyMetadata('ATR', 'ATR', AtrStrategy, 'ATR above its moving average and EMA trend.'),
    StrategyMetadata('STOCHASTIC', 'Stochastic', StochasticStrategy, 'Oversold/overbought reversals.'),
)


class StrategyRegistry:
    def __init__(self, settings=None):
        configured = settings is not None
        settings = settings or Strategies()
        self._strategies = []
        for item in REGISTRY:
            config = getattr(settings, item.strategy_id)
            enabled = config.enabled if configured else ENABLED_STRATEGIES.get(item.strategy_id, False)
            if enabled:
                if item.strategy_id == 'BREAKOUT':
                    strategy = item.implementation(lookback_period=config.lookback)
                elif item.strategy_id in ('EMA_RSI', 'ADX', 'VOLUME_SPIKE', 'ATR', 'STOCHASTIC'):
                    strategy = item.implementation(parameters=config)
                else:
                    strategy = item.implementation()
                self._strategies.append(strategy)

    def get_all(self):
        return self._strategies

    def get_names(self):
        return [strategy.get_name() for strategy in self._strategies]
