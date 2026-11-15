from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from autot.application import scanner_service
from autot.settings.configuration_manager import ConfigurationManager
from autot.settings.settings_loader import SettingsLoader
from autot.universe.index_provider import IndexUniverseProvider
from autot.universe.providers import UniverseResult


APP = str(Path(__file__).resolve().parents[1] / "web_app.py")


@pytest.fixture(autouse=True)
def scan_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOT_DATA_DIR", str(tmp_path / "runtime"))
    from autot import daily_scanner
    def inline_launch(request):
        run = daily_scanner.DailyScanner().once(request)
        return run['scan_run_id']
    monkeypatch.setattr(daily_scanner, 'launch', inline_launch)
    def load(provider):
        d = provider.definition
        return UniverseResult(["AAA", "BBB"], "Fixture source", 2, 0,
                              index_id=d.index_id, country=d.country, index_name=d.index_name,
                              fetched_at=100, source_url="https://example.test/constituents")
    monkeypatch.setattr(IndexUniverseProvider, "load", load)
    monkeypatch.setattr(SettingsLoader, "load", lambda: {
        "ACTIVE_UNIVERSE": "autot/universe/us_stocks.csv",
        "BACKTEST_PERIOD": "5y", "BACKTEST_INTERVAL": "1d", "TOP_N_STOCKS": "10",
    })


def test_web_scan_uses_service_and_keeps_results_between_reruns(monkeypatch):
    calls = []
    row = {"symbol": "AAA", "rank": 1, "signal": "BUY", "score": 80.0, "trade_quality_score": 75.0}

    def scan(**kwargs):
        calls.append(kwargs)
        kwargs["universe_loader"](kwargs["universe"])
        kwargs["diagnostics"].update(usable_market_data_count=2, failures=[{"symbol": "BBB", "reason": "Analysis failed: Insufficient data"}])
        kwargs["on_stage"]("loading_universe", {})
        kwargs["on_stage"]("universe_loaded", {"count": 2})
        kwargs["on_stage"]("analysing", {})
        kwargs["on_success"](1, 2, "AAA")
        kwargs["on_error"]("BBB", ValueError("Insufficient data"))
        kwargs["on_stage"]("ranking", {})
        return {
            "symbols": ["AAA", "BBB"], "results": [row],
            "trade_decisions": {"AAA": object()}, "ranked_results": [row],
            "top_results": [row], "trade_opportunities": [row],
        }

    monkeypatch.setattr(scanner_service, "run_scan", scan)
    app = AppTest.from_file(APP).run()
    config = ConfigurationManager()
    assert app.selectbox[0].value == "Market Index"
    assert not calls
    app.text_input[0].set_value("1y")
    app.text_input[1].set_value("1d")
    app.number_input[0].set_value(3)
    app.button[0].click().run()

    assert not app.exception
    assert calls[0]["universe"] == "sp500"
    assert calls[0]["benchmark_symbol"] == "SPY"
    assert calls[0]["period"] == "1y"
    assert calls[0]["interval"] == "1d"
    assert calls[0]["top_n"] == 3
    assert calls[0]["analyse_func"].__name__ == "analyse_stock"
    import main as cli
    from autot.market_data.market_data_manager import MarketDataManager
    assert cli.MarketDataManager is MarketDataManager
    assert callable(calls[0]["batch_data_loader"])
    assert calls[0]["benchmark_data_loader"] is cli.MarketDataManager.get_stock_data
    assert calls[0]["universe_loader"]("sp500") == ["AAA", "BBB"]
    assert app.metric[0].value == "2"
    assert len(app.dataframe) == 4
    assert app.dataframe[0].value.to_dict("records") == [{"symbol": "BBB", "reason": "Analysis failed; see server logs."}]
    assert "1 of 2" in app.warning[0].value
    app.run()
    assert len(calls) == 1
    assert len(app.dataframe) == 4


def test_web_scan_failure_without_results_reports_failure(monkeypatch):
    def fail(**kwargs):
        raise ValueError("No batch data downloaded")

    monkeypatch.setattr(scanner_service, "run_scan", fail)
    app = AppTest.from_file(APP).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.error[0].value == "Scan failed. Check the universe source, market-data settings and server logs."
    assert len(app.dataframe) == 0
    assert "scan" not in app.session_state


def test_web_rejects_blank_inputs_without_scanning(monkeypatch):
    def unexpected(**kwargs):
        raise AssertionError("Scan should not start")

    monkeypatch.setattr(scanner_service, "run_scan", unexpected)
    app = AppTest.from_file(APP).run()
    app.text_input[0].set_value(" ")
    app.button[0].click().run()
    assert not app.exception
    assert app.error[0].value == "Enter a backtest period and interval."


