"""Deployment plumbing without network requests or trading changes."""

from pathlib import Path
import os
import shutil
import subprocess
import sys

import certifi
import pytest

from autot import runtime
from autot.settings.settings_loader import DEFAULT_SETTINGS, SettingsLoader


@pytest.fixture
def no_ca_overrides(monkeypatch):
    for name in (*runtime.CERTIFICATE_VARIABLES, "SSL_CERT_DIR"):
        monkeypatch.delenv(name, raising=False)


def test_default_paths_and_settings_ignore_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOT_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert runtime.data_dir() == runtime.PROJECT_ROOT / "data_storage"
    assert runtime.BUILTIN_UNIVERSE.is_file()


@pytest.mark.parametrize("relative", [False, True])
def test_runtime_override_creates_writable_directories(tmp_path, monkeypatch, relative):
    monkeypatch.setattr(runtime, "PROJECT_ROOT", tmp_path / "app")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTOT_DATA_DIR", "runtime" if relative else str(tmp_path / "external"))
    expected = tmp_path / "app" / "runtime" if relative else tmp_path / "external"
    assert runtime.initialize_runtime() == expected
    assert runtime.initialize_runtime() == expected
    assert sorted(path.name for path in expected.iterdir()) == ["universe_cache", "yfinance_cache"]
    assert all(path.is_dir() and not list(path.iterdir()) for path in expected.iterdir())


def test_unusable_data_directory_does_not_silently_switch_storage(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    monkeypatch.setenv("AUTOT_DATA_DIR", str(blocked))
    with pytest.raises(OSError):
        runtime.initialize_runtime()


def test_certifi_defaults_and_repeated_initialization(monkeypatch, no_ca_overrides):
    runtime.configure_certificates()
    runtime.configure_certificates()
    for name in runtime.CERTIFICATE_VARIABLES:
        assert runtime.os.environ[name] == certifi.where()
    assert Path(certifi.where()).is_file()


def test_certificate_defaults_keep_client_verification_enabled(no_ca_overrides):
    import ssl
    import requests
    from curl_cffi.requests import Session

    runtime.configure_certificates()
    context = ssl.create_default_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    with Session() as session:
        assert session.verify == certifi.where()
    with requests.Session() as session:
        settings = session.merge_environment_settings("https://example.com", {}, False, None, None)
        assert settings["verify"] == certifi.where()


@pytest.mark.parametrize("name", [*runtime.CERTIFICATE_VARIABLES, "SSL_CERT_DIR"])
@pytest.mark.parametrize("value", ["/operator/trust-store", ""])
def test_explicit_ca_configuration_is_untouched(monkeypatch, no_ca_overrides, name, value):
    monkeypatch.setenv(name, value)
    runtime.configure_certificates()
    assert runtime.os.environ[name] == value
    assert all(other not in runtime.os.environ for other in runtime.CERTIFICATE_VARIABLES if other != name)


def test_fresh_checkout_defaults_and_operator_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    assert SettingsLoader.load() == DEFAULT_SETTINGS
    target = tmp_path / "data" / "config" / "app_settings.csv"
    target.parent.mkdir(parents=True)
    target.write_text("setting,value\nACTIVE_UNIVERSE,/operator/stocks.csv\nTOP_N_STOCKS,7\n")
    assert SettingsLoader.load() == {"ACTIVE_UNIVERSE": "/operator/stocks.csv", "TOP_N_STOCKS": "7"}


def test_explicit_settings_path_is_project_relative(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "PROJECT_ROOT", tmp_path / "app")
    runtime.PROJECT_ROOT.mkdir()
    (runtime.PROJECT_ROOT / "settings.csv").write_text("setting,value\nTOP_N_STOCKS,4\n")
    monkeypatch.chdir(tmp_path)
    assert SettingsLoader.load("settings.csv") == {"TOP_N_STOCKS": "4"}
    with pytest.raises(FileNotFoundError):
        SettingsLoader.load("missing.csv")


def test_relocated_fresh_checkout_starts_from_another_cwd(tmp_path):
    checkout = tmp_path / "relocated-app"
    checkout.mkdir()
    shutil.copytree(runtime.PROJECT_ROOT / "autot", checkout / "autot", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("main.py", "web_app.py"):
        shutil.copy(runtime.PROJECT_ROOT / name, checkout / name)
    environment = dict(os.environ, AUTOT_DATA_DIR=str(tmp_path / "external-data"), PYTHONDONTWRITEBYTECODE="1")
    script = f"""
import sys
sys.path.insert(0, {str(checkout)!r})
from pathlib import Path
from autot.runtime import PROJECT_ROOT, initialize_runtime
from autot.settings.settings_loader import SettingsLoader
from autot.universe.universe_loader import load_universe
from autot.market_data.yfinance_cache import ensure_yfinance_cache
from streamlit.testing.v1 import AppTest
assert PROJECT_ROOT == Path({str(checkout)!r})
assert SettingsLoader.load()['BACKTEST_PERIOD'] == '5y'
assert load_universe('autot/universe/us_stocks.csv')
initialize_runtime()
assert ensure_yfinance_cache().parent == Path({str(tmp_path / 'external-data')!r})
app = AppTest.from_file(str(PROJECT_ROOT / 'web_app.py')).run()
assert not app.exception
assert not app.error
assert app.selectbox[0].value == 'Market Index'
assert app.selectbox[1].value == 'United States'
assert app.selectbox[2].value == 'sp500'
assert not (PROJECT_ROOT / 'data_storage').exists()
"""
    # Prove the app does not need writable source files, not just a different cwd.
    directories = [checkout, *[p for p in checkout.rglob("*") if p.is_dir()]]
    try:
        for directory in directories:
            directory.chmod(0o555)
        result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                                env=environment, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        for directory in directories:
            directory.chmod(0o755)
