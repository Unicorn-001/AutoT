"""Full-precision, currency-separated forward performance and bar evidence."""
from copy import deepcopy
from decimal import Decimal as D
import json

import pytest

from autot.paper_trade.ledger import Ledger
from autot.paper_trade.performance import PerformanceService, journal_entry, summarize
from tests.test_prospective_paper import setup, confirm, bar, OPEN, BAR
from tests.test_paper_audit import legacy_copy


def test_currency_separation_and_full_precision_metrics(setup):
    service, _, _ = setup
    entries = []
    for currency, market in [('USD', 'US'), ('GBP', 'UK'), ('INR', 'IN')]:
        seed = confirm(service, key=market, market=market)
        for i, pnl in enumerate(('208.12858032226612', '-94.91392822265650', '0')):
            trade = dict(seed, trade_id=f'{currency}-{i}', status='CLOSED', fill_price='100', quantity=10,
                         filled_at=OPEN.isoformat(), closed_at=(OPEN + (i + 1) * BAR).isoformat(),
                         realized_pnl=pnl, pnl_percent='999', exit_price='100', last_checked_at=OPEN.isoformat())
            entries.append(journal_entry(trade, []))
    metrics = summarize(entries)
    assert set(metrics) == {'USD', 'GBP', 'INR'}
    for currency, m in metrics.items():
        assert m['completed_trades'] == 3
        assert (m['winners'], m['losers'], m['breakeven']) == (1, 1, 1)
        assert m['win_rate'] == D(1) / 3 * 100
        assert m['gross_profit'] == D('208.12858032226612')
        assert m['gross_loss'] == D('-94.91392822265650')
        assert m['net_realized_pnl'] == D('113.21465209960962')
        assert m['average_win'] == m['gross_profit'] and m['average_loss'] == m['gross_loss']
        assert m['profit_factor'] == m['gross_profit'] / abs(m['gross_loss'])
        assert m['best_trade']['trade_id'] == currency + '-0'
        assert m['worst_trade']['trade_id'] == currency + '-1'
        assert m['average_holding_seconds'] == 600
        assert m['average_return_percent'] == D('113.21465209960962') / 10 / 3
        assert m['average_signal_rr'] == 2


@pytest.mark.parametrize('side,fill,expected', [('BUY', '102', '2'), ('BUY', '98', '-2'),
                                              ('SELL', '98', '2'), ('SELL', '102', '-2')])
def test_entry_slippage_and_rr(setup, side, fill, expected):
    service, _, _ = setup
    seed = confirm(service, side)
    trade = dict(seed, status='OPEN', fill_price=fill, filled_at=OPEN.isoformat())
    entry = journal_entry(trade, [])
    assert entry['entry_slippage_percent'] == D(expected)
    assert entry['signal_rr'] == 2
    assert entry['actual_rr'] == (D(8) / 7 if expected == '2' else D(12) / 3)
    assert seed['risk_reward_ratio'] == '2'


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_mfe_mae_open_bars_and_restart(setup, side):
    service, provider, now = setup
    trade = confirm(service, side)
    provider.bars = [bar(o=100, h=104, l=97, c=101), bar(o=101, h=103, l=96, c=99, stamp=OPEN + BAR)]
    now[0] = OPEN + 2 * BAR
    service.update_positions()
    before = service.ledger.all()
    report = PerformanceService(Ledger(service.ledger.path)).report()
    entry = report['journal'][0]
    assert entry['mfe'] == entry['mae'] == 4
    assert entry['mfe_percent'] == entry['mae_percent'] == 4
    assert entry['holding_seconds'] is None
    assert report['performance']['USD']['completed_trades'] == 0
    assert service.ledger.all() == before
    assert entry['trade_id'] == trade['trade_id']


