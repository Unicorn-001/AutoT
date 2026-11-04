"""Streamlit AppTest runs offline, without launching a server."""
import json

from streamlit.testing.v1 import AppTest
from autot.strategy_analysis.service import StrategyAnalysisService
from tests.test_paper_web import ui, APP
from tests.test_strategy_analysis import seed


def show():
    app=AppTest.from_file(APP).run()
    app.radio[0].set_value('Paper Trading').run()
    next(t for t in app.toggle if t.label=='Show Strategy Analysis').set_value(True).run()
    return app


def select(app,label):
    return next(x for x in app.selectbox if x.label==label)


def test_empty_strategy_analysis_safe_and_summary_first(ui):
    app=show()
    assert not app.exception and not app.error
    assert select(app,'Strategy analysis mode').value=='FORWARD_TEST'
    assert any('No closed trades' in x.value for x in app.info)
    assert any('VERY SMALL SAMPLE' in x.value for x in app.markdown)


def test_strategy_tables_mode_profile_query_and_no_mutation(ui):
    service,_,_=ui
    seed(service.ledger)
    seed(service.ledger,key='research',mode='RESEARCH',pnl='-200')
    seed(service.ledger,key='legacy',mode=None,features=False)
    with service.ledger.connection() as db:
        before=list(db.iterdump())
    app=show()
    assert not app.exception and not app.error
    assert next(m for m in app.metric if m.label=='Expectancy / trade').value=='100.00'
    assert any('By strategy'==e.label for e in app.expander)
    assert any('Profile comparison'==e.label for e in app.expander)
    assert any('signal' in df.value.columns and 'effective_weight' in df.value.columns for df in app.dataframe)
    select(app,'Strategy analysis mode').set_value('RESEARCH').run()
    assert not app.exception
    assert next(m for m in app.metric if m.label=='Expectancy / trade').value=='-200.00'
    select(app,'Strategy analysis mode').set_value('UNKNOWN_LEGACY').run()
    assert not app.exception
    assert any('Legacy trades have no stored mode' in w.value for w in app.warning)
    select(app,'Strategy analysis mode').set_value('FORWARD_TEST').run()
    app.multiselect[0].set_value(['EMA_RSI','MACD']).run()
    assert not app.exception
    assert any('EMA_RSI / MACD' in list(df.value['group']) for df in app.dataframe if 'group' in df.value.columns)
    select(app,'Analysis profile / version / configuration').set_value(1).run()
    for label,value in [('Hypothesis','Alignment may help'),('Candidate change to test','Separate research filter'),('Reason for testing','Observed cohort')]:
        next(x for x in app.text_input if x.label==label).set_value(value)
    app.run()
    assert not app.exception
    assert any(e.label=='Download DRAFT proposal' for e in app.get('download_button'))
    with service.ledger.connection() as db:
        assert list(db.iterdump())==before


def test_profile_warning_and_sample_counts(ui):
    service,_,_=ui
    seed(service.ledger)
    seed(service.ledger,key='second',profile_version=2)
    app=show()
    assert not app.exception
    assert any('Multiple profile versions' in w.value for w in app.warning)
    select(app,'Analysis profile / version / configuration').set_value(1).run()
    assert not app.exception
    assert not any('Multiple profile versions' in w.value for w in app.warning)
    assert StrategyAnalysisService(service.ledger).report()['summary'][0]['trade_count']==2
