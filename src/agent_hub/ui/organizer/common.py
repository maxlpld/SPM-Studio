"""Small shared pieces of the calendar / to-do / mail views: the organizer signal bridge, colours, dates."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor

from .. import theme

_bridge = None


class Bridge(QObject):
    """Qt signals for organizer changes (the data layer calls plain listeners)."""
    calendarChanged = Signal()
    todoChanged = Signal()
    mailChanged = Signal()

    def __init__(self, organizer):
        super().__init__()
        self.organizer = organizer
        self._pending = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._flush)
        organizer.listeners.append(self._changed)
        self._watch = QTimer(self)                 # another process may write the files: look every 3 s
        self._watch.setInterval(3000)
        self._watch.timeout.connect(self._poll)
        self._watch.start()

    def _changed(self, kind: str):
        self._pending.add(kind)
        QTimer.singleShot(0, self._timer.start)

    def _flush(self):
        kinds, self._pending = self._pending, set()
        if 'calendar' in kinds:
            self.calendarChanged.emit()
        if 'todo' in kinds:
            self.todoChanged.emit()
        if 'mail' in kinds:
            self.mailChanged.emit()

    def _poll(self):
        if self.organizer.calendar.reload():
            self.calendarChanged.emit()
        if self.organizer.todo.reload():
            self.todoChanged.emit()


def bridge(organizer=None) -> Bridge:
    global _bridge
    if organizer is None:
        from ...organizer import shared
        organizer = shared()
    if _bridge is None or _bridge.organizer is not organizer:
        _bridge = Bridge(organizer)
    return _bridge


def t(key: str, default: str = '#888888') -> str:
    return str(theme.tokens().get(key, default))


def readable_on(color: str) -> QColor:
    c = QColor(color)
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return QColor('#1F1E1C') if lum > 165 else QColor('#FFFFFF')


def soft(color: str, alpha: float = 0.18) -> QColor:
    """A light tint of an event colour for the event background (works on light and dark themes)."""
    c = QColor(color)
    base = QColor(t('surface', '#FFFFFF'))
    return QColor(round(base.red() + (c.red() - base.red()) * alpha), round(base.green() + (c.green() - base.green())
                  * alpha), round(base.blue() + (c.blue() - base.blue()) * alpha))


def week_start(day: dt.date, first: int = 0) -> dt.date:
    return day - dt.timedelta(days=(day.weekday() - first) % 7)


def fmt_time(value: dt.datetime) -> str:
    return value.strftime('%H:%M')


ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
