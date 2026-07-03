"""
File: adx_strategy_class.py
Project: AutoT

Purpose:
    ADX trend strength strategy using the StrategyInterface.
"""

import pandas as pd

from autot.strategies.base.strategy_interface import StrategyInterface


class AdxStrategy(StrategyInterface):
    """
    ADX strategy.

    Logic:
        BUY  when ADX > 25 and DI_PLUS > DI_MINUS
        SELL when ADX > 25 and DI_MINUS > DI_PLUS
        HOLD otherwise
    """

    def generate_signal(self, data: pd.DataFrame) -> dict:
        if data.empty:
            return {
                "signal": "HOLD",
                "reason": "No data available.",
                "confidence": 0.0,
            }

        latest_row = data.iloc[-1]

        adx = latest_row[("ADX", "")]
        di_plus = latest_row[("DI_PLUS", "")]
        di_minus = latest_row[("DI_MINUS", "")]

        if adx > 25 and di_plus > di_minus:
            return {
                "signal": "BUY",
                "reason": (
                    f"ADX {adx:.2f} indicates a strong trend, "
                    f"and DI+ {di_plus:.2f} is above DI- {di_minus:.2f}."
                ),
                "confidence": 0.75,
            }

        if adx > 25 and di_minus > di_plus:
            return {
                "signal": "SELL",
                "reason": (
                    f"ADX {adx:.2f} indicates a strong trend, "
                    f"and DI- {di_minus:.2f} is above DI+ {di_plus:.2f}."
                ),
                "confidence": 0.75,
            }

        return {
            "signal": "HOLD",
            "reason": (
                f"ADX {adx:.2f} does not show a strong directional trend."
            ),
            "confidence": 0.5,
        }

    def get_name(self) -> str:
        return "ADX_Strategy"