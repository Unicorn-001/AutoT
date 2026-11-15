import logging
import math

import pandas as pd

from autot.market_data.symbols import normalize_market_data_symbol
from autot.market_data.yfinance_download import (
    MarketDataInfrastructureError, YahooDownloadPool, is_infrastructure_failure,
)


LOGGER = logging.getLogger(__name__)


def _to_yahoo_symbol(symbol: str) -> str:
    return normalize_market_data_symbol(symbol)


def _has_usable_data(data: pd.DataFrame) -> bool:
    return data is not None and not data.empty and len(data) >= 50


def _clean_data(data):
    if data is None:
        return None
    data = data.dropna().copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return data


def _check_infrastructure(results, stock_data):
    for symbol, result in results.items():
        if result.error is not None and is_infrastructure_failure(result.error):
            raise MarketDataInfrastructureError(
                f"Market-data infrastructure failure at {symbol}; downloads stopped "
                f"without individual retry fan-out: {result.error}",
                partial_data=stock_data.copy(),
            ) from result.error


def download_stock_data(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    yahoo_symbol = _to_yahoo_symbol(symbol)
    with YahooDownloadPool() as pool:
        results = pool.download([yahoo_symbol], period, interval)
        _check_infrastructure(results, {})
        result = results[yahoo_symbol]
        if result.error is not None:
            raise result.error
        data = result.data
        if not _has_usable_data(_clean_data(data)):
            raise ValueError(f"Insufficient market data found for symbol: {symbol}")
        return data


def download_batch_stock_data(
    symbols: list[str], period: str = "1y", interval: str = "1d", batch_size: int = 50, on_progress=None,
) -> dict[str, pd.DataFrame]:
    """Download with owned worker cleanup and bounded infrastructure-aware retries."""
    if batch_size <= 0:
        raise ValueError("Batch size must be greater than zero.")
    yahoo_to_autot = {_to_yahoo_symbol(symbol): symbol for symbol in symbols}
    yahoo_symbols = list(yahoo_to_autot)
    stock_data = {}
    retry_symbols = []
    failed = 0
    def progress():
        if on_progress:
            on_progress(dict(symbols_fetched=len(stock_data) + failed, symbols_failed=failed))

    def accept(symbol, result):
        if result.error is not None:
            return False
        data = _clean_data(result.data)
        if not _has_usable_data(data):
            return False
        autot_symbol = yahoo_to_autot[symbol]
        data.columns = pd.MultiIndex.from_product([data.columns, [autot_symbol]])
        stock_data[autot_symbol] = data
        return True

    with YahooDownloadPool() as pool:
        for start in range(0, len(yahoo_symbols), batch_size):
            batch = yahoo_symbols[start:start + batch_size]
            results = pool.download(batch, period, interval)
            missing = [symbol for symbol in batch if not accept(symbol, results[symbol])]
            _check_infrastructure(results, stock_data)
            # Broad missing data may mask transport failure. Do not infer that
            # stocks are delisted, or multiply ambiguous failures into singles.
            if len(missing) >= max(4, math.ceil(len(batch) / 2)):
                raise MarketDataInfrastructureError(
                    f"Yahoo batch unavailable: {len(missing)}/{len(batch)} datasets "
                    "missing or insufficient; cause unverified. Downloads stopped "
                    "without individual retry fan-out.",
                    partial_data=stock_data.copy(),
                )
            retry_symbols.extend(missing)
            progress()

        for symbol in dict.fromkeys(retry_symbols):
            results = pool.download([symbol], period, interval)
            _check_infrastructure(results, stock_data)
            if not accept(symbol, results[symbol]):
                failed += 1
                LOGGER.warning(
                    "Insufficient/unverified market data for %s after one retry: %s",
                    yahoo_to_autot[symbol], results[symbol].error or "fewer than 50 usable rows",
                )

            progress()

    if not stock_data:
        raise ValueError("No batch data downloaded.")
    return stock_data
