import pandas as pd


def get_value(row, column_name: str) -> float:
    value = row[column_name]

    if isinstance(value, pd.Series):
        value = value.iloc[0]

    return float(value)


def generate_signal(data: pd.DataFrame) -> str:
    latest = data.iloc[-1]

    ema20 = get_value(latest, "EMA_20")
    ema50 = get_value(latest, "EMA_50")
    rsi = get_value(latest, "RSI")

    if ema20 > ema50 and rsi < 35:
        return "BUY"

    elif ema20 < ema50 and rsi > 70:
        return "SELL"

    else:
        return "HOLD"