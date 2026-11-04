"""Offline evidence tests with durable ledgers and known outcomes."""
import csv
import io
import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from autot.paper_trade.ledger import Ledger
from autot.paper_trade.performance import journal_entry
from autot.paper_trade.service import build_snapshot, initial_state, STATE_FIELDS
from autot.paper_trade.sessions import SessionCalendar
from autot.settings.models import SettingsState, TradeSettingsSnapshot, Strategies
from autot.strategy_analysis.models import ExperimentProposal
from autot.strategy_analysis.service import (StrategyAnalysisService, metrics, band, sample_label, export_csv,
                                             DEFAULT_BINS, risk_features, combination_report)
from autot.strategy_analysis.snapshot import capture_strategies, contributions
from tests.test_prospective_paper import opportunity, CREATED, OPEN, BAR, setup, confirm, bar as price_bar


def feature(strategy='EMA_RSI', signal='BUY', enabled=True):
    return dict(strategy_id=strategy, signal=signal, enabled=enabled, effective_weight='1.2',
                regime_weight='1.2', manual_override=None, original_confidence='1', weighted_confidence='1.2')


def seed(ledger, *, key='one', pnl='100', side='BUY', market='US', mode='FORWARD_TEST',
         regime='STRONG_UPTREND', features=True, profile_version=1, config_hash=None, **updates):
    row = opportunity(side, {'US': 'AAPL', 'UK': 'AZN.L', 'IN': 'INFY.NS'}[market])
    row['market_regime'] = regime
    if features:
        row['strategy_features'] = dict(version=1, strategies=[feature('EMA_RSI', side), feature('MACD', side),
            feature('SUPERTREND', side), feature('BOLLINGER', 'SELL' if side == 'BUY' else 'BUY'), feature('ADX', 'HOLD')])
    snap = build_snapshot(row, market=market, index_name='Test', signal_time=CREATED-timedelta(hours=1),
                          timeframe='1d', quote_currency={'US': 'USD', 'UK': 'GBP', 'IN': 'INR'}[market],
                          capital=10000, risk_percent=1, metadata={}, created_at=CREATED, calendar=SessionCalendar())
    # Arbitrary cohort metadata in a legacy import fixture, not a newly validated admission.
    if mode is not None:
        snap.update(mode=mode)
    snap.update(strategy_profile_id='control', strategy_profile_name='Control', strategy_profile_version=profile_version,
                strategy_config_hash=config_hash or 'hash-a')
    snap.update(updates)
    trade = ledger.confirm(key, snap, initial_state(), create_another=True)
    state = {k: trade[k] for k in STATE_FIELDS}
    state.update(status='CLOSED', fill_price='100', filled_at=OPEN.isoformat(), closed_at=(OPEN+BAR).isoformat(),
                 realized_pnl=str(pnl), exit_price=str(100+D(pnl)/20*(1 if side == 'BUY' else -1)),
                 exit_reason='MANUAL_CLOSE', last_checked_at=OPEN.isoformat())
    return ledger.update(trade, state)


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path/'analysis.db')


def test_metrics_exact_expectancy_profit_factor_payoff_and_duration(ledger):
    entries = [journal_entry(seed(ledger, key=str(i), pnl=p), []) for i,p in enumerate(['200', '-100', '0'])]
    m = metrics(entries)
    assert (m['trade_count'], m['wins'], m['losses'], m['breakeven']) == (3, 1, 1, 1)
    assert m['gross_profit'] == 200 and m['gross_loss'] == 100 and m['net_pnl'] == 100
    assert m['profit_factor'] == 2 and m['payoff_ratio'] == 2
    assert m['expectancy'] == m['average_pnl'] == D(100)/3
    assert m['average_win'] == 200 and m['average_loss'] == -100
    assert m['average_return'] == D(5)/3
    assert m['best_trade'] == 200 and m['worst_trade'] == -100
    assert m['average_holding_seconds'] == 300
    assert m['average_mfe_percent'] is None and m['excursion_sample'] == 0


