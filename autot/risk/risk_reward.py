"""
File: risk_reward.py
Project: AutoT

Purpose:
    Calculate risk-to-reward ratio for BUY and SELL trades.
"""


def calculate_risk_reward_ratio(
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
    signal: str,
) -> float:
    """
    Calculate risk-reward ratio for BUY or SELL trades.
    """

    if entry_price <= 0:
        raise ValueError("Entry price must be greater than zero.")

    signal = signal.upper()

    if signal == "BUY":
        if stop_loss_price >= entry_price:
            raise ValueError(
                "For BUY trades, stop loss must be below entry price."
            )

        if take_profit_price <= entry_price:
            raise ValueError(
                "For BUY trades, take profit must be above entry price."
            )

        risk = entry_price - stop_loss_price
        reward = take_profit_price - entry_price

    elif signal == "SELL":
        if stop_loss_price <= entry_price:
            raise ValueError(
                "For SELL trades, stop loss must be above entry price."
            )

        if take_profit_price >= entry_price:
            raise ValueError(
                "For SELL trades, take profit must be below entry price."
            )

        risk = stop_loss_price - entry_price
        reward = entry_price - take_profit_price

    else:
        raise ValueError(
            "Signal must be either 'BUY' or 'SELL'."
        )

    if risk <= 0:
        raise ValueError("Calculated risk must be greater than zero.")

    ratio = reward / risk

    return round(ratio, 2)