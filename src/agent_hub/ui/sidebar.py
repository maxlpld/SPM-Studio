"""The chat list of the hub, drawn like a calm web-chat sidebar.

Sections (small muted headers): *Running* and *Pinned* when they have chats, **Projects** (with a ``+`` button
for a new project), **Recent chats** (chats outside a project, with relative times) and *Archived*. A project
row has a folder icon in the project's colour, a regular-weight name (elided, full name in the tooltip), a muted
chat count and a chevron to fold it. Hover and selection are soft rounded highlights. Everything is painted by
:class:`SidebarDelegate` with the theme tokens and the SPM Studio line icons (no font symbols).
"""
from __future__ import annotations

from .theme import scale_font

import time

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QTreeWidget

from . import theme
from .svg_icons import icon

ROLE = Qt.ItemDataRole.UserRole                 # (kind, id): section · project · chat
COUNT = Qt.ItemDataRole.UserRole + 1            # muted number on the right (projects, sections)
WHEN = Qt.ItemDataRole.UserRole + 2             # relative time (chats)
COLOR = Qt.ItemDataRole.UserRole + 3            # project colour
STATE = Qt.ItemDataRole.UserRole + 4            # QIcon for a running / waiting / ready chat
ADD = Qt.ItemDataRole.UserRole + 5              # section with a "+" button: what it creates
PROJECT_COLORS = ['#C8673A', '#4C8DF6', '#3BB273', '#8B6CEF', '#E8A33D', '#E5534B', '#0EA5A4', '#9AA0A6']


def relative(ts: float, now: float | None = None) -> str:
    """'now' · '5 min' · '3 h' · 'Yesterday' · 'Mon' · '12 Nov' · '12 Nov 2025'."""
    if not ts:
        return ''
    now = now or time.time()
    d = now - float(ts)
    if d < 60:
        return 'now'
    if d < 3600:
        return f'{int(d // 60)} min'
    lt, ln = time.localtime(ts), time.localtime(now)
    if lt.tm_yday == ln.tm_yday and lt.tm_year == ln.tm_year:
        return f'{int(d // 3600)} h'
    if d < 2 * 86400 and (ln.tm_yday - lt.tm_yday == 1 or (lt.tm_year < ln.tm_year and ln.tm_yday == 1)):
        return 'Yesterday'
    if d < 6 * 86400:
        return time.strftime('%a', lt)
    if lt.tm_year == ln.tm_year:
        return time.strftime('%d %b', lt).lstrip('0')
    return time.strftime('%d %b %Y', lt).lstrip('0')


