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
        stop_loss: float,
        max_loss: float,
    ) -> None:

        self.execution.execute_buy(
        symbol=symbol,
        price=price,
        quantity=quantity,
        stop_loss=stop_loss,
        max_loss=max_loss,
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
        """
        Return the account value used for V1 risk calculations.

        V1 uses initial paper capital as the risk base.
        This can later be replaced by current portfolio equity
        when live position prices are available.
        """
        return self.portfolio.initial_cash

    def get_positions(self):
        return self.portfolio.positions

    def get_portfolio_risk(self) -> float:
        """
        Return the total maximum risk of all open paper positions.
        """
        return self.portfolio.calculate_portfolio_risk()
