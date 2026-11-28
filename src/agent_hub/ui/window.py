"""Agent Hub interface: ``HubWidget`` (sidebar + panels) and the containers that show it.

* ``HubWindow`` — the standalone application window.
* ``HubDock`` — a native ``QDockWidget`` for a host main window (SPM Studio): docked by default, with a
  detach button that moves the *same* widget into ``DetachedWindow`` (any screen, maximizable) and back.
  Detaching or re-docking only re-parents the widget: running agents, streaming replies, pending approvals,
  drafts, attachments, the selected model and the scroll position are untouched.

Several chats run at the same time; tabs show a live status (spinner, needs you, ready, error).
Layouts: single, side by side, grid. Everything is reachable from the keyboard (F1).
"""
from __future__ import annotations

import html
import time

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSplitter, QStackedWidget, QTabBar, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..icons import state_icon, state_text
from . import theme
from .panel import ChatPanel
from .sidebar import ADD, COLOR, COUNT, PROJECT_COLORS, STATE, WHEN, SidebarTree, relative
from .usage_rings import UsageRings
from .widgets import MonitorStrip, icon_button

ROLE = Qt.ItemDataRole.UserRole
NARROW = 720
SHORTCUTS = [
    ('Ctrl+N', 'New chat in a new panel (the others keep running)'),
    ('Ctrl+Shift+N', 'New chat in the selected project'),
    ('Ctrl+Shift+P', 'New project'),
    ('Enter / Shift+Enter', 'Send / new line (Ctrl+Enter also sends)'),
    ('Ctrl+.', 'Stop the reply of this chat'),
    ('Alt+Y · Alt+A · Alt+N', 'Allow · Always allow · Deny the request shown above the message box'),
    ('Y · A · N · Enter · Esc', 'Same, when the request card has the focus'),
    ('Ctrl+Shift+V · hold F11', 'Voice: start/stop recording · push-to-talk (Esc cancels)'),
    ('Ctrl+Shift+B', 'Brainstorming mode on/off for this chat'),
    ('Ctrl+Shift+G', 'Generate the final prompt (brainstorming)'),
    ('Ctrl+Shift+R · Ctrl+Shift+E · Ctrl+Shift+C', 'Regenerate · edit last message · copy last reply'),
    ('Ctrl+Tab · Ctrl+Shift+Tab', 'Next / previous panel'),
    ('Ctrl+1 … Ctrl+9', 'Go to panel 1 … 9'),
    ('Alt+← → ↑ ↓', 'Move between panels shown side by side'),
    ('Ctrl+\\', 'Layout: single → side by side → grid'),
    ('Ctrl+W', 'Close the panel (a running chat may keep running)'),
    ('Ctrl+K', 'Quick switch to any chat'),
    ('Ctrl+F · Ctrl+E · Ctrl+L', 'Search chats · chat list · message box'),
    ('Ctrl+B', 'Show / hide the chat list'),
    ('F2 · Ctrl+M · Ctrl+Shift+Delete', 'Rename · move to a project · delete the chat'),
    ('Ctrl+Shift+M', 'Choose the model of this chat'),
    ('Ctrl+Shift+D', 'Detach / re-dock (inside a host window)'),
    ('Ctrl+Shift+K · Ctrl+Shift+T · Ctrl+Shift+O', 'Calendar · to-do list · e-mail (outbox and accounts)'),
    ('Delete (in the list)', 'Delete the selected chat or project'),
    ('Ctrl+,', 'Settings'),
    ('F1', 'This list'),
]


