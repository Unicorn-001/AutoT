"""
File: paper_execution.py
Project: AutoT

Purpose:
    Execute simulated paper trades using the PaperPortfolio.
"""

from autot.portfolio.paper_portfolio import PaperPortfolio


class PaperExecution:
    """
    Handles simulated trade execution.

    This class does not decide which stock to buy.
    It only executes a requested buy or sell on the paper portfolio.
    """

    def __init__(self, portfolio: PaperPortfolio) -> None:
        self.portfolio = portfolio

    def execute_buy(
        self,
        symbol: str,
        price: float,
        quantity: int,
    ) -> None:
        """
        Execute a simulated buy order.
        """

        self.portfolio.buy(
            symbol=symbol,
            price=price,
            quantity=quantity,
        )

    def execute_sell(
        self,
        symbol: str,
        price: float,
    ) -> None:
        """
        Execute a simulated sell order.
        """

        self.portfolio.sell(
            symbol=symbol,
            price=price,
        )