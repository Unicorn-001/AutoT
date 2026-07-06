from concurrent.futures import ThreadPoolExecutor, as_completed
import time

import pandas as pd

from autot.backtest.backtester import run_backtest
from autot.settings.configuration_manager import ConfigurationManager
from autot.market_data.market_data_manager import MarketDataManager
from autot.decision.trade_decision_builder import TradeDecisionBuilder
from autot.indicators.technical_indicators import add_all_indicators
from autot.ranking.ranking_engine import calculate_stock_score
from autot.strategies.manager.strategy_consensus import calculate_consensus_signal
from autot.strategies.manager.strategy_manager import StrategyManager
from autot.universe.universe_loader import load_universe
from autot.market_regime.market_regime_detector import MarketRegimeDetector
from autot.strategy_weights.strategy_weight_engine import StrategyWeightEngine
from autot.performance.performance_tracker import PerformanceTracker


def analyse_stock(
    symbol: str,
    data: pd.DataFrame,
    tracker: PerformanceTracker,
) -> dict:
    tracker.start(f"{symbol}_indicators")
    data = add_all_indicators(data)
    tracker.stop(f"{symbol}_indicators")

    tracker.start(f"{symbol}_strategies")
    strategy_manager = StrategyManager()
    strategy_results = strategy_manager.run_all(data)
    tracker.stop(f"{symbol}_strategies")

    regime = MarketRegimeDetector.detect(data)

    weighted_strategy_results = StrategyWeightEngine.apply_weights(
        strategy_results,
        regime["regime"],
    )

    consensus = calculate_consensus_signal(weighted_strategy_results)

    decision = TradeDecisionBuilder.build(
        symbol=symbol,
        data=data,
        consensus=consensus,
    )

    strategy_signal_map = {
        result["strategy"]: result["signal"]
        for result in weighted_strategy_results
    }

    tracker.start(f"{symbol}_backtest")
    backtest_result = run_backtest(data)
    tracker.stop(f"{symbol}_backtest")

    score = calculate_stock_score(
        return_percent=backtest_result["return_percent"],
        max_drawdown=backtest_result["max_drawdown"],
        win_rate=backtest_result["win_rate"],
        total_trades=backtest_result["total_trades"],
    )

    return {
        "symbol": symbol,
        "signal": decision.final_signal,
        "confidence": decision.confidence,
        "agreement": decision.agreement,
        "market_regime": decision.market_regime,
        "entry_price": decision.entry_price,
        "stop_loss": decision.stop_loss,
        "take_profit": decision.take_profit,
        "risk_reward_ratio": decision.risk_reward_ratio,
        "quantity": decision.position_size.quantity,
        "position_value": decision.position_size.position_value,
        "max_loss": decision.position_size.max_loss,
        "score": score,
        "profit_loss": backtest_result["profit_loss"],
        "return_percent": backtest_result["return_percent"],
        "max_drawdown": backtest_result["max_drawdown"],
        "win_rate": backtest_result["win_rate"],
        "total_trades": backtest_result["total_trades"],
        "buy_votes": consensus["buy_votes"],
        "sell_votes": consensus["sell_votes"],
        "hold_votes": consensus["hold_votes"],
        "buy_score": decision.buy_score,
        "sell_score": decision.sell_score,
        "hold_score": decision.hold_score,
        "decision_reason": decision.decision_reason,
        "ema_rsi_signal": strategy_signal_map.get("EMA_RSI_Strategy", "N/A"),
        "macd_signal": strategy_signal_map.get("MACD_Strategy", "N/A"),
        "bollinger_signal": strategy_signal_map.get("Bollinger_Strategy", "N/A"),
        "breakout_signal": strategy_signal_map.get("Breakout_Strategy", "N/A"),
        "supertrend_signal": strategy_signal_map.get("SuperTrend_Strategy", "N/A"),
    }


