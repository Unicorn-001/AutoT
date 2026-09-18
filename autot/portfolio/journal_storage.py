"""
File: journal_storage.py
Project: AutoT

Purpose:
    Save and load open paper-trade journal entries.
"""

import json
from datetime import datetime
from pathlib import Path

from autot.portfolio.open_journal_entry import OpenJournalEntry


DEFAULT_OPEN_JOURNAL_FILE = (
    "data_storage/processed/open_journal_entries.json"
)


def save_open_journal_entries(
    entries: dict[str, OpenJournalEntry],
    file_path: str = DEFAULT_OPEN_JOURNAL_FILE,
) -> None:
    """
    Save open journal entries to a JSON file.
    """

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {}

    for symbol, entry in entries.items():
        data[symbol] = {
            "symbol": entry.symbol,
            "entry_timestamp": entry.entry_timestamp.isoformat(),
            "entry_price": entry.entry_price,
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
        }

    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def load_open_journal_entries(
    file_path: str = DEFAULT_OPEN_JOURNAL_FILE,
) -> dict[str, OpenJournalEntry]:
    """
    Load open journal entries from a JSON file.

    If no saved file exists, return an empty dictionary.
    """

    path = Path(file_path)

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    entries = {}

    for symbol, item in data.items():
        entries[symbol] = OpenJournalEntry(
            symbol=item["symbol"],
            entry_timestamp=datetime.fromisoformat(
                item["entry_timestamp"]
            ),
            entry_price=item["entry_price"],
            quantity=item["quantity"],
            stop_loss=item["stop_loss"],
            take_profit=item["take_profit"],
            risk_reward_ratio=item["risk_reward_ratio"],
            max_loss=item["max_loss"],
            confidence=item["confidence"],
            agreement=item["agreement"],
            market_regime=item["market_regime"],
            trade_quality_score=item["trade_quality_score"],
            opportunity_score=item["opportunity_score"],
        )

    return entries