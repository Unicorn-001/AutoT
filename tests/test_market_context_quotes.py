from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import json
import sqlite3

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from autot.market_data import quote as quotes
from autot.market_data.quote import Quote, QuoteError
from autot.market_data.market_data_manager import MarketDataManager
from autot.market_data.yfinance_download import DownloadResult
from autot.market_context.store import MarketContextStore, assess_opportunity
from autot.market_context.assessment import assess
from autot.paper_trade.ledger import Ledger
from tests.test_market_context import persisted, setup
from tests.test_market_context_web import app_body

NOW = datetime(2026, 11, 20, 15, tzinfo=timezone.utc)


def pool_result(monkeypatch, result):
    pool = MagicMock()
    pool.__enter__.return_value = pool
    pool.download.return_value = {'TEST': result}
    monkeypatch.setattr(quotes, 'YahooDownloadPool', lambda: pool)
    return pool


def test_valid_quote_fetch(monkeypatch):
    data = pd.DataFrame({'Close': [99., 100.]}, index=pd.date_range(NOW, periods=2, freq='min'))
    data.columns = pd.MultiIndex.from_product([data.columns, ['TEST']])
    pool = pool_result(monkeypatch, DownloadResult(data=data))
    quote = MarketDataManager.get_latest_quote('TEST')
    assert quote.price == 100 and quote.symbol == 'TEST'
    assert quote.quote_timestamp == NOW + timedelta(minutes=1)
    assert quote.source == 'Yahoo (1-minute close)' and quote.session_label is None
    pool.download.assert_called_once_with(['TEST'], '5d', '1m')
    pool.__exit__.assert_called_once()


@pytest.mark.parametrize('session,age,stale', [
    ('REGULAR', 300, False), ('REGULAR', 301, True), ('CLOSED', 86400, False),
    ('PRE', 800, False), ('POST', 800, False), (None, 86400, False), ('REGULAR', -10, False),
])
def test_staleness(session, age, stale):
    q = Quote('TEST', 100, NOW - timedelta(seconds=age), session_label=session)
    audit = q.audit(100, now=NOW)
    assert audit['stale'] is stale
    assert audit['quote_age_seconds'] == (age if age >= 0 else None)


def test_configurable_staleness(monkeypatch):
    monkeypatch.setattr(quotes, 'STALE_QUOTE_SECONDS', 10)
    assert Quote('TEST', 100, NOW - timedelta(seconds=11), session_label='REGULAR').audit(100, now=NOW)['stale']
    assert Quote('TEST', 100).audit(100, now=NOW)['quote_age_seconds'] is None


@pytest.mark.parametrize('data', [None, pd.DataFrame(), pd.DataFrame({'Open': [100]}),
    pd.DataFrame({'Close': [None]}), pd.DataFrame({'Close': [float('inf')]}),
    pd.DataFrame({'Close': [0]}), pd.DataFrame({'Close': ['bad']})])
def test_missing_invalid(monkeypatch, data):
    pool_result(monkeypatch, DownloadResult(data=data))
    with pytest.raises(QuoteError):
        MarketDataManager.get_latest_quote('TEST')


@pytest.mark.parametrize('error', [TimeoutError('timeout'), RuntimeError('provider unavailable')])
def test_provider_failure(monkeypatch, error):
    pool_result(monkeypatch, DownloadResult(error=error))
    with pytest.raises(QuoteError, match='provider unavailable or request timed out'):
        MarketDataManager.get_latest_quote('TEST')


def test_provider_start_failure(monkeypatch):
    def fail():
        raise RuntimeError('unavailable')
    monkeypatch.setattr(quotes, 'YahooDownloadPool', fail)
    with pytest.raises(QuoteError, match='provider error'):
        MarketDataManager.get_latest_quote('TEST')


@pytest.mark.parametrize('price', [0, -1, float('nan'), float('inf'), True, '100'])
def test_invalid_quote_model(price):
    with pytest.raises(QuoteError):
        Quote('TEST', price)


