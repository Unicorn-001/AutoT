"""
File: test_risk_management.py
Project: AutoT

Purpose:
    Regression tests for AutoT risk-management behaviour.
"""

import pytest

from autot.position.position_size_calculator import (
    PositionSizeCalculator,
)
from autot.risk.daily_loss_limit import can_continue_trading
from autot.risk.max_positions import can_open_new_position
from autot.risk.risk_reward import calculate_risk_reward_ratio
from autot.risk.stop_loss import calculate_stop_loss_price
from autot.risk.take_profit import calculate_take_profit_price


def test_position_size_respects_risk_limit():
    result = PositionSizeCalculator.calculate(
        account_size=10000.0,
        risk_percent=1.0,
        entry_price=100.0,
        stop_loss=95.0,
    )

    assert result.risk_amount == 100.0
    assert result.risk_per_share == 5.0
    assert result.quantity == 20
    assert result.position_value == 2000.0
    assert result.max_loss == 100.0


def test_position_size_is_capped_by_available_capital():
    result = PositionSizeCalculator.calculate(
        account_size=1000.0,
        risk_percent=10.0,
        entry_price=600.0,
        stop_loss=599.0,
    )

    assert result.quantity == 1
    assert result.position_value == 600.0
    assert result.max_loss == 1.0


def test_zero_risk_percent_produces_zero_quantity():
    result = PositionSizeCalculator.calculate(
        account_size=10000.0,
        risk_percent=0.0,
        entry_price=100.0,
        stop_loss=95.0,
    )

    assert result.quantity == 0
    assert result.position_value == 0.0
    assert result.max_loss == 0.0


def test_buy_risk_reward_ratio():
    ratio = calculate_risk_reward_ratio(
        entry_price=100.0,
        stop_loss_price=95.0,
        take_profit_price=110.0,
        signal="BUY",
    )

    assert ratio == 2.0


def test_sell_risk_reward_ratio():
    ratio = calculate_risk_reward_ratio(
        entry_price=100.0,
        stop_loss_price=105.0,
        take_profit_price=90.0,
        signal="SELL",
    )

    assert ratio == 2.0


def test_stop_loss_and_take_profit_prices():
    assert calculate_stop_loss_price(100.0, 5.0) == 95.0
    assert calculate_take_profit_price(100.0, 10.0) == pytest.approx(
        110.0
    )


def test_max_position_boundary():
    assert can_open_new_position(4, 5) is True
    assert can_open_new_position(5, 5) is False


def test_daily_loss_boundary():
    assert can_continue_trading(
        account_balance=10000.0,
        daily_loss_amount=299.99,
        daily_loss_limit_percent=3.0,
    ) is True

    assert can_continue_trading(
        account_balance=10000.0,
        daily_loss_amount=300.0,
        daily_loss_limit_percent=3.0,
    ) is False


def test_invalid_buy_risk_reward_structure_rejected():
    with pytest.raises(ValueError):
        calculate_risk_reward_ratio(
            entry_price=100.0,
            stop_loss_price=105.0,
            take_profit_price=110.0,
            signal="BUY",
        )
