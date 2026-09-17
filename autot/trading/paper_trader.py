"""
File: paper_trader.py
Project: AutoT

Purpose:
    Coordinate paper trading using AutoT trade decisions,
    portfolio risk controls, and the broker interface.
"""

from autot.broker.broker_interface import BrokerInterface
from autot.decision.trade_decision import TradeDecision
from autot.risk.risk_manager import RiskManager


class PaperTrader:
    """
    Execute approved AutoT trade decisions through a broker.
    """

    def __init__(self, broker: BrokerInterface) -> None:
        self.broker = broker

    def execute_decision(
        self,
        decision: TradeDecision,
        daily_loss_amount: float,
    ) -> dict:
        """
        Evaluate and execute one trade decision.

        V1 paper trading currently supports opening BUY positions only.
        SELL signals are not used to open short positions.
        """

        signal = decision.final_signal.upper()

        if signal == "HOLD":
            return {
                "executed": False,
                "symbol": decision.symbol,
                "signal": signal,
                "reason": "HOLD signal does not create a trade.",
            }

        if signal == "SELL":
            return {
                "executed": False,
                "symbol": decision.symbol,
                "signal": signal,
                "reason": (
                    "Opening short positions is not supported "
                    "in V1 paper trading."
                ),
            }

        if signal != "BUY":
            return {
                "executed": False,
                "symbol": decision.symbol,
                "signal": signal,
                "reason": "Unsupported trading signal.",
            }

        quantity = decision.position_size.quantity

        if quantity <= 0:
            return {
                "executed": False,
                "symbol": decision.symbol,
                "signal": signal,
                "reason": "Calculated position quantity is zero.",
            }

        positions = self.broker.get_positions()
        current_open_positions = len(positions)

        account_balance = self.broker.get_account_balance()
        current_portfolio_risk = self.broker.get_portfolio_risk()

        risk_check = RiskManager.can_open_trade(
            account_balance=account_balance,
            current_open_positions=current_open_positions,
            current_portfolio_risk=current_portfolio_risk,
            new_trade_max_loss=decision.position_size.max_loss,
            daily_loss_amount=daily_loss_amount,
        )

        if not risk_check["can_open_trade"]:
            return {
                "executed": False,
                "symbol": decision.symbol,
                "signal": signal,
                "reason": " ".join(risk_check["reasons"]),
                "risk_check": risk_check,
            }

        try:
            self.broker.buy(
                symbol=decision.symbol,
                quantity=quantity,
                price=decision.entry_price,
                stop_loss=decision.stop_loss,
                max_loss=decision.position_size.max_loss,
            )
        except ValueError as error:
            return {
                "executed": False,
                "symbol": decision.symbol,
                "signal": signal,
                "reason": str(error),
                "risk_check": risk_check,
            }
        return {
            "executed": True,
            "symbol": decision.symbol,
            "signal": signal,
            "quantity": quantity,
            "entry_price": round(decision.entry_price, 2),
            "position_value": decision.position_size.position_value,
            "max_loss": decision.position_size.max_loss,
            "reason": "Paper BUY executed successfully.",
            "risk_check": risk_check,
        }

    def close_position(
        self,
        symbol: str,
        exit_price: float,
    ) -> dict:
        """
        Explicitly close an existing paper position.

        This is separate from a scanner SELL signal.
        V1 closes the entire open position.
        """

        positions = self.broker.get_positions()

        if symbol not in positions:
            return {
                "executed": False,
                "symbol": symbol,
                "action": "CLOSE",
                "reason": f"No open position found for {symbol}.",
            }

        position = positions[symbol]
        quantity = position.quantity
        entry_price = position.average_price

        try:
            self.broker.sell(
                symbol=symbol,
                quantity=quantity,
                price=exit_price,
            )
        except ValueError as error:
            return {
                "executed": False,
                "symbol": symbol,
                "action": "CLOSE",
                "reason": str(error),
            }

        realized_profit_loss = (
            exit_price - entry_price
        ) * quantity

        return {
            "executed": True,
            "symbol": symbol,
            "action": "CLOSE",
            "quantity": quantity,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "realized_profit_loss": round(
                realized_profit_loss,
                2,
            ),
            "reason": "Paper position closed successfully.",
        }