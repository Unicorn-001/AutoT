from autot.config.watchlist import load_watchlist
from autot.data.market_data import download_stock_data
from autot.indicators.technical_indicators import add_all_indicators
from autot.strategies.ema_rsi_strategy import generate_signal
from autot.backtest.backtester import run_backtest


def analyse_stock(symbol: str) -> dict:
    data = download_stock_data(symbol, period="6mo", interval="1d")
    data = add_all_indicators(data)

    signal = generate_signal(data)
    backtest_result = run_backtest(data)

    print("--------------------------------")
    print(f"Stock : {symbol}")
    print(f"Signal: {signal}")
    print(f"P/L   : £{backtest_result['profit_loss']:.2f}")
    print(f"Trades: {backtest_result['total_trades']}")
    print("--------------------------------")

    return {
        "symbol": symbol,
        "signal": signal,
        "profit_loss": backtest_result["profit_loss"],
        "win_rate": backtest_result["win_rate"],
        "total_trades": backtest_result["total_trades"],
    }


def main():
    symbols = load_watchlist()
    results = []

    for symbol in symbols:
        try:
            result = analyse_stock(symbol)
            results.append(result)

        except Exception as error:
            print(f"Error analysing {symbol}: {error}")

    ranked_results = sorted(
        results,
        key=lambda item: item["profit_loss"],
        reverse=True,
    )

    print("\n========== BACKTEST RANKING ==========")

    for index, result in enumerate(ranked_results, start=1):
        print(
            f"{index}. {result['symbol']} | "
            f"P/L: £{result['profit_loss']:.2f} | "
            f"Win Rate: {result['win_rate']:.2f}% | "
            f"Trades: {result['total_trades']} | "
            f"Signal: {result['signal']}"
        )

    print("======================================")


if __name__ == "__main__":
    main()