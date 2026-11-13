"""Paper UI only. Durable state and execution live in reusable services."""

from copy import deepcopy
from datetime import datetime, timezone
import logging
from uuid import uuid4

import pandas as pd
import streamlit as st

from autot.paper_trade.intraday import YahooIntradayProvider
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.performance import actual_fill_rr
from autot.application.paper_journal import render_performance_journal
from autot.paper_trade.service import PaperTradingService, quote_scale, size_position
from autot.paper_trade.sessions import MARKETS
from autot.utils.financial_validation import decimal_value as D
from autot.settings.models import SettingsState
from autot.settings.store import SettingsStore
from autot.portfolio_risk.models import PortfolioRiskRejected


LOGGER = logging.getLogger(__name__)


def paper_service():
    return PaperTradingService(Ledger(), YahooIntradayProvider())


def render_opportunity_actions(saved):
    opportunities = saved["outputs"]["trade_opportunities"]
    if not opportunities:
        return
    with st.expander("Paper trade a daily opportunity"):
        st.caption("Confirmation creates a pending entry for a future session, not a fill at the signal price.")
        for index, row in enumerate(opportunities):
            context = saved.get("paper_signal_context", {}).get(row["symbol"], {})
            ready = context.get("eligible", False) and saved["settings"]["interval"] == "1d"
            if st.button(f"Paper Trade · {row['symbol']}", key=f"paper_select_{index}", disabled=not ready):
                # Keep one event token through double clicks/reruns until explicit New action.
                if "paper_draft" not in st.session_state:
                    st.session_state["paper_draft"] = {
                        "key": str(uuid4()), "row": deepcopy(row), "context": deepcopy(context),
                        "metadata": deepcopy(saved.get("universe_metadata", {})),
                        "settings_state": deepcopy(saved.get("settings_state")),
                    }
            if not ready:
                st.caption(f"{row['symbol']}: paper confirmation needs a new scan using a completed 1d candle.")
        render_review()


