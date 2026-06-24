"""
File: ranking_engine.py
Project: AutoT

Purpose:
    Calculate a quality score for each stock based on
    return, win rate, drawdown, and trade reliability.
"""


def calculate_stock_score(
    return_percent: float,
    max_drawdown: float,
    win_rate: float,
    total_trades: int,
) -> float:
    """
    Calculate stock ranking score.

    Professional scoring idea:
        - Positive return increases score.
        - High win rate increases score.
        - High drawdown reduces score.
        - Too few trades reduces confidence.
        - Negative return is penalized heavily.

    Returns:
        Final score.
    """

    return_score = return_percent * 4
    win_rate_score = win_rate * 0.4
    drawdown_penalty = abs(max_drawdown) * 3

    trade_confidence_score = min(total_trades, 20)

    if total_trades < 5:
        trade_confidence_score -= 10

    negative_return_penalty = 0
    if return_percent < 0:
        negative_return_penalty = abs(return_percent) * 10

    total_score = (
        return_score
        + win_rate_score
        + trade_confidence_score
        - drawdown_penalty
        - negative_return_penalty
    )

    return round(total_score, 2)