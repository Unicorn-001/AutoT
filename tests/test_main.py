from types import SimpleNamespace

import main as cli


def test_cli_uses_run_scan_and_preserves_messages_and_reports(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("AUTOT_DATA_DIR", str(tmp_path / "runtime"))
    settings = {
        "ACTIVE_UNIVERSE": "test.csv",
        "BACKTEST_PERIOD": "1y",
        "BACKTEST_INTERVAL": "1d",
    }
    config = SimpleNamespace(get_string=settings.__getitem__, get_int=lambda key: 1)
    tracker = cli.PerformanceTracker()
    portfolio = SimpleNamespace(
        initial_cash=1000.0, cash=1000.0, positions={},
        calculate_portfolio_risk=lambda: 0.0,
    )
    row = {"symbol": "AAA", "score": 90.0, "signal": "HOLD"}
    scan = {
        "symbols": ["AAA", "FAIL", "MISSING"],
        "results": [row],
        "trade_decisions": {"AAA": object()},
        "ranked_results": [row],
        "top_results": [row],
        "trade_opportunities": [],
    }
    reports = []

    def run_scan(**kwargs):
        assert kwargs["universe"] == "test.csv"
        assert kwargs["period"] == "1y"
        assert kwargs["interval"] == "1d"
        assert kwargs["top_n"] == 1
        assert kwargs["max_workers"] == 8
        assert kwargs["tracker"] is tracker
        assert kwargs["analyse_func"] is cli.analyse_stock
        assert kwargs["universe_loader"] is cli.load_universe
        assert kwargs["batch_data_loader"] == cli.MarketDataManager.get_batch_stock_data
        assert kwargs["benchmark_data_loader"] == cli.MarketDataManager.get_stock_data
        for stage, details in [
            ("loading_universe", {}),
            ("universe_loaded", {"count": 3}),
            ("loading_market_data", {}),
            ("analysing", {}),
        ]:
            kwargs["on_stage"](stage, details)
        kwargs["on_success"](1, 3, "AAA")
        kwargs["on_error"]("FAIL", ValueError("Analysis failed"))
        kwargs["on_stage"]("ranking", {})
        return scan

    monkeypatch.setattr(cli, "ConfigurationManager", lambda: config)
    monkeypatch.setattr(cli, "PerformanceTracker", lambda: tracker)
    monkeypatch.setattr(cli, "load_or_create_portfolio", lambda **kwargs: portfolio)
    monkeypatch.setattr(cli, "load_open_journal_entries", lambda: {})
    monkeypatch.setattr(cli, "run_scan", run_scan)
    monkeypatch.setattr(cli.os, "makedirs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cli, "save_results_to_csv",
        lambda rows, path, metadata: reports.append((rows, path, metadata)),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "5")

    cli.main()

    lines = capsys.readouterr().out.splitlines()
    scan_lines = [line for line in lines if line in {
        "▶ Loading universe", "Loaded 3 symbols",
        "▶ Loading market data from cache/download",
        "Completed 1 / 3: AAA", "Error analysing FAIL: Analysis failed",
        "▶ Ranking results",
    }]
    assert scan_lines == [
        "▶ Loading universe", "Loaded 3 symbols",
        "▶ Loading market data from cache/download",
        "▶ Loading market data from cache/download",
        "Completed 1 / 3: AAA", "Error analysing FAIL: Analysis failed",
        "▶ Ranking results",
    ]
    assert "1. AAA | Score: 90.00 | Signal: HOLD" in lines
    assert "Exiting Manual Paper Trading Mode." in lines
    assert len(reports) == 4
    for report, key in zip(reports, [
        "ranked_results", "top_results", "trade_opportunities", "trade_opportunities",
    ]):
        assert report[0] is scan[key]
        assert report[2]["universe"] == "test.csv"
    assert reports[2][1] == str(tmp_path / "runtime" / "processed" / "trade_opportunities.csv")
