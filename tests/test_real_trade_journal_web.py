from pathlib import Path
import json
import sqlite3
from streamlit.testing.v1 import AppTest

from autot.real_trade_journal.service import RealTradeJournal, status
from tests.test_real_trade_journal import scanner_db
from autot.runtime import data_dir

APP = str(Path(__file__).resolve().parents[1] / 'web_app.py')


def button(app, label):
    return next(b for b in app.button if b.label == label)


def enter(app, label, value, index=0):
    [w for w in app.text_input if w.label == label][index].set_value(value)


def start():
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value('Real Trade Journal').run()
    assert not app.exception
    return app


def test_manual_create_exit_restart_and_delete():
    app = start()
    enter(app, 'Symbol', 'APP')
    enter(app, 'Broker', 'eToro')
    enter(app, 'Autot entry price', '390.91')
    enter(app, 'Investment amount', '10')
    enter(app, 'Investment currency', 'GBP')
    button(app, 'Save Real Trade').click().run()
    assert not app.exception and not app.error
    record = RealTradeJournal().list()[0]
    assert record['actual_entry_price'] is None
    app = start()
    assert len(RealTradeJournal().list()) == 1
    button(app, f"Record Exit · APP · {record['journal_trade_id']}").click().run()
    enter(app, 'Actual entry price', '391', index=1)
    enter(app, 'Actual exit price', '383', index=1)
    enter(app, 'Gross pnl', '-.20', index=1)
    enter(app, 'Fees', '0', index=1)
    enter(app, 'Pnl currency', 'GBP', index=1)
    [w for w in app.selectbox if w.label == 'Exit reason'][1].select('STOP_LOSS')
    button(app, 'Save Execution / Record Exit').click().run()
    assert not app.exception and not app.error
    assert status(RealTradeJournal().list()[0]) == 'CLOSED'
    assert RealTradeJournal().list()[0]['autot_entry_price'] == '390.91'
    app = start()
    assert any(h.value == 'Closed Real Trades' for h in app.subheader)
    button(app, 'Cancel Real Trade').click().run()
    assert status(RealTradeJournal().list()[0]) == 'CANCELLED'
    app.checkbox[0].check().run()
    button(app, 'Delete Real Trade').click().run()
    assert not app.exception and not RealTradeJournal().list()


def test_linked_snapshot_ui_and_invalid_submission():
    path = data_dir() / 'scanner/scans.sqlite3'
    app = start()
    fixture_path = data_dir() / 'fixture.sqlite3'
    saved = scanner_db(fixture_path)
    saved['settings_state'] = {'settings': {'advanced': {'fill_model': 'NEXT_SESSION_OPEN'}}}
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO scan_runs (scan_run_id, payload, result) VALUES (?,?,?)',
                   ('run-1', '{}', json.dumps(saved)))
    before = path.read_bytes()
    app.run()
    app.selectbox[0].select('run-1:0').run()
    assert not any(w.label in ('Autot entry price', 'Autot execution model') for w in app.text_input)
    enter(app, 'Broker', 'eToro')
    enter(app, 'Actual entry price', 'NaN')
    button(app, 'Save Real Trade').click().run()
    assert app.error and not RealTradeJournal().list()
    enter(app, 'Actual entry price', '')
    button(app, 'Save Real Trade').click().run()
    assert not app.exception and not app.error
    assert RealTradeJournal().list()[0]['scan_run_id'] == 'run-1'
    assert RealTradeJournal().list()[0]['autot_execution_model'] == 'NEXT_SESSION_OPEN'
    assert app.table[0].value.set_index('Comparison').loc['AutoT execution model', 'Value'] == 'NEXT_SESSION_OPEN'
    assert path.read_bytes() == before


def test_execution_comparison_manual_app_and_restart():
    app = start()
    enter(app, 'Symbol', 'APP')
    enter(app, 'Broker', 'eToro')
    enter(app, 'Autot execution model', 'NEXT_SESSION_OPEN')
    enter(app, 'Autot entry price', '390.91')
    enter(app, 'Actual entry price', '390.77')
    enter(app, 'Entry timestamp', '2026-11-19T14:46:00Z')
    enter(app, 'Actual exit price', '383.09')
    enter(app, 'Exit timestamp', '2026-11-19T15:00:00Z')
    enter(app, 'Investment amount', '13.05')
    enter(app, 'Investment currency', 'USD')
    enter(app, 'Net pnl', '-0.26')
    enter(app, 'Pnl currency', 'USD')
    reason = ('Real eToro trade used a limit order near the AutoT signal/reference price. '
              'AutoT paper execution model is NEXT_SESSION_OPEN. The limit filled after '
              'the stock had gapped up and subsequently reversed.')
    next(w for w in app.selectbox if w.label == 'Real order type').select('LIMIT')
    next(w for w in app.selectbox if w.label == 'Execution match status').select('MISMATCHED')
    next(w for w in app.selectbox if w.label == 'Exit reason').select('STOP_LOSS')
    next(w for w in app.text_area if w.label == 'Execution mismatch reason').set_value(reason)
    button(app, 'Save Real Trade').click().run()
    assert not app.exception and not app.error
    assert any(h.value == 'Execution Comparison' for h in app.subheader)
    table = app.table[0].value.set_index('Comparison')['Value'].to_dict()
    assert table['AutoT execution model'] == 'NEXT_SESSION_OPEN'
    assert table['Real order type'] == 'LIMIT'
    assert table['Execution match status'] == 'MISMATCHED'
    assert table['Mismatch reason'] == reason
    assert table['Actual real fill'] == '390.77'
    assert table['Signal/reference price'] == '390.91'
    assert table['Next-session open price'] == 'Unknown'
    assert table['Gap from signal to open (%)'] == 'Unknown'
    assert table['Entry slippage (absolute)'] == '-0.14'
    app = start()
    assert app.table[0].value.set_index('Comparison')['Value'].to_dict() == table
    # Synthetic opening value tests UI calculation only; not an assertion about APP's open.
    enter(app, 'Actual market open price', '400', index=1)
    [w for w in app.selectbox if w.label == 'Real order type'][1].select('MARKET')
    [w for w in app.selectbox if w.label == 'Execution match status'][1].select('MATCHED')
    button(app, 'Save Execution / Record Exit').click().run()
    assert not app.exception and not app.error
    table = app.table[0].value.set_index('Comparison')['Value'].to_dict()
    assert table['Gap from signal to open (absolute)'] == '9.09'
    assert table['Real order type'] == 'MARKET'
    assert table['Execution match status'] == 'MATCHED'
    assert table['AutoT execution model'] == 'NEXT_SESSION_OPEN'
