"""Explicit Yahoo Finance symbol normalization shared by universe and price loaders."""

import re


def normalize_market_data_symbol(symbol: str) -> str:
    """Normalize class A/B dot notation; leave other suffix conventions untouched.

    Do not replace every dot: units, warrants and international exchange suffixes
    have different meanings. Unknown source notation is retained, never guessed.
    """
    symbol = symbol.strip().upper()
    if re.fullmatch(r"[A-Z]+\.[AB]", symbol):
        return symbol.replace(".", "-")
    return symbol