@pytest.mark.parametrize('pnl,pf,payoff', [('0',None,None), ('100',None,None), ('-100',D(0),None)])
def test_one_sided_outcomes(ledger,pnl,pf,payoff):
    m=metrics([journal_entry(seed(ledger,pnl=pnl),[])])
    assert m['profit_factor'] == pf and m['payoff_ratio'] == payoff


def test_empty_metrics():
    m=metrics([])
    assert m['trade_count'] == 0 and m['expectancy'] is None and m['realized_close_drawdown'] is None


@pytest.mark.parametrize('side', ['BUY','SELL'])
def test_side_segmentation(ledger,side):
    seed(ledger,side=side)
    report=StrategyAnalysisService(ledger).report()
    assert report['sections']['side'][0]['group'] == (side,)
    assert report['sections']['side'][0]['net_pnl'] == 100


@pytest.mark.parametrize('regime,expected', [('STRONG_UPTREND','STRONG_UPTREND'),
    ('STRONG_DOWNTREND','STRONG_DOWNTREND'),('SIDEWAYS_OR_WEAK_TREND','SIDEWAYS_OR_WEAK_TREND'),('TREND','unknown'),(None,'unknown')])
def test_regime_segmentation(ledger,regime,expected):
    seed(ledger,regime=regime)
    r=StrategyAnalysisService(ledger).report()
    assert r['sections']['regime'][0]['group'] == (expected,)
    assert any(x['group'] == ('EMA_RSI','aligned',expected) for x in r['sections']['strategy_regime'])


@pytest.mark.parametrize('side',['BUY','SELL'])
def test_strategy_alignment_opposition_hold(ledger,side):
    seed(ledger,side=side)
    rows={x['group']:x for x in StrategyAnalysisService(ledger).report()['sections']['strategy']}
    assert rows[('EMA_RSI','aligned')]['trade_count'] == 1
    assert rows[('BOLLINGER','opposed')]['net_pnl'] == 100
    assert rows[('ADX','HOLD')]['win_rate'] == 100


def test_pairs_triples_queries_and_threshold(ledger):
    seed(ledger)
    service=StrategyAnalysisService(ledger)
    assert service.report()['sections']['combinations'] == []
    combos=service.report(minimum_sample=1)['sections']['combinations']
    assert len(combos)==4  # three pairs and one triple, only aligned enabled votes
    assert {len(r['group']) for r in combos} == {2,3}
    assert service.report(requested_combination=['MACD','EMA_RSI'])['sections']['combinations'][0]['trade_count']==1
    assert service.report(requested_combination=['EMA_RSI','BOLLINGER'])['sections']['combinations']==[]
    with pytest.raises(ValueError):
        combination_report([],sizes=(4,))


@pytest.mark.parametrize('field,edges', list(DEFAULT_BINS.items()))
def test_generated_band_boundaries(field,edges):
    assert band(None,edges)=='UNAVAILABLE'
    assert band(D(str(edges[0]))-1,edges).startswith('<')
    for low, high in zip(edges,edges[1:]):
        assert band(low,edges)==f'{D(str(low)):g}–<{D(str(high)):g}'
    assert band(edges[-1],edges)==f'{D(str(edges[-1])):g}+'


@pytest.mark.parametrize('field,value,expected', [('confidence','75','75–<80'),('agreement','100','100+'),
    ('trade_quality','90','90+'),('historical_score','40','40–<60'),('historical_score',None,'UNAVAILABLE')])
def test_score_band_reports(ledger,field,value,expected):
    seed(ledger,**{field:value})
    assert StrategyAnalysisService(ledger).report()['sections'][field][0]['group']==(expected,)


def test_custom_bins_and_invalid_bins(ledger):
    seed(ledger)
    service=StrategyAnalysisService(ledger)
    assert service.report(bins={'confidence':(0,90)})['sections']['confidence'][0]['group']==('0–<90',)
    for edges in ((),(1,1),(2,1)):
        with pytest.raises(ValueError):
            band(1,edges)
    with pytest.raises(ValueError):
        service.report(bins={'bogus':(0,1)})