@pytest.mark.parametrize('side,expected_mfe,expected_mae', [('BUY', 4, 3), ('SELL', 3, 4)])
def test_directional_excursions(setup, side, expected_mfe, expected_mae):
    service, provider, now = setup
    confirm(service, side)
    provider.bars = [bar(h=104, l=97)]
    now[0] = OPEN + BAR
    service.update_positions()
    entry = PerformanceService(service.ledger).report()['journal'][0]
    assert entry['mfe'] == entry['mfe_percent'] == expected_mfe
    assert entry['mae'] == entry['mae_percent'] == expected_mae


@pytest.mark.parametrize('side,high,low,mfe,mae', [('BUY', 112, 90, 0, 5), ('SELL', 112, 90, 0, 5),
                                               ('BUY', 112, 96, 10, 0), ('SELL', 104, 88, 10, 0)])
def test_exit_bar_does_not_claim_post_exit_extrema(setup, side, high, low, mfe, mae):
    service, provider, now = setup
    confirm(service, side)
    provider.bars = [bar(h=high, l=low)]
    now[0] = OPEN + BAR
    service.update_positions()
    entry = PerformanceService(service.ledger).report()['journal'][0]
    assert entry['mfe'] == mfe and entry['mae'] == mae
    assert 'lower bound' in entry['excursion_note']
    assert entry['holding_seconds'] == 0


def test_gap_exit_uses_only_open_not_remainder_of_bar(setup):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(), bar(o=90, h=200, l=1, c=100, stamp=OPEN + BAR)]
    now[0] = OPEN + 2 * BAR
    service.update_positions()
    entry = PerformanceService(service.ledger).report()['journal'][0]
    assert entry['mfe'] == 4 and entry['mae'] == 10


def test_gbp_excursions_use_pounds(setup):
    service, provider, now = setup
    trade = confirm(service, market='UK', unit='GBp')
    from autot.paper_trade.sessions import utc
    opening = utc(trade['eligible_at'])
    provider.currency, provider.bars = 'GBp', [bar(h=104, l=97, stamp=opening)]
    now[0] = opening + BAR
    service.update_positions()
    entry = PerformanceService(service.ledger).report()['journal'][0]
    assert entry['mfe'] == D('.04') and entry['mae'] == D('.03')
    assert entry['mfe_percent'] == 4 and entry['mae_percent'] == 3


def test_pre_audit_mfe_mae_unavailable_and_metrics_read_only(setup, tmp_path):
    service, provider, now = setup
    confirm(service)
    provider.bars = [bar(h=112)]
    now[0] = OPEN + BAR
    service.update_positions()
    path = tmp_path / 'legacy.db'
    legacy_copy(service, path)
    ledger = Ledger(path)
    with ledger.connection() as db:
        before = list(db.iterdump())
    report = PerformanceService(ledger).report()
    entry = report['journal'][0]
    assert entry['mfe'] is entry['mae'] is None
    assert entry['excursion_note'] == 'Unavailable for pre-audit trade'
    assert report['performance']['USD']['net_realized_pnl'] == 200
    with ledger.connection() as db:
        assert list(db.iterdump()) == before


@pytest.mark.parametrize('pnl', ['0', '10', '-10'])
def test_zero_denominators_and_outcomes(setup, pnl):
    service, _, _ = setup
    t = confirm(service)
    t.update(status='CLOSED', fill_price='100', filled_at=OPEN.isoformat(), closed_at=OPEN.isoformat(),
             realized_pnl=pnl, last_checked_at=OPEN.isoformat())
    m = summarize([journal_entry(t, [])])['USD']
    assert m['profit_factor'] == (D(0) if pnl == '-10' else None)
    assert m['average_win'] == (D(10) if pnl == '10' else None)
    assert m['average_loss'] == (D(-10) if pnl == '-10' else None)
    assert m['win_rate'] == (100 if pnl == '10' else 0)


def test_empty_report(setup):
    report = PerformanceService(setup[0].ledger).report()
    assert report == dict(journal=[], performance={}, events={})
