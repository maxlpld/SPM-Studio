"""To-do window: smart views (Today, Upcoming, Overdue, Completed, All), lists with colour and icon, tags,
search / sort / filter, drag-and-drop order, natural-language quick add (``call Bob friday 10am #admin !high``),
a detail pane (notes, list, deadline with optional time, start date, priority, tags, repeat, subtasks, links),
and the Notes page of the first to-do version. Tasks with a deadline appear in the calendar (linked both ways)."""
from __future__ import annotations

from ..theme import scale_font

import datetime as dt
import html

from PySide6.QtCore import QDate, QDateTime, QRect, QRectF, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout,
                               QWidget)

from ...organizer.todo import LIST_COLORS, LIST_ICONS, PRIORITIES, TodoStore, due_date, parse_due, parse_quick
from .. import theme
from ..svg_icons import icon, set_icon
from ..widgets import icon_button
from .common import bridge, t

ROLE = Qt.ItemDataRole.UserRole
PRIORITY_COLORS = {3: '#E5534B', 2: '#E8A33D', 1: '#4C8DF6', 0: ''}
SMART = [('today', 'Today', 'today'), ('upcoming', 'Upcoming', 'upcoming'), ('overdue', 'Overdue', 'overdue'),
         ('completed', 'Completed', 'circle-check'), ('all', 'All tasks', 'list'), ('notes', 'Notes', 'notes')]


def due_label(task: dict, today: dt.date | None = None) -> str:
    d = parse_due(task.get('due'))
    if d is None:
        return ''
    today = today or dt.date.today()
    day = d.date() if isinstance(d, dt.datetime) else d
    names = {today: 'Today', today + dt.timedelta(days=1): 'Tomorrow', today - dt.timedelta(days=1): 'Yesterday'}
    text = names.get(day) or (day.strftime('%a') if 0 < (day - today).days < 7 else day.strftime('%d %b').lstrip('0')
                              if day.year == today.year else day.strftime('%d %b %Y').lstrip('0'))
    if isinstance(d, dt.datetime):
        text += d.strftime(' %H:%M')
    return text


class TaskDelegate(QStyledItemDelegate):
    toggled = Signal(str)

    def __init__(self, store: TodoStore, parent=None):
        super().__init__(parent)
        self.store = store

    def sizeHint(self, option, index):
        task = index.data(ROLE) or {}
        h = QFontMetrics(option.font).height()
        extra = task.get('due') or task.get('tags') or task.get('subtasks') or task.get('notes')
        return QSize(10, h * (2 if extra else 1) + 18)

    def check_rect(self, rect: QRect) -> QRect:
        return QRect(rect.left() + 10, rect.top() + 9, 20, 20)

    def paint(self, p: QPainter, option, index):
        task = index.data(ROLE) or {}
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t('selection' if selected else 'surface_alt')))
            p.drawRoundedRect(QRectF(rect), 8, 8)
        done = task.get('done')
        pri = int(task.get('priority') or 0)
        ring = PRIORITY_COLORS.get(pri) or t('subtle')
        cr = self.check_rect(option.rect)
        icon('circle-check' if done else 'circle', t('success') if done else ring).paint(p, cr)
        x = cr.right() + 10
        right = rect.right() - 10
        f = QFont(option.font)
        fm = QFontMetrics(f)
        small = QFont(f)
        small = scale_font(QFont(f), 0.85)
        sfm = QFontMetrics(small)
        lst = self.store.list_(task.get('list', '')) or {}
        if lst:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(lst.get('color', '#999')))
            p.drawEllipse(QRectF(right - 8, rect.top() + 12, 8, 8))
            right -= 16
        if pri:
            icon('flag', PRIORITY_COLORS[pri]).paint(p, QRect(right - 14, rect.top() + 9, 14, 14))
            right -= 20
        links = task.get('links') or {}
        for key, name in (('email', 'mail'), ('event', 'calendar'), ('for_event', 'calendar-day'), ('chat', 'chat'),
                          ('files', 'attach')):
            if links.get(key):
                icon(name, t('subtle')).paint(p, QRect(right - 14, rect.top() + 9, 14, 14))
                right -= 18
        f.setStrikeOut(bool(done))
        p.setFont(f)
        p.setPen(QColor(t('muted') if done else t('text')))
        top = QRect(x, rect.top() + 7, right - x, fm.height() + 4)
        p.drawText(top, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(task.get('title', ''), Qt.TextElideMode.ElideRight, top.width()))
        bits = []
        due = due_label(task)
        p.setFont(small)
        y = top.bottom() + 1
        cx = x
        if due:
            late = TodoStore.overdue(task)
            p.setPen(QColor(t('error') if late else t('accent')))
            icon('repeat' if task.get('rrule') else 'calendar', t('error') if late else t('accent')).paint(
                p, QRect(cx, y + 2, 12, 12))
            cx += 15
            w = sfm.horizontalAdvance(due)
            p.drawText(QRect(cx, y, w + 2, sfm.height() + 4), Qt.AlignmentFlag.AlignVCenter, due)
            cx += w + 12
        subs = task.get('subtasks') or []
        if subs:
            bits.append(f"{sum(1 for s in subs if s['done'])}/{len(subs)}")
        if task.get('tags'):
            bits.append(' '.join('#' + x for x in task['tags']))
        if task.get('notes') and not bits and not due:
            bits.append(task['notes'].splitlines()[0][:80])
        if bits:
            p.setPen(QColor(t('subtle')))
            text = '   '.join(bits)
            p.drawText(QRect(cx, y, right - cx, sfm.height() + 4), Qt.AlignmentFlag.AlignVCenter,
                       sfm.elidedText(text, Qt.TextElideMode.ElideRight, max(10, right - cx)))
        p.restore()

    def editorEvent(self, event, model, option, index):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonRelease and self.check_rect(option.rect).contains(
                event.position().toPoint()):
            task = index.data(ROLE) or {}
            self.toggled.emit(task.get('id', ''))
            return True
        return super().editorEvent(event, model, option, index)


