"""
File: position_size_calculator.py
Project: AutoT

Purpose:
    Calculate position sizing using fixed percentage risk.
"""

from autot.position.position_size import PositionSize


class PositionSizeCalculator:

    @staticmethod
    def calculate(
        account_size: float,
        risk_percent: float,
        entry_price: float,
        stop_loss: float,
    ) -> PositionSize:

        if account_size <= 0:
            raise ValueError(
                "Account size must be greater than zero."
            )

        if risk_percent < 0:
            raise ValueError(
                "Risk percent cannot be negative."
            )

        if entry_price <= 0:
            raise ValueError(
                "Entry price must be greater than zero."
            )

        if stop_loss < 0:
            raise ValueError(
                "Stop loss cannot be negative."
            )

        risk_amount = account_size * (
            risk_percent / 100
        )

        risk_per_share = abs(
            entry_price - stop_loss
        )

        if risk_per_share == 0 or risk_amount == 0:
            quantity = 0

        else:
            risk_based_quantity = int(
                risk_amount / risk_per_share
            )

            capital_based_quantity = int(
                account_size / entry_price
            )

            quantity = min(
                risk_based_quantity,
                capital_based_quantity,
            )

        position_value = (
            quantity * entry_price
        )

        max_loss = (
            quantity * risk_per_share
        )

        return PositionSize(
            account_size=round(account_size, 2),
            risk_percent=round(risk_percent, 2),
            risk_amount=round(risk_amount, 2),
            entry_price=round(entry_price, 2),
            stop_loss=round(stop_loss, 2),
            risk_per_share=round(
                risk_per_share,
                2,
            ),
            quantity=quantity,
            position_value=round(
                position_value,
                2,
            ),
            max_loss=round(
                max_loss,
                2,
            ),
        )