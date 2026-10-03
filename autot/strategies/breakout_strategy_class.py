"""
File: breakout_strategy_class.py
Project: AutoT

Purpose:
    Breakout strategy using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class BreakoutStrategy(StrategyInterface):
    """
    20-day breakout trading strategy.
    """

    def __init__(self, lookback_period: int = 20) -> None:
        if lookback_period <= 0:
            raise ValueError(
                "lookback_period must be greater than zero."
            )

        self.lookback_period = lookback_period

    def generate_signal(self, data: pd.DataFrame) -> dict:
        if data.empty or len(data) <= self.lookback_period:
            return {
                "signal": "HOLD",
                "reason": "Not enough data for breakout calculation.",
                "confidence": 0.0,
            }

        if "Close" not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing Close data.",
                "confidence": 0.0,
            }

        if "High" not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing High data.",
                "confidence": 0.0,
            }

        if "Low" not in data.columns:
            return {
                "signal": "HOLD",
                "reason": "Missing Low data.",
                "confidence": 0.0,
            }

        close_series = data["Close"]
        if isinstance(close_series, pd.DataFrame):
            close_series = close_series.iloc[:, 0]

        high_series = data["High"]
        if isinstance(high_series, pd.DataFrame):
            high_series = high_series.iloc[:, 0]

        low_series = data["Low"]
        if isinstance(low_series, pd.DataFrame):
            low_series = low_series.iloc[:, 0]

        latest_close = close_series.iloc[-1]

        if pd.isna(latest_close) or latest_close <= 0:
            return {
                "signal": "HOLD",
                "reason": "Invalid latest close price.",
                "confidence": 0.0,
            }

        previous_high = high_series.iloc[
            -(self.lookback_period + 1):-1
        ].max()

        previous_low = low_series.iloc[
            -(self.lookback_period + 1):-1
        ].min()

        if latest_close > previous_high:
            return {
                "signal": "BUY",
                "reason": (
                    f"Close {latest_close:.2f} broke above previous "
                    f"{self.lookback_period}-day high {previous_high:.2f}."
                ),
                "confidence": 0.8,
            }

        if latest_close < previous_low:
            return {
                "signal": "SELL",
                "reason": (
                    f"Close {latest_close:.2f} broke below previous "
                    f"{self.lookback_period}-day low {previous_low:.2f}."
                ),
                "confidence": 0.8,
            }

        return {
            "signal": "HOLD",
            "reason": (
                f"Close {latest_close:.2f} is within previous "
                f"{self.lookback_period}-day range "
                f"{previous_low:.2f} to {previous_high:.2f}."
            ),
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "Breakout_Strategy"