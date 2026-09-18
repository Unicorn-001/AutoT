from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from packaging import metadata
import pandas as pd

from autot import support_resistance, volume_strength
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
from autot.trade_quality.trade_quality_engine import TradeQualityEngine
from autot.trend_strength.trend_strength_engine import TrendStrengthEngine
from autot.volume_strength.volume_strength_engine import VolumeStrengthEngine
from autot.relative_strength.relative_strength_engine import RelativeStrengthEngine
from autot.broker.paper_broker import PaperBroker
from autot.config.trading_settings import ACCOUNT_SIZE
from autot.portfolio.portfolio_storage import (
    load_or_create_portfolio,
)
from autot.trading.paper_trader import PaperTrader
from autot.support_resistance.support_resistance_engine import (
    SupportResistanceEngine,
)
from autot.opportunity_ranking.opportunity_ranking_engine import (
    OpportunityRankingEngine,
)
from datetime import datetime
import os


def print_stage(message: str) -> None:
    print(f"\n▶ {message}")

def analyse_stock(
    symbol: str,
    data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    tracker: PerformanceTracker,
    ) -> tuple[dict, object]:
    tracker.start(f"{symbol}_indicators")
    data = add_all_indicators(data)
    trend_strength = TrendStrengthEngine.calculate(data)
    relative_strength = RelativeStrengthEngine.calculate(
        stock_data=data,
        benchmark_data=benchmark_data,
    )
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
    volume_strength = VolumeStrengthEngine.calculate(data)

    support_resistance = SupportResistanceEngine.calculate(
        data=data,
        signal=decision.final_signal,
    )
    breakout_confirmation_score = support_resistance["support_resistance_score"]

    if support_resistance["support_resistance_label"] in [
        "BREAKOUT_ZONE",
        "BREAKDOWN_ZONE",
    ]:
        if volume_strength["volume_strength_label"] in [
            "STRONG_VOLUME",
            "VERY_STRONG_VOLUME",
        ]:
            breakout_confirmation_score = min(
                breakout_confirmation_score + 20,
                100,
            )

        elif volume_strength["volume_strength_label"] in [
            "LOW_VOLUME",
            "VERY_LOW_VOLUME",
        ]:
            breakout_confirmation_score = max(
                breakout_confirmation_score - 20,
                0,
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

    trade_quality = TradeQualityEngine.calculate(
        signal=decision.final_signal,
        confidence=decision.confidence,
        agreement=decision.agreement,
        score=score,
        market_regime=decision.market_regime,
        risk_reward_ratio=decision.risk_reward_ratio,
)

    opportunity_score = OpportunityRankingEngine.calculate(
        trade_quality_score=trade_quality["trade_quality_score"],
        historical_score=score,
        trend_strength_score=trend_strength["trend_strength_score"],
        volume_strength_score=volume_strength["volume_strength_score"],
        breakout_confirmation_score=breakout_confirmation_score,
        relative_strength_score=relative_strength["relative_strength_score"],
        confidence=decision.confidence,
        risk_reward_ratio=decision.risk_reward_ratio,
       
    )


    result = {
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
        "trade_quality_score": trade_quality["trade_quality_score"],
        "trade_quality_label": trade_quality["trade_quality_label"],
        "volume_ratio": volume_strength["volume_ratio"],
        "volume_strength_score": volume_strength["volume_strength_score"],
        "volume_strength_label": volume_strength["volume_strength_label"],
        "volume_confirmed": volume_strength["volume_confirmed"],
        "nearest_support": support_resistance["nearest_support"],
        "nearest_resistance": support_resistance["nearest_resistance"],
        "distance_to_support_percent": support_resistance["distance_to_support_percent"],
        "distance_to_resistance_percent": support_resistance["distance_to_resistance_percent"],
        "support_resistance_score": support_resistance["support_resistance_score"],
        "support_resistance_label": support_resistance["support_resistance_label"],
        "breakout_confirmation_score": breakout_confirmation_score,
        "stock_return_percent": relative_strength["stock_return_percent"],
        "benchmark_return_percent": relative_strength["benchmark_return_percent"],
        "relative_strength_percent": relative_strength["relative_strength_percent"],
        "relative_strength_score": relative_strength["relative_strength_score"],
        "relative_strength_label": relative_strength["relative_strength_label"],
        "stars": trade_quality["stars"],
        "opportunity_score": opportunity_score,
    }

    return result, decision

def save_results_to_csv(results: list[dict], file_path: str, metadata: dict) -> None:
    df = pd.DataFrame(results)
    for key, value in metadata.items():
        df.insert(0, key, value)
    column_order = [
        "trade_rank",
        "rank",
        "symbol",
        "signal",
        "opportunity_score",
        "trade_quality_score",
        "trade_quality_label",
        "stars",
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
        "volume_ratio",
        "volume_strength_score",
        "volume_strength_label",
        "volume_confirmed",
        "nearest_support",
        "nearest_resistance",
        "distance_to_support_percent",
        "distance_to_resistance_percent",
        "support_resistance_score",
        "support_resistance_label",
        "breakout_confirmation_score",
        "stock_return_percent",
        "benchmark_return_percent",
        "relative_strength_percent",
        "relative_strength_score",
        "relative_strength_label",
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
        "trade_quality_score",
        "volume_ratio",
        "volume_strength_score",
        "nearest_support",
        "nearest_resistance",
        "distance_to_support_percent",
        "distance_to_resistance_percent",
        "support_resistance_score",
        "breakout_confirmation_score",
        "stock_return_percent",
        "benchmark_return_percent",
        "relative_strength_percent",
        "relative_strength_score",
        "relative_strength_label",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = df[column].round(2)

    df.to_csv(file_path, index=False)

    print(f"\nSaved: {file_path}")


def main() -> None:
    start_time = time.time()
    print_stage("AutoT started")

    tracker = PerformanceTracker()
    print_stage("Loading configuration")
    config = ConfigurationManager()
    paper_portfolio = load_or_create_portfolio(
        initial_cash=ACCOUNT_SIZE
    )
    paper_broker = PaperBroker(paper_portfolio)
    paper_trader = PaperTrader(paper_broker)
    run_time = datetime.now()
    metadata = {
        "run_date": run_time.strftime("%Y-%m-%d"),
        "run_time": run_time.strftime("%H:%M:%S"),
        "universe": config.get_string("ACTIVE_UNIVERSE"),
        "backtest_period": config.get_string("BACKTEST_PERIOD"),
        "backtest_interval": config.get_string("BACKTEST_INTERVAL"),
    }

    print_stage("Loading universe")
    symbols = load_universe(
        config.get_string("ACTIVE_UNIVERSE")
    )
    print(f"Loaded {len(symbols)} symbols")

    tracker.start("Batch Download")
    print_stage("Loading market data from cache/download")
    batch_data = MarketDataManager.get_batch_stock_data(
        symbols=symbols,
        period=config.get_string("BACKTEST_PERIOD"),
        interval=config.get_string("BACKTEST_INTERVAL"),
    )

    benchmark_data = MarketDataManager.get_stock_data(
        "SPY",
        config.get_string("BACKTEST_PERIOD"),
        config.get_string("BACKTEST_INTERVAL"),
    )

    tracker.stop("Batch Download")
    print_stage("Loading market data from cache/download")
    results = []
    trade_decisions = {}
    max_workers = 8

    tracker.start("Analyse Stocks")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {
            executor.submit(
                analyse_stock,
                symbol,
                batch_data[symbol],
                benchmark_data,
                tracker,
            ): symbol
            for symbol in symbols
            if symbol in batch_data
        }

        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]

            try:
                result, decision = future.result()

                results.append(result)
                trade_decisions[symbol] = decision

                print(f"Completed {len(results)} / {len(symbols)}: {symbol}")

            except Exception as error:
                print(f"Error analysing {symbol}: {error}")

    tracker.stop("Analyse Stocks")

    ranked_results = sorted(
        results,
        key=lambda item: item["score"],
        reverse=True,
    )
    print_stage("Ranking results")
    for index, result in enumerate(ranked_results, start=1):
        result["rank"] = index

    top_n = config.get_int("TOP_N_STOCKS")
    top_results = ranked_results[:top_n]

    trade_opportunities = [
        result for result in results
        if result["signal"] in ["BUY", "SELL"]
        and result["trade_quality_score"] >= 70
    ]
    trade_opportunities = sorted(
        trade_opportunities,
        key=lambda item: item["opportunity_score"],
        reverse=True,
)
    for index, result in enumerate(trade_opportunities, start=1):
        result["trade_rank"] = index

    print("\n========== TODAY'S SWING TRADE OPPORTUNITIES ==========")

    if not trade_opportunities:
        print("No actionable BUY or SELL opportunities today.")
    else:
        print(
            "Rank | Symbol | Signal | Stars | Quality | Label | Confidence | Agreement | "
            "Regime | Entry | Stop Loss | Take Profit | Historical Score | Opportunity Score"
        )

        print("-" * 145)

        for index, result in enumerate(trade_opportunities, start=1):
            print(
                f"{index} | "
                f"{result['symbol']} | "
                f"{result['signal']} | "
                f"{result['stars']} | "
                f"{result['trade_quality_score']:.2f} | "
                f"{result['trade_quality_label']} | "
                f"{result['confidence']:.2f}% | "
                f"{result['agreement']:.2f}% | "
                f"{result['market_regime']} | "
                f"{result['entry_price']:.2f} | "
                f"{result['stop_loss']:.2f} | "
                f"{result['take_profit']:.2f} | "
                f"{result['score']:.2f} | "
                f"{result['opportunity_score']:.2f}"
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
    print_stage("Saving reports")
    tracker.start("Save Reports")

    os.makedirs("data_storage/processed/history", exist_ok=True)

    timestamp = run_time.strftime("%Y-%m-%d_%H%M%S")
    
    save_results_to_csv(
        ranked_results,
        f"data_storage/processed/backtest_results_{timestamp}.csv",
        metadata
    )
    save_results_to_csv(
        top_results,
        f"data_storage/processed/history/top_shortlist_{timestamp}.csv",
        metadata
    )
    save_results_to_csv(
        trade_opportunities,
        "data_storage/processed/trade_opportunities.csv",
        metadata,
    )

    save_results_to_csv(
        trade_opportunities,
        f"data_storage/processed/history/trade_opportunities_{timestamp}.csv",
        metadata,
    )
    tracker.stop("Save Reports")
    print_stage("Paper Trading Portfolio")

    print(f"Initial cash: ${paper_portfolio.initial_cash:.2f}")
    print(f"Available cash: ${paper_portfolio.cash:.2f}")
    print(
        f"Portfolio risk: "
        f"${paper_portfolio.calculate_portfolio_risk():.2f}"
    )
    print(f"Open positions: {len(paper_portfolio.positions)}")

    if paper_portfolio.positions:
        print("\nCurrent paper positions:")

        for position in paper_portfolio.positions.values():
            print(
                f"{position.symbol} | "
                f"Qty: {position.quantity} | "
                f"Entry: ${position.average_price:.2f} | "
                f"Stop: ${position.stop_loss:.2f} | "
                f"Max Risk: ${position.max_loss:.2f}"
            )
    else:
        print("No open paper positions.")
    end_time = time.time()
    total_time = end_time - start_time

    tracker.print_report()
    print_stage("AutoT completed")
    print(f"\nExecution time: {total_time:.2f} seconds")


if __name__ == "__main__":
    main()