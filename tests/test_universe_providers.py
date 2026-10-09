"""Offline regression coverage for official directory parsing and caching."""

import json
from unittest.mock import Mock

import pytest
import requests

from autot.market_data.symbols import normalize_market_data_symbol
from autot.universe.nasdaq_provider import (
    DEFAULT_CACHE_DIR, PROJECT_ROOT, NasdaqTraderProvider, UniverseLoadError,
    parse_directory,
)
from autot.universe.providers import CustomCSVProvider, ProviderUniverseLoader
from autot.universe.universe_loader import load_universe


NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple|Q|N|N|100|N|N
ODD|Unusual Trust L.P. - Common Shares|S|N|N|100|N|N
TEST|Test|Q|Y|N|100|N|N
FUND|ETF|Q|N|N|100|Y|N
BAD|Deficient|Q|N|D|100|N|N
|Blank|Q|N|N|100|N|N
BAD SYMBOL|Malformed|Q|N|N|100|N|N
SHORT|Missing fields
File Creation Time: 1009202617:03|||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire common|N|BRK.B|N|100|N|BRK.B
BF.A|Class A|N|BF.A|N|100|N|BF.A
AAPL|Duplicate|N|AAPL|N|100|N|AAPL
BRK-B|Normalized duplicate|N|BRK-B|N|100|N|BRK-B
ABR$D|Preferred|N|ABRpD|N|100|N|ABR-D
AAC.W|Warrant|N|AAC.WS|N|100|N|AAC+
TEST|Test|N|TEST|N|100|Y|TEST
ETF|Fund|P|ETF|Y|100|N|ETF
File Creation Time: 1009202617:03|||||||
"""


@pytest.fixture
def http(monkeypatch):
    def response(url, timeout):
        assert url.startswith("https://www.nasdaqtrader.com/")
        assert timeout == 30
        result = Mock()
        result.text = NASDAQ if url.endswith("nasdaqlisted.txt") else OTHER
        return result
    get = Mock(side_effect=response)
    monkeypatch.setattr("autot.universe.nasdaq_provider.requests.get", get)
    return get


def test_parse_nasdaq_filters_flags_malformed_and_footer():
    result = parse_directory(NASDAQ, "nasdaqlisted")
    assert result.symbols == ["AAPL", "ODD"]
    assert result.downloaded == 9
    assert result.filtered == 7
    assert result.records[0]["source_symbol"] == "AAPL"


def test_parse_other_preserves_act_symbols_and_normalizes_classes():
    result = parse_directory(OTHER, "otherlisted")
    assert result.symbols == ["BRK-B", "BF-A", "AAPL", "BRK-B"]
    assert result.records[0]["source_symbol"] == "BRK.B"
    assert result.downloaded == 9
    assert result.filtered == 5


@pytest.mark.parametrize("status", list("DEQGHJK"))
def test_known_non_normal_financial_statuses_excluded(status):
    result = parse_directory(NASDAQ.replace("|N|D|", f"|N|{status}|"), "nasdaqlisted")
    assert "BAD" not in result.symbols


def test_absent_financial_status_is_supported():
    result = parse_directory("Symbol|Security Name|Test Issue|ETF\nAAA|Name|N|N\n", "nasdaqlisted")
    assert result.symbols == ["AAA"]


@pytest.mark.parametrize("text", ["<html>Error</html>", "Symbol|Security Name\nAAA|Name"])
def test_wrong_format_raises(text):
    with pytest.raises(ValueError, match="missing required headers"):
        parse_directory(text, "nasdaqlisted")


@pytest.mark.parametrize("source,expected", [
    ("BRK.B", "BRK-B"), ("BF.B", "BF-B"), ("BF.A", "BF-A"),
    ("BRK-B", "BRK-B"), (" aapl ", "AAPL"), ("VOD.L", "VOD.L"),
    ("AAC.W", "AAC.W"), ("AAC.U", "AAC.U"), ("ABR$D", "ABR$D"),
])
def test_symbol_normalization(source, expected):
    assert normalize_market_data_symbol(source) == expected


def test_price_loader_uses_the_same_normalizer():
    from autot.data.market_data import _to_yahoo_symbol

    for symbol in ["BRK.B", "BF.B", "BF.A", "AAC.W", "VOD.L"]:
        assert _to_yahoo_symbol(symbol) == normalize_market_data_symbol(symbol)


def test_download_deduplicates_after_normalization_and_creates_cache(tmp_path, http):
    provider = NasdaqTraderProvider(tmp_path / "new", clock=lambda: 100)
    result = ProviderUniverseLoader(provider)("Online US Stocks")
    assert result == ["AAPL", "ODD", "BRK-B", "BF-A"]
    assert http.call_count == 2
    assert provider.cache_path.exists()
    cached = provider.load()
    assert (cached.downloaded, cached.filtered, cached.duplicates) == (18, 12, 2)
    assert cached.cached and not cached.stale
    assert http.call_count == 2


def test_cache_hit_across_provider_instances(tmp_path, http):
    first = NasdaqTraderProvider(tmp_path, clock=lambda: 100).load()
    second = NasdaqTraderProvider(tmp_path, clock=lambda: 86499).load()
    assert second.symbols == first.symbols
    assert second.cached
    assert http.call_count == 2


def test_cache_expiry_refreshes_at_24_hours(tmp_path, http):
    NasdaqTraderProvider(tmp_path, clock=lambda: 100).load()
    result = NasdaqTraderProvider(tmp_path, clock=lambda: 86500).load()
    assert not result.cached
    assert http.call_count == 4


def test_network_failure_uses_stale_cache_without_resetting_age(tmp_path, http, caplog):
    provider = NasdaqTraderProvider(tmp_path, clock=lambda: 100)
    expected = provider.load()
    before = provider.cache_path.read_text()
    http.side_effect = requests.ConnectionError("offline")
    result = NasdaqTraderProvider(tmp_path, clock=lambda: 86500).load()
    assert result.symbols == expected.symbols
    assert result.cached and result.stale
    assert provider.cache_path.read_text() == before
    assert "using stale universe cache" in caplog.text


def test_network_failure_without_cache_raises(tmp_path, http):
    http.side_effect = requests.Timeout("offline")
    with pytest.raises(UniverseLoadError, match="no usable cache"):
        NasdaqTraderProvider(tmp_path).load()


@pytest.mark.parametrize("body", ["<html>Service unavailable</html>",
    "Symbol|Security Name|Test Issue|ETF\nFile Creation Time: 1234|||\n"])
def test_invalid_or_empty_download_is_not_cached(tmp_path, http, body):
    http.side_effect = None
    http.return_value = Mock(text=body)
    provider = NasdaqTraderProvider(tmp_path)
    with pytest.raises(UniverseLoadError):
        provider.load()
    assert not provider.cache_path.exists()


def test_diagnostics_report_fresh_and_cached_counts(tmp_path, http, caplog):
    caplog.set_level("INFO", logger="autot.universe.nasdaq_provider")
    provider = NasdaqTraderProvider(tmp_path)
    provider.load()
    provider.load()
    assert "downloaded=18 filtered=12 duplicates=2 symbols=4 cached=False" in caplog.text
    assert "symbols=4 cached=True stale=False" in caplog.text


@pytest.mark.parametrize("corruption", ["broken", "empty", "invalid_symbol", "future"])
def test_invalid_cache_is_not_used_as_fallback(tmp_path, http, corruption):
    provider = NasdaqTraderProvider(tmp_path, clock=lambda: 100)
    provider.load()
    payload = json.loads(provider.cache_path.read_text())
    if corruption == "empty":
        payload["result"]["symbols"] = []
    elif corruption == "invalid_symbol":
        payload["result"]["symbols"][0] = "BAD SYMBOL"
    elif corruption == "future":
        payload["downloaded_at"] = 101
    provider.cache_path.write_text("broken" if corruption == "broken" else json.dumps(payload))
    http.side_effect = requests.ConnectionError("offline")
    with pytest.raises(UniverseLoadError):
        provider.load()


def test_partial_refresh_does_not_overwrite_cache(tmp_path, http):
    provider = NasdaqTraderProvider(tmp_path, clock=lambda: 100)
    expected = provider.load()
    original = provider.cache_path.read_text()
    good = Mock(text=NASDAQ)
    http.side_effect = [good, requests.HTTPError("503")]
    result = NasdaqTraderProvider(tmp_path, clock=lambda: 86500).load()
    assert result.symbols == expected.symbols
    assert result.stale
    assert provider.cache_path.read_text() == original


def test_paths_are_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert NasdaqTraderProvider().cache_dir == DEFAULT_CACHE_DIR
    assert NasdaqTraderProvider("custom/cache").cache_dir == PROJECT_ROOT / "custom/cache"


def test_existing_csv_behavior_unchanged(tmp_path):
    path = tmp_path / "stocks.csv"
    path.write_text('symbol,other\n aapl ,1\n,2\naapl,3\n" ",4\nBF.B,5\nAAC.W,6\nABR$D,7\n')
    expected = ["AAPL", "AAPL", "", "BF.B", "AAC.W", "ABR$D"]
    assert load_universe(str(path)) == expected
    assert CustomCSVProvider(str(path)).load().symbols == expected
    assert ProviderUniverseLoader(CustomCSVProvider(str(path)))(str(path)) == expected


def test_csv_missing_symbol_column_still_raises(tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text("ticker\nAAPL\n")
    with pytest.raises(ValueError, match="symbol"):
        CustomCSVProvider(str(path)).load()


@pytest.mark.parametrize("directory,symbol,name,cqs", [
    ("otherlisted", "AAC.W", "Ares Acquisition Corporation III Redeemable warrants, each whole warrant exercisable for one Class A ordinary share", "AAC.WS"),
    ("otherlisted", "AAC.U", "Ares Acquisition Corporation III Units, each consisting of one Class A ordinary share and one warrant", "AAC.U"),
    ("otherlisted", "AIIA.R", "AI Infrastructure Acquisition Corp. Rights, each entitling the holder to receive one Class A Ordinary Share", "AIIAr"),
    ("otherlisted", "ABR$D", "Arbor Realty Trust 6.375% Series D Cumulative Redeemable Preferred Stock", "ABRpD"),
    ("otherlisted", "PREF", "Example Depositary Shares, each representing an interest in Preferred Stock", "PREFpA"),
    ("otherlisted", "ISS.A", "Example", "ISS.WS.A"),
    ("otherlisted", "RIGHT", "Example", "RIGHTr"),
    ("otherlisted", "BUNDLE", "Example Units, each consisting of one Ordinary Share and one Right", "BUNDLE"),
    ("otherlisted", "WARRANT", "Example Warrants, each exercisable for one Common Stock share", "WARRANT"),
    ("otherlisted", "SUBR", "Example Subscription Rights to receive one Ordinary Share", "SUBR"),
    ("otherlisted", "ABXL", "Abacus Global Management, Inc. 9.875% Fixed Rate Senior Notes due 2028", "ABXL"),
    ("otherlisted", "EAI", "Entergy Arkansas, LLC First Mortgage Bonds, 4.875% Series Due September 1, 2066", "EAI"),
    ("otherlisted", "AFGB", "American Financial Group, Inc. 5.875% Subordinated Debentures due 2059", "AFGB"),
    ("nasdaqlisted", "AACIW", "Armada Acquisition Corp. III - Warrant", ""),
    ("nasdaqlisted", "AACIU", "Armada Acquisition Corp. III - Units", ""),
    ("nasdaqlisted", "AACPR", "Apogee Acquisition Corp - Rights", ""),
    ("nasdaqlisted", "HAVAR", "Harvard Ave Acquisition Corporation - Rights that convert on a 1/10th of 1 basis to Class A ordinary Shares", ""),
    ("nasdaqlisted", "FIGXW", "FIGX Capital Acquisition Corp. - one-half of one redeemable warrant.", ""),
    ("nasdaqlisted", "CHSCN", "CHS Inc - Preferred Class B Series 2 Reset Rate", ""),
    ("nasdaqlisted", "ACGLN", "Arch Capital Group Ltd. - Depositary Shares, each Representing an Interest in a Non-Cumulative Preferred Share, Series G", ""),
    ("nasdaqlisted", "PREF", "Example - Series A Preference Shares", ""),
    ("nasdaqlisted", "CONV", "Example - Convertible Preferred Shares convertible into Common Stock", ""),
    ("nasdaqlisted", "RWAYI", "Runway Growth Finance Corp. - 7.25% Notes due 2031", ""),
    ("nasdaqlisted", "ETN", "Example - Exchange-Traded Notes", ""),
])
def test_non_common_equity_is_excluded(directory, symbol, name, cqs):
    text = directory_row(directory, symbol, name, cqs)
    result = parse_directory(text, directory)
    assert result.symbols == []
    assert result.filtered == 1


def directory_row(directory, symbol, name, cqs=""):
    if directory == "nasdaqlisted":
        return f"Symbol|Security Name|Test Issue|Financial Status|ETF\n{symbol}|{name}|N|N|N\n"
    return f"ACT Symbol|Security Name|CQS Symbol|Test Issue|ETF\n{symbol}|{name}|{cqs or symbol}|N|N\n"


@pytest.mark.parametrize("directory,symbol,name,expected", [
    ("otherlisted", "BRK.B", "Berkshire Hathaway Inc. New Common Stock", "BRK-B"),
    ("otherlisted", "BF.B", "Brown Forman Inc Class B Common Stock", "BF-B"),
    ("otherlisted", "BF.A", "Brown Forman Inc Class A Common Stock", "BF-A"),
    ("nasdaqlisted", "AAPL", "Apple Inc. - Common Stock", "AAPL"),
    ("nasdaqlisted", "FOXA", "Fox Corporation - Class A Common Stock", "FOXA"),
    ("nasdaqlisted", "PFBC", "Preferred Bank - Common Stock", "PFBC"),
    ("nasdaqlisted", "OBAI", "Our Bond, Inc. - Common Stock", "OBAI"),
    ("nasdaqlisted", "ARLP", "Alliance Resource Partners, L.P. - Common Units Representing Limited Partnership Interests", "ARLP"),
    ("nasdaqlisted", "ACIC", "American Coastal Insurance Corporation - Common Stock", "ACIC"),
    ("otherlisted", "AMX", "America Movil American Depositary Shares (each representing the right to receive twenty Series B Shares)", "AMX"),
    ("otherlisted", "WDH", "Waterdrop Inc. American Depositary Shares (each representing the right to receive 10 Class A Ordinary Shares)", "WDH"),
    ("otherlisted", "CQP", "Cheniere Energy Partners, LP Common Units", "CQP"),
    ("otherlisted", "DMB", "BNY Mellon Municipal Bond Infrastructure Fund, Inc. Common Stock", "DMB"),
    ("otherlisted", "PTA", "Cohen & Steers Tax-Advantaged Preferred Securities and Income Fund Common Shares of Beneficial Interest", "PTA"),
    ("otherlisted", "REIT", "Example Realty Trust Common Shares", "REIT"),
    ("otherlisted", "ODD", "Warrants Rights Units Preferred Notes Holdings Common Stock", "ODD"),
    ("nasdaqlisted", "ODDW", "Unusual Company - Common Stock", "ODDW"),
    ("nasdaqlisted", "ODDU", "Unusual Company - Ordinary Shares", "ODDU"),
    ("nasdaqlisted", "ODDR", "Unusual Company - Common Shares", "ODDR"),
])
def test_common_equity_and_unusual_issuer_names_are_kept(directory, symbol, name, expected):
    result = parse_directory(directory_row(directory, symbol, name), directory)
    assert result.symbols == [expected]
    assert result.records[0]["security_name"] == name


def test_previous_broad_universe_cache_is_invalidated(tmp_path, http):
    provider = NasdaqTraderProvider(tmp_path, clock=lambda: 100)
    provider.load()
    payload = json.loads(provider.cache_path.read_text())
    payload["version"] = 1
    provider.cache_path.write_text(json.dumps(payload))
    result = provider.load()
    assert not result.cached
    assert http.call_count == 4
    payload["version"] = 1
    provider.cache_path.write_text(json.dumps(payload))
    http.side_effect = requests.ConnectionError("offline")
    with pytest.raises(UniverseLoadError):
        provider.load()