def render_review():
    draft = st.session_state.get("paper_draft")
    if not draft:
        return
    try:
        service = paper_service()
        state_data = draft.get('settings_state')
        settings_state = SettingsState.model_validate(state_data) if state_data else None
        active = settings_state or SettingsStore().load()
        risk_config = active.settings.risk
        row, context, metadata = draft["row"], draft["context"], draft["metadata"]
        existing = service.ledger.by_confirmation(draft["key"])
        if not existing and not draft.get("create_another", False):
            existing = service.existing_opportunity(
                row, market=context["market"], index_name=metadata.get("index_name") or "Custom upload",
                signal_time=context["signal_time"], timeframe="1d", mode=active.settings.general.mode)
        if existing:
            st.success(f"Paper trade {existing['trade_id']} · Status: {existing['status'].replace('_', ' ')}")
            if st.button("Create another paper trade", key="paper_new"):
                st.session_state["paper_draft"] = dict(draft, key=str(uuid4()), create_another=True)
                st.session_state.pop("paper_preview", None)
                st.rerun()
            if st.button("Dismiss completed review", key="paper_dismiss"):
                del st.session_state["paper_draft"]
                st.session_state.pop("paper_preview", None)
                st.rerun()
            return
        row, context, metadata = draft["row"], draft["context"], draft["metadata"]
        market = context["market"]
        currency = MARKETS[market][0]
        st.subheader("Review Paper Trade")
        st.write(f"{row['symbol']} · {market} · {metadata.get('index_name') or 'Custom upload'} · {currency} · {row['signal']}")
        st.write(f"Daily candle completed: {context['signal_time']}")
        st.write({"Signal/reference price (quote units)": row["entry_price"],
                  "Stop": row["stop_loss"], "Target": row["take_profit"],
                  "Risk/reward": row["risk_reward_ratio"], "Confidence": row["confidence"],
                  "Agreement": row["agreement"], "Trade quality": row["trade_quality_score"],
                  "Historical score": row["score"], "Market regime": row["market_regime"]})
        account = service.ledger.summaries().get(currency)
        st.caption(f'Profile: {active.profile.profile_name} v{active.profile.profile_version} · {active.settings.general.mode} · {active.profile.configuration_hash}')
        st.caption('Capital defaults apply only to a NEW account. Existing persisted ledger capital is used unchanged.')
        with st.form("paper_confirmation"):
            unit = st.selectbox("Scanner quote unit", ["GBp", "GBP"] if market == "UK" else [currency],
                                help="UK Yahoo listings commonly use pence (GBp). Verify the quote unit; monitoring checks provider units before any execution.")
            capital = st.number_input(f"Account capital ({currency})", min_value=1.0,
                                      value=float(account["capital"]) if account else active.settings.paper_trading.capital(currency),
                                      disabled=account is not None, key=f"paper_capital_{currency}")
            risk = st.number_input("Risk %", min_value=0.01, max_value=100.0, value=risk_config.risk_per_trade_percent, disabled=settings_state is not None, key=f"paper_risk_{active.profile.configuration_hash}" if settings_state else "paper_risk")
            acknowledged = st.checkbox("I verified the quote unit and understand this is simulated trading.")
            preview = st.form_submit_button("Calculate quantity")
            confirmed = st.form_submit_button("Confirm Paper Trade",
                disabled=st.session_state.get("paper_rejected_draft") == draft["key"])
        scale = quote_scale(market, unit)
        sizing = size_position(capital, risk, D(row["entry_price"]) * scale, D(row["stop_loss"]) * scale)
        st.write(f"Quantity: {sizing.quantity} · Estimated value: {sizing.position_value} {currency} · "
                 f"Risk budget: {sizing.risk_amount} {currency} · Stop distance: {sizing.risk_per_share} {currency}")
        st.caption("Whole shares; sizing uses the reference price. The actual fill may change notional and risk. Shorts reserve full notional; no leverage or borrow model.")
        # A preview ties the acknowledgement to the exact submitted sizing inputs.
        parameters = (capital, risk, unit)
        admission_context = dict(market=market, index_name=metadata.get("index_name") or "Custom upload",
                                 signal_time=context["signal_time"], timeframe="1d", quote_currency=unit,
                                 capital=capital, risk_percent=risk, metadata=metadata, settings_state=settings_state)
        if preview:
            st.session_state["paper_preview"] = (draft["key"], parameters)
        if preview or (not confirmed and st.session_state.get("paper_preview") == (draft["key"], parameters)):
            result = service.preview_admission(row, **admission_context)
            rejected_key = None if result.allowed else draft['key']
            if st.session_state.get('paper_rejected_draft') != rejected_key:
                st.session_state['paper_rejected_draft'] = rejected_key
                st.rerun()
            render_admission_decision(result)
        if confirmed:
            if risk_config.manual_confirmation_required and not acknowledged:
                st.error("Verify the quote unit and acknowledge simulated execution first.")
            elif st.session_state.get("paper_preview") != (draft["key"], parameters):
                st.error("Calculate quantity with these inputs before confirming.")
            else:
                trade = service.confirm(
                    draft["key"], row, create_another=draft.get("create_another", False), **admission_context,
                )
                st.success(f"Paper trade {trade['trade_id']} · Status: {trade['status'].replace('_', ' ')}")
        if st.button("Discard review", key="paper_discard"):
            del st.session_state["paper_draft"]
            st.rerun()
    except PortfolioRiskRejected as error:
        render_admission_decision(error.result, final=True)
    except ValueError as error:
        st.error(str(error))
    except Exception:
        LOGGER.exception("Paper review failed")
        st.error("Unable to load or save paper trading. Check storage and server logs.")


def format_money(value, currency, *, signed=False):
    number = D(value)
    sign = "-" if number < 0 else "+" if signed and number > 0 else ""
    unit = {"USD": "$", "GBP": "£", "INR": "₹"}.get(currency, currency + " ")
    return f"{sign}{unit}{abs(number):,.2f}"


def format_price(value):
    if value is None:
        return "—"
    number = D(value)
    return f"{number:,.2f}" if number == number.quantize(D("0.01")) else f"{number:,.4f}"


