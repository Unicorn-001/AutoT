"""
File: universe_loader.py
Project: AutoT

Purpose:
    Load stock symbols from a CSV universe file.
"""

import pandas as pd


def load_universe(file_path: str = "autot/universe/my_stocks.csv") -> list[str]:
    """
    Load stock symbols from a CSV file.

    Expected CSV format:
        symbol
        AAPL
        MSFT
        NVDA

    Returns:
        List of stock symbols.
    """

    df = pd.read_csv(file_path)

    if "symbol" not in df.columns:
        raise ValueError("CSV file must contain a 'symbol' column.")

    symbols = df["symbol"].dropna().astype(str).str.strip().str.upper().tolist()

    return symbols