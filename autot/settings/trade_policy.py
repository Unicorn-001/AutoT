"""Settings validation and opt-in admission limits inside the ledger transaction."""
from autot.settings.models import TradeSettingsSnapshot
from autot.utils.financial_validation import decimal_value as D


def validate_trade_settings(snapshot):
    if snapshot.get('configuration_source') != 'SETTINGS_V1':
        return None
    fields = TradeSettingsSnapshot.model_fields
    config = TradeSettingsSnapshot.model_validate({k: snapshot[k] for k in fields})
    if D(config.execution_risk_percent) != D(snapshot['risk_percent']):
        raise ValueError('Trade sizing does not match its settings snapshot.')
    return config


def enforce_admission(snapshot, trades, summary):
    config = validate_trade_settings(snapshot)
    if config is None:
        return
    risk = config.trading_settings.risk
    side = snapshot['side']
    if (side == 'BUY' and not risk.allow_buy) or (side == 'SELL' and not risk.allow_sell):
        raise ValueError(f'{side} trades are disabled by this strategy profile.')
    entry, stop, target = (D(snapshot[k]) for k in ('signal_price', 'stop_loss', 'take_profit'))
    rr = abs(target - entry) / abs(entry - stop)
    if rr < D(risk.minimum_risk_reward):
        raise ValueError('Trade is below the configured minimum risk/reward.')
    # Limits and reservations cover the whole currency account across modes.
    # Research does not receive a second risk or capital allowance.
    scope = [t for t in trades if t['currency'] == snapshot['currency']]
    positions = [t for t in scope if t['status'] in ('PENDING_ENTRY', 'OPEN')]
    capital = summary['capital']
    if risk.enforce_position_limit and D(snapshot['intended_position_value']) > capital * D(risk.maximum_position_percent) / 100:
        raise ValueError('Trade exceeds the maximum position percent.')
    if risk.enforce_positions_limit and len(positions) >= risk.maximum_simultaneous_positions:
        raise ValueError('Maximum simultaneous positions reached (including pending entries).')
    if risk.enforce_portfolio_risk_limit:
        reserved_risk = sum((abs(D(t['fill_price'] or t['signal_price']) - D(t['stop_loss'])) * t['quantity']
                             for t in positions), D(0))
        new_risk = abs(entry - stop) * snapshot['quantity']
        if reserved_risk + new_risk > capital * D(risk.maximum_total_portfolio_risk_percent) / 100:
            raise ValueError('Trade exceeds the maximum total portfolio risk percent.')
    if risk.enforce_daily_trade_limit:
        today = snapshot['created_at'][:10]
        if sum(t['created_at'][:10] == today for t in scope) >= risk.maximum_new_trades_per_day:
            raise ValueError('Maximum new trades per UTC day reached.')
