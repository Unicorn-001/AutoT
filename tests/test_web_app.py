from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from autot.application import scanner_service
from autot.settings.configuration_manager import ConfigurationManager
from autot.settings.settings_loader import SettingsLoader


APP = str(Path(__file__).resolve().parents[1] / "web_app.py")


@pytest.fixture(autouse=True)
def scan_defaults(monkeypatch):
    monkeypatch.setattr(SettingsLoader, "load", lambda: {
        "ACTIVE_UNIVERSE": "autot/universe/us_stocks.csv",
        "BACKTEST_PERIOD": "5y", "BACKTEST_INTERVAL": "1d", "TOP_N_STOCKS": "10",
    })


def test_web_scan_uses_service_and_keeps_results_between_reruns(monkeypatch):
    calls = []
    row = {"symbol": "AAA", "rank": 1, "signal": "BUY", "score": 80.0}

    def scan(**kwargs):
        calls.append(kwargs)
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
    assert app.text_input[0].value == config.get_string("ACTIVE_UNIVERSE")
    assert not calls
    app.text_input[0].set_value("autot/universe/my_stocks.csv")
    app.text_input[1].set_value("1y")
    app.text_input[2].set_value("1d")
    app.number_input[0].set_value(3)
    app.button[0].click().run()

    assert not app.exception
    assert calls[0]["universe"] == "autot/universe/my_stocks.csv"
    assert calls[0]["period"] == "1y"
    assert calls[0]["interval"] == "1d"
    assert calls[0]["top_n"] == 3
    assert calls[0]["analyse_func"].__name__ == "analyse_stock"
    import main as cli
    from autot.market_data.market_data_manager import MarketDataManager
    assert cli.MarketDataManager is MarketDataManager
    assert calls[0]["batch_data_loader"] is cli.MarketDataManager.get_batch_stock_data
    assert calls[0]["benchmark_data_loader"] is cli.MarketDataManager.get_stock_data
    from autot.universe.universe_loader import load_universe
    assert calls[0]["universe_loader"] is load_universe
    assert app.metric[0].value == "2"
    assert len(app.dataframe) == 3
    assert any("BBB: Insufficient data" in warning.value for warning in app.warning)
    app.run()
    assert len(calls) == 1
    assert len(app.dataframe) == 3


def test_web_scan_failure_clears_previous_results(monkeypatch):
    def fail(**kwargs):
        raise ValueError("No batch data downloaded")

    monkeypatch.setattr(scanner_service, "run_scan", fail)
    app = AppTest.from_file(APP).run()
    app.session_state["scan"] = {"outputs": {}, "settings": {}, "errors": []}
    app.button[0].click().run()
    assert not app.exception
    assert "No batch data downloaded" in app.error[0].value
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
    assert app.error[0].value == "Enter a universe CSV, backtest period and interval."


def test_web_online_selection_injects_provider_and_runs_shared_scanner(monkeypatch):
    from autot.market_data.market_data_manager import MarketDataManager
    from autot.universe.nasdaq_provider import NasdaqTraderProvider
    from autot.universe.providers import UniverseResult

    calls = []

    def load(provider):
        calls.append(provider)
        return UniverseResult(["AAA", "BRK-B"], "Nasdaq Trader", 2, 0)

    def batch(*, symbols, period, interval):
        assert symbols == ["AAA", "BRK-B"]
        return {}  # No price downloads or trading calculations in this UI test.

    monkeypatch.setattr(NasdaqTraderProvider, "load", load)
    monkeypatch.setattr(MarketDataManager, "get_batch_stock_data", batch)
    monkeypatch.setattr(MarketDataManager, "get_stock_data", lambda *args: object())
    app = AppTest.from_file(APP).run()
    app.selectbox[0].select("Online US Stocks").run()
    assert [field.label for field in app.text_input] == ["Backtest period", "Interval"]
    assert not calls
    app.button[0].click().run()
    assert not app.exception
    assert len(calls) == 1
    assert app.metric[0].value == "2"
    assert "Online US Stocks" in app.caption[1].value
    app.selectbox[0].select("Custom CSV").run()
    assert app.text_input[0].label == "Universe CSV"
    assert len(calls) == 1
