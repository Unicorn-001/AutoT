"""Read-only adapter for existing persisted scanner opportunities."""
import json
from pathlib import Path
import sqlite3

from autot.runtime import data_dir
from autot.real_trade_journal.service import RealTradeJournal


FIELD_MAP = {
    'signal': 'signal', 'market_regime': 'market_regime', 'confidence': 'confidence',
    'agreement': 'agreement', 'trade_quality': 'trade_quality_score',
    'historical_score': 'score', 'autot_entry_price': 'entry_price',
    'autot_stop_loss': 'stop_loss', 'autot_take_profit': 'take_profit',
    'autot_risk_reward_ratio': 'risk_reward_ratio',
}


def opportunities(path=None):
    path = Path(path) if path else data_dir() / 'scanner' / 'scans.sqlite3'
    if not path.exists():
        return []
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        rows = db.execute('SELECT scan_run_id, result FROM scan_runs WHERE result IS NOT NULL ORDER BY rowid DESC').fetchall()
    finally:
        db.close()
    choices = []
    for run_id, payload in rows:
        saved = json.loads(payload)
        for index, row in enumerate(saved.get('outputs', {}).get('trade_opportunities', [])):
            snapshot = {target: row.get(source) for target, source in FIELD_MAP.items()}
            # Use only the scan's persisted configuration, never today's settings.
            snapshot['autot_execution_model'] = (saved.get('settings_state') or {}).get(
                'settings', {}).get('advanced', {}).get('fill_model')
            snapshot.update(scan_run_id=run_id, signal_timestamp=(
                saved.get('paper_signal_context', {}).get(row['symbol'], {}).get('signal_time')
                or row.get('signal_timestamp')))
            choices.append(dict(key=f'{run_id}:{index}', symbol=row['symbol'], side=row['signal'],
                                snapshot=snapshot))
    return choices


def create_linked(journal: RealTradeJournal, opportunity_key, *, broker, scanner_path=None, **execution):
    # Resolve from persisted source again at submission; callers cannot override the snapshot.
    choice = next((row for row in opportunities(scanner_path) if row['key'] == opportunity_key), None)
    if choice is None:
        raise ValueError('Scanner opportunity is no longer available.')
    return journal.create(symbol=choice['symbol'], side=choice['side'], broker=broker,
                          snapshot=choice['snapshot'], **execution)
