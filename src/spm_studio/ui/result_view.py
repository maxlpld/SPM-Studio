"""Fit-to-channel native preview for lossless raster overlays and PDF reports."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap, QImage, QPainter, QBrush, QColor
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QSizePolicy, QStackedWidget, QGraphicsView, QGraphicsScene, QFrame)
try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:
    QPdfDocument=QPdfView=None

class _FitRaster(QGraphicsView):
    """Retain original image pixels and fit them; no intermediate thumbnail."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.scene_obj=QGraphicsScene(self)
        self.setScene(self.scene_obj)
        self.pixmap_item=None
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            from spm_studio.shared.appearance import colors
            self.setBackgroundBrush(QBrush(QColor(colors()['input'])))
        except Exception:
            self.setBackgroundBrush(QBrush(QColor('#111111')))
    def set_image(self,image):
        if isinstance(image,QImage):pm=QPixmap.fromImage(image)
        else:pm=QPixmap(str(image))
        if pm.isNull():raise ValueError('Unable to open analysis preview image')
        self.scene_obj.clear()
        self.pixmap_item=self.scene_obj.addPixmap(pm)
        self.scene_obj.setSceneRect(self.pixmap_item.boundingRect())
        self.fit_image()
    def fit_image(self):
        if self.pixmap_item is not None:
            self.fitInView(self.pixmap_item,Qt.AspectRatioMode.KeepAspectRatio)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.fit_image()

def _render_svg(path, long_side=2400):
    """Rasterize an SVG result for display only (the file itself is untouched)."""
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError as exc:
        raise ValueError('Qt SVG module unavailable') from exc
    renderer=QSvgRenderer(str(path))
    if not renderer.isValid():raise ValueError('unreadable SVG')
    box=renderer.viewBoxF()
    w,h=(box.width(),box.height()) if box.width()>0 and box.height()>0 else (1000.,1000.)
    scale=long_side/max(w,h)
    image=QImage(max(1,int(w*scale)),max(1,int(h*scale)),QImage.Format.Format_ARGB32)
    image.fill(QColor('#ffffff'))
    painter=QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True)
    renderer.render(painter)
    painter.end()
    return image


class ResultPreview(QWidget):
    """Displayed at the same size and in the same horizontal strip as scan channels."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumWidth(460)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.files=[]
        self.index=0
        self.live=False
        layout=QVBoxLayout(self)
        layout.setContentsMargins(1,1,1,1)
        controls=QHBoxLayout()
        self.caption=QLabel('Analysis results')
        self.caption.setObjectName('heading')
        controls.addWidget(self.caption,1)
        self.previous=QPushButton('‹')
        self.previous.setProperty('flat',True)
        self.previous.clicked.connect(lambda:self.step(-1))
        self.position=QLabel('0 / 0')
        self.next=QPushButton('›')
        self.next.setProperty('flat',True)
        self.next.clicked.connect(lambda:self.step(1))
        for w in (self.previous,self.position,self.next):controls.addWidget(w)
        layout.addLayout(controls)
        self.path_label=QLabel('')
        self.path_label.setObjectName('hint')
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)
        self.stack=QStackedWidget()
        self.raster=_FitRaster(self.stack)
        self.stack.addWidget(self.raster)
        self.document=None
        self.pdf=None
        if QPdfView is not None:
            self.document=QPdfDocument(self)
            self.pdf=QPdfView(self.stack)
            self.pdf.setDocument(self.document)
            self.pdf.setPageMode(QPdfView.PageMode.SinglePage)
            self.pdf.setZoomMode(QPdfView.ZoomMode.FitInView)
            self.stack.addWidget(self.pdf)
        layout.addWidget(self.stack,1)
        self.open=QPushButton('Open externally')
        self.open.clicked.connect(self.open_current)
        layout.addWidget(self.open)
        self.setObjectName('resultPreview')
        self._update()

    def set_reports(self,files,title='Analysis results',preferred=None):
        self.live=False
        self.caption.setText(title)
        seen=set()
        self.files=[]
        for f in files:
            p=Path(f)
            if p.is_file() and p.suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.pdf','.svg') and str(p) not in seen:
                seen.add(str(p));self.files.append(str(p))
        self.index=next((i for i,f in enumerate(self.files) if preferred and Path(f).name==Path(preferred).name),0)
        self._update()

    def set_live_image(self,image,description='Molecule placement · live preview'):
        self.live=True
        self.caption.setText('Molecule placement  •  LIVE')
        self.path_label.setText(description)
        self.raster.set_image(image)
        self.stack.setCurrentWidget(self.raster)
        self.previous.hide();self.next.hide();self.position.hide();self.open.hide()

    def set_live_message(self,message):
        self.live=True
        self.caption.setText('Molecule placement  •  LIVE')
        self.path_label.setText(message)
        self.raster.scene_obj.clear()
        self.raster.pixmap_item=None
        self.stack.setCurrentWidget(self.raster)
        self.previous.hide();self.next.hide();self.position.hide();self.open.hide()

    def step(self,direction):
        if self.live or not self.files:return
        self.index=(self.index+direction)%len(self.files)
        self._update()

    def _update(self):
        if self.live:return
        length=len(self.files)
        for w in (self.previous,self.next,self.position,self.open):w.show()
        self.previous.setEnabled(length>1)
        self.next.setEnabled(length>1)
        self.open.setEnabled(length>0)
        self.position.setText(f'{self.index+1} / {length}' if length else '0 / 0')
        self.path_label.setText(Path(self.files[self.index]).name if length else 'No report for this scan and tool.')
        if not length:return
        file=Path(self.files[self.index])
        if file.suffix.lower()=='.pdf' and self.pdf is not None:
            self.document.close()
            self.document.load(str(file))
            self.pdf.setZoomMode(QPdfView.ZoomMode.FitInView)
            self.stack.setCurrentWidget(self.pdf)
        elif file.suffix.lower()=='.svg':
            try:
                self.raster.set_image(_render_svg(file))
                self.stack.setCurrentWidget(self.raster)
            except ValueError as exc:
                self.path_label.setText(f'{file.name}: {exc}')
        elif file.suffix.lower()!='.pdf':
            self.raster.set_image(file)
            self.stack.setCurrentWidget(self.raster)
        else:
            self.path_label.setText('Qt PDF viewer unavailable. Click Open result externally.')

    def open_current(self):
        if self.files and not self.live:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.files[self.index]))
