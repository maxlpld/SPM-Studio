"""Graphics items of a slide (text, LaTeX, image, GIF, video, shape), its page, and off-screen rendering.

Every item edits its dict of the presentation model in place (``self.data``) and emits
``changed`` when the user finished a move, a resize or an edit, so that the window can record
an undo step, refresh the thumbnail and autosave.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QSizeF, QTimer
from PySide6.QtGui import (QColor, QPainter, QPen, QBrush, QPixmap, QImage, QPainterPath, QFont, QTextDocument,
                           QMovie, QPolygonF, QTextOption, QCursor)
from PySide6.QtWidgets import QGraphicsObject, QGraphicsItem, QGraphicsTextItem, QGraphicsScene, QStyle

HANDLE = 7.0
MEDIA_TYPES = ('image', 'gif', 'video', 'latex')


class Context:
    """What items need to know about their presentation."""

    def __init__(self, deck: dict, project_dir: Path, *, editable=True, live=True, renderer=None):
        self.deck = deck
        self.project_dir = Path(project_dir)
        self.editable = editable          # selection, handles, editing
        self.live = live                  # GIFs animate, videos can play
        self.renderer = renderer
        self.snap_lines = []              # guide lines shown while dragging

    @property
    def theme(self):
        return self.deck.get('theme', {})

    def size(self):
        return float(self.deck.get('width', 960)), float(self.deck.get('height', 540))

    def media(self, rel: str) -> Path:
        return self.project_dir / rel


def _qcolor(value, fallback=None):
    if not value:
        return QColor(fallback) if fallback else None
    c = QColor(value)
    return c if c.isValid() else (QColor(fallback) if fallback else None)


def fit_rect(content: QSizeF, box: QRectF, mode: str) -> QRectF:
    if content.width() <= 0 or content.height() <= 0 or mode == 'stretch':
        return QRectF(box)
    sx, sy = box.width() / content.width(), box.height() / content.height()
    s = max(sx, sy) if mode == 'cover' else min(sx, sy)
    w, h = content.width() * s, content.height() * s
    return QRectF(box.x() + (box.width() - w) / 2, box.y() + (box.height() - h) / 2, w, h)


# ============================================================================= base
class SlideItem(QGraphicsObject):
    changed = Signal()
    editRequested = Signal()

    def __init__(self, data: dict, ctx: Context):
        super().__init__()
        self.data = data
        self.ctx = ctx
        self._drag = None
        self._moving = False          # dragged by the mouse: snap to guides
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, ctx.editable and not data.get('locked'))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, ctx.editable and not data.get('locked'))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, ctx.editable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, ctx.editable)
        self.setAcceptHoverEvents(ctx.editable)
        self.setup()
        self.sync_from_data()

    def setup(self):
        """Create the sub-class's own attributes (called once, before the first content load)."""

    # geometry ------------------------------------------------------------
    def w(self):
        return float(self.data.get('w', 100))

    def h(self):
        return float(self.data.get('h', 50))

    def box(self) -> QRectF:
        return QRectF(0, 0, self.w(), self.h())

    def boundingRect(self) -> QRectF:
        m = HANDLE + 2 if self.ctx.editable else 1
        return self.box().adjusted(-m, -m, m, m)

    def shape(self):
        path = QPainterPath()
        path.addRect(self.box().adjusted(-HANDLE / 2, -HANDLE / 2, HANDLE / 2, HANDLE / 2) if self.isSelected()
                     else self.box())
        return path

    def sync_from_data(self):
        self.prepareGeometryChange()
        self.setPos(float(self.data.get('x', 0)), float(self.data.get('y', 0)))
        self.setTransformOriginPoint(self.w() / 2, self.h() / 2)
        self.setRotation(float(self.data.get('rotation', 0) or 0))
        self.setOpacity(float(self.data.get('opacity', 1) if self.data.get('opacity') is not None else 1))
        self.content_changed()
        self.update()

    def content_changed(self):
        """Re-read content (text, image…) after ``data`` changed."""

    # painting ------------------------------------------------------------
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.paint_content(painter, self.box())
        if self.ctx.editable and (self.isSelected() or option.state & QStyle.StateFlag.State_MouseOver):
            accent = QColor('#2F8CFF')
            pen = QPen(accent, 0 if self.isSelected() else 0)
            pen.setCosmetic(True)
            pen.setWidthF(1.4 if self.isSelected() else 1.0)
            if not self.isSelected():
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.box())
            if self.isSelected():
                painter.setBrush(QColor('#FFFFFF'))
                for rect in self._handle_rects().values():
                    painter.drawRect(rect)

    def paint_content(self, painter, box):
        pass

    def _handle_rects(self):
        w, h = self.w(), self.h()
        s = HANDLE
        points = {'tl': (0, 0), 't': (w / 2, 0), 'tr': (w, 0), 'r': (w, h / 2), 'br': (w, h), 'b': (w / 2, h),
                  'bl': (0, h), 'l': (0, h / 2)}
        if w < 30:
            for k in ('t', 'b'):
                points.pop(k)
        if h < 30:
            for k in ('l', 'r'):
                points.pop(k)
        return {k: QRectF(x - s / 2, y - s / 2, s, s) for k, (x, y) in points.items()}

    def _handle_at(self, pos):
        if not self.isSelected():
            return None
        for key, rect in self._handle_rects().items():
            if rect.adjusted(-3, -3, 3, 3).contains(pos):
                return key
        return None

    # interaction ---------------------------------------------------------
    def hoverMoveEvent(self, event):
        handle = self._handle_at(event.pos())
        cursors = {'tl': Qt.CursorShape.SizeFDiagCursor, 'br': Qt.CursorShape.SizeFDiagCursor,
                   'tr': Qt.CursorShape.SizeBDiagCursor, 'bl': Qt.CursorShape.SizeBDiagCursor,
                   't': Qt.CursorShape.SizeVerCursor, 'b': Qt.CursorShape.SizeVerCursor,
                   'l': Qt.CursorShape.SizeHorCursor, 'r': Qt.CursorShape.SizeHorCursor}
        self.setCursor(cursors.get(handle, Qt.CursorShape.SizeAllCursor if self.isSelected()
                                   else Qt.CursorShape.ArrowCursor))
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        handle = self._handle_at(event.pos()) if event.button() == Qt.MouseButton.LeftButton else None
        if handle:
            self._drag = (handle, event.scenePos(), float(self.data['x']), float(self.data['y']), self.w(), self.h())
            event.accept()
            return
        self._drag = None
        self._moving = event.button() == Qt.MouseButton.LeftButton
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag:
            handle, start, x0, y0, w0, h0 = self._drag
            d = event.scenePos() - start
            x, y, w, h = x0, y0, w0, h0
            if 'l' in handle:
                x, w = x0 + d.x(), w0 - d.x()
            if 'r' in handle:
                w = w0 + d.x()
            if handle.startswith('t'):
                y, h = y0 + d.y(), h0 - d.y()
            if handle.startswith('b'):
                h = h0 + d.y()
            keep = (self.data['type'] in MEDIA_TYPES and len(handle) == 2) != bool(
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if keep and w0 > 0 and h0 > 0:
                ratio = w0 / h0
                if abs(w / w0) > abs(h / h0):
                    h = w / ratio
                else:
                    w = h * ratio
                if 'l' in handle:
                    x = x0 + w0 - w
                if handle.startswith('t'):
                    y = y0 + h0 - h
            w, h = max(8.0, w), max(4.0, h)
            self.prepareGeometryChange()
            self.data.update({'x': x, 'y': y, 'w': w, 'h': h})
            self.setPos(x, y)
            self.setTransformOriginPoint(w / 2, h / 2)
            self.geometry_changed()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        was_resizing = self._drag is not None
        self._drag = None
        self._moving = False
        super().mouseReleaseEvent(event)
        moved = abs(self.pos().x() - float(self.data['x'])) > 0.01 or abs(self.pos().y() - float(self.data['y'])) > 0.01
        if moved:
            self.data['x'] = round(self.pos().x(), 2)
            self.data['y'] = round(self.pos().y(), 2)
        if self.ctx.snap_lines:
            self.ctx.snap_lines = []
            if self.scene() is not None:
                self.scene().update()
        if was_resizing or moved:
            self.changed.emit()

    def geometry_changed(self):
        """Called while resizing (text boxes re-wrap, LaTeX boxes re-render)."""

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.ctx.editable \
                and self._moving and self.scene() is not None and not self._drag \
                and len(self.scene().selectedItems()) <= 1:
            return self._snap(value)
        return super().itemChange(change, value)

    def _snap(self, pos: QPointF) -> QPointF:
        from PySide6.QtWidgets import QApplication
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
            self.ctx.snap_lines = []
            return pos
        sw, sh = self.ctx.size()
        w, h = self.w(), self.h()
        tolerance = 6.0
        xs = [0.0, sw / 2, sw, 48.0, sw - 48.0]
        ys = [0.0, sh / 2, sh, 48.0, sh - 48.0]
        for other in self.scene().items():
            if isinstance(other, SlideItem) and other is not self and not other.isSelected():
                ox, oy, ow, oh = other.data['x'], other.data['y'], other.w(), other.h()
                xs += [ox, ox + ow / 2, ox + ow]
                ys += [oy, oy + oh / 2, oy + oh]
        lines = []
        x, y = pos.x(), pos.y()
        best = None
        for edge, offset in ((x, 0.0), (x + w / 2, w / 2), (x + w, w)):
            for target in xs:
                if abs(edge - target) < tolerance and (best is None or abs(edge - target) < best[0]):
                    best = (abs(edge - target), target - offset, target)
        if best:
            x = best[1]
            lines.append(('v', best[2]))
        best = None
        for edge, offset in ((y, 0.0), (y + h / 2, h / 2), (y + h, h)):
            for target in ys:
                if abs(edge - target) < tolerance and (best is None or abs(edge - target) < best[0]):
                    best = (abs(edge - target), target - offset, target)
        if best:
            y = best[1]
            lines.append(('h', best[2]))
        self.ctx.snap_lines = lines
        self.scene().update()
        return QPointF(x, y)


# ============================================================================= text
class _TextEdit(QGraphicsTextItem):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        from PySide6.QtWidgets import QApplication
        if event.reason() in (Qt.FocusReason.PopupFocusReason, Qt.FocusReason.ActiveWindowFocusReason):
            return                       # a menu or the colour dialog: keep typing afterwards
        focus = QApplication.focusWidget()
        if focus is not None and focus.objectName() in ('SlidesFontBoxV008', 'SlidesSizeBoxV008'):
            return                       # formatting the selected words from the toolbar
        self.owner.finish_edit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clearFocus()
            return
        super().keyPressEvent(event)


class TextItem(SlideItem):
    def setup(self):
        self.editor = None

    def _ensure_editor(self):
        if self.editor is None:
            self.editor = _TextEdit(self)
            self.editor.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.editor.document().contentsChanged.connect(self._grow)
        return self.editor

    def content_changed(self):
        editor = self._ensure_editor()
        theme = self.ctx.theme
        font = QFont(theme.get('body_font') or 'Inter')
        font.setPointSizeF(float(theme.get('body_size', 20)))
        editor.document().setDefaultFont(font)
        editor.setDefaultTextColor(_qcolor(theme.get('text_color'), '#1A1D22'))
        editor.document().setDocumentMargin(0)
        if not self.editing() and editor.toHtml() != self.data.get('html', ''):
            editor.setHtml(self.data.get('html', '') or '')
        self.geometry_changed()

    def geometry_changed(self):
        if self.editor is None:
            return
        pad = float(self.data.get('padding', 6) or 0)
        self.editor.setTextWidth(max(4.0, self.w() - 2 * pad))
        eh = self.editor.boundingRect().height()
        valign = self.data.get('valign', 'top')
        y = pad if valign == 'top' else (self.h() - eh) / 2 if valign == 'middle' else self.h() - eh - pad
        self.editor.setPos(pad, max(0.0, y) if valign != 'top' else pad)

    def _grow(self):
        if self.editor is None:
            return
        pad = float(self.data.get('padding', 6) or 0)
        needed = self.editor.boundingRect().height() + 2 * pad
        if needed > self.h() + 0.5 and self.ctx.editable:
            self.prepareGeometryChange()
            self.data['h'] = round(needed, 1)
            self.setTransformOriginPoint(self.w() / 2, self.h() / 2)
        self.geometry_changed()
        self.update()

    def paint_content(self, painter, box):
        fill = _qcolor(self.data.get('fill_color'))
        line = _qcolor(self.data.get('line_color'))
        if fill is not None or (line is not None and float(self.data.get('line_width', 0) or 0) > 0):
            painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(line, float(self.data.get('line_width', 1))) if line is not None and
                           float(self.data.get('line_width', 0) or 0) > 0 else Qt.PenStyle.NoPen)
            painter.drawRoundedRect(box, 4, 4)
        if self.ctx.editable and not self.editor.document().toPlainText().strip() and not self.editing():
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(box.adjusted(8, 6, -8, -6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                             'Click twice to add text')

    def editing(self) -> bool:
        return self.editor is not None and bool(self.editor.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction)

    def start_edit(self, at_scene: QPointF | None = None, select_all=False):
        if not self.ctx.editable:
            return
        editor = self._ensure_editor()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        editor.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
        editor.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        cursor = editor.textCursor()
        if select_all:
            cursor.select(cursor.SelectionType.Document)
        elif at_scene is not None:
            local = editor.mapFromScene(at_scene)
            position = editor.document().documentLayout().hitTest(local, Qt.HitTestAccuracy.FuzzyHit)
            if position >= 0:
                cursor.setPosition(position)
        editor.setTextCursor(cursor)
        self.update()

    def finish_edit(self):
        if self.editor is None or not self.editing():
            return
        self.editor.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.editor.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        cursor = self.editor.textCursor()
        cursor.clearSelection()
        self.editor.setTextCursor(cursor)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, self.ctx.editable and not self.data.get('locked'))
        html = self.editor.toHtml()
        if html != self.data.get('html'):
            self.data['html'] = html
            self.changed.emit()
        self.update()

    def mouseDoubleClickEvent(self, event):
        if self.ctx.editable:
            self.start_edit(event.scenePos())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def commit_html(self):
        """After formatting applied from the toolbar."""
        html = self.editor.toHtml()
        if html != self.data.get('html'):
            self.data['html'] = html
            self.changed.emit()


