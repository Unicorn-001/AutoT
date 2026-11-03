import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange
from ta.momentum import StochasticOscillator
from ta.momentum import RSIIndicator
from ta.momentum import RSIIndicator, StochasticOscillator


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


def add_macd(data: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    data = data.copy()
    close = get_close_series(data)

    ema_12 = close.ewm(span=fast, adjust=False).mean()
    ema_26 = close.ewm(span=slow, adjust=False).mean()

    data["MACD"] = ema_12 - ema_26
    data["MACD_SIGNAL"] = data["MACD"].ewm(
        span=signal,
        adjust=False,
    ).mean()

    return data


def add_bollinger_bands(
    data: pd.DataFrame,
    window: int = 20,
    num_std: int = 2,
) -> pd.DataFrame:
    data = data.copy()
    close = get_close_series(data)

    middle_band = close.rolling(window=window).mean()
    std_dev = close.rolling(window=window).std()

    data["BB_MIDDLE"] = middle_band
    data["BB_UPPER"] = middle_band + (std_dev * num_std)
    data["BB_LOWER"] = middle_band - (std_dev * num_std)

    return data


def add_supertrend(
    data: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
) -> pd.DataFrame:
    data = data.copy()

    high = data["High"]
    low = data["Low"]
    close = data["Close"]

    if isinstance(high, pd.DataFrame):
        high = high.iloc[:, 0]

    if isinstance(low, pd.DataFrame):
        low = low.iloc[:, 0]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.rolling(window=period).mean()

    hl2 = (high + low) / 2
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    data["SUPERTREND_UPPER"] = upper_band
    data["SUPERTREND_LOWER"] = lower_band
    data["SUPERTREND_DIRECTION"] = close > lower_band

    return data


def add_adx(data: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    data = data.copy()

    high = data["High"]
    low = data["Low"]
    close = data["Close"]

    if isinstance(high, pd.DataFrame):
        high = high.iloc[:, 0]

    if isinstance(low, pd.DataFrame):
        low = low.iloc[:, 0]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    adx_indicator = ADXIndicator(
        high=high,
        low=low,
        close=close,
        window=window,
    )

    data["ADX"] = adx_indicator.adx()
    data["DI_PLUS"] = adx_indicator.adx_pos()
    data["DI_MINUS"] = adx_indicator.adx_neg()

    return data

def add_volume_indicators(
    data: pd.DataFrame,
    window: int = 20,
) -> pd.DataFrame:
    data = data.copy()

    volume = data["Volume"]

    if isinstance(volume, pd.DataFrame):
        volume = volume.iloc[:, 0]

    data["VOLUME_AVG"] = volume.rolling(window=window).mean()
    data["VOLUME_RATIO"] = volume / data["VOLUME_AVG"]

    return data

def add_momentum(
    data: pd.DataFrame,
    period: int = 10,
) -> pd.DataFrame:
    data = data.copy()

    close = get_close_series(data)

    data["MOMENTUM"] = close - close.shift(period)

    return data

def add_atr(
    data: pd.DataFrame,
    window: int = 14,
) -> pd.DataFrame:

    data = data.copy()

    high = data["High"]
    low = data["Low"]
    close = data["Close"]

    if isinstance(high, pd.DataFrame):
        high = high.iloc[:, 0]

    if isinstance(low, pd.DataFrame):
        low = low.iloc[:, 0]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    atr = AverageTrueRange(
        high=high,
        low=low,
        close=close,
        window=window,
    )

    data["ATR"] = atr.average_true_range()

    return data
    
def add_stochastic(
    data: pd.DataFrame,
    window: int = 14,
    smooth_window: int = 3,
) -> pd.DataFrame:
    data = data.copy()

    high = data["High"]
    low = data["Low"]
    close = data["Close"]

    if isinstance(high, pd.DataFrame):
        high = high.iloc[:, 0]

    if isinstance(low, pd.DataFrame):
        low = low.iloc[:, 0]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    stochastic = StochasticOscillator(
        high=high,
        low=low,
        close=close,
        window=window,
        smooth_window=smooth_window,
    )

    data["STOCH_K"] = stochastic.stoch()
    data["STOCH_D"] = stochastic.stoch_signal()

    return data

def add_all_indicators(data: pd.DataFrame, settings=None) -> pd.DataFrame:
    from autot.settings.models import Strategies
    s = settings or Strategies()
    data = add_ema(data, s.EMA_RSI.fast, s.EMA_RSI.slow)
    data = add_rsi(data, s.EMA_RSI.rsi_period)
    data = add_macd(data, s.MACD.fast, s.MACD.slow, s.MACD.signal)
    data = add_bollinger_bands(data, s.BOLLINGER.period, s.BOLLINGER.deviation)
    data = add_supertrend(data, s.SUPERTREND.atr_period, s.SUPERTREND.multiplier)
    data = add_adx(data, s.ADX.period)
    data = add_volume_indicators(data, s.VOLUME_SPIKE.period)
    data = add_momentum(data, s.MOMENTUM.period)
    data = add_atr(data, s.ATR.period)
    data = add_stochastic(data, s.STOCHASTIC.period, s.STOCHASTIC.smooth_period)
    return data
