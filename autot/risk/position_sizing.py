"""
File: position_sizing.py
Project: AutoT

Purpose:
    Calculate trade position size based on account balance,
    risk percentage, and stop-loss distance.
"""


def calculate_position_size(
    account_balance: float,
    risk_percent: float,
    stop_loss_percent: float,
) -> float:
    """
    Calculate how much money should be used for one trade.

    Example:
        account_balance = 10000
        risk_percent = 1
        stop_loss_percent = 5

        risk_amount = 100
        position_size = 2000

    Returns:
        Position size in account currency.
    """

    if account_balance <= 0:
        raise ValueError("Account balance must be greater than zero.")

    if risk_percent <= 0:
        raise ValueError("Risk percent must be greater than zero.")

    if stop_loss_percent <= 0:
        raise ValueError("Stop loss percent must be greater than zero.")

    risk_amount = account_balance * (risk_percent / 100)
    position_size = risk_amount / (stop_loss_percent / 100)

    return position_size