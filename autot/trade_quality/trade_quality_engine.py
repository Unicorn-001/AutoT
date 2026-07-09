"""
File: trade_quality_engine.py
Project: AutoT

Purpose:
    Calculate trade quality score for swing trade opportunities.
"""


class TradeQualityEngine:
    """
    Creates a quality score out of 100 for each trade opportunity.
    """

    @staticmethod
    def calculate(
        signal: str,
        confidence: float,
        agreement: float,
        score: float,
        market_regime: str,
        risk_reward_ratio: float,
    ) -> dict:
        if signal not in ["BUY", "SELL"]:
            return {
                "trade_quality_score": 0.0,
                "trade_quality_label": "NO TRADE",
                "stars": "☆☆☆☆☆",
            }

        quality = 0.0

        # Confidence weight: 25 points
        quality += min(confidence, 100) * 0.25

        # Agreement weight: 20 points
        quality += min(agreement, 100) * 0.20

        # Backtest score weight: 25 points
        quality += max(min(score, 100), 0) * 0.25

        # Risk reward weight: 15 points
        if risk_reward_ratio >= 3:
            quality += 15
        elif risk_reward_ratio >= 2:
            quality += 12
        elif risk_reward_ratio >= 1.5:
            quality += 8

        # Market regime weight: 15 points
        if signal == "BUY" and market_regime == "STRONG_UPTREND":
            quality += 15
        elif signal == "SELL" and market_regime == "STRONG_DOWNTREND":
            quality += 15
        elif market_regime == "SIDEWAYS_OR_WEAK_TREND":
            quality += 8
        else:
            quality -= 10

        quality = round(max(min(quality, 100), 0), 2)

        if quality >= 85:
            label = "EXCELLENT"
            stars = "★★★★★"
        elif quality >= 70:
            label = "GOOD"
            stars = "★★★★☆"
        elif quality >= 55:
            label = "MODERATE"
            stars = "★★★☆☆"
        elif quality >= 40:
            label = "WEAK"
            stars = "★★☆☆☆"
        else:
            label = "AVOID"
            stars = "★☆☆☆☆"

        return {
            "trade_quality_score": quality,
            "trade_quality_label": label,
            "stars": stars,
        }