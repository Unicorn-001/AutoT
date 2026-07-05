import yfinance as yf
import pandas as pd


def download_stock_data(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Download historical stock data for one stock.
    """

    data = yf.download(
        tickers=symbol,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
    )

    if data.empty:
        raise ValueError(f"No data found for symbol: {symbol}")

    return data


def download_batch_stock_data(
    symbols: list[str],
    period: str = "1y",
    interval: str = "1d",
) -> dict[str, pd.DataFrame]:
    """
    Download historical stock data for multiple stocks in one Yahoo Finance call.
    """

    data = yf.download(
        tickers=symbols,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )

    if data.empty:
        raise ValueError("No batch data downloaded.")

    stock_data = {}

    for symbol in symbols:
        try:
            symbol_data = data[symbol].dropna()

            if not symbol_data.empty:
                stock_data[symbol] = symbol_data

        except KeyError:
            print(f"No data found for symbol: {symbol}")

    return stock_data