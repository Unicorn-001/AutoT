"""Explicit, advisory assessment of a linked persisted scanner opportunity."""
import sqlite3
import streamlit as st

from autot.market_context.assessment import REASONS
from autot.market_data.market_data_manager import MarketDataManager
from autot.market_context.store import MarketContextStore, assess_opportunity


def render_market_context(saved, index, row):
    with st.expander(f"Pre-Trade Market Context · {row['symbol']} · {row['signal']}"):
        run_id = saved.get('scan_run_id')
        if not run_id:
            st.info('A persisted scanner run is required for a market-context assessment.')
            return
        st.caption(f'Scanner run: {run_id} · Opportunity: {index} · Advisory only; no trades are placed.')
        key = f'market_context_{run_id}_{index}'
        if st.button('Fetch latest price', key=key + '_fetch'):
            try:
                quote = MarketDataManager.get_latest_quote(row['symbol'])
                st.session_state[key + '_quote'] = quote
                st.session_state[key + '_price'] = f'{quote.price:.2f}'
            except Exception as error:
                # Keep the prior input and its provenance on a failed refresh.
                st.error(f'Unable to fetch latest price: {error}')
        quote = st.session_state.get(key + '_quote')
        if quote is not None:
            audit = quote.audit(quote.price)
            st.write(f'Latest fetched price: {quote.price:.2f}')
            st.write(f"Quote timestamp: {audit['quote_timestamp'] or 'unavailable'}")
            st.write(f'Source/provider: {quote.source}')
            st.write(f"Session: {quote.session_label or 'unknown'}")
            age = audit['quote_age_seconds']
            st.write(f'Quote age: {age:.0f} seconds ({age / 60:.1f} minutes)' if age is not None else 'Quote age: unavailable')
            if audit['stale']:
                st.warning('Stale quote: older than the regular-session freshness limit. Review or override before assessing.')
            if quote.session_label is None or age is None:
                st.caption('Freshness unverified: session or quote time is unknown. Yahoo supplies a bar close, not an executable bid/ask.')
        price = st.text_input('Current / executable price', key=key + '_price',
                              help='Fetch a quote or enter a price manually. You can override a fetched price before assessing.')
        try:
            store = MarketContextStore()
            if st.button('Assess current price', key=key + '_assess'):
                assess_opportunity(run_id, index, price, store=store, source='MANUAL', quote=quote)
            history = store.history(run_id, str(index))
        except (ValueError, OSError, sqlite3.Error):
            st.error('Unable to load or save market context. Check scanner results and data storage.')
            return
        if not history:
            st.caption('No assessment yet. Enter the current price and assess explicitly.')
            return
        a = history[0]
        st.caption(f"Last assessment: {a['assessed_at']} · Source: {a['source']} · Saved price snapshot")
        if a['fetched_price'] is not None:
            st.caption(f"Fetched price: {a['fetched_price']} · Assessed price: {a['assessed_price']} · "
                       f"Quote timestamp: {a['quote_timestamp']} · Age at assessment: {a['quote_age_seconds']} seconds · "
                       f"Session: {a['session_label'] or 'unknown'} · Stale: {a['stale']} · Manual override: {a['manual_override']}")
        for label, field in [('Reference entry', 'reference_entry'), ('Current price', 'current_price'),
                             ('Gap %', 'gap_percent'), ('Stop', 'stop_loss'), ('Target', 'take_profit'),
                             ('Original R:R', 'original_rr'), ('Current R:R', 'current_rr'),
                             ('Reward consumed %', 'reward_consumed_percent')]:
            value = a[field]
            st.write(f'{label}: {value:.4f}' if value is not None else f'{label}: unavailable')
        {'ELIGIBLE': st.success, 'CAUTION': st.warning, 'REJECT': st.error}[a['decision']](a['decision'])
        for code in a['reason_codes']:
            st.write(f"{code}: {REASONS.get(code, code)}")
