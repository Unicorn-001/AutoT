"""Exact symbol resolution and Decimal execution quotes; daily data stays Yahoo."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import re
import time

from autot.market_data.quote import Quote
from autot.utils.financial_validation import decimal_value as D
from .client import BrokerError


@dataclass(frozen=True)
class ExecutionQuote:
    symbol: str
    instrument_id: int
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal | None
    quote_timestamp: datetime | None
    side: str = 'BUY'
    source: str = 'eToro'
    session_label: str | None = None

    @property
    def price(self):
        price = self.ask if self.side == 'BUY' else self.bid
        if price is None:
            raise BrokerError('Executable side is unavailable; no substitute price was invented.')
        return price

    @property
    def spread_absolute(self):
        return self.ask - self.bid if self.ask is not None and self.bid is not None else None

    @property
    def spread_percent(self):
        return self.spread_absolute / ((self.ask + self.bid) / 2) * 100 if self.spread_absolute is not None else None

    def audit(self, assessed_price, *, now=None):
        result = Quote(self.symbol, float(self.price), self.quote_timestamp, self.source).audit(assessed_price, now=now)
        result.update(instrument_id=self.instrument_id, bid=str(self.bid) if self.bid else None,
                      ask=str(self.ask) if self.ask else None,
                      spread_absolute=str(self.spread_absolute) if self.spread_absolute is not None else None,
                      spread_percent=str(self.spread_percent) if self.spread_percent is not None else None)
        return result


class Resolver:
    def __init__(self, client, *, ttl=3600):
        self.client, self.ttl, self.cache = client, ttl, {}

    def resolve(self, symbol):
        symbol = symbol.strip().upper()
        if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', symbol):
            raise BrokerError('Invalid symbol.')
        cached = self.cache.get(symbol)
        if cached and time.monotonic() - cached[0] < self.ttl:
            return dict(cached[1])
        results = self.client.request('GET', '/api/v2/market-data/instruments/search',
                                      params={'query': symbol, 'limit': 50}).get('results', [])
        exact = [r for r in results if r.get('symbol', '').upper() == symbol]
        if len(exact) != 1:
            raise BrokerError('Instrument missing or ambiguous; exact symbol required.')
        item = {k: exact[0].get(k) for k in ('symbol', 'instrumentId', 'type', 'exchangeId')}
        if type(item['instrumentId']) is not int or item['instrumentId'] <= 0:
            raise BrokerError('Invalid instrument ID.')
        self.cache[symbol] = (time.monotonic(), item)
        return dict(item)

    def require_us_stock(self, instrument):
        exchanges = self.client.request('GET', '/api/v1/market-data/exchanges').get('exchangeInfo', [])
        names = {e['exchangeID']: e['exchangeDescription'].strip().upper() for e in exchanges}
        if instrument['type'] != 'Stocks' or names.get(instrument['exchangeId']) not in {
                'NASDAQ', 'NYSE', 'NEW YORK STOCK EXCHANGE', 'NYSE ARCA', 'NYSE AMERICAN'}:
            raise BrokerError('V1 requires a verified US stock exchange and Stocks instrument type.')


class EtoroQuoteProvider:
    def __init__(self, client, resolver=None):
        self.client, self.resolver = client, resolver or Resolver(client)

    def quote(self, symbol, side='BUY'):
        if side not in ('BUY', 'SELL'):
            raise BrokerError('Invalid quote side.')
        instrument = self.resolver.resolve(symbol)
        rates = self.client.request('GET', '/api/v1/market-data/instruments/rates',
            params={'instrumentIds': instrument['instrumentId']}).get('rates', [])
        rows = [r for r in rates if r.get('instrumentID') == instrument['instrumentId']]
        if len(rows) != 1:
            raise BrokerError('No unique rate for the resolved instrument.')
        row = rows[0]
        try:
            bid, ask, last = [D(row[k], positive=True) if row.get(k) is not None else None
                              for k in ('bid', 'ask', 'lastExecution')]
            if bid is not None and ask is not None and bid > ask:
                raise ValueError()
            stamp = datetime.fromisoformat(row['date'].replace('Z', '+00:00')) if row.get('date') else None
            if stamp and stamp.utcoffset() is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise BrokerError('Invalid eToro rate data.') from None
        return ExecutionQuote(instrument['symbol'], instrument['instrumentId'], bid, ask, last, stamp, side)
