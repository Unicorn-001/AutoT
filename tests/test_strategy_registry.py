"""
File: test_strategy_registry.py
Project: AutoT

Purpose:
    Test strategy registration and configuration behaviour.
"""

from autot.strategies.registry.strategy_registry import StrategyRegistry


def test_registry_loads_all_enabled_strategies():
    registry = StrategyRegistry()

    expected_names = [
        "EMA_RSI_Strategy",
        "MACD_Strategy",
        "Bollinger_Strategy",
        "Breakout_Strategy",
        "SuperTrend_Strategy",
        "ADX_Strategy",
        "Volume_Spike_Strategy",
        "Momentum_Strategy",
        "ATR_Strategy",
        "Stochastic_Strategy",
    ]

    assert len(registry.get_all()) == 10
    assert registry.get_names() == expected_names


def test_registry_excludes_disabled_strategy(monkeypatch):
    from autot.strategies.registry.strategy_registry import ENABLED_STRATEGIES

    monkeypatch.setitem(ENABLED_STRATEGIES, "MACD", False)

    registry = StrategyRegistry()

    assert "MACD_Strategy" not in registry.get_names()
    assert len(registry.get_all()) == 9


def test_registry_loads_only_enabled_strategy(monkeypatch):
    from autot.strategies.registry.strategy_registry import ENABLED_STRATEGIES

    for strategy_name in ENABLED_STRATEGIES:
        monkeypatch.setitem(ENABLED_STRATEGIES, strategy_name, False)

    monkeypatch.setitem(ENABLED_STRATEGIES, "BREAKOUT", True)

    registry = StrategyRegistry()

    assert len(registry.get_all()) == 1
    assert registry.get_names() == ["Breakout_Strategy"]


def test_registry_names_match_registered_strategies():
    registry = StrategyRegistry()

    strategies = registry.get_all()
    expected_names = [strategy.get_name() for strategy in strategies]

    assert registry.get_names() == expected_names
