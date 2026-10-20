"""Prospective confirmation and deterministic bar execution. No broker calls."""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging

from autot.paper_trade.intraday import HistoryUnavailable
from autot.paper_trade.ledger import ConcurrentUpdate
from autot.paper_trade.sessions import BAR, MARKETS, SessionCalendar, utc
from autot.portfolio.pnl import calculate_pnl
from autot.position.position_size_calculator import PositionSizeCalculator
from autot.risk.risk_reward import calculate_risk_reward_ratio
from autot.utils.financial_validation import decimal_value as D


LOGGER = logging.getLogger(__name__)
STATE_FIELDS = ("status", "fill_price", "filled_at", "last_checked_at", "exit_price", "closed_at",
                "realized_pnl", "unrealized_pnl", "current_price", "pnl_percent", "exit_reason",
                "intrabar_sequence_ambiguous", "ambiguity_reason", "review_required", "review_reason",
                "manual_close_requested_at", "cancelled_at", "data_source")


def now_utc():
    return datetime.now(timezone.utc)


def _json_scalar(value):
    # Scanner rows can contain numpy scalars; preserve their values, not reprs.
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise ValueError("Signal snapshot contains an unsupported value.")


def quote_scale(market, quote_currency):
    if quote_currency == MARKETS[market][0]:
        return D(1)
    if market == "UK" and quote_currency in ("GBp", "GBX"):
        return D("0.01")
    raise ValueError("Quote currency does not match the selected market account.")


def size_position(capital, risk_percent, signal_price, stop_loss):
    values = [D(v, positive=True) for v in (capital, risk_percent, signal_price, stop_loss)]
    if values[1] > 100:
        raise ValueError("Risk percent must be at most 100.")
    # Existing formula accepts Decimal arithmetic without changing scanner sizing.
    result = PositionSizeCalculator.calculate(*values)
    if result.quantity <= 0:
        raise ValueError("Calculated quantity is zero; review capital, risk and stop distance.")
    return result


def build_snapshot(opportunity, *, market, index_name, signal_time, timeframe,
                   quote_currency, capital, risk_percent, metadata, created_at, calendar):
    if market not in MARKETS or timeframe != "1d":
        raise ValueError("Paper trading requires a supported market and daily signal.")
    signal_time, created_at = utc(signal_time), utc(created_at)
    if signal_time > created_at:
        raise ValueError("The signal candle has not completed yet.")
    side = opportunity["signal"]
    if side not in ("BUY", "SELL") or D(opportunity["trade_quality_score"]) < 70:
        raise ValueError("Select a qualified BUY or SELL opportunity.")
    from autot.market_data.symbols import normalize_index_symbol
    exchange = {"US": "US", "UK": "LSE", "IN": "NSE"}[market]
    symbol = normalize_index_symbol(opportunity["symbol"], exchange)
    if symbol != opportunity["symbol"]:
        raise ValueError("Use the scanner's normalized Yahoo symbol.")
    scale = quote_scale(market, quote_currency)
    prices = [D(opportunity[k], positive=True) * scale for k in ("entry_price", "stop_loss", "take_profit")]
    # Reuse validation, but preserve the original reported ratio, never overwrite it.
    calculate_risk_reward_ratio(*prices, side)
    sizing = size_position(capital, risk_percent, prices[0], prices[1])
    snapshot = {
        "created_at": created_at.isoformat(), "symbol": symbol, "market": market,
        "index_name": index_name, "currency": MARKETS[market][0], "quote_currency": quote_currency,
        "quote_scale": str(scale), "side": side, "signal_time": signal_time.isoformat(),
        "signal_timeframe": timeframe, "signal_price": str(prices[0]),
        "stop_loss": str(prices[1]), "take_profit": str(prices[2]),
        "risk_reward_ratio": str(D(opportunity["risk_reward_ratio"], positive=True)),
        "confidence": str(D(opportunity["confidence"])), "agreement": str(D(opportunity["agreement"])),
        "market_regime": opportunity["market_regime"], "historical_score": str(D(opportunity["score"])),
        "trade_quality": str(D(opportunity["trade_quality_score"])),
        "benchmark_symbol": metadata.get("benchmark_symbol"), "universe_metadata": deepcopy(metadata),
        "original_opportunity": deepcopy(opportunity),
        "account_capital": str(D(capital)), "risk_percent": str(D(risk_percent)),
        "risk_amount": str(sizing.risk_amount), "risk_per_share": str(sizing.risk_per_share),
        "quantity": sizing.quantity, "intended_position_value": str(prices[0] * sizing.quantity),
        "eligible_at": calendar.next_open(market, max(signal_time, created_at)).isoformat(),
    }
    # Copy and check persistence compatibility now, before a confirmation transaction.
    return json.loads(json.dumps(snapshot, allow_nan=False, default=_json_scalar))


