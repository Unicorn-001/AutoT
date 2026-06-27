import pandas as pd
from ta.momentum import RSIIndicator


def get_close_series(data: pd.DataFrame) -> pd.Series:
    close = data["Close"]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    return close


def add_ema(
    data: pd.DataFrame,
    short_window: int = 20,
    long_window: int = 50,
) -> pd.DataFrame:
    data = data.copy()
    close = get_close_series(data)

    data["EMA_20"] = close.ewm(span=short_window, adjust=False).mean()
    data["EMA_50"] = close.ewm(span=long_window, adjust=False).mean()

    return data


def add_rsi(data: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    data = data.copy()
    close = get_close_series(data)

    rsi_indicator = RSIIndicator(close=close, window=window)
    data["RSI"] = rsi_indicator.rsi()

    return data


def add_macd(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    close = get_close_series(data)

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()

    data["MACD"] = ema_12 - ema_26
    data["MACD_SIGNAL"] = data["MACD"].ewm(
        span=9,
        adjust=False,
    ).mean()

    return data


def add_all_indicators(data: pd.DataFrame) -> pd.DataFrame:
    data = add_ema(data)
    data = add_rsi(data)
    data = add_macd(data)

    return data