@pytest.mark.parametrize('count,label', [(0,'VERY SMALL SAMPLE'),(19,'VERY SMALL SAMPLE'),(20,'SMALL SAMPLE'),
    (49,'SMALL SAMPLE'),(50,'EARLY EVIDENCE'),(99,'EARLY EVIDENCE'),(100,'MORE MEANINGFUL'),
    (149,'MORE MEANINGFUL'),(150,'STRONGER SAMPLE FOR REVIEW')])
def test_sample_labels(count,label):
    assert sample_label(count)==label


def test_profile_version_hash_and_mode_separation(ledger):
    seed(ledger,key='a')
    seed(ledger,key='b',profile_version=2)
    seed(ledger,key='c',config_hash='hash-b')
    seed(ledger,key='research',mode='RESEARCH',pnl='-500')
    seed(ledger,key='unknown',mode=None,pnl='-900')
    service=StrategyAnalysisService(ledger)
    report=service.report()
    assert report['summary'][0]['net_pnl']==300 and report['mixed_profiles']
    assert len(report['sections']['profile'])==3
    assert report['completeness']['excluded_unknown_mode']==1
    assert service.report(profile=report['available_profiles'][0])['summary'][0]['trade_count']==1
    assert service.report(mode='RESEARCH')['summary'][0]['net_pnl']==-500
    assert service.report(mode='UNKNOWN_LEGACY')['summary'][0]['net_pnl']==-900
    with pytest.raises(ValueError):
        service.report(mode='ALL')


def test_currencies_never_mixed(ledger):
    entries=[journal_entry(seed(ledger,key=m,market=m),[]) for m in ('US','UK','IN')]
    with pytest.raises(ValueError,match='mixed currencies'):
        metrics(entries)
    report=StrategyAnalysisService(ledger).report(minimum_sample=1)
    assert {r['currency'] for r in report['summary']}=={'USD','GBP','INR'}
    for rows in report['sections'].values():
        assert all(r['trade_count']==1 and r['net_pnl']==100 for r in rows)


def test_legacy_completeness_and_stored_partial_votes(ledger):
    t=seed(ledger,features=False,historical_score=None,strategy_profile_id=None)
    assert contributions(t)==[]
    report=StrategyAnalysisService(ledger).report()
    c=report['completeness']
    assert c['strategy_signals']==c['complete_strategy_features']==c['mfe_mae']==c['profile_metadata']==c['historical_score']==0
    t['original_opportunity']['macd_signal']='SELL'
    votes=contributions(t)
    assert len(votes)==1 and votes[0].opposed_final_signal and votes[0].effective_weight is None
    assert ledger.get(t['trade_id'])['original_opportunity'].get('macd_signal') is None


def test_disabled_and_missing_not_hold():
    trade=dict(side='BUY',strategy_features=dict(version=1,strategies=[feature(enabled=False,signal=None),feature('MACD',signal=None)]))
    assert not any(c.held or c.aligned_with_final_signal or c.opposed_final_signal for c in contributions(trade))


def test_risk_derived_only_from_trade_prices(ledger):
    t=seed(ledger)
    assert risk_features(t)==dict(planned_risk_percent=D(1),position_percent=D(20),actual_fill_risk_percent=D(1))
    t['fill_price']='102'
    assert risk_features(t)['actual_fill_risk_percent']==D('1.4')
    del t['account_capital']
    assert all(v is None for v in risk_features(t).values())


def test_drawdown_chronological_simultaneous_closes(ledger):
    rows=[journal_entry(seed(ledger,key=str(i),pnl=p),[]) for i,p in enumerate(['100','-200','100'])]
    for i,r in enumerate(rows):
        r['trade']['closed_at']=(OPEN+(i+1)*BAR).isoformat()
    assert metrics(list(reversed(rows)))['realized_close_drawdown']==200
    for r in rows:
        r['trade']['closed_at']=(OPEN+BAR).isoformat()
    assert metrics(rows)['realized_close_drawdown']==0


