"""
File: trade_decision.py
Project: AutoT

Purpose:
    Represent a structured trade decision.
"""

from dataclasses import dataclass


@dataclass
class TradeDecision:
    """
    Represents one complete trading decision.
    """

    symbol: str
    final_signal: str
    buy_score: float
    sell_score: float
    hold_score: float
    entry_price: float
    decision_reason: str