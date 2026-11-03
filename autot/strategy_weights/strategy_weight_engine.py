"""
File: strategy_weight_engine.py
Project: AutoT

Purpose:
    Apply market-regime-based weights to strategy results.
"""



class StrategyWeightEngine:
    """
    Adjusts strategy confidence based on market regime.
    """

    @staticmethod
    def apply_weights(
        strategy_results: list[dict],
        market_regime: str,
        settings=None,
    ) -> list[dict]:

        from autot.settings.models import Strategies
        from autot.strategies.registry.strategy_registry import REGISTRY
        settings = settings or Strategies()
        regime_weights = {item.implementation().get_name(): getattr(settings, item.strategy_id).effective_weight(market_regime)
                          for item in REGISTRY}

        weighted_results = []

        for result in strategy_results:
            updated_result = result.copy()

            strategy_name = updated_result["strategy"]
            original_confidence = updated_result["confidence"]

            weight = regime_weights.get(strategy_name, 1.0)

            updated_result["original_confidence"] = original_confidence
            updated_result["weight"] = weight
            updated_result["confidence"] = round(original_confidence * weight, 4)

            weighted_results.append(updated_result)

        return weighted_results