def test_reports_and_exports_never_mutate_any_table(ledger):
    seed(ledger)
    with ledger.connection() as db:
        before=list(db.iterdump())
    service=StrategyAnalysisService(ledger)
    report=service.report(minimum_sample=1)
    copied=deepcopy(report)
    for name in ('trades','summary',*report['sections']):
        exported=list(csv.DictReader(io.StringIO(export_csv(report,name))))
        assert all(row['mode']=='FORWARD_TEST' and row['currency']=='USD' for row in exported)
    assert report==copied
    with ledger.connection() as db:
        assert list(db.iterdump())==before
    assert service.report()==StrategyAnalysisService(Ledger(ledger.path)).report()


def test_new_trade_snapshot_durable_and_independent(setup):
    service,_,_=setup
    from autot.strategies.manager.strategy_manager import StrategyManager
    from autot.strategy_weights.strategy_weight_engine import StrategyWeightEngine
    from autot.indicators.technical_indicators import add_all_indicators
    from tests.settings_data import prices
    settings=Strategies()
    weighted=StrategyWeightEngine.apply_weights(StrategyManager(settings).run_all(add_all_indicators(prices('up'))), 'STRONG_UPTREND',settings)
    features=capture_strategies(weighted,settings,'STRONG_UPTREND')
    assert len(features['strategies'])==10
    row=opportunity(); row['strategy_features']=features
    t=service.confirm('snapshot',row,market='US',index_name='Example',signal_time=CREATED-timedelta(hours=1),
                      timeframe='1d',quote_currency='USD',capital=10000,risk_percent=1,metadata={})
    preserved=deepcopy(features)
    features['strategies'][0]['signal']='SELL'
    assert Ledger(service.ledger.path).get(t['trade_id'])['strategy_features']==preserved
    assert t['strategy_config_hash']==TradeSettingsSnapshot.from_state(SettingsState()).strategy_config_hash
    assert t['portfolio_risk_decision']['decision']=='ALLOW'


@pytest.mark.parametrize('side',['BUY','SELL'])
def test_audited_mfe_mae_only_when_processed_bars_available(setup,side):
    service,provider,now=setup
    confirm(service,side)
    provider.bars=[price_bar(h=112 if side=='BUY' else 104,l=96 if side=='BUY' else 89)]
    now[0]=OPEN+BAR
    service.update_positions()
    r=StrategyAnalysisService(service.ledger).report()
    assert r['completeness']['mfe_mae']==1
    assert r['summary'][0]['average_mfe_percent']==10
    assert 'lower bound' in r['journal'][0]['excursion_note']


@pytest.mark.parametrize('status',['DRAFT','READY_FOR_RESEARCH','RESEARCH_ACTIVE','REVIEWED','PROMOTED','REJECTED'])
def test_experiment_model_statuses_have_no_side_effects(status):
    p=ExperimentProposal(hypothesis='A cohort may differ',baseline_profile='control / 1 / hash',candidate_change='Test separately',
        reason='Observed association',supporting_sample=5,metrics={'USD_expectancy':'1.2'},status=status)
    assert ExperimentProposal.model_validate_json(p.model_dump_json())==p
    with pytest.raises(ValidationError):
        p.status='PROMOTED'


def test_open_trades_excluded(setup):
    service,_,_=setup
    confirm(service)
    assert StrategyAnalysisService(service.ledger).report()['summary']==[]


def test_observations_small_samples_not_recommendations(ledger):
    seed(ledger)
    r=StrategyAnalysisService(ledger).report()
    assert r['observations'] and all(x['kind']=='INSUFFICIENT SAMPLE' for x in r['observations'])
    assert all('not a settings recommendation' in x['text'] for x in r['observations'])


