"""Pure descriptive cohorts over a consistent ledger read; no settings writes."""
import csv
import io
from collections import defaultdict
from itertools import combinations

from autot.paper_trade.performance import PerformanceService, average
from autot.paper_trade.sessions import utc
from autot.strategy_analysis.snapshot import contributions
from autot.utils.financial_validation import decimal_value as D

PROFILE_FIELDS = ('strategy_profile_id', 'strategy_profile_name', 'strategy_profile_version', 'strategy_config_hash')
REGIMES = ('STRONG_UPTREND', 'STRONG_DOWNTREND', 'SIDEWAYS_OR_WEAK_TREND')
DEFAULT_BINS = {
    'confidence': tuple(range(55, 90, 5)),
    'agreement': (0, 20, 40, 60, 80, 100),
    'trade_quality': (70, 75, 80, 85, 90),
    'historical_score': (0, 20, 40, 60, 80, 100),
    'planned_risk_percent': (0, .5, 1, 1.5, 2, 3),
    'position_percent': (0, 10, 20, 30, 40, 50),
    'actual_fill_risk_percent': (0, .5, 1, 1.5, 2, 3),
}


def sample_label(count):
    for limit, label in ((20, 'VERY SMALL SAMPLE'), (50, 'SMALL SAMPLE'), (100, 'EARLY EVIDENCE'),
                         (150, 'MORE MEANINGFUL')):
        if count < limit:
            return label
    return 'STRONGER SAMPLE FOR REVIEW'


def band(value, edges):
    edges = tuple(D(x) for x in edges)
    if not edges or any(a >= b for a, b in zip(edges, edges[1:])):
        raise ValueError('Bin edges must be finite and strictly increasing.')
    if value is None:
        return 'UNAVAILABLE'
    value = D(value)
    if value < edges[0]:
        return f'<{edges[0]:g}'
    for low, high in zip(edges, edges[1:]):
        if low <= value < high:
            return f'{low:g}–<{high:g}'
    return f'{edges[-1]:g}+'


def profile_key(trade):
    return tuple(trade.get(k) for k in PROFILE_FIELDS)


def complete_features(row):
    from autot.strategies.registry.strategy_registry import REGISTRY
    votes = row['contributions']
    return (row['trade'].get('strategy_features', {}).get('version') == 1
            and {c.strategy_id for c in votes} == {s.strategy_id for s in REGISTRY}
            and all(not c.enabled or (c.signal is not None and c.effective_weight is not None) for c in votes))


def metrics(rows):
    """Money metrics require exactly one currency; empty cohorts are unavailable."""
    if len({r['currency'] for r in rows}) > 1:
        raise ValueError('Cannot aggregate mixed currencies.')
    pnl = [r['pnl'] for r in rows]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    profit, loss = sum(wins, D(0)), -sum(losses, D(0))
    avg_win, avg_loss = average(wins), average(losses)
    # Realized closed-trade P&L curve only, with simultaneous closes batched.
    # This is NOT mark-to-market account equity or an intratrade drawdown.
    closes = defaultdict(lambda: D(0))
    for r in rows:
        closes[utc(r['trade']['closed_at'])] += r['pnl']
    equity = peak = drawdown = D(0)
    for stamp in sorted(closes):
        equity += closes[stamp]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return dict(trade_count=len(rows), wins=len(wins), losses=len(losses), breakeven=len(pnl)-len(wins)-len(losses),
                buy_count=sum(r['trade']['side'] == 'BUY' for r in rows),
                sell_count=sum(r['trade']['side'] == 'SELL' for r in rows),
                win_rate=D(len(wins))*100/len(rows) if rows else None,
                gross_profit=profit, gross_loss=loss, net_pnl=profit-loss,
                profit_factor=profit/loss if loss else None,
                average_pnl=average(pnl), expectancy=average(pnl),
                average_return=average(r['return_percent'] for r in rows),
                average_win=avg_win, average_loss=avg_loss,
                payoff_ratio=avg_win/abs(avg_loss) if avg_win is not None and avg_loss else None,
                best_trade=max(pnl) if pnl else None, worst_trade=min(pnl) if pnl else None,
                average_holding_seconds=average(r['holding_seconds'] for r in rows),
                average_mfe_per_share=average(r['mfe'] for r in rows),
                average_mae_per_share=average(r['mae'] for r in rows),
                average_mfe_percent=average(r['mfe_percent'] for r in rows),
                average_mae_percent=average(r['mae_percent'] for r in rows),
                excursion_sample=sum(r['mfe_percent'] is not None and r['mae_percent'] is not None for r in rows),
                lower_bound_excursion_sample=sum('lower bound' in r['excursion_note'] for r in rows),
                realized_close_drawdown=drawdown if rows else None,
                sample_status=sample_label(len(rows)))


