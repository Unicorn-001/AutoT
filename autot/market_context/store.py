"""Append-only assessments in a dedicated database; scanner access is read-only."""
import json
from pathlib import Path
import sqlite3

from autot.runtime import data_dir
from autot.market_context.assessment import assess
from autot.market_data.quote import Quote


def with_quote_defaults(record):
    defaults = dict(fetched_price=None, assessed_price=record.get('current_price'),
                    price_source=record.get('source'), quote_timestamp=None,
                    quote_age_seconds=None, stale=False,
                    session_label=record.get('market_session'), manual_override=False)
    return defaults | record


class MarketContextStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / 'market_context' / 'market_context.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS assessments (assessment_id TEXT PRIMARY KEY, scanner_run_id TEXT, opportunity_id TEXT, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS assessment_opportunity ON assessments(scanner_run_id, opportunity_id)')

    def save(self, assessment):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO assessments VALUES (?,?,?,?)',
                       (assessment['assessment_id'], assessment['scanner_run_id'], assessment['opportunity_id'],
                        json.dumps(assessment, allow_nan=False)))
        return assessment

    def history(self, run_id, opportunity_id):
        with sqlite3.connect(self.path) as db:
            return [with_quote_defaults(json.loads(row[0])) for row in db.execute(
                'SELECT payload FROM assessments WHERE scanner_run_id=? AND opportunity_id=? ORDER BY rowid DESC',
                (run_id, str(opportunity_id)))]


def assess_opportunity(run_id, opportunity_index, current_price, *, store=None, scanner_path=None, quote: Quote | None = None, **metadata):
    """Resolve an index against the persisted snapshot, never a caller-edited setup."""
    path = Path(scanner_path) if scanner_path else data_dir() / 'scanner' / 'scans.sqlite3'
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        row = db.execute('SELECT result FROM scan_runs WHERE scan_run_id=?', (run_id,)).fetchone()
    if row is None or row[0] is None:
        raise ValueError('Persisted scanner result is unavailable')
    saved = json.loads(row[0])
    opportunities = saved['outputs']['trade_opportunities']
    if not isinstance(opportunity_index, int) or opportunity_index < 0 or opportunity_index >= len(opportunities):
        raise ValueError('Scanner opportunity is unavailable')
    opportunity = opportunities[opportunity_index]
    if quote is not None:
        if quote.symbol != opportunity.get('symbol'):
            raise ValueError('Quote symbol does not match the persisted opportunity')
        metadata.update(source=quote.source, market_session=quote.session_label)
    result = assess(symbol=opportunity.get('symbol'), side=opportunity.get('signal'),
                    reference_entry=opportunity.get('entry_price'), stop_loss=opportunity.get('stop_loss'),
                    take_profit=opportunity.get('take_profit'), original_rr=opportunity.get('risk_reward_ratio'),
                    current_price=current_price, scanner_run_id=run_id, opportunity_id=str(opportunity_index),
                    **metadata)
    result = with_quote_defaults(result)
    result['version'] = '1.1'
    if quote is not None:
        from datetime import datetime
        result.update(quote.audit(current_price, now=datetime.fromisoformat(result['assessed_at'])))
    return (store or MarketContextStore()).save(result)
