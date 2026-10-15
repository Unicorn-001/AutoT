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
from autot.universe.providers import CustomCSVProvider, ProviderUniverseLoader, UploadedCSVProvider
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


def test_builtin_csv_ignores_cwd_and_custom_relative_csv_still_works(tmp_path, monkeypatch):
    expected = load_universe("autot/universe/us_stocks.csv")
    monkeypatch.chdir(tmp_path)
    assert load_universe("autot/universe/us_stocks.csv") == expected
    assert expected
    (tmp_path / "custom.csv").write_text("symbol\nXYZ\n")
    assert CustomCSVProvider("custom.csv").load().symbols == ["XYZ"]


def test_online_download_and_stale_cache_from_another_cwd(tmp_path, monkeypatch, http):
    monkeypatch.chdir(tmp_path)
    provider = NasdaqTraderProvider(tmp_path / "external", clock=lambda: 100)
    expected = provider.load().symbols
    monkeypatch.chdir(PROJECT_ROOT)
    http.side_effect = requests.ConnectionError("offline")
    stale = NasdaqTraderProvider(tmp_path / "external", clock=lambda: 86500).load()
    assert stale.symbols == expected
    assert stale.stale


def test_uploaded_csv_stays_in_memory_and_preserves_order_duplicates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    loader = ProviderUniverseLoader(UploadedCSVProvider(b"\xef\xbb\xbfsymbol,notes\n msft ,one\nBRK.B,two\nmsft,three\n"))
    assert loader("Uploaded CSV") == ["MSFT", "BRK.B", "MSFT"]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("content", [
    b"", b"ticker\nAAPL\n", b"symbol\n", b"symbol\n../private\n",
    b'symbol\n" "\n', b'symbol\n"unclosed', b"symbol\n\xff\n",
    b"x" * (UploadedCSVProvider.MAX_BYTES + 1),
    b"symbol\n" + b"AAPL\n" * (UploadedCSVProvider.MAX_SYMBOLS + 1),
])
def test_uploaded_csv_rejects_invalid_or_excessive_input(content):
    with pytest.raises(ValueError):
        UploadedCSVProvider(content).load()


@pytest.mark.parametrize("symbol", [
    "M&M.NS", "AAPL", "BRK-B", "AZN.L", "BT-A.L", "RELIANCE.NS", "360ONE.NS",
])
def test_uploaded_csv_accepts_yahoo_symbols(symbol):
    result = UploadedCSVProvider(f"symbol\n{symbol}\n".encode()).load()
    assert result.symbols == [symbol]


@pytest.mark.parametrize("symbol", [
    "", "   ", "BAD SYMBOL", "../private", "/etc/passwd", r"C:\private\stocks.csv",
    "https://example.com/M&M.NS", "M&M.NS/../../private", "&", "<script>",
    "A" * 33,
])
def test_uploaded_csv_rejects_malformed_symbols(symbol):
    with pytest.raises(ValueError):
        UploadedCSVProvider(f'symbol\n"{symbol}"\n'.encode()).load()


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


# Index fixtures contain synthetic members; no test relies on live membership.
from autot.market_data.symbols import normalize_index_symbol
from autot.universe.index_definitions import INDICES, COUNTRIES, indices_for_country
from autot.universe.index_provider import IndexUniverseProvider
from autot.universe.index_sources import sources_for


@pytest.mark.parametrize("exchange,raw,expected", [
    ("US", "AAPL", "AAPL"), ("US", "BRK.B", "BRK-B"), ("US", "BF.A", "BF-A"),
    ("US", "BRK-B", "BRK-B"), ("LSE", "AZN", "AZN.L"), ("LSE", "SHEL", "SHEL.L"),
    ("LSE", "NG.", "NG.L"), ("LSE", "BP.", "BP.L"), ("LSE", "RR.", "RR.L"),
    ("LSE", "BT.A", "BT-A.L"), ("LSE", "BT-A.L", "BT-A.L"), ("LSE", "3IN", "3IN.L"),
    ("NSE", "RELIANCE", "RELIANCE.NS"), ("NSE", "TCS", "TCS.NS"), ("NSE", "INFY", "INFY.NS"),
    ("NSE", "M&M", "M&M.NS"), ("NSE", "BAJAJ-AUTO", "BAJAJ-AUTO.NS"),
    ("NSE", " tcs.ns ", "TCS.NS"), ("BSE", "500325", "500325.BO"),
])
def test_market_aware_index_normalization(exchange, raw, expected):
    assert normalize_index_symbol(raw, exchange) == expected
    assert normalize_index_symbol(expected, exchange) == expected
    # The existing downstream Yahoo loader must leave normalized symbols alone.
    assert normalize_market_data_symbol(expected) == expected


