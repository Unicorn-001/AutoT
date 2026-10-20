"""Provider boundary; bars are raw quote units, timestamps denote bar START."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from urllib.parse import quote

import requests

from autot.runtime import configure_certificates
from autot.utils.financial_validation import decimal_value
from autot.paper_trade.sessions import utc


class HistoryUnavailable(ValueError):
    """Safe message; no fabricated execution when coverage cannot be established."""


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self):
        object.__setattr__(self, "timestamp", utc(self.timestamp))
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, decimal_value(getattr(self, name), positive=True))
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Invalid OHLC bar.")


@dataclass(frozen=True)
class IntradayBatch:
    bars: list[Bar]
    quote_currency: str
    source: str


class IntradayProvider(Protocol):
    def get_intraday_bars(self, symbol, start, end, interval="5m") -> IntradayBatch: ...


class YahooIntradayProvider:
    """Independent public Yahoo chart adapter; no scanner workers/global yf state.

    Use a conservative 59-day request horizon, never assume it guarantees data.
    The engine separately checks every expected completed five-minute slot.
    """

    def get_intraday_bars(self, symbol, start, end, interval="5m"):
        start, end = utc(start), utc(end)
        if interval != "5m":
            raise ValueError("Paper execution requires 5m bars.")
        if start < datetime.now(timezone.utc) - timedelta(days=59):
            raise HistoryUnavailable("Required intraday history is outside the supported window; review required.")
        configure_certificates()
        try:
            response = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe=""),
                params={"period1": int(start.timestamp()), "period2": int(end.timestamp()),
                        "interval": interval, "includePrePost": "false", "events": "splits,div"},
                headers={"User-Agent": "Mozilla/5.0 AutoT paper research"}, timeout=(5, 30),
            )
            response.raise_for_status()
            chart = response.json()["chart"]
            if chart.get("error"):
                raise ValueError("Yahoo chart error")
            result = chart["result"][0]
            if result.get("events"):
                raise HistoryUnavailable("Corporate action in the monitoring window; review required.")
            currency = result["meta"]["currency"]
            stamps = result.get("timestamp", [])
            prices = result["indicators"]["quote"][0]
            bars = [Bar(datetime.fromtimestamp(t, timezone.utc),
                        *(prices[field][i] for field in ("open", "high", "low", "close")))
                    for i, t in enumerate(stamps)]
            return IntradayBatch(bars, currency, "Yahoo chart (unadjusted 5m)")
        except HistoryUnavailable:
            raise
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as error:
            raise HistoryUnavailable("Intraday data unavailable or invalid; retry or review required.") from error
