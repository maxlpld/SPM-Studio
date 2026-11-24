"""To-do list & notes window, connected to the assistant (v0.0.12; compact Apple-like redesign in v0.0.19)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox, QPushButton,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QLabel, QTabWidget, QFrame,
                               QToolButton, QMenu, QAbstractItemView, QMessageBox)

from spm_studio.documents import todo as model, settings as doc_settings

DONE_LABELS = (('crossed out', 'strike'), ('normal', 'plain'), ('hidden', 'hide'))
EMPTY_HINT = 'No tasks yet.\nType one above and press Enter.'      # v0.0.18: only the essential


POST_IT_SIZE = (380, 560)          # v0.0.19: a small window to keep in a corner, like a digital post-it


def _todo_qss(t: dict) -> str:
    """Apple-like look of the to-do window, from the colours of the current theme (v0.0.19)."""
    return f"""
QMainWindow#TodoWindowV0012, QWidget#TodoCentralV0019 {{ background: {t['background']}; }}
QLabel#TodoTitleV0019 {{ font-size: 22px; font-weight: 700; letter-spacing: -0.5px; color: {t['foreground']}; }}
QLabel#TodoCountV0019 {{ color: {t['muted']}; font-size: 12px; }}
QToolButton#TodoPinV0019, QToolButton#TodoMoreV0019 {{ border: 0; border-radius: 14px; min-width: 28px;
    min-height: 28px; background: transparent; color: {t['muted']}; font-size: 14px; }}
QToolButton#TodoPinV0019:hover, QToolButton#TodoMoreV0019:hover {{ background: {t['hover']}; }}
QToolButton#TodoPinV0019:checked {{ background: {t['accent_soft']}; color: {t['foreground']}; }}
QToolButton#TodoMoreV0019::menu-indicator {{ image: none; width: 0; }}
QFrame#TodoSegmentsV0019 {{ background: {t['surface']}; border-radius: 9px; }}
QPushButton[todoSegment="true"] {{ border: 0; border-radius: 7px; padding: 4px 10px; background: transparent;
    color: {t['muted']}; font-weight: 600; min-width: 0; }}
QPushButton[todoSegment="true"]:checked {{ background: {t['raised']}; color: {t['foreground']};
    border: 1px solid {t['border']}; }}
QLineEdit#TodoQuickAddV0012 {{ border: 0; border-radius: 10px; padding: 7px 12px; background: {t['surface']};
    color: {t['foreground']}; }}
QLineEdit#TodoQuickAddV0012:focus {{ border: 1.5px solid {t['accent']}; background: {t['raised']}; }}
QListWidget#TodoListV0012 {{ border: 0; background: transparent; padding: 0; outline: 0; }}
QListWidget#TodoListV0012::item {{ padding: 7px 6px; border: 0; border-bottom: 1px solid {t['border']};
    border-radius: 0; color: {t['foreground']}; }}
QListWidget#TodoListV0012::item:selected {{ background: {t['accent_soft']}; border-radius: 8px;
    color: {t['foreground']}; border-bottom-color: transparent; }}
QListWidget#TodoListV0012::item:hover:!selected {{ background: {t['hover']}; border-radius: 8px; }}
QListWidget#TodoListV0012::indicator {{ width: 16px; height: 16px; border-radius: 9px;
    border: 1.5px solid {t['border_strong']}; background: transparent; margin-right: 6px; }}
QListWidget#TodoListV0012::indicator:hover {{ border-color: {t['accent']}; }}
QListWidget#TodoListV0012::indicator:checked {{ background: {t['accent']}; border: 1.5px solid {t['accent']}; }}
QWidget#TodoTaskPanelV0014 {{ background: {t['surface']}; border-radius: 14px; }}
QLabel#TodoDetailTitleV0019 {{ font-weight: 700; font-size: 14px; color: {t['foreground']}; }}
QPlainTextEdit#TodoDetailsV0012 {{ border: 0; border-radius: 10px; background: {t['raised']}; padding: 6px;
    color: {t['foreground']}; }}
