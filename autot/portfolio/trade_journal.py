"""
File: trade_journal.py
Project: AutoT

Purpose:
    Save paper trading history to a CSV file.
"""

import pandas as pd

from autot.portfolio.trade import Trade
from autot.portfolio.journal_entry import JournalEntry
from datetime import datetime

from autot.portfolio.open_journal_entry import OpenJournalEntry
from pathlib import Path

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

def save_journal_entries_to_csv(
    journal_entries: list[JournalEntry],
    file_path: str = "data_storage/processed/trade_journal.csv",
) -> None:
    """
    Save completed paper-trade journal entries to CSV.
    """

    rows = []

    for entry in journal_entries:
        rows.append({
            "symbol": entry.symbol,
            "entry_timestamp": entry.entry_timestamp,
            "exit_timestamp": entry.exit_timestamp,
            "entry_price": entry.entry_price,
            "exit_price": entry.exit_price,
            "quantity": entry.quantity,
            "stop_loss": entry.stop_loss,
            "take_profit": entry.take_profit,
            "risk_reward_ratio": entry.risk_reward_ratio,
            "max_loss": entry.max_loss,
            "confidence": entry.confidence,
            "agreement": entry.agreement,
            "market_regime": entry.market_regime,
            "trade_quality_score": entry.trade_quality_score,
            "opportunity_score": entry.opportunity_score,
            "realized_profit_loss": entry.realized_profit_loss,
            "return_percent": entry.return_percent,
            "outcome": entry.outcome,
            "exit_reason": entry.exit_reason,
        })

    df = pd.DataFrame(rows)
    df.to_csv(file_path, index=False)

    print(f"Trade journal saved to: {file_path}")

def append_journal_entry_to_csv(
    entry: JournalEntry,
    file_path: str = "data_storage/processed/trade_journal.csv",
) -> None:
    """
    Append one completed paper-trade journal entry to CSV.
    """

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    row = {
        "symbol": entry.symbol,
        "entry_timestamp": entry.entry_timestamp,
        "exit_timestamp": entry.exit_timestamp,
        "entry_price": entry.entry_price,
        "exit_price": entry.exit_price,
        "quantity": entry.quantity,
        "stop_loss": entry.stop_loss,
        "take_profit": entry.take_profit,
        "risk_reward_ratio": entry.risk_reward_ratio,
        "max_loss": entry.max_loss,
        "confidence": entry.confidence,
        "agreement": entry.agreement,
        "market_regime": entry.market_regime,
        "trade_quality_score": entry.trade_quality_score,
        "opportunity_score": entry.opportunity_score,
        "realized_profit_loss": entry.realized_profit_loss,
        "return_percent": entry.return_percent,
        "outcome": entry.outcome,
        "exit_reason": entry.exit_reason,
    }

    file_exists = path.exists()

    df = pd.DataFrame([row])

    df.to_csv(
        path,
        mode="a",
        header=not file_exists,
        index=False,
    )

    print(f"Trade journal entry appended to: {file_path}")

def complete_journal_entry(
    open_entry: OpenJournalEntry,
    exit_price: float,
    exit_timestamp: datetime,
    exit_reason: str,
) -> JournalEntry:
    """
    Convert an open journal entry into a completed journal entry.
    """

    realized_profit_loss = (
        exit_price - open_entry.entry_price
    ) * open_entry.quantity

    entry_value = (
        open_entry.entry_price * open_entry.quantity
    )

    if entry_value == 0:
        return_percent = 0.0
    else:
        return_percent = (
            realized_profit_loss / entry_value
        ) * 100

    if realized_profit_loss > 0:
        outcome = "PROFIT"
    elif realized_profit_loss < 0:
        outcome = "LOSS"
    else:
        outcome = "BREAKEVEN"

    return JournalEntry(
        symbol=open_entry.symbol,
        entry_timestamp=open_entry.entry_timestamp,
        exit_timestamp=exit_timestamp,
        entry_price=open_entry.entry_price,
        exit_price=exit_price,
        quantity=open_entry.quantity,
        stop_loss=open_entry.stop_loss,
        take_profit=open_entry.take_profit,
        risk_reward_ratio=open_entry.risk_reward_ratio,
        max_loss=open_entry.max_loss,
        confidence=open_entry.confidence,
        agreement=open_entry.agreement,
        market_regime=open_entry.market_regime,
        trade_quality_score=open_entry.trade_quality_score,
        opportunity_score=open_entry.opportunity_score,
        realized_profit_loss=round(
            realized_profit_loss,
            2,
        ),
        return_percent=round(
            return_percent,
            2,
        ),
        outcome=outcome,
        exit_reason=exit_reason,
    )