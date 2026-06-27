"""
File: strategy_consensus.py
Project: AutoT

Purpose:
    Calculate a final consensus signal from multiple strategy signals.
"""


def calculate_consensus_signal(strategy_results: list[dict]) -> dict:
    """
    Calculate final trading signal from strategy results.

    Args:
        strategy_results:
            Example:
            [
                {"strategy": "EMA_RSI_Strategy", "signal": "BUY"},
                {"strategy": "MACD_Strategy", "signal": "SELL"},
            ]

    Returns:
        Dictionary containing vote counts and final signal.
    """

    buy_votes = 0
    sell_votes = 0
    hold_votes = 0

    for result in strategy_results:
        signal = result["signal"]

        if signal == "BUY":
            buy_votes += 1
        elif signal == "SELL":
            sell_votes += 1
        else:
            hold_votes += 1

    if buy_votes > sell_votes and buy_votes > hold_votes:
        final_signal = "BUY"
    elif sell_votes > buy_votes and sell_votes > hold_votes:
        final_signal = "SELL"
    else:
        final_signal = "HOLD"

    return {
        "buy_votes": buy_votes,
        "sell_votes": sell_votes,
        "hold_votes": hold_votes,
        "final_signal": final_signal,
    }