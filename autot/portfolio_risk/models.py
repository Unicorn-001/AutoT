"""Validated Decimal views of ledger inputs and portfolio risk results."""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from autot.paper_trade.sessions import MARKETS, utc
from autot.settings.models import Model, Risk, TradeSettingsSnapshot

Money = Annotated[Decimal, Field(ge=0)]
PositiveMoney = Annotated[Decimal, Field(gt=0)]
Count = Annotated[int, Field(ge=0)]
Mode = Literal['FORWARD_TEST', 'RESEARCH']
Currency = Literal['USD', 'GBP', 'INR']


class LedgerView(BaseModel):
    # Ledger snapshots contain many unrelated strategy/audit fields.
    model_config = ConfigDict(extra='ignore', frozen=True, allow_inf_nan=False)


class Account(LedgerView):
    currency: Currency
    capital: PositiveMoney
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    reserved: Money
    available: Decimal

    @model_validator(mode='after')
    def balanced(self):
        if self.available != self.capital + self.realized_pnl - self.reserved:
            raise ValueError('Account available capital does not match its reservations.')
        return self


class Exposure(LedgerView):
    currency: Currency
    market: Literal['US', 'UK', 'IN']
    mode: Mode | None = None
    created_at: datetime
    status: Literal['PENDING_ENTRY', 'OPEN', 'CLOSED', 'CANCELLED']
    signal_price: PositiveMoney
    stop_loss: PositiveMoney
    quantity: Annotated[int, Field(gt=0, strict=True)]
    fill_price: PositiveMoney | None = None

    @field_validator('created_at')
    @classmethod
    def aware(cls, value):
        return utc(value)

    @model_validator(mode='after')
    def market_currency(self):
        if MARKETS[self.market][0] != self.currency:
            raise ValueError('Market does not match the currency account.')
        return self

    @property
    def planned_risk(self):
        # Exact snapshotted prices, not the rounded display risk/share.
        return abs(self.signal_price - self.stop_loss) * self.quantity

    @property
    def fill_adjusted_risk(self):
        return abs((self.fill_price or self.signal_price) - self.stop_loss) * self.quantity

    @property
    def reserved_notional(self):
        return (self.fill_price or self.signal_price) * self.quantity


class Proposal(Exposure):
    status: Literal['PENDING_ENTRY'] = 'PENDING_ENTRY'
    fill_price: None = None
    side: Literal['BUY', 'SELL']
    take_profit: PositiveMoney
    account_capital: PositiveMoney
    risk_percent: Annotated[Decimal, Field(gt=0, le=100)]
    risk_amount: Money
    risk_per_share: Money  # Display rounded by the existing calculator; may round to zero.
    intended_position_value: PositiveMoney


class PortfolioExposure(Model):
    currency: Currency
    mode: Mode
    market: Literal['US', 'UK', 'IN']
    market_timezone: str
    local_date: date
    evaluated_at: datetime
    account_capital: PositiveMoney
    account_equity: Decimal  # Realized equity, excluding unrealized P&L.
    unrealized_pnl: Decimal
    available_capital: Decimal
    existing_reserved_notional: Money
    pending_positions: Count
    open_positions: Count
    current_open_positions: Count  # PENDING_ENTRY + OPEN across both modes.
    current_open_risk: Money  # Planned snapshot stop risk across both modes.
    fill_adjusted_open_risk: Money
    fill_risk_difference: Decimal
    current_open_risk_percent: Money
    maximum_total_portfolio_risk: Money
    largest_position: Money
    largest_position_percent: Money
    maximum_positions: Count
    remaining_position_slots: Count | None  # None means not enforced.
    new_trades_today: Count
    maximum_new_trades_per_day: Count
    risk_settings: Risk
    settings_snapshot: TradeSettingsSnapshot | None
    percentage_basis: Literal['ACCOUNT_BASE_CAPITAL'] = 'ACCOUNT_BASE_CAPITAL'
    exposure_scope: Literal['SHARED_CURRENCY_ACCOUNT'] = 'SHARED_CURRENCY_ACCOUNT'
    daily_count_scope: Literal['MARKET_LOCAL_DATE_AND_MODE'] = 'MARKET_LOCAL_DATE_AND_MODE'
    warnings: list[str]


class PortfolioRiskDecision(PortfolioExposure):
    engine_version: Literal[1] = 1
    allowed: bool
    decision: Literal['ALLOW', 'REJECT']
    reasons: list[str]
    proposed_position_value: Money
    proposed_position_percent: Money
    proposed_trade_risk: Money
    proposed_trade_risk_percent: Money
    proposed_total_open_risk: Money
    post_trade_reserved_notional: Money
    planned_risk_reward: Money
    execution_risk_percent: Annotated[Decimal, Field(gt=0, le=100)]

    @model_validator(mode='after')
    def consistent_decision(self):
        if self.allowed != (self.decision == 'ALLOW') or not self.reasons:
            raise ValueError('Risk decision must have consistent status and explicit reasons.')
        return self


class PortfolioRiskRejected(ValueError):
    """Compatible with existing callers, with a typed decision for UI/API clients."""
    def __init__(self, result: PortfolioRiskDecision):
        self.result = result
        super().__init__(' '.join(result.reasons))


class RejectedProposal(Proposal):
    symbol: str


class RiskRejection(Model):
    decision_id: str
    recorded_at: datetime
    confirmation_key: str
    proposal: RejectedProposal
    decision: PortfolioRiskDecision


class FuturePortfolioControls(Model):
    """V2 interface only: not part of active settings or admission in V1."""
    maximum_daily_realized_loss_percent: Annotated[Decimal, Field(gt=0, le=100)] | None = None
    maximum_drawdown_percent: Annotated[Decimal, Field(gt=0, le=100)] | None = None
    trading_halt: bool = False
    sector: str | None = None
    industry: str | None = None
    correlation_group: str | None = None
    beta: Decimal | None = None
