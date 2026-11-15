"""Optional offscreen Qt smoke for the native image tools UI."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from spm_studio.ui.interactive_tool_palette import InteractiveToolPalette
from spm_studio.core.interactive_tools import TOOL_BY_ID


def test_tools_can_be_selected_and_update_live_widget():
    app=QApplication.instance() or QApplication([])
    panel=InteractiveToolPalette()
    panel.resize(450,650)
    panel.show();app.processEvents()
    assert set(panel.buttons)==set(TOOL_BY_ID)
    changes=[]
    panel.toolSelected.connect(changes.append)
    QTest.mouseClick(panel.buttons['distance'],Qt.MouseButton.LeftButton)
    assert changes[-1]=='distance'
    assert panel.current=='distance'
    panel.show_results({'lines':['R = 5 nm'],'series':[('Line',[0,1],[3,4])]})
    assert '5 nm' in panel.results.toPlainText()
    assert panel.plot.isVisible()
    QTest.mouseClick(panel.buttons['filter'],Qt.MouseButton.LeftButton)
    panel.show_results({'lines':['Ready']},ready=True)
    assert panel.apply.isVisible() and panel.apply.isEnabled()
    panel.close()
