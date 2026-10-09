"""Configure yfinance's persistent caches before any download workers start."""

import logging
import os
from pathlib import Path
from threading import Lock

import yfinance as yf
from peewee import DatabaseError
from yfinance import cache


CACHE_DIR = Path(__file__).resolve().parents[2] / "data_storage" / "yfinance_cache"
LOGGER = logging.getLogger(__name__)
_initialization_lock = Lock()
_configured = False


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
