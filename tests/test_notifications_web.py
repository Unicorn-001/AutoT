"""Offline UI rendering; does not launch a server."""
from streamlit.testing.v1 import AppTest

from autot import notifications as n
from autot.settings.models import AutoTSettings, Notifications
from autot.settings.store import SettingsStore
from tests.test_paper_web import ui, APP
from tests.test_prospective_paper import confirm, bar, OPEN, BAR


def test_notifications_panel(ui):
    service, provider, clock = ui
    confirm(service)
    provider.bars = [bar()]
    clock[0] = OPEN+BAR
    service.update_positions()
    n.project(service.ledger)
    before = service.ledger.all()
    app = AppTest.from_file(APP).run()
    app.radio[0].set_value('Paper Trading').run()
    assert not app.exception
    assert any('Disabled' in c.value and 'CONSOLE' in c.value for c in app.caption)
    assert any('Pending notifications: 1' in m.value for m in app.markdown)
    assert any('PAPER_ENTRY_OPENED' in str(t.value) for t in app.table)
    SettingsStore().save(AutoTSettings(notifications=Notifications(notifications_enabled=True)), expected_version=0)
    app.run()
    assert any('Enabled' in c.value and 'CONSOLE' in c.value for c in app.caption)
    assert n.read_status(service.ledger.path)['pending'] == 1
    assert service.ledger.all() == before