def save_results_to_csv(results: list[dict], file_path: str) -> None:
    df = pd.DataFrame(results)

    column_order = [
        "rank",
        "symbol",
        "signal",
        "confidence",
        "agreement",
        "market_regime",
        "entry_price",
        "stop_loss",
        "take_profit",
        "risk_reward_ratio",
        "quantity",
        "position_value",
        "max_loss",
        "score",
        "profit_loss",
        "return_percent",
        "max_drawdown",
        "win_rate",
        "total_trades",
        "buy_votes",
        "sell_votes",
        "hold_votes",
        "buy_score",
        "sell_score",
        "hold_score",
        "decision_reason",
        "ema_rsi_signal",
        "macd_signal",
        "bollinger_signal",
        "breakout_signal",
        "supertrend_signal",
    ]

    existing_columns = [
        column for column in column_order
        if column in df.columns
    ]

    df = df[existing_columns]

    numeric_columns = [
        "confidence",
        "agreement",
        "entry_price",
        "stop_loss",
        "take_profit",
        "risk_reward_ratio",
        "position_value",
        "max_loss",
        "score",
        "profit_loss",
        "return_percent",
        "max_drawdown",
        "win_rate",
        "buy_score",
        "sell_score",
        "hold_score",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = df[column].round(2)

    df.to_csv(file_path, index=False)

    print(f"\nSaved: {file_path}")


def main() -> None:
    start_time = time.time()

    tracker = PerformanceTracker()
    config = ConfigurationManager()

    symbols = load_universe(
        config.get_string("ACTIVE_UNIVERSE")
    )

    tracker.start("Batch Download")
    batch_data = MarketDataManager.get_batch_stock_data(
        symbols=symbols,
        period=config.get_string("BACKTEST_PERIOD"),
        interval=config.get_string("BACKTEST_INTERVAL"),
    )
    tracker.stop("Batch Download")

    results = []
    max_workers = 8

    tracker.start("Analyse Stocks")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {
            executor.submit(
                analyse_stock,
                symbol,
                batch_data[symbol],
                tracker,
            ): symbol
            for symbol in symbols
            if symbol in batch_data
        }

        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]

            try:
                result = future.result()
                results.append(result)
            except Exception as error:
                print(f"Error analysing {symbol}: {error}")

    tracker.stop("Analyse Stocks")

    ranked_results = sorted(
        results,
        key=lambda item: item["score"],
        reverse=True,
    )

    for index, result in enumerate(ranked_results, start=1):
        result["rank"] = index

    top_n = config.get_int("TOP_N_STOCKS")
    top_results = ranked_results[:top_n]

    trade_opportunities = [
        result for result in ranked_results
        if result["signal"] in ["BUY", "SELL"]
    ]

    print("\n========== TODAY'S SWING TRADE OPPORTUNITIES ==========")

    if not trade_opportunities:
        print("No actionable BUY or SELL opportunities today.")
    else:
        print(
            "Rank | Symbol | Signal | Confidence | Agreement | "
            "Regime | Entry | Stop Loss | Take Profit | Score"
        )
        print("-" * 120)

        for index, result in enumerate(trade_opportunities, start=1):
            print(
                f"{index} | "
                f"{result['symbol']} | "
                f"{result['signal']} | "
                f"{result['confidence']:.2f}% | "
                f"{result['agreement']:.2f}% | "
                f"{result['market_regime']} | "
                f"{result['entry_price']:.2f} | "
                f"{result['stop_loss']:.2f} | "
                f"{result['take_profit']:.2f} | "
                f"{result['score']:.2f}"
            )

    print("=======================================================")

    print(f"\n========== TOP {top_n} SHORTLIST ==========")

    for index, result in enumerate(top_results, start=1):
        print(
            f"{index}. {result['symbol']} | "
            f"Score: {result['score']:.2f} | "
            f"Signal: {result['signal']}"
        )

    print("======================================")

    tracker.start("Save Reports")

    save_results_to_csv(
        ranked_results,
        "data_storage/processed/backtest_results.csv",
    )

    save_results_to_csv(
        top_results,
        "data_storage/processed/top_shortlist.csv",
    )

    tracker.stop("Save Reports")

    end_time = time.time()
    total_time = end_time - start_time

    tracker.print_report()

    print(f"\nExecution time: {total_time:.2f} seconds")


if __name__ == "__main__":
    main()