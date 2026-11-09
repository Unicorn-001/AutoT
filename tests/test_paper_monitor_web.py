"""Status presentation via offline AppTest; no Streamlit server is launched."""
from streamlit.testing.v1 import AppTest

from autot.paper_trade.locking import database_lock
from autot.settings.models import AutoTSettings, Monitoring
from autot.settings.store import SettingsStore
from tests.test_paper_web import ui, APP


def test_monitor_panel_distinguishes_configuration_and_process(ui):
    service, provider, _ = ui
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value('Paper Trading').run()
    assert not app.exception
    assert any('Configured: OFF' in m.value and 'NOT DETECTED' in m.value for m in app.markdown)
    SettingsStore().save(AutoTSettings(monitoring=Monitoring(paper_monitor_enabled=True)), expected_version=0)
    app.run()
    assert any('Configured: ON' in m.value and 'NOT DETECTED' in m.value for m in app.markdown)
    with database_lock(service.ledger.path, 'monitor', blocking=False):
        app.run()
        assert any('Configured: ON' in m.value and 'Process: ACTIVE' in m.value for m in app.markdown)
    assert any('python -m autot.paper_monitor --status' in c.value for c in app.code)
    assert not any('daemon' in b.label.lower() for b in app.button)
    assert any(b.label == 'Update Paper Positions' for b in app.button)
    assert not provider.calls and not service.ledger.recent_runs()
