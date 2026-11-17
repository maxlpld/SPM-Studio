"""Optional GUI regression checks (run when PySide6 is installed on Ubuntu)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
import numpy as np
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from spm_studio.ui.image_view import ImageView
from spm_studio.ui.live_analysis import LivePlot
from spm_studio.core.models import ROI,Geometry,ImageStyle

@pytest.fixture(scope='module')
def app():
    application=QApplication.instance() or QApplication([])
    yield application


def test_existing_line_endpoint_edit_without_moving_second_endpoint(app):
    viewer=ImageView();viewer.resize(680,460)
    raster=np.arange(10000,dtype=float).reshape(100,100)
    img=QImage(100,100,QImage.Format.Format_RGB888)
    img.fill(Qt.GlobalColor.black)
    viewer.set_scan(img,raster,Geometry((100,100),(1e-8,1e-8)),ImageStyle(),(0,9999),'Z','m')
    viewer.extra_rois=[ROI('line',((20.,30.),(70.,80.)))]
    viewer.set_roi_tool('line');viewer.show();app.processEvents()
    start=viewer._to_screen((20,30)).toPoint()
    target=viewer._to_screen((28,34)).toPoint()
    QTest.mousePress(viewer,Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(viewer,target)
    QTest.mouseRelease(viewer,Qt.MouseButton.LeftButton,pos=target)
    result=viewer.extra_rois[0]
    assert result.points_px[1]==(70.,80.)
    assert abs(result.points_px[0][0]-28)<2
    viewer.close()


def test_mask_handle_moves_one_boundary_only(app):
    chart=LivePlot();chart.resize(600,250)
    chart.histogram(np.linspace(0,10,1001),60,
                    [{'name':'A','low':2.,'high':8.,'color':'#ff0000'}],0)
    chart.show();QTest.qWaitForWindowExposed(chart)
    # the chart geometry is final only after the first layout/paint; on a busy Xvfb that can take a moment
    for _ in range(20):
        app.processEvents();QTest.qWait(10)
    emitted=[];chart.rangeEdited.connect(lambda x,y:emitted.append((x,y)))
    start=QPoint(round(chart._x_from_value(2.)),round(chart._chart.center().y()))
    target=QPoint(round(chart._x_from_value(3.)),round(chart._chart.center().y()))
    QTest.mouseMove(chart,start)
    QTest.mousePress(chart,Qt.MouseButton.LeftButton,pos=start)
    for step in range(1,6):                       # several moves, as a real drag sends
        QTest.mouseMove(chart,QPoint(start.x()+(target.x()-start.x())*step//5,start.y()))
    QTest.mouseRelease(chart,Qt.MouseButton.LeftButton,pos=target)
    app.processEvents()
    assert emitted
    assert 2.8<emitted[-1][0]<3.2
    assert emitted[-1][1]==8.
    chart.close()