# ============================================================================ LaTeX
class LatexItem(SlideItem):
    def setup(self):
        self.key = None
        self._resize_timer = None
        if self.ctx.renderer is not None:
            self.ctx.renderer.rendered.connect(self._rendered)

    def _scale(self):
        return max(0.1, float(self.data.get('size', 24) or 24)) / 10.0

    def content_changed(self):
        if self.ctx.renderer is None:
            return
        width = self.w() / self._scale()
        self.key = self.ctx.renderer.request(self.data.get('source', ''), self.data.get('color', '#000000'),
                                             width, self.data.get('align', 'center'),
                                             self.ctx.deck.get('formula_preamble', ''))
        self._fit()

    def geometry_changed(self):
        if self._resize_timer is None:
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.setInterval(250)
            self._resize_timer.timeout.connect(self.content_changed)
        self._resize_timer.start()

    def _rendered(self, key):
        if key == self.key:
            self._fit()
            self.update()

    def _fit(self):
        result = self.ctx.renderer.get(self.key) if self.ctx.renderer and self.key else None
        if result is None:
            return
        _image, _w, h = result
        needed = h * self._scale() + 2
        if needed > self.h() + 0.5 and self.ctx.editable:
            self.prepareGeometryChange()
            self.data['h'] = round(needed, 1)
            self.setTransformOriginPoint(self.w() / 2, self.h() / 2)

    def paint_content(self, painter, box):
        fill = _qcolor(self.data.get('fill_color'))
        if fill is not None:
            painter.fillRect(box, fill)
        result = self.ctx.renderer.get(self.key) if self.ctx.renderer and self.key else None
        if result is not None:
            image, w, h = result
            s = self._scale()
            tw, th = w * s, h * s
            if tw > box.width():
                f = box.width() / tw
                tw, th = tw * f, th * f
            align = self.data.get('align', 'center')
            x = box.x() if align == 'left' else box.right() - tw if align == 'right' else box.x() + (box.width() - tw) / 2
            y = box.y() + max(0.0, (box.height() - th) / 2)
            painter.drawImage(QRectF(x, y, tw, th), image)
            return
        error = self.ctx.renderer.error(self.key) if self.ctx.renderer and self.key else None
        painter.setPen(QColor('#C23A33') if error else QColor(140, 140, 140))
        font = painter.font()
        font.setPointSizeF(10)
        painter.setFont(font)
        text = ('LaTeX: ' + error) if error else ('Rendering…  ' + self.data.get('source', '')[:120])
        painter.drawText(box.adjusted(4, 2, -4, -2), int(Qt.AlignmentFlag.AlignCenter.value) | int(Qt.TextFlag.TextWordWrap.value), text)
        if self.ctx.editable:
            pen = QPen(QColor(150, 150, 150), 1, Qt.PenStyle.DotLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawRect(box)

    def mouseDoubleClickEvent(self, event):
        self.editRequested.emit()
        event.accept()


# ============================================================================ images
class ImageItem(SlideItem):
    def setup(self):
        self.pixmap = None
        self.svg = None

    def content_changed(self):
        path = self.ctx.media(self.data.get('src', ''))
        self.pixmap = self.svg = None
        if path.suffix.lower() == '.svg':
            try:
                from PySide6.QtSvg import QSvgRenderer
                renderer = QSvgRenderer(str(path))
                self.svg = renderer if renderer.isValid() else None
            except ImportError:
                self.svg = None
        elif path.is_file():
            pm = QPixmap(str(path))
            self.pixmap = None if pm.isNull() else pm

    def natural_size(self) -> QSizeF:
        if self.svg is not None:
            box = self.svg.viewBoxF()
            return QSizeF(box.width(), box.height()) if box.width() > 0 else QSizeF(self.svg.defaultSize())
        if self.pixmap is not None:
            return QSizeF(self.pixmap.size())
        return QSizeF(0, 0)

    def paint_content(self, painter, box):
        target = fit_rect(self.natural_size(), box, self.data.get('fit', 'contain'))
        painter.save()
        radius = float(self.data.get('radius', 0) or 0)
        if radius > 0 or self.data.get('fit') == 'cover':
            clip = QPainterPath()
            clip.addRoundedRect(box, radius, radius)
            painter.setClipPath(clip)
        if self.svg is not None:
            self.svg.render(painter, target)
        elif self.pixmap is not None:
            painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
        else:
            self._missing(painter, box)
        painter.restore()
        line = _qcolor(self.data.get('line_color'))
        if line is not None and float(self.data.get('line_width', 0) or 0) > 0:
            painter.setPen(QPen(line, float(self.data['line_width'])))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box, radius, radius)

    def _missing(self, painter, box):
        painter.fillRect(box, QColor(230, 232, 235))
        painter.setPen(QColor(120, 120, 120))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, 'Missing: ' + Path(self.data.get('src', '')).name)


