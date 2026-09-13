"""
File: trade_decision_builder.py
Project: AutoT

Purpose:
    Build a TradeDecision object from strategy consensus.
"""

import pandas as pd

from autot.decision.trade_decision import TradeDecision
from autot.position.position_size_calculator import PositionSizeCalculator
from autot.risk.risk_reward import calculate_risk_reward_ratio
from autot.config.trading_settings import (
    ACCOUNT_SIZE,
    DEFAULT_STOP_LOSS_PERCENT,
    DEFAULT_TAKE_PROFIT_PERCENT,
    RISK_PER_TRADE,
)
from autot.decision_engine.decision_engine import DecisionEngine
from autot.market_regime.market_regime_detector import MarketRegimeDetector


class TradeDecisionBuilder:

    @staticmethod
    def build(
        symbol: str,
        data: pd.DataFrame,
        consensus: dict,
    ) -> TradeDecision:

        latest = data.iloc[-1]

        entry_price = float(
            latest[("Close", data.columns[0][1])]
        )

        # Determine final trading signal first
        decision = DecisionEngine.decide(consensus)

        final_signal = decision["final_signal"]
        decision_reason = decision["decision_reason"]

        # ---------------------------------------------------------
        # Risk management
        # ---------------------------------------------------------

        if final_signal == "BUY":

            stop_loss = entry_price * (
                1 - DEFAULT_STOP_LOSS_PERCENT / 100
            )

            take_profit = entry_price * (
                1 + DEFAULT_TAKE_PROFIT_PERCENT / 100
            )

            risk_reward_ratio = calculate_risk_reward_ratio(
                entry_price=entry_price,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
                signal="BUY",
            )

        elif final_signal == "SELL":

            stop_loss = entry_price * (
                1 + DEFAULT_STOP_LOSS_PERCENT / 100
            )

            take_profit = entry_price * (
                1 - DEFAULT_TAKE_PROFIT_PERCENT / 100
            )

            risk_reward_ratio = calculate_risk_reward_ratio(
                entry_price=entry_price,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
                signal="SELL",
            )

        else:
            # HOLD means there is no active trade.
            stop_loss = entry_price
            take_profit = entry_price
            risk_reward_ratio = 0.0

        # ---------------------------------------------------------
        # Position sizing
        # ---------------------------------------------------------

        position_size = PositionSizeCalculator.calculate(
            account_size=ACCOUNT_SIZE,
            risk_percent=RISK_PER_TRADE,
            entry_price=entry_price,
            stop_loss=stop_loss,
        )

        regime = MarketRegimeDetector.detect(data)

        return TradeDecision(
            symbol=symbol,
            final_signal=final_signal,
            confidence=decision["confidence"],
            agreement=decision["agreement"],
            market_regime=regime["regime"],
            buy_score=consensus["buy_score"],
            sell_score=consensus["sell_score"],
            hold_score=consensus["hold_score"],
            entry_price=entry_price,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            risk_reward_ratio=risk_reward_ratio,
            decision_reason=decision_reason,
            position_size=position_size,
        )