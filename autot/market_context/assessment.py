"""Deterministic V1 assessment. Percentages use percentage points (1 means 1%)."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
import uuid


@dataclass(frozen=True)
class Thresholds:
    reject_rr_below: float = 1.0
    eligible_rr_min: float = 1.5
    caution_gap_percent: float = 1.0
    caution_reward_consumed_percent: float = 25.0

    def __post_init__(self):
        values = asdict(self)
        if any(not math.isfinite(v) or v < 0 for v in values.values()):
            raise ValueError('Thresholds must be finite and nonnegative')
        if self.eligible_rr_min < self.reject_rr_below:
            raise ValueError('Eligible R:R must be at least rejection R:R')


DEFAULT_THRESHOLDS = Thresholds()
REASONS = {
    'INVALID_MARKET_DATA': 'Missing, non-finite or invalid setup/price data.',
    'INVALID_STOP_RELATIVE_TO_CURRENT': 'Current price has reached or crossed the stop.',
    'TARGET_ALREADY_REACHED': 'Current price has reached or crossed the target.',
    'RISK_REWARD_DETERIORATED': 'Current R:R is below the required threshold; do not chase.',
    'LARGE_GAP': 'Absolute gap from the reference entry meets the caution threshold.',
    'REWARD_ALREADY_CONSUMED': 'Too much of the original reward has already been consumed.',
    'SETUP_STILL_VALID': 'The setup remains valid at the assessed price.',
}


def number(value):
    try:
        result = float(value) if not isinstance(value, bool) else math.nan
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def assess(*, symbol, side, reference_entry, stop_loss, take_profit, original_rr,
           current_price, assessed_at=None, market_session=None, source=None,
           scanner_run_id=None, opportunity_id=None, thresholds=DEFAULT_THRESHOLDS):
    """Return a new snapshot without modifying input data or placing trades."""
    fields = dict(reference_entry=reference_entry, stop_loss=stop_loss,
                  take_profit=take_profit, original_rr=original_rr, current_price=current_price)
    a = dict(assessment_id=uuid.uuid4().hex, symbol=symbol, side=side,
             scanner_run_id=scanner_run_id, opportunity_id=opportunity_id,
             assessed_at=assessed_at or datetime.now(timezone.utc).isoformat(),
             market_session=market_session, source=source, version=1,
             thresholds=asdict(thresholds), **{k: number(v) for k, v in fields.items()})
    a.update({k: None for k in ('gap_absolute', 'gap_percent', 'current_risk', 'current_reward',
                              'current_rr', 'rr_deterioration', 'reward_consumed_percent',
                              'distance_to_stop_absolute', 'distance_to_stop_percent',
                              'distance_to_target_absolute', 'distance_to_target_percent',
                              'stop_crossed', 'target_crossed')})
    a.update(decision='REJECT', reason_codes=['INVALID_MARKET_DATA'])
    if side not in ('BUY', 'SELL') or not symbol or any(a[k] is None or a[k] <= 0 for k in fields):
        return a
    entry, stop, target, price = (a[k] for k in ('reference_entry', 'stop_loss', 'take_profit', 'current_price'))
    direction = 1 if side == 'BUY' else -1
    original_risk = direction * (entry - stop)
    original_reward = direction * (target - entry)
    if original_risk <= 0 or original_reward <= 0:
        return a
    risk, reward = direction * (price - stop), direction * (target - price)
    a.update(gap_absolute=abs(price - entry), gap_percent=abs(price - entry) / entry * 100,
             current_risk=risk, current_reward=reward,
             distance_to_stop_absolute=abs(price - stop), distance_to_stop_percent=abs(price - stop) / price * 100,
             distance_to_target_absolute=abs(target - price), distance_to_target_percent=abs(target - price) / price * 100,
             reward_consumed_percent=max(0.0, direction * (price - entry) / original_reward * 100),
             stop_crossed=risk <= 0, target_crossed=reward <= 0)
    if risk > 0 and reward > 0:
        a['current_rr'] = reward / risk
        a['rr_deterioration'] = a['original_rr'] - a['current_rr']
    if any(isinstance(v, float) and not math.isfinite(v) for v in a.values()):
        return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in a.items()}
    reasons = []
    reject = False
    if a['stop_crossed']:
        reasons.append('INVALID_STOP_RELATIVE_TO_CURRENT')
        reject = True
    if a['target_crossed']:
        reasons.append('TARGET_ALREADY_REACHED')
        reject = True
    if a['current_rr'] is not None and a['current_rr'] < thresholds.eligible_rr_min:
        reasons.append('RISK_REWARD_DETERIORATED')
        reject = a['current_rr'] < thresholds.reject_rr_below
    if a['gap_percent'] >= thresholds.caution_gap_percent:
        reasons.append('LARGE_GAP')
    if a['reward_consumed_percent'] > thresholds.caution_reward_consumed_percent:
        reasons.append('REWARD_ALREADY_CONSUMED')
    a.update(decision='REJECT' if reject else 'CAUTION' if reasons else 'ELIGIBLE',
             reason_codes=reasons or ['SETUP_STILL_VALID'])
    return a