class GifItem(ImageItem):
    def setup(self):
        super().setup()
        self.movie = None

    def content_changed(self):
        path = self.ctx.media(self.data.get('src', ''))
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
        self.movie = QMovie(str(path)) if path.is_file() else None
        self.pixmap = self.svg = None
        if self.movie is not None and self.movie.isValid():
            self.movie.setCacheMode(QMovie.CacheMode.CacheAll)
            self.movie.frameChanged.connect(lambda _n: self.update())
            if self.ctx.live:
                self.movie.start()
            else:
                self.movie.jumpToFrame(0)

    def natural_size(self) -> QSizeF:
        if self.movie is not None and self.movie.isValid():
            pm = self.movie.currentPixmap()
            if not pm.isNull():
                return QSizeF(pm.size())
            return QSizeF(self.movie.frameRect().size())
        return QSizeF(0, 0)

    def paint_content(self, painter, box):
        if self.movie is None or not self.movie.isValid():
            self._missing(painter, box)
            return
        pm = self.movie.currentPixmap()
        if pm.isNull():
            self.movie.jumpToFrame(0)
            pm = self.movie.currentPixmap()
        target = fit_rect(QSizeF(pm.size()), box, self.data.get('fit', 'contain'))
        painter.drawPixmap(target, pm, QRectF(pm.rect()))

    def stop(self):
        if self.movie is not None:
            self.movie.stop()


