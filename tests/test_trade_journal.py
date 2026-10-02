"""
File: test_trade_journal.py
Project: AutoT

Purpose:
    Test the complete paper-trade journal lifecycle without
    modifying real AutoT journal data.
"""

from datetime import datetime

from autot.portfolio.journal_storage import (
    load_open_journal_entries,
    save_open_journal_entries,
)
from autot.portfolio.open_journal_entry import OpenJournalEntry
from autot.portfolio.trade_journal import (
    append_journal_entry_to_csv,
    complete_journal_entry,
)


def test_complete_trade_journal_lifecycle(tmp_path):
    """
    Verify that trade-analysis context survives:

    OpenJournalEntry
        -> JSON
        -> reload
        -> completed JournalEntry
        -> CSV
    """

    json_file = tmp_path / "open_journal.json"
    csv_file = tmp_path / "trade_journal.csv"

    open_entry = OpenJournalEntry(
        symbol="TEST",
        entry_timestamp=datetime(2026, 10, 1, 10, 0),
        entry_price=100.0,
        quantity=10,
        stop_loss=95.0,
        take_profit=110.0,
        risk_reward_ratio=2.0,
        max_loss=50.0,
        confidence=85.0,
        agreement=80.0,
        market_regime="STRONG_UPTREND",
        trade_quality_score=82.0,
        opportunity_score=88.0,

        trend_strength_score=78.5,
        trend_strength_label="STRONG_TREND",

        volume_ratio=1.75,
        volume_strength_score=84.25,
        volume_strength_label="STRONG_VOLUME",
        volume_confirmed=True,

        stock_return_percent=12.5,
        benchmark_return_percent=5.25,
        relative_strength_percent=7.25,
        relative_strength_score=86.5,
        relative_strength_label="STRONG",

        nearest_support=96.5,
        nearest_resistance=102.5,
        distance_to_support_percent=3.5,
        distance_to_resistance_percent=2.5,
        support_resistance_score=81.25,
        support_resistance_label="FAVOURABLE",
        breakout_confirmation_score=88.75,
    )

    # -----------------------------------------------------
    # Save open journal
    # -----------------------------------------------------

    save_open_journal_entries(
        {"TEST": open_entry},
        file_path=str(json_file),
    )

    assert json_file.exists()

    # -----------------------------------------------------
    # Reload open journal
    # -----------------------------------------------------

    loaded_entries = load_open_journal_entries(
        file_path=str(json_file),
    )

    assert "TEST" in loaded_entries

    loaded = loaded_entries["TEST"]

    assert loaded.trend_strength_score == 78.5
    assert loaded.trend_strength_label == "STRONG_TREND"

    assert loaded.volume_ratio == 1.75
    assert loaded.volume_strength_score == 84.25
    assert loaded.volume_strength_label == "STRONG_VOLUME"
    assert loaded.volume_confirmed is True

    assert loaded.stock_return_percent == 12.5
    assert loaded.benchmark_return_percent == 5.25
    assert loaded.relative_strength_percent == 7.25
    assert loaded.relative_strength_score == 86.5
    assert loaded.relative_strength_label == "STRONG"

    assert loaded.nearest_support == 96.5
    assert loaded.nearest_resistance == 102.5
    assert loaded.distance_to_support_percent == 3.5
    assert loaded.distance_to_resistance_percent == 2.5
    assert loaded.support_resistance_score == 81.25
    assert loaded.support_resistance_label == "FAVOURABLE"
    assert loaded.breakout_confirmation_score == 88.75

    # -----------------------------------------------------
    # Complete trade
    # -----------------------------------------------------

    completed = complete_journal_entry(
        open_entry=loaded,
        exit_timestamp=datetime(2026, 10, 5, 10, 0),
        exit_price=108.0,
        exit_reason="TEST_EXIT",
    )

    assert completed.realized_profit_loss == 80.0
    assert completed.return_percent == 8.0
    assert completed.outcome == "PROFIT"

    assert completed.trend_strength_score == 78.5
    assert completed.volume_strength_score == 84.25
    assert completed.relative_strength_score == 86.5
    assert completed.support_resistance_score == 81.25
    assert completed.breakout_confirmation_score == 88.75

    # -----------------------------------------------------
    # Write completed journal
    # -----------------------------------------------------

    append_journal_entry_to_csv(
        completed,
        file_path=str(csv_file),
    )

    assert csv_file.exists()

    content = csv_file.read_text()

    required_columns = [
        "trend_strength_score",
        "trend_strength_label",
        "volume_ratio",
        "volume_strength_score",
        "volume_strength_label",
        "volume_confirmed",
        "stock_return_percent",
        "benchmark_return_percent",
        "relative_strength_percent",
        "relative_strength_score",
        "relative_strength_label",
        "nearest_support",
        "nearest_resistance",
        "distance_to_support_percent",
        "distance_to_resistance_percent",
        "support_resistance_score",
        "support_resistance_label",
        "breakout_confirmation_score",
    ]

    for column in required_columns:
        assert column in content

    assert "STRONG_TREND" in content
    assert "STRONG_VOLUME" in content
    assert "FAVOURABLE" in content
    assert "88.75" in content