def initial_state():
    state = dict.fromkeys(STATE_FIELDS)
    state.update(status="PENDING_ENTRY", realized_pnl="0", unrealized_pnl="0", pnl_percent="0",
                 intrabar_sequence_ambiguous=False, review_required=False)
    return state


def close_at(trade, state, price, stamp, reason):
    pnl = calculate_pnl(D(state["fill_price"]), price, trade["quantity"], trade["side"])
    state.update(status="CLOSED", exit_price=str(price), closed_at=stamp.isoformat(),
                 current_price=str(price), realized_pnl=str(pnl), unrealized_pnl="0",
                 pnl_percent=str(pnl / (D(state["fill_price"]) * trade["quantity"]) * 100), exit_reason=reason)


def evaluate_bars(trade, batch, *, end, calendar):
    """Consume only a contiguous prefix of completed regular-session bars.

    Opening gaps execute at OPEN (including targets). Otherwise stop takes
    precedence over target. A manual close executes at the first bar OPEN at or
    after the request, never at a stale last price or before historical events.
    """
    state = {key: trade[key] for key in STATE_FIELDS}
    if state["status"] not in ("PENDING_ENTRY", "OPEN"):
        return state
    end = utc(end)
    if quote_scale(trade["market"], batch.quote_currency) != D(trade["quote_scale"]):
        raise HistoryUnavailable("Quote unit changed; review required.")
    start = utc(state["last_checked_at"]) + BAR if state["last_checked_at"] else utc(trade["eligible_at"])
    bars = {}
    for bar in batch.bars:
        if bar.timestamp in bars:
            raise HistoryUnavailable("Duplicate intraday timestamps; review required.")
        bars[bar.timestamp] = bar
    state.update(review_required=False, review_reason=None, data_source=batch.source)
    scale = D(trade["quote_scale"])
    stop, target = D(trade["stop_loss"]), D(trade["take_profit"])
    for stamp in calendar.completed_starts(trade["market"], start, end):
        if stamp not in bars:
            state.update(review_required=True, review_reason="Missing expected 5m bar or calendar exception; review required.")
            break
        bar = bars[stamp]
        opening, high, low, closing = (getattr(bar, k) * scale for k in ("open", "high", "low", "close"))
        if state["status"] == "PENDING_ENTRY":
            state.update(status="OPEN", fill_price=str(opening), filled_at=stamp.isoformat())
        buy = trade["side"] == "BUY"
        gap_stop = opening <= stop if buy else opening >= stop
        gap_target = opening >= target if buy else opening <= target
        hit_stop = low <= stop if buy else high >= stop
        hit_target = high >= target if buy else low <= target
        # Gaps are observable at open, so their order is known.
        if gap_stop or gap_target:
            close_at(trade, state, opening, stamp, "GAP_STOP" if gap_stop else "GAP_TARGET")
        elif state["manual_close_requested_at"] and stamp >= utc(state["manual_close_requested_at"]):
            close_at(trade, state, opening, stamp, "MANUAL_CLOSE")
        elif hit_stop or hit_target:
            if hit_stop and hit_target:
                state.update(intrabar_sequence_ambiguous=True,
                             ambiguity_reason="Both stop and target touched in one 5m bar; stop assumed first.")
            close_at(trade, state, stop if hit_stop else target, stamp, "STOP" if hit_stop else "TARGET")
        else:
            pnl = calculate_pnl(D(state["fill_price"]), closing, trade["quantity"], trade["side"])
            state.update(current_price=str(closing), unrealized_pnl=str(pnl),
                         pnl_percent=str(pnl / (D(state["fill_price"]) * trade["quantity"]) * 100))
        state["last_checked_at"] = stamp.isoformat()
        if state["status"] == "CLOSED":
            break
    return state