@pytest.mark.parametrize("exchange,raw", [("US", "AAPL.NS"), ("LSE", "BAD SYMBOL"),
    ("NSE", "TCS.L"), ("NSE", "../etc"), ("LSE", ""), ("US", None), ("UNKNOWN", "ABC")])
def test_index_normalization_rejects_bad_or_wrong_exchange_symbols(exchange, raw):
    with pytest.raises(ValueError):
        normalize_index_symbol(raw, exchange)


def index_response(definition, source, *, extras=False, count=None):
    count = definition.expected_size if count is None else count
    special = {"US": "BRK.B", "LSE": "BT.A", "NSE": "M&M"}[definition.exchange]
    rows = [(special, "Example Class A"), *[(f"S{i:04d}", f"Company {i}") for i in range(1, count)]]
    if extras:
        rows += [(special, "Duplicate"), ("BAD SYMBOL", "Invalid"), ("", "Empty"), ("VALID", "")]
    response = Mock()
    if source.format == "nasdaq":
        response.json.return_value = {"data": {"data": {"rows": [{"symbol": s, "companyName": n} for s, n in rows]}}}
    elif source.format == "nse":
        response.text = "Company Name,Industry,Symbol,Series,ISIN Code\n" + "\n".join(f"{n},Example,{s},EQ,ISIN" for s, n in rows)
    else:
        header = "<th>Code</th><th>Name</th>" if source.format == "lse" else "<th>Symbol</th><th>Security</th>" if definition.index_id == "sp500" else "<th>Ticker</th><th>Company</th>" if definition.market == "UK" else "<th>Symbol</th><th>Company</th>"
        response.text = "<table><tr>" + header + "</tr>" + "".join(f"<tr><td>{s}</td><td>{n}</td></tr>" for s, n in rows) + "</table>"
    return response


@pytest.mark.parametrize("index_id", list(INDICES))
def test_each_index_live_fetch_validation_cache_and_metadata(tmp_path, monkeypatch, index_id):
    definition = INDICES[index_id]
    source = sources_for(definition)[0]
    response = index_response(definition, source, extras=True)
    get = Mock(return_value=response)
    monkeypatch.setattr("autot.universe.index_provider.requests.get", get)
    provider = IndexUniverseProvider(index_id, tmp_path, clock=lambda: 100)
    result = provider.load()
    assert len(result.symbols) == definition.expected_size
    assert result.downloaded == definition.expected_size + 4
    assert result.filtered == 3
    assert result.duplicates == 1
    assert result.source == source.name and result.source_url == source.url
    assert result.index_id == index_id and result.country == definition.country
    assert result.fetched_at == 100 and not result.cached and not result.stale
    assert result.records[0]["source_symbol"] in ("BRK.B", "BT.A", "M&M")
    assert result.records[0]["yahoo_symbol"] == result.symbols[0]
    assert result.records[0]["company_name"] == "Example Class A"
    assert get.call_args.args == (source.url,)
    assert get.call_args.kwargs["timeout"] == (5, 20)
    assert get.call_args.kwargs.get("verify", True) is True
    response.raise_for_status.assert_called_once()
    cached = IndexUniverseProvider(index_id, tmp_path, clock=lambda: 86499).load()
    assert cached.cached and not cached.stale and cached.fetched_at == 100
    assert cached.records == result.records
    assert get.call_count == 1
    fresh = IndexUniverseProvider(index_id, tmp_path, clock=lambda: 86500).load()
    assert not fresh.cached and fresh.fetched_at == 86500
    assert get.call_count == 2


