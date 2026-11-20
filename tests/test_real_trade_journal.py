from copy import deepcopy
from decimal import Decimal
import json
import sqlite3

import pytest

from autot.real_trade_journal.service import RealTradeJournal, metrics, status
from autot.real_trade_journal.scanner import opportunities, create_linked


def create(journal, **overrides):
    values = dict(symbol='APP', side='BUY', broker='eToro',
                  snapshot=dict(autot_entry_price='390.91', autot_stop_loss='383.0918',
                                autot_take_profit='406.5464', autot_risk_reward_ratio=2, trade_quality='83.30'),
                  investment_amount=10, investment_currency='GBP')
    values.update(overrides)
    return journal.create(**values)


def test_initialization_persistence_crud_and_separation(tmp_path):
    journal = RealTradeJournal()
    assert journal.path == tmp_path / 'runtime/real_trade_journal/real_trade_journal.sqlite3'
    assert not (tmp_path / 'runtime/paper_trading/ledger.sqlite3').exists()
    with journal.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
    record = create(journal)
    assert RealTradeJournal().get(record['journal_trade_id']) == record
    updated = journal.update(record['journal_trade_id'], notes='Broker statement checked', actual_entry_price=391)
    assert updated['created_at'] == record['created_at']
    assert updated['updated_at'] >= record['updated_at']
    assert RealTradeJournal().list() == [updated]
    cancelled = journal.cancel(record['journal_trade_id'])
    assert status(cancelled) == 'CANCELLED'
    journal.delete(record['journal_trade_id'])
    assert journal.list() == []
    with pytest.raises(KeyError):
        journal.get(record['journal_trade_id'])


def test_incomplete_app_does_not_invent_results():
    record = create(RealTradeJournal(), exit_reason='STOP_LOSS')
    assert status(record) == 'OPEN / INCOMPLETE'
    for field in ('actual_entry_price', 'actual_exit_price', 'fees', 'gross_pnl', 'net_pnl'):
        assert record[field] is None
    derived = metrics(record)
    assert derived['net_pnl'] is None and derived['actual_return_percent'] is None
    assert Decimal(derived['planned_stop_distance_percent']) == 2
    assert Decimal(derived['planned_target_distance_percent']) == 4


@pytest.mark.parametrize('side,exit_price,expected', [('BUY', 110, 10), ('SELL', 90, 10), ('SELL', 110, -10)])
def test_closing_slippage_and_price_returns(side, exit_price, expected):
    journal = RealTradeJournal()
    record = create(journal, side=side, snapshot={'autot_entry_price': 80}, actual_entry_price=100,
                    entry_timestamp='2026-11-19T15:00:00+01:00')
    assert status(record) == 'OPEN / INCOMPLETE'
    record = journal.update(record['journal_trade_id'], actual_exit_price=exit_price,
                            exit_timestamp='2026-11-19T16:00:00Z', exit_reason='MANUAL')
    assert status(record) == 'CLOSED'
    assert record['entry_timestamp'] == '2026-11-19T14:00:00+00:00'
    derived = metrics(record)
    assert Decimal(derived['entry_slippage_absolute']) == 20
    assert Decimal(derived['entry_slippage_percent']) == 25
    assert Decimal(derived['actual_return_percent']) == expected
    assert derived['holding_duration_seconds'] == 7200
    assert derived['net_pnl'] is None


def test_cash_pnl_returns_currency_and_manual_override():
    journal = RealTradeJournal()
    record = create(journal, gross_pnl=2, fees='.25', pnl_currency='GBP')
    assert metrics(record)['net_pnl'] == '1.75'
    assert Decimal(metrics(record)['actual_return_percent']) == Decimal('17.5')
    record = journal.update(record['journal_trade_id'], net_pnl='1.60')
    assert Decimal(metrics(record)['actual_return_percent']) == 16
    record = journal.update(record['journal_trade_id'], pnl_currency='USD')
    assert metrics(record)['actual_return_percent'] is None
    record = journal.update(record['journal_trade_id'], net_pnl=None, fees=None)
    assert metrics(record)['net_pnl'] is None


