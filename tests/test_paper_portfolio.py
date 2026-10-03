"""
File: test_paper_portfolio.py
Project: AutoT

Purpose:
    Regression tests for the AutoT paper portfolio.
"""

import pytest

from autot.portfolio.paper_portfolio import PaperPortfolio


def test_buy_creates_position_and_deducts_cash():
    portfolio = PaperPortfolio(initial_cash=10000.0)

    portfolio.buy(
        symbol="TEST",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        max_loss=50.0,
    )

    assert portfolio.cash == 9000.0
    assert "TEST" in portfolio.positions

    position = portfolio.positions["TEST"]

    assert position.symbol == "TEST"
    assert position.quantity == 10
    assert position.average_price == 100.0
    assert position.stop_loss == 95.0
    assert position.max_loss == 50.0

    assert len(portfolio.trade_history) == 1

    trade = portfolio.trade_history[0]

    assert trade.action == "BUY"
    assert trade.symbol == "TEST"
    assert trade.price == 100.0
    assert trade.quantity == 10
    assert trade.total_value == 1000.0


def test_duplicate_position_is_rejected_without_changing_portfolio():
    portfolio = PaperPortfolio(initial_cash=10000.0)

    portfolio.buy(
        symbol="TEST",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        max_loss=50.0,
    )

    with pytest.raises(ValueError):
        portfolio.buy(
            symbol="TEST",
            price=110.0,
            quantity=5,
            stop_loss=105.0,
            max_loss=25.0,
        )

    assert portfolio.cash == 9000.0
    assert len(portfolio.positions) == 1
    assert len(portfolio.trade_history) == 1


def test_buy_rejects_insufficient_cash():
    portfolio = PaperPortfolio(initial_cash=1000.0)

    with pytest.raises(ValueError):
        portfolio.buy(
            symbol="TEST",
            price=600.0,
            quantity=2,
            stop_loss=550.0,
            max_loss=100.0,
        )

    assert portfolio.cash == 1000.0
    assert portfolio.positions == {}
    assert portfolio.trade_history == []


@pytest.mark.parametrize(
    "price, quantity",
    [
        (0.0, 1),
        (-1.0, 1),
        (100.0, 0),
        (100.0, -1),
    ],
)
def test_buy_rejects_invalid_price_or_quantity(price, quantity):
    portfolio = PaperPortfolio(initial_cash=10000.0)

    with pytest.raises(ValueError):
        portfolio.buy(
            symbol="TEST",
            price=price,
            quantity=quantity,
            stop_loss=95.0,
            max_loss=50.0,
        )


def test_sell_closes_position_and_restores_cash():
    portfolio = PaperPortfolio(initial_cash=10000.0)

    portfolio.buy(
        symbol="TEST",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        max_loss=50.0,
    )

    portfolio.sell(
        symbol="TEST",
        price=110.0,
    )

    assert "TEST" not in portfolio.positions
    assert portfolio.cash == 10100.0
    assert len(portfolio.trade_history) == 2

    sell_trade = portfolio.trade_history[-1]

    assert sell_trade.action == "SELL"
    assert sell_trade.symbol == "TEST"
    assert sell_trade.price == 110.0
    assert sell_trade.quantity == 10
    assert sell_trade.total_value == 1100.0


def test_sell_missing_position_is_rejected():
    portfolio = PaperPortfolio(initial_cash=10000.0)

    with pytest.raises(ValueError):
        portfolio.sell(
            symbol="MISSING",
            price=100.0,
        )

    assert portfolio.cash == 10000.0
    assert portfolio.trade_history == []


def test_portfolio_risk_sums_open_position_max_losses():
    portfolio = PaperPortfolio(initial_cash=10000.0)

    portfolio.buy(
        symbol="AAA",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        max_loss=50.0,
    )

    portfolio.buy(
        symbol="BBB",
        price=50.0,
        quantity=20,
        stop_loss=47.0,
        max_loss=60.0,
    )

    assert portfolio.calculate_portfolio_risk() == 110.0

    portfolio.sell(
        symbol="AAA",
        price=105.0,
    )

    assert portfolio.calculate_portfolio_risk() == 60.0


def test_open_position_value_and_unrealised_profit_loss():
    portfolio = PaperPortfolio(initial_cash=10000.0)

    portfolio.buy(
        symbol="AAA",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        max_loss=50.0,
    )

    current_prices = {
        "AAA": 110.0,
    }

    assert portfolio.calculate_open_position_value(
        current_prices
    ) == 1100.0

    assert portfolio.calculate_unrealised_profit_loss(
        current_prices
    ) == 100.0


def test_missing_current_price_is_rejected():
    portfolio = PaperPortfolio(initial_cash=10000.0)

    portfolio.buy(
        symbol="AAA",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        max_loss=50.0,
    )

    with pytest.raises(ValueError):
        portfolio.calculate_open_position_value({})

    with pytest.raises(ValueError):
        portfolio.calculate_unrealised_profit_loss({})


def test_portfolio_summary_with_current_prices():
    portfolio = PaperPortfolio(initial_cash=10000.0)

    portfolio.buy(
        symbol="AAA",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        max_loss=50.0,
    )

    summary = portfolio.get_summary(
        current_prices={
            "AAA": 110.0,
        }
    )

    assert summary["initial_cash"] == 10000.0
    assert summary["cash"] == 9000.0
    assert summary["open_position_value"] == 1100.0
    assert summary["portfolio_value"] == 10100.0
    assert summary["unrealised_profit_loss"] == 100.0
    assert summary["total_profit_loss"] == 100.0
    assert summary["return_percent"] == 1.0
    assert summary["open_positions"] == 1
    assert summary["trade_count"] == 1