QPlainTextEdit#TodoNotesV0012 {{ border: 0; border-radius: 14px; background: {t['surface']}; padding: 10px;
    color: {t['foreground']}; }}
QPushButton#TodoDoWithAssistantV0014 {{ border: 0; border-radius: 13px; padding: 5px 12px;
    background: {t['accent']}; color: {t['accent_fg']}; font-weight: 600; }}
QPushButton#TodoDoWithAssistantV0014:hover {{ background: {t['accent_hover']}; }}
QPushButton#TodoDeleteV0014 {{ border: 0; border-radius: 13px; padding: 5px 12px; background: transparent;
    color: {t['danger']}; font-weight: 600; }}
QPushButton#TodoDeleteV0014:hover {{ background: {t['hover']}; }}
QToolButton#TodoAskAssistantV0012 {{ border: 0; border-radius: 13px; padding: 5px 12px; background: {t['surface']};
    color: {t['foreground']}; font-weight: 600; }}
QToolButton#TodoAskAssistantV0012:hover {{ background: {t['hover']}; }}
QToolButton#TodoAskAssistantV0012::menu-indicator {{ image: none; width: 0; }}
QLabel#TodoEmptyHintV0014 {{ color: {t['subtle']}; font-size: 13px; }}
QLabel#TodoStatusV0019 {{ color: {t['subtle']}; font-size: 11px; }}
QTabWidget#TodoTabsV0014::pane {{ border: 0; }}
"""


class TodoWindow(QMainWindow):
    """To-do list & notes (v0.0.19 redesign): a compact, movable window — like a digital post-it.

    Large title with the number of open tasks, a Tasks | Notes segmented switch, one line to add a task, round
    check marks, the details of the selected task in a soft card, and a ⋯ menu for the rest (assistant, finished
    tasks style, erase). The pin keeps the window above the others.
    """

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.setObjectName('TodoWindowV0012')
        self.setWindowTitle('To-do & notes — SPM Studio')
        self.resize(*POST_IT_SIZE)
        self.setMinimumSize(300, 380)
        self.data = model.load()
        self._loading = False
        self._styling = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save)
        central = QWidget()
        central.setObjectName('TodoCentralV0019')
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 10)
        root.setSpacing(10)
        # ------------------------------------------------------------ header: title, count, pin, ⋯
        header = QHBoxLayout()
        header.setSpacing(4)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel('To-do')
        self.title.setObjectName('TodoTitleV0019')
        self.count = QLabel('')
        self.count.setObjectName('TodoCountV0019')
        titles.addWidget(self.title)
        titles.addWidget(self.count)
        header.addLayout(titles, 1)
        self.pin = QToolButton()
        self.pin.setObjectName('TodoPinV0019')
        self.pin.setText('📌')
        self.pin.setCheckable(True)
        self.pin.setToolTip('Keep this window above the other windows')
        self.pin.toggled.connect(self.set_pinned)
        header.addWidget(self.pin, 0, Qt.AlignmentFlag.AlignTop)
        self.more = QToolButton()
        self.more.setObjectName('TodoMoreV0019')
        self.more.setText('⋯')
        self.more.setToolTip('More')
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        header.addWidget(self.more, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)
        # ------------------------------------------------------------ Tasks | Notes
        self.segments = QFrame()
        self.segments.setObjectName('TodoSegmentsV0019')
        sh = QHBoxLayout(self.segments)
        sh.setContentsMargins(2, 2, 2, 2)
        sh.setSpacing(2)
        self.segment_buttons = []
        for index, label in enumerate(('Tasks', 'Notes')):
            b = QPushButton(label)
            b.setProperty('todoSegment', True)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(lambda _=False, i=index: self.tabs.setCurrentIndex(i))
            sh.addWidget(b, 1)
            self.segment_buttons.append(b)
        self.segment_buttons[0].setChecked(True)
        root.addWidget(self.segments)
        # ------------------------------------------------------------ add a task (one line, Enter)
        self.quick = QLineEdit()
        self.quick.setObjectName('TodoQuickAddV0012')
        self.quick.setPlaceholderText('＋  New task')
        self.quick.setToolTip('Type a task and press Enter (Ctrl+N)')
        self.quick.setClearButtonEnabled(True)
        self.quick.setMinimumHeight(34)
        self.quick.returnPressed.connect(self.add_from_quick)
        self.category = QComboBox()                     # kept for older code paths; tasks need no category
        self.category.addItem('No category', '')
        self.category.hide()
        root.addWidget(self.quick)
        # ------------------------------------------------------------ pages (the switch above replaces the tabs)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('TodoTabsV0014')
        self.tabs.tabBar().hide()
        self.tabs.currentChanged.connect(self._page_changed)
        root.addWidget(self.tabs, 1)
        tasks_page = QWidget()
        tv = QVBoxLayout(tasks_page)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(8)
        self.empty = QLabel(EMPTY_HINT)
        self.empty.setObjectName('TodoEmptyHintV0014')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setToolTip('Tick a task when it is done. Select it to add details or to hand it to the assistant.')
        self.empty.setContentsMargins(20, 30, 20, 30)
        tv.addWidget(self.empty)
        self.list = QListWidget()
        self.list.setObjectName('TodoListV0012')
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                  QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list.setWordWrap(True)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.itemChanged.connect(self._item_changed)
        self.list.currentItemChanged.connect(self._show_details)
        self.list.model().rowsMoved.connect(self._rows_moved)
        tv.addWidget(self.list, 1)
        # details of the selected task (hidden while nothing is selected)
        self.panel = QWidget()
        self.panel.setObjectName('TodoTaskPanelV0014')
        self.panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(12, 10, 12, 10)
        pv.setSpacing(6)
        self.detail_title = QLabel()
        self.detail_title.setWordWrap(True)
        self.detail_title.setObjectName('TodoDetailTitleV0019')
        pv.addWidget(self.detail_title)
        self.details = QPlainTextEdit()
        self.details.setObjectName('TodoDetailsV0012')
        self.details.setPlaceholderText('Add details: scans, channels, expected result …')
        self.details.setToolTip('The assistant reads these details when you hand it the task.')
        self.details.setMaximumHeight(96)
        self.details.textChanged.connect(self._detail_changed)
        pv.addWidget(self.details)
        self.detail_category = QComboBox()              # data model field, not shown in the simple layout
        self.detail_category.addItem('No category', '')
        for c in model.CATEGORIES:
            self.detail_category.addItem(c, c)
        self.detail_category.hide()
        prow = QHBoxLayout()
        self.do_it = QPushButton('✨ Do it')
        self.do_it.setObjectName('TodoDoWithAssistantV0014')
        self.do_it.setProperty('primary', True)
        self.do_it.setToolTip('Sends this task (and its details) to the assistant')
        self.do_it.clicked.connect(lambda: self.ask_tasks('selected'))
        self.delete_button = QPushButton('Delete')
        self.delete_button.setObjectName('TodoDeleteV0014')
        self.delete_button.clicked.connect(self.delete_selected)
        prow.addWidget(self.do_it)
        prow.addStretch(1)
        prow.addWidget(self.delete_button)
        pv.addLayout(prow)
        tv.addWidget(self.panel)
        self.tabs.addTab(tasks_page, 'Tasks')
        self.notes = QPlainTextEdit()
        self.notes.setObjectName('TodoNotesV0012')
        self.notes.setPlaceholderText('Notes: observations, results, ideas …\n\n'
                                      'The assistant can turn them into a report, a paper draft or slides.')
        self.notes.textChanged.connect(self._notes_changed)
        self.tabs.addTab(self.notes, 'Notes')
        # ------------------------------------------------------------ bottom bar: assistant + saved state
        bar = QHBoxLayout()
        self.ask = QToolButton()
        self.ask.setObjectName('TodoAskAssistantV0012')
        self.ask.setText('✨ Assistant')
        self.ask.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.ask)
        for label, slot in (('Do all open tasks, one after the other', lambda: self.ask_tasks('open')),
                            ('Make a plan for the open tasks (changes nothing)', lambda: self.ask_tasks('plan')),
                            (None, None),
                            ('Write a report from my notes (LaTeX)', lambda: self.ask_writing('report')),
                            ('Write a paper draft from my notes (LaTeX)', lambda: self.ask_writing('paper')),
                            ('Make slides from my notes', lambda: self.ask_writing('slides')),
                            ('Summarise my notes', lambda: self.ask_writing('summary'))):
            if label is None:
                menu.addSeparator()
            else:
                menu.addAction(label, slot)
        self.ask.setMenu(menu)
        bar.addWidget(self.ask)
        bar.addStretch(1)
        self.status = QLabel('')
        self.status.setObjectName('TodoStatusV0019')
        bar.addWidget(self.status)
        root.addLayout(bar)
        # finished-task style and erase: in the ⋯ menu (the controls stay, for older code paths)
        self.done_style = QComboBox()
        self.done_style.setObjectName('TodoDoneStyleV0012')
        for label, key in DONE_LABELS:
            self.done_style.addItem(label, key)
        style = doc_settings.load().get('todo_done_style', 'strike')
        self.done_style.setCurrentIndex(max(0, self.done_style.findData(style)))
        self.done_style.currentIndexChanged.connect(self._done_style_changed)
        self.done_style.hide()
        self.erase = QToolButton()
        self.erase.setObjectName('TodoEraseAllV0012')
        self.erase.setText('Erase all…')
        self.erase.setToolTip('Remove every task and the notes (a copy is kept in the to-do folder)')
        self.erase.clicked.connect(self.erase_all)
        self.erase.hide()
        self._build_more_menu()
        QShortcut(QKeySequence.StandardKey.Delete, self.list, activated=self.delete_selected)
        QShortcut(QKeySequence('Ctrl+N'), self, activated=self._focus_quick)
        # reload when the assistant changes the file directly
        self.watcher = QFileSystemWatcher(self)
        model.file().parent.mkdir(parents=True, exist_ok=True)
        if not model.file().is_file():
            model.save(self.data)
        self.watcher.addPath(str(model.file()))
        self.watcher.fileChanged.connect(self._file_changed)
        self._own_write = False
        self._restore_place()
        self.restyle()
        self.refresh()
        self.quick.setFocus()

    # ------------------------------------------------------------------ v0.0.19 window behaviour and look
    def _build_more_menu(self):
        menu = QMenu(self.more)
        sub = menu.addMenu('Finished tasks')
        self._done_actions = []
        for index, (label, _key) in enumerate(DONE_LABELS):
            action = sub.addAction(label.capitalize())
            action.setCheckable(True)
            action.setChecked(index == self.done_style.currentIndex())
            action.triggered.connect(lambda _=False, i=index: self.done_style.setCurrentIndex(i))
            self._done_actions.append(action)
        menu.addSeparator()
        menu.addAction('Keep on top', lambda: self.pin.toggle())
        menu.addAction('Erase all…', self.erase_all)
        self.more.setMenu(menu)

    def _settings(self):
        from PySide6.QtCore import QSettings
        return QSettings('SPM Studio', 'SPM Studio AI 0.7')

    def _restore_place(self):
        settings = self._settings()
        geometry = settings.value('todo/geometry')
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except Exception:
                pass
        if self.width() > 900 or self.height() > 1000:      # older versions opened very large
            self.resize(*POST_IT_SIZE)
        pinned = str(settings.value('todo/on_top', False)).lower() in ('true', '1')
        if pinned:
            self.pin.setChecked(True)

    def set_pinned(self, on: bool):
        """Keep the window above the others (a post-it on the screen)."""
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        if visible:
            self.show()
        self._settings().setValue('todo/on_top', bool(on))
        self.pin.setToolTip('Pinned above the other windows — click to unpin' if on else
                            'Keep this window above the other windows')

    def restyle(self):
        if self._styling:
            return
        self._styling = True
        try:
            from spm_studio.shared.appearance import colors
            self.setStyleSheet(_todo_qss(colors()))
        except Exception:
            pass
        finally:
            self._styling = False

    def showEvent(self, event):
        self.restyle()
        super().showEvent(event)

    def _focus_quick(self):
        self.tabs.setCurrentIndex(0)
        self.quick.setFocus()

    def _page_changed(self, index):
        if 0 <= index < len(self.segment_buttons):
            self.segment_buttons[index].setChecked(True)
        self.quick.setVisible(index == 0)

    def _context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        self.list.setCurrentItem(item)
        menu = QMenu(self)
        done = item.checkState() == Qt.CheckState.Checked
        menu.addAction('Mark as not done' if done else 'Mark as done',
                       lambda: item.setCheckState(Qt.CheckState.Unchecked if done else Qt.CheckState.Checked))
        menu.addAction('Rename', lambda: self.list.editItem(item))
        menu.addAction('✨ Do it with the assistant', lambda: self.ask_tasks('selected'))
        menu.addSeparator()
        menu.addAction('Delete', self.delete_selected)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ data ↔ view
    def refresh(self):
        self._loading = True
        current = self.current_task()
        current_id = current['id'] if current else None
        self.list.clear()
        style = self.done_style.currentData()
        for n, t in enumerate(self.data['tasks'], 1):
            if t['done'] and style == 'hide':
                continue
            item = QListWidgetItem(t['text'])
            item.setData(Qt.ItemDataRole.UserRole, t['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable |
                          Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if t['done'] else Qt.CheckState.Unchecked)
            font = QFont(item.font())
            font.setStrikeOut(bool(t['done'] and style == 'strike'))
            item.setFont(font)
            if t['done'] and style == 'strike':
                item.setForeground(self.palette().color(self.palette().ColorRole.PlaceholderText))
            tip = f"#{n} · {t['category'] or 'no category'} · {t['id']}"
            if t['details']:
                tip += '\n' + t['details'][:400]
            item.setToolTip(tip)
            self.list.addItem(item)
            if t['id'] == current_id:
                self.list.setCurrentItem(item)
        if self.notes.toPlainText() != self.data['notes']:
            self.notes.setPlainText(self.data['notes'])
        self._loading = False
        self._show_details(self.list.currentItem())
        empty = not self.data['tasks']
        self.empty.setVisible(empty)
        self.list.setVisible(not empty)
        open_count = sum(1 for t in self.data['tasks'] if not t['done'])
        self.tabs.setTabText(0, f'Tasks ({open_count})' if open_count else 'Tasks')
        self.tabs.setTabText(1, 'Notes ✎' if self.data['notes'].strip() else 'Notes')
        for index, button in enumerate(self.segment_buttons):
            button.setText(self.tabs.tabText(index))
        done_count = len(self.data['tasks']) - open_count
        self.count.setText(('No open task' if not open_count else f'{open_count} open') +
                           (f' · {done_count} done' if done_count else ''))
        for index, action in enumerate(getattr(self, '_done_actions', [])):
            action.setChecked(index == self.done_style.currentIndex())
        self.status.setText('Saved')
        self.status.setToolTip(str(model.file()))

    def current_task(self):
        item = self.list.currentItem() if hasattr(self, 'list') else None
        if item is None:
            return None
        try:
            return model.find(self.data, item.data(Qt.ItemDataRole.UserRole))
        except ValueError:
            return None

    def selected_ids(self):
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]

    def schedule_save(self):
        self._save_timer.start()

    def save(self):
        self._save_timer.stop()
        self._own_write = True
        try:
            model.save(self.data)
        except OSError as exc:
            self.status.setText(f'⚠ Could not save: {exc}')
        finally:
            QTimer.singleShot(300, lambda: setattr(self, '_own_write', False))
        if str(model.file()) not in self.watcher.files():
            self.watcher.addPath(str(model.file()))

    def reload(self):
        self.data = model.load()
        self.refresh()

    def _file_changed(self, _path):
        if str(model.file()) not in self.watcher.files() and model.file().is_file():
            self.watcher.addPath(str(model.file()))
        if self._own_write or self._save_timer.isActive():
            return
        self.reload()

    # ------------------------------------------------------------------ editing
    def add_from_quick(self):
        text, cat = model.parse_quick(self.quick.text())
        if not text:
            return
        task = model.add_task(self.data, text, category=cat or self.category.currentData())
        self.quick.clear()
        self.refresh()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == task['id']:
                self.list.setCurrentRow(i)
        self.save()

    def _item_changed(self, item):
        if self._loading:
            return
        try:
            task = model.find(self.data, item.data(Qt.ItemDataRole.UserRole))
        except ValueError:
            return
        task['text'] = item.text().strip() or task['text']
        done = item.checkState() == Qt.CheckState.Checked
        if done != task['done']:
            model.set_done(task, done)
            self.save()
            QTimer.singleShot(0, self.refresh)        # apply the done style
            return
        self.schedule_save()

    def _rows_moved(self, *_):
        order = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        hidden = [t for t in self.data['tasks'] if t['id'] not in order]
        by_id = {t['id']: t for t in self.data['tasks']}
        self.data['tasks'] = [by_id[i] for i in order if i in by_id] + hidden
        self.schedule_save()

    def _show_details(self, item, *_):
        task = None
        if item is not None:
            try:
                task = model.find(self.data, item.data(Qt.ItemDataRole.UserRole))
            except ValueError:
                task = None
        self._loading = True
        self.details.setEnabled(task is not None)
        self.detail_category.setEnabled(task is not None)
        self.panel.setVisible(task is not None)
        if task is None:
            self.detail_title.setText('')
            self.details.setPlainText('')
        else:
            self.detail_title.setText(task['text'] + ('   ✓ done' if task['done'] else ''))
            if self.details.toPlainText() != task['details']:
                self.details.setPlainText(task['details'])
            self.detail_category.setCurrentIndex(max(0, self.detail_category.findData(task['category'])))
        self._loading = False

    def _detail_changed(self, *_):
        if self._loading:
            return
        task = self.current_task()
        if task is None:
            return
        task['details'] = self.details.toPlainText()
        task['category'] = self.detail_category.currentData() or ''
        self.schedule_save()

    def _notes_changed(self):
        if self._loading:
            return
        self.data['notes'] = self.notes.toPlainText()
        self.schedule_save()

    def _done_style_changed(self, *_):
        doc_settings.save({'todo_done_style': self.done_style.currentData()})
        self.refresh()

    def delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        for i in ids:
            try:
                model.delete(self.data, i)
            except ValueError:
                pass
        self.refresh()
        self.save()

    def erase_all(self):
        if not self.data['tasks'] and not self.data['notes'].strip():
            return
        answer = QMessageBox.question(self, 'Erase everything?',
                                      'Remove every task and all the notes?\n\nA copy is kept in\n'
                                      f'{model.folder()}\n(erased_<date>.json) in case you need it again.')
        if answer != QMessageBox.StandardButton.Yes:
            return
        copy = model.erase_all(self.data)
        self.refresh()
        self.save()
        if copy:
            self.status.setText(f'Erased. Copy kept: {copy}')

    def closeEvent(self, event):
        self.save()
        try:
            self._settings().setValue('todo/geometry', self.saveGeometry())
        except Exception:
            pass
        try:
            self.hub.unregister(self)
        except Exception:
            pass
        super().closeEvent(event)

    # ------------------------------------------------------------------ assistant
    def _send(self, text):
        self.save()
        self.hub.ask_assistant(text, send=True, source=self)

    def ask_tasks(self, which):
        if which == 'selected':
            ids = self.selected_ids()
            if not ids:
                QMessageBox.information(self, 'Assistant', 'Click a task first.')
                return
            listing = model.as_text(self.data, only=set(ids))
            intro = 'Please do these tasks from my SPM Studio to-do list:'
        else:
            listing = model.as_text(self.data, include_done=False)
            if listing == '(no tasks)':
                QMessageBox.information(self, 'Ask the assistant', 'There is no open task.')
                return
            intro = ('Here are the open tasks of my SPM Studio to-do list. Make a short plan (order, what you '
                     'need from me, what you will create) and ask me before changing anything:'
                     if which == 'plan' else
                     'Please do the open tasks of my SPM Studio to-do list, one after the other:')
        text = (f'{intro}\n\n{listing}\n\n'
                'The details under each task say what I need. Ask me if something essential is missing. '
                + ('' if which == 'plan' else
                   'When a task is finished, tick it and write in its details what you did and where the result '
                   'is (to-do requests: update_task with "done": true and "append").'))
        self._send(text)

    def ask_writing(self, kind):
        notes = self.data['notes'].strip()
        done = model.as_text(self.data, only={t['id'] for t in self.data['tasks'] if t['done']})
        if not notes and done == '(no tasks)':
            QMessageBox.information(self, 'Assistant', 'Write some notes first (tab “Notes”).')
            return
        conf = doc_settings.load()
        if kind in ('report', 'paper') and not conf.get('latex_enabled'):
            doc_settings.save({'latex_enabled': True})
        if kind == 'slides' and not conf.get('slides_enabled'):
            doc_settings.save({'slides_enabled': True})
        if kind in ('report', 'paper', 'slides') and not (conf.get('latex_enabled') and conf.get('slides_enabled')):
            # the assistant needs the editors' instructions: refresh its context
            try:
                self.hub.main_window.refresh_document_buttons()
                dock = self.hub._dock()
                if dock is not None and dock.rpc is not None and not dock._running:
                    dock._open_backend()
            except Exception:
                pass
        what = {'report': 'a structured scientific report (LaTeX editor: create a new project from the Article '
                          'template, fill the sections, insert the figures that exist, compile)',
                'paper': 'a paper draft (LaTeX editor: new project; abstract, introduction, methods, results, '
                         'discussion, conclusion; mark missing data and references as TODO, never invent results)',
                'slides': 'a presentation (presentation editor: new presentation, one idea per slide, short bullet '
                          'points, speaker notes with the details)',
                'summary': 'a concise summary of these notes, in the chat (key results, open questions, next steps)'}[kind]
        text = (f'Please write {what}, based on my notes and finished tasks below. Keep my numbers and '
                f'observations exactly; say what is missing.\n\n### Notes\n{notes or "(none)"}\n\n'
                f'### Finished tasks\n{done}')
        self._send(text)

    # protocol: <spm-doc>{"app": "todo", ...}</spm-doc>
    def ai_state(self) -> str:
        return f'to-do list & notes window ({model.summary(self.data)})'

    def apply_external_change(self):
        self.reload()


def ai_action(request: dict, window: TodoWindow | None = None) -> str:
    """Run one to-do request on the saved list (the window, if open, is refreshed)."""
    if window is None:
        return model.ai_action(request)
    result = model.ai_action(request, window.data, save=False)
    if request['action'] != 'read':
        window.refresh()
        window.save()
    return result
