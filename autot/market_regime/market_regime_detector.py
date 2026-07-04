"""
File: market_regime_detector.py
Project: AutoT

Purpose:
    Detect market regime such as uptrend, downtrend, or sideways.
"""


class MarketRegimeDetector:
    """
    Detects basic market regime using EMA and ADX.
    """

    @staticmethod
    def detect(data) -> dict:
        latest = data.iloc[-1]

        ema_20 = latest[("EMA_20", "")]
        ema_50 = latest[("EMA_50", "")]
        adx = latest[("ADX", "")]

        if ema_20 > ema_50 and adx >= 25:
            regime = "STRONG_UPTREND"
        elif ema_20 < ema_50 and adx >= 25:
            regime = "STRONG_DOWNTREND"
        else:
            regime = "SIDEWAYS_OR_WEAK_TREND"

        return {
            "regime": regime,
            "ema_20": float(ema_20),
            "ema_50": float(ema_50),
            "adx": float(adx),
        }