"""Offline risk preview, rejection and exposure UI; no market calls."""
from streamlit.testing.v1 import AppTest

from autot.settings.store import SettingsStore
from tests.test_paper_web import ui, APP, button, start_review
from tests.test_settings import changed
from tests.test_settings_paper import create
from tests.test_portfolio_risk import dump


def test_review_displays_structured_rejection_without_writes(ui):
    service, provider, _ = ui
    SettingsStore().save(changed(risk={'enforce_position_limit':True,'maximum_position_percent':10}),expected_version=0)
    app=start_review()
    before=dump(service.ledger)
    button(app,'Calculate quantity').click().run()
    assert not app.exception
    assert any(s.value == 'Portfolio Risk · REJECT' for s in app.subheader)
    assert any('maximum position percent' in e.value for e in app.error)
    assert button(app,'Confirm Paper Trade').disabled
    assert dump(service.ledger) == before and not provider.calls


def test_allow_preview_does_not_bypass_changed_portfolio(ui):
    service, _, _ = ui
    store=SettingsStore()
    state=store.save(changed(risk={'enforce_positions_limit':True,'maximum_simultaneous_positions':1}),expected_version=0)
    app=start_review()
    button(app,'Calculate quantity').click().run()
    assert any(s.value == 'Portfolio Risk · ALLOW' for s in app.subheader)
    create(service,state,key='external',symbol='MSFT')
    before=dump(service.ledger)
    app.checkbox[0].check()
    button(app,'Confirm Paper Trade').click().run()
    assert any('Maximum simultaneous positions' in e.value for e in app.error)
    assert len(service.ledger.rejections()) == 1
    assert len(service.ledger.all()) == 1


def test_exposure_view_reads_active_limits_without_mutation(ui):
    service, provider, _ = ui
    store=SettingsStore()
    state=store.save(changed(risk={'enforce_positions_limit':True,'maximum_simultaneous_positions':5,
                                  'enforce_portfolio_risk_limit':True}),expected_version=0)
    create(service,state)
    before=dump(service.ledger)
    app=AppTest.from_file(APP).run()
    app.radio[0].set_value('Paper Trading').run()
    assert not app.exception and not app.error
    values={m.label:m.value for m in app.metric}
    assert values['Account equity'] == '$10,000.00'
    assert values['Reserved notional'] == '$2,000.00'
    assert values['Available capital'] == '$8,000.00'
    assert values['Pending / Open'] == '1 / 0'
    assert values['Planned portfolio risk'] == '$100.00'
    assert values['Configured portfolio risk max'] == '2.5% / $250.00'
    assert values['Largest position % (base capital)'] == '20.00%'
    assert values['Remaining position slots'] == '4'
    assert values['New trades today'] == '1'
    assert values['Daily trade limit'] == '5 (not enforced)'
    assert any('America/New_York' in c.value for c in app.caption)
    app.run()
    assert dump(service.ledger) == before and not provider.calls


def test_rejection_history_is_reviewable_without_performance_trade(ui):
    service, _, _ = ui
    store = SettingsStore()
    state = store.save(changed(risk={'allow_buy': False}), expected_version=0)
    from autot.portfolio_risk.models import PortfolioRiskRejected
    import pytest
    with pytest.raises(PortfolioRiskRejected):
        create(service, state)
    before = dump(service.ledger)
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value('Paper Trading').run()
    assert not app.exception
    assert any('BUY trades are disabled' in m.value for m in app.markdown)
    assert not service.ledger.all() and dump(service.ledger) == before


def test_settings_distinguishes_configured_and_enforced_limits(ui):
    store = SettingsStore()
    store.save(changed(risk={'enforce_position_limit': True}), expected_version=0)
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value('Settings').run()
    assert not app.exception
    table = next(d.value for d in app.dataframe if 'Configured' in d.value.columns).set_index('Limit')
    assert table.loc['Risk/trade', 'Status'] == 'ENFORCED'
    assert table.loc['Max position', 'Status'] == 'ENFORCED'
    assert table.loc['Portfolio risk', 'Configured'] == '2.5%'
    assert table.loc['Portfolio risk', 'Status'] == 'INACTIVE'
    assert table.loc['Daily trade limit', 'Status'] == 'INACTIVE'


def test_journal_exposes_admission_metrics_without_changing_performance(ui):
    from autot.application.paper_journal import journal_row
    from autot.paper_trade.performance import PerformanceService
    service, _, _ = ui
    create(service, SettingsStore().load())
    report = PerformanceService(service.ledger).report()
    before = dump(service.ledger)
    row = journal_row(report['journal'][0])
    assert row['Admission'] == 'ALLOW'
    assert float(row['Planned position %']) == 20
    assert float(row['Planned trade risk %']) == 1
    assert row['Positions after admission'] == 1
    assert dump(service.ledger) == before
    assert PerformanceService(service.ledger).report() == report
