"""Validated, immutable runtime settings. No Streamlit or credentials."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

PositiveInt = Annotated[int, Field(gt=0, le=10000)]
Percent = Annotated[float, Field(ge=0, le=100)]
Positive = Annotated[float, Field(gt=0)]
Weight = Annotated[float, Field(ge=0)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False, validate_default=True)


class RegimeWeights(Model):
    strong_uptrend: Weight = 1.0
    strong_downtrend: Weight = 1.0
    sideways_or_weak_trend: Weight = 1.0


class Strategy(Model):
    enabled: bool = True
    weight: Weight | None = None  # Optional replacement for the existing regime weight.
    regime_weights: RegimeWeights = Field(default_factory=RegimeWeights)

    def effective_weight(self, regime):
        return self.weight if self.weight is not None else getattr(self.regime_weights, regime.lower(), 1.0)


class EmaRsi(Strategy):
    fast: PositiveInt = 20
    slow: PositiveInt = 50
    rsi_period: PositiveInt = 14
    buy_threshold: Percent = 50
    sell_threshold: Percent = 45
    regime_weights: RegimeWeights = RegimeWeights(strong_uptrend=1.2, strong_downtrend=1.2)

    @model_validator(mode='after')
    def ordered(self):
        if self.fast >= self.slow:
            raise ValueError('EMA fast period must be below slow period.')
        if self.sell_threshold > self.buy_threshold:
            raise ValueError('RSI sell threshold must not exceed buy threshold.')
        return self


class Macd(Strategy):
    fast: PositiveInt = 12
    slow: PositiveInt = 26
    signal: PositiveInt = 9
    regime_weights: RegimeWeights = RegimeWeights(strong_uptrend=1.2, strong_downtrend=1.2)

    @model_validator(mode='after')
    def ordered(self):
        if self.fast >= self.slow:
            raise ValueError('MACD fast period must be below slow period.')
        return self


class Bollinger(Strategy):
    period: PositiveInt = 20
    deviation: Positive = 2.0
    regime_weights: RegimeWeights = RegimeWeights(strong_uptrend=.9, strong_downtrend=.9, sideways_or_weak_trend=1.2)


class Breakout(Strategy):
    lookback: PositiveInt = 20
    regime_weights: RegimeWeights = RegimeWeights(strong_uptrend=1.1, strong_downtrend=1.1, sideways_or_weak_trend=.85)


class Supertrend(Strategy):
    atr_period: PositiveInt = 10
    multiplier: Positive = 3.0
    regime_weights: RegimeWeights = RegimeWeights(strong_uptrend=1.2, strong_downtrend=1.2, sideways_or_weak_trend=.9)


class Adx(Strategy):
    period: Annotated[int, Field(ge=2, le=10000)] = 14
    threshold: Percent = 25


class VolumeSpike(Strategy):
    period: PositiveInt = 20
    threshold: Positive = 2.0
    regime_weights: RegimeWeights = RegimeWeights(sideways_or_weak_trend=1.1)


class Momentum(Strategy):
    period: PositiveInt = 10
    regime_weights: RegimeWeights = RegimeWeights(strong_uptrend=1.15, strong_downtrend=1.15, sideways_or_weak_trend=.9)


class Atr(Strategy):
    period: PositiveInt = 14
    average_period: PositiveInt = 20


class Stochastic(Strategy):
    period: PositiveInt = 14
    smooth_period: PositiveInt = 3
    oversold: Percent = 20
    overbought: Percent = 80
    regime_weights: RegimeWeights = RegimeWeights(strong_uptrend=.9, strong_downtrend=.9, sideways_or_weak_trend=1.2)

    @model_validator(mode='after')
    def ordered(self):
        if self.oversold >= self.overbought:
            raise ValueError('Stochastic oversold must be below overbought.')
        return self


class Strategies(Model):
    EMA_RSI: EmaRsi = Field(default_factory=EmaRsi)
    MACD: Macd = Field(default_factory=Macd)
    BOLLINGER: Bollinger = Field(default_factory=Bollinger)
    BREAKOUT: Breakout = Field(default_factory=Breakout)
    SUPERTREND: Supertrend = Field(default_factory=Supertrend)
    ADX: Adx = Field(default_factory=Adx)
    VOLUME_SPIKE: VolumeSpike = Field(default_factory=VolumeSpike)
    MOMENTUM: Momentum = Field(default_factory=Momentum)
    ATR: Atr = Field(default_factory=Atr)
    STOCHASTIC: Stochastic = Field(default_factory=Stochastic)


class General(Model):
    mode: Literal['FORWARD_TEST', 'RESEARCH'] = 'FORWARD_TEST'


class Scanner(Model):
    country: Literal['United States', 'United Kingdom', 'India'] = 'United States'
    index: str = 'sp500'
    history_period: Literal['1mo','3mo','6mo','1y','2y','5y','10y','ytd','max'] = '5y'
    interval: Literal['1d','5d','1wk','1mo','3mo','1h','60m','30m','15m','5m','2m','1m','90m'] = '1d'
    top_ranked_count: PositiveInt = 10
    top_trade_opportunity_count: PositiveInt | None = None  # Previously all opportunities.

    @model_validator(mode='after')
    def valid_index(self):
        from autot.universe.index_definitions import INDICES
        if self.index not in INDICES or INDICES[self.index].country != self.country:
            raise ValueError('Select an index belonging to the default country.')
        return self


class Consensus(Model):
    minimum_confidence: Percent = 55.0
    minimum_agreement: Percent = 0.0  # No additional restriction at baseline.


class Risk(Model):
    risk_per_trade_percent: Annotated[float, Field(gt=0, le=100)] = 1.0
    maximum_position_percent: Annotated[float, Field(gt=0, le=100)] = 30.0
    maximum_simultaneous_positions: PositiveInt = 5
    maximum_total_portfolio_risk_percent: Annotated[float, Field(gt=0, le=100)] = 2.5
    minimum_risk_reward: Annotated[float, Field(ge=0)] = 0.0
    maximum_new_trades_per_day: PositiveInt = 5
    enforce_position_limit: bool = False
    enforce_positions_limit: bool = False
    enforce_portfolio_risk_limit: bool = False
    enforce_daily_trade_limit: bool = False
    allow_buy: bool = True
    allow_sell: bool = True
    manual_confirmation_required: bool = True

    @model_validator(mode='after')
    def consistent(self):
        if self.enforce_portfolio_risk_limit and self.maximum_total_portfolio_risk_percent < self.risk_per_trade_percent:
            raise ValueError('Enabled portfolio risk limit must be at least single-trade risk.')
        return self


class PaperTrading(Model):
    usd_base_capital: Positive = 10000.0
    gbp_base_capital: Positive = 10000.0
    inr_base_capital: Positive = 10000.0

    def capital(self, currency):
        return getattr(self, currency.lower() + '_base_capital')


class News(Model):
    enabled: bool = False
    general_news_enabled: bool = False
    official_disclosures_enabled: bool = False
    recent_window_days: PositiveInt = 7
    max_articles: PositiveInt = 50


class Monitoring(Model):
    paper_monitor_enabled: bool = False
    paper_update_interval_minutes: PositiveInt = 5
    daily_scan_enabled: bool = False
    daily_scan_time_local: Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")] = "22:00"
    daily_scan_quality_threshold: Annotated[float, Field(ge=70, le=100)] = 70.0


class Notifications(Model):
    notifications_enabled: bool = False
    notification_channel: Literal['CONSOLE'] = 'CONSOLE'


class Advanced(Model):
    execution_timeframe: Literal['5m'] = '5m'
    fill_model: Literal['NEXT_SESSION_OPEN'] = 'NEXT_SESSION_OPEN'
    same_bar_rule: Literal['STOP_FIRST'] = 'STOP_FIRST'
    calendar_model: Literal['SessionCalendar'] = 'SessionCalendar'
    market_data_provider: Literal['Yahoo'] = 'Yahoo'
    execution_provider: Literal['PAPER'] = 'PAPER'
    database_path: Literal['AUTOT_DATA_DIR/paper_trading/ledger.sqlite3'] = 'AUTOT_DATA_DIR/paper_trading/ledger.sqlite3'


class AutoTSettings(Model):
    schema_version: Literal[1] = 1
    general: General = Field(default_factory=General)
    scanner: Scanner = Field(default_factory=Scanner)
    strategies: Strategies = Field(default_factory=Strategies)
    consensus: Consensus = Field(default_factory=Consensus)
    risk: Risk = Field(default_factory=Risk)
    paper_trading: PaperTrading = Field(default_factory=PaperTrading)
    news: News = Field(default_factory=News)
    monitoring: Monitoring = Field(default_factory=Monitoring)
    notifications: Notifications = Field(default_factory=Notifications)
    advanced: Advanced = Field(default_factory=Advanced)


class TradingConfiguration(Model):
    strategies: Strategies
    consensus: Consensus
    risk: Risk

    @classmethod
    def from_settings(cls, settings):
        return cls(strategies=settings.strategies, consensus=settings.consensus, risk=settings.risk)


def canonical(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='json')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def configuration_hash(value):
    return sha256(canonical(value).encode()).hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class StrategyProfile(Model):
    profile_id: str = Field(min_length=1)
    profile_name: str = Field(min_length=1, max_length=100)
    profile_version: PositiveInt = 1
    created_at: str
    updated_at: str
    parent_profile_id: str | None = None
    configuration_hash: str
    configuration: TradingConfiguration
    builtin: bool = False

    @field_validator('created_at', 'updated_at')
    @classmethod
    def valid_timestamp(cls, value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError('Profile timestamps must include a timezone.')
        return parsed.astimezone(timezone.utc).isoformat()

    @model_validator(mode='after')
    def valid_hash(self):
        if self.builtin or self.profile_id == 'autot-baseline':
            if (not self.builtin or self.profile_id != 'autot-baseline' or self.profile_version != 1
                    or self.profile_name != 'AutoT Current / Baseline'
                    or self.configuration != TradingConfiguration.from_settings(AutoTSettings())):
                raise ValueError('The built-in baseline profile is protected.')
        if self.configuration_hash != configuration_hash(self.configuration):
            raise ValueError('Profile configuration hash does not match its snapshot.')
        return self


def baseline_profile():
    config = TradingConfiguration.from_settings(AutoTSettings())
    return StrategyProfile(profile_id='autot-baseline', profile_name='AutoT Current / Baseline',
                           created_at='2026-10-24T00:00:00+00:00', updated_at='2026-10-24T00:00:00+00:00',
                           configuration_hash=configuration_hash(config), configuration=config, builtin=True)


class SettingsState(Model):
    settings_version: Annotated[int, Field(ge=0)] = 0
    settings: AutoTSettings = Field(default_factory=AutoTSettings)
    profile: StrategyProfile = Field(default_factory=baseline_profile)

    @model_validator(mode='after')
    def consistent(self):
        if TradingConfiguration.from_settings(self.settings) != self.profile.configuration:
            raise ValueError('Active settings do not match the profile snapshot.')
        return self


class TradeSettingsSnapshot(Model):
    settings_version: Annotated[int, Field(ge=0)]
    strategy_profile_id: str
    strategy_profile_name: str
    strategy_profile_version: PositiveInt
    strategy_config_hash: str
    configuration_source: Literal['SETTINGS_V1'] = 'SETTINGS_V1'
    mode: Literal['FORWARD_TEST', 'RESEARCH']
    trading_settings: TradingConfiguration
    execution_risk_percent: Annotated[float, Field(gt=0, le=100)]

    @model_validator(mode='after')
    def valid_hash(self):
        if self.strategy_config_hash != configuration_hash(self.trading_settings):
            raise ValueError('Trade configuration hash does not match its snapshot.')
        return self

    @classmethod
    def from_state(cls, state, execution_risk_percent=None):
        p = state.profile
        return cls(settings_version=state.settings_version, strategy_profile_id=p.profile_id,
                   strategy_profile_name=p.profile_name, strategy_profile_version=p.profile_version,
                   strategy_config_hash=p.configuration_hash, mode=state.settings.general.mode,
                   trading_settings=p.configuration,
                   execution_risk_percent=execution_risk_percent if execution_risk_percent is not None else state.settings.risk.risk_per_trade_percent)
