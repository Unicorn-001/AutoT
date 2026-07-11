"""
File: trend_strength_engine.py
Project: AutoT

Purpose:
    Calculate trend strength score for swing trading.
"""


class TrendStrengthEngine:
    """
    Calculates trend strength from EMA and ADX values.
    """

    @staticmethod
    def calculate(data) -> dict:
        latest = data.iloc[-1]

        close = float(latest["Close"].iloc[0])
        ema_20 = float(latest["EMA_20"].iloc[0])
        ema_50 = float(latest["EMA_50"].iloc[0])
        ema_200 = float(latest["EMA_200"].iloc[0]) if "EMA_200" in data.columns.get_level_values(0) else ema_50
        adx = float(latest["ADX"].iloc[0])

        score = 0.0

        if close > ema_20:
            score += 20

        if ema_20 > ema_50:
            score += 25

        if close > ema_50:
            score += 20

        if close > ema_200:
            score += 15

        if adx >= 25:
            score += 20
        elif adx >= 20:
            score += 10

        score = round(min(score, 100), 2)

        if score >= 85:
            label = "VERY_STRONG_TREND"
        elif score >= 70:
            label = "STRONG_TREND"
        elif score >= 50:
            label = "MODERATE_TREND"
        elif score >= 30:
            label = "WEAK_TREND"
        else:
            label = "NO_TREND"

        return {
            "trend_strength_score": score,
            "trend_strength_label": label,
        }