class TaskList(QListWidget):
    reordered = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('todoTasks')
        self.setMouseTracking(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit([self.item(i).data(ROLE)['id'] for i in range(self.count()) if self.item(i).data(ROLE)])


class Details(QScrollArea):
    """Edit one task. Changes are saved as you type (short delay)."""
    changed = Signal()

    def __init__(self, organizer, parent=None):
        super().__init__(parent)
        self.org = organizer
        self.task_id = ''
        self._loading = False
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName('todoDetails')
        box = QWidget()
        self.setWidget(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        self.title = QLineEdit()
        f = self.title.font()
        scale_font(f, 1.25)
        self.title.setFont(f)
        lay.addWidget(self.title)
        form = QFormLayout()
        lay.addLayout(form)
        self.list = QComboBox()
        form.addRow('List', self.list)
        due_row = QHBoxLayout()
        self.has_due = QCheckBox()
        self.due = QDateEdit()
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat('ddd d MMM yyyy')
        self.has_time = QCheckBox('at')
        self.time = QDateTimeEdit()
        self.time.setDisplayFormat('HH:mm')
        for w in (self.has_due, self.due, self.has_time, self.time):
            due_row.addWidget(w)
        due_row.addStretch(1)
        form.addRow('Deadline', due_row)
        start_row = QHBoxLayout()
        self.has_start = QCheckBox()
        self.start = QDateEdit()
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat('ddd d MMM yyyy')
        start_row.addWidget(self.has_start)
        start_row.addWidget(self.start)
        start_row.addStretch(1)
        form.addRow('Start', start_row)
        self.priority = QComboBox()
        for k, v in PRIORITIES.items():
            self.priority.addItem(icon('flag', PRIORITY_COLORS[k]) if k else icon('flag', t('subtle')), v, k)
        form.addRow('Priority', self.priority)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText('#admin #lab')
        form.addRow('Tags', self.tags)
        self.repeat = QComboBox()
        for label, rule in (('Does not repeat', ''), ('Every day', 'FREQ=DAILY'), ('Every week', 'FREQ=WEEKLY'),
                            ('Every weekday', 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'), ('Every month', 'FREQ=MONTHLY'),
                            ('Every year', 'FREQ=YEARLY')):
            self.repeat.addItem(label, rule)
        form.addRow('Repeat', self.repeat)
        lay.addWidget(QLabel('<b>Subtasks</b>'))
        self.subs = QListWidget()
        self.subs.setObjectName('todoSubs')
        self.subs.setMaximumHeight(150)
        lay.addWidget(self.subs)
        self.new_sub = QLineEdit()
        self.new_sub.setPlaceholderText('Add a subtask and press Enter')
        lay.addWidget(self.new_sub)
        lay.addWidget(QLabel('<b>Notes</b>'))
        self.notes = QPlainTextEdit()
        self.notes.setMinimumHeight(100)
        lay.addWidget(self.notes)
        lay.addWidget(QLabel('<b>Links</b>'))
        self.links = QLabel('')
        self.links.setWordWrap(True)
        self.links.setTextFormat(Qt.TextFormat.RichText)
        self.links.linkActivated.connect(self._link)
        lay.addWidget(self.links)
        row = QHBoxLayout()
        add_file = QPushButton('Link a file…')
        set_icon(add_file, 'attach')
        add_file.clicked.connect(self._add_file)
        delete = QPushButton('Delete task')
        set_icon(delete, 'trash')
        delete.clicked.connect(self._delete)
        row.addWidget(add_file)
        row.addStretch(1)
        row.addWidget(delete)
        lay.addLayout(row)
        lay.addStretch(1)
        for combo in (self.list, self.priority, self.repeat):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.save)
        for w in (self.title, self.tags):
            w.textEdited.connect(lambda _t: self._timer.start())
        self.notes.textChanged.connect(lambda: self._timer.start() if not self._loading else None)
        for w in (self.list, self.priority, self.repeat):
            w.activated.connect(lambda _i: self.save())
        for w in (self.has_due, self.has_time, self.has_start):
            w.toggled.connect(lambda _on: self.save())
        for w in (self.due, self.start):
            w.dateChanged.connect(lambda _d: self.save() if not self._loading else None)
        self.time.timeChanged.connect(lambda _t: self.save() if not self._loading else None)
        self.new_sub.returnPressed.connect(self._add_sub)
        self.subs.itemChanged.connect(self._sub_changed)
        self.setEnabled(False)

    def show_task(self, tid: str):
        task = self.org.todo.get(tid) if tid else None
        self.task_id = tid if task else ''
        self.setEnabled(task is not None)
        if task is None:
            return
        self._loading = True
        self.title.setText(task['title'])
        self.list.clear()
        for l in self.org.todo.lists():
            self.list.addItem(icon(l.get('icon', 'list'), l['color']), l['name'], l['id'])
        self.list.setCurrentIndex(max(0, self.list.findData(task['list'])))
        due = parse_due(task.get('due'))
        self.has_due.setChecked(due is not None)
        day = (due.date() if isinstance(due, dt.datetime) else due) or dt.date.today()
        self.due.setDate(QDate(day.year, day.month, day.day))
        self.has_time.setChecked(isinstance(due, dt.datetime))
        tm = due.time() if isinstance(due, dt.datetime) else dt.time(9)
        self.time.setTime(QTime(tm.hour, tm.minute))
        start = parse_due(task.get('start'))
        self.has_start.setChecked(start is not None)
        sd = start or dt.date.today()
        self.start.setDate(QDate(sd.year, sd.month, sd.day))
        self.priority.setCurrentIndex(self.priority.findData(task['priority']))
        self.tags.setText(' '.join('#' + x for x in task['tags']))
        i = self.repeat.findData(task.get('rrule', ''))
        if i < 0:
            from ...organizer import rrule
            self.repeat.addItem(rrule.describe(task['rrule']), task['rrule'])
            i = self.repeat.count() - 1
        self.repeat.setCurrentIndex(i)
        self.subs.clear()
        for s in task.get('subtasks', []):
            it = QListWidgetItem(s['title'])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            it.setCheckState(Qt.CheckState.Checked if s['done'] else Qt.CheckState.Unchecked)
            it.setData(ROLE, s['id'])
            self.subs.addItem(it)
        self.notes.setPlainText(task.get('notes', ''))
        self._show_links(task)
        self._loading = False

    def _show_links(self, task):
        links = task.get('links') or {}
        rows = []
        if links.get('event'):
            ev = self.org.calendar.get(links['event'])
            if ev:
                rows.append(f"<a href='event:{links['event']}'>In the calendar: {html.escape(ev['start'][:16].replace('T', ' '))}</a>")
        if links.get('for_event'):
            ev = self.org.calendar.get(links['for_event'])
            if ev:
                rows.append(f"<a href='event:{links['for_event']}'>{html.escape(links.get('purpose', 'prep').capitalize())} "
                            f"for “{html.escape(ev['title'])}”</a>")
        if links.get('email'):
            rows.append('From an e-mail: ' + html.escape(str(links['email'])[:80]))
        if links.get('chat'):
            rows.append(f"<a href='chat:{links['chat']}'>From a chat</a>")
        for f in links.get('files', []):
            rows.append(f"<a href='file:{html.escape(f)}'>{html.escape(f.rsplit('/', 1)[-1])}</a>")
        self.links.setText('<br>'.join(rows) or "<span style='color:gray'>No links. A deadline puts the task in the "
                                                 'calendar.</span>')

    def _link(self, href: str):
        kind, _, value = href.partition(':')
        if kind == 'event':
            from .windows import open_window
            open_window('calendar', value, parent=self.window())
        elif kind == 'file':
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(value))

    def save(self):
        if self._loading or not self.task_id:
            return
        due = ''
        if self.has_due.isChecked():
            d = self.due.date()
            day = dt.date(d.year(), d.month(), d.day())
            if self.has_time.isChecked():
                tm = self.time.time()
                due = dt.datetime.combine(day, dt.time(tm.hour(), tm.minute())).strftime('%Y-%m-%dT%H:%M')
            else:
                due = day.isoformat()
        start = ''
        if self.has_start.isChecked():
            d = self.start.date()
            start = dt.date(d.year(), d.month(), d.day()).isoformat()
        self.due.setEnabled(self.has_due.isChecked())
        self.has_time.setEnabled(self.has_due.isChecked())
        self.time.setEnabled(self.has_due.isChecked() and self.has_time.isChecked())
        self.start.setEnabled(self.has_start.isChecked())
        try:
            self.org.update_task(self.task_id, title=self.title.text().strip() or 'Task', list=self.list.currentData(),
                                 due=due, start=start, priority=self.priority.currentData(),
                                 tags=self.tags.text().replace('#', ' ').split(), rrule=self.repeat.currentData() or '',
                                 notes=self.notes.toPlainText())
        except (KeyError, ValueError):
            return
        self.changed.emit()

    def _add_sub(self):
        text = self.new_sub.text().strip()
        task = self.org.todo.get(self.task_id)
        if not text or task is None:
            return
        self.org.update_task(self.task_id, subtasks=list(task['subtasks']) + [{'title': text}])
        self.new_sub.clear()
        self.show_task(self.task_id)
        self.changed.emit()

    def _sub_changed(self, item):
        if self._loading:
            return
        task = self.org.todo.get(self.task_id)
        subs = []
        for i in range(self.subs.count()):
            it = self.subs.item(i)
            if it.text().strip():
                subs.append({'id': it.data(ROLE), 'title': it.text(), 'done': it.checkState() == Qt.CheckState.Checked})
        self.org.update_task(self.task_id, subtasks=subs)
        self.changed.emit()

    def _add_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, 'Link a file')
        task = self.org.todo.get(self.task_id)
        if path and task:
            links = dict(task.get('links') or {})
            links['files'] = list(links.get('files', [])) + [path]
            self.org.update_task(self.task_id, links=links)
            self.show_task(self.task_id)

    def _delete(self):
        task = self.org.todo.get(self.task_id)
        if task and QMessageBox.question(self, 'Delete task', f"Delete “{task['title']}”?") == \
                QMessageBox.StandardButton.Yes:
            self.org.delete_task(self.task_id)
            self.show_task('')
            self.changed.emit()


