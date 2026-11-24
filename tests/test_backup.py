"""Operational backup tests use isolated real stores; no providers or live data."""
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3

import pytest

from autot import backup
from autot.application.scan_store import ScanStore
from autot.application.system_health import snapshot
from autot.market_context.store import MarketContextStore
from autot.paper_trade.ledger import Ledger
from autot.paper_trade.locking import database_lock
from autot.real_trade_journal.service import RealTradeJournal
from autot.runtime import data_dir
from autot.settings.store import SettingsStore
from autot.ops import main


@pytest.fixture
def stores(tmp_path, monkeypatch):
    Ledger()
    ScanStore()
    MarketContextStore()
    RealTradeJournal()
    settings = SettingsStore()
    settings.save(settings.load().settings, expected_version=0)
    monkeypatch.setenv('AUTOT_BACKUP_DIR', str(tmp_path / 'backups'))
    return data_dir()


def make_backup():
    return Path(backup.create_backup()['path'])


def test_healthy_manifest_and_idempotent_verification(stores):
    extra = stores / 'processed' / 'paper_portfolio_state.json'
    extra.parent.mkdir()
    extra.write_text('{"cash": 123}')
    cache = stores / 'yfinance_cache'
    cache.mkdir()
    (cache / 'cookies.db').write_bytes(b'private cache')
    path = make_backup()
    original = {p.relative_to(path): p.read_bytes() for p in path.rglob('*') if p.is_file()}
    manifest = backup.verify_backup(path)
    assert backup.verify_backup(path) == manifest
    assert {p.relative_to(path): p.read_bytes() for p in path.rglob('*') if p.is_file()} == original
    assert manifest['format'] == backup.FORMAT
    assert manifest['source_data_dir'] == str(stores.resolve())
    assert manifest['commit']
    assert len(manifest['files']) == 6
    assert not (path / 'yfinance_cache').exists()
    assert all(len(e['sha256']) == 64 for e in manifest['files'])
    assert all('schema' in e and 'user_version' in e for e in manifest['files'] if e['kind'] == 'sqlite')


def test_backup_open_wal_and_uncommitted_writer(stores):
    path = stores / 'paper_trading/ledger.sqlite3'
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('CREATE TABLE backup_probe(value TEXT)')
        writer.execute("INSERT INTO backup_probe VALUES ('committed')")
        writer.commit()
        writer.execute("INSERT INTO backup_probe VALUES ('uncommitted')")
        with database_lock(path, 'monitor'):
            saved = make_backup()
        with closing(backup.readonly(saved / 'paper_trading/ledger.sqlite3', immutable=True)) as reader:
            assert reader.execute('SELECT value FROM backup_probe').fetchall() == [('committed',)]
        writer.rollback()


@pytest.mark.parametrize('relative', list(backup.DATABASES))
def test_missing_critical_source_fails(stores, relative):
    (stores / relative).unlink()
    assert main(['backup']) == 1
    assert not backup.list_backups()


def test_invalid_output_and_corrupt_source(stores, tmp_path):
    output = tmp_path / 'file'
    output.write_text('occupied')
    assert main(['backup', '--output', str(output)]) == 1
    assert main(['backup', '--output', str(stores / 'backups')]) == 1
    (stores / 'market_context/market_context.sqlite3').write_bytes(b'broken')
    assert main(['backup']) == 1
    assert not backup.list_backups()


@pytest.mark.parametrize('damage', ['checksum', 'sqlite', 'missing', 'extra', 'inventory', 'traversal', 'schema', 'symlink'])
def test_invalid_backup(stores, damage):
    path = make_backup()
    target = path / 'market_context/market_context.sqlite3'
    manifest_path = path / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if damage in ('checksum', 'sqlite'):
        target.write_bytes(b'broken')
        if damage == 'sqlite':
            entry = next(e for e in manifest['files'] if e['path'] == target.relative_to(path).as_posix())
            entry.update(sha256=backup.digest(target), size=target.stat().st_size)
    elif damage == 'missing':
        target.unlink()
    elif damage == 'extra':
        (path / 'extra.txt').write_text('unexpected')
    elif damage == 'inventory':
        manifest['files'] = [e for e in manifest['files'] if e['path'] != target.relative_to(path).as_posix()]
        target.unlink()
    elif damage == 'traversal':
        manifest['files'][0]['path'] = '../escape'
    elif damage == 'schema':
        manifest['files'][0]['user_version'] += 1
    elif damage == 'symlink':
        target.unlink()
        target.symlink_to(stores / 'market_context/market_context.sqlite3')
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(backup.BackupError):
        backup.verify_backup(path)
    assert main(['verify-backup', str(path)]) == 1


def test_restore_new_directory_preserves_backup(stores, tmp_path):
    path = make_backup()
    before = {p: p.read_bytes() for p in path.rglob('*') if p.is_file()}
    destination = tmp_path / 'restored'
    result = backup.restore_backup(path, destination)
    assert set(result['restored']) == set(backup.DATABASES)
    for relative in backup.DATABASES:
        assert backup.digest(destination / relative) == backup.digest(path / relative)
    assert all(p.read_bytes() == content for p, content in before.items())
    with pytest.raises(backup.BackupError, match='already exists'):
        backup.restore_backup(path, destination)
    with pytest.raises(backup.BackupError, match='overlaps live'):
        backup.restore_backup(path, stores)