class SidebarDelegate(QStyledItemDelegate):
    def __init__(self, tree, parent=None):
        super().__init__(parent or tree)
        self.tree = tree

    def sizeHint(self, option, index):
        kind = (index.data(ROLE) or ('', ''))[0]
        h = QFontMetrics(option.font).height()
        if kind == 'section':
            return QSize(10, h + 16 if index.row() else h + 10)
        return QSize(10, h + 14)

    def _plus_rect(self, rect: QRect) -> QRect:
        return QRect(rect.right() - 26, rect.top() + (rect.height() - 22) // 2 + 2, 22, 22)

    def paint(self, p: QPainter, option, index: QModelIndex):
        t = theme.tokens()
        kind, ident = index.data(ROLE) or ('', '')
        rect = QRect(option.rect)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        depth = 1 if index.parent().isValid() else 0
        text_color = QColor(str(t.get('text', '#2A2723')))
        muted = QColor(str(t.get('muted', '#6F6A62')))
        subtle = QColor(str(t.get('subtle', '#9A948A')))
        if kind == 'section':
            f = QFont(option.font)
            scale_font(f, 0.88, 7.0)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(muted)
            top = rect.adjusted(10, 6 if index.row() else 2, -30, 0)
            label = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
            count = index.data(COUNT)
            fm = QFontMetrics(f)
            p.drawText(top, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            if count:
                p.setPen(subtle)
                p.drawText(top.adjusted(fm.horizontalAdvance(label) + 6, 0, 0, 0),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(count))
            if index.data(ADD):
                pr = self._plus_rect(rect)
                if hover:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(str(t.get('surface_alt', '#F1EEE7'))) if not selected else
                               QColor(str(t.get('border', '#E2DDD3'))))
                    p.drawRoundedRect(QRectF(pr), 6, 6)
                icon('plus', str(t.get('muted'))).paint(p, pr.adjusted(3, 3, -3, -3))
            elif index.model().hasChildren(index):
                chevron = 'chevron-down' if self.tree.isExpanded(index) else 'chevron-right'
                icon(chevron, str(t.get('subtle'))).paint(p, QRect(rect.right() - 22, rect.top() +
                                                                   (rect.height() - 14) // 2 + 2, 14, 14))
            p.restore()
            return
        bg = rect.adjusted(4 + depth * 14, 1, -4, -1)
        if selected or hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(str(t.get('selection' if selected else 'surface_alt', '#F1EEE7'))))
            p.drawRoundedRect(QRectF(bg), 7, 7)
        x = bg.left() + 8
        icon_rect = QRect(x, rect.top() + (rect.height() - 16) // 2, 16, 16)
        right = bg.right() - 8
        f = QFont(option.font)
        f.setBold(False)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        fm = QFontMetrics(f)
        small = QFont(f)
        small = scale_font(QFont(f), 0.85)
        sfm = QFontMetrics(small)
        if kind == 'project':
            color = str(index.data(COLOR) or t.get('muted'))
            name = 'folder-open' if self.tree.isExpanded(index) and index.model().hasChildren(index) else 'folder-closed'
            icon(name, color).paint(p, icon_rect)
            x = icon_rect.right() + 9
            count = index.data(COUNT)
            if index.model().hasChildren(index) and (hover or selected):
                chevron = 'chevron-down' if self.tree.isExpanded(index) else 'chevron-right'
                icon(chevron, str(t.get('subtle'))).paint(p, QRect(right - 14, rect.top() + (rect.height() - 14) // 2,
                                                                   14, 14))
                right -= 20
            elif count:
                p.setFont(small)
                p.setPen(subtle)
                cw = sfm.horizontalAdvance(str(count))
                p.drawText(QRect(right - cw, rect.top(), cw, rect.height()), Qt.AlignmentFlag.AlignVCenter, str(count))
                right -= cw + 8
                p.setFont(f)
        else:  # chat
            state = index.data(STATE)
            if state is not None:
                state.paint(p, icon_rect)
                x = icon_rect.right() + 9
            elif index.data(Qt.ItemDataRole.DecorationRole) is not None:
                index.data(Qt.ItemDataRole.DecorationRole).paint(p, icon_rect)
                x = icon_rect.right() + 9
            when = str(index.data(WHEN) or '')
            if when:
                p.setFont(small)
                p.setPen(subtle)
                ww = sfm.horizontalAdvance(when)
                p.drawText(QRect(right - ww, rect.top(), ww, rect.height()), Qt.AlignmentFlag.AlignVCenter, when)
                right -= ww + 10
                p.setFont(f)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or '')
        if index.data(Qt.ItemDataRole.FontRole) is not None and index.data(Qt.ItemDataRole.FontRole).italic():
            f.setItalic(False)
            p.setFont(f)
        p.setPen(text_color if kind == 'project' or selected else QColor(str(t.get('text'))))
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(10, right - x))
        p.drawText(QRect(x, rect.top(), right - x, rect.height()), Qt.AlignmentFlag.AlignVCenter, elided)
        p.restore()

    def editorEvent(self, event, model, option, index):
        kind = (index.data(ROLE) or ('', ''))[0]
        if kind == 'section' and index.data(ADD) and event.type() == QEvent.Type.MouseButtonRelease:
            if self._plus_rect(option.rect).contains(event.position().toPoint()):
                self.tree.addRequested.emit(str(index.data(ADD)))
                return True
        return super().editorEvent(event, model, option, index)


class SidebarTree(QTreeWidget):
    addRequested = Signal(str)                  # 'project'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('hubSidebarTree')
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setMouseTracking(True)
        self.setUniformRowHeights(False)
        self.setAnimated(True)
        self.setExpandsOnDoubleClick(False)
        self.setItemDelegate(SidebarDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            item = self.itemAt(event.pos())
            if item is not None and not item.toolTip(0):
                item.setToolTip(0, item.text(0))
        return super().viewportEvent(event)

    def project_color(self, project: dict, n: int) -> str:
        return project.get('color') or PROJECT_COLORS[n % len(PROJECT_COLORS)]