class QuickSwitch(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Go to a chat')
        self.resize(520, 420)
        self.store = store
        self.result_id = ''
        self.new_panel = False
        lay = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setPlaceholderText('Type to search titles and messages · Enter opens · Shift+Enter in a new panel')
        self.list = QListWidget()
        lay.addWidget(self.query)
        lay.addWidget(self.list, 1)
        self.query.textChanged.connect(self.fill)
        self.query.installEventFilter(self)
        self.list.itemActivated.connect(lambda _i: self.done_with())
        self.fill('')

    def fill(self, text):
        self.list.clear()
        names = {p['id']: p['name'] for p in self.store.projects()}
        for chat in self.store.chats(query=text, archived=None)[:200]:
            label = chat['title'] + (f"   · {names.get(chat.get('project'), '')}" if chat.get('project') else '')
            if chat.get('archived'):
                label += '   · archived'
            item = QListWidgetItem(label)
            item.setData(ROLE, chat['id'])
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                self.list.keyPressEvent(event)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.new_panel = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self.done_with()
                return True
        return super().eventFilter(obj, event)

    def done_with(self):
        item = self.list.currentItem()
        if item is not None:
            self.result_id = item.data(ROLE)
            self.accept()


class HubWidget(QWidget):
    """Everything of the hub inside one widget, so any container (window, dock) can show it."""
    detachRequested = Signal()

    def __init__(self, core, host_window=None, api=None, parent=None):
        super().__init__(parent)
        self.core = core
        self.host_window = host_window
        self.api = api
        self.setObjectName('hubRoot')
        self.setMinimumWidth(330)                  # explicit: a docked panel may be narrow (compact layout)
        self.qsettings = QSettings('SPM Studio', 'Agent Hub')
        self.panels: dict[str, ChatPanel] = {}
        self.order: list[str] = []
        self.current = ''
        self.mode = core.conf.get('layout', 'single')
        self._frame = 0
        self._content = None
        self._narrow = False
        self._collapsed = set(str(x) for x in (self.qsettings.value('collapsed') or ['_archived']) if x)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._toolbar())
        self.banner = QLabel('')
        self.banner.setObjectName('hubHint')
        self.banner.setWordWrap(True)
        self.banner.hide()
        outer.addWidget(self.banner)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self._sidebar())
        self.split.addWidget(self._workspace())
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([260, 900])
        self.split.setChildrenCollapsible(False)
        outer.addWidget(self.split, 1)
        self.strip = MonitorStrip(core)
        outer.addWidget(self.strip)
        self._shortcuts()
        self._spinner = QTimer(self)
        self._spinner.setInterval(110)
        self._spinner.timeout.connect(self._animate)
        self._spinner.start()
        self._list_timer = QTimer(self)
        self._list_timer.setSingleShot(True)
        self._list_timer.setInterval(120)
        self._list_timer.timeout.connect(self.fill_list)
        core.chatsChanged.connect(self._list_timer.start)
        core.stateChanged.connect(self._run_state)
        core.settingsChanged.connect(self._settings_changed)
        core.backendsChanged.connect(self._providers_label)
        state = self.qsettings.value('split')
        if state:
            self.split.restoreState(state)
        self.sidebar.setVisible(bool(core.conf.get('sidebar', True)))
        self.apply_theme()
        self.fill_list()
        for cid in [str(c) for c in (self.qsettings.value('open_chats') or []) if c][:12]:
            if core.store.get_chat(cid):
                self.open_chat(cid, new_panel=True, focus=False)
        last = str(self.qsettings.value('current') or '')
        if last in self.panels:
            self.focus_chat(last)
        self._rebuild()
        self._update_title()
        if core.migration.get('copied'):
            self.show_banner(f"Your chats and projects were copied from {core.migration['copied']} (the original "
                             'stays untouched for rollback).')

    # ================================================================== toolbar
    def _toolbar(self):
        bar = QWidget()
        bar.setObjectName('hubToolbar')
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(4)
        side = icon_button('menu', 'Show / hide the chat list (Ctrl+B)')
        side.clicked.connect(self.toggle_sidebar)
        new = QPushButton('New chat')
        new.setObjectName('hubSend')
        from .svg_icons import set_icon
        set_icon(new, 'chat-new', 'accent_fg')
        new.setToolTip('New chat in a new panel (Ctrl+N)')
        new.clicked.connect(lambda: self.new_chat())
        row.addWidget(side)
        row.addWidget(new)
        row.addSpacing(8)
        self.layout_buttons = {}
        self.secondary = []                       # folded into the "More" menu in a narrow panel
        for mode, tip in (('single', 'One chat at a time'), ('columns', 'Open chats side by side'),
                          ('grid', 'Open chats in a grid')):
            b = icon_button('layout-' + mode, tip + ' (Ctrl+\\ cycles)', checkable=True)
            b.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            row.addWidget(b)
            self.layout_buttons[mode] = b
            self.secondary.append(b)
        row.addStretch(1)
        self.counts = QLabel('')
        self.counts.setObjectName('hubMeta')
        from PySide6.QtWidgets import QSizePolicy
        self.counts.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.counts, 1)
        try:
            badge = self.api.beta_badge(bar) if self.api is not None else None
            if badge is not None:
                row.addWidget(badge)
        except Exception:
            pass
        self.profile = QComboBox()
        for key, label in (('eco', 'Eco'), ('balanced', 'Balanced'), ('performance', 'Performance'),
                           ('local', 'Local only'), ('manual', 'Manual')):
            self.profile.addItem(label, key)
        self.profile.setToolTip('Routing profile: Eco (local / low-cost first) · Balanced · Performance (stronger '
                                'models) · Local only (never the cloud) · Manual (only the model you pick)')
        self.profile.activated.connect(self._profile_chosen)
        row.addWidget(self.profile)
        for name, tip, slot in (('calendar', 'Calendar (Ctrl+Shift+K)', lambda: self.open_organizer('calendar')),
                                ('todo', 'To-do list (Ctrl+Shift+T)', lambda: self.open_organizer('todo')),
                                ('mail', 'E-mail: outbox and accounts (Ctrl+Shift+O)',
                                 lambda: self.open_organizer('mail'))):
            b = icon_button(name, tip)
            b.clicked.connect(slot)
            row.addWidget(b)
            self.secondary.append(b)
        self.full_button = icon_button('full', 'Full access — like an octopus, the assistant can reach anything: '
                                               'commands and file changes anywhere your account can, without '
                                               'asking. Still asked every time: anything that leaves this computer '
                                               '(e-mails, pushes, uploads, form posts). Off: requests appear above '
                                               'the message box.', checkable=True)
        self.full_button.setObjectName('hubFullAccess')
        self.full_button.setAccessibleName('Full access')
        self.full_button.clicked.connect(self.toggle_full_access)
        row.addWidget(self.full_button)
        refresh = icon_button('refresh', 'Look again for installed models (Pi, Claude Code, Codex, Ollama, APIs)')
        refresh.clicked.connect(self.core.refresh_backends)
        row.addWidget(refresh)
        self.secondary.append(refresh)
        self.more_button = icon_button('more', 'More: layouts, calendar, to-do, e-mail, look for models, shortcuts')
        self.more_button.setPopupMode(self.more_button.ToolButtonPopupMode.InstantPopup)
        from PySide6.QtWidgets import QMenu as _QMenu
        more = _QMenu(self.more_button)
        from .svg_icons import icon as _icon
        for mode, label in (('single', 'One chat at a time'), ('columns', 'Side by side'), ('grid', 'Grid')):
            more.addAction(_icon('layout-' + mode), label, lambda m=mode: self.set_mode(m))
        more.addSeparator()
        more.addAction(_icon('calendar'), 'Calendar', lambda: self.open_organizer('calendar'))
        more.addAction(_icon('todo'), 'To-do list', lambda: self.open_organizer('todo'))
        more.addAction(_icon('mail'), 'E-mail', lambda: self.open_organizer('mail'))
        more.addSeparator()
        more.addAction(_icon('refresh'), 'Look again for installed models', self.core.refresh_backends)
        more.addAction(_icon('help'), 'Keyboard shortcuts (F1)', lambda: self.show_help())
        self.more_button.setMenu(more)
        self.more_button.hide()
        row.addWidget(self.more_button)
        self.container_slot = QHBoxLayout()
        self.container_slot.setSpacing(2)
        row.addLayout(self.container_slot)
        settings = icon_button('gear', 'Settings (Ctrl+,)')
        settings.clicked.connect(self.open_settings)
        helpb = icon_button('help', 'Keyboard shortcuts (F1)')
        helpb.clicked.connect(self.show_help)
        row.addWidget(settings)
        row.addWidget(helpb)
        self.secondary.append(helpb)
        self._settings_changed()
        return bar

    def add_container_button(self, button: QToolButton):
        self.container_slot.addWidget(button)

    def _profile_chosen(self, _i):
        conf = dict(self.core.conf)
        conf['routing_profile'] = self.profile.currentData()
        self.core.save_settings(conf)

    def _settings_changed(self):
        on = bool(self.core.conf.get('full_access'))
        self.full_button.setChecked(on)
        from .svg_icons import set_icon
        set_icon(self.full_button, 'full', 'accent_fg' if on else None)
        for mode, b in self.layout_buttons.items():
            b.setChecked(mode == self.mode)
        i = self.profile.findData(self.core.conf.get('routing_profile', 'balanced'))
        self.profile.setCurrentIndex(max(0, i))

    def apply_theme(self):
        """Live theme change: only styles are replaced; chats and running agents are untouched."""
        self.setStyleSheet(theme.stylesheet())
        from . import svg_icons
        svg_icons.refresh()
        scale = int(self.core.conf.get('font_scale', 100))
        if scale != 100:
            f = theme.scale_font(QFont(QApplication.font()), scale / 100, 6.0)
            self.setFont(f)
        for p in self.panels.values():
            p._settings_changed()

    def show_banner(self, text: str):
        self.banner.setText('  ' + text)
        self.banner.setVisible(bool(text))
        if text:
            QTimer.singleShot(15000, lambda: self.banner.hide())

    def toggle_full_access(self):
        conf = dict(self.core.conf)
        if not conf.get('full_access'):
            box = QMessageBox(self)
            box.setWindowTitle('Full access')
            box.setText('Let the assistant work without asking?')
            box.setInformativeText('It will run commands, change files anywhere your user account can and move '
                                   'chats without asking you first. It is not sandboxed. Anything that would leave '
                                   'this computer on your behalf — sending an e-mail, a push, an upload, a form — '
                                   'is still shown to you every time. Brainstorming chats stay read-only. '
                                   'Conversations use the new setting from their next message.')
            on = box.addButton('Turn &on full access', QMessageBox.ButtonRole.AcceptRole)
            box.addButton('&Cancel', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not on:
                self.full_button.setChecked(False)
                return
            conf['full_access'] = True
        else:
            conf['full_access'] = False
        self.core.save_settings(conf)

    # ================================================================== sidebar
    def _sidebar(self):
        self.sidebar = QWidget()
        self.sidebar.setObjectName('hubSidebar')
        self.sidebar.setMinimumWidth(200)
        lay = QVBoxLayout(self.sidebar)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName('hubSearch')
        self.search.setPlaceholderText('Search chats  (Ctrl+F)')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._list_timer.start())
        lay.addWidget(self.search)
        self.tree = SidebarTree()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._list_menu)
        self.tree.itemActivated.connect(self._activated)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemExpanded.connect(lambda i: self._remember_fold(i, False))
        self.tree.itemCollapsed.connect(lambda i: self._remember_fold(i, True))
        self.tree.addRequested.connect(lambda what: self.new_project() if what == 'project' else None)
        self.tree.installEventFilter(self)
        lay.addWidget(self.tree, 1)
        self.usage_rings = UsageRings(self.core)
        lay.addWidget(self.usage_rings)
        self.providers = QLabel('')               # kept for hosts and tests; shown as the rings' tooltip
        self.providers.hide()
        lay.addWidget(self.providers)
        self._providers_label()
        return self.sidebar

    def _providers_label(self):
        groups = {}
        for b in self.core.backends:
            groups.setdefault(b['group'], []).append(b)
        from ..scheduler import GROUP_LABELS
        if not groups:
            text = 'No model connected yet — Settings › AI Providers & Accounts.'
        else:
            text = 'Connected: ' + ', '.join(f"{GROUP_LABELS.get(g, g)} ({len(v)})" for g, v in groups.items())
        self.providers.setText(text)
        self.usage_rings.setToolTip(text + '\nClick a ring for usage, limits and reset times.')

    def _remember_fold(self, item, collapsed):
        kind, ident = item.data(0, ROLE) or ('', '')
        if kind in ('project', 'section'):
            (self._collapsed.add if collapsed else self._collapsed.discard)(ident or '_unsorted')
            self.qsettings.setValue('collapsed', sorted(self._collapsed))

    def _section(self, title, ident, tip='', count=None, add=''):
        top = QTreeWidgetItem([title])
        top.setData(0, ROLE, ('section', ident))
        if count is not None:
            top.setData(0, COUNT, count)
        if add:
            top.setData(0, ADD, add)
            tip = tip or 'New project'
        if tip:
            top.setToolTip(0, tip)
        top.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.tree.addTopLevelItem(top)
        return top

    def fill_list(self):
        query = self.search.text().strip()
        selected = self._selected()
        self.tree.blockSignals(True)
        self.tree.clear()
        store = self.core.store
        now = time.time()
        active = [cid for cid, r in self.core.runs.items() if r.state in ('running', 'approval', 'queued')]
        if active and not query:
            top = self._section('Running', '_running', 'Chats working, queued or waiting for you')
            for cid in active:
                chat = store.get_chat(cid)
                if chat:
                    top.addChild(self._chat_item(chat, now))
            top.setExpanded(True)
        pinned = [c for c in store.chats(query=query) if c.get('pinned')]
        if pinned:
            top = self._section('Pinned', '_pinned')
            for chat in pinned:
                top.addChild(self._chat_item(chat, now))
            top.setExpanded(bool(query) or '_pinned' not in self._collapsed)
        projects = store.projects()
        live = [p for p in projects if not p.get('archived')]
        self._section('Projects', '_projects', 'New project (Ctrl+Shift+P)', add='project')
        for n, p in enumerate(projects):
            if p.get('archived'):
                continue
            chats = [c for c in store.chats(project=p['id'], query=query) if not c.get('pinned')]
            if query and not chats:
                continue
            item = QTreeWidgetItem([p['name']])
            item.setData(0, ROLE, ('project', p['id']))
            item.setData(0, COUNT, len(chats) or '')
            item.setData(0, COLOR, self.tree.project_color(p, n))
            tip = p['name'] + (f"\n{(p.get('instructions') or '')[:240]}" if p.get('instructions') else '')
            item.setToolTip(0, tip)
            self.tree.addTopLevelItem(item)
            for chat in chats[:300]:
                item.addChild(self._chat_item(chat, now))
            item.setExpanded(bool(query) or (p['id'] not in self._collapsed and bool(chats) and
                                             p['id'] in self._expanded_projects()))
        if not live and not query:
            hint = QTreeWidgetItem(['No projects yet — use + to make one'])
            hint.setData(0, ROLE, ('hint', ''))
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(hint)
        recent = [c for c in store.chats(project='', query=query) if not c.get('pinned')]
        top = self._section('Recent chats', '', 'Chats outside a project, newest first')
        for chat in recent[:500]:
            top.addChild(self._chat_item(chat, now))
        top.setExpanded(bool(query) or '_unsorted' not in self._collapsed)
        archived = store.chats(query=query, archived=True)
        archived_projects = [p for p in projects if p.get('archived')]
        if archived or archived_projects:
            top = self._section('Archived', '_archived', count=len(archived) + len(archived_projects))
            for n, p in enumerate(archived_projects):
                item = QTreeWidgetItem([p['name']])
                item.setData(0, ROLE, ('project', p['id']))
                item.setData(0, COLOR, self.tree.project_color(p, n))
                item.setData(0, COUNT, len(store.chats(project=p['id'], archived=None)) or '')
                item.setToolTip(0, p['name'] + ' (archived project)')
                top.addChild(item)
            for chat in archived[:300]:
                top.addChild(self._chat_item(chat, now))
            top.setExpanded(bool(query) or '_archived' not in self._collapsed)
        self.tree.blockSignals(False)
        if selected:
            self._select(*selected)
        for cid, panel in self.panels.items():
            panel._refresh_header()
            self.tabs.setTabText(self.order.index(cid), self._tab_text(cid))
        self._update_title()

    def _expanded_projects(self) -> set:
        """Projects shown open: the one of the current chat, plus those the user unfolded."""
        found = set(str(x) for x in (self.qsettings.value('expanded_projects') or []) if x)
        chat = self.core.store.get_chat(self.current) if self.current else None
        if chat and chat.get('project'):
            found.add(chat['project'])
        return found

    def _remember_open(self, item, opened):
        kind, ident = item.data(0, ROLE) or ('', '')
        if kind != 'project':
            return
        found = set(str(x) for x in (self.qsettings.value('expanded_projects') or []) if x)
        (found.add if opened else found.discard)(ident)
        self.qsettings.setValue('expanded_projects', sorted(found))

    def _chat_item(self, chat, now=None):
        item = QTreeWidgetItem([chat['title']])
        item.setData(0, ROLE, ('chat', chat['id']))
        item.setToolTip(0, chat['title'])
        item.setData(0, WHEN, relative(chat.get('updated') or chat.get('created') or 0, now))
        run = self.core.runs.get(chat['id'])
        if run is not None and run.state != 'idle':
            item.setData(0, STATE, state_icon(run.state, self._frame, run.unread))
        elif chat.get('mode') == 'brainstorm':
            from .svg_icons import icon
            item.setIcon(0, icon('brainstorm', theme.tokens().get('muted')))
        elif chat.get('pinned'):
            from .svg_icons import icon
            item.setIcon(0, icon('pin', theme.tokens().get('muted')))
        return item

    def _selected(self):
        item = self.tree.currentItem()
        return tuple(item.data(0, ROLE)) if item is not None and item.data(0, ROLE) else None

    def _select(self, kind, ident):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if tuple(top.data(0, ROLE) or ()) == (kind, ident):
                self.tree.setCurrentItem(top)
                return
            for j in range(top.childCount()):
                child = top.child(j)
                if tuple(child.data(0, ROLE) or ()) == (kind, ident):
                    self.tree.setCurrentItem(child)
                    return

    def _clicked(self, item, _col):
        kind, ident = item.data(0, ROLE) or ('', '')
        if kind == 'chat':
            new = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
            self.open_chat(ident, new_panel=new)
        elif kind in ('project', 'section') and item.childCount():
            item.setExpanded(not item.isExpanded())
            self._remember_open(item, item.isExpanded())

    def _activated(self, item, _col):
        kind, ident = item.data(0, ROLE) or ('', '')
        if kind == 'chat':
            new = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.open_chat(ident, new_panel=new)
        elif kind in ('project', 'section'):
            item.setExpanded(not item.isExpanded())
            self._remember_open(item, item.isExpanded())

    def _selected_project(self) -> str:
        item = self.tree.currentItem()
        if item is None:
            chat = self.core.store.get_chat(self.current) if self.current else None
            return (chat or {}).get('project', '')
        kind, ident = item.data(0, ROLE) or ('', '')
        if kind == 'project':
            return ident
        if kind == 'chat':
            return (self.core.store.get_chat(ident) or {}).get('project', '')
        return ''

    def _list_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        kind, ident = (item.data(0, ROLE) if item is not None else None) or ('', '')
        if kind == 'chat':
            chat = self.core.store.get_chat(ident) or {}
            menu.addAction('Open', lambda: self.open_chat(ident))
            menu.addAction('Open in a new panel', lambda: self.open_chat(ident, new_panel=True))
            menu.addAction('Rename…', lambda: self.rename_chat(ident))
            menu.addAction('Unpin' if chat.get('pinned') else 'Pin', lambda: self._flag(ident, 'pinned'))
            menu.addAction('Unarchive' if chat.get('archived') else 'Archive', lambda: self._flag(ident, 'archived'))
            move = menu.addMenu('Move to project')
            for p in self.core.store.projects():
                move.addAction(p['name'], lambda pid=p['id']: self._move(ident, pid))
            move.addSeparator()
            move.addAction('No project', lambda: self._move(ident, ''))
            menu.addAction('Export as Markdown…', lambda: self.export_chat(ident))
            menu.addSeparator()
            menu.addAction('Delete…', lambda: self.delete_chat(ident))
        elif kind == 'project':
            from .svg_icons import icon
            project = self.core.store.project(ident) or {}
            menu.addAction(icon('chat-new'), 'New chat in this project', lambda: self.new_chat(project=ident))
            menu.addAction(icon('brainstorm'), 'New brainstorming in this project',
                           lambda: self.new_chat(project=ident, brainstorm=True))
            try:
                from ..host import current
                for label, fn in current().project_actions(project) or []:
                    menu.addAction(label, lambda f=fn: f(self))
            except Exception:
                pass
            menu.addSeparator()
            menu.addAction(icon('rename'), 'Rename…', lambda: self.rename_project(ident))
            colors = menu.addMenu(icon('palette'), 'Colour')
            for n, c in enumerate(PROJECT_COLORS):
                act = colors.addAction(theme.dot_icon(c), ('Default' if n == 0 else c), lambda col=c: self._project_color(ident, col))
                act.setCheckable(True)
                act.setChecked((project.get('color') or '') == c)
            menu.addAction(icon('archive'), 'Unarchive' if project.get('archived') else 'Archive',
                           lambda: self._project_archive(ident, not project.get('archived')))
            menu.addAction(icon('settings'), 'Project settings…', lambda: self.edit_project(ident))
            menu.addSeparator()
            menu.addAction(icon('trash'), 'Delete project…', lambda: self.delete_project(ident))
        menu.addSeparator()
        menu.addAction('New chat', lambda: self.new_chat())
        menu.addAction('New brainstorming', lambda: self.new_chat(brainstorm=True))
        menu.addAction('New project…', self.new_project)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def rename_project(self, pid):
        project = self.core.store.project(pid)
        if project is None:
            return
        text, ok = QInputDialog.getText(self, 'Rename project', 'Name:', text=project['name'])
        if ok and text.strip():
            try:
                self.core.store.update_project(pid, name=text.strip())
            except ValueError as exc:
                QMessageBox.warning(self, 'Rename project', str(exc))
                return
            self.core.chatsChanged.emit()

    def _project_color(self, pid, color):
        self.core.store.update_project(pid, color=color)
        self.core.chatsChanged.emit()

    def _project_archive(self, pid, archived):
        self.core.store.update_project(pid, archived=bool(archived))
        self.core.chatsChanged.emit()

    def _flag(self, chat_id, flag):
        chat = self.core.store.get_chat(chat_id) or {}
        self.core.store.set_flag(chat_id, flag, not chat.get(flag))
        self.core.chatsChanged.emit()

    def _move(self, chat_id, project_id):
        try:
            self.core.store.move_chat(chat_id, project_id)
        except KeyError:
            return
        self.core.chatsChanged.emit()

    def export_chat(self, chat_id):
        from PySide6.QtWidgets import QFileDialog
        from pathlib import Path
        chat = self.core.store.get_chat(chat_id)
        if not chat:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export chat', str(Path.home() / (chat['title'][:40] + '.md')),
                                              'Markdown (*.md)')
        if not path:
            return
        lines = [f"# {chat['title']}\n"]
        for m in chat['messages']:
            who = {'user': 'You', 'assistant': m.get('model') or 'Assistant'}.get(m['role'], 'Note')
            lines.append(f"## {who}\n\n{m['content']}\n")
        Path(path).write_text('\n'.join(lines), encoding='utf8')

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.tree and event.type() == QEvent.Type.KeyPress:
            kind, ident = self._selected() or ('', '')
            if event.key() == Qt.Key.Key_Delete:
                if kind == 'chat':
                    self.delete_chat(ident)
                elif kind == 'project':
                    self.delete_project(ident)
                return True
            if event.key() == Qt.Key.Key_F2:
                if kind == 'chat':
                    self.rename_chat(ident)
                elif kind == 'project':
                    self.edit_project(ident)
                return True
        return super().eventFilter(obj, event)

    # ================================================================== workspace
    def _workspace(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.tabs = QTabBar()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(lambda i: self.close_chat(self.order[i]) if 0 <= i < len(self.order)
                                            else None)
        self.tabs.tabMoved.connect(self._tab_moved)
        lay.addWidget(self.tabs)
        self.area = QWidget()
        self.area_lay = QVBoxLayout(self.area)
        self.area_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.area, 1)
        self.empty = QLabel('<p style="font-size:16px"><b>How can I help?</b></p>'
                            '<p><b>Ctrl+N</b> new chat · <b>Ctrl+K</b> open one · brainstorm first to save '
                            'tokens (Ctrl+Shift+B)<br>Several chats run at the same time. <b>F1</b> lists every shortcut.</p>')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        return box

    def _tab_text(self, cid):
        title = (self.core.store.get_chat(cid) or {}).get('title', 'Chat')
        return title if len(title) <= 26 else title[:25] + '…'

    def _tab_changed(self, index):
        if 0 <= index < len(self.order):
            cid = self.order[index]
            if cid != self.current:
                self.current = cid
                self._show_current()

    def _tab_moved(self, frm, to):
        cid = self.order.pop(frm)
        self.order.insert(to, cid)
        if self._effective_mode() != 'single':
            self._rebuild()

    def _effective_mode(self):
        return 'single' if self._narrow else self.mode

    def _show_current(self):
        panel = self.panels.get(self.current)
        if panel is None:
            return
        if isinstance(self._content, QStackedWidget):
            self._content.setCurrentWidget(panel)
        accent = theme.tokens().get('accent', '#C8673A')
        for cid, p in self.panels.items():
            p.setStyleSheet('#hubPanel { border-top: 2px solid %s; }' % (
                accent if (cid == self.current and self._effective_mode() != 'single') else 'transparent'))
        run = self.core.runs.get(self.current)
        if run is not None and run.state == 'done':
            run.unread = False
            self._refresh_icon(self.current)
        panel.focus_input()
        self._update_title()

    def _rebuild(self):
        for cid in self.order:
            self.panels[cid].setParent(None)
        self.empty.setParent(None)
        old = self._content
        if old is not None:
            self.area_lay.removeWidget(old)
            old.deleteLater()
        n = len(self.order)
        mode = self._effective_mode()
        if n == 0:
            content = QWidget()
            QVBoxLayout(content).addWidget(self.empty)
        elif mode == 'single' or n == 1:
            content = QStackedWidget()
            for cid in self.order:
                content.addWidget(self.panels[cid])
        elif mode == 'columns':
            content = QSplitter(Qt.Orientation.Horizontal)
            for cid in self.order:
                content.addWidget(self.panels[cid])
        else:
            cols = 2 if n <= 4 else 3
            content = QSplitter(Qt.Orientation.Vertical)
            for start in range(0, n, cols):
                row = QSplitter(Qt.Orientation.Horizontal)
                for cid in self.order[start:start + cols]:
                    row.addWidget(self.panels[cid])
                content.addWidget(row)
        self._content = content
        self.area_lay.addWidget(content)
        for p in self.panels.values():
            p.show()
            p.compact(self._narrow)
        self._show_current()
        for m, b in self.layout_buttons.items():
            b.setChecked(m == self.mode)

    def set_mode(self, mode):
        self.mode = mode
        conf = dict(self.core.conf)
        conf['layout'] = mode
        self.core.save_settings(conf)
        self._rebuild()

    def cycle_mode(self):
        modes = ['single', 'columns', 'grid']
        self.set_mode(modes[(modes.index(self.mode) + 1) % 3] if self.mode in modes else 'single')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < NARROW
        if narrow != self._narrow:
            self._narrow = narrow
            if narrow:
                self.sidebar.hide()
            elif not narrow:
                self.sidebar.setVisible(bool(self.core.conf.get('sidebar', True)))
            self.profile.setVisible(not narrow)
            self.counts.setVisible(not narrow)
            for b in self.secondary:
                b.setVisible(not narrow)
            self.more_button.setVisible(narrow)
            self._rebuild()

    # ================================================================== open / close
    def open_chat(self, cid, new_panel=False, focus=True):
        if cid in self.panels:
            if focus:
                self.focus_chat(cid)
            return
        if self.core.store.get_chat(cid) is None:
            return
        replace = ''
        if not new_panel and self.current in self.panels:
            run = self.core.runs.get(self.current)
            if run is None or (not run.busy and run.state != 'queued'):
                replace = self.current
        panel = ChatPanel(self.core, cid)
        panel.focused.connect(self._panel_focused)
        panel.closeRequested.connect(self.close_chat)
        panel.stateChanged.connect(lambda c, s: self._refresh_icon(c))
        panel.executionStarted.connect(lambda c: self.open_chat(c, new_panel=True))
        panel.openOrganizer.connect(lambda which, ident: self.open_organizer(which, ident))
        self.panels[cid] = panel
        if replace:
            index = self.order.index(replace)
            self._remove_panel(replace)
            self.order.insert(index, cid)
            self.tabs.insertTab(index, self._tab_text(cid))
        else:
            self.order.append(cid)
            self.tabs.addTab(self._tab_text(cid))
        self._refresh_icon(cid)
        self._rebuild()
        if focus:
            self.focus_chat(cid)
        self._list_timer.start()
        self._save_open()

    def _remove_panel(self, cid):
        panel = self.panels.pop(cid, None)
        if cid in self.order:
            index = self.order.index(cid)
            self.order.pop(index)
            self.tabs.blockSignals(True)
            self.tabs.removeTab(index)
            self.tabs.blockSignals(False)
        if panel is not None:
            panel.dispose()
            panel.setParent(None)
            panel.deleteLater()
        self.core.close_run(cid)

    def focus_chat(self, cid):
        if cid not in self.order:
            return
        self.current = cid
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(self.order.index(cid))
        self.tabs.blockSignals(False)
        self._show_current()

    def _panel_focused(self, cid):
        if cid != self.current and cid in self.order:
            self.current = cid
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(self.order.index(cid))
            self.tabs.blockSignals(False)
            self._show_current()

    def close_chat(self, cid=None):
        cid = cid or self.current
        if cid not in self.panels:
            return
        run = self.core.runs.get(cid)
        if run is not None and (run.busy or run.state == 'queued'):
            box = QMessageBox(self)
            box.setWindowTitle('Close chat')
            box.setText(f"“{(self.core.store.get_chat(cid) or {}).get('title', 'This chat')}” is still working.")
            keep = box.addButton('&Keep it running', QMessageBox.ButtonRole.AcceptRole)
            stop = box.addButton('&Stop it', QMessageBox.ButtonRole.DestructiveRole)
            box.addButton('&Cancel', QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(keep)
            box.exec()
            if box.clickedButton() is stop:
                run.stop()
            elif box.clickedButton() is not keep:
                return
        index = self.order.index(cid)
        self._remove_panel(cid)
        if self.current == cid:
            self.current = self.order[min(index, len(self.order) - 1)] if self.order else ''
        self._rebuild()
        self._list_timer.start()
        self._save_open()

    def step(self, delta):
        if not self.order:
            return
        i = self.order.index(self.current) if self.current in self.order else 0
        self.focus_chat(self.order[(i + delta) % len(self.order)])

    def goto(self, n):
        if 0 <= n < len(self.order):
            self.focus_chat(self.order[n])

    def neighbour(self, dx, dy):
        mode = self._effective_mode()
        if mode == 'single' or not self.order:
            self.step(dx or dy)
            return
        cols = len(self.order) if mode == 'columns' else (2 if len(self.order) <= 4 else 3)
        i = self.order.index(self.current) if self.current in self.order else 0
        r, c = divmod(i, cols)
        target = (r + dy) * cols + (c + dx)
        if 0 <= c + dx < cols and 0 <= target < len(self.order):
            self.focus_chat(self.order[target])

    # ================================================================== chats & projects
    def new_chat(self, project='', backend=None, brainstorm=False):
        chat = self.core.store.new_chat(project=project,
                                        backend=backend or self.core.conf.get('default_backend', 'auto'))
        if brainstorm:
            self.core.store.set_meta(chat['id'], mode='brainstorm')
        self.core.chatsChanged.emit()
        self.open_chat(chat['id'], new_panel=True)
        return self.core.store.get_chat(chat['id'])

    def new_chat_in_project(self):
        self.new_chat(project=self._selected_project())

    def rename_chat(self, cid=None):
        cid = cid or self.current
        chat = self.core.store.get_chat(cid) if cid else None
        if chat is None:
            return
        text, ok = QInputDialog.getText(self, 'Rename chat', 'Title:', text=chat['title'])
        if ok and text.strip():
            self.core.store.rename_chat(cid, text)
            self.core.chatsChanged.emit()

    def delete_chat(self, cid=None):
        cid = cid or self.current
        chat = self.core.store.get_chat(cid) if cid else None
        if chat is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle('Delete chat')
        box.setText(f"Delete “{chat['title']}”?")
        box.setInformativeText('The conversation is removed from this computer. Archive it instead to keep it '
                               'out of the way. Deleting cannot be undone.')
        delete = box.addButton('&Delete', QMessageBox.ButtonRole.DestructiveRole)
        archive = box.addButton('&Archive instead', QMessageBox.ButtonRole.ActionRole)
        box.addButton('&Cancel', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is archive:
            self.core.store.set_flag(cid, 'archived', True)
            self.core.chatsChanged.emit()
            return
        if box.clickedButton() is not delete:
            return
        run = self.core.runs.get(cid)
        if run is not None:
            run.stop()
        if cid in self.panels:
            index = self.order.index(cid)
            self._remove_panel(cid)
            if self.current == cid:
                self.current = self.order[min(index, len(self.order) - 1)] if self.order else ''
            self._rebuild()
        run = self.core.runs.pop(cid, None)
        if run is not None:
            run.shutdown()
        self.core.store.delete_chat(cid)
        self.core.chatsChanged.emit()
        self._save_open()

    def new_project(self):
        from .settings_dialog import ProjectDialog
        if ProjectDialog(self.core, None, self).exec() == QDialog.DialogCode.Accepted:
            self.core.chatsChanged.emit()

    def edit_project(self, pid):
        from .settings_dialog import ProjectDialog
        project = self.core.store.project(pid)
        if project is not None and ProjectDialog(self.core, project, self).exec() == QDialog.DialogCode.Accepted:
            self.core.chatsChanged.emit()

    def delete_project(self, pid):
        project = self.core.store.project(pid)
        if project is None:
            return
        n = len(self.core.store.chats(project=pid, archived=None))
        box = QMessageBox(self)
        box.setWindowTitle('Delete project')
        box.setText(f"Delete the project “{project['name']}”?")
        box.setInformativeText(f'Its {n} chat(s) move to “Chats” (outside any project). Built-in projects can be '
                               'restored in Settings › Projects & Memory.')
        delete = box.addButton('&Delete project', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton('&Cancel', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is delete:
            self.core.store.delete_project(pid)
            self.core.chatsChanged.emit()

    # ================================================================== state marks
    def _run_state(self, cid, state):
        self._refresh_icon(cid)
        self._list_timer.start()
        win = self.window()
        if state in ('done', 'error', 'approval') and win is not None and \
                (not win.isActiveWindow() or cid != self.current):
            QApplication.alert(win, 0)
        self._update_title()

    def _refresh_icon(self, cid):
        if cid not in self.order:
            return
        run = self.core.runs.get(cid)
        state = run.state if run is not None else 'idle'
        unread = run.unread if run is not None else False
        i = self.order.index(cid)
        win = self.window()
        if state == 'done' and cid == self.current and win is not None and win.isActiveWindow():
            unread = False
            if run is not None:
                run.unread = False
        self.tabs.setTabIcon(i, state_icon(state, self._frame, unread))
        self.tabs.setTabToolTip(i, f"{(self.core.store.get_chat(cid) or {}).get('title', '')} — {state_text(state)}")

    def _animate(self):
        running = [cid for cid, run in self.core.runs.items() if run.state == 'running']
        if not running or not self.isVisible():
            return
        self._frame = (self._frame + 1) % 12
        for cid in running:
            self._refresh_icon(cid)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                kind, ident = child.data(0, ROLE) or ('', '')
                if ident in running:
                    child.setData(0, STATE, state_icon('running', self._frame))

    def status_text(self) -> str:
        states = [r.state for r in self.core.runs.values()]
        parts = []
        for state, word in (('running', 'working'), ('approval', 'waiting for you'), ('queued', 'queued')):
            if states.count(state):
                parts.append(f'{states.count(state)} {word}')
        return ' · '.join(parts)

    def _update_title(self):
        text = self.status_text()
        self.counts.setText(text)
        win = self.window()
        if isinstance(win, (HubWindow, DetachedWindow)):
            win.setWindowTitle('Agent Hub' + (' — ' + text if text else ''))

    # ================================================================== misc
    def _shortcuts(self):
        def add(seq, slot):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
        add('Ctrl+N', lambda: self.new_chat())
        add('Ctrl+Shift+N', self.new_chat_in_project)
        add('Ctrl+Shift+P', self.new_project)
        add('Ctrl+W', lambda: self.close_chat())
        add('Ctrl+Tab', lambda: self.step(1))
        add('Ctrl+PgDown', lambda: self.step(1))
        add('Ctrl+Shift+Tab', lambda: self.step(-1))
        add('Ctrl+PgUp', lambda: self.step(-1))
        for n in range(1, 10):
            add(f'Ctrl+{n}', lambda n=n: self.goto(n - 1))
        add('Ctrl+\\', self.cycle_mode)
        add('Alt+Left', lambda: self.neighbour(-1, 0))
        add('Alt+Right', lambda: self.neighbour(1, 0))
        add('Alt+Up', lambda: self.neighbour(0, -1))
        add('Alt+Down', lambda: self.neighbour(0, 1))
        add('Ctrl+B', self.toggle_sidebar)
        add('Ctrl+K', self.quick_switch)
        add('Ctrl+F', self._focus_search)
        add('Ctrl+E', self._focus_list)
        add('Ctrl+L', lambda: self.panels[self.current].focus_input() if self.current in self.panels else None)
        add('F2', lambda: self.rename_chat())
        add('Ctrl+Shift+Delete', lambda: self.delete_chat())
        add('Ctrl+Shift+D', self.detachRequested.emit)
        add('Ctrl+,', self.open_settings)
        add('Ctrl+Shift+K', lambda: self.open_organizer('calendar'))
        add('Ctrl+Shift+T', lambda: self.open_organizer('todo'))
        add('Ctrl+Shift+O', lambda: self.open_organizer('mail'))
        add('F1', self.show_help)
        add('Ctrl+/', self.show_help)

    def toggle_sidebar(self):
        on = not self.sidebar.isVisible()
        self.sidebar.setVisible(on)
        if not self._narrow:
            conf = dict(self.core.conf)
            conf['sidebar'] = on
            self.core.save_settings(conf)
        if on:
            self.tree.setFocus()

    def _focus_search(self):
        if not self.sidebar.isVisible():
            self.toggle_sidebar()
        self.search.setFocus()
        self.search.selectAll()

    def _focus_list(self):
        if not self.sidebar.isVisible():
            self.toggle_sidebar()
        self.tree.setFocus()
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def quick_switch(self):
        dialog = QuickSwitch(self.core.store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_id:
            self.open_chat(dialog.result_id, new_panel=dialog.new_panel)

    def open_settings(self, page: str = ''):
        from .settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.core, self)
        if page:
            dialog.select(page)
        dialog.exec()
        self.apply_theme()

    def open_organizer(self, which: str, ident: str = ''):
        """Calendar, to-do or e-mail window (one each, shared with the host)."""
        from .organizer.windows import open_window
        return open_window(which, ident, parent=self.window())

    def show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Agent Hub — keyboard')
        lay = QVBoxLayout(dialog)
        rows = ''.join(f'<tr><td style="padding:3px 14px 3px 0"><b>{html.escape(k)}</b></td>'
                       f'<td>{html.escape(v)}</td></tr>' for k, v in SHORTCUTS)
        label = QLabel(f'<table>{rows}</table>')
        label.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        lay.addWidget(buttons)
        dialog.exec()

    def _save_open(self):
        self.qsettings.setValue('open_chats', list(self.order))
        self.qsettings.setValue('current', self.current)

    def save_state(self):
        self._save_open()
        self.qsettings.setValue('split', self.split.saveState())
        for p in self.panels.values():
            p.save_draft()

    def focus_current(self):
        try:
            if self.current in self.panels:
                self.panels[self.current].focus_input()
            else:
                self.tree.setFocus()
        except RuntimeError:                 # closed in the meantime
            pass

    def shutdown(self):
        self.save_state()
        self.strip.stop()
        for p in list(self.panels.values()):
            p.dispose()


# ====================================================================== containers
class HubWindow(QMainWindow):
    """Standalone window (no host main window)."""

    def __init__(self, core, api=None):
        super().__init__(None)
        self.core = core
        self.setObjectName('AgentHubWindow')
        self.setWindowTitle('Agent Hub')
        self.hub = HubWidget(core, api=api)
        self.setCentralWidget(self.hub)
        self.resize(1200, 820)
        geometry = QSettings('SPM Studio', 'Agent Hub').value('standalone_geometry')
        if geometry:
            self.restoreGeometry(geometry)
        _ensure_on_screen(self)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.hub.focus_current)

    def closeEvent(self, event):
        QSettings('SPM Studio', 'Agent Hub').setValue('standalone_geometry', self.saveGeometry())
        busy = self.core.active_runs()
        if busy:
            answer = QMessageBox.question(self, 'Quit Agent Hub',
                                          f'{len(busy)} chat(s) are still working. Stop them and quit?')
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.hub.shutdown()
        self.core.shutdown()
        event.accept()


def _ensure_on_screen(win):
    """A window remembered on a now-disconnected monitor comes back to the primary one."""
    frame = win.frameGeometry()
    screens = [s.availableGeometry() for s in QApplication.screens()]
    if not screens or any(g.intersects(frame) for g in screens):
        return
    target = QApplication.primaryScreen().availableGeometry()
    win.resize(min(win.width(), target.width() - 40), min(win.height(), target.height() - 40))
    win.move(target.center() - win.rect().center())


class DetachedWindow(QWidget):
    """The hub in a window of its own (any screen, maximizable). Closing it hides it or re-docks it, as set in
    Settings › General; it never stops a running agent."""
    closed = Signal()

    def __init__(self, icon=None):
        super().__init__(None, Qt.WindowType.Window)
        self.setObjectName('AgentHubDetached')
        self.setWindowTitle('Agent Hub')
        if icon is not None:
            self.setWindowIcon(icon)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.resize(900, 820)

    def closeEvent(self, event):
        QSettings('SPM Studio', 'Agent Hub').setValue('detached_geometry', self.saveGeometry())
        event.accept()
        QTimer.singleShot(0, self.closed.emit)


class HubDock(QDockWidget):
    """Native panel in a host main window, with detach / re-dock that keep every state."""
    shownChanged = Signal(bool)

    def __init__(self, core, main_window, api=None, area=Qt.DockWidgetArea.RightDockWidgetArea):
        super().__init__('Agent Hub', main_window)
        self.core = core
        self.main_window = main_window
        self.setObjectName('AgentHubDock')
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetClosable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.hub = HubWidget(core, host_window=main_window, api=api)
        self.detach_button = icon_button('float', 'Open the assistant in its own window (Ctrl+Shift+D)')
        self.detach_button.clicked.connect(self.toggle_detached)
        self.hub.add_container_button(self.detach_button)
        self.hub.detachRequested.connect(self.toggle_detached)
        self.setWidget(self.hub)
        self._placeholder = QLabel('Agent Hub is in its own window.')
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.window_ = None
        self._detached = False
        main_window.addDockWidget(area, self)
        self.setMinimumWidth(340)
        self.visibilityChanged.connect(lambda v: self.shownChanged.emit(self.is_open()))
        self.topLevelChanged.connect(self._top_changed)
        QDockWidget.hide(self)

    # ---- state
    def detached(self) -> bool:
        return self._detached

    def is_open(self) -> bool:
        return self.window_.isVisible() if self._detached and self.window_ is not None else self.isVisible()

    def panel_window(self):
        return self.window_ if self._detached else self

    # ---- detach / re-dock (re-parenting only)
    def detach(self, show=True):
        if self._detached:
            if show:
                self._raise_window()
            return self.window_
        if self.window_ is None:
            self.window_ = DetachedWindow(self.main_window.windowIcon())
            self.window_.closed.connect(self._window_closed)
            geometry = QSettings('SPM Studio', 'Agent Hub').value('detached_geometry')
            if geometry:
                self.window_.restoreGeometry(geometry)
        self.setWidget(self._placeholder)
        self.window_.layout().addWidget(self.hub)
        self.hub.show()
        self._detached = True
        from .svg_icons import set_icon
        set_icon(self.detach_button, 'dock')
        self.detach_button.setToolTip('Dock the assistant back into the main window (Ctrl+Shift+D)')
        QDockWidget.hide(self)
        QSettings('SPM Studio', 'Agent Hub').setValue('detached', True)
        if show:
            self._raise_window()
        self.shownChanged.emit(self.is_open())
        return self.window_

    def redock(self):
        if not self._detached:
            return
        QSettings('SPM Studio', 'Agent Hub').setValue('detached_geometry', self.window_.saveGeometry())
        self.window_.layout().removeWidget(self.hub)
        self.setWidget(self.hub)
        self.hub.show()
        self.window_.hide()
        self._detached = False
        from .svg_icons import set_icon
        set_icon(self.detach_button, 'float')
        self.detach_button.setToolTip('Open the assistant in its own window (Ctrl+Shift+D)')
        if self.isFloating():
            self.setFloating(False)
        QSettings('SPM Studio', 'Agent Hub').setValue('detached', False)
        QDockWidget.show(self)
        self.raise_()
        self.hub.focus_current()
        self.shownChanged.emit(True)

    def toggle_detached(self):
        self.redock() if self._detached else self.detach()

    def _raise_window(self):
        w = self.window_
        w.show()
        if w.isMinimized():
            w.showNormal()
        _ensure_on_screen(w)
        w.raise_()
        w.activateWindow()
        QTimer.singleShot(0, self.hub.focus_current)

    def _window_closed(self):
        if self.core.conf.get('detached_close') == 'redock':
            self.redock()
        else:
            self.shownChanged.emit(False)

    def _top_changed(self, floating):
        # dragging the dock out of the main window turns it into a real window once the drag is over
        if floating:
            QTimer.singleShot(0, self._float_to_window)

    def _float_to_window(self):
        if not self.isFloating():
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            QTimer.singleShot(120, self._float_to_window)
            return
        self.setFloating(False)
        self.detach()

    # ---- show / hide as one thing
    def open_panel(self):
        if self._detached:
            self._raise_window()
        else:
            QDockWidget.show(self)
            if not getattr(self, '_sized', False):           # a comfortable width the first time
                self._sized = True
                try:
                    self.main_window.resizeDocks([self], [460], Qt.Orientation.Horizontal)
                except RuntimeError:
                    pass
            self.raise_()
            QTimer.singleShot(0, self.hub.focus_current)
        self.shownChanged.emit(True)

    def close_panel(self):
        if self._detached:
            self.window_.hide()
        else:
            QDockWidget.hide(self)
        self.shownChanged.emit(False)

    def toggle(self):
        if self.is_open() and (not self._detached or self.window_.isActiveWindow()):
            self.close_panel()
        else:
            self.open_panel()

    def restore_saved(self):
        if str(QSettings('SPM Studio', 'Agent Hub').value('detached', 'false')).lower() == 'true':
            self.detach(show=False)

    def closeEvent(self, event):
        self.hub.save_state()
        event.accept()                                  # hiding only: chats keep running

    def shutdown(self):
        self.hub.shutdown()
        if self.window_ is not None:
            try:
                QSettings('SPM Studio', 'Agent Hub').setValue('detached_geometry', self.window_.saveGeometry())
                self.window_.hide()
                self.window_.deleteLater()
            except RuntimeError:
                pass
