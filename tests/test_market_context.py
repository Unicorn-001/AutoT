from copy import deepcopy
import math

import pytest

from autot.market_context.assessment import assess, Thresholds
from autot.market_context.store import MarketContextStore, assess_opportunity
from autot.application.scan_store import ScanStore
from autot.paper_trade.ledger import Ledger


def setup(side='BUY', **changes):
    values = dict(symbol='TEST', side=side, reference_entry=100, stop_loss=99 if side == 'BUY' else 101,
                  take_profit=102 if side == 'BUY' else 98, original_rr=2, current_price=100)
    values.update(changes)
    return values


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
@pytest.mark.parametrize('offset,decision,reason', [
    (0, 'ELIGIBLE', 'SETUP_STILL_VALID'),
    (-0.2, 'ELIGIBLE', 'SETUP_STILL_VALID'),
    (3 / 2.2 - 1, 'CAUTION', 'RISK_REWARD_DETERIORATED'),
    (0.6, 'REJECT', 'RISK_REWARD_DETERIORATED'),
    (-1, 'REJECT', 'INVALID_STOP_RELATIVE_TO_CURRENT'),
    (-1.1, 'REJECT', 'INVALID_STOP_RELATIVE_TO_CURRENT'),
    (2, 'REJECT', 'TARGET_ALREADY_REACHED'),
    (2.1, 'REJECT', 'TARGET_ALREADY_REACHED'),
])
def test_directional_decisions(side, offset, decision, reason):
    a = assess(**setup(side, current_price=100 + offset * (1 if side == 'BUY' else -1)))
    assert a['decision'] == decision
    assert reason in a['reason_codes']
    if offset == 3 / 2.2 - 1:
        assert a['current_rr'] == pytest.approx(1.2)
    if a['stop_crossed'] or a['target_crossed']:
        assert a['current_rr'] is None and a['rr_deterioration'] is None


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_calculations(side):
    d = 1 if side == 'BUY' else -1
    a = assess(**setup(side, current_price=100 + 0.4 * d))
    assert a['gap_absolute'] == pytest.approx(.4)
    assert a['gap_percent'] == pytest.approx(.4)
    assert a['current_risk'] == pytest.approx(1.4)
    assert a['current_reward'] == pytest.approx(1.6)
    assert a['current_rr'] == pytest.approx(1.6 / 1.4)
    assert a['rr_deterioration'] == pytest.approx(2 - 1.6 / 1.4)
    assert a['reward_consumed_percent'] == pytest.approx(20)
    assert a['distance_to_stop_absolute'] == pytest.approx(1.4)
    assert a['distance_to_stop_percent'] == pytest.approx(1.4 / a['current_price'] * 100)
    assert a['distance_to_target_absolute'] == pytest.approx(1.6)
    assert a['distance_to_target_percent'] == pytest.approx(1.6 / a['current_price'] * 100)
    assert a['stop_crossed'] is False and a['target_crossed'] is False


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_gap_and_reward_thresholds(side):
    d = 1 if side == 'BUY' else -1
    a = assess(**setup(side, stop_loss=100 - 10*d, take_profit=100 + 20*d, current_price=100 - d))
    assert a['decision'] == 'CAUTION' and a['reason_codes'] == ['LARGE_GAP']
    assert a['reward_consumed_percent'] == 0
    # High original R:R isolates reward consumption from the R:R rule.
    a = assess(**setup(side, stop_loss=100 - .1*d, take_profit=100 + .8*d,
                      original_rr=8, current_price=100 + .3*d))
    assert a['decision'] == 'CAUTION'
    assert 'REWARD_ALREADY_CONSUMED' in a['reason_codes']


@pytest.mark.parametrize('field', ['reference_entry', 'stop_loss', 'take_profit', 'original_rr', 'current_price'])
@pytest.mark.parametrize('value', [None, math.nan, math.inf, -math.inf, 0, -1, 'bad', True])
def test_invalid_data(field, value):
    a = assess(**setup(**{field: value}))
    assert a['decision'] == 'REJECT' and a['reason_codes'] == ['INVALID_MARKET_DATA']


