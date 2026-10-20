"""Replaceable regular-session calendar; weekday fallback is NOT a holiday calendar.

Absent holiday/early-close overrides, a missing expected bar stops execution for
review. Never infer that an absent session was a holiday and skip its prices.
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


MARKETS = {
    "US": ("USD", "America/New_York", time(9, 30), time(16)),
    "UK": ("GBP", "Europe/London", time(8), time(16, 30)),
    "IN": ("INR", "Asia/Kolkata", time(9, 15), time(15, 30)),
}
BAR = timedelta(minutes=5)


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required.")
    return value.astimezone(timezone.utc)


class SessionCalendar:
    """Inject overrides {(market, date): None | (local_open, local_close)}.

    None closes a holiday; a time pair supports special sessions/early closes.
    A production scheduler should supply an authoritative calendar adapter.
    """

    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def bounds(self, market, day):
        _, zone, opening, closing = MARKETS[market]
        hours = self.overrides.get((market, day), (opening, closing) if day.weekday() < 5 else None)
        if hours is None:
            return None
        return tuple(datetime.combine(day, t, ZoneInfo(zone)).astimezone(timezone.utc) for t in hours)

    def next_open(self, market, after):
        after = utc(after)
        day = after.astimezone(ZoneInfo(MARKETS[market][1])).date()
        for _ in range(370):
            bounds = self.bounds(market, day)
            if bounds and bounds[0] > after:
                return bounds[0]
            day += timedelta(days=1)
        raise ValueError("No eligible session in calendar.")

    def completed_starts(self, market, start, end):
        start, end = utc(start), utc(end)
        day = start.astimezone(ZoneInfo(MARKETS[market][1])).date()
        last = end.astimezone(ZoneInfo(MARKETS[market][1])).date()
        while day <= last:
            bounds = self.bounds(market, day)
            if bounds:
                stamp, close = bounds
                while stamp + BAR <= close and stamp + BAR <= end:
                    if stamp >= start:
                        yield stamp
                    stamp += BAR
            day += timedelta(days=1)

    def signal_close(self, market, day):
        bounds = self.bounds(market, day)
        if bounds is None:
            raise ValueError("Signal date is not a known session.")
        return bounds[1]
