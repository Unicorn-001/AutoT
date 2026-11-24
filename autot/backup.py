"""Versioned local backup sets. No store constructors or trading mutations."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid

from autot.runtime import data_dir, project_path, PROJECT_ROOT

FORMAT = 'autot-backup'
VERSION = 1
DATABASES = {
    'paper_trading/ledger.sqlite3': {'trades', 'paper_trade_events', 'notification_outbox'},
    'scanner/scans.sqlite3': {'scan_runs', 'scanner_status', 'notification_outbox'},
    'market_context/market_context.sqlite3': {'assessments'},
    'real_trade_journal/real_trade_journal.sqlite3': {'real_trades'},
    'settings/settings.sqlite3': {'revisions', 'profiles', 'changes'},
}
FILE_ROOTS = {'config', 'watchlists', 'manual_trading', 'processed'}
EXCLUDED = ['cache/', 'yfinance_cache/', 'universe_cache/', 'scanner/worker.log',
            '*.lock', 'SQLite WAL/SHM/journal sidecars', 'prior backup sets', 'diagnostic reports']


class BackupError(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def backup_directory(output=None):
    return project_path(output or os.environ.get('AUTOT_BACKUP_DIR') or
                        str(data_dir().parent / (data_dir().name + '-backups'))).resolve()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def readonly(path, *, immutable=False):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro' +
                           ('&immutable=1' if immutable else ''), uri=True, timeout=5)


def sqlite_metadata(path, relative):
    with closing(readonly(path, immutable=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise BackupError(f'Integrity check failed: {relative}')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise BackupError(f'Foreign key check failed: {relative}')
        schema = db.execute('SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name').fetchall()
        tables = {r[1] for r in schema if r[0] == 'table'}
        if not DATABASES[relative] <= tables:
            raise BackupError(f'Missing critical tables: {relative}')
        return dict(user_version=db.execute('PRAGMA user_version').fetchone()[0],
                    schema_version=db.execute('PRAGMA schema_version').fetchone()[0],
                    schema=schema)


def supplemental(root):
    return sorted(p.relative_to(root).as_posix() for name in FILE_ROOTS
                  for p in (root / name).rglob('*')
                  if p.is_file() and p.suffix.lower() in {'.csv', '.json'})


def safe_file(root, relative):
    path = root / relative
    if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise BackupError(f'Symlinks are not supported: {path}')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise BackupError(f'Missing or unsafe file: {relative}')
    return path


def fsync_tree(root):
    for path in root.rglob('*'):
        if path.is_file():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    for path in [p for p in root.rglob('*') if p.is_dir()] + [root]:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextmanager
def repository_lock(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / '.operations.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def create_backup(output=None):
    source = data_dir().resolve()
    output = backup_directory(output)
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise BackupError('Backup destination must be separate from the live data directory.')
    for relative in DATABASES:
        safe_file(source, relative)
    with repository_lock(output):
        with tempfile.TemporaryDirectory(prefix='.partial-', dir=output) as temporary:
            stage = Path(temporary)
            started = utcnow()
            files = []
            extras = supplemental(source)
            extra_hashes = {r: digest(safe_file(source, r)) for r in extras}
            for relative in [*DATABASES, *extras]:
                original = safe_file(source, relative)
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                entry = dict(path=relative, classification='critical', kind='sqlite' if relative in DATABASES else 'file')
                if relative in DATABASES:
                    deadline = time.monotonic() + 120
                    def progress(status, remaining, total):
                        if time.monotonic() > deadline:
                            raise BackupError(f'SQLite backup timed out: {relative}')
                    with closing(readonly(original)) as src, closing(sqlite3.connect(target)) as dst:
                        entry['source_journal_mode'] = src.execute('PRAGMA journal_mode').fetchone()[0]
                        src.backup(dst, pages=256, progress=progress, sleep=.05)
                        dst.execute('PRAGMA journal_mode=DELETE')
                    entry.update(sqlite_metadata(target, relative))
                else:
                    shutil.copyfile(original, target)
                    if digest(target) != extra_hashes[relative]:
                        raise BackupError(f'File changed during backup: {relative}')
                    if target.suffix == '.json':
                        json.loads(target.read_text())
                entry.update(sha256=digest(target), size=target.stat().st_size)
                files.append(entry)
            if extras != supplemental(source) or any(digest(safe_file(source, r)) != h for r, h in extra_hashes.items()):
                raise BackupError('Supplemental files changed during backup; stop legacy writers and retry.')
            try:
                commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT_ROOT,
                                                 stderr=subprocess.DEVNULL, text=True, timeout=5).strip()
                dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=PROJECT_ROOT,
                                                    stderr=subprocess.DEVNULL, timeout=5))
            except (OSError, subprocess.SubprocessError):
                commit, dirty = None, None
            manifest = dict(format=FORMAT, version=VERSION, started_at=started.isoformat(),
                            completed_at=utcnow().isoformat(), source_data_dir=str(source),
                            commit=commit, working_tree_dirty=dirty, files=files,
                            required_databases=list(DATABASES), excluded=EXCLUDED,
                            consistency='Per-database SQLite snapshot; no cross-database transaction',
                            verification='verified at creation')
            (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2))
            verify_backup(stage)
            fsync_tree(stage)
            name = 'autot-' + started.strftime('%Y%m%dT%H%M%S.%fZ-') + uuid.uuid4().hex[:8]
            destination = output / name
            stage.rename(destination)
            fd = os.open(output, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    return dict(path=str(destination), manifest=manifest)


def read_manifest(path):
    path = Path(path)
    manifest = json.loads(safe_file(path, 'manifest.json').read_text())
    if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or manifest.get('version') != VERSION:
        raise BackupError('Unsupported backup manifest')
    for field in ('started_at', 'completed_at'):
        if datetime.fromisoformat(manifest[field]).tzinfo is None:
            raise BackupError('Backup timestamps must include timezone')
    if not isinstance(manifest['source_data_dir'], str) or not Path(manifest['source_data_dir']).is_absolute():
        raise BackupError('Invalid source directory')
    if set(manifest['required_databases']) != set(DATABASES):
        raise BackupError('Invalid required database inventory')
    if not isinstance(manifest['files'], list):
        raise BackupError('Invalid file inventory')
    return manifest


def verify_backup(path):
    """Pure read: repeated verification neither annotates nor modifies the set."""
    path = Path(path).absolute()
    try:
        manifest = read_manifest(path)
        expected = {'manifest.json'}
        for entry in manifest['files']:
            relative = entry['path']
            rel = Path(relative)
            if rel.is_absolute() or '..' in rel.parts or rel.as_posix() != relative or relative in expected:
                raise BackupError(f'Invalid or duplicate manifest path: {relative}')
            is_db = relative in DATABASES
            if not is_db and (not rel.parts or rel.parts[0] not in FILE_ROOTS or rel.suffix.lower() not in {'.csv', '.json'}):
                raise BackupError(f'Unrecognized critical file: {relative}')
            if entry['kind'] != ('sqlite' if is_db else 'file') or entry['classification'] != 'critical':
                raise BackupError(f'Invalid file classification: {relative}')
            expected.add(relative)
            file = safe_file(path, relative)
            if file.stat().st_size != entry['size'] or digest(file) != entry['sha256']:
                raise BackupError(f'Checksum/size mismatch: {relative}')
            if is_db:
                actual = json.loads(json.dumps(sqlite_metadata(file, relative)))
                if any(entry[key] != value for key, value in actual.items()):
                    raise BackupError(f'Schema metadata mismatch: {relative}')
        if not set(DATABASES) <= expected:
            raise BackupError('Missing critical database in manifest')
        all_paths = list(path.rglob('*'))
        if any(p.is_symlink() for p in all_paths):
            raise BackupError('Backup contains symlinks')
        actual_files = {p.relative_to(path).as_posix() for p in all_paths if not p.is_dir()}
        if actual_files != expected:
            raise BackupError(f'Missing/extra files: {sorted(actual_files ^ expected)}')
        return manifest
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        raise BackupError(f'Invalid backup {path}: {error}') from error


def list_backups(output=None, *, verify=False):
    root = backup_directory(output)
    results = []
    if not root.exists():
        return results
    for path in sorted(root.glob('autot-*'), reverse=True):
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            manifest = verify_backup(path) if verify else read_manifest(path)
            results.append(dict(path=str(path), completed_at=manifest['completed_at'],
                                verification='valid' if verify else 'verified at creation; not rechecked'))
        except (OSError, ValueError, KeyError, TypeError) as error:
            results.append(dict(path=str(path), verification='invalid', error=str(error)))
    return sorted(results, key=lambda r: r.get('completed_at', ''), reverse=True)


def restore_backup(path, destination):
    """Restore only to a new directory; never replace any live data or lock inode."""
    from autot.daily_scanner import active
    destination = Path(destination).expanduser().absolute()
    live = data_dir().resolve()
    backup_path = Path(path).resolve()
    if destination.resolve().is_relative_to(backup_path) or backup_path.is_relative_to(destination.resolve()):
        raise BackupError('Restore destination overlaps the backup; choose a separate directory.')
    if destination.resolve().is_relative_to(live) or live.is_relative_to(destination.resolve()):
        raise BackupError('Restore destination overlaps live AUTOT_DATA_DIR; choose a separate new directory.')
    for relative, kinds in {
        'paper_trading/ledger.sqlite3': ('monitor', 'update', 'notifications'),
        'scanner/scans.sqlite3': ('scan', 'scheduler', 'submission'),
    }.items():
        if any(active(destination / relative, kind) for kind in kinds):
            raise BackupError('Active service lock at restore destination')
    if destination.exists() or destination.is_symlink():
        raise BackupError('Restore destination already exists; in-place/force restore is not supported.')
    manifest = verify_backup(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.autot-restore-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        for relative in ['manifest.json', *(e['path'] for e in manifest['files'])]:
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_file(Path(path), relative), target)
        verify_backup(stage)
        (stage / 'manifest.json').unlink()
        fsync_tree(stage)
        # Reserve with mkdir (exclusive); never replace an existing destination.
        destination.mkdir(mode=0o700)
        try:
            stage.rename(destination)
            fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except BaseException:
            if not any(destination.iterdir()):
                destination.rmdir()
            raise
    return dict(destination=str(destination), restored=[e['path'] for e in manifest['files']])


def prune_backups(output=None, *, keep=14, days=30, dry_run=False):
    if keep < 1 or days < 0:
        raise BackupError('Retention requires keep >= 1 and days >= 0')
    root = backup_directory(output)
    with repository_lock(root):
        records = list_backups(root, verify=True)
        valid = [r for r in records if r['verification'] == 'valid']
        cutoff = utcnow() - timedelta(days=days)
        candidates = [r['path'] for r in valid[keep:]
                      if datetime.fromisoformat(r['completed_at']) < cutoff]
        if not dry_run:
            for candidate in candidates:
                shutil.rmtree(candidate)
    return dict(dry_run=dry_run, candidates=candidates, kept=len(records)-len(candidates))


def backup_health(*, now=None):
    now = now or utcnow()
    result = dict(destination=str(backup_directory()), last_successful_backup=None,
                  age_seconds=None, verification='unknown', warning=None)
    try:
        records = list_backups()
        usable = [r for r in records if r['verification'] != 'invalid']
        if usable:
            latest = usable[0]
            age = (now - datetime.fromisoformat(latest['completed_at'])).total_seconds()
            result.update(last_successful_backup=latest['completed_at'], age_seconds=age,
                          verification=latest['verification'])
            if age > 48 * 3600 or age < -30:
                result['warning'] = 'Latest backup is stale (over 48 hours) or has a future timestamp.'
        else:
            result['warning'] = 'No successful backup found.'
        if any(r['verification'] == 'invalid' for r in records):
            result['warning'] = 'Invalid backup metadata found; run verify-backup.'
    except (OSError, ValueError, KeyError, TypeError) as error:
        result['warning'] = f'Backup information unavailable: {error}'
    return result
