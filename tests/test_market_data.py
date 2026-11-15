import collections
import logging
from threading import Lock

import pandas as pd
import pytest
from peewee import OperationalError

from autot.data import market_data
from autot.market_data import yfinance_download as downloads
from autot.market_data.market_data_manager import MarketDataManager


def prices(rows=60):
    return pd.DataFrame({"Close": range(rows), "Open": range(rows)})


def test_single_download_cache_precedes_yahoo_and_normalizes(monkeypatch):
    expected = pd.concat({"BF-B": prices()}, axis=1).swaplevel(axis=1)
    original = downloads.worker_cache_databases
    initialized = []

    def setup():
        databases = original()
        initialized.append(True)
        return databases

    def download(**kwargs):
        assert initialized == [True]
        assert kwargs["tickers"] == "BF-B"
        assert kwargs["threads"] is False
        return expected

    monkeypatch.setattr(downloads, "worker_cache_databases", setup)
    monkeypatch.setattr(downloads.yf, "download", download)
    assert MarketDataManager.get_stock_data("BF.B", "1y", "1d") is expected


def test_insufficient_single_data_behavior(monkeypatch):
    monkeypatch.setattr(downloads.yf, "download", lambda **kwargs: prices(49))
    with pytest.raises(ValueError, match="Insufficient market data found for symbol: UDR"):
        market_data.download_stock_data("UDR")


def test_batch_normalization_shapes_and_one_isolated_retry(monkeypatch):
    counts = collections.Counter()
    lock = Lock()

    def download(**kwargs):
        symbol = kwargs["tickers"]
        with lock:
            counts[symbol] += 1
            attempt = counts[symbol]
        assert kwargs["threads"] is False
        assert kwargs["period"] == "5y" and kwargs["interval"] == "1d"
        if symbol == "BBB" and attempt == 1:
            return prices(49)
        if symbol == "CCC":
            raise ValueError("isolated ticker problem")
        return pd.concat({symbol: prices()}, axis=1).swaplevel(axis=1)

    monkeypatch.setattr(downloads.yf, "download", download)
    progress = []
    result = market_data.download_batch_stock_data(
        ["BF.B", "BF.B", "BRK.B", "BBB", "CCC"], "5y", "1d", batch_size=2, on_progress=progress.append,
    )
    assert progress[0] == dict(symbols_fetched=2, symbols_failed=0)
    assert progress[-1] == dict(symbols_fetched=4, symbols_failed=1)
    assert counts == {"BF-B": 1, "BRK-B": 1, "BBB": 2, "CCC": 2}
    assert list(result) == ["BF.B", "BRK.B", "BBB"]
    for symbol, data in result.items():
        assert len(data) == 60
        assert data.columns.get_level_values(1).unique().tolist() == [symbol]


@pytest.mark.parametrize("error", [
    RuntimeError("curl: (6) getaddrinfo() thread failed to start"),
    RuntimeError("Could not resolve host: query2.finance.yahoo.com"),
    OperationalError("unable to open database file"),
    RuntimeError("curl: (77) error setting certificate verify locations"),
])
def test_infrastructure_failure_no_retry_fanout_and_preserves_partial(monkeypatch, error):
    calls = []

    def download(**kwargs):
        symbol = kwargs["tickers"]
        calls.append(symbol)
        if symbol == "S0":
            return prices()
        raise error

    monkeypatch.setattr(downloads.yf, "download", download)
    with pytest.raises(downloads.MarketDataInfrastructureError, match="without individual retry") as caught:
        market_data.download_batch_stock_data([f"S{i}" for i in range(100)])
    assert len(calls) == 50
    assert len(set(calls)) == 50
    assert list(caught.value.partial_data) == ["S0"]


def test_swallowed_yfinance_transport_error_trips_breaker(monkeypatch):
    calls = []

    def download(**kwargs):
        calls.append(kwargs["tickers"])
        logging.getLogger("yfinance").error("curl: (6) Could not resolve host: Yahoo")
        return pd.DataFrame()

    monkeypatch.setattr(downloads.yf, "download", download)
    with pytest.raises(downloads.MarketDataInfrastructureError, match="infrastructure"):
        market_data.download_batch_stock_data(["AAA", "BBB"])
    assert sorted(calls) == ["AAA", "BBB"]


def test_broad_ambiguous_empty_batch_stops_without_delisted_classification(monkeypatch):
    calls = []

    def download(**kwargs):
        calls.append(kwargs["tickers"])
        return pd.DataFrame()

    monkeypatch.setattr(downloads.yf, "download", download)
    with pytest.raises(downloads.MarketDataInfrastructureError, match="cause unverified") as caught:
        market_data.download_batch_stock_data([f"S{i}" for i in range(100)])
    assert len(calls) == 50
    assert "delisted" not in str(caught.value)


def test_infrastructure_during_isolated_retry_stops_remaining_retries(monkeypatch):
    counts = collections.Counter()

    def download(**kwargs):
        symbol = kwargs["tickers"]
        counts[symbol] += 1
        if symbol in ("A", "B"):
            if counts[symbol] == 2:
                raise RuntimeError("Could not resolve host: Yahoo")
            return prices(49)
        return prices()

    monkeypatch.setattr(downloads.yf, "download", download)
    with pytest.raises(downloads.MarketDataInfrastructureError):
        market_data.download_batch_stock_data(["A", "B", "C", "D", "E"])
    assert counts == {"A": 2, "B": 1, "C": 1, "D": 1, "E": 1}


def test_invalid_batch_size_does_not_initialize_or_download(monkeypatch):
    monkeypatch.setattr(downloads, "worker_cache_databases", lambda: pytest.fail("No setup"))
    with pytest.raises(ValueError, match="Batch size must be greater than zero"):
        market_data.download_batch_stock_data(["AAA"], batch_size=0)
