from logging import config

import pandas as pd
import time

from autot.backtest.backtester import run_backtest
from autot.settings.configuration_manager import ConfigurationManager
from autot.data.market_data import download_stock_data
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
    backtest_period: str,
    backtest_interval: str,
    tracker: PerformanceTracker,
) -> dict:
    tracker.start(f"{symbol}_download")
    data = download_stock_data(
        symbol,
        period=backtest_period,
        interval=backtest_interval,    
    )

    tracker.stop(f"{symbol}_download")

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
    strategy_results = weighted_strategy_results

    decision = TradeDecisionBuilder.build(
        symbol=symbol,
        data=data,
        consensus=consensus,
    )

    strategy_signal_map = {
        result["strategy"]: result["signal"]
        for result in strategy_results
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

    print("--------------------------------")
    print(f"Stock       : {symbol}")
    print(f"Signal      : {decision.final_signal}")
    print(f"Confidence  : {decision.confidence:.2f}%")
    print(f"Buy Votes   : {consensus['buy_votes']}")
    print(f"Sell Votes  : {consensus['sell_votes']}")
    print(f"Hold Votes  : {consensus['hold_votes']}")
    print(f"Buy Score   : {decision.buy_score}")
    print(f"Sell Score  : {decision.sell_score}")
    print(f"Hold Score  : {decision.hold_score}")
    print(f"Entry Price : £{decision.entry_price:.2f}")
    print(f"Stop Loss   : £{decision.stop_loss:.2f}")
    print(f"Take Profit : £{decision.take_profit:.2f}")
    print(f"Risk/Reward : {decision.risk_reward_ratio:.2f}")
    print(f"Quantity    : {decision.position_size.quantity}")
    print(f"Position Val: £{decision.position_size.position_value:.2f}")
    print(f"Max Loss    : £{decision.position_size.max_loss:.2f}")
    print(f"Decision    : {decision.decision_reason}")
    print(f"Agreement   : {decision.agreement:.2f}%")
    print(f"Market Regime: {decision.market_regime}")

    print("Strategies  :")
    for strategy_result in strategy_results:
        print(
            f"  {strategy_result['strategy']} -> "
            f"{strategy_result['signal']} "
            f"(Confidence: {strategy_result['confidence']:.2f})"
        )
        print(f"    Reason: {strategy_result['reason']}")

    print(f"Score       : {score:.2f}")
    print(f"P/L         : £{backtest_result['profit_loss']:.2f}")
    print(f"Return      : {backtest_result['return_percent']:.2f}%")
    print(f"Max Drawdown: {backtest_result['max_drawdown']:.2f}%")
    print(f"Trades      : {backtest_result['total_trades']}")
    print("--------------------------------")

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
        "entry_price": decision.entry_price,
        "decision_reason": decision.decision_reason,
        "ema_rsi_signal": strategy_signal_map.get("EMA_RSI_Strategy", "N/A"),
        "macd_signal": strategy_signal_map.get("MACD_Strategy", "N/A"),
        "bollinger_signal": strategy_signal_map.get("Bollinger_Strategy", "N/A"),
        "breakout_signal": strategy_signal_map.get("Breakout_Strategy", "N/A"),
        "supertrend_signal": strategy_signal_map.get("SuperTrend_Strategy", "N/A"),
        "stop_loss": decision.stop_loss,
        "take_profit": decision.take_profit,
        "risk_reward_ratio": decision.risk_reward_ratio,
        "quantity": decision.position_size.quantity,
        "position_value": decision.position_size.position_value,
        "max_loss": decision.position_size.max_loss,
    }


def save_results_to_csv(results: list[dict], file_path: str) -> None:
    df = pd.DataFrame(results)

    numeric_columns = [
        "score",
        "profit_loss",
        "return_percent",
        "max_drawdown",
        "win_rate",
        "buy_score",
        "sell_score",
        "hold_score",
        "entry_price",
        "stop_loss",
        "take_profit",
        "risk_reward_ratio",
        "position_value",
        "max_loss",
    ]

    df[numeric_columns] = df[numeric_columns].round(2)
    df.to_csv(file_path, index=False)

    print(f"\nSaved: {file_path}")


def main() -> None:
    start_time = time.time()
    tracker = PerformanceTracker()
    config = ConfigurationManager()
    symbols = load_universe(
        config.get_string("ACTIVE_UNIVERSE")
    )
    results = []
    tracker.start("Analyse Stocks")
    for symbol in symbols:
        try:
            result = analyse_stock(
                symbol=symbol,
                backtest_period=config.get_string("BACKTEST_PERIOD"),
                backtest_interval=config.get_string("BACKTEST_INTERVAL"),
                tracker=tracker,
            )
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

    print("\n========== TODAY'S TRADE OPPORTUNITIES ==========")

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

    print("=================================================")

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