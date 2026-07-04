"""
File: trade_decision.py
Project: AutoT

Purpose:
    Represent a structured trade decision.
"""

from dataclasses import dataclass
from autot.position.position_size import PositionSize


@dataclass
class TradeDecision:
    """
    Represents one complete trading decision.
    """

    symbol: str
    final_signal: str
    confidence: float
    buy_score: float
    sell_score: float
    hold_score: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    decision_reason: str
    position_size: PositionSize
    agreement: float
    