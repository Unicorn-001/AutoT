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
    """Compatibility entry point; the portfolio engine owns admission policy."""
    from autot.portfolio_risk.engine import evaluate_admission
    from autot.portfolio_risk.models import PortfolioRiskRejected
    result = evaluate_admission(snapshot, trades, summary)
    if not result.allowed:
        raise PortfolioRiskRejected(result)
    return result
