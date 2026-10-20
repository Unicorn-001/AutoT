from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

from autot.paper_trade.intraday import YahooIntradayProvider, HistoryUnavailable
from autot.paper_trade.scan_context import observe_analysis
from autot.paper_trade.sessions import BAR


@pytest.fixture
def chart(monkeypatch):
    stamp = datetime.now(timezone.utc) - timedelta(days=1)
    stamp = stamp.replace(second=0, microsecond=0)
    payload = {"chart": {"error": None, "result": [{
        "meta": {"currency": "GBp"}, "timestamp": [int(stamp.timestamp())],
        "indicators": {"quote": [{"open": [100], "high": [105], "low": [95], "close": [103]}]},
    }]}}
    response = Mock()
    response.json.return_value = payload
    get = Mock(return_value=response)
    monkeypatch.setattr("autot.paper_trade.intraday.requests.get", get)
    return stamp, payload, get


def test_yahoo_adapter_contract_and_certificate_verification(chart):
    stamp, _, get = chart
    batch = YahooIntradayProvider().get_intraday_bars("M&M.NS", stamp, stamp + BAR)
    assert batch.quote_currency == "GBp" and batch.bars[0].open == 100
    assert batch.bars[0].timestamp.tzinfo is not None
    assert get.call_args.args[0].endswith("M%26M.NS")
    kwargs = get.call_args.kwargs
    assert kwargs["params"]["interval"] == "5m"
    assert kwargs["params"]["includePrePost"] == "false"
    assert kwargs.get("verify", True) is True and kwargs["timeout"] == (5, 30)


@pytest.mark.parametrize("mode", ["null", "malformed", "split", "dividend", "http", "currency", "length", "invalid_bar"])
def test_yahoo_bad_or_unsafe_data_is_unavailable(chart, mode):
    stamp, payload, get = chart
    result = payload["chart"]["result"][0]
    if mode == "null": result["indicators"]["quote"][0]["open"] = [None]
    if mode == "malformed": payload["chart"]["result"] = None
    if mode in ("split", "dividend"): result["events"] = {mode: {"test": {}}}
    if mode == "http": get.side_effect = requests.HTTPError("private-response")
    if mode == "currency": del result["meta"]["currency"]
    if mode == "length": result["timestamp"].append(int(stamp.timestamp()) + 300)
    if mode == "invalid_bar": result["indicators"]["quote"][0]["high"] = [1]
    with pytest.raises(HistoryUnavailable):
        YahooIntradayProvider().get_intraday_bars("AAPL", stamp, stamp + BAR)


def test_retention_limit_fails_before_network(chart):
    _, _, get = chart
    end = datetime.now(timezone.utc)
    with pytest.raises(HistoryUnavailable, match="window"):
        YahooIntradayProvider().get_intraday_bars("AAPL", end - timedelta(days=60), end)
    get.assert_not_called()


def test_other_intervals_rejected(chart):
    stamp, _, get = chart
    with pytest.raises(ValueError, match="5m"):
        YahooIntradayProvider().get_intraday_bars("AAPL", stamp, stamp + BAR, interval="1d")
    get.assert_not_called()


@pytest.mark.parametrize("market,symbol,closed", [
    ("US", "AAPL", "2026-10-12T20:00:00+00:00"),
    ("UK", "AZN.L", "2026-10-12T15:30:00+00:00"),
    ("IN", "M&M.NS", "2026-10-12T10:00:00+00:00"),
])
def test_observer_preserves_scanner_outputs_and_records_daily_close(market, symbol, closed):
    frame = pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-10-12"]))
    original = frame.copy(deep=True)
    output = ({"symbol": symbol}, object())
    analyse = Mock(return_value=output)
    context = {}
    wrapper = observe_analysis(analyse, context, interval="1d", market=market,
                               clock=lambda: datetime(2026, 10, 12, 22, tzinfo=timezone.utc))
    assert wrapper(symbol, frame, "benchmark", "tracker") is output
    pd.testing.assert_frame_equal(frame, original)
    analyse.assert_called_once_with(symbol, frame, "benchmark", "tracker")
    assert context[symbol]["eligible"] and context[symbol]["signal_time"] == closed


@pytest.mark.parametrize("interval,frame", [
    ("5m", pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-10-12"]))),
    ("1d", pd.DataFrame({"Close": [100]})),
    ("1d", pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-10-13"]))),
])
def test_ineligible_signal_does_not_change_scan(interval, frame):
    context, result = {}, object()
    wrapper = observe_analysis(lambda *args: result, context, interval=interval,
                               clock=lambda: datetime(2026, 10, 12, 22, tzinfo=timezone.utc))
    assert wrapper("AAPL", frame, None, None) is result
    assert not context["AAPL"]["eligible"]