def risk_features(trade):
    # Derivable only from immutable prices, quantity and capital, never current settings.
    result = dict.fromkeys(('planned_risk_percent', 'position_percent', 'actual_fill_risk_percent'))
    if any(trade.get(k) is None for k in ('account_capital', 'signal_price', 'stop_loss', 'quantity')):
        return result
    capital, signal, stop = (D(trade[k]) for k in ('account_capital', 'signal_price', 'stop_loss'))
    if capital <= 0:
        return result
    quantity = trade['quantity']
    result.update(planned_risk_percent=abs(signal-stop)*quantity/capital*100,
                  position_percent=signal*quantity/capital*100)
    if trade.get('fill_price') is not None:
        result['actual_fill_risk_percent'] = abs(D(trade['fill_price'])-stop)*quantity/capital*100
    return result


def grouped(rows, keys):
    cohorts = defaultdict(list)
    for row in rows:
        for key in keys(row):
            cohorts[(row['currency'], *key)].append(row)
    return [dict(currency=key[0], group=key[1:], **metrics(values)) for key, values in sorted(cohorts.items(), key=lambda x: str(x[0]))]


def combination_report(rows, *, requested=None, minimum_sample=20, sizes=(2, 3)):
    if minimum_sample < 1 or any(n not in (2, 3) for n in sizes):
        raise ValueError('Automatic combinations support pairs/triples and a positive minimum sample.')
    if requested is not None:
        requested = tuple(sorted(set(requested)))
        if not 2 <= len(requested) <= 10:
            raise ValueError('Query between two and ten distinct strategy IDs.')
    def keys(row):
        aligned = sorted(c.strategy_id for c in row['contributions'] if c.aligned_with_final_signal)
        if requested is not None:
            return [requested] if set(requested) <= set(aligned) else []
        return [combo for size in sizes for combo in combinations(aligned, size)]
    result = grouped(rows, keys)
    # Specific queries expose small samples explicitly instead of hiding them.
    return result if requested is not None else [r for r in result if r['trade_count'] >= minimum_sample]


def observations(summary, sections):
    baseline = {r['currency']: r for r in summary}
    result = []
    for section in ('side', 'regime', 'strategy', 'strategy_regime', 'confidence', 'agreement', 'trade_quality'):
        for row in sections[section]:
            base = baseline[row['currency']]
            if row['expectancy'] is None or base['expectancy'] is None:
                continue
            label = 'INSUFFICIENT SAMPLE' if row['trade_count'] < 50 else 'OBSERVATION'
            relation = 'higher' if row['expectancy'] > base['expectancy'] else 'lower' if row['expectancy'] < base['expectancy'] else 'equal'
            result.append(dict(currency=row['currency'], kind=label, section=section,
                               group=' / '.join(map(str, row['group'])), supporting_sample=row['trade_count'],
                               expectancy=row['expectancy'], baseline_expectancy=base['expectancy'],
                               text=f"Observed expectancy is {relation} than the selected baseline ({row['sample_status']}). "
                                    'Overlapping cohorts; descriptive association only. Possible candidate for testing, not a settings recommendation.'))
    return result


