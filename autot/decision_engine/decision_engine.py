"""
File: decision_engine.py
Project: AutoT

Purpose:
    Central decision engine for final BUY / SELL / HOLD decisions.
"""


class DecisionEngine:
    """
    Creates one final decision from consensus scores.
    """

    @staticmethod
    def decide(consensus: dict) -> dict:
        final_signal = consensus["final_signal"]

        reason = (
            f"Final signal is {final_signal}. "
            f"BUY Score={consensus['buy_score']}, "
            f"SELL Score={consensus['sell_score']}, "
            f"HOLD Score={consensus['hold_score']}."
        )

        return {
            "final_signal": final_signal,
            "decision_reason": reason,
        }