def format_timestamp(value):
    if not value:
        return "—"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def trade_summary(trade):
    """Build a presentation row from stored values, without recalculating P&L."""
    t = trade
    row = {"Symbol": t["symbol"], "Side": t["side"]}
    status = t["status"]
    if status == "OPEN":
        row["Status"] = status
    if status in ("OPEN", "CLOSED"):
        row["Entry"] = format_price(t["fill_price"])
        row["Current" if status == "OPEN" else "Exit"] = format_price(t["current_price"] if status == "OPEN" else t["exit_price"])
    else:
        row["Signal Price"] = format_price(t["signal_price"])
    if status in ("OPEN", "PENDING_ENTRY"):
        row.update(Stop=format_price(t["stop_loss"]), Target=format_price(t["take_profit"]))
    row["Qty"] = t["quantity"]
    if status in ("OPEN", "CLOSED"):
        pnl = t["unrealized_pnl" if status == "OPEN" else "realized_pnl"]
        row["Unrealized P&L" if status == "OPEN" else "Realized P&L"] = format_money(pnl, t["currency"], signed=True)
        row["Return %"] = f"{D(t['pnl_percent']):+.2f}%"
        if status == "CLOSED":
            row["Outcome"] = "PROFIT" if D(pnl) > 0 else "LOSS" if D(pnl) < 0 else "BREAKEVEN"
            row["Exit Reason"] = t["exit_reason"]
        row["Filled At"] = format_timestamp(t["filled_at"])
        row["Last Checked" if status == "OPEN" else "Closed At"] = format_timestamp(t["last_checked_at"] if status == "OPEN" else t["closed_at"])
    elif status == "PENDING_ENTRY":
        row.update({"Intended Value": format_money(t["intended_position_value"], t["currency"]),
                    "Eligible At": format_timestamp(t["eligible_at"]),
                    "Trade Quality": str(t["trade_quality"]), "Confidence": str(t["confidence"])})
    else:
        row.update({"Created At": format_timestamp(t["created_at"]),
                    "Cancelled At": format_timestamp(t["cancelled_at"]), "Trade ID": t["trade_id"]})
    row["Currency"] = t["currency"]
    return row


def pnl_style(value):
    if str(value).startswith("+") or value == "PROFIT":
        return "color: #15803d; font-weight: bold"
    if str(value).startswith("-") or value == "LOSS":
        return "color: #b91c1c; font-weight: bold"
    return ""


def render_accounts(summaries):
    st.subheader("Accounts by currency")
    for currency, account in summaries.items():
        st.markdown(f"**{currency}**")
        for column, (label, key) in zip(st.columns(5), [
            ("Capital", "capital"), ("Realized P&L", "realized_pnl"),
            ("Unrealized P&L", "unrealized_pnl"), ("Reserved notional", "reserved"),
            ("Available capital", "available"),
        ]):
            column.metric(label, format_money(account[key], currency, signed="pnl" in key))
    st.caption("Available = capital + realized P&L − reserved notional. Unrealized P&L is shown separately. No FX or mixed-currency total.")


def render_admission_decision(result, *, final=False):
    st.subheader(f"Portfolio Risk · {result.decision}")
    for reason in result.reasons:
        (st.success if result.allowed else st.error)(reason)
    for warning in result.warnings:
        st.warning(warning)
    currency = result.currency
    st.write(f"Proposed position: {format_money(result.proposed_position_value, currency)} "
             f"({result.proposed_position_percent:.2f}% of base capital) · "
             f"Planned trade risk: {format_money(result.proposed_trade_risk, currency)} "
             f"({result.proposed_trade_risk_percent:.2f}%)")
    st.write(f"Account capital / equity: {format_money(result.account_capital, currency)} / "
             f"{format_money(result.account_equity, currency)} · "
             f"Position slots used: {result.current_open_positions} · Trades today: {result.new_trades_today}")
    st.write(f"Available capital: {format_money(result.available_capital, currency)} · "
             f"Post-trade reserved: {format_money(result.post_trade_reserved_notional, currency)} · "
             f"Post-trade planned risk: {format_money(result.proposed_total_open_risk, currency)}")
    st.caption('Confirmation rejected; no trade or reservation was created.' if final else
               'Advisory preview for a new exposure. Confirmation checks the current portfolio again; this preview reserves no capital.')
    with st.expander('Portfolio admission details'):
        st.json(result.model_dump(mode='json'))


