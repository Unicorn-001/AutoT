"""
File: trade_decision_builder.py
Project: AutoT

Purpose:
    Build a TradeDecision object from strategy consensus.
"""

import pandas as pd

from autot.decision.trade_decision import TradeDecision
from autot.position.position_size_calculator import PositionSizeCalculator
from autot.config.trading_settings import (
    ACCOUNT_SIZE,
    DEFAULT_STOP_LOSS_PERCENT,
    DEFAULT_TAKE_PROFIT_PERCENT,
    RISK_PER_TRADE,
)
from autot.decision_engine.decision_engine import DecisionEngine



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
        stop_loss = entry_price * (1 - DEFAULT_STOP_LOSS_PERCENT / 100)
        take_profit = entry_price * (1 + DEFAULT_TAKE_PROFIT_PERCENT / 100)
        risk_reward_ratio = 2.0

        position_size = PositionSizeCalculator.calculate(
            account_size=ACCOUNT_SIZE,
            risk_percent=RISK_PER_TRADE,
            entry_price=float(entry_price),
            stop_loss=float(stop_loss),
        )
        decision = DecisionEngine.decide(consensus)

        decision_reason = decision["decision_reason"]

        return TradeDecision(
            symbol=symbol,
            final_signal=decision["final_signal"],
            confidence=decision["confidence"],
            buy_score=consensus["buy_score"],
            sell_score=consensus["sell_score"],
            hold_score=consensus["hold_score"],
            entry_price=float(entry_price),
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            risk_reward_ratio=risk_reward_ratio,
            decision_reason=decision_reason,
            position_size=position_size,
        )
        