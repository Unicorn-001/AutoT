"""
File: open_journal_entry.py
Project: AutoT

Purpose:
    Preserve AutoT decision context for an open paper trade.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class OpenJournalEntry:
    """
    Represents the entry-time context of an open paper trade.
    """

    symbol: str
    entry_timestamp: datetime

    entry_price: float
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
