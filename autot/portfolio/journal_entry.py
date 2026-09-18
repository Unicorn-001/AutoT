"""
File: journal_entry.py
Project: AutoT

Purpose:
    Define a completed paper-trade journal record.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class JournalEntry:
    """
    Represents one completed paper trade from entry to exit.
    """

    symbol: str

    entry_timestamp: datetime
    exit_timestamp: datetime

    entry_price: float
    exit_price: float

    quantity: int

    stop_loss: float
    take_profit: float

    risk_reward_ratio: float
    max_loss: float

    confidence: float
    agreement: float
    market_regime: str

    trade_quality_score: float
    opportunity_score: float

    realized_profit_loss: float
    return_percent: float

    outcome: str
    exit_reason: str