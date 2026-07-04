"""
File: strategy_weight_settings.py
Project: AutoT

Purpose:
    Market-regime-based strategy weight settings.
"""

MARKET_REGIME_WEIGHTS = {
    "STRONG_UPTREND": {
        "EMA_RSI_Strategy": 1.20,
        "MACD_Strategy": 1.20,
        "SuperTrend_Strategy": 1.20,
        "Momentum_Strategy": 1.15,
        "Breakout_Strategy": 1.10,
        "Bollinger_Strategy": 0.90,
        "Stochastic_Strategy": 0.90,
    },
    "STRONG_DOWNTREND": {
        "EMA_RSI_Strategy": 1.20,
        "MACD_Strategy": 1.20,
        "SuperTrend_Strategy": 1.20,
        "Momentum_Strategy": 1.15,
        "Breakout_Strategy": 1.10,
        "Bollinger_Strategy": 0.90,
        "Stochastic_Strategy": 0.90,
    },
    "SIDEWAYS_OR_WEAK_TREND": {
        "Bollinger_Strategy": 1.20,
        "Stochastic_Strategy": 1.20,
        "Volume_Spike_Strategy": 1.10,
        "Breakout_Strategy": 0.85,
        "Momentum_Strategy": 0.90,
        "SuperTrend_Strategy": 0.90,
    },
}
