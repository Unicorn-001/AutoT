"""
File: portfolio_storage.py
Project: AutoT

Purpose:
    Save and load paper portfolio state.
"""

import json
from datetime import datetime
from pathlib import Path

from autot.portfolio.paper_portfolio import PaperPortfolio
from autot.portfolio.position import Position
from autot.portfolio.trade import Trade

DEFAULT_PORTFOLIO_FILE = (
    "data_storage/processed/paper_portfolio_state.json"
)


def save_portfolio(
    portfolio: PaperPortfolio,
    file_path: str = DEFAULT_PORTFOLIO_FILE,
) -> None:
    """
    Save the current paper portfolio state to a JSON file.
    """

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "initial_cash": portfolio.initial_cash,
        "cash": portfolio.cash,
        "positions": {
            symbol: {
                "quantity": position.quantity,
                "average_price": position.average_price,
                "stop_loss": position.stop_loss,
                "max_loss": position.max_loss,
            }
            for symbol, position in portfolio.positions.items()
        },
        "trade_history": [
            {
                "action": trade.action,
                "symbol": trade.symbol,
                "price": trade.price,
                "quantity": trade.quantity,
                "total_value": trade.total_value,
                "timestamp": trade.timestamp.isoformat(),
            }
            for trade in portfolio.trade_history
        ],
    }

    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def load_portfolio(
    file_path: str = DEFAULT_PORTFOLIO_FILE,
) -> PaperPortfolio:
    """
    Load a paper portfolio from a JSON state file.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Paper portfolio state file not found: {file_path}"
        )

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    portfolio = PaperPortfolio(
        initial_cash=float(data["initial_cash"])
    )

    portfolio.cash = float(data["cash"])

    portfolio.positions = {
        symbol: Position(
            symbol=symbol,
            quantity=int(position_data["quantity"]),
            average_price=float(position_data["average_price"]),
            stop_loss=float(position_data["stop_loss"]),
            max_loss=float(position_data["max_loss"]),
        )
        for symbol, position_data in data["positions"].items()
    }

    portfolio.trade_history = [
        Trade(
            action=trade_data["action"],
            symbol=trade_data["symbol"],
            price=float(trade_data["price"]),
            quantity=int(trade_data["quantity"]),
            total_value=float(trade_data["total_value"]),
            timestamp=datetime.fromisoformat(
                trade_data["timestamp"]
            ),
        )
        for trade_data in data["trade_history"]
    ]

    return portfolio

def load_or_create_portfolio(
    initial_cash: float,
    file_path: str = DEFAULT_PORTFOLIO_FILE,
) -> PaperPortfolio:
    """
    Load an existing paper portfolio or create a new one.

    If no saved portfolio state exists, a fresh portfolio is created
    using the supplied initial cash value.
    """

    path = Path(file_path)

    if path.exists():
        return load_portfolio(file_path)

    return PaperPortfolio(initial_cash=initial_cash)