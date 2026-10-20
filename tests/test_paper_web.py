from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from autot.application import paper_display
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.service import PaperTradingService
from autot.settings.settings_loader import SettingsLoader
from tests.test_prospective_paper import opportunity, Provider, CREATED, OPEN, BAR, bar


APP = str(Path(__file__).resolve().parents[1] / "web_app.py")


def button(app, label):
    return next(b for b in app.button if b.label == label)


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SettingsLoader, "load", lambda: {"BACKTEST_PERIOD": "5y", "BACKTEST_INTERVAL": "1d", "TOP_N_STOCKS": "10"})
    now = [CREATED]
    provider = Provider()
    service = PaperTradingService(Ledger(), provider, clock=lambda: now[0])
    monkeypatch.setattr(paper_display, "paper_service", lambda: service)
    return service, provider, now


def saved_scan(market="US"):
    row = opportunity(symbol={"US": "AAPL", "UK": "AZN.L", "IN": "M&M.NS"}[market])
    return {"outputs": dict(symbols=[row["symbol"]], results=[row], ranked_results=[row],
                            top_results=[row], trade_opportunities=[row]),
            "settings": dict(universe="test", period="5y", interval="1d", top_n=10),
            "universe_metadata": {"benchmark_symbol": "SPY", "index_name": "Example"},
            "paper_signal_context": {row["symbol"]: {"eligible": True, "market": market,
                                                      "signal_time": "2026-10-12T20:00:00+00:00"}}}


def start_review(market="US"):
    app = AppTest.from_file(APP).run()
    app.session_state["scan"] = saved_scan(market)
    app.run()
    button(app, f"Paper Trade · {saved_scan(market)['outputs']['symbols'][0]}").click().run()
    return app


@pytest.mark.parametrize("market,currency", [("US", "USD"), ("UK", "GBP"), ("IN", "INR")])
def test_review_confirm_rerun_and_dashboard_restart(ui, market, currency):
    service, _, _ = ui
    app = start_review(market)
    assert not app.exception and len(service.ledger.all()) == 0
    app.checkbox[0].check()
    button(app, "Calculate quantity").click().run()
    button(app, "Confirm Paper Trade").click().run()
    assert not app.exception and not app.error
    assert any("PENDING ENTRY" in s.value for s in app.success)
    assert len(service.ledger.all()) == 1
    assert service.ledger.all()[0]["currency"] == currency
    app.run()
    assert len(service.ledger.all()) == 1
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value("Paper Trading").run()
    assert not app.exception
    assert any(s.value == "Pending Entries" for s in app.subheader)
    assert len(service.ledger.all()) == 1


def test_confirmation_requires_preview_and_acknowledgement(ui):
    service, _, _ = ui
    app = start_review()
    button(app, "Confirm Paper Trade").click().run()
    assert app.error and not service.ledger.all()
    app.checkbox[0].check()
    button(app, "Confirm Paper Trade").click().run()
    assert "Calculate quantity" in app.error[0].value and not service.ledger.all()


def test_completed_review_can_be_dismissed_to_select_different_opportunity(ui):
    service, _, _ = ui
    app = start_review()
    app.checkbox[0].check()
    button(app, "Calculate quantity").click().run()
    button(app, "Confirm Paper Trade").click().run()
    app.run()
    button(app, "Dismiss completed review").click().run()
    assert "paper_draft" not in app.session_state
    assert "paper_preview" not in app.session_state
    saved = saved_scan()
    saved["outputs"]["trade_opportunities"].append(opportunity(symbol="MSFT"))
    saved["paper_signal_context"]["MSFT"] = deepcopy(saved["paper_signal_context"]["AAPL"])
    app.session_state["scan"] = saved
    app.run()
    button(app, "Paper Trade · MSFT").click().run()
    assert app.session_state["paper_draft"]["row"]["symbol"] == "MSFT"
    app.checkbox[0].check()
    button(app, "Calculate quantity").click().run()
    button(app, "Confirm Paper Trade").click().run()
    assert not app.exception and not app.error
    assert {t["symbol"] for t in service.ledger.all()} == {"AAPL", "MSFT"}


def test_changed_inputs_require_new_preview(ui):
    service, _, _ = ui
    app = start_review()
    app.checkbox[0].check()
    button(app, "Calculate quantity").click().run()
    next(n for n in app.number_input if n.label == "Risk %").set_value(2.0)
    button(app, "Confirm Paper Trade").click().run()
    assert not service.ledger.all() and app.error


