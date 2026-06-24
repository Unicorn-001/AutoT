"""
File: settings.py
Project: AutoT

Purpose:
    Store project-wide configuration values.
"""

# Universe selection
ACTIVE_UNIVERSE_FILE = "autot/universe/uk_stocks.csv"

# Backtest settings
BACKTEST_PERIOD = "5y"
BACKTEST_INTERVAL = "1d"

# Capital settings
INITIAL_CAPITAL = 10000
TRADE_AMOUNT = 1000
TRANSACTION_COST_PERCENT = 0.10