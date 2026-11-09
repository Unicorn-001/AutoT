"""Atomic append-only settings revisions and profiles in a separate SQLite store."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import warnings
from uuid import uuid4

from autot.runtime import data_dir
from autot.settings.models import (AutoTSettings, SettingsState, StrategyProfile, TradingConfiguration,
                                   baseline_profile, canonical, configuration_hash, timestamp)


class SettingsWarning(UserWarning):
    pass


class SettingsConflict(ValueError):
    pass


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / 'settings' / 'settings.sqlite3'
        self.warning = None

    def _warn(self, message):
        self.warning = message
        warnings.warn(message, SettingsWarning, stacklevel=3)

    @contextmanager
    def _read(self):
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS revisions (version INTEGER PRIMARY KEY, payload TEXT NOT NULL, hash TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS profiles (id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(id,version))')
            db.execute('CREATE TABLE IF NOT EXISTS changes (change_id TEXT PRIMARY KEY, changed_at TEXT NOT NULL, old_hash TEXT NOT NULL, new_hash TEXT NOT NULL, profile_id TEXT NOT NULL, profile_version INTEGER NOT NULL, reason TEXT)')
            for table in ('revisions', 'profiles', 'changes'):
                for action in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'Settings history is append-only'); END")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _load(self, db):
        invalid = False
        for version, payload, digest in db.execute('SELECT version,payload,hash FROM revisions ORDER BY version DESC'):
            try:
                state = SettingsState.model_validate_json(payload)
                persisted_shape = state.model_dump(mode='json')
                # Old signed revisions predate the default-OFF monitor field.
                # Verify their original shape without rewriting append-only history.
                if 'paper_monitor_enabled' not in json.loads(payload).get('settings', {}).get('monitoring', {}):
                    persisted_shape['settings']['monitoring'].pop('paper_monitor_enabled')
                if configuration_hash(persisted_shape) != digest or state.settings_version != version:
                    raise ValueError('Revision integrity mismatch')
                if invalid:
                    self._warn('Invalid settings revision detected. Using the last valid configuration; review Settings before trading.')
                return state
            except (ValueError, TypeError):
                invalid = True
        if invalid:
            self._warn('No valid settings revision remains. Using protected baseline defaults; review Settings before trading.')
        return SettingsState()

    def load(self):
        self.warning = None
        if not self.path.exists():
            return SettingsState()
        try:
            with self._read() as db:
                return self._load(db)
        except sqlite3.DatabaseError:
            self._warn('Settings storage is unreadable. Using protected baseline defaults; repair storage before saving or trading.')
            return SettingsState()

    def profiles(self):
        result = [baseline_profile()]
        if self.path.exists():
            try:
                with self._read() as db:
                    for (payload,) in db.execute('SELECT payload FROM profiles ORDER BY rowid'):
                        try:
                            p = StrategyProfile.model_validate_json(payload)
                            if p.profile_id != 'autot-baseline':
                                result.append(p)
                        except ValueError:
                            self._warn('Invalid saved profile skipped; review settings storage.')
            except sqlite3.DatabaseError:
                self._warn('Unable to read custom profiles; protected baseline remains available.')
        return result

    def history(self):
        if not self.path.exists():
            return []
        with self._read() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM changes ORDER BY rowid')]

    def save(self, settings, *, expected_version, profile_name=None, new_profile=False,
             activate=None, reason=None):
        # Revalidation also rejects model_construct/model_copy bypasses.
        settings = AutoTSettings.model_validate(settings.model_dump(mode='json'))
        if profile_name is not None:
            profile_name = profile_name.strip()
            if not profile_name:
                raise ValueError('Profile name must not be blank.')
        with self._write() as db:
            current = self._load(db)
            latest = db.execute('SELECT COALESCE(MAX(version),0) FROM revisions').fetchone()[0]
            if current.settings_version != expected_version:
                raise SettingsConflict('Settings changed in another session. Reload before saving.')
            profile = current.profile
            if activate is not None:
                # Only durable profiles or the protected baseline can be activated.
                if activate == ('autot-baseline', 1):
                    profile = baseline_profile()
                else:
                    row = db.execute('SELECT payload FROM profiles WHERE id=? AND version=?', activate).fetchone()
                    if row is None:
                        raise ValueError('Saved profile not found.')
                    profile = StrategyProfile.model_validate_json(row[0])
                settings = AutoTSettings.model_validate(dict(settings.model_dump(), **profile.configuration.model_dump()))
            config = TradingConfiguration.from_settings(settings)
            changed = config != profile.configuration
            renamed = profile_name is not None and profile_name != profile.profile_name
            if renamed and profile.builtin and not new_profile and not changed:
                raise ValueError('Duplicate the built-in baseline to rename it.')
            if activate is None and (changed or renamed or new_profile):
                create = new_profile or profile.builtin
                pid = str(uuid4()) if create else profile.profile_id
                version = 1 if create else db.execute('SELECT COALESCE(MAX(version),0)+1 FROM profiles WHERE id=?', (pid,)).fetchone()[0]
                now = timestamp()
                profile = StrategyProfile(profile_id=pid,
                    profile_name=profile_name or ('Custom Profile' if profile.builtin else profile.profile_name),
                    profile_version=version, created_at=now if create else profile.created_at,
                    updated_at=now, parent_profile_id=profile.profile_id if create else profile.parent_profile_id,
                    configuration_hash=configuration_hash(config), configuration=config)
                db.execute('INSERT INTO profiles VALUES (?,?,?)', (pid, version, canonical(profile)))
            if settings == current.settings and profile == current.profile and latest == current.settings_version:
                return current  # Reruns/no-op saves do not generate audit noise.
            state = SettingsState(settings_version=latest+1, settings=settings, profile=profile)
            db.execute('INSERT INTO revisions VALUES (?,?,?)', (state.settings_version, canonical(state), configuration_hash(state)))
            db.execute('INSERT INTO changes VALUES (?,?,?,?,?,?,?)',
                       (str(uuid4()), timestamp(), configuration_hash(current.settings), configuration_hash(settings),
                        profile.profile_id, profile.profile_version, reason))
            return state

    def activate(self, profile_id, version, *, expected_version, reason=None):
        return self.save(self.load().settings, expected_version=expected_version,
                         activate=(profile_id, version), reason=reason)
