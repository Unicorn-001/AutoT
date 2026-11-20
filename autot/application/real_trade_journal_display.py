"""Manual real trade entry and comparison; no broker or execution integration."""
import logging
import sqlite3

import pandas as pd
import streamlit as st

from autot.real_trade_journal.service import (
    EXECUTION_FIELDS, SNAPSHOT_FIELDS, EXIT_REASONS, ORDER_TYPES, MATCH_STATUSES,
    RealTradeJournal, metrics, status,
)
from autot.real_trade_journal.scanner import opportunities, create_linked

LOGGER = logging.getLogger(__name__)


def execution_inputs(record=None):
    record = record or {}
    values = {}
    st.caption('Leave unknown values blank. Timestamps: ISO 8601 with timezone, e.g. 2026-11-19T14:30:00Z. Prices must use the same quote units as the AutoT plan. Gross P&L, fees and net P&L use P&L currency.')
    for field in EXECUTION_FIELDS:
        label = field.replace('_', ' ').capitalize()
        if field == 'exit_reason':
            options = ['', *EXIT_REASONS]
            values[field] = st.selectbox(label, options, index=options.index(record.get(field) or '')) or None
        elif field == 'real_order_type':
            options = ['', *ORDER_TYPES]
            values[field] = st.selectbox(label, options, index=options.index(record.get(field) or '')) or None
        elif field == 'execution_match_status':
            values[field] = st.selectbox(label, MATCH_STATUSES,
                index=MATCH_STATUSES.index(record.get(field) or 'UNKNOWN'),
                help='Classify manually. A LIMIT near the signal price does not necessarily reproduce NEXT_SESSION_OPEN.')
        elif field == 'actual_market_open_price':
            values[field] = st.text_input(label, value=record.get(field) or '',
                help='Manually verified next-session regular-market opening price, in the same quote units as the signal. Leave blank if unknown.') or None
        elif field in ('notes', 'execution_mismatch_reason'):
            values[field] = st.text_area(label, value=record.get(field) or '') or None
        else:
            values[field] = st.text_input(label, value=str(record.get(field) or '')) or None
    return values


def summary(record):
    derived = metrics(record)
    fields = ('symbol', 'side', 'broker', 'autot_entry_price', 'actual_entry_price',
              'autot_stop_loss', 'autot_take_profit', 'actual_exit_price', 'exit_reason',
              'pnl_currency', 'trade_quality')
    return {**{k: record[k] for k in fields}, 'net_pnl': derived['net_pnl'],
            'return_percent': derived['actual_return_percent'], 'return_basis': derived['return_basis']}


def render_real_trade_journal():
    st.header('Real Trade Journal')
    st.caption('Manually record broker results. Signal snapshots are immutable; this journal is separate from paper trading.')
    try:
        _render(RealTradeJournal())
    except (OSError, sqlite3.Error):
        LOGGER.exception('Real trade journal storage failed')
        st.error('Unable to access journal storage. Check AUTOT_DATA_DIR and server logs.')


