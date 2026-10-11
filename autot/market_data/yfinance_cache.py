"""Configure yfinance's persistent caches before any download workers start."""

import logging
import os
from pathlib import Path
from threading import Lock

import yfinance as yf
import peewee
from peewee import DatabaseError
from yfinance import cache


CACHE_DIR = Path(__file__).resolve().parents[2] / "data_storage" / "yfinance_cache"
LOGGER = logging.getLogger(__name__)
_initialization_lock = Lock()
_configured = False

# yfinance has cache location configuration but no public close API. Keep its
# undocumented cache access here. Upgrade these pins only after adapter tests.
SUPPORTED_CACHE_VERSIONS = ("1.4.1", "4.0.8")


class CacheLifecycleError(RuntimeError):
    """Cache layout or cleanup is unsafe; do not start/retry Yahoo requests."""


def worker_cache_databases() -> tuple:
    """Validate yfinance's cache layout before starting workers.

    get_*_cache(), initialise(), get_db(), initialised and dummy are non-public
    yfinance APIs. No managers, proxies, or connection objects are replaced.
    Public Peewee close()/is_closed() act only on the invoking thread.
    """
    if (yf.__version__, peewee.__version__) != SUPPORTED_CACHE_VERSIONS:
        raise CacheLifecycleError(
            "Unsupported yfinance/Peewee cache lifecycle versions: "
            f"{yf.__version__}/{peewee.__version__}; expected "
            f"{'/'.join(SUPPORTED_CACHE_VERSIONS)}. Validate the cache adapter before downloading."
        )
    try:
        ensure_yfinance_cache()
        databases = tuple(
            persistent_cache.get_db()
            for persistent_cache in (
                cache.get_tz_cache(), cache.get_cookie_cache(), cache.get_isin_cache(),
            )
            if persistent_cache.initialised == 1 and not persistent_cache.dummy
        )
        expected = ("tkr-tz.db", "cookies.db", "isin-tkr.db")
        if len(databases) != 3 or any(
            not isinstance(db, peewee.SqliteDatabase)
            or not db.thread_safe or not db.autoconnect
            or Path(db.database) != CACHE_DIR / filename
            for db, filename in zip(databases, expected)
        ):
            raise ValueError("Unexpected cache database layout")
    except (AttributeError, TypeError, ValueError) as error:
        raise CacheLifecycleError(
            "Unsupported yfinance cache layout; downloads stopped before worker creation."
        ) from error
    return databases


def close_worker_cache_connections(databases: tuple) -> None:
    """Close connections owned by this thread without touching other threads."""
    errors = []
    for db in databases:
        try:
            if not db.is_closed():
                db.close()
        except Exception as error:
            errors.append(f"{db.database}: {error}")
    if errors:
        raise CacheLifecycleError("Unable to close Yahoo cache connections: " + "; ".join(errors))


def ensure_yfinance_cache() -> Path:
    """Use an absolute, writable cache and initialize SQLite once per process.

    Streamlit reruns and simultaneous callers must not repeatedly relocate live
    databases. Peewee retains its thread-local connections and yfinance's WAL
    configuration; only first-use setup is serialized, not market downloads.
    """
    global _configured

    with _initialization_lock:
        if _configured:
            return CACHE_DIR
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            if not all(os.access(CACHE_DIR, mode) for mode in (os.R_OK, os.W_OK, os.X_OK)):
                raise PermissionError(f"Cache directory is not readable/writable/searchable: {CACHE_DIR}")
            for filename in ("tkr-tz.db", "cookies.db", "isin-tkr.db"):
                path = CACHE_DIR / filename
                if path.exists() and not all(os.access(path, mode) for mode in (os.R_OK, os.W_OK)):
                    raise PermissionError(f"Cache database is not readable/writable: {path}")

            # Documented API configures timezone, cookie and ISIN caches together.
            # Call before yfinance's threaded batch download touches these caches.
            yf.set_tz_cache_location(str(CACHE_DIR))
            for persistent_cache in (
                cache.get_tz_cache(), cache.get_cookie_cache(), cache.get_isin_cache(),
            ):
                persistent_cache.initialise()
                if persistent_cache.dummy or persistent_cache.initialised != 1:
                    raise OSError("yfinance could not initialize its persistent cache")
        except (OSError, DatabaseError) as error:
            raise RuntimeError(
                f"Unable to initialize yfinance cache at {CACHE_DIR}: {error}"
            ) from error

        _configured = True
        LOGGER.info("yfinance persistent cache initialized at %s", CACHE_DIR)
        return CACHE_DIR