@pytest.mark.parametrize("index_id", list(INDICES))
def test_each_index_stale_fallback_and_total_failure(tmp_path, monkeypatch, index_id):
    definition = INDICES[index_id]
    get = Mock(return_value=index_response(definition, sources_for(definition)[0]))
    monkeypatch.setattr("autot.universe.index_provider.requests.get", get)
    provider = IndexUniverseProvider(index_id, tmp_path, clock=lambda: 100)
    live = provider.load()
    before = provider.cache_path.read_bytes()
    get.side_effect = requests.Timeout("offline")
    stale = IndexUniverseProvider(index_id, tmp_path, clock=lambda: 86500).load()
    assert stale.cached and stale.stale and stale.fetched_at == 100
    assert stale.symbols == live.symbols
    assert any("stale cache" in w for w in stale.warnings)
    assert provider.cache_path.read_bytes() == before
    with pytest.raises(UniverseLoadError, match="no usable cache"):
        IndexUniverseProvider(index_id, tmp_path / "empty").load()


@pytest.mark.parametrize("index_id", ["nasdaq100", "ftse100", "ftse250", "nifty50"])
def test_preferred_source_failure_uses_identified_same_index_fallback(tmp_path, monkeypatch, index_id):
    definition = INDICES[index_id]
    primary, fallback = sources_for(definition)
    get = Mock(side_effect=[index_response(definition, primary, count=5), index_response(definition, fallback)])
    monkeypatch.setattr("autot.universe.index_provider.requests.get", get)
    result = IndexUniverseProvider(index_id, tmp_path).load()
    assert result.source == fallback.name and result.source_url == fallback.url
    assert any("Preferred source unavailable" in w for w in result.warnings)
    assert any("unofficial" in w for w in result.warnings) == fallback.unofficial


@pytest.mark.parametrize("index_id", list(INDICES))
def test_partial_index_never_cached(tmp_path, monkeypatch, index_id):
    definition = INDICES[index_id]
    responses = [index_response(definition, source, count=5) for source in sources_for(definition)]
    monkeypatch.setattr("autot.universe.index_provider.requests.get", Mock(side_effect=responses))
    provider = IndexUniverseProvider(index_id, tmp_path)
    with pytest.raises(UniverseLoadError):
        provider.load()
    assert not provider.cache_path.exists()


@pytest.mark.parametrize("corruption", ["json", "version", "identity", "future", "nan", "negative", "symbols", "records", "duplicates", "counts", "source", "url", "warnings"])
def test_index_corrupt_cache_not_used(tmp_path, monkeypatch, corruption):
    definition = INDICES["nifty50"]
    get = Mock(return_value=index_response(definition, sources_for(definition)[0]))
    monkeypatch.setattr("autot.universe.index_provider.requests.get", get)
    provider = IndexUniverseProvider("nifty50", tmp_path, clock=lambda: 100)
    provider.load()
    payload = json.loads(provider.cache_path.read_text())
    r = payload["result"]
    if corruption == "version": payload["version"] = -1
    if corruption == "identity": r["index_id"] = "niftynext50"
    if corruption == "future": r["fetched_at"] = 101
    if corruption == "nan": r["fetched_at"] = float("nan")
    if corruption == "negative": r["fetched_at"] = -1
    if corruption == "symbols": r["symbols"][0] = "WRONG.NS"
    if corruption == "records": r["records"][0]["market"] = "US"
    if corruption == "duplicates": r["records"][1] = r["records"][0]
    if corruption == "counts": r["downloaded"] += 1
    if corruption == "source": r["source"] = "Other source"
    if corruption == "url": r["source_url"] = "https://example.test"
    if corruption == "warnings": r["warnings"] = "bad"
    provider.cache_path.write_text("broken" if corruption == "json" else json.dumps(payload))
    get.side_effect = requests.ConnectionError("offline")
    with pytest.raises(UniverseLoadError):
        provider.load()


def test_index_cache_write_failure_keeps_live_result(tmp_path, monkeypatch):
    definition = INDICES["sp500"]
    monkeypatch.setattr("autot.universe.index_provider.requests.get", Mock(return_value=index_response(definition, sources_for(definition)[0])))
    def fail(*args):
        raise PermissionError("private path")
    monkeypatch.setattr(IndexUniverseProvider, "_write_cache", fail)
    result = IndexUniverseProvider("sp500", tmp_path).load()
    assert not result.cached and len(result.symbols) == 500
    assert any("could not be saved" in w for w in result.warnings)
    assert all("private path" not in w for w in result.warnings)


