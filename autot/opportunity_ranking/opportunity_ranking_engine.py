"""
File: opportunity_ranking_engine.py
Project: AutoT

Purpose:
    Calculate the overall ranking score for current swing-trade opportunities.
"""


class OpportunityRankingEngine:
    """
    Combines current trade quality and historical performance
    into one opportunity-ranking score.
    """

    @staticmethod
    def calculate(
        trade_quality_score: float,
        historical_score: float,
        trend_strength_score: float,
        confidence: float,
        risk_reward_ratio: float,
    ) -> float:
        normalized_historical_score = max(
            min(historical_score, 100),
            0,
        )

        normalized_trade_quality = max(
            min(trade_quality_score, 100),
            0,
        )

        normalized_trend_strength = max(
            min(trend_strength_score, 100),
            0,
        )

        normalized_confidence = max(
            min(confidence, 100),
            0,
        )

        if risk_reward_ratio >= 3:
            risk_reward_score = 100.0
        elif risk_reward_ratio >= 2:
            risk_reward_score = 80.0
        elif risk_reward_ratio >= 1.5:
            risk_reward_score = 55.0
        elif risk_reward_ratio >= 1:
            risk_reward_score = 30.0
        else:
            risk_reward_score = 0.0

        opportunity_score = (
            normalized_trade_quality * 0.40
            + normalized_historical_score * 0.25
            + normalized_trend_strength * 0.15
            + normalized_confidence * 0.10
            + risk_reward_score * 0.10
        )

        return round(opportunity_score, 2)