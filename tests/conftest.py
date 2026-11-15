import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

# Keep Qt's C++ application alive throughout a Linux GUI test session.
# GUI tests can otherwise release the last QApplication reference before
# Python has finished disposing of Qt widgets and their deferred events.
import gc
import os
import pytest

@pytest.fixture(scope="session", autouse=True)
def _linux_qt_session_lifetime():
    if sys.platform != "linux" or not (
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