def test_web_online_selection_injects_provider_and_runs_shared_scanner(monkeypatch):
    from autot.market_data.market_data_manager import MarketDataManager
    from autot.universe.index_provider import IndexUniverseProvider
    from autot.universe.providers import UniverseResult

    calls = []

    def load(provider):
        calls.append(provider)
        return UniverseResult(["AAA", "BRK-B"], "Nasdaq Trader", 2, 0)

    def batch(*, symbols, period, interval, on_progress=None):
        assert symbols == ["AAA", "BRK-B"]
        return {}  # No price downloads or trading calculations in this UI test.

    monkeypatch.setattr(IndexUniverseProvider, "load", load)
    monkeypatch.setattr(MarketDataManager, "get_batch_stock_data", batch)
    monkeypatch.setattr(MarketDataManager, "get_stock_data", lambda *args: object())
    app = AppTest.from_file(APP).run()
    app.selectbox[2].select("nasdaq100").run()
    assert [field.label for field in app.text_input] == ["Backtest period", "Interval"]
    assert not calls
    app.button[0].click().run()
    assert not app.exception
    assert len(calls) == 1
    assert app.metric[0].value == "2"
    assert any("nasdaq100" in caption.value for caption in app.caption)
    app.selectbox[0].select("Upload CSV").run()
    assert app.get("file_uploader")[0].label == "Universe CSV"
    assert len(calls) == 1
    assert app.metric[0].value == "2"


@pytest.mark.parametrize("missing,analysis_failure", [(False, False), (True, False), (False, True)])
def test_completed_scan_counts_reasons_and_opportunities(monkeypatch, missing, analysis_failure):
    from autot.market_data.market_data_manager import MarketDataManager
    import main
    from autot.application.scan_display import OPPORTUNITY_COLUMNS

    row = {
        "symbol": "AAA", "signal": "BUY", "confidence": 71.53,
        "agreement": 60.2, "market_regime": "STRONG_UPTREND",
        "entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
        "risk_reward_ratio": 2.0, "score": 61.12, "trade_quality_score": 72.20,
        "opportunity_score": 90.0, "quantity": 42,
    }
    monkeypatch.setattr("autot.universe.universe_loader.load_universe", lambda _: ["AAA", "BBB"])
    monkeypatch.setattr(MarketDataManager, "get_stock_data", lambda *args: object())
    monkeypatch.setattr(MarketDataManager, "get_batch_stock_data", lambda **kwargs: {symbol: object() for symbol in (["AAA"] if missing else ["AAA", "BBB"])})

    def analyse(symbol, *args):
        if symbol == "BBB" and analysis_failure:
            raise ValueError("indicator input unavailable")
        return dict(row, symbol=symbol), object()

    monkeypatch.setattr(main, "analyse_stock", analyse)
    app = AppTest.from_file(APP).run()
    app.button[0].click().run()
    assert not app.exception
    failed = int(missing or analysis_failure)
    assert {metric.label: metric.value for metric in app.metric} == {
        "Constituents fetched": "2", "Usable market data": str(2 - int(missing)),
        "Successfully analysed": str(2 - failed), "Skipped / failed": str(failed),
        "Trade opportunities": str(2 - failed),
    }
    if failed:
        failures = app.dataframe[0].value.to_dict("records")
        assert failures == [{"symbol": "BBB", "reason": "No usable market data returned; cause unverified" if missing else "Analysis failed; see server logs."}]
        assert "1 of 2" in app.warning[0].value
    else:
        assert not app.warning
        assert not any("Skipped / failed symbols" in exp.label for exp in app.expander)
    table = app.dataframe[int(bool(failed))].value
    assert list(table.columns) == OPPORTUNITY_COLUMNS
    assert table["historical_score"].tolist() == [61.12] * (2 - failed)
    assert table["trade_quality"].tolist() == [72.20] * (2 - failed)
    assert "score" not in table.columns
    assert "trade_quality_score" not in table.columns
    assert "quantity" not in table.columns
    assert any("AAA — BUY: Strong uptrend, 71.53% confidence, 60.20% agreement, risk/reward 2.00, trade quality 72.20 (minimum 70)." == text.value for text in app.markdown)
    saved_row = app.session_state["scan"]["outputs"]["results"][0]
    assert saved_row["score"] == 61.12
    assert saved_row["trade_quality_score"] == 72.20
    assert "historical_score" not in saved_row
    assert "trade_quality" not in saved_row
    assert app.session_state["scan"]["outputs"]["results"][0]["quantity"] == 42
    app.run()
    assert not app.exception
    assert app.metric[3].value == str(failed)


