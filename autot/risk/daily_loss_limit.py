"""
File: daily_loss_limit.py
Project: AutoT

Purpose:
    Prevent further trading after exceeding the
    maximum daily loss.
"""


def can_continue_trading(
    account_balance: float,
    daily_loss_amount: float,
    daily_loss_limit_percent: float,
) -> bool:
    """
    Determine whether trading should continue.

    Example:
        Account balance = £10,000
        Daily loss = £200
        Daily loss limit = 3%

        Maximum loss allowed = £300

        Result = True
    """

    if account_balance <= 0:
        raise ValueError(
            "Account balance must be greater than zero."
        )

    if daily_loss_limit_percent <= 0:
        raise ValueError(
            "Daily loss limit percent must be greater than zero."
        )

    maximum_daily_loss = (
        account_balance * daily_loss_limit_percent / 100
    )

    return daily_loss_amount < maximum_daily_loss