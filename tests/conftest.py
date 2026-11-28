import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

# Keep Qt's C++ application alive throughout Linux, Windows and macOS GUI test sessions.
# GUI tests can otherwise release the last QApplication reference before
# Python has finished disposing of Qt widgets and their deferred events.
import gc
import os
import pytest

@pytest.fixture(scope="session", autouse=True)
def _qt_session_lifetime():
    if sys.platform not in ("linux", "win32", "darwin") or not (
        os.environ.get("DISPLAY") or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    ):
        yield
        return
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        yield
        return
    app = QApplication.instance() or QApplication([])
    yield
    for widget in list(app.topLevelWidgets()):
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def _isolated_agent_hub(tmp_path_factory, monkeypatch):
    """v0.1.0: every test has its own Agent Hub folder (chats, calendar, to-do, mail, settings), so no test can
    read or write a real user's data, and the shared organizer / host never leak from one test to the next."""
    folder = tmp_path_factory.mktemp('agent-hub')
    monkeypatch.setenv('AGENT_HUB_DATA', str(folder))
    yield
    try:
        from agent_hub import host, organizer
        organizer.reset()
        host.set_host(host.Host())
        from agent_hub.ui.organizer import common, windows
        windows.close_all()
        common._bridge = None
    except Exception:
        pass
