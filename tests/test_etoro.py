"""Offline contract and safety tests. All HTTP is replaced with fakes."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
import requests
from streamlit.testing.v1 import AppTest

from autot.broker.etoro.client import Client, Config, BrokerError
from autot.broker.etoro.market import Resolver, EtoroQuoteProvider
from autot.broker.etoro.broker import EtoroDemoBroker, ORDERS
from autot.broker.demo_service import DemoService, compare
from autot.broker.execution_store import ExecutionStore
from tests.test_settings_paper import environment
from tests.test_fill_time_risk import prepare


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No real eToro HTTP in automated tests')
    monkeypatch.setattr(requests.Session, 'request', forbidden)


def response(body=None, status=200, headers=None):
    return SimpleNamespace(status_code=status, headers=headers or {}, text=json.dumps(body or {}))


class Queue:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def client(session, **kwargs):
    return Client(Config('fake-app-secret', 'fake-user-secret'), session=session, **kwargs)


def test_headers_request_ids_no_secrets(caplog):
    session = Queue(response(), response())
    c = client(session)
    for _ in range(2):
        c.request('GET', '/api/v1/market-data/exchanges')
    headers = [call[1]['headers'] for call in session.calls]
    assert headers[0]['x-api-key'] == 'fake-app-secret'
    assert headers[0]['x-user-key'] == 'fake-user-secret'
    assert UUID(headers[0]['x-request-id']) != UUID(headers[1]['x-request-id'])
    assert session.calls[0][1]['timeout'] == 10
    assert session.calls[0][1]['allow_redirects'] is False
    assert 'fake-app-secret' not in repr(c.config) + caplog.text
    assert 'fake-user-secret' not in repr(c.config) + caplog.text


@pytest.mark.parametrize('status', [301, 400, 401, 403, 429, 500])
def test_normalized_errors_never_echo_secrets(status, caplog):
    session = Queue(*[response({'error': 'fake-app-secret fake-user-secret'}, status) for _ in range(3)])
    with pytest.raises(BrokerError) as error:
        client(session, sleep=lambda _: None).request('GET', '/api/v1/market-data/exchanges')
    assert str(status) in str(error.value)
    assert 'fake-app-secret' not in str(error.value) + caplog.text
    assert 'fake-user-secret' not in str(error.value) + caplog.text


def test_bounded_backoff_unique_ids_and_retry_after():
    session = Queue(response(status=429), response(status=429, headers={'Retry-After': '3'}), response())
    sleeps = []
    client(session, sleep=sleeps.append).request('GET', '/api/v1/market-data/exchanges')
    assert sleeps == [1, 3]
    assert len({call[1]['headers']['x-request-id'] for call in session.calls}) == 3
    session = Queue(response(status=429, headers={'Retry-After': '60'}))
    with pytest.raises(BrokerError, match='429'):
        client(session, sleep=sleeps.append).request('GET', '/api/v1/market-data/exchanges')
    assert len(session.calls) == 1


@pytest.mark.parametrize('failure', [requests.Timeout('fake-user-secret'), requests.ConnectionError('fake-app-secret')])
def test_timeout_normalized_no_mutation_retry(failure):
    session = Queue(failure)
    with pytest.raises(BrokerError) as error:
        client(session).request('POST', ORDERS, payload={})
    assert error.value.uncertain and len(session.calls) == 1
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('mode', ['real', 'REAL', '', 'paper'])
def test_real_mode_rejected(mode):
    with pytest.raises(BrokerError):
        Config('fake', 'fake', mode=mode)


def test_env_defaults_and_bad_settings(monkeypatch):
    monkeypatch.delenv('ETORO_TRADING_MODE', raising=False)
    monkeypatch.setenv('ETORO_API_KEY', 'app')
    monkeypatch.setenv('ETORO_USER_KEY', 'user')
    assert Config.from_env().mode == 'demo' and Config.from_env().configured
    monkeypatch.setenv('ETORO_MAX_RETRIES', '100')
    with pytest.raises(BrokerError):
        Config.from_env()


@pytest.mark.parametrize('path', ['/api/v2/trading/execution/orders', 'https://evil.test/',
                                  '/api/v2/trading/execution/demo/../orders'])
def test_real_or_foreign_route_blocked(path):
    session = Queue()
    with pytest.raises(BrokerError):
        client(session).request('POST', path)
    assert not session.calls


@pytest.mark.parametrize('symbol', ['AAPL', 'NVDA', 'BE'])
def test_resolution_cache_exact_and_metadata(symbol):
    session = Queue(response({'results': [{'symbol': symbol, 'instrumentId': 12, 'type': 'Stocks', 'exchangeId': 1}]}))
    resolver = Resolver(client(session))
    assert resolver.resolve(symbol)['instrumentId'] == 12
    assert resolver.resolve(symbol.lower())['type'] == 'Stocks'
    assert len(session.calls) == 1


@pytest.mark.parametrize('results', [[], [{'symbol': 'AAPL.X', 'instrumentId': 1}],
    [{'symbol': 'AAPL', 'instrumentId': 1}, {'symbol': 'AAPL', 'instrumentId': 2}]])
def test_missing_ambiguous_symbol(results):
    with pytest.raises(BrokerError, match='missing or ambiguous'):
        Resolver(client(Queue(response({'results': results})))).resolve('AAPL')


def quote_session(rate):
    return Queue(response({'results': [{'symbol': 'AAPL', 'instrumentId': 12}]}), response({'rates': [rate]}))


def test_quote_precision_bid_ask_spread_source():
    rate = dict(instrumentID=12, bid='100.123456789123456789', ask='100.223456789123456789',
                lastExecution='100.17', date='2026-11-24T15:00:00Z')
    q = EtoroQuoteProvider(client(quote_session(rate))).quote('AAPL')
    assert q.price == Decimal(rate['ask']) and q.last == Decimal('100.17')
    assert q.spread_absolute == Decimal('.1')
    assert q.spread_percent == Decimal('.1') / ((q.bid + q.ask) / 2) * 100
    assert q.source == 'eToro' and q.instrument_id == 12
    assert q.audit(q.price)['bid'] == rate['bid']
    sell = EtoroQuoteProvider(client(quote_session(rate))).quote('AAPL', 'SELL')
    assert sell.price == sell.bid


def test_missing_bid_not_invented_and_no_execution_fallback():
    q = EtoroQuoteProvider(client(quote_session(dict(instrumentID=12, ask=100, lastExecution=99)))).quote('AAPL', 'SELL')
    assert q.bid is None and q.spread_absolute is None and q.quote_timestamp is None
    with pytest.raises(BrokerError, match='unavailable'):
        _ = q.price


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.ask = '100'
        self.stamp = datetime.now(timezone.utc).isoformat()
        self.submit_error = None
        self.order_status = 3
        self.exchange = 'NASDAQ'
        self.kind = 'Stocks'
        self.settlement = 'REAL'
        self.positions = []
        self.on_submit = None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith('/instruments/search'):
            return response({'results': [{'symbol': kwargs['params']['query'], 'instrumentId': 12,
                                          'type': self.kind, 'exchangeId': 1}]})
        if url.endswith('/exchanges'):
            return response({'exchangeInfo': [{'exchangeID': 1, 'exchangeDescription': self.exchange}]})
        if url.endswith('/eligibility'):
            return response({'eligibilities': [{'instrumentId': 12, 'allowOpenPosition': True,
                'leverageConfigs': [{'settlementType': self.settlement, 'direction': 'LONG',
                                     'leverageValues': [1], 'isPotential': False}]}]})
        if url.endswith('/rates'):
            return response({'rates': [dict(instrumentID=12, bid='99.99', ask=self.ask, date=self.stamp)]})
        if url.endswith('/pnl'):
            return response({'clientPortfolio': dict(credit=100000, positions=self.positions)})
        if url.endswith('/orders'):
            if self.on_submit:
                self.on_submit()
            if self.submit_error:
                raise self.submit_error
            return response({'orderId': 123, 'referenceId': kwargs['headers']['x-request-id']})
        if url.endswith('/orders:lookup'):
            return response(dict(orderId=123, asset={'instrumentId': 12, 'settlementType': 'real', 'leverage': 1},
                status={'id': self.order_status, 'name': 'Filled', 'errorMessage': 'fake-user-secret reason' if self.order_status == 4 else None},
                totalCosts='1.2', positionExecutions=[] if self.order_status == 4 else [dict(positionId=999,
                    stopLossRate='95', takeProfitRate='110', openingData=dict(units=10,
                    avgPrice='100.01234567890123456789', fees='1.2', executionTime=self.stamp))]))
        if '/market-close-orders/positions/' in url:
            return response({'orderForClose': {'orderID': 456}})
        if '/close-orders/' in url:
            return response(dict(orderID=456, instrumentID=12, statusID=3,
                positions=[dict(positionID=999, occurred=self.stamp, units=10, rate='101')]))
        raise AssertionError(url)


@pytest.fixture
def setup_demo(environment):
    trade = prepare(environment)
    api = FakeAPI()
    service = DemoService(client(api), paper_path=environment[1].ledger.path)
    return trade, api, service


def test_manual_confirmation_required(setup_demo):
    trade, api, service = setup_demo
    for confirmed in (False, None, 1, 'yes'):
        with pytest.raises(BrokerError, match='confirmation'):
            service.submit(trade['trade_id'], confirmed=confirmed)
    assert not api.calls and not service.store.all()


def test_submission_mapping_durable_intent_restart_no_paper_mutation(setup_demo, environment):
    trade, api, service = setup_demo
    before = service.paper_snapshot()
    # Assert persistence while the fake HTTP call is in progress.
    def inspect_intent():
        row = ExecutionStore(service.store.path).all()[0]
        assert row['broker_status'] == 'INTENDED' and row['request_id']
    api.on_submit = inspect_intent
    row = service.submit(trade['trade_id'], confirmed=True)
    assert row['broker_status'] == 'SUBMITTED' and row['fill_price'] is None
    assert row['order_payload'] == dict(action='open', transaction='buy', instrumentId=12, orderType='mkt',
        units=10, orderCurrency='usd', leverage=1, settlementType='real', stopLossType='fixed',
        stopLossRate=95, takeProfitRate=110)
    restarted = DemoService(client(api), store=ExecutionStore(service.store.path), paper_path=service.paper_path)
    assert restarted.submit(trade['trade_id'], confirmed=True) == row
    assert len([call for call in api.calls if call[1].endswith('/orders')]) == 1
    fill = restarted.reconcile(row['intent_key'])
    assert Decimal(fill['fill_price']) == Decimal('100.01234567890123456789')
    assert fill['filled_quantity'] == '10' and fill['position_ids'] == [999]
    assert Decimal(fill['fees']) == Decimal('1.2')
    assert service.paper_snapshot() == before
    data = service.store.path.read_bytes()
    assert b'fake-user-secret' not in data and b'fake-app-secret' not in data


def test_lost_response_reconciles_by_request_without_resubmit(setup_demo):
    trade, api, service = setup_demo
    api.submit_error = requests.Timeout('secret')
    row = service.submit(trade['trade_id'], confirmed=True)
    assert row['broker_status'] == 'UNKNOWN'
    assert service.submit(trade['trade_id'], confirmed=True) == row
    result = service.reconcile(row['intent_key'])
    assert api.calls[-1][2]['params'] == {'referenceId': row['request_id']}
    assert result['broker_status'] == 'FILLED'


def test_broker_rejection_redacted_and_persisted(setup_demo):
    trade, api, service = setup_demo
    row = service.submit(trade['trade_id'], confirmed=True)
    api.order_status = 4
    result = service.reconcile(row['intent_key'])
    assert result['broker_status'] == 'REJECTED' and result['fill_price'] is None
    assert result['rejection_reason'] == '[REDACTED] reason'
    assert b'fake-user-secret' not in service.store.path.read_bytes()


@pytest.mark.parametrize('field,value', [('ask', '120'), ('ask', '102'), ('kind', 'Crypto'),
    ('exchange', 'London'), ('settlement', 'CFD'), ('stamp', '2020-01-01T00:00:00Z'),
    ('positions', [{'positionId': 123456}])])
def test_fail_closed_safety_checks(setup_demo, field, value):
    trade, api, service = setup_demo
    setattr(api, field, value)
    with pytest.raises(BrokerError):
        service.submit(trade['trade_id'], confirmed=True)
    assert not service.store.all()
    assert not any(call[1].endswith('/orders') for call in api.calls)


def test_close_confirmation_path_and_shadow_comparison(setup_demo):
    trade, api, service = setup_demo
    row = service.submit(trade['trade_id'], confirmed=True)
    row = service.reconcile(row['intent_key'])
    api.positions = [dict(positionId=999, instrumentId=12, units=10, isBuy=True, leverage=1)]
    with pytest.raises(BrokerError, match='confirmation'):
        service.close(row['intent_key'])
    closed = service.close(row['intent_key'], confirmed=True)
    assert closed['close_status'] == 'SUBMITTED'
    assert closed['close_reference'] is None
    assert closed['close_position_id'] == 999 and closed['close_intended_quantity'] == '10'
    service.close(row['intent_key'], confirmed=True)
    assert len([c for c in api.calls if '/market-close-orders/positions/' in c[1]]) == 1
    closed = service.reconcile_close(row['intent_key'])
    assert closed['closed_quantity'] == '10' and closed['pnl_basis'] == 'gross, before fees'
    paper = dict(trade, fill_price='100', filled_at=(datetime.fromisoformat(api.stamp)-timedelta(seconds=2)).isoformat(),
                 status='CLOSED', realized_pnl='9')
    comparison = compare(paper, closed)
    assert comparison['timing_difference_seconds'] == 2
    assert comparison['quantity_difference'] == '0'
    assert Decimal(comparison['entry_difference']) == Decimal('0.01234567890123456789')
    assert comparison['realized_pnl_difference'] is not None


def app_body():
    from autot.application.broker_display import render_broker
    render_broker()


def test_ui_missing_credentials(monkeypatch):
    monkeypatch.delenv('ETORO_API_KEY', raising=False)
    monkeypatch.delenv('ETORO_USER_KEY', raising=False)
    app = AppTest.from_function(app_body).run()
    assert not app.exception and 'Not configured' in app.info[0].value
    assert 'DEMO ONLY' in app.warning[0].value
    assert not app.button


def test_ui_configured_no_auto_network_or_secret_display(monkeypatch):
    monkeypatch.setenv('ETORO_API_KEY', 'fake-app-secret')
    monkeypatch.setenv('ETORO_USER_KEY', 'fake-user-secret')
    app = AppTest.from_function(app_body).run()
    assert not app.exception and 'unverified' in app.caption[0].value
    assert all('fake-user-secret' not in str(e.value) for e in app.markdown)
    assert any(b.label == 'Check demo connection / portfolio' for b in app.button)


def test_direct_adapter_rejects_short_limit_leverage_and_extra_fields():
    session = Queue()
    broker = EtoroDemoBroker(client(session))
    base = dict(action='open', transaction='buy', instrumentId=12, orderType='mkt', units=10,
                orderCurrency='usd', leverage=1, settlementType='real', stopLossType='fixed',
                stopLossRate=95, takeProfitRate=110)
    for changes in ({'transaction': 'sellShort'}, {'leverage': 2}, {'orderType': 'mit'},
                    {'settlementType': 'cfd'}, {'units': -1}, {'units': True}, {'amount': 10}):
        with pytest.raises(BrokerError):
            broker.submit(base | changes, request_id='unused', confirmed=True)
    with pytest.raises(BrokerError):
        broker.submit(base, request_id='unused', confirmed=False)
    assert not session.calls


def test_http_rejection_captured_after_durable_intent(setup_demo):
    trade, api, service = setup_demo
    original = api.request
    def reject(method, url, **kwargs):
        if url.endswith('/orders'):
            assert service.store.all()[0]['broker_status'] == 'INTENDED'
            return response({'errorMessage': 'fake-user-secret'}, 400)
        return original(method, url, **kwargs)
    api.request = reject
    result = service.submit(trade['trade_id'], confirmed=True)
    assert result['broker_status'] == 'REJECTED'
    assert result['rejection_reason'] == 'eToro HTTP 400.'


def test_all_paper_tables_unchanged_and_scanner_provenance(setup_demo):
    import sqlite3
    trade, api, service = setup_demo
    from autot.application.scan_store import ScanStore
    scans = ScanStore()
    with scans.connection() as db:
        saved = dict(outputs={'trade_opportunities': [trade['original_opportunity']]},
                     paper_signal_context={trade['symbol']: {'signal_time': trade['signal_time']}})
        db.execute('INSERT INTO scan_runs VALUES (?,?,?)', ('scan-1', '{}', json.dumps(saved)))
    with sqlite3.connect(service.paper_path) as db:
        before = list(db.iterdump())
    scanner_before = scans.path.read_bytes()
    result = service.submit(trade['trade_id'], confirmed=True)
    assert result['scanner_run_id'] == 'scan-1' and result['opportunity_id'] == '0'
    service.reconcile(result['intent_key'])
    with sqlite3.connect(service.paper_path) as db:
        assert list(db.iterdump()) == before
    assert scans.path.read_bytes() == scanner_before


def test_concurrent_confirmation_only_one_order(setup_demo):
    from concurrent.futures import ThreadPoolExecutor
    trade, api, service = setup_demo
    def submit():
        return DemoService(client(api), store=ExecutionStore(service.store.path),
                           paper_path=service.paper_path).submit(trade['trade_id'], confirmed=True)
    with ThreadPoolExecutor(max_workers=2) as workers:
        records = list(workers.map(lambda _: submit(), range(2)))
    assert records[0]['intent_key'] == records[1]['intent_key']
    assert len([c for c in api.calls if c[1].endswith('/orders')]) == 1


def test_crash_after_intent_does_not_resend(setup_demo):
    trade, api, service = setup_demo
    class ProcessStopped(BaseException):
        pass
    def crash():
        raise ProcessStopped()
    api.on_submit = crash
    with pytest.raises(ProcessStopped):
        service.submit(trade['trade_id'], confirmed=True)
    record = ExecutionStore(service.store.path).all()[0]
    assert record['broker_status'] == 'INTENDED'
    api.on_submit = None
    restarted = DemoService(client(api), store=ExecutionStore(service.store.path), paper_path=service.paper_path)
    assert restarted.submit(trade['trade_id'], confirmed=True)['broker_status'] == 'INTENDED'
    assert len([c for c in api.calls if c[1].endswith('/orders')]) == 1
    assert restarted.reconcile(record['intent_key'])['broker_status'] == 'FILLED'


def test_ui_connection_and_quote_with_fake_credentials(monkeypatch):
    monkeypatch.setenv('ETORO_API_KEY', 'fake-app-secret')
    monkeypatch.setenv('ETORO_USER_KEY', 'fake-user-secret')
    service = DemoService(client(FakeAPI()))
    monkeypatch.setattr('autot.application.broker_display.DemoService', lambda: service)
    app = AppTest.from_function(app_body).run()
    next(b for b in app.button if b.label == 'Check demo connection / portfolio').click().run()
    assert not app.exception and 'Authenticated' in app.success[0].value
    next(b for b in app.button if b.label == 'Resolve instrument / fetch eToro quote').click().run()
    assert not app.exception and not app.error


def test_raw_json_float_precision_and_redaction():
    raw = SimpleNamespace(status_code=200, headers={},
        text='{"price":100.123456789123456789,"token":"omit", "error":"fake-user-secret"}')
    result = client(Queue(raw)).request('GET', '/api/v1/market-data/exchanges')
    assert result['price'] == Decimal('100.123456789123456789')
    assert result['error'] == '[REDACTED]' and 'token' not in result


def test_future_quote_and_missing_credentials_fail_closed(setup_demo):
    trade, api, service = setup_demo
    api.stamp = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    with pytest.raises(BrokerError, match='Fresh'):
        service.submit(trade['trade_id'], confirmed=True)
    with pytest.raises(BrokerError, match='credentials'):
        Client(Config('', ''), session=Queue()).request('GET', '/api/v1/market-data/exchanges')


def tracked_close(setup_demo):
    trade, api, service = setup_demo
    row = service.submit(trade['trade_id'], confirmed=True)
    row = service.reconcile(row['intent_key'])
    api.positions = [dict(positionId=999, instrumentId=12, units=10, isBuy=True, leverage=1)]
    api.calls.clear()
    return row, api, service


def test_close_ignores_rejected_entry_context_risk_scanner_and_quotes(setup_demo, monkeypatch):
    from autot.market_context.assessment import assess
    row, api, service = tracked_close(setup_demo)
    assert assess(symbol=row['symbol'], side='BUY', reference_entry=row['reference_entry'],
        stop_loss=row['stop'], take_profit=row['target'], original_rr=2,
        current_price=90)['decision'] == 'REJECT'
    def entry_only(*args, **kwargs):
        pytest.fail('A close must not call entry gates, scanner, paper eligibility or quote provider')
    monkeypatch.setattr('autot.broker.demo_service.assess', entry_only)
    monkeypatch.setattr('autot.broker.demo_service.recheck', entry_only)
    monkeypatch.setattr(service, 'scanner_link', entry_only)
    monkeypatch.setattr(service, 'paper_snapshot', entry_only)
    monkeypatch.setattr(service.quotes, 'quote', entry_only)
    original = api.request
    def verify_intent(method, url, **kwargs):
        if '/market-close-orders/positions/' in url:
            durable = ExecutionStore(service.store.path).get(row['intent_key'])
            assert durable['close_status'] == 'INTENDED'
            assert durable['close_request_id'] == kwargs['headers']['x-request-id']
            assert durable['close_position_id'] == 999
            assert kwargs['json'] == {'InstrumentID': 12}
            assert method == 'POST' and url.endswith('/demo/market-close-orders/positions/999')
        return original(method, url, **kwargs)
    api.request = verify_intent
    result = service.close(row['intent_key'], confirmed=True)
    assert result['close_status'] == 'SUBMITTED'
    assert 'close_risk_check' not in result and 'close_market_context' not in result
    assert not any(c[1].endswith('/orders') for c in api.calls)
    assert service.reconcile_close(row['intent_key'])['close_status'] == 'FILLED'


@pytest.mark.parametrize('change', [{'isBuy': False}, {'instrumentId': 13}, {'positionId': 998}, {'units': 11}])
def test_close_rejects_wrong_or_short_position(setup_demo, change):
    row, api, service = tracked_close(setup_demo)
    api.positions[0].update(change)
    with pytest.raises(BrokerError):
        service.close(row['intent_key'], confirmed=True)
    assert not service.store.get(row['intent_key']).get('close_request_id')
    assert not any(c[0] == 'POST' for c in api.calls)


@pytest.mark.parametrize('confirmed', [False, None, 1, 'yes'])
def test_close_requires_explicit_boolean_confirmation(setup_demo, confirmed):
    row, api, service = tracked_close(setup_demo)
    with pytest.raises(BrokerError, match='confirmation'):
        service.close(row['intent_key'], confirmed=confirmed)
    assert not api.calls


def test_close_rejects_real_mode_at_service_and_adapter(setup_demo):
    row, api, service = tracked_close(setup_demo)
    service.client.config = SimpleNamespace(mode='real')
    with pytest.raises(BrokerError):
        service.close(row['intent_key'], confirmed=True)
    with pytest.raises(BrokerError):
        service.broker.close_position(999, 12, request_id='unused', confirmed=True)
    assert not api.calls


@pytest.mark.parametrize('position_id,instrument_id', [(0, 12), (999, 0), (True, 12), (999, True), (999, '12')])
def test_close_adapter_validates_ids(position_id, instrument_id):
    session = Queue()
    with pytest.raises(BrokerError):
        EtoroDemoBroker(client(session)).close_position(position_id, instrument_id,
            request_id='unused', confirmed=True)
    assert not session.calls


@pytest.mark.parametrize('outcome', ['timeout', 'missing_id'])
def test_uncertain_close_survives_restart_without_replay(setup_demo, outcome):
    row, api, service = tracked_close(setup_demo)
    original = api.request
    close_calls = []
    def uncertain(method, url, **kwargs):
        if '/market-close-orders/positions/' in url:
            close_calls.append(url)
            if outcome == 'timeout':
                raise requests.Timeout('fake-user-secret')
            return response({})
        return original(method, url, **kwargs)
    api.request = uncertain
    result = service.close(row['intent_key'], confirmed=True)
    assert result['close_status'] == 'UNKNOWN'
    restarted = DemoService(client(api), store=ExecutionStore(service.store.path), paper_path=service.paper_path)
    assert restarted.close(row['intent_key'], confirmed=True) == result
    with pytest.raises(BrokerError, match='No close order ID'):
        restarted.reconcile_close(row['intent_key'])
    assert len(close_calls) == 1
    assert 'fake-user-secret' not in result['close_error']
