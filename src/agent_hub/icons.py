"""Status marks for tabs and the chat list, like a browser tab: a spinner while running, an exclamation mark
when the assistant waits for you, a check mark when a reply arrived that you have not read, a cross on an error,
three dots while queued. All drawn as vector shapes (no font glyphs or emoji)."""
from __future__ import annotations

COLORS = {'running': '#4C8DF6', 'approval': '#E8A33D', 'queued': '#9AA0A6', 'done': '#3BB273',
          'error': '#E5534B', 'idle': '#9AA0A6'}
TEXT = {'running': 'Working', 'approval': 'Needs your answer', 'queued': 'Waiting for a free model',
        'done': 'Reply ready', 'error': 'Error', 'idle': 'Idle'}


def state_color(state: str) -> str:
    return COLORS.get(state, COLORS['idle'])


def state_text(state: str) -> str:
    return TEXT.get(state, state)


_cache = {}


def state_icon(state: str, frame: int = 0, unread: bool = True):
    """QIcon for a state; ``frame`` animates the running spinner (0–11)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    key = (state, frame % 12 if state == 'running' else 0, unread)
    if key in _cache:
        return _cache[key]
    size = 32
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(state_color(state))
    rect = QRectF(5, 5, size - 10, size - 10)
    if state == 'running':
        pen = QPen(QColor(color.red(), color.green(), color.blue(), 60), 4)
        p.setPen(pen)
        p.drawEllipse(rect)
        pen.setColor(color)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(-(frame % 12) * 30 * 16), 110 * 16)
    elif state in ('approval', 'error', 'queued') or (state == 'done' and unread):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(rect)
        pen = QPen(QColor('#FFFFFF'), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        c = size / 2
        if state == 'approval':                     # exclamation mark
            p.drawLine(QPointF(c, c - 6), QPointF(c, c + 1.5))
            p.drawPoint(QPointF(c, c + 6))
        elif state == 'error':                      # cross
            p.drawLine(QPointF(c - 4.5, c - 4.5), QPointF(c + 4.5, c + 4.5))
            p.drawLine(QPointF(c + 4.5, c - 4.5), QPointF(c - 4.5, c + 4.5))
        elif state == 'queued':                     # three dots
            for dx in (-5, 0, 5):
                p.drawPoint(QPointF(c + dx, c))
        else:                                       # check mark
            p.drawPolyline([QPointF(c - 5, c + 0.5), QPointF(c - 1.5, c + 4), QPointF(c + 5.5, c - 4)])
    else:
        p.setPen(QPen(QColor(state_color('idle')), 2))
        p.drawEllipse(QRectF(11, 11, 10, 10))
    p.end()
    icon = QIcon(pix)
    _cache[key] = icon
    return icon
