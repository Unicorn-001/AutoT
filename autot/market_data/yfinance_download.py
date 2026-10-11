"""AutoT owns Yahoo worker lifetime; yfinance's internal threading stays off."""

from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
import logging
from threading import Barrier, Lock, RLock, get_ident

from curl_cffi.requests import Session
from peewee import DatabaseError
import yfinance as yf

from autot.market_data.yfinance_cache import (
    CacheLifecycleError, close_worker_cache_connections, worker_cache_databases,
)


YAHOO_DOWNLOAD_WORKERS = 4
_download_lock = RLock()


class MarketDataInfrastructureError(RuntimeError):
    """Abort retry fan-out; retain usable datasets for explicit recovery."""

    def __init__(self, message, *, partial_data=None):
        super().__init__(message)
        self.partial_data = {} if partial_data is None else partial_data


def is_infrastructure_failure(error) -> bool:
    if isinstance(error, (DatabaseError, CacheLifecycleError, MarketDataInfrastructureError)):
        return True
    message = str(error).lower()
    return any(marker in message for marker in (
        "getaddrinfo", "could not resolve", "curl: (6)",
        "unable to open database file", "database is locked", "operationalerror",
        "curl: (77)", "certificate verify locations", "curl: (60)",
        "certificate verify failed", "curl: (28)", "timed out", "timeout",
        "curl: (7)", "curl: (35)", "curl: (55)", "curl: (56)",
        "too many requests", "ratelimit", "rate limit", "http error 429",
        "can't start new thread", "cannot start new thread", "too many open files",
        "resource temporarily unavailable",
    ))


@dataclass
class DownloadResult:
    data: object = None
    error: Exception | None = None


class _WorkerErrors(logging.Handler):
    """Observe swallowed yf.download errors without changing logger levels."""

    def __init__(self):
        super().__init__(logging.ERROR)
        self.owner = get_ident()
        self.infrastructure = []

    def emit(self, record):
        if record.thread == self.owner:
            message = record.getMessage()
            if is_infrastructure_failure(message):
                self.infrastructure.append(message)


class YahooDownloadPool:
    """Reuse up to four workers and one supported session across a whole scan.

    Top-level AutoT operations serialize because yfinance has singleton HTTP
    state. Each yf.download has its own result context (in the pinned version)
    and receives the same session. curl_cffi has a thread-local worker handle.
    """

    def __enter__(self):
        _download_lock.acquire()
        self.session = None
        try:
            self.databases = worker_cache_databases()
            self.session = Session(impersonate="chrome")
            self.executor = ThreadPoolExecutor(
                max_workers=YAHOO_DOWNLOAD_WORKERS, thread_name_prefix="autot-yahoo",
            )
            self.owners = set()
            self.owners_lock = Lock()
            return self
        except BaseException:
            if self.session is not None:
                self.session.close()
            _download_lock.release()
            raise

    def _download(self, symbol, period, interval):
        with self.owners_lock:
            self.owners.add(get_ident())
        observer = _WorkerErrors()
        logger = logging.getLogger("yfinance")
        logger.addHandler(observer)
        try:
            data = yf.download(
                tickers=symbol, period=period, interval=interval,
                auto_adjust=True, progress=False, threads=False, session=self.session,
            )
            if observer.infrastructure:
                return DownloadResult(error=MarketDataInfrastructureError(
                    f"Yahoo infrastructure failure for {symbol}: " + observer.infrastructure[0]
                ))
            return DownloadResult(data=data)
        except Exception as error:
            return DownloadResult(error=error)
        finally:
            logger.removeHandler(observer)
            close_worker_cache_connections(self.databases)

    def download(self, symbols, period, interval) -> dict[str, DownloadResult]:
        futures = {}
        results = {}
        try:
            for symbol in symbols:
                futures[symbol] = self.executor.submit(self._download, symbol, period, interval)
            for symbol, future in futures.items():
                try:
                    results[symbol] = future.result()
                except Exception as error:
                    results[symbol] = DownloadResult(error=error)
        except BaseException:
            # Finish running requests before scheduling owning-worker finalizers
            # even on interruption or native thread-creation failure.
            for future in futures.values():
                future.cancel()
            wait(futures.values())
            raise
        return results

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            # Finalizers occupy different workers until all close their own
            # curl handle. Session.close() alone only closes the caller's.
            # Session.curl and Curl.close() are public curl_cffi APIs.
            if self.owners:
                barrier = Barrier(len(self.owners))

                def finish_worker():
                    try:
                        self.session.curl.close()
                    finally:
                        barrier.wait()

                endings = [self.executor.submit(finish_worker) for _ in self.owners]
                for ending in endings:
                    ending.result()
        finally:
            try:
                self.executor.shutdown(wait=True)
                self.session.close()
            finally:
                _download_lock.release()
