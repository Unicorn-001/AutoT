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
            "trend_strength_score": entry.trend_strength_score,
            "trend_strength_label": entry.trend_strength_label,
            "volume_ratio": entry.volume_ratio,
            "volume_strength_score": entry.volume_strength_score,
            "volume_strength_label": entry.volume_strength_label,
            "volume_confirmed": entry.volume_confirmed,
            "stock_return_percent": entry.stock_return_percent,
            "benchmark_return_percent": entry.benchmark_return_percent,
            "relative_strength_percent": entry.relative_strength_percent,
            "relative_strength_score": entry.relative_strength_score,
            "relative_strength_label": entry.relative_strength_label,
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
            trend_strength_score=item.get(
                "trend_strength_score",
                0.0,
            ),
            trend_strength_label=item.get(
                "trend_strength_label",
                "UNKNOWN",
            ),
            volume_ratio=item.get(
                "volume_ratio",
                0.0,
            ),
            volume_strength_score=item.get(
                "volume_strength_score",
                0.0,
            ),
            volume_strength_label=item.get(
                "volume_strength_label",
                "UNKNOWN",
            ),
            volume_confirmed=item.get(
                "volume_confirmed",
                False,
            ),
            stock_return_percent=item.get(
                "stock_return_percent",
                0.0,
            ),
            benchmark_return_percent=item.get(
                "benchmark_return_percent",
                0.0,
            ),
            relative_strength_percent=item.get(
                "relative_strength_percent",
                0.0,
            ),
            relative_strength_score=item.get(
                "relative_strength_score",
                0.0,
            ),
            relative_strength_label=item.get(
                "relative_strength_label",
                "UNKNOWN",
            ),
        )

    return entries