@pytest.mark.parametrize('overrides', [
    {'side': 'HOLD'}, {'side': 'buy'}, {'symbol': ''}, {'broker': ' '},
    {'actual_entry_price': 0}, {'actual_entry_price': -1}, {'actual_entry_price': True},
    {'investment_amount': 'NaN'}, {'gross_pnl': 'Infinity'}, {'fees': -1},
    {'fees': 'oops'}, {'investment_currency': 'pounds'}, {'investment_currency': None},
    {'gross_pnl': 1}, {'exit_reason': 'UNKNOWN'}, {'actual_exit_price': 20},
    {'entry_timestamp': '2026-11-19T00:00:00'}, {'entry_timestamp': 'nonsense'},
    {'entry_timestamp': '2026-11-19T00:00:00Z', 'exit_timestamp': '2026-11-18T00:00:00Z'},
    {'snapshot': {'autot_entry_price': 0}}, {'snapshot': {'confidence': 'NaN'}},
    {'unexpected': 'value'},
])
def test_invalid_values(overrides):
    journal = RealTradeJournal()
    with pytest.raises(ValueError):
        create(journal, **overrides)
    assert journal.list() == []


def test_invalid_update_is_atomic_and_snapshot_locked():
    journal = RealTradeJournal()
    record = create(journal)
    for patch in ({'actual_entry_price': -1}, {'autot_entry_price': 1}, {'side': 'SELL'}, {'broker': 'other'}):
        with pytest.raises(ValueError):
            journal.update(record['journal_trade_id'], **patch)
        assert journal.get(record['journal_trade_id']) == record


def scanner_db(path):
    row = dict(symbol='APP', signal='BUY', entry_price=390.91, stop_loss=383.0918,
               take_profit=406.5464, risk_reward_ratio=2, confidence=80, agreement=90,
               trade_quality_score=83.30, score=55, market_regime='BULLISH')
    saved = {'outputs': {'trade_opportunities': [row]},
             'paper_signal_context': {'APP': {'signal_time': '2026-11-19T14:00:00Z'}}}
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS scan_runs (scan_run_id TEXT, result TEXT)')
        db.execute('INSERT INTO scan_runs (scan_run_id, result) VALUES (?,?)', ('run-1', json.dumps(saved)))
    return saved


def test_scanner_snapshot_immutable_and_source_untouched(tmp_path):
    path = tmp_path / 'scanner.sqlite3'
    saved = scanner_db(path)
    before = path.read_bytes()
    choice = opportunities(path)[0]
    journal = RealTradeJournal()
    record = create_linked(journal, choice['key'], broker='eToro', scanner_path=path)
    assert path.read_bytes() == before
    assert record['scan_run_id'] == 'run-1'
    assert record['trade_quality'] == '83.3'
    assert record['signal_timestamp'] == '2026-11-19T14:00:00+00:00'
    original = deepcopy(record)
    choice['snapshot']['autot_entry_price'] = 1
    saved['outputs']['trade_opportunities'][0]['entry_price'] = 2
    with sqlite3.connect(path) as db:
        db.execute('UPDATE scan_runs SET result=?', (json.dumps(saved),))
    assert RealTradeJournal().get(record['journal_trade_id']) == original
    record['autot_entry_price'] = '3'
    assert journal.get(record['journal_trade_id']) == original
    with pytest.raises(ValueError):
        create_linked(journal, 'missing', broker='eToro', scanner_path=path)


