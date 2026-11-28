"""Calendar window in the style of a web calendar: day, week, month and schedule views, a mini month navigator,
calendars with colours and show / hide, create by click or drag, move and resize by drag, an event popup, and
the usual keyboard shortcuts — ``d`` ``w`` ``m`` ``a`` (schedule), ``t`` today, ``j`` / ``k`` (or ``n`` / ``p``)
next / previous, ``c`` create, ``/`` search, ``Delete`` the selected event, ``Esc`` close the popup."""
from __future__ import annotations

from ..theme import scale_font

import datetime as dt
import html

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (QAbstractScrollArea, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame,
                               QStyledItemDelegate,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ...organizer.calendar import iso, parse_time
from .. import theme
from ..svg_icons import icon, set_icon
from ..widgets import icon_button
from .common import bridge, readable_on, soft, t, week_start

HOUR = 48                                         # pixels per hour in day / week views
SNAP = 15                                         # minutes
GUTTER = 56


# ====================================================================== mini month
class MiniMonth(QWidget):
    picked = Signal(object)                       # date

    def __init__(self, parent=None):
        super().__init__(parent)
        self.month = dt.date.today().replace(day=1)
        self.selected = dt.date.today()
        self.first = 0
        self.busy = set()
        self.setMinimumSize(210, 200)
        self.setMouseTracking(True)
        self.hover = None

    def set_date(self, day: dt.date):
        self.selected = day
        if (day.year, day.month) != (self.month.year, self.month.month):
            self.month = day.replace(day=1)
        self.update()

    def _cells(self):
        start = week_start(self.month, self.first)
        return [start + dt.timedelta(days=i) for i in range(42)]

    def _geom(self):
        w = self.width()
        cw = (w - 8) / 7
        return cw, 26, 30                          # cell width, cell height, top

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cw, ch, top = self._geom()
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(t('text')))
        p.drawText(QRect(6, 0, self.width() - 70, 24), Qt.AlignmentFlag.AlignVCenter, self.month.strftime('%B %Y'))
        icon('chevron-left', t('muted')).paint(p, QRect(self.width() - 58, 4, 18, 18))
        icon('chevron-right', t('muted')).paint(p, QRect(self.width() - 28, 4, 18, 18))
        small = QFont(self.font())
        scale_font(small, 0.85, 7.0)
        p.setFont(small)
        names = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
        names = names[self.first:] + names[:self.first]
        p.setPen(QColor(t('subtle')))
        for i, n in enumerate(names):
            p.drawText(QRectF(4 + i * cw, top - 4, cw, 18), Qt.AlignmentFlag.AlignCenter, n)
        today = dt.date.today()
        for i, day in enumerate(self._cells()):
            r = QRectF(4 + (i % 7) * cw, top + 14 + (i // 7) * ch, cw, ch)
            circle = QRectF(r.center().x() - 11, r.center().y() - 11, 22, 22)
            if day == today:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t('accent')))
                p.drawEllipse(circle)
                p.setPen(QColor(t('accent_fg')))
            elif day == self.selected:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t('selection')))
                p.drawEllipse(circle)
                p.setPen(QColor(t('text')))
            elif self.hover == i:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t('surface_alt')))
                p.drawEllipse(circle)
                p.setPen(QColor(t('text')))
            else:
                p.setPen(QColor(t('text') if day.month == self.month.month else t('subtle')))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(day.day))
            if day in self.busy and day != today:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t('accent')))
                p.drawEllipse(QPointF(r.center().x(), r.bottom() - 3), 1.6, 1.6)
        p.end()

    def _index(self, pos):
        cw, ch, top = self._geom()
        if pos.y() < top + 14:
            return None
        col, row = int((pos.x() - 4) // cw), int((pos.y() - top - 14) // ch)
        if 0 <= col < 7 and 0 <= row < 6:
            return row * 7 + col
        return None

    def mouseMoveEvent(self, e):
        idx = self._index(e.position())
        if idx != self.hover:
            self.hover = idx
            self.update()

    def leaveEvent(self, _e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        pos = e.position()
        if pos.y() < 26:
            if pos.x() > self.width() - 62:
                step = -1 if pos.x() < self.width() - 32 else 1
                m = self.month.month - 1 + step
                self.month = dt.date(self.month.year + m // 12, m % 12 + 1, 1)
                self.update()
            return
        idx = self._index(pos)
        if idx is not None:
            day = self._cells()[idx]
            self.set_date(day)
            self.picked.emit(day)


# ====================================================================== time grid (day / week)
def layout_columns(items):
    """Overlapping timed events side by side: [(item, column, columns)]."""
    items = sorted(items, key=lambda o: (o['start'], -(o['end'] - o['start']).total_seconds()))
    out, group, group_end = [], [], None
    columns = []

    def flush():
        n = max((c for _i, c in group), default=-1) + 1
        out.extend((i, c, n) for i, c in group)
    for o in items:
        if group_end is not None and o['start'] >= group_end:
            flush()
            group, columns, group_end = [], [], None
        placed = None
        for ci, end in enumerate(columns):
            if end <= o['start']:
                placed = ci
                columns[ci] = o['end']
                break
        if placed is None:
            columns.append(o['end'])
            placed = len(columns) - 1
        group.append((o, placed))
        group_end = max(group_end or o['end'], o['end'])
    flush()
    return out


class TimeGrid(QAbstractScrollArea):
    """Day or week view: all-day strip on top, hours below; drag to create, move, resize."""
    createRequested = Signal(object, object, bool)          # start, end, all_day
    openRequested = Signal(dict, QPoint)                    # occurrence, global position
    editRequested = Signal(dict)
    moved = Signal(dict, object, object)                    # occurrence, new start, new end

    def __init__(self, organizer, days: int = 7, parent=None):
        super().__init__(parent)
        self.org = organizer
        self.days = days
        self.start = week_start(dt.date.today())
        self.occ = []
        self.allday = []
        self.selected = None
        self.drag = None
        self.first_hour = 8
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._now = QTimer(self)
        self._now.setInterval(60_000)
        self._now.timeout.connect(self.viewport().update)
        self._now.start()

    # ---- data
    def set_range(self, start: dt.date, days: int):
        self.start, self.days = start, days
        self.reload()

    def reload(self):
        s = dt.datetime.combine(self.start, dt.time())
        e = s + dt.timedelta(days=self.days)
        found = self.org.calendar.occurrences(s, e)
        self.allday = [o for o in found if o['all_day'] or (o['end'] - o['start']) >= dt.timedelta(hours=24)]
        self.occ = [o for o in found if o not in self.allday]
        self._update_scroll()
        self.viewport().update()

    def header_height(self):
        rows = self._allday_rows()
        return 52 + max(1, len(rows)) * 22 + 6

    def _allday_rows(self):
        rows = []
        for o in sorted(self.allday, key=lambda o: (self._day_index(o['start']), -self._span(o))):
            a, b = self._day_index(o['start']), self._day_index(o['start']) + self._span(o)
            for row in rows:
                if all(b <= x or a >= y for x, y, _o in row):
                    row.append((a, b, o))
                    break
            else:
                rows.append([(a, b, o)])
        return rows

    def _day_index(self, value) -> int:
        d = value.date() if isinstance(value, dt.datetime) else value
        return max(0, (d - self.start).days)

    def _span(self, o) -> int:
        s = o['start'].date() if isinstance(o['start'], dt.datetime) else o['start']
        e = o['end'].date() if isinstance(o['end'], dt.datetime) else o['end']
        if isinstance(o['end'], dt.datetime) and o['end'].time() != dt.time():
            e = e + dt.timedelta(days=1)
        first = max(s, self.start)
        last = min(e, self.start + dt.timedelta(days=self.days))
        return max(1, (last - first).days)

    def _update_scroll(self):
        total = 24 * HOUR
        visible = self.viewport().height() - self.header_height()
        self.verticalScrollBar().setRange(0, max(0, total - visible))
        self.verticalScrollBar().setPageStep(max(1, visible))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_scroll()

    def scroll_to_hour(self, hour: int):
        self.verticalScrollBar().setValue(int(hour * HOUR))

    # ---- geometry
    def col_width(self) -> float:
        return max(20.0, (self.viewport().width() - GUTTER) / self.days)

    def y_of(self, value: dt.datetime) -> float:
        return self.header_height() + (value.hour + value.minute / 60) * HOUR - self.verticalScrollBar().value()

    def time_at(self, pos) -> dt.datetime | None:
        col = int((pos.x() - GUTTER) // self.col_width())
        if not 0 <= col < self.days or pos.y() < self.header_height():
            return None
        minutes = (pos.y() - self.header_height() + self.verticalScrollBar().value()) / HOUR * 60
        minutes = max(0, min(24 * 60 - SNAP, int(minutes // SNAP * SNAP)))
        return dt.datetime.combine(self.start + dt.timedelta(days=col), dt.time()) + dt.timedelta(minutes=minutes)

    def event_rects(self):
        cw = self.col_width()
        out = []
        by_day = {}
        for o in self.occ:
            d = self._day_index(o['start'])
            if 0 <= d < self.days:
                by_day.setdefault(d, []).append(o)
        for d, items in by_day.items():
            for o, c, n in layout_columns(items):
                y0 = self.y_of(o['start'])
                end = min(o['end'], dt.datetime.combine(o['start'].date() + dt.timedelta(days=1), dt.time()))
                y1 = max(y0 + 18, self.header_height() + ((end - dt.datetime.combine(o['start'].date(), dt.time()))
                                                          .total_seconds() / 3600) * HOUR - self.verticalScrollBar().value())
                x0 = GUTTER + d * cw + 2 + c * (cw - 8) / n
                w = (cw - 8) / n - 2 + (6 if c == n - 1 else 0)
                out.append((QRectF(x0, y0 + 1, max(8, w), y1 - y0 - 2), o))
        return out

    def allday_rects(self):
        cw = self.col_width()
        out = []
        for r, row in enumerate(self._allday_rows()):
            for a, b, o in row:
                out.append((QRectF(GUTTER + a * cw + 2, 52 + r * 22, (b - a) * cw - 4, 20), o))
        return out

    # ---- painting
    def paintEvent(self, _e):
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.viewport().width(), self.viewport().height()
        cw = self.col_width()
        top = self.header_height()
        p.fillRect(0, 0, W, H, QColor(t('surface', '#FFFFFF')))
        grid = QColor(t('border'))
        today = dt.date.today()
        # hour lines
        small = QFont(self.font())
        scale_font(small, 0.82, 7.0)
        p.setFont(small)
        p.save()
        p.setClipRect(QRect(0, top, W, H - top))
        for h in range(25):
            y = top + h * HOUR - self.verticalScrollBar().value()
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(GUTTER - 6, y), QPointF(W, y))
            if 0 < h < 24:
                p.setPen(QColor(t('subtle')))
                p.drawText(QRectF(0, y - 8, GUTTER - 10, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           f'{h:02d}:00')
        for d in range(self.days + 1):
            x = GUTTER + d * cw
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x, top), QPointF(x, H))
        # selection preview while dragging on empty space
        if self.drag and self.drag['kind'] == 'create' and self.drag.get('end'):
            a, b = sorted([self.drag['start'], self.drag['end']])
            b = b + dt.timedelta(minutes=SNAP)
            d = self._day_index(a)
            rect = QRectF(GUTTER + d * cw + 2, self.y_of(a), cw - 6, self.y_of(b) - self.y_of(a))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t('accent')))
            p.setOpacity(0.35)
            p.drawRoundedRect(rect, 6, 6)
            p.setOpacity(1)
            p.setPen(QColor(t('text')))
            p.drawText(rect.adjusted(6, 2, -4, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       f'{a:%H:%M} – {b:%H:%M}')
        # events
        for rect, o in self.event_rects():
            if self.drag and self.drag['kind'] in ('move', 'resize') and self.drag['occ'] is o and self.drag.get('rect'):
                rect = self.drag['rect']
            self._paint_event(p, rect, o)
        # now line
        if self.start <= today < self.start + dt.timedelta(days=self.days):
            now = dt.datetime.now()
            y = self.y_of(now)
            x0 = GUTTER + (today - self.start).days * cw
            red = QColor(t('error', '#C94A3F'))
            p.setPen(QPen(red, 2))
            p.drawLine(QPointF(x0, y), QPointF(x0 + cw, y))
            p.setBrush(red)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x0, y), 5, 5)
        p.restore()
        # header (fixed)
        p.fillRect(0, 0, W, top, QColor(t('surface', '#FFFFFF')))
        p.setPen(QPen(grid, 1))
        p.drawLine(0, top - 1, W, top - 1)
        for d in range(self.days):
            day = self.start + dt.timedelta(days=d)
            x = GUTTER + d * cw
            p.setFont(small)
            p.setPen(QColor(t('accent') if day == today else t('muted')))
            p.drawText(QRectF(x, 4, cw, 16), Qt.AlignmentFlag.AlignCenter, day.strftime('%a').upper())
            big = QFont(self.font())
            scale_font(big, 1.45)
            p.setFont(big)
            circle = QRectF(x + cw / 2 - 16, 20, 32, 30)
            if day == today:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t('accent')))
                p.drawEllipse(circle)
                p.setPen(QColor(t('accent_fg')))
            else:
                p.setPen(QColor(t('text')))
            p.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(day.day))
        p.setFont(small)
        p.setPen(QColor(t('subtle')))
        p.drawText(QRectF(0, 52, GUTTER - 8, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, 'all day')
        for rect, o in self.allday_rects():
            self._paint_chip(p, rect, o)
        p.end()

    def _paint_event(self, p, rect: QRectF, o):
        color = o['color']
        done = (o.get('links') or {}).get('todo') and self.org.calendar.get(o['uid']) and \
            self.org.calendar.get(o['uid']).get('status') == 'DONE'
        p.setPen(QPen(QColor(t('surface')), 1))
        p.setBrush(QColor(color) if not done else soft(color, 0.35))
        p.drawRoundedRect(rect, 5, 5)
        if o is self.selected or (self.selected and self.selected.get('uid') == o['uid'] and
                                  self.selected.get('instance') == o['instance']):
            p.setPen(QPen(QColor(t('text')), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 5, 5)
        fg = readable_on(color) if not done else QColor(t('muted'))
        p.setPen(fg)
        f = QFont(self.font())
        scale_font(f, 0.86, 7.0)
        f.setWeight(QFont.Weight.DemiBold)
        f.setStrikeOut(bool(done))
        p.setFont(f)
        inner = rect.adjusted(6, 2, -4, -2)
        fm = QFontMetrics(f)
        title = o['title']
        line = f"{o['start']:%H:%M}–{o['end']:%H:%M}"
        if inner.height() < 2.2 * fm.height():
            p.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                       fm.elidedText(f'{title}, {o["start"]:%H:%M}', Qt.TextElideMode.ElideRight, int(inner.width())))
            return
        p.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, title)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        y = inner.top() + fm.boundingRect(QRect(0, 0, int(inner.width()), 400), Qt.TextFlag.TextWordWrap, title).height()
        if y + fm.height() < inner.bottom():
            p.drawText(QRectF(inner.left(), y, inner.width(), fm.height()), Qt.AlignmentFlag.AlignLeft,
                       line + (f" · {o['location']}" if o.get('location') else ''))
        if o.get('recurring') and inner.height() > 30:
            icon('repeat', fg.name()).paint(p, QRect(int(inner.right() - 12), int(inner.bottom() - 12), 12, 12))

    def _paint_chip(self, p, rect: QRectF, o):
        color = o['color']
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(rect, 4, 4)
        f = QFont(self.font())
        scale_font(f, 0.86, 7.0)
        f.setWeight(QFont.Weight.DemiBold)
        ev = self.org.calendar.get(o['uid']) or {}
        f.setStrikeOut(ev.get('status') == 'DONE')
        p.setFont(f)
        p.setPen(readable_on(color))
        fm = QFontMetrics(f)
        p.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(o['title'], Qt.TextElideMode.ElideRight, int(rect.width() - 10)))

    # ---- mouse
    def _hit(self, pos):
        for rect, o in reversed(self.allday_rects()):
            if rect.contains(QPointF(pos)):
                return o, rect, 'allday'
        if pos.y() < self.header_height():
            return None, None, None
        for rect, o in reversed(self.event_rects()):
            if rect.contains(QPointF(pos)):
                edge = 'bottom' if pos.y() > rect.bottom() - 6 and not o.get('readonly') else 'body'
                return o, rect, edge
        return None, None, None

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        pos = e.position().toPoint()
        o, rect, part = self._hit(pos)
        if o is not None:
            self.selected = o
            if part == 'allday' or o.get('readonly'):
                self.drag = {'kind': 'click', 'occ': o, 'origin': pos}
            else:
                self.drag = {'kind': 'resize' if part == 'bottom' else 'move', 'occ': o, 'origin': pos,
                             'rect0': QRectF(rect), 'rect': None, 'moved': False}
            self.viewport().update()
            return
        when = self.time_at(pos)
        if when is not None:
            self.drag = {'kind': 'create', 'start': when, 'end': None, 'origin': pos}
        elif 52 <= pos.y() < self.header_height() and pos.x() > GUTTER:
            col = int((pos.x() - GUTTER) // self.col_width())
            day = self.start + dt.timedelta(days=col)
            self.createRequested.emit(day, day + dt.timedelta(days=1), True)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if not self.drag:
            o, _rect, part = self._hit(pos)
            self.viewport().setCursor(Qt.CursorShape.SizeVerCursor if part == 'bottom' else
                                      Qt.CursorShape.PointingHandCursor if o is not None else Qt.CursorShape.ArrowCursor)
            return
        d = self.drag
        if d['kind'] == 'create':
            when = self.time_at(QPoint(d['origin'].x(), pos.y()))
            if when is not None:
                d['end'] = when
                self.viewport().update()
        elif d['kind'] in ('move', 'resize'):
            if (pos - d['origin']).manhattanLength() < 4 and not d['moved']:
                return
            d['moved'] = True
            r = QRectF(d['rect0'])
            dy = round((pos.y() - d['origin'].y()) / (HOUR * SNAP / 60)) * (HOUR * SNAP / 60)
            if d['kind'] == 'move':
                dx = round((pos.x() - d['origin'].x()) / self.col_width()) * self.col_width()
                r.translate(dx, dy)
            else:
                r.setBottom(max(r.top() + HOUR * SNAP / 60, r.bottom() + dy))
            d['rect'] = r
            self.viewport().update()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if not d:
            return
        pos = e.position().toPoint()
        if d['kind'] == 'create':
            a = d['start']
            b = d.get('end') or a
            a, b = sorted([a, b])
            b = b + dt.timedelta(minutes=SNAP)
            if b - a < dt.timedelta(minutes=30):
                b = a + dt.timedelta(minutes=60 if d.get('end') is None else 30)
            self.createRequested.emit(a, b, False)
        elif d['kind'] in ('move', 'resize') and d.get('moved') and d.get('rect') is not None:
            o = d['occ']
            r = d['rect']
            minutes_top = round((r.top() - d['rect0'].top()) / HOUR * 60 / SNAP) * SNAP
            days = round((r.left() - d['rect0'].left()) / self.col_width())
            if d['kind'] == 'move':
                start = o['start'] + dt.timedelta(days=days, minutes=minutes_top)
                end = start + (o['end'] - o['start'])
            else:
                minutes_len = round((r.height() - d['rect0'].height()) / HOUR * 60 / SNAP) * SNAP
                start = o['start']
                end = max(start + dt.timedelta(minutes=SNAP), o['end'] + dt.timedelta(minutes=minutes_len))
            self.moved.emit(o, start, end)
        elif d['kind'] in ('move', 'resize', 'click'):
            self.openRequested.emit(d['occ'], self.viewport().mapToGlobal(pos))
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        o, _r, _p = self._hit(e.position().toPoint())
        if o is not None:
            self.editRequested.emit(o)

    def wheelEvent(self, e):
        super().wheelEvent(e)


# ====================================================================== month
class MonthView(QWidget):
    createRequested = Signal(object, object, bool)
    openRequested = Signal(dict, QPoint)
    editRequested = Signal(dict)
    moved = Signal(dict, object, object)
    dayRequested = Signal(object)

    def __init__(self, organizer, parent=None):
        super().__init__(parent)
        self.org = organizer
        self.month = dt.date.today().replace(day=1)
        self.first = 0
        self.occ = {}
        self.selected = None
        self.drag = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_month(self, day: dt.date):
        self.month = day.replace(day=1)
        self.reload()

    def cells(self):
        start = week_start(self.month, self.first)
        return [start + dt.timedelta(days=i) for i in range(42)]

    def reload(self):
        cells = self.cells()
        found = self.org.calendar.occurrences(cells[0], cells[-1] + dt.timedelta(days=1))
        self.occ = {}
        for o in found:
            s = o['start'].date() if isinstance(o['start'], dt.datetime) else o['start']
            e = o['end'].date() if isinstance(o['end'], dt.datetime) else o['end']
            if isinstance(o['end'], dt.datetime) and o['end'].time() == dt.time() and e > s:
                e -= dt.timedelta(days=1)
            if o['all_day']:
                e -= dt.timedelta(days=1)
            day = s
            while day <= max(s, e):
                self.occ.setdefault(day, []).append(o)
                day += dt.timedelta(days=1)
        self.update()

    def _geom(self):
        head = 26
        return (self.width()) / 7, (self.height() - head) / 6, head

    def chip_rects(self):
        cw, ch, head = self._geom()
        fm = QFontMetrics(self.font())
        line = fm.height() + 4
        out = []
        for i, day in enumerate(self.cells()):
            x, y = (i % 7) * cw, head + (i // 7) * ch
            items = self.occ.get(day, [])
            room = max(0, int((ch - 26) // line))
            shown = items if len(items) <= room else items[:max(0, room - 1)]
            for k, o in enumerate(shown):
                out.append((QRectF(x + 3, y + 24 + k * line, cw - 6, line - 2), o, day))
            if len(items) > len(shown):
                out.append((QRectF(x + 3, y + 24 + len(shown) * line, cw - 6, line - 2),
                            {'more': len(items) - len(shown)}, day))
        return out

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cw, ch, head = self._geom()
        p.fillRect(self.rect(), QColor(t('surface', '#FFFFFF')))
        grid = QColor(t('border'))
        small = QFont(self.font())
        scale_font(small, 0.82, 7.0)
        names = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
        names = names[self.first:] + names[:self.first]
        p.setFont(small)
        p.setPen(QColor(t('muted')))
        for i, n in enumerate(names):
            p.drawText(QRectF(i * cw, 4, cw, 18), Qt.AlignmentFlag.AlignCenter, n)
        today = dt.date.today()
        for i, day in enumerate(self.cells()):
            x, y = (i % 7) * cw, head + (i // 7) * ch
            p.setPen(QPen(grid, 1))
            p.setBrush(Qt.BrushStyle.NoBrush if day.month == self.month.month else QColor(t('surface_alt')))
            p.drawRect(QRectF(x, y, cw, ch))
            circle = QRectF(x + cw / 2 - 12, y + 2, 24, 20)
            if day == today:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t('accent')))
                p.drawRoundedRect(circle, 10, 10)
                p.setPen(QColor(t('accent_fg')))
            else:
                p.setPen(QColor(t('text') if day.month == self.month.month else t('subtle')))
            label = day.strftime('%d %b').lstrip('0') if day.day == 1 else str(day.day)
            p.setFont(small)
            p.drawText(circle.adjusted(-20 if day.day == 1 else 0, 0, 20 if day.day == 1 else 0, 0),
                       Qt.AlignmentFlag.AlignCenter, label)
        f = QFont(self.font())
        scale_font(f, 0.86, 7.0)
        fm = QFontMetrics(f)
        p.setFont(f)
        for rect, o, day in self.chip_rects():
            if 'more' in o:
                p.setPen(QColor(t('muted')))
                p.drawText(rect.adjusted(6, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, f"{o['more']} more")
                continue
            if self.drag and self.drag.get('occ') is o and self.drag.get('target'):
                continue
            color = o['color']
            ev = self.org.calendar.get(o['uid']) or {}
            done = ev.get('status') == 'DONE'
            f.setStrikeOut(done)
            p.setFont(f)
            if o['all_day'] or (o['end'] - o['start']) >= dt.timedelta(hours=24):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(color) if not done else soft(color, 0.35))
                p.drawRoundedRect(rect, 4, 4)
                p.setPen(readable_on(color) if not done else QColor(t('muted')))
                p.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(o['title'], Qt.TextElideMode.ElideRight, int(rect.width() - 10)))
            else:
                if self.selected is o:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(t('selection')))
                    p.drawRoundedRect(rect, 4, 4)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(color))
                p.drawEllipse(QPointF(rect.left() + 7, rect.center().y()), 3.5, 3.5)
                p.setPen(QColor(t('text') if not done else t('muted')))
                text = f"{o['start']:%H:%M} {o['title']}"
                p.drawText(rect.adjusted(15, 0, -2, 0), Qt.AlignmentFlag.AlignVCenter,
                           fm.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width() - 18)))
        if self.drag and self.drag.get('target'):
            i = self.cells().index(self.drag['target']) if self.drag['target'] in self.cells() else -1
            if i >= 0:
                x, y = (i % 7) * cw, head + (i // 7) * ch
                p.setPen(QPen(QColor(t('accent')), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(x + 1, y + 1, cw - 2, ch - 2))
        p.end()

    def day_at(self, pos):
        cw, ch, head = self._geom()
        col, row = int(pos.x() // cw), int((pos.y() - head) // ch)
        if 0 <= col < 7 and 0 <= row < 6 and pos.y() >= head:
            return self.cells()[row * 7 + col]
        return None

    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        for rect, o, day in self.chip_rects():
            if rect.contains(pos):
                if 'more' in o:
                    self.dayRequested.emit(day)
                    return
                self.selected = o
                self.drag = {'occ': o, 'origin': pos, 'target': None}
                self.update()
                return
        day = self.day_at(pos)
        if day is not None:
            cw, ch, head = self._geom()
            i = self.cells().index(day)
            if pos.y() - (head + (i // 7) * ch) < 22:
                self.dayRequested.emit(day)
                return
            self.createRequested.emit(day, day + dt.timedelta(days=1), True)

    def mouseMoveEvent(self, e):
        if self.drag and not self.drag['occ'].get('readonly'):
            if (e.position() - self.drag['origin']).manhattanLength() > 6:
                self.drag['target'] = self.day_at(e.position())
                self.update()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        if not d:
            return
        o = d['occ']
        target = d.get('target')
        s0 = o['start'].date() if isinstance(o['start'], dt.datetime) else o['start']
        if target is not None and target != s0:
            delta = target - s0
            self.moved.emit(o, o['start'] + delta, o['end'] + delta)
        else:
            self.openRequested.emit(o, self.mapToGlobal(e.position().toPoint()))
        self.update()

    def mouseDoubleClickEvent(self, e):
        for rect, o, _day in self.chip_rects():
            if rect.contains(e.position()) and 'more' not in o:
                self.editRequested.emit(o)
                return


# ====================================================================== schedule
class ScheduleView(QListWidget):
    openRequested = Signal(dict, QPoint)
    editRequested = Signal(dict)

    def __init__(self, organizer, parent=None):
        super().__init__(parent)
        self.org = organizer
        self.start = dt.date.today()
        self.setObjectName('calSchedule')
        self.itemClicked.connect(self._clicked)
        self.itemDoubleClicked.connect(lambda i: self.editRequested.emit(i.data(Qt.ItemDataRole.UserRole))
                                       if i.data(Qt.ItemDataRole.UserRole) else None)

    def set_start(self, day: dt.date):
        self.start = day
        self.reload()

    def reload(self):
        self.clear()
        found = self.org.calendar.occurrences(self.start, self.start + dt.timedelta(days=60))
        last = None
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        for o in found:
            day = o['start'].date() if isinstance(o['start'], dt.datetime) else o['start']
            day = max(day, self.start)
            if day != last:
                head = QListWidgetItem(day.strftime('%A %d %B %Y').replace(' 0', ' ') + ('   · today'
                                                                                           if day == dt.date.today()
                                                                                           else ''))
                head.setFont(bold)
                head.setFlags(Qt.ItemFlag.NoItemFlags)
                head.setForeground(QColor(t('accent') if day == dt.date.today() else t('text')))
                self.addItem(head)
                last = day
            when = 'All day' if o['all_day'] else f"{o['start']:%H:%M} – {o['end']:%H:%M}"
            item = QListWidgetItem(theme.dot_icon(o['color']), f"   {when}    {o['title']}" +
                                   (f"   · {o['location']}" if o.get('location') else ''))
            item.setData(Qt.ItemDataRole.UserRole, o)
            item.setToolTip(o.get('description', '')[:400] or o['calendar_name'])
            self.addItem(item)
        if not found:
            empty = QListWidgetItem('Nothing planned in the next 60 days.')
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(empty)

    def _clicked(self, item):
        o = item.data(Qt.ItemDataRole.UserRole)
        if o:
            self.openRequested.emit(o, self.mapToGlobal(self.visualItemRect(item).center()))


# ====================================================================== popup
class EventPopup(QFrame):
    edit = Signal(dict)
    delete = Signal(dict)
    done = Signal(dict, bool)

    def __init__(self, organizer, o: dict, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName('calPopup')
        self.setStyleSheet(f"#calPopup {{ background: {t('surface')}; border: 1px solid {t('border')}; "
                           f"border-radius: 10px; }} QLabel {{ color: {t('text')}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        row = QHBoxLayout()
        row.addStretch(1)
        ev = organizer.calendar.get(o['uid']) or {}
        if not o.get('readonly'):
            b = icon_button('edit', 'Edit (e)')
            b.clicked.connect(lambda: (self.close(), self.edit.emit(o)))
            row.addWidget(b)
            b = icon_button('trash', 'Delete (Delete)')
            b.clicked.connect(lambda: (self.close(), self.delete.emit(o)))
            row.addWidget(b)
        b = icon_button('close', 'Close (Esc)')
        b.clicked.connect(self.close)
        row.addWidget(b)
        lay.addLayout(row)
        title = QLabel(f"<span style='font-size:15pt'>{html.escape(o['title'])}</span>")
        title.setWordWrap(True)
        lay.addWidget(title)
        if o['all_day']:
            s = o['start']
            e = o['end'] - dt.timedelta(days=1) if not isinstance(o['end'], dt.datetime) else o['end']
            when = s.strftime('%A %d %B') + ('' if e == s else ' – ' + e.strftime('%A %d %B'))
        else:
            when = f"{o['start']:%A %d %B · %H:%M} – {o['end']:%H:%M}"
        rows = [('clock', when + (f" ({o['tz']})" if o.get('tz') else ''))]
        if o.get('recurring'):
            from ...organizer import rrule
            rows.append(('repeat', rrule.describe(ev.get('rrule', ''))))
        if o.get('location'):
            rows.append(('location', o['location']))
        if o.get('reminders'):
            rows.append(('bell', ', '.join(f'{m} min' if m < 60 else f'{m // 60} h' if m < 1440 else f'{m // 1440} d'
                                           for m in o['reminders']) + ' before'))
        rows.append(('calendar', o['calendar_name'] + ('  (read-only)' if o.get('readonly') else '') +
                     ('  · added by the assistant' if o.get('created_by') == 'assistant' else '')))
        for name, text in rows:
            r = QHBoxLayout()
            ic = QLabel()
            ic.setPixmap(icon(name, t('muted')).pixmap(QSize(16, 16)))
            r.addWidget(ic)
            lab = QLabel(html.escape(text))
            lab.setWordWrap(True)
            r.addWidget(lab, 1)
            lay.addLayout(r)
        if o.get('description'):
            d = QLabel(html.escape(o['description'][:600]).replace('\n', '<br>'))
            d.setWordWrap(True)
            d.setStyleSheet(f"color: {t('muted')}")
            lay.addWidget(d)
        if (o.get('links') or {}).get('todo'):
            check = QCheckBox('Done (linked to-do)')
            check.setChecked(ev.get('status') == 'DONE')
            check.toggled.connect(lambda on: self.done.emit(o, on))
            lay.addWidget(check)
        self.setMinimumWidth(320)
        self.setMaximumWidth(420)


class CalendarListDelegate(QStyledItemDelegate):
    """A calendar in the side list: a rounded check box in the calendar's own colour (filled = shown)."""

    def paint(self, p, option, index):
        from PySide6.QtWidgets import QStyle
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        if option.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t('surface_alt')))
            p.drawRoundedRect(QRectF(r.adjusted(2, 1, -2, -1)), 6, 6)
        color = QColor(index.data(Qt.ItemDataRole.UserRole + 1) or t('accent'))
        box = QRectF(r.left() + 8, r.center().y() - 8, 16, 16)
        shown = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value or \
            index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        p.setPen(QPen(color, 2))
        p.setBrush(color if shown else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box.adjusted(1, 1, -1, -1), 3, 3)
        if shown:
            pen = QPen(readable_on(color.name()), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPolyline([QPointF(box.left() + 4, box.center().y()), QPointF(box.left() + 7, box.bottom() - 4.5),
                            QPointF(box.right() - 3.5, box.top() + 4.5)])
        p.setPen(QColor(t('text')))
        p.drawText(QRect(r.left() + 34, r.top(), r.width() - 38, r.height()), Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(option.font).elidedText(str(index.data()), Qt.TextElideMode.ElideRight, r.width() - 40))
        p.restore()

    def sizeHint(self, option, index):
        return QSize(10, QFontMetrics(option.font).height() + 12)

    def editorEvent(self, event, model, option, index):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonRelease:
            state = index.data(Qt.ItemDataRole.CheckStateRole)
            checked = state in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
            model.setData(index, Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
                          Qt.ItemDataRole.CheckStateRole)
            return True
        return super().editorEvent(event, model, option, index)


# ====================================================================== window
class CalendarWindow(QMainWindow):
    VIEWS = ('day', 'week', 'month', 'schedule')

    def __init__(self, organizer=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        from ...organizer import shared
        self.org = organizer or shared()
        self.bridge = bridge(self.org)
        self.setObjectName('AgentHubCalendar')
        self.setWindowTitle('Calendar')
        self.resize(1240, 820)
        conf = _conf()
        self.first = int(conf.get('calendar_week_start', 0))
        self.view = conf.get('calendar_default_view', 'week')
        self.date = dt.date.today()
        root = QWidget()
        root.setObjectName('calRoot')
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._toolbar())
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._side())
        self.stack = QStackedWidget()
        self.grid = TimeGrid(self.org)
        self.grid.first_hour = int(conf.get('calendar_day_start', 8))
        self.month = MonthView(self.org)
        self.month.first = self.first
        self.schedule = ScheduleView(self.org)
        for w in (self.grid, self.month, self.schedule):
            self.stack.addWidget(w)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([250, 990])
        outer.addWidget(split, 1)
        for v in (self.grid, self.month):
            v.createRequested.connect(self.create)
            v.moved.connect(self.move_occurrence)
        for v in (self.grid, self.month, self.schedule):
            v.openRequested.connect(self.show_popup)
            v.editRequested.connect(self.edit)
        self.month.dayRequested.connect(lambda d: (self.set_date(d), self.set_view('day')))
        self.bridge.calendarChanged.connect(self.reload)
        self._shortcuts()
        self.apply_theme()
        self.set_view(self.view)
        QTimer.singleShot(0, lambda: self.grid.scroll_to_hour(self.grid.first_hour))

    # ---- chrome
    def _toolbar(self):
        bar = QWidget()
        bar.setObjectName('calToolbar')
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(icon('calendar', t('accent')).pixmap(QSize(26, 26)))
        row.addWidget(logo)
        name = QLabel('Calendar')
        f = name.font()
        scale_font(f, 1.3)
        name.setFont(f)
        row.addWidget(name)
        row.addSpacing(20)
        today = QPushButton('Today')
        today.setObjectName('calPill')
        today.setToolTip('Today (t)')
        today.clicked.connect(lambda: self.set_date(dt.date.today()))
        row.addWidget(today)
        prev = icon_button('chevron-left', 'Previous (k or p)')
        nxt = icon_button('chevron-right', 'Next (j or n)')
        prev.clicked.connect(lambda: self.step(-1))
        nxt.clicked.connect(lambda: self.step(1))
        row.addWidget(prev)
        row.addWidget(nxt)
        self.title = QLabel('')
        f = self.title.font()
        scale_font(f, 1.3)
        self.title.setFont(f)
        row.addWidget(self.title)
        row.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName('hubSearch')
        self.search.setPlaceholderText('Search (/)')
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(240)
        self.search.returnPressed.connect(self.do_search)
        row.addWidget(self.search)
        self.view_buttons = {}
        group = QButtonGroup(self)
        seg = QWidget()
        seg.setObjectName('calSegment')
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        for key, label, keyhint in (('day', 'Day', 'd'), ('week', 'Week', 'w'), ('month', 'Month', 'm'),
                                    ('schedule', 'Schedule', 'a')):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setObjectName('calSeg')
            b.setToolTip(f'{label} ({keyhint})')
            b.clicked.connect(lambda _=False, k=key: self.set_view(k))
            group.addButton(b)
            sl.addWidget(b)
            self.view_buttons[key] = b
        row.addWidget(seg)
        settings = icon_button('gear', 'Calendar settings (import, subscribe, export, sync)')
        settings.clicked.connect(self.open_settings)
        row.addWidget(settings)
        return bar

    def _side(self):
        side = QWidget()
        side.setObjectName('calSide')
        side.setMinimumWidth(220)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(10, 10, 8, 10)
        lay.setSpacing(10)
        create = QPushButton('  Create')
        create.setObjectName('calCreate')
        set_icon(create, 'plus')
        create.setToolTip('New event (c)')
        create.clicked.connect(lambda: self.create(None, None, False))
        create.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        lay.addWidget(create)
        self.mini = MiniMonth()
        self.mini.first = self.first
        self.mini.picked.connect(self.set_date)
        lay.addWidget(self.mini)
        head = QHBoxLayout()
        lab = QLabel('My calendars')
        lab.setObjectName('calSection')
        head.addWidget(lab)
        head.addStretch(1)
        add = icon_button('plus', 'Add a calendar, subscribe to a URL or import an .ics file')
        add.clicked.connect(self._add_menu)
        head.addWidget(add)
        lay.addLayout(head)
        self.cal_list = QListWidget()
        self.cal_list.setObjectName('calList')
        self.cal_list.setItemDelegate(CalendarListDelegate(self.cal_list))
        self.cal_list.setMouseTracking(True)
        self.cal_list.itemChanged.connect(self._toggled)
        self.cal_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cal_list.customContextMenuRequested.connect(self._cal_menu)
        lay.addWidget(self.cal_list, 1)
        self.fill_calendars()
        return side

    def apply_theme(self):
        r = int(theme.tokens().get('hub_radius', 12))
        self.setStyleSheet(theme.stylesheet() + f"""
#calRoot {{ background: {t('window')}; color: {t('text')}; }}
#calToolbar {{ background: {t('window')}; border-bottom: 1px solid {t('border')}; }}
#calSide {{ background: {t('window')}; }}
#calSection {{ color: {t('muted')}; font-weight: 600; }}
QPushButton#calCreate {{ background: {t('surface')}; color: {t('text')}; border: 1px solid {t('border')};
    border-radius: {r + 6}px; padding: 10px 18px; font-weight: 600; }}
QPushButton#calCreate:hover {{ background: {t('surface_alt')}; }}
QPushButton#calPill {{ border: 1px solid {t('border')}; border-radius: {r}px; padding: 5px 14px; background: {t('surface')}; }}
QPushButton#calSeg {{ border: 1px solid {t('border')}; padding: 5px 12px; background: {t('surface')}; color: {t('text')}; }}
QPushButton#calSeg:checked {{ background: {t('selection')}; font-weight: 600; }}
#calList, #calSchedule {{ background: transparent; border: none; outline: none; }}
#calSchedule {{ background: {t('surface')}; }}
#calSchedule::item {{ padding: 6px 8px; }}
""")

    def fill_calendars(self):
        self.cal_list.blockSignals(True)
        self.cal_list.clear()
        for c in self.org.calendar.calendars():
            label = c['name'] + {'subscription': '  (subscribed)', 'caldav': '  (CalDAV)', 'google': '  (Google)',
                                 'microsoft': '  (Microsoft)'}.get(c.get('kind'), '')
            item = QListWidgetItem(theme.dot_icon(c['color'], 14), label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if c.get('visible', True) else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, c['id'])
            item.setData(Qt.ItemDataRole.UserRole + 1, c['color'])
            tip = c['name'] + ' — click to show / hide'
            src = c.get('source') or {}
            if src.get('last_error'):
                tip += '\nLast sync: ' + src['last_error']
            item.setToolTip(tip)
            self.cal_list.addItem(item)
        self.cal_list.blockSignals(False)

    def _toggled(self, item):
        self.org.calendar.update_calendar(item.data(Qt.ItemDataRole.UserRole),
                                          visible=item.checkState() == Qt.CheckState.Checked)
        self.reload()

    def _cal_menu(self, pos):
        item = self.cal_list.itemAt(pos)
        if item is None:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        cal = self.org.calendar.calendar(cid)
        menu = QMenu(self)
        menu.addAction(icon('rename'), 'Rename…', lambda: self._rename(cid))
        colors = menu.addMenu(icon('palette'), 'Colour')
        from ...organizer.calendar import PALETTE
        for c in PALETTE:
            colors.addAction(theme.dot_icon(c), c, lambda col=c: (self.org.calendar.update_calendar(cid, color=col),
                                                                  self.reload()))
        menu.addAction(icon('export'), 'Export as .ics…', lambda: self.export([cid]))
        if cal.get('kind') == 'subscription':
            menu.addAction(icon('refresh'), 'Refresh now', lambda: self.refresh_subscription(cid))
        menu.addSeparator()
        menu.addAction(icon('trash'), 'Remove calendar…', lambda: self._remove(cid))
        menu.exec(self.cal_list.viewport().mapToGlobal(pos))

    def _rename(self, cid):
        cal = self.org.calendar.calendar(cid)
        text, ok = QInputDialog.getText(self, 'Rename calendar', 'Name:', text=cal['name'])
        if ok and text.strip():
            self.org.calendar.update_calendar(cid, name=text.strip())
            self.reload()

    def _remove(self, cid):
        cal = self.org.calendar.calendar(cid)
        n = len(self.org.calendar.events(cid))
        if QMessageBox.question(self, 'Remove calendar', f"Remove “{cal['name']}” and its {n} event(s) from this "
                                'computer? (A subscribed or synchronised calendar stays on its server.)') == \
                QMessageBox.StandardButton.Yes:
            self.org.calendar.delete_calendar(cid)
            self.reload()

    def _add_menu(self):
        menu = QMenu(self)
        menu.addAction(icon('plus'), 'New calendar…', self._new_calendar)
        menu.addAction(icon('link'), 'Subscribe to a URL (iCal / webcal)…', self.subscribe)
        menu.addAction(icon('import'), 'Import an .ics file…', self.import_ics)
        menu.addAction(icon('refresh'), 'Two-way sync (Google, Microsoft, iCloud / CalDAV)…', self.open_settings)
        menu.exec(self.cursor().pos())

    def _new_calendar(self):
        text, ok = QInputDialog.getText(self, 'New calendar', 'Name:')
        if ok and text.strip():
            self.org.calendar.add_calendar(text.strip())
            self.reload()

    # ---- navigation
    def set_view(self, view: str):
        self.view = view if view in self.VIEWS else 'week'
        for k, b in self.view_buttons.items():
            b.setChecked(k == self.view)
        self.stack.setCurrentWidget({'day': self.grid, 'week': self.grid, 'month': self.month,
                                     'schedule': self.schedule}[self.view])
        self.reload()

    def set_date(self, day: dt.date):
        self.date = day
        self.reload()

    def step(self, n: int):
        if self.view == 'day':
            self.date += dt.timedelta(days=n)
        elif self.view == 'week':
            self.date += dt.timedelta(weeks=n)
        elif self.view == 'month':
            m = self.date.month - 1 + n
            self.date = dt.date(self.date.year + m // 12, m % 12 + 1, 1)
        else:
            self.date += dt.timedelta(days=30 * n)
        self.reload()

    def reload(self):
        self.org.calendar.reload()
        self.fill_calendars()
        self.mini.set_date(self.date)
        if self.view in ('day', 'week'):
            start = self.date if self.view == 'day' else week_start(self.date, self.first)
            self.grid.set_range(start, 1 if self.view == 'day' else 7)
            end = start + dt.timedelta(days=0 if self.view == 'day' else 6)
            if self.view == 'day':
                self.title.setText(start.strftime('%A %d %B %Y').replace(' 0', ' '))
            elif start.month == end.month:
                self.title.setText(start.strftime('%B %Y'))
            else:
                self.title.setText(f"{start:%b} – {end:%b %Y}")
        elif self.view == 'month':
            self.month.set_month(self.date)
            self.title.setText(self.date.strftime('%B %Y'))
        else:
            self.schedule.set_start(self.date)
            self.title.setText('From ' + self.date.strftime('%d %B %Y').lstrip('0'))
        m0 = self.date.replace(day=1) - dt.timedelta(days=7)
        busy = set()
        for o in self.org.calendar.occurrences(m0, m0 + dt.timedelta(days=50)):
            busy.add(o['start'].date() if isinstance(o['start'], dt.datetime) else o['start'])
        self.mini.busy = busy
        self.mini.update()

    # ---- actions
    def create(self, start=None, end=None, all_day=False):
        from .event_editor import EventEditor
        dialog = EventEditor(self.org, None, start, end, all_day, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_fields:
            try:
                self.org.create_event(dialog.result_fields)
            except (ValueError, PermissionError) as exc:
                QMessageBox.warning(self, 'Event', str(exc))
            self.reload()

    def _ask_scope(self, verb: str) -> str:
        box = QMessageBox(self)
        box.setWindowTitle(f'{verb.capitalize()} recurring event')
        box.setText(f'{verb.capitalize()} which events?')
        one = box.addButton('This event', QMessageBox.ButtonRole.AcceptRole)
        following = box.addButton('This and following events', QMessageBox.ButtonRole.AcceptRole)
        allb = box.addButton('All events', QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return {one: 'one', following: 'following', allb: 'all'}.get(box.clickedButton(), '')

    def edit(self, o: dict):
        from .event_editor import EventEditor
        ev = self.org.calendar.get(o['uid'])
        if ev is None:
            return
        if o.get('readonly'):
            self.show_popup(o, self.cursor().pos())
            return
        shown = dict(ev)
        if o.get('recurring'):
            shown.update(start=iso(o['start']), end=iso(o['end']), title=o['title'])
        dialog = EventEditor(self.org, shown, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if dialog.deleted:
                self.delete(o)
                return
            fields = dialog.result_fields
            if o.get('recurring'):
                scope = self._ask_scope('change')
                if not scope:
                    return
                if scope == 'one':
                    self.org.calendar.update_occurrence(o['uid'], o['instance'], **{k: fields[k] for k in (
                        'title', 'start', 'end', 'location', 'description', 'color', 'all_day')})
                    self.org.changed('calendar')
                elif scope == 'following':
                    self.org.calendar.split_series(o['uid'], o['instance'], **fields)
                    self.org.changed('calendar')
                else:
                    s0 = parse_time(ev['start'])
                    new_start, new_end = parse_time(fields['start']), parse_time(fields['end'])
                    shift = new_start - o['start']
                    fields['start'] = iso(s0 + shift)
                    fields['end'] = iso(s0 + shift + (new_end - new_start))
                    self.org.update_event(o['uid'], **fields)
            else:
                self.org.update_event(o['uid'], **fields)
        except (ValueError, PermissionError, KeyError) as exc:
            QMessageBox.warning(self, 'Event', str(exc))
        self.reload()

    def delete(self, o: dict):
        if o.get('readonly'):
            return
        if o.get('recurring'):
            scope = self._ask_scope('delete')
            if not scope:
                return
            if scope == 'one':
                self.org.calendar.delete_occurrence(o['uid'], o['instance'])
                self.org.changed('calendar')
            elif scope == 'following':
                from ...organizer import rrule
                ev = self.org.calendar.get(o['uid'])
                rule = rrule.parse(ev['rrule'])
                first = parse_time(o['instance'])
                rule['count'] = None
                rule['until'] = first - (dt.timedelta(seconds=1) if isinstance(first, dt.datetime) else dt.timedelta(days=1))
                self.org.calendar.update(o['uid'], rrule=rrule.to_text(rule))
                self.org.changed('calendar')
            else:
                self.org.delete_event(o['uid'])
        else:
            self.org.delete_event(o['uid'])
        self.reload()

    def move_occurrence(self, o: dict, start, end):
        if o.get('readonly'):
            return
        try:
            if o.get('recurring'):
                scope = self._ask_scope('move')
                if scope == 'one':
                    self.org.calendar.update_occurrence(o['uid'], o['instance'], start=start, end=end)
                    self.org.changed('calendar')
                elif scope in ('all', 'following'):
                    ev = self.org.calendar.get(o['uid'])
                    shift = start - o['start']
                    if scope == 'all':
                        self.org.move_event(o['uid'], parse_time(ev['start']) + shift,
                                            parse_time(ev['start']) + shift + (end - start))
                    else:
                        self.org.calendar.split_series(o['uid'], o['instance'], start=iso(start), end=iso(end))
                        self.org.changed('calendar')
            else:
                self.org.move_event(o['uid'], start, end)
        except (ValueError, PermissionError) as exc:
            QMessageBox.warning(self, 'Event', str(exc))
        self.reload()

    def show_popup(self, o: dict, pos: QPoint):
        popup = EventPopup(self.org, o, self)
        popup.edit.connect(self.edit)
        popup.delete.connect(self.delete)
        popup.done.connect(lambda occ, on: (self.org.set_event_done(occ['uid'], on), self.reload()))
        popup.adjustSize()
        screen = self.screen().availableGeometry()
        x = min(pos.x() + 12, screen.right() - popup.width() - 10)
        y = min(pos.y(), screen.bottom() - popup.height() - 10)
        popup.move(max(screen.left(), x), max(screen.top(), y))
        popup.show()
        self._popup = popup

    def do_search(self):
        q = self.search.text().strip()
        if not q:
            return
        found = self.org.calendar.search(q)
        menu = QMenu(self)
        for o in found[:30]:
            when = o['start'].strftime('%d %b %Y' + ('' if o['all_day'] else ' %H:%M'))
            menu.addAction(theme.dot_icon(o['color']), f"{when}   {o['title']}",
                           lambda occ=o: (self.set_date(occ['start'].date() if isinstance(occ['start'], dt.datetime)
                                                        else occ['start']), self.set_view('day'),
                                          QTimer.singleShot(50, lambda: self.show_popup(occ, self.cursor().pos()))))
        if not found:
            menu.addAction('No event found').setEnabled(False)
        menu.exec(self.search.mapToGlobal(self.search.rect().bottomLeft()))

    def _shortcuts(self):
        def add(seq, slot):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(lambda: None if isinstance(self.focusWidget(), QLineEdit) else slot())
        add('D', lambda: self.set_view('day'))
        add('W', lambda: self.set_view('week'))
        add('M', lambda: self.set_view('month'))
        add('A', lambda: self.set_view('schedule'))
        add('T', lambda: self.set_date(dt.date.today()))
        for k in ('J', 'N'):
            add(k, lambda: self.step(1))
        for k in ('K', 'P'):
            add(k, lambda: self.step(-1))
        add('C', lambda: self.create(None, None, False))
        add('/', lambda: (self.search.setFocus(), self.search.selectAll()))
        add('Delete', lambda: self.delete(self.grid.selected) if self.view in ('day', 'week') and self.grid.selected
            else (self.delete(self.month.selected) if self.view == 'month' and self.month.selected else None))
        add('E', lambda: self.edit(self.grid.selected) if self.grid.selected else None)
        add('Ctrl+W', self.close)

    # ---- settings actions
    def import_ics(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import an .ics file', '', 'Calendar (*.ics *.ical *.ifb)')
        if not path:
            return
        from pathlib import Path
        try:
            text = Path(path).read_text(encoding='utf8', errors='replace')
            cals = [c for c in self.org.calendar.calendars() if not c.get('readonly')]
            names = [f"New calendar “{Path(path).stem}”"] + [c['name'] for c in cals]
            choice, ok = QInputDialog.getItem(self, 'Import', 'Add the events to:', names, 0, False)
            if not ok:
                return
            cid = '' if names.index(choice) == 0 else cals[names.index(choice) - 1]['id']
            result = self.org.calendar.import_ics(text, calendar_id=cid, name=Path(path).stem)
            self.org.changed('calendar')
            QMessageBox.information(self, 'Import', f"{result['added']} event(s) added, {result['updated']} updated.")
        except Exception as exc:
            QMessageBox.warning(self, 'Import', f'The file could not be imported: {exc}')
        self.reload()

    def export(self, ids=None):
        path, _ = QFileDialog.getSaveFileName(self, 'Export as .ics', 'calendar.ics', 'Calendar (*.ics)')
        if path:
            from pathlib import Path
            Path(path).write_text(self.org.calendar.export_ics(ids), encoding='utf8')

    def subscribe(self):
        url, ok = QInputDialog.getText(self, 'Subscribe to a calendar', 'iCal / webcal address (read-only):')
        if not ok or not url.strip():
            return
        from ...organizer import sync
        try:
            cal = sync.subscribe(self.org.calendar, url.strip())
        except ValueError as exc:
            QMessageBox.warning(self, 'Subscribe', str(exc))
            return
        self.refresh_subscription(cal['id'])

    def refresh_subscription(self, cid):
        from ...organizer import sync
        from .cards import _Job
        job = _Job(lambda: sync.refresh_subscription(self.org.calendar, cid), self)
        job.done.connect(lambda r, err: (QMessageBox.warning(self, 'Subscription', err) if err else None,
                                         self.org.changed('calendar'), self.reload()))
        job.start()
        self._job = job

    def open_settings(self):
        from .settings_pages import open_organizer_settings
        open_organizer_settings('calendar', self)
        self.reload()


def _conf() -> dict:
    try:
        from ... import settings as hubsettings
        from ...host import current
        return hubsettings.load(current().data_dir())
    except Exception:
        return {}
