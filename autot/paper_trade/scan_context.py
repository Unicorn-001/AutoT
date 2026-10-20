"""Observe scanner input dates without filtering data or changing analysis results."""

from functools import wraps
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from autot.paper_trade.sessions import MARKETS, SessionCalendar


def symbol_market(symbol):
    if symbol.endswith(".NS"):
        return "IN"
    if symbol.endswith(".L"):
        return "UK"
    return "US"


def observe_analysis(analyse_func, contexts, *, interval, market=None, clock=None):
    @wraps(analyse_func)
    def analyse(symbol, data, benchmark, tracker):
        # Missing/invalid provenance must only disable paper eligibility, never a scan.
        context = {"eligible": False, "reason": "A completed daily candle with a known date is required."}
        try:
            chosen_market = market or symbol_market(symbol)
            if interval == "1d" and isinstance(data.index, pd.DatetimeIndex) and len(data.index):
                stamp = data.index[-1]
                if stamp.tzinfo is not None:
                    stamp = stamp.tz_convert(ZoneInfo(MARKETS[chosen_market][1]))
                close = SessionCalendar().signal_close(chosen_market, stamp.date())
                observed = (clock or (lambda: datetime.now(timezone.utc)))()
                context.update(market=chosen_market, signal_time=close.isoformat(),
                               observed_at=observed.isoformat(), eligible=close <= observed)
        except (AttributeError, ValueError, TypeError, KeyError):
            pass
        contexts[symbol] = context
        return analyse_func(symbol, data, benchmark, tracker)
    return analyse
