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
        # Default risk management (2% Stop Loss, 4% Take Profit)
        stop_loss = entry_price * 0.98
        take_profit = entry_price * 1.04
        risk_reward_ratio = 2.0

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
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            risk_reward_ratio=risk_reward_ratio,
            decision_reason=reason,
        )
        