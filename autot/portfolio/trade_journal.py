"""
File: trade_journal.py
Project: AutoT

Purpose:
    Save paper trading history to a CSV file.
"""

import pandas as pd

from autot.portfolio.trade import Trade


def save_trade_history_to_csv(
    trade_history: list[Trade],
    file_path: str = "data_storage/processed/trade_history.csv",
) -> None:
    """
    Save trade history to CSV file.
    """

    rows = []

    for trade in trade_history:
        rows.append({
            "timestamp": trade.timestamp,
            "action": trade.action,
            "symbol": trade.symbol,
            "price": trade.price,
            "quantity": trade.quantity,
            "total_value": trade.total_value,
        })

    df = pd.DataFrame(rows)
    df.to_csv(file_path, index=False)

    print(f"Trade history saved to: {file_path}")