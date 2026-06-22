import pandas as pd


def run_backtest(data: pd.DataFrame):
    print("\nBacktest started...")
    print(f"Number of candles: {len(data)}")