@pytest.mark.parametrize('side', ['BUY', 'SELL', 'HOLD'])
def test_invalid_reference_geometry(side):
    assert assess(**setup(side, stop_loss=100))['reason_codes'] == ['INVALID_MARKET_DATA']
    assert assess(**setup(side, take_profit=100))['reason_codes'] == ['INVALID_MARKET_DATA']


def test_boundaries_and_configurable_thresholds():
    for price, decision in [(100, 'ELIGIBLE'), (101, 'CAUTION'), (101.5, 'REJECT')]:
        a = assess(**setup(stop_loss=98, take_profit=104, current_price=price),
                   thresholds=Thresholds(caution_gap_percent=10))
        assert a['decision'] == decision
    a = assess(**setup(stop_loss=98, take_profit=103, original_rr=1.5))
    assert a['current_rr'] == 1.5 and a['decision'] == 'ELIGIBLE'
    a = assess(**setup(stop_loss=99, take_profit=103, original_rr=3, current_price=101),
               thresholds=Thresholds(caution_gap_percent=10, caution_reward_consumed_percent=100))
    assert a['current_rr'] == 1 and a['decision'] == 'CAUTION'
    a = assess(**setup(stop_loss=99, take_profit=104, original_rr=4, current_price=101),
               thresholds=Thresholds(caution_gap_percent=10))
    assert a['reward_consumed_percent'] == 25 and a['decision'] == 'ELIGIBLE'
    with pytest.raises(ValueError):
        Thresholds(eligible_rr_min=.5)


def test_cah_example():
    a = assess(**setup(symbol='CAH', reference_entry=272.34, stop_loss=266.8932,
                      take_profit=283.2336, current_price=275.63))
    assert a['current_rr'] == pytest.approx(.8702957605)
    assert a['decision'] == 'REJECT'


@pytest.fixture
def persisted(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOT_DATA_DIR', str(tmp_path))
    scanner = ScanStore()
    run = scanner.create(dict(market='US', universe='test', state={'profile': 'test'}))
    row = dict(symbol='TEST', signal='BUY', entry_price=100, stop_loss=99,
               take_profit=102, risk_reward_ratio=2, confidence=90, agreement=80,
               score=72, trade_quality_score=85)
    saved = dict(scan_run_id=run['scan_run_id'], outputs={'trade_opportunities': [row]})
    scanner.save(run, saved)
    return scanner, run, saved


def test_persistence_restart_and_isolation(persisted):
    scanner, run, saved = persisted
    original = deepcopy(saved)
    ledger = Ledger()
    before_scanner = scanner.path.read_bytes()
    before_paper = ledger.path.read_bytes()
    store = MarketContextStore()
    assert store.history(run['scan_run_id'], '0') == []
    a = assess_opportunity(run['scan_run_id'], 0, 100.6, assessed_at='2026-11-20T15:00:00+00:00',
                           source='MANUAL', market_session='REGULAR')
    assert MarketContextStore().history(run['scan_run_id'], '0') == [a]
    b = assess_opportunity(run['scan_run_id'], 0, None)
    assert MarketContextStore().history(run['scan_run_id'], '0') == [b, a]
    assert a['assessment_id'] != b['assessment_id']
    assert a['scanner_run_id'] == run['scan_run_id'] and a['opportunity_id'] == '0'
    assert saved == original and scanner.latest() == original
    assert scanner.path.read_bytes() == before_scanner
    assert ledger.path.read_bytes() == before_paper
    assert store.path.name == 'market_context.sqlite3'
    for run_id, index in [('missing', 0), (run['scan_run_id'], -1), (run['scan_run_id'], 1)]:
        with pytest.raises(ValueError):
            assess_opportunity(run_id, index, 100)
