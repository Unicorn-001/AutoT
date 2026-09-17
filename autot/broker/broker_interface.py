"""
File: broker_interface.py
Project: AutoT

Purpose:
    Define the standard broker interface used by AutoT.

Every broker implementation (Paper, Alpaca, Interactive Brokers, etc.)
must implement this interface.
"""

from abc import ABC, abstractmethod


class BrokerInterface(ABC):
    """
    Base broker interface.
    """
    @abstractmethod
    def buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        stop_loss: float,
        max_loss: float,
    ) -> None:
        """
        Place a buy order.
        """
        pass
    @abstractmethod
    def sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
    ) -> None:
        """
        Place a sell order.
        """
        pass

    @abstractmethod
    def get_account_balance(self) -> float:
        """
        Return current account balance.
        """
        pass

    @abstractmethod
    def get_positions(self):
        """
        Return all open positions.
        """
        pass

    @abstractmethod
    def get_portfolio_risk(self) -> float:
        """
        Return the total maximum risk of all open positions.
        """
        pass
