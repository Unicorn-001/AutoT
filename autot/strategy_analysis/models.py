"""Versioned scan evidence and human-reviewed experiment ideas."""
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class StrategyFeature(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    strategy_id: str
    enabled: bool
    # Disabled strategies were not run; None must never be presented as HOLD.
    signal: Literal['BUY', 'SELL', 'HOLD'] | None = None
    effective_weight: Decimal | None = Field(default=None, ge=0)
    regime_weight: Decimal | None = Field(default=None, ge=0)
    manual_override: Decimal | None = Field(default=None, ge=0)
    original_confidence: Decimal | None = None
    weighted_confidence: Decimal | None = None


class TradeFeatureSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    version: Literal[1] = 1
    strategies: list[StrategyFeature] = Field(max_length=10)

    @model_validator(mode='after')
    def unique_strategies(self):
        if len({s.strategy_id for s in self.strategies}) != len(self.strategies):
            raise ValueError('Strategy IDs must be unique in a snapshot.')
        if any(not s.enabled and s.signal is not None for s in self.strategies):
            raise ValueError('Disabled strategies must not have an evaluated signal.')
        return self


class StrategyContribution(StrategyFeature):
    final_signal: Literal['BUY', 'SELL']

    @computed_field
    @property
    def aligned_with_final_signal(self) -> bool:
        return self.enabled and self.signal == self.final_signal

    @computed_field
    @property
    def opposed_final_signal(self) -> bool:
        return self.enabled and self.signal in ('BUY', 'SELL') and self.signal != self.final_signal

    @computed_field
    @property
    def held(self) -> bool:
        return self.enabled and self.signal == 'HOLD'


class ExperimentProposal(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    hypothesis: str = Field(min_length=1)
    baseline_profile: str = Field(min_length=1)  # ID/version/hash identity
    candidate_change: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    supporting_sample: int = Field(ge=0)
    metrics: dict[str, str | int | None]
    minimum_required_sample: int = Field(default=50, ge=1)
    status: Literal['DRAFT', 'READY_FOR_RESEARCH', 'RESEARCH_ACTIVE', 'REVIEWED', 'PROMOTED', 'REJECTED'] = 'DRAFT'