class VideoItem(SlideItem):
    def setup(self):
        self.player = None
        self.video = None
        self.audio = None

    def content_changed(self):
        if self.player is not None:
            self.player.stop()

    def _ensure_player(self):
        if self.player is not None or not self.ctx.live:
            return self.player
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
        except ImportError:
            return None
        from PySide6.QtCore import QUrl
        self.video = QGraphicsVideoItem(self)
        self.video.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio if self.data.get('fit') != 'stretch'
                                      else Qt.AspectRatioMode.IgnoreAspectRatio)
        self.audio = QAudioOutput()
        self.audio.setMuted(bool(self.data.get('muted')))
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.setSource(QUrl.fromLocalFile(str(self.ctx.media(self.data.get('src', '')))))
        self.player.setLoops(-1 if self.data.get('loop') else 1)
        self.player.playbackStateChanged.connect(lambda _s: self.update())
        self.geometry_changed()
        return self.player

    def geometry_changed(self):
        if self.video is not None:
            self.video.setSize(QSizeF(self.w(), self.h()))

    def playing(self) -> bool:
        if self.player is None:
            return False
        from PySide6.QtMultimedia import QMediaPlayer
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def toggle(self):
        player = self._ensure_player()
        if player is None:
            return
        if self.playing():
            player.pause()
        else:
            player.play()
        self.update()

    def stop(self):
        if self.player is not None:
            self.player.stop()

    def paint_content(self, painter, box):
        if self.playing() or (self.player is not None and self.player.position() > 0):
            painter.fillRect(box, QColor(0, 0, 0))
            return
        painter.fillRect(box, QColor(18, 20, 23))
        r = min(box.width(), box.height()) * 0.18
        c = box.center()
        painter.setBrush(QColor(255, 255, 255, 220))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(c, r, r)
        triangle = QPolygonF([QPointF(c.x() - r * 0.35, c.y() - r * 0.5), QPointF(c.x() - r * 0.35, c.y() + r * 0.5),
                              QPointF(c.x() + r * 0.55, c.y())])
        painter.setBrush(QColor(18, 20, 23))
        painter.drawPolygon(triangle)
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(box.adjusted(8, 0, -8, -6), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                         '▶ ' + Path(self.data.get('src', '')).name + ('   (double-click to play)' if self.ctx.editable else ''))

    def mouseDoubleClickEvent(self, event):
        self.toggle()
        event.accept()

    def mousePressEvent(self, event):
        if not self.ctx.editable:
            self.toggle()
            event.accept()
            return
        super().mousePressEvent(event)