def render_portfolio_exposure(service):
    store = SettingsStore()
    state = store.load()
    if store.warning:
        st.warning(store.warning)
        return
    views = service.ledger.portfolio_exposures(state, when=service.clock())
    if not views:
        return
    st.subheader('Portfolio Risk / Exposure')
    st.caption(f'Limits shown for active profile {state.profile.profile_name} v{state.profile.profile_version} · '
               f'{state.settings.general.mode}. Delayed scan confirmations use their captured profile.')
    st.caption('Reservations, position slots and planned risk are shared across modes within each currency. '
               'Percentage limits use account base capital. Equity below is capital + realized P&L; unrealized P&L is separate.')
    for view in views:
        currency, risk = view.currency, view.risk_settings
        st.markdown(f'**{currency} PORTFOLIO RISK**')
        metrics = [
            ('Account equity', format_money(view.account_equity, currency)),
            ('Available capital', format_money(view.available_capital, currency)),
            ('Reserved notional', format_money(view.existing_reserved_notional, currency)),
            ('Pending / Open', f'{view.pending_positions} / {view.open_positions}'),
            ('Planned portfolio risk', format_money(view.current_open_risk, currency)),
            ('Portfolio risk % (base capital)', f'{view.current_open_risk_percent:.2f}%'),
            ('Configured portfolio risk max', f'{risk.maximum_total_portfolio_risk_percent:g}% / '
             f'{format_money(view.maximum_total_portfolio_risk, currency)}' + ('' if risk.enforce_portfolio_risk_limit else ' (not enforced)')),
            ('Fill-adjusted stop risk', format_money(view.fill_adjusted_open_risk, currency)),
            ('Largest position', format_money(view.largest_position, currency)),
            ('Largest position % (base capital)', f'{view.largest_position_percent:.2f}%'),
            ('Remaining position slots', str(view.remaining_position_slots) if risk.enforce_positions_limit else 'Not enforced'),
            ('Position limit', str(view.maximum_positions) + ('' if risk.enforce_positions_limit else ' (not enforced)')),
            ('New trades today', str(view.new_trades_today)),
            ('Daily trade limit', str(view.maximum_new_trades_per_day) + ('' if risk.enforce_daily_trade_limit else ' (not enforced)')),
        ]
        for start in range(0, len(metrics), 4):
            for column, (label, value) in zip(st.columns(4), metrics[start:start+4]):
                column.metric(label, value)
        st.caption(f'Daily count: {view.mode} · {view.local_date} · {view.market_timezone}; '
                   'includes cancelled confirmations. Pending entries consume position slots and reserve full notional.')
        for warning in view.warnings:
            st.warning(warning)


def render_trade_counts(trades, summaries):
    st.subheader("Paper Trade Summary")
    st.write(" · ".join(f"{label}: {sum(t['status'] == status for t in trades)}" for status, label in
                        [("PENDING_ENTRY", "Pending"), ("OPEN", "Open"), ("CLOSED", "Closed"), ("CANCELLED", "Cancelled")]))
    closed = [t for t in trades if t["status"] == "CLOSED"]
    st.write(f"Closed winners: {sum(D(t['realized_pnl']) > 0 for t in closed)} · "
             f"Closed losers: {sum(D(t['realized_pnl']) < 0 for t in closed)}")
    st.caption("Realized P&L by currency")
    for currency, account in summaries.items():
        st.write(f"{currency} {format_money(account['realized_pnl'], currency, signed=True)}")


def render_execution_comparison(trade):
    st.caption(f"Signal Price: {format_price(trade['signal_price'])} {trade['currency']} · "
               f"Actual Fill Price: {format_price(trade['fill_price'])} {trade['currency']} · "
               f"Signal R:R: {trade['risk_reward_ratio']}")
    ratio = actual_fill_rr(trade)
    if ratio is not None:
        st.caption(f"Actual Fill R:R: {ratio:.2f} · Informational only")
    if trade.get("intrabar_sequence_ambiguous"):
        st.warning("Intrabar sequence ambiguous. See the recorded execution details below.")


