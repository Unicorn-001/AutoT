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

    trend_strength_score: float = 0.0
    trend_strength_label: str = "UNKNOWN"

    volume_ratio: float = 0.0
    volume_strength_score: float = 0.0
    volume_strength_label: str = "UNKNOWN"
    volume_confirmed: bool = False

    stock_return_percent: float = 0.0
    benchmark_return_percent: float = 0.0
    relative_strength_percent: float = 0.0
    relative_strength_score: float = 0.0
    relative_strength_label: str = "UNKNOWN"

    nearest_support: float = 0.0
    nearest_resistance: float = 0.0
    distance_to_support_percent: float = 0.0
    distance_to_resistance_percent: float = 0.0
    support_resistance_score: float = 0.0
    support_resistance_label: str = "UNKNOWN"
    breakout_confirmation_score: float = 0.0