class StrategyAnalysisService:
    def __init__(self, ledger):
        self.ledger = ledger

    def report(self, *, mode='FORWARD_TEST', profile=None, bins=None, minimum_sample=20, requested_combination=None):
        if mode not in ('FORWARD_TEST', 'RESEARCH', 'UNKNOWN_LEGACY'):
            raise ValueError('Select one explicit analysis mode.')
        all_rows = PerformanceService(self.ledger).report(mode='ALL')['journal']
        closed = [r for r in all_rows if r['trade']['status'] == 'CLOSED']
        rows = [r for r in closed if (r['trade'].get('mode') or 'UNKNOWN_LEGACY') == mode]
        available_profiles = list(dict.fromkeys(profile_key(r['trade']) for r in rows))
        if profile is not None:
            rows = [r for r in rows if profile_key(r['trade']) == tuple(profile)]
        for r in rows:
            r['contributions'] = contributions(r['trade'])
            r['risk_features'] = risk_features(r['trade'])
        def regime(r):
            value = r['trade'].get('market_regime')
            return value if value in REGIMES else 'unknown'
        def alignment(r):
            return [(c.strategy_id, 'aligned' if c.aligned_with_final_signal else 'opposed' if c.opposed_final_signal
                     else 'HOLD' if c.held else 'disabled' if not c.enabled else 'UNAVAILABLE') for c in r['contributions']]
        sections = {
            'side': grouped(rows, lambda r: [(r['trade']['side'],)]),
            'regime': grouped(rows, lambda r: [(regime(r),)]),
            'strategy': grouped(rows, alignment),
            'strategy_regime': grouped(rows, lambda r: [(name, state, regime(r)) for name, state in alignment(r)]),
            'profile': grouped(rows, lambda r: [profile_key(r['trade'])]),
            'combinations': combination_report(rows, minimum_sample=minimum_sample, requested=requested_combination),
        }
        configured_bins = dict(DEFAULT_BINS)
        if set(bins or {}) - set(configured_bins):
            raise ValueError('Unsupported band field.')
        configured_bins.update(bins or {})
        for field, edges in configured_bins.items():
            band(None, edges)  # validate even for empty datasets
            sections[field] = grouped(rows, lambda r, f=field, e=edges: [(band(
                r['risk_features'].get(f) if f in r['risk_features'] else r['trade'].get(f), e),)])
        summary = grouped(rows, lambda r: [()])
        completeness = dict(closed_trades=len(rows), strategy_signals=sum(
                            any(c.enabled and c.signal is not None for c in r['contributions']) for r in rows),
                            complete_strategy_features=sum(complete_features(r) for r in rows),
                            mfe_mae=sum(r['mfe_percent'] is not None and r['mae_percent'] is not None for r in rows),
                            profile_metadata=sum(all(r['trade'].get(k) is not None for k in PROFILE_FIELDS) for r in rows),
                            historical_score=sum(r['trade'].get('historical_score') is not None for r in rows),
                            pre_settings_legacy=sum(r['trade'].get('configuration_source') == 'PRE_SETTINGS_BASELINE' for r in rows),
                            excluded_unknown_mode=sum(r['trade'].get('mode') is None for r in closed) if mode != 'UNKNOWN_LEGACY' else 0)
        return dict(mode=mode, journal=rows, summary=summary, sections=sections, completeness=completeness,
                    available_profiles=available_profiles, mixed_profiles=len({profile_key(r['trade']) for r in rows}) > 1,
                    observations=observations(summary, sections), bins=configured_bins)


def export_csv(report, section='trades'):
    """No IO or mutation. Currency and mode accompany every exported row."""
    if section == 'trades':
        rows = []
        for entry in report['journal']:
            trade = entry['trade']
            row = {k: trade.get(k) for k in ('trade_id', 'symbol', 'market', 'index_name', 'side', 'signal_time',
                   'market_regime', 'confidence', 'agreement', 'trade_quality', 'historical_score', 'risk_reward_ratio',
                   'fill_price', 'exit_price', 'filled_at', 'closed_at', *PROFILE_FIELDS)}
            row.update({k: entry[k] for k in ('currency', 'pnl', 'return_percent', 'holding_seconds',
                                             'mfe', 'mae', 'mfe_percent', 'mae_percent', 'excursion_note')})
            row.update(entry['risk_features'])
            for c in entry['contributions']:
                for key, value in c.model_dump().items():
                    row[f'{c.strategy_id}_{key}'] = value
            rows.append(row)
    elif section == 'summary':
        rows = report['summary']
    else:
        rows = report['sections'][section]
    profiles = list(dict.fromkeys(profile_key(r['trade']) for r in report['journal']))
    profile_scope = '; '.join(' / '.join('UNAVAILABLE' if x is None else str(x) for x in p) for p in profiles)
    fields = list(dict.fromkeys(['mode', 'currency', 'analysis_profiles', *(k for row in rows for k in row)]))
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=fields, restval='UNAVAILABLE')
    writer.writeheader()
    for row in rows:
        values = dict(row, mode=report['mode'], analysis_profiles=profile_scope)
        def cell(value):
            if value is None:
                return 'UNAVAILABLE'
            if isinstance(value, tuple):
                value = ' / '.join('UNAVAILABLE' if x is None else str(x) for x in value)
            # Treat text as text in spreadsheet applications.
            if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
                return "'" + value
            return value
        writer.writerow({k: cell(v) for k, v in values.items()})
    return output.getvalue()
