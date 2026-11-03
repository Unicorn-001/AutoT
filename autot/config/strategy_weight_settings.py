"""Legacy compatibility view of the canonical baseline regime weights."""
from autot.settings.models import Strategies

_NAMES = {
    'EMA_RSI': 'EMA_RSI_Strategy', 'MACD': 'MACD_Strategy', 'BOLLINGER': 'Bollinger_Strategy',
    'BREAKOUT': 'Breakout_Strategy', 'SUPERTREND': 'SuperTrend_Strategy', 'ADX': 'ADX_Strategy',
    'VOLUME_SPIKE': 'Volume_Spike_Strategy', 'MOMENTUM': 'Momentum_Strategy',
    'ATR': 'ATR_Strategy', 'STOCHASTIC': 'Stochastic_Strategy',
}
_BASELINE = Strategies()
MARKET_REGIME_WEIGHTS = {
    regime: {name: getattr(_BASELINE, key).effective_weight(regime) for key, name in _NAMES.items()
             if getattr(_BASELINE, key).effective_weight(regime) != 1.0}
    for regime in ('STRONG_UPTREND', 'STRONG_DOWNTREND', 'SIDEWAYS_OR_WEAK_TREND')
}
