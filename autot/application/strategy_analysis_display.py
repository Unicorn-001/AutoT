"""Read-only paper evidence, with explicit mode/profile selection and CSV exports."""
import streamlit as st

from autot.strategy_analysis.models import ExperimentProposal
from autot.strategy_analysis.service import StrategyAnalysisService, export_csv, sample_label
from autot.strategy_analysis.snapshot import contributions


def display_rows(rows):
    return [{key: ('UNAVAILABLE' if value is None else ' / '.join(str(x) if x is not None else 'UNAVAILABLE' for x in value)
                  if isinstance(value, tuple) else str(value) if not isinstance(value, (str, int, bool)) else value)
             for key, value in row.items()} for row in rows]


def render_trade_features(entry):
    trade = entry['trade']
    st.markdown('**Signal and profile**')
    st.dataframe(display_rows([{key: trade.get(key) for key in (
        'symbol', 'market', 'index_name', 'side', 'signal_time', 'market_regime', 'confidence', 'agreement',
        'trade_quality', 'historical_score', 'risk_reward_ratio', 'strategy_profile_id', 'strategy_profile_name',
        'strategy_profile_version', 'strategy_config_hash')}]), hide_index=True)
    votes = contributions(trade)
    if votes:
        st.dataframe(display_rows([c.model_dump() for c in votes]), hide_index=True)
    else:
        st.info('Strategy signals and weights: UNAVAILABLE. No historical values have been reconstructed.')
    st.caption('Disabled strategies were not evaluated; missing signals are not HOLD. Legacy stored votes may lack weights.')
    admission = trade.get('portfolio_risk_decision')
    if admission:
        st.write(f"Portfolio-risk admission: {admission['decision']} · position {admission['proposed_position_percent']}% · "
                 f"planned risk {admission['proposed_trade_risk_percent']}%")
        with st.expander('Stored portfolio-risk admission'):
            st.write(' '.join(admission['reasons']))
            st.dataframe(display_rows([{k: admission.get(k) for k in (
                'decision', 'proposed_position_percent', 'proposed_trade_risk_percent',
                'proposed_total_open_risk', 'available_capital', 'currency')}]), hide_index=True)
    else:
        st.caption('Portfolio-risk admission: UNAVAILABLE (pre-portfolio-risk trade).')
    st.dataframe(display_rows([{key: entry.get(key) for key in (
        'currency', 'pnl', 'return_percent', 'holding_seconds', 'mfe', 'mae', 'mfe_percent', 'mae_percent', 'excursion_note')}
        | {key: trade.get(key) for key in ('signal_price', 'fill_price', 'filled_at', 'exit_price', 'closed_at', 'exit_reason')}]), hide_index=True)


