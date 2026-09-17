"""
File: position.py
Project: AutoT

Purpose:
    Define an open portfolio position.
"""

from dataclasses import dataclass


@dataclass
class Position:
    """
    Represents an open stock position.
    """

    symbol: str
    quantity: int
    average_price: float
    stop_loss: float
    max_loss: float
