"""Execution-only risk check using the existing account and exposure policy."""
from decimal import ROUND_FLOOR

from autot.portfolio_risk.engine import portfolio_exposure
from autot.settings.trade_policy import validate_trade_settings
from autot.utils.financial_validation import decimal_value as D


def recheck(trade, fill, trades, summary, *, checked_at, fill_time):
    result = dict(version=1, reference_entry=trade.get('signal_price'),
                  planned_quantity=trade.get('quantity'), planned_risk_per_share=None,
                  planned_total_risk=None, actual_fill_price=None, actual_risk_per_share=None,
                  actual_total_risk=None, approved_quantity=0, approved_total_risk='0',
                  decision='REJECT', reason='INVALID_EXECUTION_DATA', rechecked_at=checked_at,
                  fill_time=fill_time, risk_allowance=None)

    def reject(reason):
        result.update(decision='REJECT', reason=reason, approved_quantity=0, approved_total_risk='0')
        return result

    try:
        price = D(fill, positive=True)
        result['actual_fill_price'] = str(price)
        entry, stop = (D(v, positive=True) for v in
                       (trade.get('signal_price'), trade.get('stop_loss')))
        D(trade.get('take_profit'), positive=True)
        qty = trade.get('quantity')
        if type(qty) is not int or qty < 1 or trade.get('side') not in ('BUY', 'SELL'):
            return result
        direction = 1 if trade['side'] == 'BUY' else -1
        planned, actual = (entry-stop)*direction, (price-stop)*direction
        result.update(reference_entry=str(entry), actual_fill_price=str(price),
                      planned_risk_per_share=str(planned), planned_total_risk=str(planned*qty),
                      actual_risk_per_share=str(actual), actual_total_risk=str(actual*qty))
        if actual <= 0:
            return reject('INVALID_STOP_RELATIVE_TO_FILL')
        if planned <= 0:
            return result
        config = validate_trade_settings(trade)
        # Exclude this pending reservation from position/risk counts. Daily policy
        # remains the existing market-local CONFIRMATION-day policy (not fill day).
        others = [t for t in trades if t['trade_id'] != trade['trade_id']]
        view = portfolio_exposure(others, summary, settings_snapshot=config,
                                  market=trade['market'], mode=trade.get('mode') or 'FORWARD_TEST',
                                  when=trade['created_at'])
        risk = view.risk_settings
        percent = D(risk.risk_per_trade_percent if config else trade['risk_percent'], positive=True)
        allowance = view.account_capital * percent / 100
        result['risk_allowance'] = str(allowance)
        approved = min(qty, int((allowance / actual).to_integral_value(rounding=ROUND_FLOOR)))
        if approved < 1:
            return reject('MINIMUM_QUANTITY_NOT_POSSIBLE')
        if config:
            if risk.enforce_positions_limit and view.current_open_positions >= risk.maximum_simultaneous_positions:
                return reject('POSITION_LIMIT')
            if risk.enforce_daily_trade_limit and view.new_trades_today >= risk.maximum_new_trades_per_day:
                return reject('DAILY_TRADE_LIMIT')
            if (risk.enforce_portfolio_risk_limit and
                    view.fill_adjusted_open_risk + actual*approved > view.maximum_total_portfolio_risk):
                return reject('PORTFOLIO_RISK_LIMIT')
            if risk.enforce_position_limit and price*approved > view.account_capital * D(risk.maximum_position_percent)/100:
                return reject('POSITION_LIMIT')
        # The ledger summary still includes this trade's original reservation.
        if price*approved > view.available_capital + entry*qty:
            return reject('INSUFFICIENT_CAPITAL')
        result.update(approved_quantity=approved, approved_total_risk=str(actual*approved),
                      decision='RESIZE' if approved < qty else 'ACCEPT',
                      reason='GAP_INCREASED_RISK' if approved < qty else 'WITHIN_RISK')
        return result
    except (ValueError, TypeError, KeyError):
        return reject('INVALID_EXECUTION_DATA')
