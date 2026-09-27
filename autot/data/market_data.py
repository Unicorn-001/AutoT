import yfinance as yf
import pandas as pd


YAHOO_SYMBOL_MAP = {
    "BF.B": "BF-B",
}


def _to_yahoo_symbol(symbol: str) -> str:
    """
    Convert an AutoT market symbol to the format expected by Yahoo Finance.
    """
    return YAHOO_SYMBOL_MAP.get(symbol, symbol)


def _has_usable_data(data: pd.DataFrame) -> bool:
    """
    Check whether downloaded market data contains enough rows
    to be useful for AutoT analysis.

    V1 requires at least 50 daily observations.
    """
    return data is not None and not data.empty and len(data) >= 50


def download_stock_data(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Download historical stock data for one stock.
    """

    yahoo_symbol = _to_yahoo_symbol(symbol)

    data = yf.download(
        tickers=yahoo_symbol,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if not _has_usable_data(data):
        raise ValueError(
            f"Insufficient market data found for symbol: {symbol}"
        )

    return data


def download_batch_stock_data(
    symbols: list[str],
    period: str = "1y",
    interval: str = "1d",
    batch_size: int = 50,
) -> dict[str, pd.DataFrame]:
    """
    Download historical market data for multiple stocks.

    Stocks are downloaded in controlled batches. Missing or
    insufficient datasets are retried individually.
    """

    if batch_size <= 0:
        raise ValueError("Batch size must be greater than zero.")

    stock_data = {}
    retry_symbols = []

    yahoo_to_autot = {
        _to_yahoo_symbol(symbol): symbol
        for symbol in symbols
    }

    yahoo_symbols = list(yahoo_to_autot.keys())

    for start in range(0, len(yahoo_symbols), batch_size):
        batch = yahoo_symbols[
            start:start + batch_size
        ]

        try:
            data = yf.download(
                tickers=batch,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=True,
            )

        except Exception as error:
            print(
                "Batch market-data download failed. "
                f"Retrying individually: {error}"
            )

            retry_symbols.extend(
                yahoo_to_autot[symbol]
                for symbol in batch
            )
            continue

        for yahoo_symbol in batch:
            autot_symbol = yahoo_to_autot[yahoo_symbol]

            try:
                symbol_data = data[yahoo_symbol].dropna()

            except (KeyError, TypeError):
                retry_symbols.append(autot_symbol)
                continue

            if not _has_usable_data(symbol_data):
                retry_symbols.append(autot_symbol)
                continue

            symbol_data.columns = pd.MultiIndex.from_product(
                [symbol_data.columns, [autot_symbol]]
            )

            stock_data[autot_symbol] = symbol_data

    # Retry failed or insufficient batch downloads individually.
    for symbol in dict.fromkeys(retry_symbols):
        yahoo_symbol = _to_yahoo_symbol(symbol)

        try:
            data = yf.download(
                tickers=yahoo_symbol,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )

        except Exception as error:
            print(
                f"Unable to download {symbol}: {error}"
            )
            continue

        if not _has_usable_data(data):
            print(
                f"Insufficient market data for {symbol}. "
                "Symbol skipped."
            )
            continue

        # Single-symbol yfinance downloads normally contain
        # MultiIndex columns. Convert them to the same format
        # expected by the rest of AutoT.
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = data.dropna()

        data.columns = pd.MultiIndex.from_product(
            [data.columns, [symbol]]
        )

        stock_data[symbol] = data

    if not stock_data:
        raise ValueError("No batch data downloaded.")

    return stock_data
