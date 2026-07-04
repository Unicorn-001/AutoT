"""
File: watchlist_loader.py
Project: AutoT

Purpose:
    Load stock symbols from watchlist CSV files.
"""

import pandas as pd


class WatchlistLoader:
    """
    Loads watchlists from CSV files.
    """

    @staticmethod
    def load_symbols(file_path: str) -> list[str]:
        data = pd.read_csv(file_path)

        if "symbol" not in data.columns:
            raise ValueError("Watchlist CSV must contain a 'symbol' column.")

        return data["symbol"].dropna().astype(str).tolist()