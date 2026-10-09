from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest
from yfinance import cache

from autot.data import market_data
from autot.market_data import yfinance_cache
from autot.market_data.market_data_manager import MarketDataManager


def prices():
    return pd.DataFrame({"Close": range(60), "Open": range(60)})


def test_single_download_initializes_cache_before_yahoo(monkeypatch):
    calls = []
    expected = prices()
    monkeypatch.setattr(market_data, "ensure_yfinance_cache", lambda: calls.append("cache"))

    def download(**kwargs):
        assert calls == ["cache"]
        assert kwargs["tickers"] == "BF-B"
        assert kwargs["threads"] is False
        assert kwargs["auto_adjust"] is True
        return expected

    monkeypatch.setattr(market_data.yf, "download", download)
    actual = MarketDataManager.get_stock_data("BF.B", "1y", "1d")
    assert actual is expected


def test_threaded_batches_use_real_initialized_cache_and_keep_results(monkeypatch):
    # Network is mocked; yfinance's actual SQLite cache operates in each worker.
    def worker(symbol):
        tz = cache.get_tz_cache()
        assert tz.initialised == 1 and not tz.dummy
        try:
            tz.store(symbol, "America/New_York")
            assert tz.lookup(symbol) == "America/New_York"
            return symbol, prices()
        finally:
            tz.db.close()

    def download(**kwargs):
        assert Path(cache._TzDBManager.get_location()) == yfinance_cache.CACHE_DIR
        assert kwargs["threads"] is True
        with ThreadPoolExecutor(max_workers=3) as executor:
            return pd.concat(dict(executor.map(worker, kwargs["tickers"])), axis=1)

    monkeypatch.setattr(market_data.yf, "download", download)
    symbols = ["UDR", "FOXA", "BF.B"]
    for _ in range(2):
        result = MarketDataManager.get_batch_stock_data(symbols, "1y", "1d")
        assert list(result) == symbols
        for symbol in symbols:
            assert len(result[symbol]) == 60
            assert result[symbol].columns.get_level_values(1).unique().tolist() == [symbol]


def test_insufficient_data_behavior_is_unchanged(monkeypatch):
    monkeypatch.setattr(market_data, "ensure_yfinance_cache", lambda: None)
    monkeypatch.setattr(market_data.yf, "download", lambda **kwargs: prices().iloc[:49])
    with pytest.raises(ValueError, match="Insufficient market data found for symbol: UDR"):
        market_data.download_stock_data("UDR")
