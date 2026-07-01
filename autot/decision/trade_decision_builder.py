"""
File: trade_decision_builder.py
Project: AutoT

Purpose:
    Build a TradeDecision object from strategy consensus.
"""

import pandas as pd

from autot.decision.trade_decision import TradeDecision


class TradeDecisionBuilder:

    @staticmethod
    def build(
        symbol: str,
        data: pd.DataFrame,
        consensus: dict,
    ) -> TradeDecision:

        latest = data.iloc[-1]

        entry_price = latest[("Close", data.columns[0][1])]

        reason = (
            f"BUY Score={consensus['buy_score']}, "
            f"SELL Score={consensus['sell_score']}, "
            f"HOLD Score={consensus['hold_score']}"
        )

        return TradeDecision(
            symbol=symbol,
            final_signal=consensus["final_signal"],
            buy_score=consensus["buy_score"],
            sell_score=consensus["sell_score"],
            hold_score=consensus["hold_score"],
            entry_price=float(entry_price),
            decision_reason=reason,
        )