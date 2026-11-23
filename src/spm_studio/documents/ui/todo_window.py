"""To-do list & notes window, connected to the assistant (v0.0.12; simpler layout in v0.0.14)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox, QPushButton,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QLabel, QTabWidget,
                               QToolButton, QMenu, QAbstractItemView, QMessageBox)

from spm_studio.documents import todo as model, settings as doc_settings

DONE_LABELS = (('crossed out', 'strike'), ('normal', 'plain'), ('hidden', 'hide'))
EMPTY_HINT = 'No tasks yet.\nType one above and press Enter.'      # v0.0.18: only the essential


class TodoWindow(QMainWindow):
    """Simple to-do list: add in one line, tick, select for details, notes in a second tab (v0.0.14 layout)."""

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.setObjectName('TodoWindowV0012')
        self.setWindowTitle('To-do & notes — SPM Studio')
        self.resize(760, 640)
        self.data = model.load()
        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 8)
        root.setSpacing(8)
        # ------------------------------------------------------------ add a task (one line, Enter)
        self.quick = QLineEdit()
        self.quick.setObjectName('TodoQuickAddV0012')
        self.quick.setPlaceholderText('＋  Add a task and press Enter')
        self.quick.setClearButtonEnabled(True)
        self.quick.setMinimumHeight(34)
        self.quick.returnPressed.connect(self.add_from_quick)
        self.category = QComboBox()                     # kept for older code paths; tasks need no category
        self.category.addItem('No category', '')
        self.category.hide()
        root.addWidget(self.quick)
        # ------------------------------------------------------------ tasks | notes
        self.tabs = QTabWidget()
        self.tabs.setObjectName('TodoTabsV0014')
        root.addWidget(self.tabs, 1)
        tasks_page = QWidget()
        tv = QVBoxLayout(tasks_page)
        tv.setContentsMargins(0, 6, 0, 0)
        self.empty = QLabel(EMPTY_HINT)
        self.empty.setObjectName('TodoEmptyHintV0014')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setProperty('class', 'emptyState')
        self.empty.setToolTip('Tick a task when it is done. Select it to add details or to hand it to the assistant.')
        self.empty.setContentsMargins(30, 30, 30, 30)
        tv.addWidget(self.empty)
        self.list = QListWidget()
        self.list.setObjectName('TodoListV0012')
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                  QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list.setSpacing(2)
        self.list.setStyleSheet('QListWidget::item { padding: 6px 4px; }')
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.itemChanged.connect(self._item_changed)
        self.list.currentItemChanged.connect(self._show_details)
        self.list.model().rowsMoved.connect(self._rows_moved)
        tv.addWidget(self.list, 1)
        # details of the selected task (hidden while nothing is selected)
        self.panel = QWidget()
        self.panel.setObjectName('TodoTaskPanelV0014')
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(0, 6, 0, 0)
        self.detail_title = QLabel()
        self.detail_title.setWordWrap(True)
        self.detail_title.setObjectName('launcherTitle')
        pv.addWidget(self.detail_title)
        self.details = QPlainTextEdit()
        self.details.setObjectName('TodoDetailsV0012')
        self.details.setPlaceholderText('Details (optional): which scans, channels, parameters, what result you '
                                        'expect … The assistant reads this when you hand it the task.')
        self.details.setMaximumHeight(120)
        self.details.textChanged.connect(self._detail_changed)
        pv.addWidget(self.details)
        self.detail_category = QComboBox()              # data model field, not shown in the simple layout
        self.detail_category.addItem('No category', '')
        for c in model.CATEGORIES:
            self.detail_category.addItem(c, c)
        self.detail_category.hide()
        prow = QHBoxLayout()
        self.do_it = QPushButton('✨ Do it with the assistant')
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
        self.notes.setPlaceholderText('Your notes: observations, results, ideas, references …\n\n'
                                      'The assistant can turn them into a report, a paper draft or slides '
                                      '(button “Assistant” below).')
        self.notes.textChanged.connect(self._notes_changed)
        self.tabs.addTab(self.notes, 'Notes')
        # ------------------------------------------------------------ bottom bar
        bar = QHBoxLayout()
        self.ask = QToolButton()
        self.ask.setObjectName('TodoAskAssistantV0012')
        self.ask.setText('✨ Assistant ▾')
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
        bar.addWidget(QLabel('Finished tasks:'))
        self.done_style = QComboBox()
        self.done_style.setObjectName('TodoDoneStyleV0012')
        for label, key in DONE_LABELS:
            self.done_style.addItem(label, key)
        style = doc_settings.load().get('todo_done_style', 'strike')
        self.done_style.setCurrentIndex(max(0, self.done_style.findData(style)))
        self.done_style.currentIndexChanged.connect(self._done_style_changed)
        bar.addWidget(self.done_style)
        self.erase = QToolButton()
        self.erase.setObjectName('TodoEraseAllV0012')
        self.erase.setText('Erase all…')
        self.erase.setToolTip('Remove every task and the notes (a copy is kept in the to-do folder)')
        self.erase.clicked.connect(self.erase_all)
        bar.addWidget(self.erase)
        root.addLayout(bar)
        self.status = QLabel('')
        self.status.setObjectName('hint')
        root.addWidget(self.status)
        QShortcut(QKeySequence.StandardKey.Delete, self.list, activated=self.delete_selected)
        QShortcut(QKeySequence('Ctrl+N'), self, activated=lambda: self.quick.setFocus())
        # reload when the assistant changes the file directly
        self.watcher = QFileSystemWatcher(self)
        model.file().parent.mkdir(parents=True, exist_ok=True)
        if not model.file().is_file():
            model.save(self.data)
        self.watcher.addPath(str(model.file()))
        self.watcher.fileChanged.connect(self._file_changed)
        self._own_write = False
        self.refresh()
        self.quick.setFocus()

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
        self.status.setText('Saved automatically.')
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
