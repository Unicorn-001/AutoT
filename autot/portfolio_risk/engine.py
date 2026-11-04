"""Pure portfolio calculations. Caller supplies a consistent ledger read snapshot.

Admission uses base capital (Settings V1 basis), planned stop risk and shared
currency exposures. Daily counts alone are mode-specific, on the market local
calendar date of creation (including weekends/cancellations, not fill date).
"""
from zoneinfo import ZoneInfo

from autot.paper_trade.sessions import MARKETS, utc
from autot.portfolio_risk.models import Account, Exposure, Proposal, PortfolioExposure, PortfolioRiskDecision
from autot.position.position_size_calculator import PositionSizeCalculator
from autot.settings.models import Risk
from autot.settings.trade_policy import validate_trade_settings
from autot.utils.financial_validation import decimal_value as D


def portfolio_exposure(trades, summary, *, settings_snapshot, market, mode, when):
    account = Account.model_validate(summary)
    if MARKETS[market][0] != account.currency:
        raise ValueError('Market does not match the currency account.')
    risk = settings_snapshot.trading_settings.risk if settings_snapshot else Risk()
    zone = ZoneInfo(MARKETS[market][1])
    when = utc(when)
    day = when.astimezone(zone).date()
    scope = [Exposure.model_validate(t) for t in trades if t['currency'] == account.currency]
    positions = [t for t in scope if t.status in ('PENDING_ENTRY', 'OPEN')]
    planned = sum((t.planned_risk for t in positions), D(0))
    filled = sum((t.fill_adjusted_risk for t in positions), D(0))
    largest = max((t.reserved_notional for t in positions), default=D(0))
    warnings = []
    if filled != planned:
        warnings.append('Fill-adjusted stop risk differs from planned risk; admission limits use planned snapshots.')
    if any(t.mode is None for t in scope):
        warnings.append('Pre-settings trades share account exposure and count in forward daily admissions; their stored mode remains unknown.')
    return PortfolioExposure(
        currency=account.currency, market=market, mode=mode, market_timezone=str(zone), local_date=day,
        evaluated_at=when, account_capital=account.capital,
        account_equity=account.capital + account.realized_pnl, unrealized_pnl=account.unrealized_pnl,
        available_capital=account.available, existing_reserved_notional=account.reserved,
        pending_positions=sum(t.status == 'PENDING_ENTRY' for t in positions),
        open_positions=sum(t.status == 'OPEN' for t in positions), current_open_positions=len(positions),
        current_open_risk=planned, fill_adjusted_open_risk=filled, fill_risk_difference=filled-planned,
        current_open_risk_percent=planned / account.capital * 100,
        maximum_total_portfolio_risk=account.capital * D(risk.maximum_total_portfolio_risk_percent) / 100,
        largest_position=largest, largest_position_percent=largest / account.capital * 100,
        maximum_positions=risk.maximum_simultaneous_positions,
        remaining_position_slots=max(0, risk.maximum_simultaneous_positions-len(positions)) if risk.enforce_positions_limit else None,
        new_trades_today=sum(t.market == market and (t.mode or 'FORWARD_TEST') == mode
                            and t.created_at.astimezone(zone).date() == day for t in scope),
        maximum_new_trades_per_day=risk.maximum_new_trades_per_day,
        risk_settings=risk, settings_snapshot=settings_snapshot, warnings=warnings,
    )


def evaluate_admission(snapshot, trades, summary):
    """Return all policy failures; malformed inputs raise validation errors.

    Legacy low-level imports retain their pre-settings sizing provenance. All
    Settings V1 service proposals must match the existing sizing calculator.
    """
    config = validate_trade_settings(snapshot)
    proposed = Proposal.model_validate(snapshot)
    view = portfolio_exposure(trades, summary, settings_snapshot=config, market=proposed.market,
                              mode=proposed.mode or 'FORWARD_TEST', when=proposed.created_at)
    risk = view.risk_settings
    reasons, warnings = [], list(view.warnings)
    entry, stop, target = proposed.signal_price, proposed.stop_loss, proposed.take_profit
    distance = abs(entry-stop)
    rr = abs(target-entry) / distance if distance else D(0)
    value = entry * proposed.quantity
    planned = proposed.planned_risk
    percent = value / view.account_capital * 100
    total_risk = view.current_open_risk + planned
    if proposed.account_capital != view.account_capital:
        reasons.append('Use the existing paper account capital for this currency.')
    if value > view.available_capital:
        reasons.append(f'Insufficient available paper capital, including pending reservations: '
                       f'{value} {view.currency} required; {view.available_capital} available.')
    if config is not None:
        if not (stop < entry < target if proposed.side == 'BUY' else target < entry < stop):
            reasons.append('Planned entry, stop and target are invalid for the trade side.')
        expected = PositionSizeCalculator.calculate(proposed.account_capital, proposed.risk_percent, entry, stop)
        if (proposed.quantity != expected.quantity or proposed.risk_amount != expected.risk_amount
                or proposed.risk_per_share != expected.risk_per_share or proposed.intended_position_value != value):
            reasons.append('Trade risk budget, risk/share, quantity or notional does not match the existing sizing engine.')
        if proposed.risk_percent != D(risk.risk_per_trade_percent):
            reasons.append(f'Risk differs from the scan profile: {proposed.risk_percent}% does not match configured '
                           f'risk_per_trade_percent {risk.risk_per_trade_percent:g}%. Save settings and run a new scan.')
        if (proposed.side == 'BUY' and not risk.allow_buy) or (proposed.side == 'SELL' and not risk.allow_sell):
            reasons.append(f'{proposed.side} trades are disabled by this strategy profile.')
        if rr < D(risk.minimum_risk_reward):
            reasons.append(f'Trade is below the configured minimum risk/reward: {rr:.4f} < {risk.minimum_risk_reward:g}.')
        if risk.enforce_position_limit and value > view.account_capital * D(risk.maximum_position_percent) / 100:
            reasons.append(f'Trade exceeds the maximum position percent: {percent:.4f}% > {risk.maximum_position_percent:g}% of base capital.')
        if risk.enforce_positions_limit and view.current_open_positions >= risk.maximum_simultaneous_positions:
            reasons.append(f'Maximum simultaneous positions reached (including pending entries): '
                           f'{view.current_open_positions} / {risk.maximum_simultaneous_positions}.')
        if risk.enforce_portfolio_risk_limit and total_risk > view.maximum_total_portfolio_risk:
            reasons.append(f'Trade exceeds the maximum total portfolio risk: {total_risk} > '
                           f'{view.maximum_total_portfolio_risk} {view.currency} planned stop risk.')
        if risk.enforce_daily_trade_limit and view.new_trades_today >= risk.maximum_new_trades_per_day:
            reasons.append(f'Maximum new trades per market-local day reached: {view.new_trades_today} / '
                           f'{risk.maximum_new_trades_per_day} for {view.mode} on {view.local_date} ({view.market_timezone}).')
    return PortfolioRiskDecision(**view.model_dump(exclude={'warnings'}), warnings=warnings,
        allowed=not reasons, decision='REJECT' if reasons else 'ALLOW',
        reasons=reasons or ['Available capital and all enforced portfolio admission limits permit this trade.'],
        proposed_position_value=value, proposed_position_percent=percent,
        proposed_trade_risk=planned, proposed_trade_risk_percent=planned / view.account_capital * 100,
        proposed_total_open_risk=total_risk, post_trade_reserved_notional=view.existing_reserved_notional+value,
        planned_risk_reward=rr, execution_risk_percent=proposed.risk_percent)
