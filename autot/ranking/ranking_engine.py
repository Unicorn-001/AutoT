"""
File: ranking_engine.py
Project: AutoT

Purpose:
    Calculate a quality score for each stock based on
    backtest performance and risk.
"""


def calculate_stock_score(
    return_percent: float,
    max_drawdown: float,
    win_rate: float,
    total_trades: int,
) -> float:
    """
    Calculate stock ranking score.

    Scoring logic:
        Higher return       = better
        Higher win rate     = better
        Lower drawdown      = better
        More valid trades   = better

    Returns:
        Score between 0 and 100 approximately.
    """

    return_score = return_percent * 3
    win_rate_score = win_rate * 0.3
    drawdown_score = abs(max_drawdown) * -2
    trade_score = min(total_trades, 20) * 1

    total_score = (
        return_score
        + win_rate_score
        + drawdown_score
        + trade_score
    )

    return round(total_score, 2)