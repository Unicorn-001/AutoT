"""
File: test_paper_trader.py
Project: AutoT

Purpose:
    Regression tests for the paper-trading orchestration layer.

These tests protect the path:

TradeDecision
    -> PaperTrader
    -> RiskManager
    -> PaperBroker
    -> PaperExecution
    -> PaperPortfolio
"""

import pytest

from autot.broker.paper_broker import PaperBroker
from autot.decision.trade_decision import TradeDecision
from autot.portfolio.paper_portfolio import PaperPortfolio
from autot.position.position_size import PositionSize
from autot.trading.paper_trader import PaperTrader


def make_decision(
    signal="BUY",
    symbol="TEST",
    entry_price=100.0,
    stop_loss=95.0,
    take_profit=110.0,
    quantity=10,
    max_loss=50.0,
):
    """
    Build a predictable TradeDecision for paper-trader tests.
    """

    position_size = PositionSize(
        account_size=10000.0,
        risk_percent=1.0,
        risk_amount=100.0,
        entry_price=entry_price,
        stop_loss=stop_loss,
        risk_per_share=abs(entry_price - stop_loss),
        quantity=quantity,
        position_value=entry_price * quantity,
        max_loss=max_loss,
    )

    return TradeDecision(
        symbol=symbol,
        final_signal=signal,
        confidence=85.0,
        agreement=80.0,
        market_regime="STRONG_UPTREND",
        buy_score=3.0,
        sell_score=0.5,
        hold_score=0.5,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward_ratio=2.0,
        decision_reason="TEST_DECISION",
        position_size=position_size,
    )


def make_trader(initial_cash=10000.0):
    portfolio = PaperPortfolio(initial_cash=initial_cash)
    broker = PaperBroker(portfolio)
    trader = PaperTrader(broker)

    return portfolio, broker, trader


def test_buy_decision_executes_through_real_paper_stack():
    portfolio, _, trader = make_trader()

    decision = make_decision()

    result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    assert result["executed"] is True
    assert result["symbol"] == "TEST"
    assert result["signal"] == "BUY"
    assert result["quantity"] == 10
    assert result["entry_price"] == 100.0
    assert result["position_value"] == 1000.0
    assert result["max_loss"] == 50.0

    assert "TEST" in portfolio.positions
    assert portfolio.cash == 9000.0

    position = portfolio.positions["TEST"]

    assert position.quantity == 10
    assert position.average_price == 100.0
    assert position.stop_loss == 95.0
    assert position.max_loss == 50.0


def test_hold_decision_does_not_execute_trade():
    portfolio, _, trader = make_trader()

    decision = make_decision(signal="HOLD")

    result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    assert result["executed"] is False
    assert result["signal"] == "HOLD"
    assert "HOLD signal" in result["reason"]

    assert portfolio.cash == 10000.0
    assert portfolio.positions == {}


def test_sell_signal_does_not_open_short_position():
    portfolio, _, trader = make_trader()

    decision = make_decision(signal="SELL")

    result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    assert result["executed"] is False
    assert result["signal"] == "SELL"
    assert "short positions" in result["reason"]

    assert portfolio.cash == 10000.0
    assert portfolio.positions == {}


def test_unsupported_signal_does_not_execute():
    portfolio, _, trader = make_trader()

    decision = make_decision(signal="INVALID")

    result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    assert result["executed"] is False
    assert result["signal"] == "INVALID"
    assert result["reason"] == "Unsupported trading signal."

    assert portfolio.positions == {}


def test_zero_quantity_buy_is_rejected():
    portfolio, _, trader = make_trader()

    decision = make_decision(
        quantity=0,
        max_loss=0.0,
    )

    result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    assert result["executed"] is False
    assert result["signal"] == "BUY"
    assert "quantity is zero" in result["reason"]

    assert portfolio.cash == 10000.0
    assert portfolio.positions == {}


def test_daily_loss_limit_blocks_trade():
    portfolio, _, trader = make_trader()

    decision = make_decision()

    result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=300.0,
    )

    assert result["executed"] is False
    assert result["signal"] == "BUY"
    assert result["risk_check"]["can_open_trade"] is False

    assert portfolio.cash == 10000.0
    assert portfolio.positions == {}


def test_duplicate_buy_returns_broker_error_without_second_trade():
    portfolio, _, trader = make_trader()

    decision = make_decision()

    first_result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    second_result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    assert first_result["executed"] is True
    assert second_result["executed"] is False

    assert "TEST" in second_result["reason"]

    assert len(portfolio.positions) == 1
    assert portfolio.positions["TEST"].quantity == 10
    assert portfolio.cash == 9000.0


def test_close_position_realizes_profit():
    portfolio, _, trader = make_trader()

    decision = make_decision()

    buy_result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    assert buy_result["executed"] is True

    close_result = trader.close_position(
        symbol="TEST",
        exit_price=110.0,
    )

    assert close_result["executed"] is True
    assert close_result["action"] == "CLOSE"
    assert close_result["quantity"] == 10
    assert close_result["entry_price"] == 100.0
    assert close_result["exit_price"] == 110.0
    assert close_result["realized_profit_loss"] == 100.0

    assert "TEST" not in portfolio.positions
    assert portfolio.cash == 10100.0


def test_close_position_realizes_loss():
    portfolio, _, trader = make_trader()

    decision = make_decision()

    trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    close_result = trader.close_position(
        symbol="TEST",
        exit_price=90.0,
    )

    assert close_result["executed"] is True
    assert close_result["realized_profit_loss"] == -100.0

    assert "TEST" not in portfolio.positions
    assert portfolio.cash == 9900.0


def test_close_missing_position_is_rejected():
    portfolio, _, trader = make_trader()

    result = trader.close_position(
        symbol="MISSING",
        exit_price=100.0,
    )

    assert result["executed"] is False
    assert result["action"] == "CLOSE"
    assert "No open position found" in result["reason"]

    assert portfolio.cash == 10000.0
    assert portfolio.positions == {}


def test_insufficient_cash_is_reported_as_failed_execution():
    portfolio, _, trader = make_trader(
        initial_cash=500.0,
    )

    decision = make_decision(
        entry_price=100.0,
        quantity=10,
        max_loss=50.0,
    )

    result = trader.execute_decision(
        decision=decision,
        daily_loss_amount=0.0,
    )

    assert result["executed"] is False
    assert result["signal"] == "BUY"

    assert portfolio.cash == 500.0
    assert portfolio.positions == {}
