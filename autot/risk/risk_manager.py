"""
File: risk_manager.py
Project: AutoT

Purpose:
    Central portfolio risk management for AutoT.
"""

from autot.config.trading_settings import (
    MAX_OPEN_POSITIONS,
    MAX_PORTFOLIO_RISK_PERCENT,
    MAX_DAILY_LOSS_PERCENT,
)

from autot.risk.max_positions import can_open_new_position
from autot.risk.daily_loss_limit import can_continue_trading


class RiskManager:
    """
    Evaluate portfolio-level risk before opening a new trade.
    """

    @staticmethod
    def can_open_trade(
        account_balance: float,
        current_open_positions: int,
        current_portfolio_risk: float,
        new_trade_max_loss: float,
        daily_loss_amount: float,
    ) -> dict:

        if account_balance <= 0:
            raise ValueError(
                "Account balance must be greater than zero."
            )

        if current_open_positions < 0:
            raise ValueError(
                "Current open positions cannot be negative."
            )

        if current_portfolio_risk < 0:
            raise ValueError(
                "Current portfolio risk cannot be negative."
            )

        if new_trade_max_loss < 0:
            raise ValueError(
                "New trade max loss cannot be negative."
            )

        if daily_loss_amount < 0:
            raise ValueError(
                "Daily loss amount cannot be negative."
            )

        # ---------------------------------------------------------
        # Maximum open positions
        # ---------------------------------------------------------

        position_limit_ok = can_open_new_position(
            current_open_positions=current_open_positions,
            maximum_open_positions=MAX_OPEN_POSITIONS,
        )

        # ---------------------------------------------------------
        # Daily loss limit
        # ---------------------------------------------------------

        daily_loss_limit_ok = can_continue_trading(
            account_balance=account_balance,
            daily_loss_amount=daily_loss_amount,
            daily_loss_limit_percent=MAX_DAILY_LOSS_PERCENT,
        )

        # ---------------------------------------------------------
        # Total portfolio risk
        # ---------------------------------------------------------

        maximum_portfolio_risk = (
            account_balance
            * MAX_PORTFOLIO_RISK_PERCENT
            / 100
        )

        proposed_portfolio_risk = (
            current_portfolio_risk
            + new_trade_max_loss
        )

        portfolio_risk_limit_ok = (
            proposed_portfolio_risk
            <= maximum_portfolio_risk
        )

        # ---------------------------------------------------------
        # Final decision
        # ---------------------------------------------------------

        can_open = (
            position_limit_ok
            and daily_loss_limit_ok
            and portfolio_risk_limit_ok
        )

        reasons = []

        if not position_limit_ok:
            reasons.append(
                "Maximum open position limit reached."
            )

        if not daily_loss_limit_ok:
            reasons.append(
                "Maximum daily loss limit reached."
            )

        if not portfolio_risk_limit_ok:
            reasons.append(
                "Maximum portfolio risk limit would be exceeded."
            )

        if can_open:
            reasons.append(
                "Trade passes all portfolio risk checks."
            )

        return {
            "can_open_trade": can_open,
            "position_limit_ok": position_limit_ok,
            "daily_loss_limit_ok": daily_loss_limit_ok,
            "portfolio_risk_limit_ok": portfolio_risk_limit_ok,
            "current_portfolio_risk": round(
                current_portfolio_risk,
                2,
            ),
            "new_trade_max_loss": round(
                new_trade_max_loss,
                2,
            ),
            "proposed_portfolio_risk": round(
                proposed_portfolio_risk,
                2,
            ),
            "maximum_portfolio_risk": round(
                maximum_portfolio_risk,
                2,
            ),
            "reasons": reasons,
        }