from streamlit.testing.v1 import AppTest

from autot.paper_trade.ledger import Ledger
from tests.test_paper_web import ui, APP, button
from tests.test_prospective_paper import confirm, bar, OPEN, BAR
from tests.test_paper_audit import legacy_copy


def show_journal():
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value('Paper Trading').run()
    app.toggle[0].set_value(True).run()
    return app


def test_journal_timeline_runs_and_raw_snapshot_rendering(ui):
    service, provider, now = ui
    t = confirm(service)
    provider.bars = [bar(h=112)]
    now[0] = OPEN + BAR
    service.update_positions()
    before = service.ledger.all()
    events = service.ledger.events(t['trade_id'])
    runs = service.ledger.recent_runs()
    for _ in range(2):
        app = show_journal()
        assert not app.exception and not app.error
        assert any(w.value == 'Small sample — insufficient for strategy conclusions.' for w in app.warning)
        frames = [f.value for f in app.dataframe]
        journal = next(f for f in frames if 'Entry Slippage %' in f.columns)
        assert {'Symbol', 'Side', 'Signal Time', 'Signal Price', 'Fill Price', 'Exit Price', 'Outcome',
                'P&L', 'Return %', 'Signal R:R', 'Actual R:R', 'Holding Duration', 'Exit Reason',
                'Market Regime', 'Trade Quality', 'Historical Score', 'MFE', 'MAE'} <= set(journal.columns)
        timeline = next(f for f in frames if 'Event' in f.columns)
        assert list(timeline['Event']) == [e['event_type'] for e in events]
        run_table = next(f for f in frames if 'Bars processed' in f.columns)
        assert run_table.iloc[0]['Status'] == 'SUCCESS'
        assert run_table.iloc[0]['Bars processed'] == 1
        assert any(e.label == 'Raw trade snapshot JSON' for e in app.expander)
        assert any(e.label.startswith('Details / actions') for e in app.expander)
        assert len(app.json) == 3
        assert service.ledger.all() == before
        assert service.ledger.events(t['trade_id']) == events
        assert service.ledger.recent_runs() == runs


def test_legacy_timeline_shows_only_baseline(ui, tmp_path):
    service, provider, now = ui
    confirm(service)
    provider.bars = [bar(h=112)]
    now[0] = OPEN + BAR
    service.update_positions()
    path = tmp_path / 'legacy.db'
    legacy_copy(service, path)
    service.ledger = Ledger(path)
    app = show_journal()
    assert not app.exception
    timeline = next(f.value for f in app.dataframe if 'Event' in f.value.columns)
    assert list(timeline['Event']) == ['AUDIT_BASELINE_CREATED']
    journal = next(f.value for f in app.dataframe if 'Excursion Evidence' in f.value.columns)
    assert journal.iloc[0]['Excursion Evidence'] == 'Unavailable for pre-audit trade'


def test_explicit_update_click_creates_run_but_reruns_do_not(ui):
    service, _, _ = ui
    app = show_journal()
    assert not service.ledger.recent_runs()
    button(app, 'Update Paper Positions').click().run()
    assert len(service.ledger.recent_runs()) == 1
    app.run()
    assert len(service.ledger.recent_runs()) == 1
    button(app, 'Update Paper Positions').click().run()
    assert len(service.ledger.recent_runs()) == 2
    assert all(r['status'] == 'SUCCESS' for r in service.ledger.recent_runs())


def test_missing_data_run_is_not_presented_as_success(ui):
    service, _, now = ui
    confirm(service)
    now[0] = OPEN + BAR
    app = show_journal()
    button(app, 'Update Paper Positions').click().run()
    assert not app.exception
    assert any('Run status: PARTIAL' in w.value for w in app.warning)
    assert not app.success
