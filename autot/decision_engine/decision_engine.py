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
    def decide(consensus: dict, settings=None) -> dict:
        from autot.settings.models import Consensus
        settings = settings or Consensus()
        minimum_confidence = settings.minimum_confidence
        buy = consensus["buy_score"]
        sell = consensus["sell_score"]
        hold = consensus["hold_score"]

        total = buy + sell + hold

        if total == 0:
            confidence = 0.0
        else:
            confidence = max(buy, sell, hold) / total

        confidence_percent = round(confidence * 100, 2)
        final_signal = consensus["final_signal"]

        scores = [buy, sell, hold]
        sorted_scores = sorted(scores, reverse=True)

        highest_score = sorted_scores[0]
        second_highest_score = sorted_scores[1]

        if highest_score == 0:
            agreement = 0.0
        else:
            agreement = (
                (highest_score - second_highest_score)
                / highest_score
            ) * 100

        agreement_percent = round(agreement, 2)
        if final_signal in ["BUY", "SELL"] and confidence_percent < minimum_confidence:
            final_signal = "HOLD"
            reason = (
                f"Signal changed to HOLD because confidence "
                f"{confidence_percent}% is below minimum threshold "
                f"{minimum_confidence}%."
            )
        else:
            reason = (
                f"Final signal is {final_signal}. "
                f"BUY Score={buy}, "
                f"SELL Score={sell}, "
                f"HOLD Score={hold}."
            )

        if final_signal in ('BUY', 'SELL') and agreement_percent < settings.minimum_agreement:
            final_signal = 'HOLD'
            reason = f'Signal changed to HOLD because agreement {agreement_percent}% is below minimum threshold {settings.minimum_agreement}%.'

        return {
            "final_signal": final_signal,
            "decision_reason": reason,
            "confidence": confidence_percent,
            "agreement": agreement_percent,
        }