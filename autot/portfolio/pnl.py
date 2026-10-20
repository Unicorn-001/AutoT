"""Shared long/short P&L, supporting floats and Decimal without coercion."""


def calculate_pnl(entry_price, current_price, quantity, side="BUY"):
    if side not in ("BUY", "SELL"):
        raise ValueError("P&L side must be BUY or SELL.")
    return (current_price - entry_price if side == "BUY" else entry_price - current_price) * quantity