def test_dashboard_manual_update_is_explicit_and_persistent(ui):
    service, provider, now = ui
    app = start_review()
    app.checkbox[0].check()
    button(app, "Calculate quantity").click().run()
    button(app, "Confirm Paper Trade").click().run()
    assert not provider.calls
    app.radio[0].set_value("Paper Trading").run()
    assert not provider.calls
    provider.bars = [bar()]
    now[0] = OPEN + BAR
    button(app, "Update Paper Positions").click().run()
    assert not app.exception and service.ledger.all()[0]["status"] == "OPEN"
    count = len(provider.calls)
    app.run()
    assert len(provider.calls) == count
    button(app, "Request Manual Close").click().run()
    assert service.ledger.all()[0]["manual_close_requested_at"] is not None


def test_incomplete_daily_or_intraday_scan_cannot_confirm(ui):
    app = AppTest.from_file(APP).run()
    saved = saved_scan()
    saved["paper_signal_context"]["AAPL"]["eligible"] = False
    app.session_state["scan"] = saved
    app.run()
    assert button(app, "Paper Trade · AAPL").disabled
    saved = deepcopy(saved_scan())
    saved["settings"]["interval"] = "5m"
    app.session_state["scan"] = saved
    app.run()
    assert button(app, "Paper Trade · AAPL").disabled


def test_storage_errors_are_private(ui, monkeypatch):
    def fail():
        raise OSError("/private/operator/secret")
    monkeypatch.setattr(paper_display, "paper_service", fail)
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value("Paper Trading").run()
    assert not app.exception
    assert app.error and "/private" not in app.error[0].value


def test_reopen_refresh_and_explicit_addition(ui):
    service, _, _ = ui
    app = start_review()
    app.checkbox[0].check()
    button(app, "Calculate quantity").click().run()
    button(app, "Confirm Paper Trade").click().run()
    first = service.ledger.all()[0]
    reserved = service.ledger.summaries()["USD"]["reserved"]
    app.run()
    # A fresh browser loses its random draft key but still finds the same signal.
    app = start_review()
    assert first["trade_id"] in app.success[0].value
    assert not any(b.label == "Confirm Paper Trade" for b in app.button)
    assert len(service.ledger.all()) == 1
    assert service.ledger.summaries()["USD"]["reserved"] == reserved
    button(app, "Create another paper trade").click().run()
    assert len(service.ledger.all()) == 1  # explicit action opens review, not a trade
    app.checkbox[0].check()
    button(app, "Calculate quantity").click().run()
    button(app, "Confirm Paper Trade").click().run()
    app.run()
    assert not app.exception and len(service.ledger.all()) == 2
    assert service.ledger.summaries()["USD"]["reserved"] == 2 * reserved
    app = start_review()
    assert len(service.ledger.all()) == 2
    assert first["trade_id"] in app.success[0].value


@pytest.mark.parametrize("side,fill,stop,target,expected", [
    ("BUY", "100", "95", "110", "2"),
    ("SELL", "100", "105", "90", "2"),
    ("BUY", "100", "100", "110", None),
    ("SELL", "100", "100", "90", None),
    ("BUY", "94", "95", "110", None),
    ("SELL", "106", "105", "90", None),
    ("BUY", "111", "95", "110", None),
    ("SELL", "89", "105", "90", None),
    ("BUY", None, "95", "110", None),
    ("BUY", "NaN", "95", "110", None),
    ("BUY", "100", "95", "100", "0"),
])
def test_actual_fill_rr(side, fill, stop, target, expected):
    from decimal import Decimal
    trade = dict(status="OPEN", filled_at="2026-10-13T13:30:00+00:00", side=side,
                 fill_price=fill, stop_loss=stop, take_profit=target, risk_reward_ratio="3")
    before = deepcopy(trade)
    assert paper_display.actual_fill_rr(trade) == (Decimal(expected) if expected else None)
    assert trade == before
    trade["status"] = "PENDING_ENTRY"
    assert paper_display.actual_fill_rr(trade) is None
    trade["status"] = "OPEN"
    trade["filled_at"] = None
    assert paper_display.actual_fill_rr(trade) is None


def summary_fixture(service):
    """Representative recorded values in a temporary ledger, never the real account."""
    from tests.test_prospective_paper import confirm
    from autot.paper_trade.service import STATE_FIELDS
    seed = confirm(service)
    service.cancel(seed["trade_id"])
    result = []
    for status, symbol in [("OPEN", "MPC"), ("CLOSED", "MRNA"), ("PENDING_ENTRY", "PENDING"), ("CANCELLED", "MPC")]:
        snapshot = {k: v for k, v in seed.items() if k not in STATE_FIELDS}
        snapshot.update(symbol=symbol, quantity=1 if status == "PENDING_ENTRY" else 10 if symbol == "MPC" else 22,
                        signal_price="478" if symbol == "MPC" else "217",
                        stop_loss="468.51" if symbol == "MPC" else "210",
                        take_profit="497.19" if symbol == "MPC" else "226.7303943")
        snapshot["intended_position_value"] = str(paper_display.D(snapshot["signal_price"]) * snapshot["quantity"])
        state = {k: seed[k] for k in STATE_FIELDS}
        state.update(status=status)
        if status in ("OPEN", "CLOSED"):
            state.update(fill_price="478.00" if status == "OPEN" else "217.2700043",
                         filled_at=OPEN.isoformat(), last_checked_at=(OPEN + BAR).isoformat(),
                         current_price="473.7900085", pnl_percent="-0.88075135" if status == "OPEN" else "4.35445")
        if status == "OPEN":
            state.update(unrealized_pnl="-42.09991455", review_required=True, review_reason="Fixture review needed")
        if status == "CLOSED":
            state.update(exit_price="226.7303943", realized_pnl="208.1285803", exit_reason="TARGET",
                         closed_at=(OPEN + BAR).isoformat(), intrabar_sequence_ambiguous=True)
        if status == "CANCELLED":
            state["cancelled_at"] = CREATED.isoformat()
        result.append(service.ledger.confirm(status, snapshot, state, create_another=True))
    for market in ("UK", "IN"):
        confirm(service, key=market, market=market)
    return result