@pytest.mark.parametrize('relative,kind', [
    ('paper_trading/ledger.sqlite3', 'monitor'), ('paper_trading/ledger.sqlite3', 'update'),
    ('paper_trading/ledger.sqlite3', 'notifications'), ('scanner/scans.sqlite3', 'scan'),
    ('scanner/scans.sqlite3', 'scheduler'), ('scanner/scans.sqlite3', 'submission')])
def test_restore_refuses_service_locks(stores, tmp_path, relative, kind):
    path = make_backup()
    destination = tmp_path / 'restore'
    db = destination / relative
    db.parent.mkdir(parents=True)
    with database_lock(db, kind):
        with pytest.raises(backup.BackupError, match='Active service lock'):
            backup.restore_backup(path, destination)


def test_restore_verifies_before_creating_destination(stores, tmp_path):
    path = make_backup()
    (path / 'settings/settings.sqlite3').unlink()
    with pytest.raises(backup.BackupError):
        backup.restore_backup(path, tmp_path / 'restore')
    assert not (tmp_path / 'restore').exists()


def test_retention_dry_run_and_newest_valid(stores):
    paths = [make_backup() for _ in range(3)]
    (paths[-1] / 'settings/settings.sqlite3').unlink()
    unknown = backup.backup_directory() / 'autot-unknown'
    unknown.mkdir()
    (unknown / 'keep.txt').write_text('not a backup')
    plan = backup.prune_backups(keep=1, days=0, dry_run=True)
    assert plan['candidates'] == [str(paths[0])]
    assert all(p.exists() for p in paths)
    backup.prune_backups(keep=1, days=0)
    assert not paths[0].exists()
    assert paths[1].exists() and paths[2].exists() and unknown.exists()
    backup.prune_backups(keep=1, days=0)
    assert paths[1].exists()
    with pytest.raises(backup.BackupError):
        backup.prune_backups(keep=0)


def test_retention_age_protects_recent(stores):
    paths = [make_backup() for _ in range(2)]
    assert backup.prune_backups(keep=1, days=30)['candidates'] == []
    assert all(p.exists() for p in paths)


def test_health_read_only_missing_fresh_stale_and_invalid(stores, monkeypatch):
    assert snapshot()['backup']['warning'] == 'No successful backup found.'
    path = make_backup()
    def forbidden(*args, **kwargs):
        raise AssertionError('Health must not back up or run database verification')
    monkeypatch.setattr(backup, 'create_backup', forbidden)
    monkeypatch.setattr(backup, 'verify_backup', forbidden)
    health = snapshot()['backup']
    assert health['warning'] is None
    assert health['age_seconds'] >= 0
    assert health['verification'] == 'verified at creation; not rechecked'
    assert health['destination'] == str(path.parent)
    assert backup.backup_health(now=backup.utcnow() + timedelta(days=3))['warning']
    (path / 'manifest.json').write_text('invalid')
    assert snapshot()['backup']['warning']


def test_cli_workflow(stores, tmp_path, capsys):
    assert main(['backup']) == 0
    path = json.loads(capsys.readouterr().out)['path']
    assert main(['verify-backup', path]) == 0
    assert main(['list-backups']) == 0
    assert main(['prune-backups', '--dry-run']) == 0
    assert main(['restore', path, '--destination', str(tmp_path / 'restored')]) == 0


def test_restore_cannot_modify_backup(stores):
    path = make_backup()
    with pytest.raises(backup.BackupError, match='overlaps the backup'):
        backup.restore_backup(path, path / 'restored')
    backup.verify_backup(path)


def test_existing_empty_restore_directory_is_refused(stores, tmp_path):
    path = make_backup()
    destination = tmp_path / 'empty'
    destination.mkdir()
    with pytest.raises(backup.BackupError, match='already exists'):
        backup.restore_backup(path, destination)
    assert list(destination.iterdir()) == []


def test_supplemental_changes_abort_publication(stores, monkeypatch):
    extra = stores / 'manual_trading/trades.csv'
    extra.parent.mkdir()
    extra.write_text('symbol\nAAPL\n')
    real_copy = backup.shutil.copyfile
    def changing_copy(source, target):
        result = real_copy(source, target)
        if source == extra:
            extra.write_text('symbol\nMSFT\n')
        return result
    monkeypatch.setattr(backup.shutil, 'copyfile', changing_copy)
    with pytest.raises(backup.BackupError, match='changed during backup'):
        make_backup()
    assert not backup.list_backups()
    assert not list(backup.backup_directory().glob('.partial-*'))


def test_backup_with_concurrent_commits(stores):
    import threading
    path = stores / 'paper_trading/ledger.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE backup_pairs(a INTEGER, b INTEGER)')
    stop = threading.Event()
    ready = threading.Event()
    errors = []
    def write():
        try:
            with closing(sqlite3.connect(path, timeout=5)) as db:
                n = 0
                while not stop.is_set():
                    with db:
                        db.execute('INSERT INTO backup_pairs VALUES (?, ?)', (n, n))
                    ready.set()
                    n += 1
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=write)
    thread.start()
    try:
        assert ready.wait(5)
        saved = make_backup()
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and not errors
    with closing(backup.readonly(saved / 'paper_trading/ledger.sqlite3', immutable=True)) as db:
        assert db.execute('SELECT COUNT(*) FROM backup_pairs').fetchone()[0] > 0
        assert db.execute('SELECT COUNT(*) FROM backup_pairs WHERE a != b').fetchone()[0] == 0