class TodoWindow(QMainWindow):
    def __init__(self, organizer=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        from ...organizer import shared
        self.org = organizer or shared()
        self.bridge = bridge(self.org)
        self.setObjectName('AgentHubTodo')
        self.setWindowTitle('To-do')
        self.resize(1120, 760)
        self.view = 'today'
        self.list_id = ''
        self.tag = ''
        root = QWidget()
        root.setObjectName('todoRoot')
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.side = self._side()
        split.addWidget(self.side)
        split.addWidget(self._center())
        self.details = Details(self.org)
        self.details.changed.connect(self._refresh_soon)
        split.addWidget(self.details)
        split.setSizes([220, 540, 380])
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(True)
        split.setMinimumWidth(300)                 # explicit: the window may narrow into its compact form
        self.split = split
        lay.addWidget(split)
        self.compact_mode = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.refresh)
        self.bridge.todoChanged.connect(self._refresh_soon)
        self._shortcuts()
        self.apply_theme()
        self.select_view('today')

    def _side(self):
        side = QWidget()
        side.setObjectName('todoSide')
        side.setMinimumWidth(150)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(10, 12, 8, 10)
        lay.setSpacing(6)
        head = QLabel('To-do')
        f = head.font()
        scale_font(f, 1.3)
        head.setFont(f)
        lay.addWidget(head)
        self.smart = QListWidget()
        self.smart.setObjectName('todoNav')
        for key, label, ic in SMART:
            item = QListWidgetItem(icon(ic, t('muted')), label)
            item.setData(ROLE, ('view', key))
            self.smart.addItem(item)
        self.smart.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.smart.setFixedHeight(sum(self.smart.sizeHintForRow(i) for i in range(self.smart.count())) +
                                  2 * self.smart.frameWidth() + 8 + 4 * len(SMART))
        self.smart.itemClicked.connect(lambda i: self.select_view(i.data(ROLE)[1]))
        lay.addWidget(self.smart)
        row = QHBoxLayout()
        lab = QLabel('Lists')
        lab.setObjectName('todoSection')
        row.addWidget(lab)
        row.addStretch(1)
        add = icon_button('plus', 'New list')
        add.clicked.connect(self.new_list)
        row.addWidget(add)
        lay.addLayout(row)
        self.lists = QListWidget()
        self.lists.setObjectName('todoNav')
        self.lists.itemClicked.connect(lambda i: self.select_list(i.data(ROLE)[1]))
        self.lists.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lists.customContextMenuRequested.connect(self._list_menu)
        lay.addWidget(self.lists, 1)
        lab = QLabel('Tags')
        lab.setObjectName('todoSection')
        lay.addWidget(lab)
        self.tags = QListWidget()
        self.tags.setObjectName('todoNav')
        self.tags.setMaximumHeight(140)
        self.tags.itemClicked.connect(lambda i: self.select_tag(i.data(ROLE)[1]))
        lay.addWidget(self.tags)
        return side

    def _center(self):
        box = QWidget()
        box.setObjectName('todoCenter')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        row = QHBoxLayout()
        self.nav_combo = QComboBox()                # compact window: the views as a menu
        for key, label, ic in SMART:
            self.nav_combo.addItem(icon(ic, t('muted')), label, key)
        self.nav_combo.activated.connect(lambda _i: self.select_view(self.nav_combo.currentData()))
        self.nav_combo.hide()
        row.addWidget(self.nav_combo)
        self.heading = QLabel('Today')
        f = self.heading.font()
        scale_font(f, 1.45)
        f.setWeight(QFont.Weight.DemiBold)
        self.heading.setFont(f)
        row.addWidget(self.heading)
        row.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName('hubSearch')
        self.search.setPlaceholderText('Search (Ctrl+F)')
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(220)
        self.search.setMinimumWidth(90)
        self.search.textChanged.connect(self._refresh_soon)
        row.addWidget(self.search)
        self.sort = QComboBox()
        for label, key in (('My order', 'manual'), ('Deadline', 'due'), ('Priority', 'priority'), ('Title', 'title'),
                           ('Newest', 'created')):
            self.sort.addItem(icon('sort', t('muted')), label, key)
        self.sort.setToolTip('Sort (drag and drop works in “My order”)')
        self.sort.activated.connect(lambda _i: self.refresh())
        row.addWidget(self.sort)
        self.pri_filter = QComboBox()
        self.pri_filter.addItem(icon('filter', t('muted')), 'Any priority', -1)
        for k in (3, 2, 1):
            self.pri_filter.addItem(icon('flag', PRIORITY_COLORS[k]), PRIORITIES[k] + ' only', k)
        self.pri_filter.activated.connect(lambda _i: self.refresh())
        row.addWidget(self.pri_filter)
        self.more = icon_button('more', 'More: ask the assistant, keep on top, done tasks, erase all')
        self.more.setPopupMode(self.more.ToolButtonPopupMode.InstantPopup)
        self.more.setMenu(self._more_menu())
        row.addWidget(self.more)
        lay.addLayout(row)
        self.quick = QLineEdit()
        self.quick.setObjectName('todoQuick')
        self.quick.setPlaceholderText('Add a task — e.g. “call Bob friday 10am #admin !high”  (Enter)')
        self.quick.returnPressed.connect(self.quick_add)
        self.quick.textChanged.connect(self._preview)
        lay.addWidget(self.quick)
        self.preview = QLabel('')
        self.preview.setObjectName('hubHint')
        lay.addWidget(self.preview)
        self.stack = QStackedWidget()
        self.tasks = TaskList()
        self.delegate = TaskDelegate(self.org.todo, self.tasks)
        self.delegate.toggled.connect(self.toggle)
        self.tasks.setItemDelegate(self.delegate)
        self.tasks.currentItemChanged.connect(lambda cur, _p: self.details.show_task(
            (cur.data(ROLE) or {}).get('id', '') if cur else ''))
        self.tasks.reordered.connect(self._reordered)
        self.tasks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tasks.customContextMenuRequested.connect(self._task_menu)
        self.empty = QLabel('')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName('hubHint')
        self.notes = QPlainTextEdit()
        self.notes.setObjectName('todoNotes')
        self.notes.setPlaceholderText('Notes (saved automatically)')
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(600)
        self._notes_timer.timeout.connect(lambda: self.org.todo.set_notes(self.notes.toPlainText()))
        self.notes.textChanged.connect(self._notes_timer.start)
        for w in (self.tasks, self.empty, self.notes):
            self.stack.addWidget(w)
        lay.addWidget(self.stack, 1)
        return box

    def apply_theme(self):
        self.setStyleSheet(theme.stylesheet() + f"""
#todoRoot, #todoSide, #todoCenter {{ background: {t('window')}; color: {t('text')}; }}
#todoSide {{ border-right: 1px solid {t('border')}; }}
#todoDetails {{ background: {t('surface')}; border: none; border-left: 1px solid {t('border')}; }}
#todoDetails > QWidget > QWidget {{ background: {t('surface')}; }}
#todoSection {{ color: {t('muted')}; font-weight: 600; margin-top: 6px; }}
#todoNav {{ background: transparent; border: none; outline: none; }}
#todoNav::item {{ padding: 6px 6px; border-radius: 7px; }}
#todoNav::item:selected {{ background: {t('selection')}; color: {t('text')}; }}
#todoNav::item:hover:!selected {{ background: {t('surface_alt')}; }}
#todoTasks {{ background: {t('surface')}; border: 1px solid {t('border')}; border-radius: 10px; outline: none; }}
#todoTasks::item:selected {{ background: transparent; }}
#todoQuick {{ border: 1px solid {t('border')}; border-radius: 10px; padding: 8px 12px; background: {t('surface')}; }}
#todoNotes {{ background: {t('surface')}; border: 1px solid {t('border')}; border-radius: 10px; padding: 8px; }}
""")

    # ---- navigation
    def fill_side(self):
        counts = self.org.todo.counts()
        for i in range(self.smart.count()):
            item = self.smart.item(i)
            key = item.data(ROLE)[1]
            label = dict((k, l) for k, l, _i in SMART)[key]
            item.setText(label + (f'   {counts[key]}' if counts.get(key) else ''))
            if key == 'overdue':
                item.setForeground(QColor(t('error') if counts.get('overdue') else t('text')))
        self.lists.clear()
        for l in self.org.todo.lists():
            n = len(self.org.todo.tasks(l['id'], include_done=False))
            item = QListWidgetItem(icon(l.get('icon', 'list'), l['color']), l['name'] + (f'   {n}' if n else ''))
            item.setData(ROLE, ('list', l['id']))
            self.lists.addItem(item)
            if self.list_id == l['id']:
                item.setSelected(True)
        self.tags.clear()
        for tag in self.org.todo.tags():
            item = QListWidgetItem(icon('tag', t('muted')), '#' + tag)
            item.setData(ROLE, ('tag', tag))
            self.tags.addItem(item)

    def select_view(self, key: str):
        self.view, self.list_id, self.tag = key, '', ''
        i = self.nav_combo.findData(key)
        if i >= 0:
            self.nav_combo.setCurrentIndex(i)
        self.lists.clearSelection()
        self.tags.clearSelection()
        for i in range(self.smart.count()):
            self.smart.item(i).setSelected(self.smart.item(i).data(ROLE)[1] == key)
        self.refresh()

    def select_list(self, lid: str):
        self.view, self.list_id, self.tag = 'all', lid, ''
        self.smart.clearSelection()
        self.tags.clearSelection()
        self.refresh()

    def select_tag(self, tag: str):
        self.view, self.list_id, self.tag = 'all', '', tag
        self.smart.clearSelection()
        self.lists.clearSelection()
        self.refresh()

    def _refresh_soon(self):
        self._timer.start()

    def refresh(self):
        self.org.todo.reload()
        self.fill_side()
        if self.view == 'notes':
            self.heading.setText('Notes')
            if not self.notes.hasFocus():
                self.notes.blockSignals(True)
                self.notes.setPlainText(self.org.todo.notes())
                self.notes.blockSignals(False)
            self.stack.setCurrentWidget(self.notes)
            return
        lst = self.org.todo.list_(self.list_id) if self.list_id else None
        self.heading.setText(lst['name'] if lst else ('#' + self.tag if self.tag else
                                                       dict((k, l) for k, l, _i in SMART)[self.view]))
        view = self.view if self.view != 'all' else ('all' if _conf().get('todo_show_completed', True) else 'open')
        tasks = self.org.todo.view(view, query=self.search.text(), tag=self.tag, sort=self.sort.currentData(),
                                   list_id=self.list_id)
        pri = self.pri_filter.currentData()
        if pri is not None and pri >= 0:
            tasks = [x for x in tasks if x['priority'] == pri]
        current = (self.tasks.currentItem().data(ROLE) or {}).get('id') if self.tasks.currentItem() else ''
        self.tasks.blockSignals(True)
        self.tasks.clear()
        for task in tasks:
            item = QListWidgetItem(task['title'])
            item.setData(ROLE, task)
            item.setToolTip(task['title'] + (f"\n{task['notes'][:300]}" if task.get('notes') else ''))
            self.tasks.addItem(item)
            if task['id'] == current:
                self.tasks.setCurrentItem(item)
        self.tasks.blockSignals(False)
        manual = self.sort.currentData() == 'manual'
        self.tasks.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove if manual else
                                   QAbstractItemView.DragDropMode.NoDragDrop)
        if tasks:
            self.stack.setCurrentWidget(self.tasks)
        else:
            self.empty.setText({'today': 'Nothing due today.', 'overdue': 'Nothing overdue.',
                                'upcoming': 'Nothing planned.', 'completed': 'No completed task yet.'}.get(
                self.view, 'No task here. Add one above.'))
            self.stack.setCurrentWidget(self.empty)
        if current and self.details.task_id == current:
            self.details.show_task(current) if not self.details.isAncestorOf(self.focusWidget() or self) else None

    # ---- the "more" menu (assistant, keep on top, done tasks, erase) — kept from the first to-do window
    def _more_menu(self):
        menu = QMenu(self)
        ask = menu.addMenu(icon('ai'), 'Ask the assistant')
        ask.addAction(icon('run'), 'Do the selected task(s)', lambda: self.ask_tasks('selected'))
        ask.addAction(icon('checklist'), 'Plan the open tasks', lambda: self.ask_tasks('plan'))
        ask.addAction(icon('run'), 'Do the open tasks, one after the other', lambda: self.ask_tasks('all'))
        write = ask.addMenu(icon('notes'), 'Write from my notes and finished tasks')
        write.addAction('A short summary (in the chat)', lambda: self.ask_writing(
            'a concise summary of these notes, in the chat (key results, open questions, next steps)'))
        try:
            from ...host import current
            for label, what in current().todo_writing_actions() or []:
                write.addAction(label, lambda w=what: self.ask_writing(w))
        except Exception:
            pass
        menu.addSeparator()
        self.pin_action = menu.addAction(icon('pin'), 'Keep on top', self.set_pinned)
        self.pin_action.setCheckable(True)
        done = menu.addMenu(icon('circle-check'), 'Done tasks in lists')
        for label, key in (('Crossed out', 'strike'), ('Hidden', 'hide')):
            act = done.addAction(label, lambda k=key: self._done_style(k))
            act.setCheckable(True)
            act.setChecked(_conf().get('todo_show_completed', True) == (key == 'strike'))
        menu.addSeparator()
        menu.addAction(icon('trash'), 'Erase all…', self.erase_all)
        return menu

    def set_pinned(self, on: bool | None = None):
        on = self.pin_action.isChecked() if on is None else on
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        self.show()

    def _done_style(self, key: str):
        try:
            from ... import settings as hubsettings
            from ...host import current
            root = current().data_dir()
            conf = hubsettings.load(root)
            conf['todo_show_completed'] = key == 'strike'
            hubsettings.save(root, conf)
        except Exception:
            pass
        self.refresh()

    def erase_all(self):
        if QMessageBox.question(self, 'Erase all', 'Remove every task and the notes? A copy is kept in the to-do '
                                'folder first.') == QMessageBox.StandardButton.Yes:
            copy = self.org.todo.erase_all()
            self.org.changed('todo')
            self.org.changed('calendar')
            if copy is not None:
                QMessageBox.information(self, 'Erase all', f'A copy was kept: {copy}')
            self.refresh()

    def _ask(self, text: str) -> bool:
        from ...host import current
        try:
            if current().ask_assistant(text, True):
                return True
        except Exception:
            pass
        from .settings_pages import _find_hub
        hub = _find_hub(self)
        if hub is None:
            QMessageBox.information(self, 'Assistant', 'Open the AI assistant first.')
            return False
        chat = hub.new_chat()
        panel = hub.panels.get(chat['id'])
        if panel is not None:
            panel.input.setPlainText(text)
            panel.send()
        return True

    def _listing(self, tasks) -> str:
        lines = []
        for t in tasks:
            lines.append(f"- {t['title']} (to-do id {t['id']})" + (f", due {t['due'].replace('T', ' ')}"
                                                                   if t.get('due') else ''))
            for line in (t.get('notes') or '').strip().splitlines():
                lines.append('    ' + line)
        return '\n'.join(lines)

    def ask_tasks(self, which: str):
        if which == 'selected':
            tasks = [i.data(ROLE) for i in self.tasks.selectedItems() if i.data(ROLE)]
            if not tasks:
                QMessageBox.information(self, 'Assistant', 'Click a task first.')
                return
            intro = 'Please do these tasks from my to-do list:'
        else:
            tasks = self.org.todo.view('open', sort='due')
            if not tasks:
                QMessageBox.information(self, 'Assistant', 'There is no open task.')
                return
            intro = ('Here are the open tasks of my to-do list. Make a short plan (order, what you need from me, '
                     'what you will create) and ask me before changing anything:' if which == 'plan' else
                     'Please do the open tasks of my to-do list, one after the other:')
        text = (f'{intro}\n\n{self._listing(tasks)}\n\nThe notes under each task say what I need. Ask me if '
                'something essential is missing.' + ('' if which == 'plan' else
                                                     ' When a task is finished, mark it done (todo.complete) and add '
                                                     'what you did and where the result is to its notes.'))
        self._ask(text)

    def ask_writing(self, what: str):
        notes = self.org.todo.notes().strip()
        done = self._listing(self.org.todo.view('completed'))
        if not notes and not done:
            QMessageBox.information(self, 'Assistant', 'Write some notes first (Notes).')
            return
        self._ask(f'Please write {what}, based on my notes and finished tasks below. Keep my numbers and '
                  f'observations exactly; say what is missing.\n\n### Notes\n{notes or "(none)"}\n\n'
                  f'### Finished tasks\n{done or "(none)"}')

    # ---- actions
    def _preview(self, text):
        if not text.strip():
            self.preview.setText('')
            return
        q = parse_quick(text)
        bits = [f"“{q['title']}”"]
        if q['due']:
            bits.append('due ' + due_label({'due': q['due']}))
        if q['rrule']:
            from ...organizer import rrule
            bits.append(rrule.describe(q['rrule']).lower())
        if q['tags']:
            bits.append(' '.join('#' + x for x in q['tags']))
        if q['priority']:
            bits.append(PRIORITIES[q['priority']].lower() + ' priority')
        if q['list_name']:
            bits.append('in ' + q['list_name'])
        self.preview.setText(' · '.join(bits))

    def quick_add(self):
        text = self.quick.text().strip()
        if not text:
            return
        q = parse_quick(text)
        fields = {'title': q['title'], 'due': q['due'], 'tags': q['tags'], 'priority': q['priority'],
                  'rrule': q['rrule']}
        lst = self.org.todo.list_by_name(q['list_name']) if q['list_name'] else None
        import re as _re
        prefix = _re.match(r'\s*([A-Za-z][\w -]{0,30}?)\s*:\s*(.+)$', fields['title'])
        if lst is None and prefix:                 # "Analysis: fit the CPD" (first to-do version) → that list
            from ...organizer.todo import OLD_CATEGORY_ICONS
            name = prefix.group(1).strip()
            lst = self.org.todo.list_by_name(name)
            if lst is None and name.capitalize() in OLD_CATEGORY_ICONS:
                lst = self.org.todo.add_list(name.capitalize(), '', OLD_CATEGORY_ICONS[name.capitalize()])
            if lst is not None:
                fields['title'] = prefix.group(2).strip()
        if lst is None and self.list_id:
            lst = self.org.todo.list_(self.list_id)
        if lst is not None:
            fields['list'] = lst['id']
        if self.tag and self.tag not in fields['tags']:
            fields['tags'] = fields['tags'] + [self.tag]
        if self.view == 'today' and not fields['due']:
            fields['due'] = dt.date.today().isoformat()
        task = self.org.add_task(fields)
        self.quick.clear()
        self.refresh()
        for i in range(self.tasks.count()):
            if (self.tasks.item(i).data(ROLE) or {}).get('id') == task['id']:
                self.tasks.setCurrentRow(i)

    def toggle(self, tid: str):
        task = self.org.todo.get(tid)
        if task is not None:
            self.org.complete_task(tid, not task['done'])
            self.refresh()

    def _reordered(self, ids):
        self.org.todo.reorder(ids)

    def new_list(self):
        name, ok = QInputDialog.getText(self, 'New list', 'Name:')
        if ok and name.strip():
            lst = self.org.todo.add_list(name.strip())
            self.select_list(lst['id'])

    def _list_menu(self, pos):
        item = self.lists.itemAt(pos)
        if item is None:
            return
        lid = item.data(ROLE)[1]
        lst = self.org.todo.list_(lid)
        menu = QMenu(self)
        menu.addAction(icon('rename'), 'Rename…', lambda: self._rename_list(lid))
        colors = menu.addMenu(icon('palette'), 'Colour')
        for c in LIST_COLORS:
            colors.addAction(theme.dot_icon(c), c, lambda col=c: (self.org.todo.update_list(lid, color=col),
                                                                  self.refresh()))
        icons = menu.addMenu(icon('star'), 'Icon')
        for name in LIST_ICONS:
            icons.addAction(icon(name, lst['color']), name.capitalize(),
                            lambda n=name: (self.org.todo.update_list(lid, icon=n), self.refresh()))
        menu.addSeparator()
        menu.addAction(icon('trash'), 'Delete list…', lambda: self._delete_list(lid))
        menu.exec(self.lists.viewport().mapToGlobal(pos))

    def _rename_list(self, lid):
        lst = self.org.todo.list_(lid)
        name, ok = QInputDialog.getText(self, 'Rename list', 'Name:', text=lst['name'])
        if ok and name.strip():
            self.org.todo.update_list(lid, name=name.strip())
            self.refresh()

    def _delete_list(self, lid):
        lst = self.org.todo.list_(lid)
        if QMessageBox.question(self, 'Delete list', f"Delete the list “{lst['name']}”? Its tasks move to the "
                                'inbox (nothing is deleted with it).') == QMessageBox.StandardButton.Yes:
            try:
                self.org.todo.delete_list(lid)
            except ValueError as exc:
                QMessageBox.warning(self, 'Delete list', str(exc))
            self.select_view('all')

    def _task_menu(self, pos):
        item = self.tasks.itemAt(pos)
        if item is None:
            return
        task = item.data(ROLE)
        menu = QMenu(self)
        menu.addAction(icon('circle-check'), 'Mark not done' if task['done'] else 'Mark done',
                       lambda: self.toggle(task['id']))
        due = menu.addMenu(icon('calendar'), 'Deadline')
        today = dt.date.today()
        for label, day in (('Today', today), ('Tomorrow', today + dt.timedelta(days=1)),
                           ('Next week', today + dt.timedelta(days=7 - today.weekday())), ('No deadline', None)):
            due.addAction(label, lambda d=day: (self.org.update_task(task['id'], due=d.isoformat() if d else ''),
                                                self.refresh()))
        pri = menu.addMenu(icon('flag'), 'Priority')
        for k, v in PRIORITIES.items():
            pri.addAction(icon('flag', PRIORITY_COLORS[k] or t('subtle')), v,
                          lambda p=k: (self.org.update_task(task['id'], priority=p), self.refresh()))
        move = menu.addMenu(icon('folder'), 'Move to list')
        for l in self.org.todo.lists():
            move.addAction(icon(l.get('icon', 'list'), l['color']), l['name'],
                           lambda lid=l['id']: (self.org.update_task(task['id'], list=lid), self.refresh()))
        menu.addSeparator()
        menu.addAction(icon('trash'), 'Delete', lambda: (self.org.delete_task(task['id']), self.refresh()))
        menu.exec(self.tasks.viewport().mapToGlobal(pos))

    def focus_task(self, tid: str):
        task = self.org.todo.get(tid)
        if task is None:
            return
        self.select_list(task['list'])
        for i in range(self.tasks.count()):
            if (self.tasks.item(i).data(ROLE) or {}).get('id') == tid:
                self.tasks.setCurrentRow(i)

    def _shortcuts(self):
        def add(seq, slot):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)
        add('Ctrl+N', lambda: self.quick.setFocus())
        add('Ctrl+F', lambda: (self.search.setFocus(), self.search.selectAll()))
        add('Ctrl+1', lambda: self.select_view('today'))
        add('Ctrl+2', lambda: self.select_view('upcoming'))
        add('Ctrl+3', lambda: self.select_view('overdue'))
        add('Ctrl+4', lambda: self.select_view('completed'))
        add('Ctrl+W', self.close)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        compact = self.width() < 640                # a small "post-it" window in a corner
        if compact != self.compact_mode:
            self.compact_mode = compact
            self.side.setVisible(not compact)
            self.details.setVisible(not compact)
            self.nav_combo.setVisible(compact)
            self.heading.setVisible(not compact)
            self.sort.setVisible(not compact)
            self.pri_filter.setVisible(not compact)

    def keyPressEvent(self, e):
        if self.tasks.hasFocus() and self.tasks.currentItem() is not None:
            task = self.tasks.currentItem().data(ROLE)
            if e.key() == Qt.Key.Key_Space:
                self.toggle(task['id'])
                return
            if e.key() == Qt.Key.Key_Delete:
                self.org.delete_task(task['id'])
                self.refresh()
                return
        super().keyPressEvent(e)


def _conf() -> dict:
    try:
        from ... import settings as hubsettings
        from ...host import current
        return hubsettings.load(current().data_dir())
    except Exception:
        return {}
