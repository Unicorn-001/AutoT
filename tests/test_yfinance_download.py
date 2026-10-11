"""Public Yahoo I/O is mocked; AutoT's real executor and cache cleanup run."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, get_ident, current_thread

import pandas as pd
import pytest
from yfinance import cache

from autot.market_data import yfinance_download as downloads
from autot.data.market_data import download_batch_stock_data, download_stock_data


def prices():
    return pd.DataFrame({"Close": range(60), "Open": range(60)})


def test_four_owned_workers_internal_threads_off_and_global_limit(monkeypatch):
    gate = Barrier(4, timeout=5)
    lock = Lock()
    active = peak = 0
    owners = set()
    sessions = []

    def download(**kwargs):
        nonlocal active, peak
        assert kwargs["threads"] is False
        assert isinstance(kwargs["tickers"], str)
        assert kwargs["period"] == "5y" and kwargs["interval"] == "1d"
        assert kwargs["auto_adjust"] is True and kwargs["progress"] is False
        assert "verify" not in kwargs
        assert current_thread().name.startswith("autot-yahoo")
        with lock:
            active += 1
            peak = max(peak, active)
            owners.add(get_ident())
            sessions.append(kwargs["session"])
        try:
            if kwargs["tickers"] != "SPY":
                gate.wait()
            return prices()
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(downloads.yf, "download", download)
    symbols = [f"S{i}" for i in range(16)]
    with ThreadPoolExecutor(max_workers=3) as callers:
        jobs = [callers.submit(download_batch_stock_data, symbols, "5y", "1d", 8)
                for _ in range(2)]
        jobs.append(callers.submit(download_stock_data, "SPY", "5y", "1d"))
        for job in jobs:
            assert job.result(timeout=20) is not None
    assert peak == 4
    assert active == 0
    # Two batches within each scan share one session, closed on operation exit.
    assert len({id(session) for session in sessions}) == 3
    assert all(session._closed for session in sessions)


@pytest.mark.parametrize("fail", [False, True])
def test_owning_worker_cleanup_on_success_and_exception(monkeypatch, fail):
    worker_ids = []
    cleanup_ids = []
    original_close = downloads.close_worker_cache_connections

    def download(**kwargs):
        worker_ids.append(get_ident())
        for getter in (cache.get_tz_cache, cache.get_cookie_cache, cache.get_isin_cache):
            getter().get_db().execute_sql("SELECT 1").fetchone()
        if fail:
            raise RuntimeError("isolated ticker failure")
        return prices()

    def cleanup(databases):
        assert all(not db.is_closed() for db in databases)
        cleanup_ids.append(get_ident())
        original_close(databases)
        assert all(db.is_closed() for db in databases)

    monkeypatch.setattr(downloads.yf, "download", download)
    monkeypatch.setattr(downloads, "close_worker_cache_connections", cleanup)
    with downloads.YahooDownloadPool() as pool:
        result = pool.download(["AAA"], "5y", "1d")["AAA"]
    assert worker_ids == cleanup_ids
    assert worker_ids[0] != get_ident()
    assert (result.error is not None) is fail


def test_repeated_batches_reopen_and_close_worker_cache_without_accumulation(monkeypatch):
    state_lock = Lock()
    open_resources = peak_resources = 0
    cleanup_count = 0
    gate = Barrier(4, timeout=5)
    original_close = downloads.close_worker_cache_connections

    def download(**kwargs):
        nonlocal open_resources, peak_resources
        databases = [getter().get_db() for getter in
                     (cache.get_tz_cache, cache.get_cookie_cache, cache.get_isin_cache)]
        assert all(db.is_closed() for db in databases)
        for db in databases:
            db.execute_sql("SELECT 1").fetchone()
        with state_lock:
            open_resources += 3
            peak_resources = max(peak_resources, open_resources)
        gate.wait()
        return prices()

    def cleanup(databases):
        nonlocal open_resources, cleanup_count
        original_close(databases)
        assert all(db.is_closed() for db in databases)
        with state_lock:
            open_resources -= 3
            cleanup_count += 1

    monkeypatch.setattr(downloads.yf, "download", download)
    monkeypatch.setattr(downloads, "close_worker_cache_connections", cleanup)
    with downloads.YahooDownloadPool() as pool:
        for _ in range(10):
            results = pool.download([f"S{i}" for i in range(8)], "5y", "1d")
            assert all(result.error is None for result in results.values())
            assert open_resources == 0
        assert len(pool.owners) == 4
    assert peak_resources <= 12
    assert cleanup_count == 80


def test_curl_handles_close_in_their_own_workers(monkeypatch):
    opened = set()
    closed = set()
    gate = Barrier(4, timeout=5)
    lock = Lock()

    class Curl:
        def close(self):
            with lock:
                closed.add(get_ident())

    class Session:
        @property
        def curl(self):
            return Curl()

        def close(self):
            pass

    def download(**kwargs):
        with lock:
            opened.add(get_ident())
        gate.wait()
        return prices()

    monkeypatch.setattr(downloads, "Session", lambda **kwargs: Session())
    monkeypatch.setattr(downloads.yf, "download", download)
    with downloads.YahooDownloadPool() as pool:
        pool.download(["A", "B", "C", "D"], "5y", "1d")
    assert len(opened) == 4
    assert closed == opened


def test_cleanup_failure_reaches_circuit_breaker(monkeypatch):
    monkeypatch.setattr(downloads.yf, "download", lambda **kwargs: prices())

    def fail(databases):
        raise downloads.CacheLifecycleError("cleanup failed")

    monkeypatch.setattr(downloads, "close_worker_cache_connections", fail)
    with pytest.raises(downloads.MarketDataInfrastructureError, match="cleanup failed"):
        download_batch_stock_data(["AAA"])


def test_installed_yfinance_concurrent_calls_preserve_independent_results(monkeypatch):
    """Run real yf.download; replace only its public Ticker.history I/O."""
    gate = Barrier(4, timeout=5)

    def history(ticker, **kwargs):
        assert kwargs["period"] == "5y" and kwargs["interval"] == "1d"
        assert kwargs["auto_adjust"] is True
        gate.wait()
        value = int(ticker.ticker[1:])
        return pd.DataFrame(
            {"Close": [value] * 60, "Open": [value] * 60},
            index=pd.date_range("2026-01-01", periods=60),
        )

    monkeypatch.setattr(downloads.yf.Ticker, "history", history)
    symbols = [f"S{i}" for i in range(16)]
    for _ in range(2):
        result = download_batch_stock_data(symbols, "5y", "1d", batch_size=8)
        assert list(result) == symbols
        for i, symbol in enumerate(symbols):
            assert result[symbol][("Close", symbol)].tolist() == [i] * 60


def test_installed_yfinance_swallowed_infrastructure_exception_is_observed(monkeypatch):
    def history(ticker, **kwargs):
        raise RuntimeError("curl: (6) Could not resolve host: query2.finance.yahoo.com")

    monkeypatch.setattr(downloads.yf.Ticker, "history", history)
    with pytest.raises(downloads.MarketDataInfrastructureError, match="Could not resolve host"):
        download_batch_stock_data(["AAA", "BBB"])