def render_paper_dashboard():
    st.header("Paper Trading")
    st.caption("Prospective simulation · daily signals · completed 5-minute execution bars · no real broker")
    st.info("The V1 calendar uses local weekday sessions. Holidays, shortened sessions and missing bars require review; no prices are invented.")
    try:
        service = paper_service()
        render_monitor_status(service.ledger)
        render_notifications(service.ledger)
        render_review()
        if st.button("Update Paper Positions", key="paper_update"):
            with st.spinner("Processing available completed 5-minute bars…"):
                updated = service.update_positions()
            run = service.ledger.get_run(service.last_update_run_id)
            message = f"Checked {len(updated)} pending/open paper trades. Run status: {run['status']}."
            if run['status'] in ('SUCCESS', 'NO_WORK'):
                st.success(message)
            else:
                st.warning(message + ' Inspect review details and update run history.')
        summaries = service.ledger.summaries()
        if summaries:
            render_accounts(summaries)
        render_portfolio_exposure(service)
        trades = service.ledger.all()
        render_trade_counts(trades, summaries)
        for status, title in [("OPEN", "Open Positions"), ("CLOSED", "Closed Trades"),
                              ("PENDING_ENTRY", "Pending Entries"), ("CANCELLED", "Cancelled Trades")]:
            st.subheader(title)
            rows = [t for t in trades if t["status"] == status]
            if not rows:
                st.caption("None")
                continue
            frame = pd.DataFrame([trade_summary(t) for t in rows])
            colored = [c for c in ("Unrealized P&L", "Realized P&L", "Return %", "Outcome") if c in frame]
            st.dataframe(frame.style.map(pnl_style, subset=colored) if colored else frame, hide_index=True)
            for trade in rows:
                with st.expander(f"Details / actions · {trade['symbol']} · {trade['trade_id']}"):
                    render_execution_comparison(trade)
                    st.json(trade)
                    if trade["review_required"]:
                        st.warning(trade["review_reason"])
                    if status == "PENDING_ENTRY" and st.button("Cancel pending entry", key=f"cancel_{trade['trade_id']}"):
                        service.cancel(trade["trade_id"])
                        st.rerun()
                    if status == "OPEN":
                        st.caption("Manual close requests execute at the next available completed bar's open after the request. Catch-up stop/target events take precedence.")
                        if trade["manual_close_requested_at"]:
                            st.write(f"Manual close requested: {trade['manual_close_requested_at']}")
                        elif st.button("Request Manual Close", key=f"close_{trade['trade_id']}"):
                            service.request_manual_close(trade["trade_id"])
                            st.rerun()
        with st.expander('Rejected paper confirmations'):
            st.caption('Latest 100 rejected confirmation attempts; previews are not recorded. No trades or performance results are created.')
            for rejected in service.ledger.rejections():
                st.write(f'{rejected.recorded_at} · {rejected.proposal.symbol} · '
                         f'{rejected.decision.currency} · {rejected.decision.mode}')
                st.write(' '.join(rejected.decision.reasons))
                st.json(rejected.model_dump(mode='json'))
        render_performance_journal(service.ledger)
        from autot.application.strategy_analysis_display import render_strategy_analysis
        render_strategy_analysis(service.ledger)
    except ValueError as error:
        st.error(str(error))
    except Exception:
        LOGGER.exception("Paper dashboard failed")
        st.error("Paper trading is unavailable. Check AUTOT_DATA_DIR and server logs.")


def render_monitor_status(ledger):
    from autot.paper_monitor import read_status
    with st.expander('Paper Monitor'):
        try:
            status = read_status(ledger.path)
        except (OSError, RuntimeError):
            st.warning('Monitor status unavailable; check settings storage and server logs.')
            return
        st.write(f"Configured: {'ON' if status['configured'] else 'OFF'} · "
                 f"Process: {status['process_status']} · Interval: {status['interval_minutes']} minutes")
        st.write(f"Active trades: {status['pending'] + status['open']} · "
                 f"Pending: {status['pending']} · Open: {status['open']}")
        st.write(f"Last heartbeat: {status['heartbeat'] or 'Never'} · Phase: {status['phase'] or 'Unknown'}")
        st.write(f"Next expected run: {status['next_expected_run'] or 'Unavailable'}")
        for key, label in [('last_run', 'Last scheduled run'), ('last_success', 'Last success'),
                           ('last_failure', 'Last failure / partial run')]:
            run = status[key]
            st.write(f"{label}: " + (f"{run['started_at']} · {run['status']}" if run else 'Never'))
        st.caption('Start externally from the AutoT directory using the same AUTOT_DATA_DIR. '
                   'Enable and save Monitoring settings first. Refresh this page for current status. '
                   'ACTIVE means the process holds the lock; a stale heartbeat may indicate a slow or stuck update.')
        st.code('python -m autot.paper_monitor\npython -m autot.paper_monitor --once\npython -m autot.paper_monitor --status', language='bash')


def render_notifications(ledger):
    from autot.notifications import configuration, read_status
    with st.expander('Notifications'):
        try:
            config = configuration()
            status = read_status(ledger.path)
            st.caption(f"{'Enabled' if config.notifications_enabled else 'Disabled'} · Channel: {config.notification_channel}")
            st.write(f"Pending notifications: {status['pending']}")
            for label, key, stamp in [('Last delivered', 'last_delivered', 'delivered_at'),
                                      ('Last failed', 'last_failed', 'last_failure_at')]:
                item = status[key]
                st.write(f"{label}: {item[stamp] if item else 'None'}")
            if status['history']:
                st.table([{k: row[k] for k in ('event_type', 'created_at', 'symbol', 'delivery_status',
                                              'attempt_count', 'error_category')}
                          for row in status['history']])
            else:
                st.caption('No notification history yet.')
        except Exception:
            st.warning('Notification status unavailable.')
