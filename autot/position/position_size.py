"""
File: position_size.py
Project: AutoT

Purpose:
    Represent calculated position sizing information.
"""

from dataclasses import dataclass


@dataclass
class PositionSize:
    """
    Represents position sizing result for one trade.
    """

    account_size: float
    risk_percent: float
    risk_amount: float
    entry_price: float
    stop_loss: float
    risk_per_share: float
    quantity: int
    position_value: float
    max_loss: float
    