@pytest.mark.parametrize('price,override', [(100, False), (100.5, True), ('bad', True)])
def test_audit_restart_isolation(persisted, price, override):
    scanner, run, _ = persisted
    ledger = Ledger()
    before = (scanner.path.read_bytes(), ledger.path.read_bytes())
    q = Quote('TEST', 100, NOW - timedelta(seconds=400), session_label='REGULAR')
    a = assess_opportunity(run['scan_run_id'], 0, price, quote=q, assessed_at=NOW.isoformat())
    assert a['fetched_price'] == 100 and a['manual_override'] is override
    assert a['assessed_price'] == a['current_price']
    assert a['quote_timestamp'] == q.quote_timestamp.isoformat()
    assert a['price_source'] == a['source'] == q.source
    assert a['quote_age_seconds'] == 400 and a['stale'] is True
    assert a['session_label'] == 'REGULAR'
    assert MarketContextStore().history(run['scan_run_id'], '0') == [a]
    assert before == (scanner.path.read_bytes(), ledger.path.read_bytes())
    with pytest.raises(ValueError, match='symbol'):
        assess_opportunity(run['scan_run_id'], 0, 100, quote=Quote('OTHER', 100))


def test_old_v1_records(persisted):
    _, run, _ = persisted
    store = MarketContextStore()
    old = assess(**setup(), scanner_run_id=run['scan_run_id'], opportunity_id='0', source='MANUAL')
    store.save(old)
    before = store.path.read_bytes()
    a = MarketContextStore().history(run['scan_run_id'], '0')[0]
    assert a['version'] == 1 and a['fetched_price'] is None
    assert a['assessed_price'] == 100 and a['manual_override'] is False
    assert store.path.read_bytes() == before
    with sqlite3.connect(store.path) as db:
        assert json.loads(db.execute('SELECT payload FROM assessments').fetchone()[0]) == old


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_ui_fetch_override_explicit_assess(persisted, monkeypatch):
    _, run, _ = persisted
    q = Quote('TEST', 100, datetime.now(timezone.utc) - timedelta(minutes=10), session_label='REGULAR')
    monkeypatch.setattr(MarketDataManager, 'get_latest_quote', lambda symbol: q)
    app = AppTest.from_function(app_body).run()
    button(app, 'Fetch latest price').click().run()
    assert not app.exception
    assert app.text_input[0].value == '100.00'
    for text in ['Latest fetched price: 100', 'Quote timestamp:', 'Source/provider: Yahoo', 'Session: REGULAR', 'Quote age:']:
        assert any(text in m.value for m in app.markdown)
    assert any('Stale quote' in w.value for w in app.warning)
    assert MarketContextStore().history(run['scan_run_id'], '0') == []
    app.text_input[0].set_value('100.5').run()
    assert MarketContextStore().history(run['scan_run_id'], '0') == []
    button(app, 'Assess current price').click().run()
    a = MarketContextStore().history(run['scan_run_id'], '0')[0]
    assert a['fetched_price'] == 100 and a['assessed_price'] == 100.5 and a['manual_override']
    assert not app.exception
    app = AppTest.from_function(app_body).run()
    assert any('Manual override: True' in c.value for c in app.caption)


@pytest.mark.parametrize('raw_price,display_price', [
    (357.1700134277388, '357.17'),
    (357.1799938964844, '357.18'),
    (100.5, '100.50'),
])
def test_ui_price_format_preserves_raw_quote(persisted, monkeypatch, raw_price, display_price):
    _, run, _ = persisted
    q = Quote('TEST', raw_price, datetime.now(timezone.utc), session_label='REGULAR')
    monkeypatch.setattr(MarketDataManager, 'get_latest_quote', lambda symbol: q)
    app = AppTest.from_function(app_body).run()
    button(app, 'Fetch latest price').click().run()
    assert not app.exception
    assert app.text_input[0].value == display_price
    assert any(m.value == f'Latest fetched price: {display_price}' for m in app.markdown)
    key = f"market_context_{run['scan_run_id']}_0_quote"
    assert app.session_state[key].price == raw_price
    assert MarketContextStore().history(run['scan_run_id'], '0') == []
    button(app, 'Assess current price').click().run()
    assert not app.exception
    saved = MarketContextStore().history(run['scan_run_id'], '0')[0]
    assert saved['fetched_price'] == raw_price
    assert saved['assessed_price'] == float(display_price)
    assert saved['quote_timestamp'] == q.quote_timestamp.isoformat()
    assert app.session_state[key].price == raw_price


def test_ui_fetch_error_preserves_manual_flow(persisted, monkeypatch):
    def fail(symbol):
        raise QuoteError('Yahoo provider unavailable')
    monkeypatch.setattr(MarketDataManager, 'get_latest_quote', fail)
    app = AppTest.from_function(app_body).run()
    app.text_input[0].set_value('100').run()
    button(app, 'Fetch latest price').click().run()
    assert not app.exception and app.text_input[0].value == '100'
    assert 'provider unavailable' in app.error[0].value
    button(app, 'Assess current price').click().run()
    assert not app.exception and app.success[0].value == 'ELIGIBLE'
