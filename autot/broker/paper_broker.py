"""
File: paper_broker.py
Project: AutoT

Purpose:
    Paper trading broker implementation.
"""

from autot.broker.broker_interface import BrokerInterface
from autot.execution.paper_execution import PaperExecution
from autot.portfolio.paper_portfolio import PaperPortfolio


class PaperBroker(BrokerInterface):
    """
    Paper trading broker.
    """

    def __init__(self, portfolio: PaperPortfolio):
        self.portfolio = portfolio
        self.execution = PaperExecution(portfolio)

    def buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
    ) -> None:
        self.execution.execute_buy(
            symbol=symbol,
            price=price,
            quantity=quantity,
        )

    def sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
    ) -> None:
        # Quantity is currently determined by the open position.
        # It is kept here because every broker implements the same interface.
        _ = quantity

        self.execution.execute_sell(
            symbol=symbol,
            price=price,
        )

    def get_account_balance(self) -> float:
        return self.portfolio.cash

    def get_positions(self):
        return self.portfolio.positions