"""
File: paper_trader.py
Project: AutoT

Purpose:
    Connect ranked stock results to the paper execution engine.
"""

from autot.execution.paper_execution import PaperExecution
from autot.portfolio.paper_portfolio import PaperPortfolio


class PaperTrader:
    """
    Executes paper trades from a ranked stock shortlist.
    """

    def __init__(
        self,
        portfolio: PaperPortfolio,
        execution: PaperExecution,
        trade_amount: float,
    ) -> None:
        if trade_amount <= 0:
            raise ValueError("Trade amount must be greater than zero.")

        self.portfolio = portfolio
        self.execution = execution
        self.trade_amount = trade_amount

    def buy_shortlist(
        self,
        shortlist: list[dict],
        current_prices: dict[str, float],
    ) -> None:
        """
        Buy each stock in the shortlist using fixed trade amount.
        """

        for stock in shortlist:
            symbol = stock["symbol"]

            if symbol not in current_prices:
                print(f"Skipping {symbol}: current price missing.")
                continue

            price = current_prices[symbol]

            if price <= 0:
                print(f"Skipping {symbol}: invalid price.")
                continue

            quantity = int(self.trade_amount // price)

            if quantity <= 0:
                print(f"Skipping {symbol}: trade amount too small.")
                continue

            try:
                self.execution.execute_buy(
                    symbol=symbol,
                    price=price,
                    quantity=quantity,
                )

                print(
                    f"Paper BUY executed: {symbol} | "
                    f"Price: {price:.2f} | "
                    f"Qty: {quantity}"
                )

            except ValueError as error:
                print(f"Could not buy {symbol}: {error}")