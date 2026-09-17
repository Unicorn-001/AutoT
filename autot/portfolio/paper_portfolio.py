"""
File: paper_portfolio.py
Project: AutoT

Purpose:
    Manage a simulated paper trading portfolio.
"""

from datetime import datetime

from autot.portfolio.position import Position
from autot.portfolio.trade import Trade


class PaperPortfolio:
    """
    Simulated trading portfolio.

    Tracks:
        - Cash balance
        - Open positions
        - Trade history
        - Realised profit/loss
        - Unrealised profit/loss
    """

    def __init__(self, initial_cash: float) -> None:
        if initial_cash <= 0:
            raise ValueError("Initial cash must be greater than zero.")

        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, Position] = {}
        self.trade_history: list[Trade] = []

    def buy(
        self,
        symbol: str,
        price: float,
        quantity: int,
        stop_loss: float,
        max_loss: float,
    ) -> None:
        """
        Buy a stock in paper trading mode.
        """

        if price <= 0:
            raise ValueError("Price must be greater than zero.")

        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")

        if symbol in self.positions:
            raise ValueError(f"Position already open for {symbol}.")

        total_cost = price * quantity

        if total_cost > self.cash:
            raise ValueError("Not enough cash to buy this position.")


        self.cash -= total_cost

        self.positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            average_price=price,
            stop_loss=stop_loss,
            max_loss=max_loss,
        )

        self.trade_history.append(
            Trade(
                action="BUY",
                symbol=symbol,
                price=price,
                quantity=quantity,
                total_value=total_cost,
                timestamp=datetime.now(),
            )
        )

    def sell(
        self,
        symbol: str,
        price: float,
    ) -> None:
        """
        Sell an open paper trading position.
        """

        if price <= 0:
            raise ValueError("Price must be greater than zero.")

        if symbol not in self.positions:
            raise ValueError(f"No open position found for {symbol}.")

        position = self.positions[symbol]
        total_value = price * position.quantity

        self.cash += total_value

        self.trade_history.append(
            Trade(
                action="SELL",
                symbol=symbol,
                price=price,
                quantity=position.quantity,
                total_value=total_value,
                timestamp=datetime.now(),
            )
        )

        del self.positions[symbol]

    def calculate_open_position_value(
        self,
        current_prices: dict[str, float],
    ) -> float:
        """
        Calculate current market value of all open positions.
        """

        total_value = 0.0

        for symbol, position in self.positions.items():
            if symbol not in current_prices:
                raise ValueError(f"Missing current price for {symbol}.")

            current_price = current_prices[symbol]
            total_value += current_price * position.quantity

        return total_value

    def calculate_unrealised_profit_loss(
        self,
        current_prices: dict[str, float],
    ) -> float:
        """
        Calculate unrealised profit/loss from open positions.
        """

        unrealised_profit_loss = 0.0

        for symbol, position in self.positions.items():
            if symbol not in current_prices:
                raise ValueError(f"Missing current price for {symbol}.")

            current_price = current_prices[symbol]
            entry_value = position.average_price * position.quantity
            current_value = current_price * position.quantity

            unrealised_profit_loss += current_value - entry_value

        return unrealised_profit_loss
    def calculate_portfolio_risk(self) -> float:
        """
        Calculate the total maximum risk of all open positions.
        """

        total_risk = sum(
            position.max_loss
            for position in self.positions.values()
        )

        return round(total_risk, 2)

    def get_summary(
        self,
        current_prices: dict[str, float] | None = None,
    ) -> dict:
        """
        Return portfolio summary.
        """

        open_position_value = 0.0
        unrealised_profit_loss = 0.0

        if current_prices is not None:
            open_position_value = self.calculate_open_position_value(
                current_prices
            )
            unrealised_profit_loss = (
                self.calculate_unrealised_profit_loss(current_prices)
            )

        portfolio_value = self.cash + open_position_value
        total_profit_loss = portfolio_value - self.initial_cash

        return_percent = (
            total_profit_loss / self.initial_cash
        ) * 100

        return {
            "initial_cash": round(self.initial_cash, 2),
            "cash": round(self.cash, 2),
            "open_position_value": round(open_position_value, 2),
            "portfolio_value": round(portfolio_value, 2),
            "unrealised_profit_loss": round(unrealised_profit_loss, 2),
            "total_profit_loss": round(total_profit_loss, 2),
            "return_percent": round(return_percent, 2),
            "open_positions": len(self.positions),
            "trade_count": len(self.trade_history),
        }