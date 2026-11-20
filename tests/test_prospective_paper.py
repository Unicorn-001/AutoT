"""Offline forward-execution scenarios with explicit clocks and supplied bars."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone, date, time
from decimal import Decimal
from decimal import Decimal as D
from concurrent.futures import ThreadPoolExecutor

import pytest

from autot.paper_trade.intraday import Bar, IntradayBatch, HistoryUnavailable
from autot.paper_trade.ledger import Ledger, ConcurrentUpdate
from autot.paper_trade.service import PaperTradingService, STATE_FIELDS, size_position
from autot.paper_trade.sessions import SessionCalendar, utc, BAR
from autot.portfolio.pnl import calculate_pnl
from autot.utils.financial_validation import decimal_value


CREATED = datetime(2026, 10, 12, 21, tzinfo=timezone.utc)
OPEN = datetime(2026, 10, 13, 13, 30, tzinfo=timezone.utc)


def opportunity(side="BUY", symbol="AAPL"):
    return dict(symbol=symbol, signal=side, entry_price=100, stop_loss=95 if side == "BUY" else 105,
                take_profit=110 if side == "BUY" else 90, risk_reward_ratio=2,
                confidence=80, agreement=75, market_regime="TREND", score=85, trade_quality_score=80)


class Provider:
    def __init__(self, bars=(), currency="USD"):
        self.bars, self.currency, self.calls = list(bars), currency, []

    def get_intraday_bars(self, symbol, start, end, interval="5m"):
        self.calls.append((symbol, start, end, interval))
        return IntradayBatch(self.bars, self.currency, "Offline fixture")


@pytest.fixture
def setup(tmp_path):
    provider = Provider()
    now = [CREATED]
    ledger = Ledger(tmp_path / "paper" / "ledger.db")
    service = PaperTradingService(ledger, provider, clock=lambda: now[0])
    return service, provider, now


def confirm(service, side="BUY", key="event", market="US", unit=None, create_another=False):
    symbols = {"US": "AAPL", "UK": "AZN.L", "IN": "M&M.NS"}
    currencies = {"US": "USD", "UK": "GBP", "IN": "INR"}
    return service.confirm(key, opportunity(side, symbols[market]), create_another=create_another, market=market,
                           index_name="Example", signal_time=CREATED - timedelta(hours=1),
                           timeframe="1d", quote_currency=unit or currencies[market],
                           capital=10000, risk_percent=1, metadata={"benchmark_symbol": "SPY", "source": "Fixture"})


def bar(o=100, h=104, l=96, c=101, stamp=OPEN):
    return Bar(stamp, o, h, l, c)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("market,currency", [("US", "USD"), ("UK", "GBP"), ("IN", "INR")])
def test_confirmation_snapshot_and_restart(setup, side, market, currency):
    service, _, _ = setup
    t = confirm(service, side, market=market)
    assert t["status"] == "PENDING_ENTRY"
    assert t["fill_price"] is None and t["filled_at"] is None
    assert t["currency"] == currency and t["side"] == side
    assert t["signal_price"] == "100" and t["quantity"] == 20
    assert t["intended_position_value"] == "2000"
    assert t["benchmark_symbol"] == "SPY" and t["universe_metadata"]["source"] == "Fixture"
    assert Ledger(service.ledger.path).get(t["trade_id"]) == t
    assert utc(t["eligible_at"]) > CREATED


def test_input_mutation_cannot_change_snapshot(setup):
    service, _, _ = setup
    row = opportunity()
    context = dict(market="US", index_name="Example", signal_time=CREATED - timedelta(hours=1),
                   timeframe="1d", quote_currency="USD", capital=10000, risk_percent=1,
                   metadata={"source": "Original"})
    t = service.confirm("one", row, **context)
    row["entry_price"] = 123
    context["metadata"]["source"] = "Changed"
    saved = service.ledger.get(t["trade_id"])
    assert saved["original_opportunity"]["entry_price"] == 100
    assert saved["universe_metadata"]["source"] == "Original"


def test_idempotency_across_restart_and_concurrent_confirmations(setup):
    service, _, _ = setup
    with ThreadPoolExecutor(max_workers=4) as pool:
        trades = list(pool.map(lambda _: confirm(service), range(8)))
    assert len({t["trade_id"] for t in trades}) == 1
    restarted = PaperTradingService(Ledger(service.ledger.path), clock=lambda: CREATED)
    assert confirm(restarted)["trade_id"] == trades[0]["trade_id"]
    assert confirm(restarted, key="explicit-new-action", create_another=True)["trade_id"] != trades[0]["trade_id"]
    assert len(service.ledger.all()) == 2


def test_next_session_fill_uses_open_and_preserves_signal(setup):
    service, provider, now = setup
    t = confirm(service)
    provider.bars = [bar(o=102, h=104, l=100, c=103)]
    now[0] = OPEN + BAR
    updated = service.update_positions()[0]
    assert updated["status"] == "OPEN" and updated["fill_price"] == "102"
    assert updated["signal_price"] == "100" and updated["filled_at"] == OPEN.isoformat()
    assert updated["unrealized_pnl"] == "14"  # fill 102 and risk-approved quantity 14
    assert updated["last_checked_at"] == OPEN.isoformat()
    for key in ("original_opportunity", "signal_time", "stop_loss", "take_profit", "trade_quality"):
        assert updated[key] == t[key]


def test_waits_for_next_session_and_bar_completion(setup):
    service, provider, now = setup
    confirm(service)
    for stamp in (CREATED, OPEN, OPEN + timedelta(minutes=4)):
        now[0] = stamp
        assert service.update_positions()[0]["status"] == "PENDING_ENTRY"
    assert provider.calls == []


def test_no_bars_remains_pending_and_flags_review(setup):
    service, _, now = setup
    confirm(service)
    now[0] = OPEN + BAR
    t = service.update_positions()[0]
    assert t["status"] == "PENDING_ENTRY" and t["fill_price"] is None
    assert t["review_required"] and t["last_checked_at"] is None


@pytest.mark.parametrize("side,ohlc,reason,price,pnl,ambiguous", [
    ("BUY", (100, 104, 94, 99), "STOP", "95", "-100", False),
    ("BUY", (100, 112, 96, 109), "TARGET", "110", "200", False),
    ("SELL", (100, 106, 96, 101), "STOP", "105", "-100", False),
    ("SELL", (100, 104, 89, 91), "TARGET", "90", "200", False),
    ("BUY", (100, 112, 94, 100), "STOP", "95", "-100", True),
    ("SELL", (100, 106, 89, 100), "STOP", "105", "-100", True),
])
def test_intrabar_exits_and_ambiguity(setup, side, ohlc, reason, price, pnl, ambiguous):
    service, provider, now = setup
    confirm(service, side)
    provider.bars = [bar(*ohlc)]
    now[0] = OPEN + BAR
    t = service.update_positions()[0]
    assert t["status"] == "CLOSED" and t["exit_reason"] == reason
    assert t["exit_price"] == price and t["realized_pnl"] == pnl
    assert t["unrealized_pnl"] == "0"
    assert t["intrabar_sequence_ambiguous"] == ambiguous
    if ambiguous:
        assert "stop assumed first" in t["ambiguity_reason"]
    assert Ledger(service.ledger.path).get(t["trade_id"])["intrabar_sequence_ambiguous"] == ambiguous


@pytest.mark.parametrize("side,second,reason,price,pnl", [
    ("BUY", (90, 94, 89, 92), "GAP_STOP", "90", "-200"),
    ("SELL", (112, 114, 111, 113), "GAP_STOP", "112", "-240"),
    ("BUY", (115, 116, 114, 115), "GAP_TARGET", "115", "300"),
    ("SELL", (85, 87, 84, 86), "GAP_TARGET", "85", "300"),
])
def test_open_gap_execution_at_actual_open(setup, side, second, reason, price, pnl):
    service, provider, now = setup
    confirm(service, side)
    provider.bars = [bar(), bar(*second, stamp=OPEN + BAR)]
    now[0] = OPEN + 2 * BAR
    t = service.update_positions()[0]
    assert t["exit_reason"] == reason and t["exit_price"] == price
    assert t["realized_pnl"] == pnl


@pytest.mark.parametrize("side,ohlc,reason", [
    ("BUY", (90, 94, 89, 92), "GAP_STOP"), ("SELL", (112, 114, 111, 113), "GAP_STOP"),
    ("BUY", (115, 116, 114, 115), "GAP_TARGET"), ("SELL", (85, 87, 84, 86), "GAP_TARGET"),
])
def test_entry_gap_can_fill_and_immediately_close_without_fictional_profit(setup, side, ohlc, reason):
    service, provider, now = setup
    confirm(service, side)
    provider.bars = [bar(*ohlc)]
    now[0] = OPEN + BAR
    t = service.update_positions()[0]
    if reason == 'GAP_STOP':
        assert t['status'] == 'CANCELLED' and t['fill_price'] is None
        assert t['fill_time_risk_check']['reason'] == 'INVALID_STOP_RELATIVE_TO_FILL'
    else:
        assert t["status"] == "CLOSED" and t["exit_reason"] == reason
        assert t["fill_price"] == t["exit_price"] == str(ohlc[0])
    assert t["realized_pnl"] == "0"


def test_catchup_chronological_resume_and_no_replay(setup):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(stamp=OPEN + BAR), bar(), bar(101, 112, 99, 109, OPEN + BAR * 2)]
    now[0] = OPEN + BAR
    t = service.update_positions()[0]
    assert t["status"] == "OPEN"
    restarted = PaperTradingService(Ledger(service.ledger.path), provider, clock=lambda: OPEN + BAR * 3)
    t = restarted.update_positions()[0]
    assert provider.calls[-1][1] == OPEN + BAR
    assert t["status"] == "CLOSED" and t["exit_price"] == "110"
    assert t["last_checked_at"] == (OPEN + BAR * 2).isoformat()
    count = len(provider.calls)
    assert restarted.update_positions() == [] and len(provider.calls) == count


def test_missing_middle_bar_stops_then_recovers(setup):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(), bar(100, 112, 96, 109, OPEN + 2 * BAR)]
    now[0] = OPEN + 3 * BAR
    t = service.update_positions()[0]
    assert t["status"] == "OPEN" and t["last_checked_at"] == OPEN.isoformat()
    assert t["review_required"]
    provider.bars.append(bar(stamp=OPEN + BAR))
    t = service.update_positions()[0]
    assert t["status"] == "CLOSED" and not t["review_required"]


def test_missing_first_bar_never_uses_later_price(setup):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(stamp=OPEN + BAR)]
    now[0] = OPEN + 2 * BAR
    t = service.update_positions()[0]
    assert t["status"] == "PENDING_ENTRY" and t["fill_price"] is None and t["review_required"]


def test_history_unavailable_safe_error_and_no_watermark_advance(setup):
    service, provider, now = setup
    confirm(service)
    provider.get_intraday_bars = lambda *a, **k: (_ for _ in ()).throw(HistoryUnavailable("/private/sensitive"))
    now[0] = OPEN + BAR
    t = service.update_positions()[0]
    assert t["review_required"] and t["last_checked_at"] is None
    assert "/private" not in t["review_reason"]


def test_cancel_pending_releases_reservation(setup):
    service, _, _ = setup
    t = confirm(service)
    assert service.ledger.summaries()["USD"]["reserved"] == 2000
    assert service.cancel(t["trade_id"])["status"] == "CANCELLED"
    assert service.cancel(t["trade_id"])["status"] == "CANCELLED"
    assert service.ledger.summaries()["USD"]["reserved"] == 0


def test_late_cancel_cannot_erase_unprocessed_fill(setup):
    service, _, now = setup
    t = confirm(service)
    now[0] = OPEN + BAR
    with pytest.raises(ValueError, match="Update positions"):
        service.cancel(t["trade_id"])


def test_manual_close_uses_future_open_not_stale_mark(setup):
    service, provider, now = setup
    t = confirm(service)
    provider.bars = [bar()]
    now[0] = OPEN + BAR
    service.update_positions()
    service.request_manual_close(t["trade_id"])
    provider.bars.append(bar(103, 104, 100, 102, OPEN + BAR))
    now[0] = OPEN + 2 * BAR
    t = service.update_positions()[0]
    assert t["exit_reason"] == "MANUAL_CLOSE" and t["exit_price"] == "103"
    assert t["realized_pnl"] == "60"


def test_historical_stop_precedes_manual_request(setup):
    service, provider, now = setup
    t = confirm(service)
    provider.bars = [bar()]
    now[0] = OPEN + BAR
    service.update_positions()
    now[0] = OPEN + 3 * BAR
    service.request_manual_close(t["trade_id"])
    provider.bars.append(bar(100, 102, 94, 96, OPEN + BAR))
    assert service.update_positions()[0]["exit_reason"] == "STOP"


def test_currency_summaries_and_capital_reservations(setup):
    service, _, _ = setup
    for market in ("US", "UK", "IN"):
        confirm(service, key=market, market=market)
    summaries = service.ledger.summaries()
    assert set(summaries) == {"USD", "GBP", "INR"}
    assert all(s["available"] == 8000 for s in summaries.values())
    for i in range(4):
        confirm(service, key=f"US-{i}", create_another=True)
    with pytest.raises(ValueError, match="Insufficient"):
        confirm(service, key="US-overbooked", create_another=True)


def test_pence_to_gbp_for_sizing_fill_and_pnl(setup):
    service, provider, now = setup
    t = confirm(service, market="UK", unit="GBp")
    assert D(t["signal_price"]) == 1 and t["quantity"] == 2000
    assert t["original_opportunity"]["entry_price"] == 100
    opening = utc(t["eligible_at"])
    provider.bars, provider.currency = [bar(stamp=opening)], "GBp"
    now[0] = opening + BAR
    t = service.update_positions()[0]
    assert D(t["fill_price"]) == 1 and D(t["unrealized_pnl"]) == 20


@pytest.mark.parametrize("currency", ["GBP", "INR", "GBp"])
def test_quote_unit_mismatch_prevents_fill(setup, currency):
    service, provider, now = setup
    confirm(service)
    provider.currency, provider.bars = currency, [bar()]
    now[0] = OPEN + BAR
    t = service.update_positions()[0]
    assert t["status"] == "PENDING_ENTRY" and t["review_required"]


def test_gap_cannot_overdraw_account(setup):
    service, provider, now = setup
    for i in range(5):
        confirm(service, key=str(i), create_another=True)
    provider.bars = [bar(102, 104, 100, 103)]
    now[0] = OPEN + BAR
    updated = service.update_positions()
    assert all(t['status'] == 'OPEN' and t['quantity'] == 14 for t in updated)
    assert service.ledger.summaries()['USD']['available'] == 2860


def test_revision_conflict_cannot_overwrite_trade(setup):
    service, _, _ = setup
    t = confirm(service)
    service.cancel(t["trade_id"])
    with pytest.raises(ConcurrentUpdate):
        service.ledger.update(t, {k: t[k] for k in STATE_FIELDS})


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", None, True, "garbage"])
def test_financial_boundary_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        decimal_value(value)


@pytest.mark.parametrize("values", [(0, 1, 100, 95), (10000, 0, 100, 95),
    (10000, 101, 100, 95), (10000, 1, 100, 100), (1, 1, 100, 95)])
def test_sizing_rejects_invalid_or_zero_quantity(values):
    with pytest.raises(ValueError):
        size_position(*values)


@pytest.mark.parametrize("side,exit_price,expected", [("BUY", 110, 100), ("BUY", 90, -100),
    ("SELL", 90, 100), ("SELL", 110, -100)])
def test_shared_pnl(side, exit_price, expected):
    assert calculate_pnl(Decimal(100), Decimal(exit_price), 10, side) == expected


def test_sizing_reuses_existing_calculator():
    from autot.position.position_size_calculator import PositionSizeCalculator
    actual = size_position(10000, 1, 100, 95)
    original = PositionSizeCalculator.calculate(10000, 1, 100, 95)
    assert actual.quantity == original.quantity == 20
    assert actual.position_value == original.position_value


@pytest.mark.parametrize("market,summer,winter", [("US", 13, 14), ("UK", 7, 8), ("IN", 3, 3)])
def test_calendar_timezones_dst_and_weekends(market, summer, winter):
    calendar = SessionCalendar()
    assert calendar.bounds(market, date(2026, 7, 6))[0].hour == summer
    assert calendar.bounds(market, date(2026, 12, 7))[0].hour == winter
    assert calendar.bounds(market, date(2026, 10, 17)) is None
    friday = datetime(2026, 10, 16, 23, tzinfo=timezone.utc)
    assert calendar.next_open(market, friday).date() == date(2026, 10, 19)


def test_calendar_explicit_holiday_and_early_close():
    calendar = SessionCalendar({("US", date(2026, 10, 13)): None,
                                ("US", date(2026, 10, 14)): (time(9, 30), time(13))})
    assert calendar.next_open("US", CREATED).date() == date(2026, 10, 14)
    assert calendar.bounds("US", date(2026, 10, 14))[1].hour == 17


def test_missing_holiday_not_silently_skipped(setup):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(stamp=OPEN + timedelta(days=1))]
    now[0] = OPEN + timedelta(days=1, minutes=5)
    assert service.update_positions()[0]["status"] == "PENDING_ENTRY"


@pytest.mark.parametrize("stamp", [datetime(2026, 10, 13), "2026-10-13T13:30:00"])
def test_naive_timestamps_rejected(stamp):
    with pytest.raises(ValueError):
        utc(stamp)


@pytest.mark.parametrize("values", [(100, 99, 95, 100), (100, 110, 101, 105), (0, 5, 0, 1), (100, "NaN", 95, 100)])
def test_invalid_ohlc_rejected(values):
    with pytest.raises(ValueError):
        bar(*values)


def test_duplicate_timestamps_not_used(setup):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(), bar()]
    now[0] = OPEN + BAR
    t = service.update_positions()[0]
    assert t["status"] == "PENDING_ENTRY" and t["review_required"]


def test_default_ledger_respects_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOT_DATA_DIR", str(tmp_path))
    assert Ledger().path == tmp_path / "paper_trading" / "ledger.sqlite3"


@pytest.mark.parametrize("change", ["intraday", "future", "hold", "quality", "geometry", "currency", "nan"])
def test_invalid_confirmation_creates_no_trade_or_account(setup, change):
    service, _, _ = setup
    row = opportunity()
    context = dict(market="US", index_name="Example", signal_time=CREATED - timedelta(hours=1),
                   timeframe="1d", quote_currency="USD", capital=10000, risk_percent=1, metadata={})
    if change == "intraday": context["timeframe"] = "5m"
    if change == "future": context["signal_time"] = CREATED + timedelta(hours=1)
    if change == "hold": row["signal"] = "HOLD"
    if change == "quality": row["trade_quality_score"] = 69
    if change == "geometry": row["stop_loss"] = 105
    if change == "currency": context["quote_currency"] = "GBP"
    if change == "nan": row["entry_price"] = float("nan")
    with pytest.raises(ValueError):
        service.confirm("invalid", row, **context)
    assert service.ledger.all() == [] and service.ledger.summaries() == {}


def test_overnight_catchup_processes_offline_exit_in_order(setup):
    service, provider, now = setup
    t = confirm(service)
    end_of_first_day = datetime(2026, 10, 13, 20, tzinfo=timezone.utc)
    provider.bars = [bar(stamp=s) for s in service.calendar.completed_starts("US", OPEN, end_of_first_day)]
    next_open = service.calendar.next_open("US", end_of_first_day)
    provider.bars.append(bar(90, 94, 89, 92, next_open))
    provider.bars.reverse()
    now[0] = next_open + BAR
    t = service.update_positions()[0]
    assert t["status"] == "CLOSED" and t["exit_reason"] == "GAP_STOP"
    assert t["closed_at"] == next_open.isoformat() and t["realized_pnl"] == "-200"


def test_account_capital_cannot_change_on_later_confirmation(setup):
    service, _, _ = setup
    confirm(service)
    with pytest.raises(ValueError, match="existing paper account"):
        service.confirm("new", opportunity(), create_another=True, market="US", index_name="Example",
                        signal_time=CREATED - timedelta(hours=1), timeframe="1d", quote_currency="USD",
                        capital=20000, risk_percent=1, metadata={})
    assert len(service.ledger.all()) == 1


def test_closed_trade_realized_pnl_updates_currency_capital(setup):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(100, 112, 96, 110)]
    now[0] = OPEN + BAR
    service.update_positions()
    summary = service.ledger.summaries()["USD"]
    assert summary["available"] == 10200 and summary["reserved"] == 0
    assert summary["realized_pnl"] == 200 and summary["unrealized_pnl"] == 0


def test_concurrent_monitor_update_and_cancel_do_not_resurrect_trade(setup):
    service, provider, now = setup
    t = confirm(service)
    service.cancel(t["trade_id"])
    state = {k: t[k] for k in STATE_FIELDS}
    state.update(status="OPEN", fill_price="100", filled_at=OPEN.isoformat())
    with pytest.raises(ConcurrentUpdate):
        service.ledger.update(t, state)
    assert service.ledger.get(t["trade_id"])["status"] == "CANCELLED"


def mpc_confirm(service, key, **changes):
    row = opportunity(symbol="MPC")
    row.update(entry_price=478.07000732421875, stop_loss=468.50860717773435,
               take_profit=497.1928076171875)
    context = dict(market="US", index_name="S&P 500", signal_time="2026-10-16T20:00:00+00:00",
                   timeframe="1d", quote_currency="USD", capital=10000, risk_percent=1,
                   metadata={"benchmark_symbol": "SPY"})
    context.update(changes)
    return service.confirm(key, row, **context)


def mpc_service(path):
    return PaperTradingService(Ledger(path), clock=lambda: utc("2026-10-17T17:00:00+00:00"))


def test_mpc_repeated_confirmation_new_keys_and_restart(tmp_path):
    path = tmp_path / "ledger.db"
    service = mpc_service(path)
    first = mpc_confirm(service, "first-review")
    assert first["quantity"] == 10
    assert mpc_confirm(service, "first-review")["trade_id"] == first["trade_id"]
    assert mpc_confirm(service, "reopened-review")["trade_id"] == first["trade_id"]
    restarted = mpc_service(path)
    # Changed risk/source metadata and equivalent timezone representation are not new signals.
    assert mpc_confirm(restarted, "refresh", risk_percent=2, metadata={"source": "refreshed"},
                       signal_time="2026-10-16T16:00:00-04:00")["trade_id"] == first["trade_id"]
    assert len(restarted.ledger.all()) == 1
    summary = restarted.ledger.summaries()["USD"]
    assert summary["reserved"] == D("4780.70007324218750")
    assert summary["available"] == D("5219.29992675781250")


def test_mpc_concurrent_distinct_confirmation_keys(tmp_path):
    from threading import Barrier
    path = tmp_path / "ledger.db"
    services = [mpc_service(path) for _ in range(8)]
    barrier = Barrier(8)
    def submit(i):
        barrier.wait()
        return mpc_confirm(services[i], f"review-{i}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        trades = list(pool.map(submit, range(8)))
    assert len({t["trade_id"] for t in trades}) == 1
    assert len(services[0].ledger.all()) == 1
    assert services[0].ledger.summaries()["USD"]["reserved"] == D("4780.70007324218750")


def test_mpc_different_signal_time_is_new_opportunity(tmp_path):
    service = mpc_service(tmp_path / "ledger.db")
    first = mpc_confirm(service, "one")
    second = mpc_confirm(service, "two", signal_time="2026-10-15T20:00:00+00:00")
    assert first["opportunity_id"] != second["opportunity_id"]
    assert len(service.ledger.all()) == 2


def test_mpc_explicit_addition_is_idempotent_and_cannot_overbook(tmp_path):
    service = mpc_service(tmp_path / "ledger.db")
    first = mpc_confirm(service, "one")
    second = mpc_confirm(service, "explicit-add", create_another=True)
    assert first["trade_id"] != second["trade_id"]
    assert first["opportunity_id"] == second["opportunity_id"]
    restarted = mpc_service(service.ledger.path)
    assert mpc_confirm(restarted, "explicit-add", create_another=True)["trade_id"] == second["trade_id"]
    assert mpc_confirm(restarted, "ordinary-review")["trade_id"] == first["trade_id"]
    with pytest.raises(ValueError, match="Insufficient"):
        mpc_confirm(restarted, "explicit-third", create_another=True)
    assert len(service.ledger.all()) == 2
    assert service.ledger.summaries()["USD"]["reserved"] == D("9561.40014648437500")


@pytest.mark.parametrize("status", ["OPEN", "CLOSED", "CANCELLED"])
def test_default_reuses_live_and_terminal_history(setup, status):
    service, provider, now = setup
    first = confirm(service)
    if status == "CANCELLED":
        service.cancel(first["trade_id"])
    else:
        provider.bars = [bar(h=112 if status == "CLOSED" else 104)]
        now[0] = OPEN + BAR
        service.update_positions()
    before = service.ledger.summaries()
    assert confirm(service, key="new-review")["status"] == status
    assert service.ledger.summaries() == before
    assert len(service.ledger.all()) == 1
    assert confirm(service, key="explicit-add", create_another=True)["trade_id"] != first["trade_id"]


def test_database_unique_intent_and_rollback(setup):
    import sqlite3
    service, _, _ = setup
    confirm(service)
    before = service.ledger.summaries()
    with pytest.raises(sqlite3.IntegrityError):
        with service.ledger.connection() as db:
            db.execute("INSERT INTO trades SELECT 'other-id', 'other-key', snapshot, state, revision, "
                       "opportunity_id, intent_key FROM trades")
    assert len(service.ledger.all()) == 1
    assert service.ledger.summaries() == before


def test_legacy_duplicate_migration_preserves_records_and_reservations(tmp_path):
    import json
    import sqlite3
    service = mpc_service(tmp_path / "seed.db")
    first = mpc_confirm(service, "first")
    path = tmp_path / "legacy.db"
    with service.ledger.connection() as db:
        row = db.execute("SELECT snapshot, state FROM trades").fetchone()
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE accounts (currency TEXT PRIMARY KEY, capital TEXT NOT NULL);"
                         "CREATE TABLE trades (trade_id TEXT PRIMARY KEY, confirmation_key TEXT NOT NULL UNIQUE,"
                         "snapshot TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0);")
        db.execute("INSERT INTO accounts VALUES ('USD', '10000')")
        for i in range(2):
            db.execute("INSERT INTO trades VALUES (?, ?, ?, ?, 0)", (f"legacy-{i}", f"key-{i}", *row))
    migrated = mpc_service(path)
    assert len(migrated.ledger.all()) == 2
    assert mpc_confirm(migrated, "fresh-review")["trade_id"] == "legacy-0"
    assert migrated.ledger.summaries()["USD"]["reserved"] == D("9561.40014648437500")
    for trade in migrated.ledger.all():
        assert trade["original_opportunity"] == first["original_opportunity"]
        assert trade["revision"] == 0
    migrated.cancel("legacy-1")
    assert migrated.ledger.summaries()["USD"]["reserved"] == D("4780.70007324218750")
    assert len(mpc_service(path).ledger.all()) == 2
