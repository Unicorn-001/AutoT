"""Advisory quote snapshots using the existing owned Yahoo download pool."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math

import pandas as pd

from autot.market_data.symbols import normalize_market_data_symbol
from autot.market_data.yfinance_download import YahooDownloadPool

STALE_QUOTE_SECONDS = 300


class QuoteError(ValueError):
    """A non-fatal quote retrieval/validation failure."""


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    quote_timestamp: datetime | None = None
    source: str = 'Yahoo (1-minute close)'
    session_label: str | None = None

    def __post_init__(self):
        if (not self.symbol or isinstance(self.price, bool)
                or not isinstance(self.price, (int, float))
                or not math.isfinite(self.price) or self.price <= 0):
            raise QuoteError('Invalid quote: expected a positive, finite price.')
        if self.quote_timestamp is not None and (
                not isinstance(self.quote_timestamp, datetime)
                or self.quote_timestamp.utcoffset() is None):
            raise QuoteError('Invalid quote timestamp: timezone is required.')

    def audit(self, assessed_price, *, now=None):
        now = now or datetime.now(timezone.utc)
        age = None if self.quote_timestamp is None else (now - self.quote_timestamp).total_seconds()
        # Future timestamps cannot establish freshness.
        age = age if age is not None and age >= 0 else None
        try:
            override = float(assessed_price) != self.price
        except (TypeError, ValueError, OverflowError):
            override = True
        return dict(fetched_price=self.price, price_source=self.source,
                    quote_timestamp=self.quote_timestamp.isoformat() if self.quote_timestamp else None,
                    quote_age_seconds=age,
                    stale=bool(self.session_label == 'REGULAR' and age is not None and age > STALE_QUOTE_SECONDS),
                    session_label=self.session_label, manual_override=override)


def fetch_latest_quote(symbol):
    """Latest available regular-session bar; no calendar/session inference.

    Empty Yahoo results cannot reliably distinguish unknown symbols from unavailable
    data. Do not fall back to scanner prices or silently reuse an earlier quote.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise QuoteError('Symbol not found: select an opportunity with a valid symbol.')
    try:
        yahoo_symbol = normalize_market_data_symbol(symbol)
        with YahooDownloadPool() as pool:
            result = pool.download([yahoo_symbol], '5d', '1m')[yahoo_symbol]
        if result.error is not None:
            raise QuoteError('Yahoo provider unavailable or request timed out. Try again or enter a price manually.') from result.error
        data = result.data
        if data is None or data.empty:
            raise QuoteError('Symbol not found or Yahoo price unavailable; no quote returned.')
        data = data.copy()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        if 'Close' not in data:
            raise QuoteError('Missing price: Yahoo returned no closing price.')
        # A missing last value must not silently select an older valid price.
        data = data.sort_index()
        price = float(data['Close'].iloc[-1])
        stamp = data.index[-1]
        timestamp = stamp.to_pydatetime() if isinstance(stamp, pd.Timestamp) and not pd.isna(stamp) and stamp.tzinfo else None
        return Quote(symbol=symbol, price=price, quote_timestamp=timestamp)
    except QuoteError:
        raise
    except Exception as error:
        raise QuoteError('Yahoo provider error or invalid quote. Try again or enter a price manually.') from error
