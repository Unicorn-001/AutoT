"""Offline SQLite integration tests; subprocesses isolate yfinance's global caches."""

from pathlib import Path
import subprocess
import sys

import pytest

from autot.market_data import yfinance_cache


ROOT = Path(__file__).resolve().parents[1]


def run_isolated(code, cwd):
    result = subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r})\n" + code],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_library_reproduces_operational_error_without_network(tmp_path):
    output = run_isolated("""
from pathlib import Path
import peewee
import yfinance as yf
from yfinance import cache

directory = Path.cwd() / 'library_cache'
yf.set_tz_cache_location(str(directory))
cookie = cache.get_cookie_cache()
db = cookie.get_db()  # yfinance checks/creates parent before opening SQLite.
assert Path(db.database) == directory / 'cookies.db'
directory.rename(directory.with_name('moved'))
try:
    cookie.lookup('curlCffi')
except peewee.OperationalError as error:
    assert str(error) == 'unable to open database file'
    print(type(error).__module__, str(error), db.database)
else:
    raise AssertionError('The unavailable parent must prevent SQLite opening')
""", tmp_path)
    assert "peewee unable to open database file" in output


def test_absolute_default_path_is_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert yfinance_cache.CACHE_DIR == ROOT / "data_storage" / "yfinance_cache"
    assert yfinance_cache.CACHE_DIR.is_absolute()


def test_creates_real_databases_and_preserves_repeated_access(tmp_path):
    run_isolated("""
from pathlib import Path
import yfinance as yf
from yfinance import cache
from autot.market_data import yfinance_cache as setup

setup.CACHE_DIR = Path.cwd() / 'new' / 'nested' / 'cache'
path = setup.ensure_yfinance_cache()
tz = cache.get_tz_cache()
cookie = cache.get_cookie_cache()
isin = cache.get_isin_cache()
tz.store('UDR', 'America/New_York')
cookie.store('test', {'cached': True})
isin.store('test-isin', 'UDR')
original_db = tz.db
def must_not_relocate(*args):
    raise AssertionError('Repeated access must not reset active databases')
yf.set_tz_cache_location = must_not_relocate
for _ in range(3):
    assert setup.ensure_yfinance_cache() == path
    assert tz.db is original_db
    assert tz.lookup('UDR') == 'America/New_York'
    assert cookie.lookup('test')['cookie'] == {'cached': True}
    assert isin.lookup('test-isin') == 'UDR'
for name in ('tkr-tz.db', 'cookies.db', 'isin-tkr.db'):
    assert (path / name).is_file()
assert tz.db.execute_sql('PRAGMA journal_mode').fetchone()[0] == 'wal'
""", tmp_path)


def test_concurrent_first_use_and_cache_operations(tmp_path):
    run_isolated("""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from yfinance import cache
from autot.market_data import yfinance_cache as setup

setup.CACHE_DIR = Path.cwd() / 'threaded-cache'
barrier = Barrier(8)
def access(index):
    barrier.wait()
    path = setup.ensure_yfinance_cache()
    tz = cache.get_tz_cache()
    cookie = cache.get_cookie_cache()
    try:
        tz.store(f'SYMBOL{index}', 'America/New_York')
        cookie.store(f'test{index}', {'index': index})
        assert tz.lookup(f'SYMBOL{index}') == 'America/New_York'
        assert cookie.lookup(f'test{index}')['cookie'] == {'index': index}
        return path
    finally:
        # Peewee owns separate connections per thread; close worker connections.
        tz.db.close()
        cookie.db.close()
with ThreadPoolExecutor(max_workers=8) as executor:
    paths = list(executor.map(access, range(8)))
assert all(path == setup.CACHE_DIR for path in paths)
for index in range(8):
    assert cache.get_tz_cache().lookup(f'SYMBOL{index}') == 'America/New_York'
""", tmp_path)


def test_cache_setup_error_is_clear_and_prevents_download(tmp_path, monkeypatch):
    from autot.data import market_data

    path = tmp_path / "not_a_directory"
    path.write_text("blocked")
    monkeypatch.setattr(yfinance_cache, "CACHE_DIR", path)
    monkeypatch.setattr(yfinance_cache, "_configured", False)
    monkeypatch.setattr(yfinance_cache.yf, "download", lambda **kwargs: pytest.fail("No download should start"))
    with pytest.raises(RuntimeError, match=f"Unable to initialize yfinance cache at {path}"):
        market_data.download_batch_stock_data(["UDR", "FOXA"], "1y", "1d")


def test_unwritable_cache_is_reported_without_silent_disable(tmp_path, monkeypatch):
    monkeypatch.setattr(yfinance_cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(yfinance_cache, "_configured", False)
    monkeypatch.setattr(yfinance_cache.os, "access", lambda *args: False)
    with pytest.raises(RuntimeError, match="not readable/writable/searchable"):
        yfinance_cache.ensure_yfinance_cache()


@pytest.mark.parametrize("library", [yfinance_cache.yf, yfinance_cache.peewee])
def test_unknown_dependency_version_stops_before_cache_or_download(monkeypatch, library):
    monkeypatch.setattr(library, "__version__", "999.0")
    monkeypatch.setattr(yfinance_cache, "ensure_yfinance_cache", lambda: pytest.fail("No setup"))
    with pytest.raises(yfinance_cache.CacheLifecycleError, match="Unsupported.*versions"):
        yfinance_cache.worker_cache_databases()


def test_changed_cache_layout_fails_safely(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(yfinance_cache, "ensure_yfinance_cache", lambda: None)
    monkeypatch.setattr(yfinance_cache.cache, "get_tz_cache", lambda: SimpleNamespace())
    with pytest.raises(yfinance_cache.CacheLifecycleError, match="Unsupported yfinance cache layout"):
        yfinance_cache.worker_cache_databases()


def test_cleanup_attempts_all_connections_and_reports_failure():
    calls = []

    class DB:
        def __init__(self, name):
            self.database = name

        def is_closed(self):
            return False

        def close(self):
            calls.append(self.database)
            if self.database == "tkr-tz.db":
                raise RuntimeError("close failed")

    with pytest.raises(yfinance_cache.CacheLifecycleError, match="tkr-tz.db: close failed"):
        yfinance_cache.close_worker_cache_connections(tuple(DB(name) for name in (
            "tkr-tz.db", "cookies.db", "isin-tkr.db",
        )))
    assert calls == ["tkr-tz.db", "cookies.db", "isin-tkr.db"]