def test_no_trade_opportunities_preserves_ranked_hold_results(monkeypatch):
    row = {"symbol": "AAA", "signal": "HOLD", "score": 99.0}

    def scan(**kwargs):
        kwargs["diagnostics"].update(usable_market_data_count=1, failures=[])
        return {"symbols": ["AAA"], "results": [row], "ranked_results": [row],
                "top_results": [row], "trade_opportunities": [], "trade_decisions": {}}

    monkeypatch.setattr(scanner_service, "run_scan", scan)
    app = AppTest.from_file(APP).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.metric[4].value == "0"
    assert any("No actionable BUY or SELL" in info.value for info in app.info)
    assert len(app.dataframe) == 2
    assert app.dataframe[0].value.iloc[0]["signal"] == "HOLD"


def test_qualification_explanation_does_not_invent_missing_values():
    from autot.application.scan_display import qualification_explanation
    assert qualification_explanation({"symbol": "AAA", "signal": "SELL"}) == "AAA — SELL: No additional calculated details available."


def test_upload_runs_shared_scanner_and_survives_reruns(monkeypatch, tmp_path):
    calls = []

    def scan(**kwargs):
        calls.append(kwargs["universe_loader"](kwargs["universe"]))
        kwargs["diagnostics"].update(usable_market_data_count=0, failures=[])
        return {"symbols": calls[-1], "results": [], "ranked_results": [],
                "top_results": [], "trade_opportunities": [], "trade_decisions": {}}

    monkeypatch.setattr(scanner_service, "run_scan", scan)
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(APP).run()
    app.selectbox[0].select("Upload CSV").run()
    app.file_uploader[0].set_value(("stocks.csv", b"symbol\nAAPL\nMSFT\n", "text/csv"))
    app.button[0].click().run()
    assert not app.exception
    assert calls == [["AAPL", "MSFT"]]
    assert app.metric[0].value == "2"
    assert app.session_state["scan"]["settings"]["universe"] == "Upload CSV"
    app.run()
    app.selectbox[0].select("Market Index").run()
    assert calls == [["AAPL", "MSFT"]]
    assert app.metric[0].value == "2"
    assert not list(tmp_path.rglob("*.csv"))


@pytest.mark.parametrize("content", [None, b"ticker\nAAPL\n", b"symbol\n/secret/path\n"])
def test_invalid_upload_does_not_start_scan(monkeypatch, content):
    monkeypatch.setattr(scanner_service, "run_scan", lambda **kwargs: pytest.fail("No scan"))
    app = AppTest.from_file(APP).run()
    app.selectbox[0].select("Upload CSV").run()
    if content is not None:
        app.file_uploader[0].set_value(("stocks.csv", content, "text/csv"))
    app.button[0].click().run()
    assert not app.exception
    assert len(app.error) == 1
    assert "/secret/path" not in app.error[0].value


def test_scan_errors_are_private_but_logged(monkeypatch, caplog):
    secret_marker = "sensitive-test-marker"

    def fail(**kwargs):
        raise OSError(secret_marker)

    monkeypatch.setattr(scanner_service, "run_scan", fail)
    app = AppTest.from_file(APP).run()
    app.button[0].click().run()
    assert not app.exception
    assert secret_marker not in app.error[0].value
    assert secret_marker in caplog.text


def test_startup_permission_errors_are_private_but_logged(monkeypatch, caplog):
    import autot.runtime as runtime

    def fail():
        raise PermissionError("sensitive-startup-marker")

    monkeypatch.setattr(runtime, "initialize_runtime", fail)
    app = AppTest.from_file(APP).run()
    assert not app.exception
    assert "AUTOT_DATA_DIR" in app.error[0].value
    assert "sensitive-startup-marker" not in app.error[0].value
    assert "sensitive-startup-marker" in caplog.text


def test_analysis_errors_are_private_in_diagnostics_and_session(monkeypatch, caplog):
    from autot.market_data.market_data_manager import MarketDataManager
    import main

    def fail(*args):
        raise ValueError("sensitive-analysis-marker")

    monkeypatch.setattr(IndexUniverseProvider, "load", lambda _: UniverseResult(["AAA"], "Fixture", 1, 0))
    monkeypatch.setattr(MarketDataManager, "get_stock_data", lambda *args: object())
    monkeypatch.setattr(MarketDataManager, "get_batch_stock_data", lambda **kwargs: {"AAA": object()})
    monkeypatch.setattr(main, "analyse_stock", fail)
    app = AppTest.from_file(APP).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["reason"] == "Analysis failed; see server logs."
    assert "sensitive-analysis-marker" not in str(app.session_state["scan"])
    assert "sensitive-analysis-marker" in caplog.text


