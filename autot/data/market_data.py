import yfinance as yf
import pandas as pd


def download_stock_data(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """
    Download historical stock data from Yahoo Finance.

    Example symbols:
    AAPL   = Apple
    MSFT   = Microsoft
    RR.L   = Rolls-Royce UK
    SHEL.L = Shell UK
    """

    data = yf.download(
        tickers=symbol,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False
    )

    if data.empty:
        raise ValueError(f"No data found for symbol: {symbol}")

    return data