"""
File: take_profit.py
Project: AutoT

Purpose:
    Calculate take profit price.
"""


def calculate_take_profit_price(
    entry_price: float,
    take_profit_percent: float,
) -> float:
    """
    Calculate take profit price.

    Example:
        Entry Price = 100
        Take Profit = 10%

        Result = 110

    Returns:
        Take profit price.
    """

    if entry_price <= 0:
        raise ValueError("Entry price must be greater than zero.")

    if take_profit_percent <= 0:
        raise ValueError("Take profit percent must be greater than zero.")

    take_profit_price = entry_price * (
        1 + take_profit_percent / 100
    )

    return take_profit_price