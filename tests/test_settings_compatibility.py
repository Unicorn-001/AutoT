"""Historical writer fixtures retain their original canonical revision hashes."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import warnings

import pytest

from autot import daily_scanner as ds
from autot.settings.models import SettingsState, TradeSettingsSnapshot, configuration_hash
from autot.settings.store import SettingsStore, SettingsWarning, validate_revision


FIXTURES = json.loads((Path(__file__).parent / 'fixtures/settings_revision_compatibility.json').read_text())
VALID = [name for name in FIXTURES if name != 'tampered']


def install(*names):
    store = SettingsStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store.path) as db:
        db.execute('CREATE TABLE revisions (version INTEGER PRIMARY KEY, payload TEXT, hash TEXT)')
        for name in names:
            fixture = FIXTURES[name]
            db.execute('INSERT INTO revisions VALUES (?,?,?)',
                       (fixture['payload']['settings_version'], json.dumps(fixture['payload']), fixture['hash']))
    return store


@pytest.mark.parametrize('name', VALID)
def test_historical_revision_loads_without_rewriting(name):
    store = install(name)
    before = store.path.read_bytes()
    fixture = FIXTURES[name]
    with warnings.catch_warnings():
        warnings.simplefilter('error', SettingsWarning)
        state = store.load()
    assert state.settings_version == fixture['payload']['settings_version']
    assert store.warning is None
    assert state.settings.scanner.index == 'nasdaq100'
    assert state.settings.risk.risk_per_trade_percent == .5
    monitoring = state.settings.monitoring
    original = fixture['payload']['settings']
    assert monitoring.paper_update_interval_minutes == 15
    assert monitoring.paper_monitor_enabled == original['monitoring'].get('paper_monitor_enabled', False)
    assert not monitoring.daily_scan_enabled
    assert monitoring.daily_scan_time_local == '22:00'
    assert monitoring.daily_scan_quality_threshold == 70
    assert state.settings.notifications.notifications_enabled == original.get('notifications', {}).get('notifications_enabled', False)
    assert state.settings.notifications.notification_channel == 'CONSOLE'
    assert state.profile.model_dump(mode='json') == fixture['payload']['profile']
    assert TradeSettingsSnapshot.from_state(state).strategy_config_hash == state.profile.configuration_hash
    assert state.profile.configuration_hash == configuration_hash(state.profile.configuration)
    assert store.path.read_bytes() == before


def test_latest_valid_legacy_selected():
    store = install('before_monitor', 'before_notifications', 'before_daily_scanner')
    assert store.load().settings_version == 3
    assert store.warning is None


def test_tampered_latest_falls_back_and_all_invalid_uses_baseline():
    store = install('before_notifications', 'tampered')
    before = store.path.read_bytes()
    with pytest.warns(SettingsWarning, match='last valid'):
        assert store.load().settings_version == 2
    assert store.path.read_bytes() == before


def test_only_corrupt_revision_uses_baseline():
    store = install('tampered')
    with pytest.warns(SettingsWarning, match='No valid settings revision'):
        assert store.load() == SettingsState()


@pytest.mark.parametrize('mutation', ['remove', 'coerce', 'profile', 'version', 'schema', 'unknown', 'missing_unrelated'])
def test_integrity_and_schema_checks_remain_strict(mutation):
    fixture = copy.deepcopy(FIXTURES['current'])
    raw = fixture['payload']
    digest = fixture['hash']
    version = raw['settings_version']
    if mutation == 'remove':
        del raw['settings']['monitoring']['daily_scan_time_local']
    elif mutation == 'coerce':
        raw['settings']['scanner']['top_ranked_count'] = '10'
    elif mutation == 'profile':
        raw['profile']['configuration_hash'] = '0' * 64
        digest = configuration_hash(raw)
    elif mutation == 'version':
        version += 1
    else:
        if mutation == 'schema':
            raw['settings']['schema_version'] = 2
        elif mutation == 'unknown':
            raw['settings']['unexpected'] = True
        else:
            del raw['settings']['scanner']['interval']
        digest = configuration_hash(raw)
    with pytest.raises(ValueError):
        validate_revision(version, json.dumps(raw), digest)


def test_partial_notification_defaults():
    raw = copy.deepcopy(FIXTURES['before_daily_scanner']['payload'])
    raw['settings']['notifications'] = {}
    state = validate_revision(raw['settings_version'], json.dumps(raw), configuration_hash(raw))
    assert not state.settings.notifications.notifications_enabled
    assert state.settings.notifications.notification_channel == 'CONSOLE'


def test_new_save_uses_current_format_preserves_historical_hash():
    store = install('before_daily_scanner')
    with sqlite3.connect(store.path) as db:
        before = db.execute('SELECT * FROM revisions').fetchall()
    state = store.load()
    raw = state.settings.model_dump(mode='json')
    raw['scanner']['top_ranked_count'] = 12
    updated = store.save(type(state.settings).model_validate(raw), expected_version=3)
    assert updated.profile == state.profile
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT * FROM revisions WHERE version=3').fetchall() == before
        payload, digest = db.execute('SELECT payload,hash FROM revisions WHERE version=4').fetchone()
    assert json.loads(payload) == updated.model_dump(mode='json')
    assert digest == configuration_hash(updated)
    assert store.load() == updated


@pytest.mark.parametrize('name', VALID)
def test_status_cli_is_read_only_and_once_builds_legacy_request(name, monkeypatch, capsys):
    store = install(name)
    root = store.path.parent.parent
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = subprocess.run([sys.executable, '-m', 'autot.daily_scanner', '--status'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'SettingsWarning' not in result.stderr
    assert json.loads(result.stdout)['configured'] is False
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
    # Exercise the actual --once CLI/request path, stopping at fake persistence
    # and execution so no provider, paper ledger, or production scan is involved.
    captured = []
    class RequestStore(ds.ScanStore):
        def create(self, request):
            captured.append(request)
            return {'status': 'SUCCESS'}
    monkeypatch.setattr(ds, 'ScanStore', RequestStore)
    monkeypatch.setattr(ds.DailyScanner, 'work', lambda self, run: run)
    assert ds.main(['--once']) == 0
    capsys.readouterr()
    assert captured[0]['universe'] == 'nasdaq100'
    assert captured[0]['quality_threshold'] == 70
    assert captured[0]['state']['profile'] == FIXTURES[name]['payload']['profile']
    assert store.path.read_bytes() == before[store.path.relative_to(root)]
