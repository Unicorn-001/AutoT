"""Manual, advisory assessment of a linked persisted scanner opportunity."""
import sqlite3
import streamlit as st

from autot.market_context.assessment import REASONS
from autot.market_context.store import MarketContextStore, assess_opportunity


def render_market_context(saved, index, row):
    with st.expander(f"Pre-Trade Market Context · {row['symbol']} · {row['signal']}"):
        run_id = saved.get('scan_run_id')
        if not run_id:
            st.info('A persisted scanner run is required for a market-context assessment.')
            return
        st.caption(f'Scanner run: {run_id} · Opportunity: {index} · Advisory only; no trades are placed.')
        key = f'market_context_{run_id}_{index}'
        price = st.text_input('Current / executable price', key=key + '_price',
                              help='Enter a fresh quote manually. No live price is fetched.')
        try:
            store = MarketContextStore()
            if st.button('Assess current price', key=key + '_assess'):
                assess_opportunity(run_id, index, price, store=store, source='MANUAL')
            history = store.history(run_id, str(index))
        except (ValueError, OSError, sqlite3.Error):
            st.error('Unable to load or save market context. Check scanner results and data storage.')
            return
        if not history:
            st.caption('No assessment yet. Enter the current price and assess explicitly.')
            return
        a = history[0]
        st.caption(f"Last assessment: {a['assessed_at']} · Source: {a['source']} · Saved price snapshot")
        for label, field in [('Reference entry', 'reference_entry'), ('Current price', 'current_price'),
                             ('Gap %', 'gap_percent'), ('Stop', 'stop_loss'), ('Target', 'take_profit'),
                             ('Original R:R', 'original_rr'), ('Current R:R', 'current_rr'),
                             ('Reward consumed %', 'reward_consumed_percent')]:
            value = a[field]
            st.write(f'{label}: {value:.4f}' if value is not None else f'{label}: unavailable')
        {'ELIGIBLE': st.success, 'CAUTION': st.warning, 'REJECT': st.error}[a['decision']](a['decision'])
        for code in a['reason_codes']:
            st.write(f"{code}: {REASONS.get(code, code)}")