def test_csv_unavailable_and_injection_safe(ledger):
    seed(ledger,strategy_profile_name='=HYPERLINK("bad")')
    rows=list(csv.DictReader(io.StringIO(export_csv(StrategyAnalysisService(ledger).report()))))
    assert rows[0]['mfe']=='UNAVAILABLE'
    assert rows[0]['strategy_profile_name'].startswith("'=")


def test_capture_preserves_real_weight_and_manual_override_without_recalculation():
    config=Strategies().model_dump()
    config['MACD']['weight']=1.7
    config['ADX']['enabled']=False
    settings=Strategies.model_validate(config)
    weighted=[dict(strategy='MACD_Strategy',signal='SELL',weight=1.7,original_confidence=.8,confidence=1.36)]
    before=deepcopy(weighted)
    snapshot=capture_strategies(weighted,settings,'STRONG_UPTREND')
    macd=next(s for s in snapshot['strategies'] if s['strategy_id']=='MACD')
    assert macd['effective_weight']==macd['manual_override']=='1.7'
    assert macd['regime_weight']=='1.2' and macd['weighted_confidence']=='1.36'
    adx=next(s for s in snapshot['strategies'] if s['strategy_id']=='ADX')
    assert not adx['enabled'] and adx['signal'] is None and adx['effective_weight'] is None
    assert weighted==before


@pytest.mark.parametrize('problem',['duplicate','disabled_signal','negative_weight','version'])
def test_snapshot_validation(problem):
    from autot.strategy_analysis.models import TradeFeatureSnapshot
    snap=dict(version=1,strategies=[feature()])
    if problem=='duplicate':
        snap['strategies'].append(feature())
    elif problem=='disabled_signal':
        snap['strategies'][0]['enabled']=False
    elif problem=='negative_weight':
        snap['strategies'][0]['effective_weight']=-1
    else:
        snap['version']=2
    with pytest.raises(ValidationError):
        TradeFeatureSnapshot.model_validate(snap)


def test_historical_rows_and_settings_are_never_reconstructed(ledger,monkeypatch):
    from autot.settings.store import SettingsStore
    def forbidden(*args,**kwargs):
        raise AssertionError('Analytics must never load current settings')
    for symbol in ('MRNA','MPC','ULTA'):
        seed(ledger,key=symbol,features=False,mode=None,strategy_profile_id=None,
             strategy_profile_name=None,strategy_profile_version=None,strategy_config_hash=None)
    with ledger.connection() as db:
        before=[tuple(r) for r in db.execute('SELECT * FROM trades')]
    monkeypatch.setattr(SettingsStore,'load',forbidden)
    report=StrategyAnalysisService(ledger).report(mode='UNKNOWN_LEGACY')
    assert report['completeness']['closed_trades']==3
    assert report['completeness']['profile_metadata']==0
    assert report['sections']['strategy']==[]
    assert 'UNAVAILABLE' in export_csv(report)
    with ledger.connection() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM trades')]==before


def test_missing_votes_do_not_count_as_signal_evidence(ledger):
    seed(ledger, strategy_features=dict(version=1, strategies=[
        feature('EMA_RSI', signal=None), feature('MACD', signal=None, enabled=False)]))
    report = StrategyAnalysisService(ledger).report()
    assert report['completeness']['strategy_signals'] == 0
    assert report['completeness']['complete_strategy_features'] == 0
    groups = {r['group'] for r in report['sections']['strategy']}
    assert groups == {('EMA_RSI', 'UNAVAILABLE'), ('MACD', 'disabled')}


def test_csv_missing_legacy_strategy_columns_are_explicit(ledger):
    seed(ledger, key='modern')
    legacy = seed(ledger, key='legacy', features=False)
    report = StrategyAnalysisService(ledger).report()
    rows = list(csv.DictReader(io.StringIO(export_csv(report))))
    row = next(r for r in rows if r['trade_id'] == legacy['trade_id'])
    assert row['EMA_RSI_signal'] == 'UNAVAILABLE'
    assert row['EMA_RSI_effective_weight'] == 'UNAVAILABLE'