@pytest.mark.parametrize("country,index_id,benchmark,display_name", [
    ("United States", "sp500", "SPY", "SPDR S&P 500 ETF Trust"),
    ("United States", "nasdaq100", "^NDX", "Nasdaq-100"),
    ("United States", "dow30", "^DJI", "Dow Jones Industrial Average"),
    ("United Kingdom", "ftse100", "^FTSE", "FTSE 100"),
    ("United Kingdom", "ftse250", "^FTMC", "FTSE 250"),
    ("India", "nifty50", "^NSEI", "NIFTY 50"),
    ("India", "niftynext50", "^NSEI", "NIFTY 50"),
    ("India", "nifty100", "^NSEI", "NIFTY 50"),
    ("India", "nifty200", "^NSEI", "NIFTY 50"),
    ("India", "nifty500", "^NSEI", "NIFTY 50"),
])
def test_selected_index_benchmark_reaches_scanner_and_persists(monkeypatch, country, index_id, benchmark, display_name):
    calls = []
    def scan(**kwargs):
        calls.append(kwargs)
        symbols = kwargs["universe_loader"](kwargs["universe"])
        kwargs["diagnostics"].update(usable_market_data_count=0, failures=[])
        return dict(symbols=symbols, results=[], ranked_results=[], top_results=[], trade_opportunities=[], trade_decisions={})
    monkeypatch.setattr(scanner_service, "run_scan", scan)
    app = AppTest.from_file(APP).run()
    app.selectbox[1].select(country).run()
    from autot.universe.index_definitions import INDICES
    assert app.selectbox[2].options == [d.index_name for d in INDICES.values() if d.country == country]
    app.selectbox[2].select(index_id).run()
    app.button[0].click().run()
    assert not app.exception
    assert calls[-1]["universe"] == index_id
    assert calls[-1]["benchmark_symbol"] == benchmark
    saved = app.session_state["scan"]["universe_metadata"]
    assert saved["country"] == country
    assert saved["index_id"] == index_id
    assert saved["benchmark_symbol"] == benchmark
    assert saved["benchmark_display_name"] == display_name
    wording = f"Relative-strength benchmark: {display_name} ({benchmark})"
    assert any(c.value == wording for c in app.caption)
    assert saved["source"] == "Fixture source"
    assert any("Status: Live" in c.value for c in app.caption)
    app.selectbox[1].select("India" if country != "India" else "United States").run()
    assert len(calls) == 1
    assert app.session_state["scan"]["universe_metadata"] == saved
    assert any(country in m.value and INDICES[index_id].index_name in m.value for m in app.markdown)

    assert any(c.value == wording for c in app.caption)


def test_stale_source_warning_survives_rerun(monkeypatch):
    original = IndexUniverseProvider.load
    def stale(provider):
        result = original(provider)
        result.cached = result.stale = True
        result.warnings = ["Live constituent refresh failed; using stale cache. Membership may have changed."]
        return result
    monkeypatch.setattr(IndexUniverseProvider, "load", stale)
    from autot.market_data.market_data_manager import MarketDataManager
    monkeypatch.setattr(MarketDataManager, "get_stock_data", lambda *a: object())
    monkeypatch.setattr(MarketDataManager, "get_batch_stock_data", lambda **kw: {})
    app = AppTest.from_file(APP).run()
    app.button[0].click().run()
    for _ in range(2):
        assert not app.exception
        assert any("stale cache" in w.value for w in app.warning)
        assert any("Status: Stale cache" in c.value and "1970" in c.value for c in app.caption)
        app.run()


def test_index_total_failure_is_clear_and_private(monkeypatch):
    from autot.universe.nasdaq_provider import UniverseLoadError
    def fail(provider):
        raise UniverseLoadError("sensitive-provider-marker")
    monkeypatch.setattr(IndexUniverseProvider, "load", fail)
    app = AppTest.from_file(APP).run()
    app.button[0].click().run()
    assert not app.exception
    assert "Scan failed" in app.error[0].value
    assert "sensitive-provider-marker" not in app.error[0].value
    assert "scan" not in app.session_state