def test_missing_scanner_is_not_initialized(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    assert opportunities(path) == []
    assert not path.exists()


def test_existing_paper_ledger_untouched(tmp_path):
    paper = tmp_path / 'runtime/paper_trading/ledger.sqlite3'
    paper.parent.mkdir(parents=True)
    with sqlite3.connect(paper) as db:
        db.execute('CREATE TABLE existing_results (result TEXT)')
        db.execute('INSERT INTO existing_results VALUES (?)', ('unchanged paper result',))
    original = paper.read_bytes()
    journal = RealTradeJournal()
    record = create(journal)
    journal.update(record['journal_trade_id'], actual_entry_price='390.91000001')
    journal.cancel(record['journal_trade_id'])
    journal.delete(record['journal_trade_id'])
    assert paper.read_bytes() == original


def test_negative_slippage_and_unknown_fees():
    record = create(RealTradeJournal(), snapshot={'autot_entry_price': 100},
                    actual_entry_price=99, gross_pnl=-2, pnl_currency='GBP')
    result = metrics(record)
    assert result['entry_slippage_absolute'] == '-1'
    assert result['entry_slippage_percent'] == '-1.00'
    assert result['net_pnl'] is None


def test_future_schema_is_rejected_without_change(tmp_path):
    path = tmp_path / 'future.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=3')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='schema version'):
        RealTradeJournal(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize('order_type', ['MARKET', 'LIMIT', 'STOP', 'OTHER'])
@pytest.mark.parametrize('match_status', ['MATCHED', 'MISMATCHED', 'UNKNOWN'])
def test_execution_fields_persist_and_update(order_type, match_status):
    journal = RealTradeJournal()
    record = create(journal, snapshot={'autot_execution_model': 'NEXT_SESSION_OPEN'},
                    real_order_type=order_type, execution_match_status=match_status,
                    execution_mismatch_reason='Manual broker comparison', actual_market_open_price='401.25')
    assert record['real_order_type'] == order_type
    assert record['execution_match_status'] == match_status
    assert record['autot_execution_model'] == 'NEXT_SESSION_OPEN'
    assert record['actual_market_open_price'] == '401.25'
    assert record['execution_mismatch_reason'] == 'Manual broker comparison'
    assert RealTradeJournal().get(record['journal_trade_id']) == record
    updated = journal.update(record['journal_trade_id'], real_order_type='LIMIT',
                             execution_match_status='MISMATCHED', execution_mismatch_reason='Filled after open')
    assert RealTradeJournal().get(record['journal_trade_id']) == updated
    with pytest.raises(ValueError, match='immutable'):
        journal.update(record['journal_trade_id'], autot_execution_model='OTHER')


@pytest.mark.parametrize('fields', [
    {'real_order_type': 'limit'}, {'real_order_type': 'UNKNOWN'},
    {'execution_match_status': 'matched'}, {'execution_match_status': 'INVALID'},
    {'execution_match_status': True}, {'actual_market_open_price': 0},
    {'actual_market_open_price': -10}, {'actual_market_open_price': 'NaN'},
    {'actual_market_open_price': 'Infinity'}, {'actual_market_open_price': True},
    {'execution_mismatch_reason': 123},
])
def test_invalid_execution_comparison(fields):
    journal = RealTradeJournal()
    with pytest.raises(ValueError):
        create(journal, **fields)
    record = create(journal)
    with pytest.raises(ValueError):
        journal.update(record['journal_trade_id'], **fields)
    assert journal.get(record['journal_trade_id']) == record


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
@pytest.mark.parametrize('opening,gap,percent', [(110, 10, 10), (90, -10, -10), (100, 0, 0)])
def test_signal_to_open_gap(side, opening, gap, percent):
    record = create(RealTradeJournal(), side=side, snapshot={'autot_entry_price': 100},
                    actual_market_open_price=opening)
    result = metrics(record)
    assert Decimal(result['gap_from_signal_to_open_absolute']) == gap
    assert Decimal(result['gap_from_signal_to_open_percent']) == percent
    assert record['execution_match_status'] == 'UNKNOWN'


@pytest.mark.parametrize('snapshot,opening', [({}, 100), ({'autot_entry_price': 100}, None), ({}, None)])
def test_missing_gap_inputs(snapshot, opening):
    record = create(RealTradeJournal(), snapshot=snapshot, actual_market_open_price=opening)
    assert metrics(record)['gap_from_signal_to_open_absolute'] is None
    assert metrics(record)['gap_from_signal_to_open_percent'] is None


def test_limit_near_signal_does_not_automatically_classify():
    record = create(RealTradeJournal(), snapshot={'autot_entry_price': '390.91',
                    'autot_execution_model': 'NEXT_SESSION_OPEN'},
                    real_order_type='LIMIT', actual_entry_price='390.77')
    assert record['execution_match_status'] == 'UNKNOWN'
    assert record['execution_mismatch_reason'] is None
    assert Decimal(metrics(record)['entry_slippage_absolute']) == Decimal('-.14')


def test_execution_snapshot_from_historical_scan_and_read_only_ledgers(tmp_path):
    path = tmp_path / 'scan.sqlite3'
    saved = scanner_db(path)
    saved['settings_state'] = {'settings': {'advanced': {'fill_model': 'NEXT_SESSION_OPEN'}}}
    with sqlite3.connect(path) as db:
        db.execute('UPDATE scan_runs SET result=?', (json.dumps(saved),))
    paper = tmp_path / 'runtime/paper_trading/ledger.sqlite3'
    paper.parent.mkdir(parents=True)
    with sqlite3.connect(paper) as db:
        db.execute('CREATE TABLE existing_results (result TEXT)')
        db.execute("INSERT INTO existing_results VALUES ('original')")
    scan_before, paper_before = path.read_bytes(), paper.read_bytes()
    journal = RealTradeJournal()
    record = create_linked(journal, 'run-1:0', broker='eToro', scanner_path=path, real_order_type='LIMIT')
    assert record['autot_execution_model'] == 'NEXT_SESSION_OPEN'
    journal.update(record['journal_trade_id'], execution_match_status='MISMATCHED', actual_market_open_price=400)
    assert path.read_bytes() == scan_before
    assert paper.read_bytes() == paper_before
    saved['settings_state']['settings']['advanced']['fill_model'] = 'DIFFERENT_FUTURE_MODEL'
    with sqlite3.connect(path) as db:
        db.execute('UPDATE scan_runs SET result=?', (json.dumps(saved),))
    assert RealTradeJournal().get(record['journal_trade_id'])['autot_execution_model'] == 'NEXT_SESSION_OPEN'
    del saved['settings_state']
    with sqlite3.connect(path) as db:
        db.execute('UPDATE scan_runs SET result=?', (json.dumps(saved),))
    # Missing historical configuration must not fall back to the current default.
    assert create_linked(journal, 'run-1:0', broker='eToro', scanner_path=path)['autot_execution_model'] is None


def test_v1_migration_preserves_payloads_and_timestamps(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    journal = RealTradeJournal(path)
    record = create(journal)
    with journal.connection() as db:
        row = db.execute('SELECT * FROM real_trades').fetchone()
        snapshot, execution = json.loads(row['snapshot']), json.loads(row['execution'])
        snapshot.pop('autot_execution_model')
        for field in ('real_order_type', 'execution_match_status', 'execution_mismatch_reason', 'actual_market_open_price'):
            execution.pop(field)
        db.execute('UPDATE real_trades SET snapshot=?, execution=?', (json.dumps(snapshot), json.dumps(execution)))
        db.execute('PRAGMA user_version=1')
        original_row = tuple(db.execute('SELECT * FROM real_trades').fetchone())
    for _ in range(2):
        journal = RealTradeJournal(path)
        with journal.connection() as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 2
            assert tuple(db.execute('SELECT * FROM real_trades').fetchone()) == original_row
        loaded = journal.get(record['journal_trade_id'])
        assert loaded['execution_match_status'] == 'UNKNOWN'
        assert loaded['autot_execution_model'] is None
        assert loaded['actual_market_open_price'] is None
    updated = journal.update(record['journal_trade_id'], real_order_type='LIMIT', execution_match_status='MISMATCHED')
    assert updated['created_at'] == record['created_at']
    with journal.connection() as db:
        assert db.execute('SELECT snapshot FROM real_trades').fetchone()[0] == original_row[6]
