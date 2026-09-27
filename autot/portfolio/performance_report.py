"""
File: performance_report.py
Project: AutoT

Purpose:
    Calculate paper-trading portfolio and performance statistics.
"""

from pathlib import Path

import pandas as pd

from autot.config.trading_settings import MAX_DAILY_LOSS_PERCENT
from autot.portfolio.paper_portfolio import PaperPortfolio
from autot.portfolio.trade_journal import calculate_daily_realized_loss


DEFAULT_JOURNAL_FILE = "data_storage/processed/trade_journal.csv"


def build_performance_report(
    portfolio: PaperPortfolio,
    target_date,
    journal_file: str = DEFAULT_JOURNAL_FILE,
) -> dict:
    """
    Build a summary of paper-trading performance.
    """

    invested_capital = sum(
        position.average_price * position.quantity
        for position in portfolio.positions.values()
    )

    portfolio_risk = portfolio.calculate_portfolio_risk()

    daily_realized_loss = calculate_daily_realized_loss(
        target_date=target_date,
        file_path=journal_file,
    )

    maximum_daily_loss = (
        portfolio.initial_cash
        * MAX_DAILY_LOSS_PERCENT
        / 100
    )

    remaining_daily_loss_allowance = max(
        0.0,
        maximum_daily_loss - daily_realized_loss,
    )

    report = {
        "initial_cash": round(portfolio.initial_cash, 2),
        "available_cash": round(portfolio.cash, 2),
        "invested_capital": round(invested_capital, 2),
        "open_positions": len(portfolio.positions),
        "portfolio_risk": round(portfolio_risk, 2),
        "completed_trades": 0,
        "profitable_trades": 0,
        "losing_trades": 0,
        "breakeven_trades": 0,
        "win_rate": 0.0,
        "total_realized_profit_loss": 0.0,
        "average_return_percent": 0.0,
        "daily_realized_loss": daily_realized_loss,
        "maximum_daily_loss": round(maximum_daily_loss, 2),
        "remaining_daily_loss_allowance": round(
            remaining_daily_loss_allowance,
            2,
        ),
    }

    path = Path(journal_file)

    if not path.exists():
        return report

    df = pd.read_csv(path)

    if df.empty:
        return report

    required_columns = {
        "outcome",
        "realized_profit_loss",
        "return_percent",
    }

    if not required_columns.issubset(df.columns):
        raise ValueError(
            "Trade journal is missing required columns "
            "for performance reporting."
        )

    completed_trades = len(df)
    profitable_trades = (df["outcome"] == "PROFIT").sum()
    losing_trades = (df["outcome"] == "LOSS").sum()
    breakeven_trades = (df["outcome"] == "BREAKEVEN").sum()

    win_rate = (
        profitable_trades / completed_trades * 100
    )

    total_realized_profit_loss = pd.to_numeric(
        df["realized_profit_loss"],
        errors="coerce",
    ).sum()

    average_return_percent = pd.to_numeric(
        df["return_percent"],
        errors="coerce",
    ).mean()

    report.update({
        "completed_trades": int(completed_trades),
        "profitable_trades": int(profitable_trades),
        "losing_trades": int(losing_trades),
        "breakeven_trades": int(breakeven_trades),
        "win_rate": round(float(win_rate), 2),
        "total_realized_profit_loss": round(
            float(total_realized_profit_loss),
            2,
        ),
        "average_return_percent": round(
            float(average_return_percent),
            2,
        ),
    })

    return report