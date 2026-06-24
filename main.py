import pandas as pd
import time

from autot.backtest.backtester import run_backtest
from autot.config.settings import (
    ACTIVE_UNIVERSE_FILE,
    BACKTEST_INTERVAL,
    BACKTEST_PERIOD,
    TOP_N_STOCKS,
)
from autot.data.market_data import download_stock_data
from autot.indicators.technical_indicators import add_all_indicators
from autot.ranking.ranking_engine import calculate_stock_score
from autot.strategies.ema_rsi_strategy import generate_signal
from autot.universe.universe_loader import load_universe


def analyse_stock(symbol: str) -> dict:
    data = download_stock_data(
        symbol,
        period=BACKTEST_PERIOD,
        interval=BACKTEST_INTERVAL,
    )

    data = add_all_indicators(data)

    signal = generate_signal(data)
    backtest_result = run_backtest(data)

    score = calculate_stock_score(
        return_percent=backtest_result["return_percent"],
        max_drawdown=backtest_result["max_drawdown"],
        win_rate=backtest_result["win_rate"],
        total_trades=backtest_result["total_trades"],
    )

    print("--------------------------------")
    print(f"Stock       : {symbol}")
    print(f"Signal      : {signal}")
    print(f"Score       : {score:.2f}")
    print(f"P/L         : £{backtest_result['profit_loss']:.2f}")
    print(f"Return      : {backtest_result['return_percent']:.2f}%")
    print(f"Max Drawdown: {backtest_result['max_drawdown']:.2f}%")
    print(f"Trades      : {backtest_result['total_trades']}")
    print("--------------------------------")

    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "profit_loss": backtest_result["profit_loss"],
        "return_percent": backtest_result["return_percent"],
        "max_drawdown": backtest_result["max_drawdown"],
        "win_rate": backtest_result["win_rate"],
        "total_trades": backtest_result["total_trades"],
    }


def save_results_to_csv(
    results: list[dict],
    file_path: str,
) -> None:
    df = pd.DataFrame(results)

    numeric_columns = [
        "score",
        "profit_loss",
        "return_percent",
        "max_drawdown",
        "win_rate",
    ]

    df[numeric_columns] = df[numeric_columns].round(2)
    df.to_csv(file_path, index=False)

    print(f"\nSaved: {file_path}")


def main() -> None:
    start_time = time.time()
    symbols = load_universe(ACTIVE_UNIVERSE_FILE)
    results = []

    for symbol in symbols:
        try:
            result = analyse_stock(symbol)
            results.append(result)
        except Exception as error:
            print(f"Error analysing {symbol}: {error}")

    ranked_results = sorted(
        results,
        key=lambda item: item["score"],
        reverse=True,
    )

    top_results = ranked_results[:TOP_N_STOCKS]

    print("\n========== BACKTEST RANKING ==========")

    for index, result in enumerate(ranked_results, start=1):
        print(
            f"{index}. {result['symbol']} | "
            f"Score: {result['score']:.2f} | "
            f"P/L: £{result['profit_loss']:.2f} | "
            f"Return: {result['return_percent']:.2f}% | "
            f"Max DD: {result['max_drawdown']:.2f}% | "
            f"Win Rate: {result['win_rate']:.2f}% | "
            f"Trades: {result['total_trades']} | "
            f"Signal: {result['signal']}"
        )

    print("======================================")

    print(f"\n========== TOP {TOP_N_STOCKS} SHORTLIST ==========")

    for index, result in enumerate(top_results, start=1):
        print(
            f"{index}. {result['symbol']} | "
            f"Score: {result['score']:.2f} | "
            f"Signal: {result['signal']}"
        )

    print("======================================")

    save_results_to_csv(
        ranked_results,
        "data_storage/processed/backtest_results.csv",
    )

    save_results_to_csv(
        top_results,
        "data_storage/processed/top_shortlist.csv",
    )
    end_time = time.time()
    total_time = end_time - start_time

    print(f"\nExecution time: {total_time:.2f} seconds")

if __name__ == "__main__":
    main()