def test_summary_tables_details_restart_and_no_ledger_changes(ui):
    service, provider, _ = ui
    trades = summary_fixture(service)
    before = service.ledger.all()
    account_before = service.ledger.summaries()
    with service.ledger.connection() as db:
        persisted_before = list(db.iterdump())
    for _ in range(2):
        app = AppTest.from_file(APP).run()
        app.radio[0].set_value("Paper Trading").run()
        assert not app.exception and not app.error
        opened, closed, pending, cancelled = [d.value for d in app.dataframe]
        assert opened.iloc[0]["Entry"] == "478.00"
        assert opened.iloc[0]["Current"] == "473.7900"
        assert opened.iloc[0]["Unrealized P&L"] == "-$42.10"
        assert opened.iloc[0]["Return %"] == "-0.88%"
        assert opened.iloc[0]["Filled At"] == "2026-10-13 13:30:00 UTC"
        assert closed.iloc[0]["Realized P&L"] == "+$208.13"
        assert closed.iloc[0]["Return %"] == "+4.35%"
        assert closed.iloc[0]["Outcome"] == "PROFIT"
        assert closed.iloc[0]["Exit Reason"] == "TARGET"
        assert {"Signal Price", "Stop", "Target", "Qty", "Intended Value", "Eligible At", "Trade Quality", "Confidence"} <= set(pending.columns)
        assert {"Created At", "Cancelled At", "Trade ID"} <= set(cancelled.columns)
        assert trades[3]["trade_id"] in set(cancelled["Trade ID"])
        assert len(app.metric) == 15  # five independent metrics per currency; no total
        assert {m.value for m in app.metric if m.label == "Capital"} == {"$10,000.00", "£10,000.00", "₹10,000.00"}
        assert any(m.value == "+$208.13" for m in app.metric)
        assert any(m.value == "-$42.10" for m in app.metric)
        assert any("Closed winners: 1 · Closed losers: 0" in m.value for m in app.markdown)
        assert len(app.json) == len(before)
        for trade in before:
            assert any(e.label == f"Details / actions · {trade['symbol']} · {trade['trade_id']}" for e in app.expander)
        assert any("Signal Price:" in c.value and "Actual Fill Price:" in c.value for c in app.caption)
        assert any("Actual Fill R:R:" in c.value for c in app.caption)
        assert any(w.value == "Fixture review needed" for w in app.warning)
        assert any("Intrabar sequence ambiguous" in w.value for w in app.warning)
        assert button(app, "Request Manual Close")
        assert button(app, "Cancel pending entry")
        assert service.ledger.all() == before
        assert service.ledger.summaries() == account_before
        assert not provider.calls
    with service.ledger.connection() as db:
        assert list(db.iterdump()) == persisted_before
    # Scanner state and its rendered results survive dashboard navigation.
    app.session_state["scan"] = saved_scan()
    app.radio[0].set_value("Scanner").run()
    assert not app.exception and app.session_state["scan"] == saved_scan()
    assert button(app, "Paper Trade · AAPL")


@pytest.mark.parametrize("pnl,outcome", [("208.1285803", "PROFIT"), ("-0.001", "LOSS"), ("0", "BREAKEVEN")])
def test_closed_outcome_uses_unrounded_realized_pnl(ui, pnl, outcome):
    trade = summary_fixture(ui[0])[1]
    trade.update(realized_pnl=pnl, pnl_percent="99")
    assert paper_display.trade_summary(trade)["Outcome"] == outcome


def test_cancel_action_preserves_history(ui):
    from tests.test_prospective_paper import confirm
    service, _, _ = ui
    trade = confirm(service)
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value("Paper Trading").run()
    button(app, "Cancel pending entry").click().run()
    assert not app.exception
    assert service.ledger.get(trade["trade_id"])["status"] == "CANCELLED"
    assert app.dataframe[0].value.iloc[0]["Trade ID"] == trade["trade_id"]
