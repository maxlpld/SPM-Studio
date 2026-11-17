"""Full-screen slide show: arrows / space / click to advance, Esc to leave, B for a black screen."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import QGraphicsView, QWidget, QVBoxLayout, QGraphicsPixmapItem, QLabel

from .slide_items import Context, SlideScene, VideoItem


class SlideShow(QWidget):
    def __init__(self, deck: dict, project_dir, start: int = 0, renderer=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(deck.get('title', 'Presentation') + ' — slide show')
        self.deck = deck
        self.order = [i for i, s in enumerate(deck['slides']) if not s.get('hidden')] or [0]
        self.position = max(0, min(len(self.order) - 1, next((n for n, i in enumerate(self.order) if i >= start), 0)))
        self.ctx = Context(deck, project_dir, editable=False, live=True, renderer=renderer)
        self.scene = SlideScene(self.ctx, self)
        self.view = QGraphicsView(self.scene)
        self.view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.view.setBackgroundBrush(QColor('#000000'))
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform |
                                 QPainter.RenderHint.TextAntialiasing)
        self.view.viewport().installEventFilter(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.counter = QLabel(self)
        self.counter.setStyleSheet('color: rgba(255,255,255,140); background: transparent; font-size: 12px;')
        self.black = False
        self._overlay = None
        self._animation = None
        for keys, slot in ((('Right', 'Down', 'Space', 'PgDown', 'Return', 'N'), self.next),
                           (('Left', 'Up', 'PgUp', 'Backspace', 'P'), self.previous),
                           (('Escape',), self.close), (('Home',), lambda: self.go(0)),
                           (('End',), lambda: self.go(len(self.order) - 1)), (('B', '.'), self.toggle_black)):
            for key in keys:
                QShortcut(QKeySequence(key), self, activated=slot)
        self.setStyleSheet('background: #000000;')
        self._show(animate=False)

    def start(self):
        self.showFullScreen()
        self.activateWindow()
        self.setFocus()

    def _fit(self):
        w, h = self.ctx.size()
        self.view.fitInView(QRectF(0, 0, w, h), Qt.AspectRatioMode.KeepAspectRatio)
        self.counter.move(self.width() - 80, self.height() - 26)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _show(self, animate=True):
        index = self.order[self.position]
        slide = self.deck['slides'][index]
        old = None
        if animate and slide.get('transition') in ('fade', 'push') and self.view.viewport().width() > 10:
            old = self.view.grab()
        graphics = self.scene.build(slide, index + 1, len(self.deck['slides']))
        for item in graphics.values():
            if isinstance(item, VideoItem) and item.data.get('autoplay'):
                item.toggle()
        self._fit()
        self.counter.setText(f'{self.position + 1} / {len(self.order)}')
        self.counter.adjustSize()
        if old is not None:
            self._transition(old, slide.get('transition'))

    def _transition(self, pixmap: QPixmap, kind: str):
        overlay = QLabel(self.view)
        overlay.setPixmap(pixmap)
        overlay.setGeometry(0, 0, self.view.width(), self.view.height())
        overlay.show()
        self._overlay = overlay
        animation = QVariantAnimation(self)
        animation.setDuration(380)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)

        def step(value):
            if kind == 'push':
                overlay.move(int(-self.view.width() * value), 0)
            else:
                effect.setOpacity(1.0 - value)
        animation.valueChanged.connect(step)
        animation.finished.connect(overlay.deleteLater)
        self._animation = animation
        animation.start()

    def go(self, position):
        position = max(0, min(len(self.order) - 1, position))
        if position != self.position:
            self.position = position
            self._show()

    def next(self):
        if self.black:
            self.toggle_black()
            return
        if self.position >= len(self.order) - 1:
            self.close()
            return
        self.go(self.position + 1)

    def previous(self):
        self.go(self.position - 1)

    def toggle_black(self):
        self.black = not self.black
        self.view.setVisible(not self.black)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.view.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            item = self.view.itemAt(event.position().toPoint())
            while item is not None and not isinstance(item, VideoItem):
                item = item.parentItem()
            if isinstance(item, VideoItem):
                item.toggle()
            elif event.button() == Qt.MouseButton.RightButton:
                self.previous()
            else:
                self.next()
            return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        for item in self.scene.graphics.values():
            if hasattr(item, 'stop'):
                item.stop()
        super().closeEvent(event)
