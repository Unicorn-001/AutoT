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


def normalize_index_symbol(source_symbol: str, exchange: str) -> str:
    """Validate index source notation and return Yahoo notation without mutating it.

    LSE terminal dots (NG., BP., RR.) are punctuation, internal dots denote
    share classes (BT.A -> BT-A.L). Explicit exchange suffixes are idempotent.
    NSE ampersands and hyphens are meaningful (M&M, BAJAJ-AUTO).
    The BSE branch reserves the same interface for a future constituent adapter.
    """
    if not isinstance(source_symbol, str):
        raise ValueError("Missing source symbol")
    symbol = source_symbol.strip().upper()
    if exchange == "US":
        if not re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.-][A-Z])?", symbol):
            raise ValueError("Invalid US constituent symbol")
        return symbol.replace(".", "-")
    suffixes = {"LSE": ".L", "NSE": ".NS", "BSE": ".BO"}
    if exchange not in suffixes:
        raise ValueError("Unsupported exchange")
    suffix = suffixes[exchange]
    if symbol.endswith(suffix):
        symbol = symbol[:-len(suffix)]
    if exchange == "LSE":
        if not re.fullmatch(r"[A-Z0-9]+(?:[.-][A-Z])?\.?", symbol):
            raise ValueError("Invalid LSE constituent symbol")
        symbol = symbol.removesuffix(".").replace(".", "-")
    elif not re.fullmatch(r"[A-Z0-9][A-Z0-9&-]*", symbol):
        raise ValueError("Invalid Indian constituent symbol")
    if len(symbol) > 24:
        raise ValueError("Constituent symbol too long")
    return symbol + suffix