def render_strategy_analysis(ledger):
    st.subheader('Strategy Analysis')
    if not st.toggle('Show Strategy Analysis', key='paper_show_strategy_analysis'):
        return
    mode = st.selectbox('Strategy analysis mode', ['FORWARD_TEST', 'RESEARCH', 'UNKNOWN_LEGACY'])
    st.markdown('**FORWARD PAPER STRATEGY ANALYSIS**' if mode == 'FORWARD_TEST' else f'**{mode} STRATEGY ANALYSIS**')
    service = StrategyAnalysisService(ledger)
    initial = service.report(mode=mode)
    profiles = initial['available_profiles']
    choice = st.selectbox('Analysis profile / version / configuration', range(len(profiles) + 1),
                          format_func=lambda i: 'All profiles — explicit comparison' if i == 0 else ' / '.join(str(x) for x in profiles[i-1]))
    minimum = st.number_input('Minimum trades for automatic combinations', min_value=1, value=20, step=1)
    report = service.report(mode=mode, profile=profiles[choice-1] if choice else None, minimum_sample=minimum)
    count = report['completeness']['closed_trades']
    st.write(f'Closed trades: {count} · Sample status: {sample_label(count)}')
    st.caption('Sample labels are descriptive, not tests of statistical significance. Results are gross simulated outcomes; no causation or automatic optimisation.')
    if report['mixed_profiles']:
        st.warning('Multiple profile versions/configurations selected explicitly. Pooled cohorts may be confounded; use a single profile for baseline review.')
    if mode == 'UNKNOWN_LEGACY':
        st.warning('Legacy trades have no stored mode. They are excluded from FORWARD_TEST and RESEARCH statistics.')
    if not count:
        st.info('No closed trades in this selection. Missing evidence remains UNAVAILABLE.')
    for row in report['summary']:
        st.markdown(f"**{row['currency']} · {row['trade_count']} closed trades · {row['sample_status']}**")
        for col, key, label in zip(st.columns(4), ('net_pnl', 'win_rate', 'profit_factor', 'expectancy'),
                                   ('Net P&L', 'Win rate %', 'Profit factor', 'Expectancy / trade')):
            value = row[key]
            col.metric(label, 'UNAVAILABLE' if value is None else f'{value:,.2f}')
    st.caption('Currencies remain separate. Profit factor is UNAVAILABLE without losses. Realized-close drawdown excludes open positions and intratrade movement. MFE/MAE percentages use only supported audit evidence and may be lower bounds.')
    with st.expander('Outcome metrics and data completeness', expanded=not count):
        st.dataframe(display_rows(report['summary']), hide_index=True)
        st.dataframe([{'Evidence': k, 'Trades': v} for k, v in report['completeness'].items()], hide_index=True)
    labels = {'side': 'BUY vs SELL', 'regime': 'By market regime', 'strategy': 'By strategy',
              'strategy_regime': 'Strategy × regime', 'combinations': 'Strategy combinations',
              'confidence': 'Confidence bands', 'agreement': 'Agreement bands', 'trade_quality': 'Trade quality bands',
              'historical_score': 'Historical-score bands', 'planned_risk_percent': 'Planned risk %',
              'position_percent': 'Position %', 'actual_fill_risk_percent': 'Actual fill risk %', 'profile': 'Profile comparison'}
    for section, label in labels.items():
        with st.expander(label):
            rows = report['sections'][section]
            if rows:
                st.dataframe(display_rows(rows), hide_index=True)
            else:
                st.caption('No qualifying evidence for this selection/sample threshold.')
            if section in report['bins']:
                st.caption('Bands include their lower bound and exclude the upper bound; final band is open-ended. UNAVAILABLE is separate.')
            if section == 'combinations':
                ids = sorted({c.strategy_id for r in report['journal'] for c in r['contributions']})
                requested = st.multiselect('Specific aligned combination (2–10 strategies)', ids)
                if len(requested) >= 2:
                    query = service.report(mode=mode, profile=profiles[choice-1] if choice else None, requested_combination=requested)
                    st.dataframe(display_rows(query['sections']['combinations']), hide_index=True)
                    st.caption('Specific queries show small samples; empty results mean zero qualifying closed trades.')
            st.download_button(f'Export {label} CSV', export_csv(report, section), f'strategy_analysis_{section}.csv', 'text/csv', key=f'analysis_export_{section}')
    with st.expander('Candidate observations'):
        st.caption('Cohorts overlap the baseline; many comparisons invite selection bias. Results describe admitted trades only. The profitability of rejected or filtered-out signals is UNAVAILABLE without prospective counterfactual tracking.')
        st.dataframe(display_rows(report['observations']), hide_index=True)
    with st.expander('Experiment proposal — human review'):
        st.caption('Download a DRAFT idea to track outside the app. This never creates, activates or promotes a strategy profile. Research requires a separate explicit decision.')
        hypothesis = st.text_input('Hypothesis')
        change = st.text_input('Candidate change to test')
        reason = st.text_input('Reason for testing')
        required = st.number_input('Minimum required sample', min_value=1, value=50)
        if hypothesis and change and reason and choice:
            proposal = ExperimentProposal(hypothesis=hypothesis, baseline_profile=str(profiles[choice-1]),
                candidate_change=change, reason=reason, supporting_sample=count,
                metrics={r['currency'] + '_expectancy': str(r['expectancy']) for r in report['summary']},
                minimum_required_sample=required)
            st.download_button('Download DRAFT proposal', proposal.model_dump_json(indent=2), 'experiment_proposal.json', 'application/json')
        else:
            st.caption('Select a single baseline profile and complete the three fields to export a draft.')
    st.download_button('Export trade-level analysis CSV', export_csv(report), 'strategy_analysis_trades.csv', 'text/csv')
    with st.expander('Closed-trade evidence'):
        entries = {r['trade_id']: r for r in report['journal']}
        if entries:
            selected = st.selectbox('Analysis trade', list(entries), format_func=lambda k: f"{entries[k]['trade']['symbol']} · {k}")
            render_trade_features(entries[selected])
            with st.expander('Raw analysis trade snapshot'):
                st.json(entries[selected]['trade'])
