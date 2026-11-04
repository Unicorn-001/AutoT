"""Serialize already-computed votes. No indicators, scoring or decisions run here."""
from autot.strategy_analysis.models import StrategyFeature, StrategyContribution


def capture_strategies(weighted_results, settings, regime):
    from autot.strategies.registry.strategy_registry import REGISTRY
    results = {r['strategy']: r for r in weighted_results}
    features = []
    for item in REGISTRY:
        config = getattr(settings, item.strategy_id)
        result = results.get(item.implementation().get_name(), {})
        features.append(StrategyFeature(
            strategy_id=item.strategy_id, enabled=config.enabled,
            signal=result.get('signal'), effective_weight=result.get('weight'),
            regime_weight=getattr(config.regime_weights, regime.lower(), None),
            manual_override=config.weight, original_confidence=result.get('original_confidence'),
            weighted_confidence=result.get('confidence'),
        ).model_dump(mode='json'))
    return {'version': 1, 'strategies': features}


def contributions(trade):
    snapshot = trade.get('strategy_features')
    if snapshot and snapshot.get('version') == 1:
        return [StrategyContribution(**r, final_signal=trade['side']) for r in snapshot['strategies']]
    # Only use actual stored legacy votes; do not infer weights or enabled flags
    # from today's settings. A recorded valid vote proves that strategy ran.
    row = trade.get('original_opportunity') or {}
    fields = {'EMA_RSI': 'ema_rsi_signal', 'MACD': 'macd_signal', 'BOLLINGER': 'bollinger_signal',
              'BREAKOUT': 'breakout_signal', 'SUPERTREND': 'supertrend_signal'}
    return [StrategyContribution(strategy_id=name, enabled=True, signal=row[field], final_signal=trade['side'])
            for name, field in fields.items() if row.get(field) in ('BUY', 'SELL', 'HOLD')]
