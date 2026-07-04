"""
File: strategy_weight_engine.py
Project: AutoT

Purpose:
    Apply market-regime-based weights to strategy results.
"""

from autot.config.strategy_weight_settings import MARKET_REGIME_WEIGHTS


class StrategyWeightEngine:
    """
    Adjusts strategy confidence based on market regime.
    """

    @staticmethod
    def apply_weights(
        strategy_results: list[dict],
        market_regime: str,
    ) -> list[dict]:

        regime_weights = MARKET_REGIME_WEIGHTS.get(market_regime, [])

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