def _render(journal):
    st.subheader('Add Real Trade')
    choices = opportunities()
    selected = st.selectbox('Link scanner opportunity', ['Manual entry'] + [row['key'] for row in choices],
                            format_func=lambda key: 'Manual entry' if key == 'Manual entry' else next(
                                f"{r['symbol']} · {r['side']} · {r['snapshot']['signal_timestamp'] or 'timestamp unavailable'} · {r['key']}"
                                for r in choices if r['key'] == key))
    choice = next((r for r in choices if r['key'] == selected), None)
    if choice:
        st.write({'symbol': choice['symbol'], 'side': choice['side'], **choice['snapshot']})
    with st.form('real_trade_create', clear_on_submit=False):
        if not choice:
            symbol = st.text_input('Symbol')
            side = st.selectbox('Side', ['BUY', 'SELL'])
            st.caption('Optional AutoT plan snapshot: enter known historical values once. These are locked after creation.')
            snapshot = {field: st.text_input(field.replace('_', ' ').capitalize()) or None for field in SNAPSHOT_FIELDS}
        broker = st.text_input('Broker')
        execution = execution_inputs()
        submitted = st.form_submit_button('Save Real Trade')
    if submitted:
        try:
            if choice:
                record = create_linked(journal, selected, broker=broker, **execution)
            else:
                record = journal.create(symbol=symbol, side=side, broker=broker, snapshot=snapshot, **execution)
            st.success(f"Saved real trade {record['journal_trade_id']}")
        except ValueError as error:
            st.error(str(error))
    records = journal.list()
    st.subheader('Open / Incomplete Real Trades')
    incomplete = [r for r in records if status(r) == 'OPEN / INCOMPLETE']
    st.caption('Includes drafts with unknown entry and trades with missing exit price or exit reason.')
    if incomplete:
        st.dataframe(pd.DataFrame([summary(r) for r in incomplete]), hide_index=True)
    for record in incomplete:
        if st.button(f"Record Exit · {record['symbol']} · {record['journal_trade_id']}"):
            st.session_state['real_trade_detail'] = record['journal_trade_id']
    st.subheader('Closed Real Trades')
    closed = [r for r in records if status(r) == 'CLOSED']
    if closed:
        st.dataframe(pd.DataFrame([summary(r) for r in closed]), hide_index=True)
    cancelled = [r for r in records if status(r) == 'CANCELLED']
    if cancelled:
        with st.expander('Cancelled Real Trades'):
            st.dataframe(pd.DataFrame([summary(r) for r in cancelled]), hide_index=True)
    if not records:
        st.info('No real trades recorded yet.')
        return
    st.subheader('Trade detail')
    ids = [r['journal_trade_id'] for r in records]
    if st.session_state.get('real_trade_detail') not in ids:
        st.session_state['real_trade_detail'] = ids[0]
    trade_id = st.selectbox('Trade', ids, key='real_trade_detail', format_func=lambda key: next(
        f"{r['symbol']} · {r['side']} · {r['broker']} · {status(r)} · {key}" for r in records if r['journal_trade_id'] == key))
    record = journal.get(trade_id)
    left, right = st.columns(2)
    with left:
        st.markdown('**AutoT Plan**')
        st.write({k: record[k] for k in SNAPSHOT_FIELDS})
    with right:
        st.markdown('**Real Execution**')
        st.write({k: record[k] for k in EXECUTION_FIELDS})
    st.write({'journal_trade_id': trade_id, 'created_at': record['created_at'], 'updated_at': record['updated_at']})
    st.write(metrics(record))
    render_execution_comparison(record)
    st.caption('Net P&L uses the manually supplied net value, or gross minus fees when both are known. Price-based returns are directional and exclude fees, FX and leverage. Stop/target distances are absolute percentages of planned entry.')
    with st.form(f'real_trade_edit_{trade_id}'):
        st.markdown('**Record Exit / Edit Real Execution**')
        values = execution_inputs(record)
        save = st.form_submit_button('Save Execution / Record Exit')
    if save:
        try:
            journal.update(trade_id, **values)
            st.rerun()
        except ValueError as error:
            st.error(str(error))
    if st.button('Cancel Real Trade', key=f'cancel_{trade_id}'):
        journal.cancel(trade_id)
        st.rerun()
    confirm = st.checkbox('Permanently delete this real journal entry', key=f'delete_confirm_{trade_id}')
    if st.button('Delete Real Trade', disabled=not confirm, key=f'delete_{trade_id}'):
        journal.delete(trade_id)
        st.rerun()


def render_execution_comparison(record):
    derived = metrics(record)
    st.subheader('Execution Comparison')
    st.caption('Manual classification; order type alone does not establish a match. Gap and slippage use the signal/reference price and the same quote units, for both BUY and SELL.')
    comparison = {
        'AutoT execution model': record.get('autot_execution_model'),
        'Real order type': record.get('real_order_type'),
        'Signal/reference price': record.get('autot_entry_price'),
        'Next-session open price': record.get('actual_market_open_price'),
        'Actual real fill': record.get('actual_entry_price'),
        'Gap from signal to open (absolute)': derived['gap_from_signal_to_open_absolute'],
        'Gap from signal to open (%)': derived['gap_from_signal_to_open_percent'],
        'Entry slippage (absolute)': derived['entry_slippage_absolute'],
        'Entry slippage (%)': derived['entry_slippage_percent'],
        'Execution match status': record.get('execution_match_status') or 'UNKNOWN',
        'Mismatch reason': record.get('execution_mismatch_reason'),
    }
    st.table(pd.DataFrame([
        {'Comparison': label, 'Value': value if value is not None else 'Unknown'}
        for label, value in comparison.items()
    ]))
