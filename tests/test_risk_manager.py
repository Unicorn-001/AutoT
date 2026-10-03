"""
File: test_risk_manager.py
Project: AutoT

Purpose:
    Regression tests for the central AutoT RiskManager.
"""

import pytest

from autot.risk.risk_manager import RiskManager


def test_trade_passes_all_risk_checks():
    result = RiskManager.can_open_trade(
        account_balance=10000.0,
        current_open_positions=2,
        current_portfolio_risk=200.0,
        new_trade_max_loss=100.0,
        daily_loss_amount=50.0,
    )

    assert result["can_open_trade"] is True
    assert result["position_limit_ok"] is True
    assert result["daily_loss_limit_ok"] is True
    assert result["portfolio_risk_limit_ok"] is True

    assert result["current_portfolio_risk"] == 200.0
    assert result["new_trade_max_loss"] == 100.0
    assert result["proposed_portfolio_risk"] == 300.0
    assert result["maximum_portfolio_risk"] == 500.0

    assert result["reasons"] == [
        "Trade passes all portfolio risk checks."
    ]


def test_maximum_position_limit_rejects_trade():
    result = RiskManager.can_open_trade(
        account_balance=10000.0,
        current_open_positions=5,
        current_portfolio_risk=200.0,
        new_trade_max_loss=100.0,
        daily_loss_amount=50.0,
    )

    assert result["can_open_trade"] is False
    assert result["position_limit_ok"] is False
    assert result["daily_loss_limit_ok"] is True
    assert result["portfolio_risk_limit_ok"] is True

    assert "Maximum open position limit reached." in result["reasons"]


def test_daily_loss_limit_rejects_trade_at_exact_boundary():
    result = RiskManager.can_open_trade(
        account_balance=10000.0,
        current_open_positions=2,
        current_portfolio_risk=200.0,
        new_trade_max_loss=100.0,
        daily_loss_amount=300.0,
    )

    assert result["can_open_trade"] is False
    assert result["position_limit_ok"] is True
    assert result["daily_loss_limit_ok"] is False
    assert result["portfolio_risk_limit_ok"] is True

    assert "Maximum daily loss limit reached." in result["reasons"]


def test_portfolio_risk_exact_limit_is_allowed():
    result = RiskManager.can_open_trade(
        account_balance=10000.0,
        current_open_positions=2,
        current_portfolio_risk=400.0,
        new_trade_max_loss=100.0,
        daily_loss_amount=0.0,
    )

    assert result["maximum_portfolio_risk"] == 500.0
    assert result["proposed_portfolio_risk"] == 500.0

    assert result["portfolio_risk_limit_ok"] is True
    assert result["can_open_trade"] is True


def test_portfolio_risk_above_limit_rejects_trade():
    result = RiskManager.can_open_trade(
        account_balance=10000.0,
        current_open_positions=2,
        current_portfolio_risk=400.0,
        new_trade_max_loss=100.01,
        daily_loss_amount=0.0,
    )

    assert result["maximum_portfolio_risk"] == 500.0
    assert result["proposed_portfolio_risk"] == 500.01

    assert result["portfolio_risk_limit_ok"] is False
    assert result["can_open_trade"] is False

    assert (
        "Maximum portfolio risk limit would be exceeded."
        in result["reasons"]
    )


def test_multiple_risk_failures_are_reported():
    result = RiskManager.can_open_trade(
        account_balance=10000.0,
        current_open_positions=5,
        current_portfolio_risk=500.0,
        new_trade_max_loss=100.0,
        daily_loss_amount=300.0,
    )

    assert result["can_open_trade"] is False
    assert result["position_limit_ok"] is False
    assert result["daily_loss_limit_ok"] is False
    assert result["portfolio_risk_limit_ok"] is False

    assert result["reasons"] == [
        "Maximum open position limit reached.",
        "Maximum daily loss limit reached.",
        "Maximum portfolio risk limit would be exceeded.",
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "account_balance": 0.0,
            "current_open_positions": 0,
            "current_portfolio_risk": 0.0,
            "new_trade_max_loss": 0.0,
            "daily_loss_amount": 0.0,
        },
        {
            "account_balance": 10000.0,
            "current_open_positions": -1,
            "current_portfolio_risk": 0.0,
            "new_trade_max_loss": 0.0,
            "daily_loss_amount": 0.0,
        },
        {
            "account_balance": 10000.0,
            "current_open_positions": 0,
            "current_portfolio_risk": -1.0,
            "new_trade_max_loss": 0.0,
            "daily_loss_amount": 0.0,
        },
        {
            "account_balance": 10000.0,
            "current_open_positions": 0,
            "current_portfolio_risk": 0.0,
            "new_trade_max_loss": -1.0,
            "daily_loss_amount": 0.0,
        },
        {
            "account_balance": 10000.0,
            "current_open_positions": 0,
            "current_portfolio_risk": 0.0,
            "new_trade_max_loss": 0.0,
            "daily_loss_amount": -1.0,
        },
    ],
)
def test_invalid_risk_manager_inputs_raise_value_error(arguments):
    with pytest.raises(ValueError):
        RiskManager.can_open_trade(**arguments)
