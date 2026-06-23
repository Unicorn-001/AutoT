"""
File: stop_loss.py
Project: AutoT

Purpose:
    Calculate stop loss price.
"""


def calculate_stop_loss_price(
    entry_price: float,
    stop_loss_percent: float,
) -> float:
    """
    Calculate stop loss price.

    Example:
        Entry Price = 100
        Stop Loss = 5%

        Result = 95

    Returns:
        Stop loss price.
    """

    if entry_price <= 0:
        raise ValueError("Entry price must be greater than zero.")

    if stop_loss_percent <= 0:
        raise ValueError("Stop loss percent must be greater than zero.")

    stop_loss_price = entry_price * (
        1 - stop_loss_percent / 100
    )

    return stop_loss_price