def test_index_catalogue_and_benchmarks():
    assert COUNTRIES == ("United States", "United Kingdom", "India")
    assert [len(indices_for_country(c)) for c in COUNTRIES] == [3, 2, 5]
    with pytest.raises(ValueError, match="Unknown index"):
        IndexUniverseProvider("unknown")


def test_index_cache_respects_runtime_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOT_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert IndexUniverseProvider("sp500").cache_dir == tmp_path / "universe_cache"
    assert IndexUniverseProvider("sp500", "custom/cache").cache_dir == PROJECT_ROOT / "custom/cache"


def test_nse_preserves_non_eq_constituents():
    from autot.universe.index_sources import parse_source
    source = sources_for(INDICES["nifty500"])[0]
    response = Mock(text="Company Name,Industry,Symbol,Series,ISIN Code\nExample REIT,Realty,REIT,RR,ISIN1\nExample Equity,Tech,EQUITY,BE,ISIN2\n")
    assert parse_source(source, response) == [("REIT", "Example REIT"), ("EQUITY", "Example Equity")]


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {"data": {"rows": None}}},
    {"data": {"data": {"rows": []}, "totalrecords": 101}},
    {"data": {"data": {"rows": []}, "totalrecords": None}}])
def test_nasdaq_invalid_or_paginated_response_rejected(payload):
    from autot.universe.index_sources import parse_source
    source = sources_for(INDICES["nasdaq100"])[0]
    with pytest.raises(ValueError):
        parse_source(source, Mock(json=Mock(return_value=payload)))


def test_public_us_sources_use_dedicated_constituent_pages():
    assert sources_for(INDICES["dow30"])[0].url.endswith("/List_of_Dow_Jones_Industrial_Average_companies")
    assert sources_for(INDICES["nasdaq100"])[-1].url.endswith("/List_of_NASDAQ-100_companies")


def test_html_parser_ignores_history_and_retains_share_classes():
    from autot.universe.index_sources import parse_source
    source = sources_for(INDICES["ftse100"])[-1]
    response = Mock(text='''<table><tr><th>Added</th><th>Removed</th></tr><tr><td>OLD</td><td>OTHER</td></tr></table>
    <table><tr><th>Company</th><th>Ticker</th><th>Sector</th></tr>
    <tr><td>Example Group<sup>[1]</sup></td><td>BT.A</td><td>Telecom</td></tr>
    <tr><td>Example Power</td><td>NG.</td><td>Utilities</td></tr>
    <tr><td>Malformed</td></tr></table>''')
    assert parse_source(source, response) == [("BT.A", "Example Group"), ("NG.", "Example Power"), (None, None)]


@pytest.mark.parametrize("index_id", ["sp500", "nasdaq100", "nifty50", "ftse100"])
def test_bad_live_response_uses_stale_cache_without_overwrite(tmp_path, monkeypatch, index_id):
    definition = INDICES[index_id]
    get = Mock(return_value=index_response(definition, sources_for(definition)[0]))
    monkeypatch.setattr("autot.universe.index_provider.requests.get", get)
    provider = IndexUniverseProvider(index_id, tmp_path, clock=lambda: 100)
    provider.load()
    original = provider.cache_path.read_bytes()
    get.return_value = Mock(text="<html>Maintenance</html>", json=Mock(return_value={}))
    stale = IndexUniverseProvider(index_id, tmp_path, clock=lambda: 86500).load()
    assert stale.stale and stale.fetched_at == 100
    assert provider.cache_path.read_bytes() == original


@pytest.mark.parametrize("index_id,benchmark", [
    ("sp500", "SPY"), ("nasdaq100", "^NDX"), ("dow30", "^DJI"),
    ("ftse100", "^FTSE"), ("ftse250", "^FTMC"),
    ("nifty50", "^NSEI"), ("niftynext50", "^NSEI"),
    ("nifty100", "^NSEI"), ("nifty200", "^NSEI"), ("nifty500", "^NSEI"),
])
def test_index_specific_benchmark_mapping(index_id, benchmark):
    assert INDICES[index_id].benchmark_symbol == benchmark
    assert INDICES[index_id].benchmark_display_name
    if index_id.startswith("nifty"):
        assert INDICES[index_id].benchmark_display_name == "NIFTY 50"