class PaperTradingService:
    def __init__(self, ledger, provider=None, calendar=None, clock=None):
        self.ledger, self.provider = ledger, provider
        self.calendar, self.clock = calendar or SessionCalendar(), clock or now_utc

    def existing_opportunity(self, opportunity, *, market, index_name, signal_time, timeframe, **_):
        return self.ledger.by_opportunity(dict(symbol=opportunity["symbol"], side=opportunity["signal"],
                                              market=market, index_name=index_name, signal_time=signal_time,
                                              signal_timeframe=timeframe))

    def confirm(self, confirmation_key, opportunity, *, create_another=False, **context):
        existing = self.ledger.by_confirmation(confirmation_key)
        if existing:
            return existing
        if not create_another:
            existing = self.existing_opportunity(opportunity, **context)
            if existing:
                return existing
        snapshot = build_snapshot(opportunity, created_at=self.clock(), calendar=self.calendar, **context)
        return self.ledger.confirm(confirmation_key, snapshot, initial_state(), create_another=create_another)

    def cancel(self, trade_id):
        trade = self.ledger.get(trade_id)
        if trade["status"] == "CANCELLED":
            return trade
        if trade["status"] != "PENDING_ENTRY" or utc(self.clock()) >= utc(trade["eligible_at"]):
            raise ValueError("Cancellation requires a pending trade before its eligible session. Update positions first.")
        state = {key: trade[key] for key in STATE_FIELDS}
        state.update(status="CANCELLED", cancelled_at=utc(self.clock()).isoformat())
        return self.ledger.update(trade, state)

    def request_manual_close(self, trade_id):
        trade = self.ledger.get(trade_id)
        if trade["status"] != "OPEN":
            raise ValueError("Only open positions can request manual close.")
        if trade["manual_close_requested_at"]:
            return trade
        state = {key: trade[key] for key in STATE_FIELDS}
        state["manual_close_requested_at"] = utc(self.clock()).isoformat()
        return self.ledger.update(trade, state)

    def update_positions(self):
        """One bounded pass; callable unchanged from a future scheduled worker."""
        updated = []
        for trade in self.ledger.all():
            if trade["status"] not in ("PENDING_ENTRY", "OPEN"):
                continue
            state = {key: trade[key] for key in STATE_FIELDS}
            end = utc(self.clock())
            start = utc(trade["last_checked_at"]) + BAR if trade["last_checked_at"] else utc(trade["eligible_at"])
            if next(self.calendar.completed_starts(trade["market"], start, end), None) is None:
                updated.append(trade)
                continue
            try:
                batch = self.provider.get_intraday_bars(trade["symbol"], start, end, interval="5m")
                state = evaluate_bars(trade, batch, end=end, calendar=self.calendar)
                updated.append(self.ledger.update(trade, state))
            except ConcurrentUpdate:
                updated.append(self.ledger.get(trade["trade_id"]))
            except Exception:
                LOGGER.exception("Paper monitoring failed for trade %s", trade["trade_id"])
                # On a failed transaction/provider call keep all previously committed execution state.
                state = {key: trade[key] for key in STATE_FIELDS}
                state.update(review_required=True,
                             review_reason="Intraday update could not be verified (history, quote units or capital). Review server logs; no execution invented.")
                try:
                    updated.append(self.ledger.update(trade, state))
                except ConcurrentUpdate:
                    updated.append(self.ledger.get(trade["trade_id"]))
        return updated
