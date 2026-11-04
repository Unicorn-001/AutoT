"""Keep offline tests independent of the operator's saved settings and trades."""
import pytest


@pytest.fixture(autouse=True)
def isolated_runtime_data(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOT_DATA_DIR', str(tmp_path / 'runtime'))