# ============================================================================ shapes
class ShapeItem(SlideItem):
    def path(self, box) -> QPainterPath:
        kind = self.data.get('shape', 'rect')
        path = QPainterPath()
        if kind == 'ellipse':
            path.addEllipse(box)
        elif kind == 'rounded':
            r = min(float(self.data.get('radius', 12) or 12), box.width() / 2, box.height() / 2)
            path.addRoundedRect(box, r, r)
        elif kind == 'triangle':
            path.addPolygon(QPolygonF([QPointF(box.center().x(), box.top()), box.bottomRight(), box.bottomLeft()]))
            path.closeSubpath()
        elif kind in ('line', 'arrow'):
            path.moveTo(box.left(), box.center().y())
            path.lineTo(box.right(), box.center().y())
        else:
            r = float(self.data.get('radius', 0) or 0) if kind == 'rect' else 0
            if r > 0 and self.data.get('placeholder'):
                path.addRoundedRect(box, r, r)
            else:
                path.addRect(box)
        return path

    def paint_content(self, painter, box):
        kind = self.data.get('shape', 'rect')
        fill = _qcolor(self.data.get('fill_color'))
        line = _qcolor(self.data.get('line_color'))
        width = float(self.data.get('line_width', 0) or 0)
        if kind in ('line', 'arrow'):
            color = line or fill or QColor('#1A1D22')
            pen = QPen(color, max(1.5, width or 3.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            y = box.center().y()
            end = box.right() - (max(1.5, width or 3.0) * 3 if kind == 'arrow' else 0)
            painter.drawLine(QPointF(box.left(), y), QPointF(end, y))
            if kind == 'arrow':
                a = max(8.0, (width or 3.0) * 4)
                painter.setBrush(color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPolygon(QPolygonF([QPointF(box.right(), y), QPointF(box.right() - a, y - a * 0.55),
                                               QPointF(box.right() - a, y + a * 0.55)]))
        else:
            painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(line, width) if line is not None and width > 0 else Qt.PenStyle.NoPen)
            painter.drawPath(self.path(box))
        html = self.data.get('html')
        if html:
            doc = QTextDocument()
            doc.setDocumentMargin(4)
            doc.setHtml(html)
            doc.setTextWidth(box.width())
            painter.save()
            painter.translate(box.x(), box.y() + max(0.0, (box.height() - doc.size().height()) / 2))
            doc.drawContents(painter)
            painter.restore()


ITEM_CLASSES = {'text': TextItem, 'latex': LatexItem, 'image': ImageItem, 'gif': GifItem, 'video': VideoItem,
                'shape': ShapeItem}


def make_graphics_item(data, ctx) -> SlideItem:
    return ITEM_CLASSES.get(data.get('type'), ShapeItem)(data, ctx)


# ============================================================================== page
class PageItem(QGraphicsItem):
    """Slide background, title bar, footer and slide number (from the theme)."""

    def __init__(self, ctx: Context, slide: dict, number: int, total: int):
        super().__init__()
        self.ctx = ctx
        self.slide = slide
        self.number = number
        self.total = total
        self.setZValue(-1000)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._image = None
        image = slide.get('background_image') or ctx.theme.get('background_image')
        if image:
            pm = QPixmap(str(ctx.media(image)))
            self._image = None if pm.isNull() else pm

    def boundingRect(self):
        w, h = self.ctx.size()
        return QRectF(0, 0, w, h)

    def paint(self, painter, option, widget=None):
        t = self.ctx.theme
        rect = self.boundingRect()
        painter.fillRect(rect, _qcolor(self.slide.get('background_color') or t.get('background_color'), '#FFFFFF'))
        if self._image is not None:
            painter.drawPixmap(fit_rect(QSizeF(self._image.size()), rect, 'cover'), self._image,
                               QRectF(self._image.rect()))
        if t.get('title_bar') and self.slide.get('layout') not in ('title', 'section', 'blank'):
            title = next((i for i in self.slide.get('items', []) if i.get('role') == 'title'), None)
            if title is not None:
                bottom = float(title['y']) + float(title['h']) + 10
                painter.fillRect(QRectF(0, 0, rect.width(), bottom), _qcolor(t.get('title_bar_color'), '#0F7C6F'))
        muted = _qcolor(t.get('muted_color'), '#5E6672')
        font = QFont(t.get('body_font') or 'Inter')
        font.setPointSizeF(11)
        painter.setFont(font)
        painter.setPen(muted)
        if t.get('footer') and self.slide.get('layout') != 'title':
            painter.drawText(QRectF(48, rect.height() - 34, rect.width() / 2, 24),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(t['footer']))
        if t.get('slide_numbers', True) and self.number > 1:
            painter.drawText(QRectF(rect.width() - 148, rect.height() - 34, 100, 24),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(self.number))


class SlideScene(QGraphicsScene):
    def __init__(self, ctx: Context, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.page = None
        self.slide = None
        self.graphics = {}

    def build(self, slide: dict, number: int, total: int):
        for item in list(self.graphics.values()):
            if hasattr(item, 'stop'):
                item.stop()
        self.clear()
        self.graphics = {}
        self.slide = slide
        w, h = self.ctx.size()
        self.setSceneRect(QRectF(0, 0, w, h))
        self.page = PageItem(self.ctx, slide, number, total)
        self.addItem(self.page)
        for z, data in enumerate(slide.get('items', [])):
            item = make_graphics_item(data, self.ctx)
            item.setZValue(z)
            self.addItem(item)
            self.graphics[data['id']] = item
        return self.graphics

    def restack(self):
        for z, data in enumerate(self.slide.get('items', [])):
            item = self.graphics.get(data['id'])
            if item is not None:
                item.setZValue(z)

    def drawForeground(self, painter, rect):
        if not self.ctx.snap_lines:
            return
        pen = QPen(QColor('#FF3D7F'), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        w, h = self.ctx.size()
        for kind, value in self.ctx.snap_lines:
            if kind == 'v':
                painter.drawLine(QPointF(value, 0), QPointF(value, h))
            else:
                painter.drawLine(QPointF(0, value), QPointF(w, value))


def render_slide(deck: dict, index: int, project_dir, width_px: int, renderer=None, *, for_print=False) -> QImage:
    """Image of one slide (thumbnails, PNG / PDF / PowerPoint export)."""
    ctx = Context(deck, project_dir, editable=False, live=False, renderer=renderer)
    scene = SlideScene(ctx)
    slides = deck.get('slides', [])
    scene.build(slides[index], index + 1, len(slides))
    w, h = ctx.size()
    height_px = max(1, round(width_px * h / w))
    image = QImage(width_px, height_px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#FFFFFF'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    scene.render(painter, QRectF(0, 0, width_px, height_px), QRectF(0, 0, w, h))
    painter.end()
    scene.clear()
    return image


def paint_slide(painter: QPainter, target: QRectF, deck: dict, index: int, project_dir, renderer=None):
    """Draw one slide with a painter (vector output for PDF export)."""
    ctx = Context(deck, project_dir, editable=False, live=False, renderer=renderer)
    scene = SlideScene(ctx)
    slides = deck.get('slides', [])
    scene.build(slides[index], index + 1, len(slides))
    w, h = ctx.size()
    scene.render(painter, target, QRectF(0, 0, w, h))
    scene.clear()
