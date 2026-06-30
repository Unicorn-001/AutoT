"""
File: strategy_consensus.py
Project: AutoT

Purpose:
    Calculate final consensus signal from multiple strategy results.
"""


def calculate_consensus_signal(strategy_results: list[dict]) -> dict:
    """
    Calculate final trading signal using confidence-weighted voting.
    """

    buy_votes = 0
    sell_votes = 0
    hold_votes = 0

    buy_score = 0.0
    sell_score = 0.0
    hold_score = 0.0

    for result in strategy_results:
        signal = result["signal"]
        confidence = result.get("confidence", 0.5)

        if signal == "BUY":
            buy_votes += 1
            buy_score += confidence
        elif signal == "SELL":
            sell_votes += 1
            sell_score += confidence
        else:
            hold_votes += 1
            hold_score += confidence

    if buy_score > sell_score and buy_score > hold_score:
        final_signal = "BUY"
    elif sell_score > buy_score and sell_score > hold_score:
        final_signal = "SELL"
    else:
        final_signal = "HOLD"

    return {
        "buy_votes": buy_votes,
        "sell_votes": sell_votes,
        "hold_votes": hold_votes,
        "buy_score": round(buy_score, 2),
        "sell_score": round(sell_score, 2),
        "hold_score": round(hold_score, 2),
        "final_signal": final_signal,
    }