"""
File: broker_settings.py
Project: AutoT

Purpose:
    Load broker-related configuration safely from environment variables.
"""

import os

from dotenv import load_dotenv


load_dotenv()


ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv(
    "ALPACA_BASE_URL",
    "https://paper-api.alpaca.markets",
)


def validate_alpaca_settings() -> None:
    """
    Validate Alpaca paper trading settings.
    """

    if not ALPACA_API_KEY:
        raise ValueError("ALPACA_API_KEY is missing in .env file.")

    if not ALPACA_SECRET_KEY:
        raise ValueError("ALPACA_SECRET_KEY is missing in .env file.")