"""
File: trading_settings.py
Project: AutoT

Purpose:
    Central trading and risk configuration for AutoT.
"""


from autot.settings.models import AutoTSettings

_BASELINE = AutoTSettings()
ACCOUNT_SIZE = _BASELINE.paper_trading.usd_base_capital
RISK_PER_TRADE = _BASELINE.risk.risk_per_trade_percent

MAX_OPEN_POSITIONS = 5
MAX_PORTFOLIO_RISK_PERCENT = 5.0
MAX_DAILY_LOSS_PERCENT = 3.0

DEFAULT_STOP_LOSS_PERCENT = 2.0
DEFAULT_TAKE_PROFIT_PERCENT = 4.0
MIN_CONFIDENCE = _BASELINE.consensus.minimum_confidence