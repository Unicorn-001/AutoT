"""
File: universe_loader.py
Project: AutoT

Purpose:
    Load stock symbols from a CSV universe file.
"""

import pandas as pd
from pathlib import Path

from autot.runtime import project_path


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

    # App-bundled paths are stable across cwd changes. User-supplied CLI paths
    # retain their existing absolute/relative filesystem semantics.
    path = Path(file_path).expanduser()
    if not path.is_absolute() and path.parts[:2] == ("autot", "universe"):
        path = project_path(path)
    df = pd.read_csv(path)

    if "symbol" not in df.columns:
        raise ValueError("CSV file must contain a 'symbol' column.")

    symbols = df["symbol"].dropna().astype(str).str.strip().str.upper().tolist()

    return symbols
