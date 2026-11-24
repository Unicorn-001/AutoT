"""Manual demo workspace. No HTTP, automatic refresh or background workers."""
import sqlite3
import streamlit as st
from autot.broker.etoro.client import Config, BrokerError
from autot.broker.demo_service import DemoService, compare


def render_broker():
    st.header('Broker / eToro Demo')
    st.warning('DEMO ONLY — simulated funds. Real-money execution is disabled in V1.')
    try:
        config = Config.from_env()
        if not config.configured:
            st.info('Not configured. Set ETORO_API_KEY and ETORO_USER_KEY in the server environment. Never enter keys here.')
            return
        st.caption('Demo credentials configured. Authentication is unverified until you check connectivity.')
        service = DemoService()
        if st.button('Check demo connection / portfolio'):
            account = service.broker.account()
            st.success('Authenticated eToro DEMO connection')
            st.write({'demo_credit': str(account.get('credit')), 'unrealized_pnl': str(account.get('unrealizedPnL')),
                      'open_positions': len(account.get('positions', []))})
            st.dataframe(account.get('positions', []))
        symbol = st.text_input('eToro quote symbol', value='AAPL')
        side = st.selectbox('Executable quote side', ['BUY', 'SELL'])
        if st.button('Resolve instrument / fetch eToro quote'):
            quote = service.quotes.quote(symbol, side)
            st.write({'symbol': quote.symbol, 'instrument_id': quote.instrument_id,
                      'bid': str(quote.bid), 'ask': str(quote.ask), 'last': str(quote.last),
                      'executable_reference': str(quote.price), 'spread': str(quote.spread_absolute),
                      'spread_percent': str(quote.spread_percent), 'timestamp': str(quote.quote_timestamp),
                      'source': quote.source})
        trades, _ = service.paper_snapshot()
        active = {t['trade_id']: t for t in trades if t['market'] == 'US' and t['side'] == 'BUY'
                  and t['status'] in ('PENDING_ENTRY', 'OPEN')}
        st.subheader('Manually submit a linked demo order')
        st.caption('US underlying equities · BUY MARKET · X1 · paper stop/target · one demo order per paper intent')
        if active:
            selected = st.selectbox('Internal paper intent', list(active),
                                    format_func=lambda key: f"{active[key]['symbol']} · {key}")
            trade = active[selected]
            st.write({k: trade[k] for k in ('symbol', 'side', 'quantity', 'signal_price', 'stop_loss', 'take_profit')})
            confirmed = st.checkbox('I explicitly confirm this eToro DEMO order', key='demo_confirm_' + selected)
            if st.button('Submit confirmed DEMO order', disabled=not confirmed):
                result = service.submit(selected, confirmed=confirmed)
                st.write(result)
                st.info('Submission is not a fill. Reconcile the broker status below.')
        else:
            st.info('Confirm a qualified US BUY opportunity in Paper Trading first to create a comparison intent.')
        st.subheader('Demo orders and fills')
        records = service.store.all()
        if records:
            st.dataframe([{k: r.get(k) for k in ('intent_key', 'symbol', 'broker_order_id', 'broker_status',
                'submitted_at', 'fill_price', 'filled_at', 'filled_quantity', 'fees', 'rejection_reason')} for r in records])
            key = st.selectbox('Broker execution to reconcile', [r['intent_key'] for r in records])
            if st.button('Refresh broker status / reconcile'):
                st.write(service.reconcile(key))
            close_confirmed = st.checkbox('I explicitly confirm closing this tracked eToro DEMO position', key='close_' + key)
            if st.button('Close confirmed DEMO position', disabled=not close_confirmed):
                st.write(service.close(key, confirmed=close_confirmed))
            if st.button('Refresh demo close status'):
                st.write(service.reconcile_close(key))
            paper = {t['trade_id']: t for t in trades}
            st.subheader('Shadow comparison — eToro minus internal paper')
            st.write([compare(paper[r['paper_trade_id']], r) for r in service.store.all() if r['paper_trade_id'] in paper])
        else:
            st.caption('No demo submissions recorded.')
    except BrokerError as error:
        st.error(str(error))
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        st.error('Unable to verify demo data or storage. No execution should be assumed; reconcile before retrying.')
