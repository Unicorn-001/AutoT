"""
File: risk_reward.py
Project: AutoT

Purpose:
    Calculate risk-to-reward ratio.
"""


def calculate_risk_reward_ratio(
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
) -> float:
    """
    Calculate risk-reward ratio.

    Example:
        Entry Price = 100
        Stop Loss = 95
        Take Profit = 110

        Risk = 5
        Reward = 10

        Ratio = 2.0

    Returns:
        Risk-reward ratio.
    """

    if stop_loss_price >= entry_price:
        raise ValueError(
            "Stop loss must be below entry price."
        )

    if take_profit_price <= entry_price:
        raise ValueError(
            "Take profit must be above entry price."
        )

    risk = entry_price - stop_loss_price
    reward = take_profit_price - entry_price

    ratio = reward / risk

    return ratio