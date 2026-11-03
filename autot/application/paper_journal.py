"""Summary-first, read-only performance journal and durable audit timelines."""

import pandas as pd
import streamlit as st

from autot.paper_trade.performance import PerformanceService


def number(value, suffix=''):
    return '—' if value is None else f'{value:,.2f}{suffix}'


def duration(seconds):
    if seconds is None:
        return '—'
    minutes = int(seconds / 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    return f'{days}d {hours}h {minutes}m'


def journal_row(entry):
    from autot.application.paper_display import format_money, format_price, format_timestamp
    t = entry['trade']
    return {'Symbol': t['symbol'], 'Side': t['side'], 'Currency': t['currency'],
            'Signal Time': format_timestamp(t['signal_time']), 'Signal Price': format_price(t['signal_price']),
            'Fill Price': format_price(t['fill_price']), 'Exit Price': format_price(t['exit_price']),
            'Outcome': entry['outcome'],
            'P&L': format_money(entry['pnl'], t['currency'], signed=True) if entry['pnl'] is not None else '—',
            'Return %': number(entry['return_percent']), 'Signal R:R': number(entry['signal_rr']),
            'Actual R:R': number(entry['actual_rr']), 'Entry Slippage %': number(entry['entry_slippage_percent']),
            'Holding Duration': duration(entry['holding_seconds']), 'Exit Reason': t['exit_reason'] or '—',
            'Market Regime': t['market_regime'], 'Trade Quality': t['trade_quality'],
            'Historical Score': t['historical_score'],
            'MFE': number(entry['mfe']), 'MFE %': number(entry['mfe_percent']),
            'MAE': number(entry['mae']), 'MAE %': number(entry['mae_percent']),
            'Excursion Evidence': entry['excursion_note']}


def timeline_rows(events):
    from autot.application.paper_display import format_price, format_timestamp
    return [{'Timestamp': format_timestamp(e['event_time']), 'Recorded At': format_timestamp(e['recorded_at']),
             'Event': e['event_type'], 'Price': format_price(e['price']),
             'Status transition': f"{e['status_before'] or '—'} → {e['status_after']}",
             'Reason': e['reason'] or '—', 'Run ID': e['update_run_id'] or '—'} for e in events]


def render_performance_journal(ledger):
    from autot.application.paper_display import format_money, format_timestamp
    st.subheader('Performance / Journal')
    if not st.toggle('Show Performance / Journal', key='paper_show_journal'):
        return
    st.warning('Small sample — insufficient for strategy conclusions.')
    st.caption('Closed trades only in performance summaries. Gross simulated results, separated by currency; no FX total.')
    mode = st.selectbox('Performance mode', ['FORWARD_TEST', 'RESEARCH', 'PRE_SETTINGS_BASELINE'],
                        help='Forward view includes existing pre-settings trades without inventing their mode. Research is always separate.')
    report = PerformanceService(ledger).report(mode=mode)
    with st.expander('Filter / group performance'):
        fields = ['strategy_profile_id', 'strategy_profile_version', 'strategy_config_hash', 'market', 'index_name', 'side', 'market_regime']
        field = st.selectbox('Segment field', fields)
        values = list(dict.fromkeys(e['trade'].get(field) for e in report['journal']))
        choice = st.selectbox('Segment value', range(len(values)+1),
                              format_func=lambda i: 'All' if i == 0 else str(values[i-1]) if values[i-1] is not None else 'Unknown / pre-settings')
        report = PerformanceService(ledger).report(mode=mode, filters={field: values[choice-1]} if choice else None, group_by=field)
        st.dataframe([{'Segment': str(k) if k is not None else 'Unknown / pre-settings', 'Currency': c,
                       'Completed trades': m['completed_trades'], 'Net realized P&L': str(m['net_realized_pnl'])}
                      for k, v in report['segments'].items() for c, m in v.items()], hide_index=True)
    for currency, metrics in report['performance'].items():
        st.markdown(f'**{currency}**')
        counts = [('Completed trades', 'completed_trades'), ('Winners', 'winners'), ('Losers', 'losers'),
                  ('Breakeven', 'breakeven'), ('Win rate', 'win_rate')]
        for column, (label, key) in zip(st.columns(5), counts):
            column.metric(label, number(metrics[key], '%') if key == 'win_rate' else metrics[key])
        money = [('Gross profit', 'gross_profit'), ('Gross loss', 'gross_loss'), ('Net P&L', 'net_realized_pnl'),
                 ('Average win', 'average_win'), ('Average loss', 'average_loss')]
        for column, (label, key) in zip(st.columns(5), money):
            value = metrics[key]
            column.metric(label, format_money(value, currency, signed=True) if value is not None else '—')
        st.write(f"Profit factor: {number(metrics['profit_factor'])}" +
                 (f" ({metrics['profit_factor_note']})" if metrics['profit_factor_note'] else ''))
        st.write(f"Average return: {number(metrics['average_return_percent'], '%')} · "
                 f"Average holding duration: {duration(metrics['average_holding_seconds'])}")
        st.write(f"Average signal R:R: {number(metrics['average_signal_rr'])} · "
                 f"Average actual-fill R:R: {number(metrics['average_actual_rr'])} · "
                 f"Average entry slippage: {number(metrics['average_entry_slippage_percent'], '%')}")
        for label, key in [('Best trade', 'best_trade'), ('Worst trade', 'worst_trade')]:
            entry = metrics[key]
            st.write(f"{label}: " + (f"{entry['trade']['symbol']} · {format_money(entry['pnl'], currency, signed=True)} · "
                                    f"{entry['trade_id']}" if entry else '—'))
        rows = [e for e in report['journal'] if e['currency'] == currency]
        st.dataframe(pd.DataFrame([journal_row(e) for e in rows]), hide_index=True)
    st.caption('Slippage: positive is adverse for either side. MFE/MAE are positive price movements in account currency per share and percentages of fill. Intrabar exit excursions are known-movement lower bounds. Holding durations use bar-start execution timestamps.')
    entries = {e['trade_id']: e for e in report['journal']}
    if entries:
        selected = st.selectbox('Journal trade', list(entries),
                                format_func=lambda key: f"{entries[key]['trade']['symbol']} · {entries[key]['trade']['status']} · {key}")
        st.markdown('**Event timeline**')
        st.dataframe(pd.DataFrame(timeline_rows(report['events'].get(selected, []))), hide_index=True)
        st.caption(entries[selected]['excursion_note'])
        with st.expander('Raw trade snapshot JSON'):
            st.json(entries[selected]['trade'])
        with st.expander('Raw audit event JSON'):
            st.json(report['events'].get(selected, []))
    else:
        st.caption('No paper trades yet.')
    st.markdown('**Update run history**')
    runs = ledger.recent_runs()
    if runs:
        labels = {'status': 'Status', 'trades_considered': 'Trades considered', 'trades_opened': 'Trades opened',
                  'trades_closed': 'Trades closed', 'trades_updated': 'Trades updated', 'bars_processed': 'Bars processed',
                  'warnings_count': 'Warnings', 'errors_count': 'Errors', 'provider': 'Provider'}
        st.dataframe(pd.DataFrame([dict({'Run ID': r['run_id'], 'Started': format_timestamp(r['started_at']),
                                        'Completed': format_timestamp(r['completed_at'])},
                                       **{label: r[key] for key, label in labels.items()}) for r in runs]), hide_index=True)
        st.caption('Latest 50 runs. RUNNING without completion may indicate an interrupted process; it is never presented as SUCCESS.')
    else:
        st.caption('No update runs recorded.')
