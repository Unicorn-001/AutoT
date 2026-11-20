from streamlit.testing.v1 import AppTest
import pytest

from tests.test_market_context import persisted
from autot.market_context.store import MarketContextStore


def app_body():
    from autot.application.scan_store import ScanStore
    from autot.application.market_context_display import render_market_context
    saved = ScanStore().latest()
    render_market_context(saved, 0, saved['outputs']['trade_opportunities'][0])


@pytest.mark.parametrize('price,decision,reason', [
    ('100', 'ELIGIBLE', 'SETUP_STILL_VALID'),
    ('100.36', 'CAUTION', 'RISK_REWARD_DETERIORATED'),
    ('100.6', 'REJECT', 'RISK_REWARD_DETERIORATED'),
    ('bad', 'REJECT', 'INVALID_MARKET_DATA'),
])
def test_manual_link_decision_reasons_and_restart(persisted, price, decision, reason):
    scanner, run, _ = persisted
    before = scanner.path.read_bytes()
    app = AppTest.from_function(app_body).run()
    assert not app.exception
    assert any(run['scan_run_id'] in c.value for c in app.caption)
    assert MarketContextStore().history(run['scan_run_id'], '0') == []
    app.text_input[0].set_value(price)
    app.button[0].click().run()
    assert not app.exception
    outputs = {'ELIGIBLE': app.success, 'CAUTION': app.warning, 'REJECT': app.error}
    assert outputs[decision][0].value == decision
    assert any(reason in m.value for m in app.markdown)
    assert any('Reference entry: 100.0000' in m.value for m in app.markdown)
    app.run()
    restarted = AppTest.from_function(app_body).run()
    assert not restarted.exception
    assert len(MarketContextStore().history(run['scan_run_id'], '0')) == 1
    assert any(reason in m.value for m in restarted.markdown)
    assert scanner.path.read_bytes() == before


def scanner_app_body():
    from autot.application.scan_store import ScanStore
    from autot.application.scan_display import render_scan_results
    render_scan_results(ScanStore().latest())


def test_scanner_details_select_correct_persisted_opportunity(persisted):
    scanner, run, saved = persisted
    buy = saved['outputs']['trade_opportunities'][0]
    sell = dict(buy, symbol='SECOND', signal='SELL', stop_loss=101, take_profit=98)
    saved['outputs'].update(symbols=['TEST', 'SECOND'], results=[buy, sell],
                            ranked_results=[buy, sell], top_results=[buy, sell],
                            trade_opportunities=[buy, sell])
    saved['settings'] = dict(universe='test', period='1y', interval='1d', top_n=10)
    scanner.save(run, saved)
    before = scanner.path.read_bytes()
    app = AppTest.from_function(scanner_app_body).run()
    assert not app.exception
    assert any(e.label == 'Pre-Trade Market Context · SECOND · SELL' for e in app.expander)
    app.text_input[1].set_value('99.4')
    app.button[1].click().run()
    assert not app.exception and app.error[0].value == 'REJECT'
    store = MarketContextStore()
    assert store.history(run['scan_run_id'], '0') == []
    assessment = store.history(run['scan_run_id'], '1')[0]
    assert assessment['symbol'] == 'SECOND' and assessment['side'] == 'SELL'
    assert assessment['current_price'] == 99.4
    restarted = AppTest.from_function(scanner_app_body).run()
    assert not restarted.exception and restarted.error[0].value == 'REJECT'
    assert scanner.path.read_bytes() == before
