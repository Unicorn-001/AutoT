"""
File: trade.py
Project: AutoT

Purpose:
    Define a trade record for paper trading.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:
    """
    Represents one paper trading transaction.
    """

    action: str
    symbol: str
    price: float
    quantity: int
    total_value: float
    timestamp: datetime