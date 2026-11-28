"""Agent Hub settings (one window, categories on the left) and the project editor."""
from __future__ import annotations

import html
import json
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .. import settings_store as ss
from ..host import current as current_host
from ..scheduler import GROUP_LABELS

FOLDERS = [('general', 'Its own folder (in the Agent Hub data)')]
PAGES = ['General', 'Appearance & Theme', 'AI Providers & Accounts', 'Pi Agent', 'Models & Routing',
         'Brainstorming', 'Voice & Transcription', 'Connections & Integrations', 'Projects & Memory',
         'Permissions & Security', 'Usage & Budgets', 'Local Hardware Monitoring', 'Desktop Integration',
         'Remote Access', 'Updates & Diagnostics']


def _hint(text):
    label = QLabel(text)
    label.setObjectName('hubHint')
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setOpenExternalLinks(True)
    return label


class _Job(QThread):
    done = Signal(object)
    line = Signal(str)
    progress = Signal(int)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.line.emit, self.progress.emit))
        except Exception as exc:
            self.done.emit(exc)


def _safe(callback):
    def call(*args):
        try:
            callback(*args)
        except RuntimeError:          # the dialog was closed meanwhile
            pass
    return call


# ====================================================================== project
class ProjectDialog(QDialog):
    def __init__(self, core, project=None, parent=None):
        super().__init__(parent)
        self.core = core
        self.project = project
        self.setWindowTitle('Project settings' if project else 'New project')
        self.resize(580, 600)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit((project or {}).get('name', ''))
        self.folder = QComboBox()
        for key, label in FOLDERS + [(k, v) for k, v in getattr(current_host(), 'FOLDERS', [])]:
            self.folder.addItem(label, key)
        self.folder.addItem('Another folder…', '__custom__')
        current = (project or {}).get('folder', 'general') or 'general'
        i = self.folder.findData(current)
        if i < 0:
            self.folder.insertItem(self.folder.count() - 1, current, current)
            i = self.folder.findData(current)
        self.folder.setCurrentIndex(i)
        self.folder.activated.connect(self._folder)
        form.addRow('Name', self.name)
        form.addRow('Works in', self.folder)
        lay.addLayout(form)
        lay.addWidget(QLabel('Instructions for the assistant in this project'))
        self.instructions = QPlainTextEdit((project or {}).get('instructions', ''))
        self.instructions.setPlaceholderText('e.g. “Answer in French. Our lab uses Nanonis .sxm files.”')
        lay.addWidget(self.instructions, 1)
        lay.addWidget(QLabel('Project memory — notes the assistant keeps in every chat of this project'))
        self.notes = QPlainTextEdit((project or {}).get('notes', ''))
        self.notes.setPlaceholderText('Facts, decisions and preferences to remember. You control this text.')
        lay.addWidget(self.notes, 1)
        lay.addWidget(QLabel('Words that suggest this project for a new chat (comma separated)'))
        self.keywords = QLineEdit(', '.join((project or {}).get('keywords', [])))
        lay.addWidget(self.keywords)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _folder(self, _i):
        if self.folder.currentData() == '__custom__':
            chosen = QFileDialog.getExistingDirectory(self, 'Folder of this project', str(Path.home()))
            if chosen:
                self.folder.insertItem(self.folder.count() - 1, chosen, chosen)
                self.folder.setCurrentIndex(self.folder.findData(chosen))
            else:
                self.folder.setCurrentIndex(0)

    def _save(self):
        fields = {'name': self.name.text(), 'instructions': self.instructions.toPlainText(),
                  'notes': self.notes.toPlainText(), 'folder': self.folder.currentData() or 'general',
                  'keywords': [k.strip() for k in self.keywords.text().split(',')]}
        try:
            if self.project:
                self.core.store.update_project(self.project['id'], **fields)
            else:
                p = self.core.store.add_project(fields['name'], fields['instructions'], fields['folder'])
                self.core.store.update_project(p['id'], notes=fields['notes'], keywords=fields['keywords'])
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, 'Project', str(exc))
            return
        self.accept()


# ====================================================================== settings
class SettingsDialog(QDialog):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.host = current_host()
        self.conf = dict(core.conf)
        self.jobs = []
        self.setWindowTitle('Agent Hub settings')
        self.resize(900, 680)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search settings…')
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search)
        lay.addLayout(top)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.nav = QListWidget()
        self.nav.setMaximumWidth(230)
        self.stack = QStackedWidget()
        self.page_text = {}
        builders = [self._general, self._appearance, self._providers, self._pi, self._routing, self._brainstorm,
                    self._voice, self._connections, self._projects, self._permissions, self._usage, self._monitor,
                    self._desktop, self._remote, self._diagnostics]
        self.pages = list(PAGES)
        self.extra_pages = []                    # (title, widget, save(conf) | None)
        # 0.3: calendar, to-do, e-mail and the assistant's use of them
        from .organizer.settings_pages import PAGES as ORGANIZER_PAGES
        for cls in ORGANIZER_PAGES:
            self.pages.insert(self.pages.index('Connections & Integrations') + 1 + len(self.extra_pages), cls.title)
            builders.insert(self.pages.index(cls.title),
                            lambda cls=cls: self._extra(cls.title, lambda parent, c=cls: c(self.core.organizer,
                                                                                           self.conf, parent)))
        # host pages (e.g. SPM Studio: literature sources, its Pi setup)
        try:
            host_pages = list(self.host.settings_pages() or [])
        except Exception:
            host_pages = []
        for title, factory, saver in host_pages:
            self.pages.insert(self.pages.index('Connections & Integrations') + 1, title)
            builders.insert(self.pages.index(title), lambda f=factory, tt=title, sv=saver: self._extra(tt, f, sv))
        for name, build in zip(self.pages, builders):
            page = build()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
            self.nav.addItem(name)
            words = []
            for kind in (QLabel, QCheckBox, QRadioButton, QPushButton):
                words += [w.text() + ' ' + w.toolTip() for w in page.findChildren(kind)]
            for combo in page.findChildren(QComboBox):
                words += [combo.itemText(i) for i in range(combo.count())]
            self.page_text[name] = ' '.join(words).lower()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        split.addWidget(self.nav)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def select(self, name: str):
        for i in range(self.nav.count()):
            if self.nav.item(i).text().lower().startswith(name.lower()):
                self.nav.setCurrentRow(i)
                return

    def _filter(self, text):
        text = text.lower().strip()
        first = None
        for i, name in enumerate(self.pages):
            match = not text or text in name.lower() or text in self.page_text.get(name, '')
            self.nav.item(i).setHidden(not match)
            if match and first is None:
                first = i
        if first is not None:
            self.nav.setCurrentRow(first)

    def _job(self, fn, done, status_label=None, bar=None):
        job = _Job(fn, self.core)              # parented to the engine: survives this dialog
        if status_label is not None:
            job.line.connect(_safe(status_label.setText))
        if bar is not None:
            job.progress.connect(_safe(bar.setValue))
        job.done.connect(_safe(done))
        job.finished.connect(job.deleteLater)
        self.jobs.append(job)
        job.start()

    def _extra(self, title, factory, saver=None):
        """A page made by a factory (organizer pages, host pages); ``save(conf)`` runs on Save."""
        try:
            page = factory(self)
        except Exception as exc:                 # a broken page never breaks the settings
            page = QWidget()
            QVBoxLayout(page).addWidget(_hint(f'This page could not be built: {html.escape(str(exc))}'))
        self.extra_pages.append((title, page, saver or getattr(page, 'save', None)))
        return page

    @staticmethod
    def _radios(parent_layout, options, current, group_parent):
        group = QButtonGroup(group_parent)
        for i, (key, text) in enumerate(options):
            b = QRadioButton(text)
            b.setProperty('key', key)
            b.setChecked(current == key)
            group.addButton(b, i)
            parent_layout.addWidget(b)
        return group

    # ---------------------------------------------------------------- general
    def _general(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_hint('Agent Hub is one assistant shown in several places: the panel inside '
                          f'{html.escape(self.host.label)}, a detached window and the standalone app. They share '
                          'chats, projects and settings on this computer.'))
        if self.host.name != 'standalone':
            box = QGroupBox(f'Inside {self.host.label}')
            b = QVBoxLayout(box)
            self.open_group = self._radios(b, [('panel', 'Open as a panel in the main window (default)'),
                                               ('window', 'Open in its own window')],
                                           self.conf['open_mode'], self)
            self.close_group = self._radios(b, [('hide', 'Closing the detached window hides it (chats keep running)'),
                                                ('redock', 'Closing the detached window docks it back')],
                                            self.conf['detached_close'], self)
            v.addWidget(box)
        self.enter = QCheckBox('Enter sends the message (Shift+Enter: new line). Off: Ctrl+Enter sends.')
        self.enter.setChecked(self.conf['send_with_enter'])
        v.addWidget(self.enter)
        v.addStretch(1)
        return page

    # ---------------------------------------------------------------- appearance
    def _appearance(self):
        page = QWidget()
        v = QVBoxLayout(page)
        if self.host.name != 'standalone':
            v.addWidget(_hint(f'Inside {html.escape(self.host.label)} the hub follows its active theme and Theme '
                              'Studio profiles live (chats keep running when the theme changes).'))
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItem('Light', 'light')
        self.theme.addItem('Dark', 'dark')
        cur = self.conf['standalone_theme']
        if cur not in ('light', 'dark'):
            self.theme.addItem(Path(cur).name, cur)
        self.theme.setCurrentIndex(max(0, self.theme.findData(cur)))
        imp = QPushButton('Import a theme file (SPM Studio / Theme Studio JSON)…')
        imp.clicked.connect(self._import_theme)
        exp = QPushButton('Export the current theme…')
        exp.clicked.connect(self._export_theme)
        form.addRow('Standalone theme', self.theme)
        form.addRow('', imp)
        form.addRow('', exp)
        self.scale = QSpinBox()
        self.scale.setRange(70, 200)
        self.scale.setSuffix(' %')
        self.scale.setValue(self.conf['font_scale'])
        form.addRow('Text size', self.scale)
        v.addLayout(form)
        v.addWidget(_hint('Themes use semantic tokens (background, surface, foreground, accent, muted, sidebar, '
                          'input, border, selection, warning, danger, success, radius, font_family, font_size, and '
                          'hub_* tokens such as hub_user_bubble, hub_code_bg, hub_status_running, hub_graph_1). '
                          'Older themes get defaults for missing tokens.'))
        v.addStretch(1)
        return page

    def _import_theme(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Theme file', str(Path.home()), 'Theme (*.json)')
        if not path:
            return
        from . import theme
        try:
            theme.load_theme_file(Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'Theme', f'Not a readable theme: {exc}')
            return
        target = Path(self.core.root) / 'themes' / Path(path).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(Path(path).read_text(encoding='utf8'), encoding='utf8')
        self.theme.addItem(target.name, str(target))
        self.theme.setCurrentIndex(self.theme.count() - 1)

    def _export_theme(self):
        from . import theme
        path, _ = QFileDialog.getSaveFileName(self, 'Export theme', str(Path.home() / 'agent-hub-theme.json'),
                                              'Theme (*.json)')
        if path:
            Path(path).write_text(json.dumps({'name': 'Agent Hub theme', 'tokens': theme.tokens()}, indent=1),
                                  encoding='utf8')

    # ---------------------------------------------------------------- providers
    def _providers(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_hint('Connect several providers and accounts at once. API keys go to the system keyring '
                          '(never to files, logs or exports). A website subscription (claude.ai, chatgpt.com) is '
                          'not an API: use the official agents below for subscriptions.'))
        box = QGroupBox('Agents found on this computer (they use their own sign-in)')
        b = QVBoxLayout(box)
        self.agents_label = QLabel('')
        self.agents_label.setWordWrap(True)
        b.addWidget(self.agents_label)
        v.addWidget(box)
        box2 = QGroupBox('Direct connections (API keys, local servers)')
        b2 = QVBoxLayout(box2)
        self.conn_list = QListWidget()
        b2.addWidget(self.conn_list)
        row = QHBoxLayout()
        for text, slot in (('Add…', self._add_connection), ('Test / refresh models', self._test_connection),
                           ('Default model…', self._set_model), ('Remove', self._remove_connection)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        b2.addLayout(row)
        self.conn_status = _hint('')
        b2.addWidget(self.conn_status)
        v.addWidget(box2)
        v.addWidget(_hint('<b>Capabilities</b>: Pi, Claude Code and Codex are agents (files, commands, tools, with '
                          'approvals). API and local connections are chat-only. Usage quotas of subscriptions are '
                          'not exposed by the providers; see Usage & Budgets.'))
        v.addStretch(1)
        self._fill_connections()
        return page

    def _fill_connections(self):
        agents = [b for b in self.core.backends if b['tools']]
        self.agents_label.setText('<br>'.join(f"<b>{html.escape(b['label'])}</b> — {html.escape(b.get('note', ''))}"
                                              for b in agents) or 'None found (Pi, Claude Code, Codex).')
        self.conn_list.clear()
        for c in ss.load_ai()['connections']:
            meta = ss.PROVIDERS.get(c['provider'], {})
            key = ' · key stored' if meta.get('kind') == 'api' and ss.api_key(c) else (
                ' · NO KEY' if meta.get('kind') == 'api' else '')
            item = QListWidgetItem(f"{c['label']} — {c.get('model') or 'no model chosen'} · {c.get('base')}{key}")
            item.setData(Qt.ItemDataRole.UserRole, c['id'])
            self.conn_list.addItem(item)

    def _selected_conn(self):
        item = self.conn_list.currentItem()
        if item is None:
            return None
        return next((c for c in ss.load_ai()['connections'] if c['id'] == item.data(Qt.ItemDataRole.UserRole)), None)

    def _add_connection(self):
        names = [f"{meta['label']}" for meta in ss.PROVIDERS.values()]
        keys = list(ss.PROVIDERS)
        choice, ok = QInputDialog.getItem(self, 'Add a connection', 'Provider', names, 0, False)
        if not ok:
            return
        provider = keys[names.index(choice)]
        meta = ss.PROVIDERS[provider]
        base = meta['base']
        if meta['kind'] in ('custom', 'local'):
            base, ok = QInputDialog.getText(self, 'Endpoint', 'Address (local http://127.0.0.1:… or https://…)',
                                            text=base)
            if not ok:
                return
        key = ''
        if meta['kind'] in ('api', 'custom'):
            key, ok = QInputDialog.getText(self, 'API key', f'{meta["label"]}: API key (stored in the system '
                                           'keyring; leave empty for none)', QLineEdit.EchoMode.Password)
            if not ok:
                return
        label, ok = QInputDialog.getText(self, 'Name', 'Name of this account (e.g. “Work”)', text=meta['label'])
        if not ok:
            return
        try:
            conn = ss.add_connection(provider, label=label, base=base, api_key=key)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, 'Connection', str(exc))
            return
        self._fill_connections()
        self.conn_status.setText(f"Added {html.escape(conn['label'])}. Press Test / refresh models, then choose a "
                                 'default model.')

    def _test_connection(self):
        conn = self._selected_conn()
        if conn is None:
            return
        self.conn_status.setText('Testing…')

        def work(log, progress):
            return ss.list_models(conn)

        def done(result):
            if isinstance(result, Exception):
                self.conn_status.setText('Connection failed: ' + html.escape(str(result)[:300]))
                return
            ss.update_connection(conn['id'], models=result[:400])
            self.conn_status.setText(f'OK — {len(result)} models.' + (' Choose one with Default model…' if
                                                                      not conn.get('model') else ''))
        self._job(work, done)

    def _set_model(self):
        conn = self._selected_conn()
        if conn is None:
            return
        models = conn.get('models') or []
        if models:
            model, ok = QInputDialog.getItem(self, 'Default model', conn['label'], models,
                                             max(0, models.index(conn['model'])) if conn.get('model') in models else 0,
                                             True)
        else:
            model, ok = QInputDialog.getText(self, 'Default model', 'Model id', text=conn.get('model', ''))
        if ok and model.strip():
            ss.update_connection(conn['id'], model=model.strip())
            self._fill_connections()
            self.core.refresh_backends()

    def _remove_connection(self):
        conn = self._selected_conn()
        if conn and QMessageBox.question(self, 'Remove', f"Remove {conn['label']} and its stored key?") == \
                QMessageBox.StandardButton.Yes:
            ss.remove_connection(conn['id'])
            self._fill_connections()
            self.core.refresh_backends()

    # ---------------------------------------------------------------- pi
    def _pi(self):
        page = QWidget()
        v = QVBoxLayout(page)
        managed = None
        try:
            managed = self.host.managed_pi()
        except Exception:
            pass
        pi = next((b for b in self.core.backends if b['key'] == 'pi'), None)
        if managed:
            v.addWidget(_hint(f"<b>{html.escape(managed.get('label', 'Pi'))}</b> — set up by "
                              f"{html.escape(self.host.label)}. {html.escape(managed.get('note', ''))}"))
            router = managed.get('router') or {}
            if router:
                v.addWidget(_hint('Router: Fast ' + html.escape(', '.join(router.get('fast', [])) or '—') +
                                  ' · Smart ' + html.escape(', '.join(router.get('smart', [])) or '—') +
                                  ' · Judge ' + html.escape(str(router.get('judge', '—'))) +
                                  ' — Pi routes each request itself; the hub does not route it a second time.'))
        elif pi:
            v.addWidget(_hint(f"<b>Your own Pi</b> ({html.escape(pi.get('executable', ''))}) is used as it is: its "
                              '~/.pi configuration, models, extensions, router and skills are read by Pi and never '
                              'modified by Agent Hub.'))
        else:
            v.addWidget(_hint('No Pi found. Pi is optional: direct connections and other agents work without it.'))
        row = QHBoxLayout()
        setup = QPushButton(f'Set up Pi in {self.host.label}…' if self.host.name != 'standalone' else
                            'Install Pi (instructions)…')
        setup.clicked.connect(self._pi_setup)
        row.addWidget(setup)
        refresh = QPushButton('Look again')
        refresh.clicked.connect(lambda: (self.core.refresh_backends(), self._fill_connections()))
        row.addWidget(refresh)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(_hint('Recommended profile (when installed by SPM Studio\'s wizard): pi-shift-router with '
                          'Fast / Smart tiers, a local Judge (small Ollama model, thinking off) and pi-subagents. '
                          'The Judge classifies requests; it is not used as a conversation model.'))
        v.addStretch(1)
        return page

    def _pi_setup(self):
        if not self.host.open_setup(self):
            QMessageBox.information(self, 'Pi', 'Install Pi with npm (Node.js 20+):\n\n'
                                    '  npm install -g @earendil-works/pi-coding-agent\n\n'
                                    'then run “pi” once in a terminal to sign in, and press Look again. Agent Hub '
                                    'uses your ~/.pi configuration without changing it.')
        self.core.refresh_backends()
        self._fill_connections()

    # ---------------------------------------------------------------- routing
    def _routing(self):
        page = QWidget()
        v = QVBoxLayout(page)
        form = QFormLayout()
        self.profile = QComboBox()
        for key, label in (('eco', 'Eco — local or low-cost first'), ('balanced', 'Balanced — by task size'),
                           ('performance', 'Performance — stronger models first'),
                           ('local', 'Local only — never the cloud (no cloud fallback or transcription)'),
                           ('manual', 'Manual — only the model you pick, no automatic switching')):
            self.profile.addItem(label, key)
        self.profile.setCurrentIndex(max(0, self.profile.findData(self.conf['routing_profile'])))
        form.addRow('Routing profile', self.profile)
        self.default_backend = QComboBox()
        form.addRow('New chats use', self.default_backend)
        self.preference = QLineEdit(', '.join(self.conf['preference']))
        self.preference.setToolTip('Order tried by Auto for large tasks: pi, claude-code, codex')
        form.addRow('Agent order for large tasks', self.preference)
        self.local_small = QCheckBox('Use a local model for small requests when one is installed (saves tokens)')
        self.local_small.setChecked(self.conf['local_for_small'])
        form.addRow('', self.local_small)
        v.addLayout(form)
        box = QGroupBox('Requests running at the same time, per account')
        bf = QFormLayout(box)
        self.limits = {}
        for group in ('anthropic', 'openai', 'pi', 'local', 'api'):
            spin = QSpinBox()
            spin.setRange(1, 8)
            spin.setValue(int(self.conf['limits'].get(group, 1)))
            self.limits[group] = spin
            bf.addRow(GROUP_LABELS[group].capitalize(), spin)
        bf.addRow(_hint('A Claude Pro or ChatGPT Plus subscription shares one usage limit between the website and '
                        'the agents: 1 long run at a time is the safe default.'))
        v.addWidget(box)
        box2 = QGroupBox('When the chosen model is busy')
        b2 = QVBoxLayout(box2)
        self.busy_group = self._radios(b2, [('ask', 'Ask me which free model to use'),
                                            ('auto', 'Use another free model automatically'),
                                            ('queue', 'Wait until it is free')], self.conf['when_busy'], self)
        v.addWidget(box2)
        row = QHBoxLayout()
        local = QPushButton('Suggest a local model for this computer…')
        local.clicked.connect(self._suggest_local)
        row.addWidget(local)
        row.addStretch(1)
        v.addLayout(row)
        self.local_bar = QProgressBar()
        self.local_bar.hide()
        self.local_status = _hint('')
        v.addWidget(self.local_bar)
        v.addWidget(self.local_status)
        v.addStretch(1)
        self._fill_defaults()
        return page

    def _fill_defaults(self):
        current = self.conf['default_backend']
        self.default_backend.clear()
        self.default_backend.addItem('Auto — choose by task size and free capacity', 'auto')
        for b in self.core.backends:
            self.default_backend.addItem(b['label'], b['key'])
        self.default_backend.setCurrentIndex(max(0, self.default_backend.findData(current)))

    def _suggest_local(self):
        def work(log, progress):
            from ..agents import ollama
            from ..agents import platform_util as pu
            hw = pu.hardware()
            names = [m.get('name', '') for m in ollama.installed()]
            return hw, ollama.suggest(hw, names), bool(ollama.running()), bool(ollama.executable()), names
        self.local_status.setText('Checking RAM, GPU and Ollama…')
        self._job(work, self._suggested)

    def _suggested(self, result):
        if isinstance(result, Exception):
            self.local_status.setText('Could not check this computer: ' + html.escape(str(result)))
            return
        hw, best, running, installed, names = result
        gb = 1024 ** 3
        text = (f"{hw.get('gpu', 'no GPU')}" + (f" ({hw['gpu_memory_bytes'] / gb:.0f} GB)" if hw.get('gpu_memory_bytes')
                                                else '') + f", RAM {(hw.get('ram_bytes') or 0) / gb:.0f} GB.")
        if names:
            text += '<br>Installed: ' + html.escape(', '.join(names[:8])) + '.'
        if not best:
            self.local_status.setText(text + '<br>No conversational local model fits well; cloud models are used.')
            return
        if not installed:
            self.local_status.setText(text + f"<br>Suggested: <b>{best['tag']}</b>. Install Ollama first "
                                             '(ollama.com, or the SPM Studio wizard), then try again.')
            return
        if best['installed']:
            self.local_status.setText(text + f"<br><b>{best['tag']}</b> is installed and used for small requests.")
            return
        if QMessageBox.question(self, 'Download a local model?',
                                f"{best['tag']} ({best['params']}, about {best['gb']} GB, runs on {best['runs_on']}) "
                                f"fits this computer — {best['note']}. Download it with Ollama now?") != \
                QMessageBox.StandardButton.Yes:
            self.local_status.setText(text + f"<br>Suggested: <b>{best['tag']}</b>.")
            return
        tag = best['tag']

        def pull(log, progress):
            from ..agents import ollama
            if not ollama.running() and not ollama.start():
                raise RuntimeError('Ollama is installed but does not start')
            ollama.pull(tag, log, progress)
            return tag

        def pulled(r):
            self.local_bar.hide()
            if isinstance(r, Exception):
                self.local_status.setText('Download failed: ' + html.escape(str(r)))
            else:
                self.local_status.setText(f'<b>{r}</b> downloaded; it now appears in the model list.')
                self.core.refresh_backends()
                self._fill_defaults()
        self.local_bar.setRange(0, 100)
        self.local_bar.show()
        self._job(pull, pulled, self.local_status, self.local_bar)

    # ---------------------------------------------------------------- brainstorming
    def _brainstorm(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_hint('Brainstorming refines an idea with an economical model before any expensive work. The '
                          'application blocks file changes, commands, installs, pushes, sub-agents and messages in '
                          'brainstorming chats (Claude Code runs in plan mode, Codex read-only, Pi behind the '
                          'approval gate). “Generate final prompt” writes an editable implementation prompt; '
                          '“Start execution” runs it only after you approve.'))
        form = QFormLayout()
        self.bs_backend = QComboBox()
        self.bs_backend.addItem('Auto — local conversational model, else a cheap API, else an agent read-only', 'auto')
        for b in self.core.backends:
            self.bs_backend.addItem(b['label'], b['key'])
        self.bs_backend.setCurrentIndex(max(0, self.bs_backend.findData(self.conf['brainstorm_backend'])))
        form.addRow('Brainstorming model', self.bs_backend)
        self.bs_research = QCheckBox('Allow bounded read-only research (reading files, web search)')
        self.bs_research.setChecked(self.conf['brainstorm_research'])
        form.addRow('', self.bs_research)
        self.bs_calls = QSpinBox()
        self.bs_calls.setRange(1, 200)
        self.bs_calls.setValue(self.conf['brainstorm_max_tool_calls'])
        form.addRow('Read-only tool calls per reply', self.bs_calls)
        self.bs_budget = QSpinBox()
        self.bs_budget.setRange(0, 5_000_000)
        self.bs_budget.setSingleStep(10000)
        self.bs_budget.setSuffix(' tokens')
        self.bs_budget.setValue(self.conf['brainstorm_budget_tokens'])
        form.addRow('Budget per brainstorming chat (0 = none)', self.bs_budget)
        v.addLayout(form)
        v.addStretch(1)
        return page

    # ---------------------------------------------------------------- voice
    def _voice(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_hint('Click the microphone in the message box to record, click again to stop (Esc cancels), '
                          'or hold the push-to-talk key. The text is inserted for editing; nothing is sent '
                          'automatically. Audio is kept in memory only.'))
        form = QFormLayout()
        self.voice_backend = QComboBox()
        self.voice_backend.addItem('Offline (Vosk) — audio never leaves this computer', 'vosk')
        self.voice_backend.addItem('Cloud (OpenAI-compatible transcription of one of your connections)', 'cloud')
        self.voice_backend.setCurrentIndex(max(0, self.voice_backend.findData(self.conf['voice_backend'])))
        form.addRow('Transcription', self.voice_backend)
        self.voice_lang = QComboBox()
        for code, name in (('en', 'English'), ('fr', 'Français'), ('de', 'Deutsch')):
            self.voice_lang.addItem(name, code)
        self.voice_lang.setCurrentIndex(max(0, self.voice_lang.findData(self.conf['voice_language'])))
        form.addRow('Language', self.voice_lang)
        self.voice_dev = QComboBox()
        self.voice_dev.addItem('System default microphone', '')
        from ..voice import speech
        for dev_id, desc in speech.input_devices():
            self.voice_dev.addItem(desc, dev_id)
        self.voice_dev.setCurrentIndex(max(0, self.voice_dev.findData(self.conf['voice_device'])))
        form.addRow('Microphone', self.voice_dev)
        self.voice_key = QLineEdit(self.conf['voice_shortcut'])
        form.addRow('Push-to-talk key (hold)', self.voice_key)
        self.voice_conn = QComboBox()
        self.voice_conn.addItem('—', '')
        for c in ss.load_ai()['connections']:
            if ss.PROVIDERS.get(c['provider'], {}).get('wire') == 'openai':
                self.voice_conn.addItem(c['label'], c['id'])
        self.voice_conn.setCurrentIndex(max(0, self.voice_conn.findData(self.conf['voice_cloud_connection'])))
        form.addRow('Cloud connection', self.voice_conn)
        self.voice_consent = QCheckBox('I consent to sending recordings to this connection for transcription')
        self.voice_consent.setChecked(self.conf['voice_cloud_consent'])
        form.addRow('', self.voice_consent)
        v.addLayout(form)
        status = []
        status.append('vosk package: ' + ('installed' if speech.vosk_installed() else
                                          'missing (pip install vosk) — needed for offline transcription'))
        for code in ('en', 'fr', 'de'):
            status.append(f"{code} model: {'downloaded' if speech.model_available(code) else 'not downloaded (asked on first use)'}")
        v.addWidget(_hint('<br>'.join(status)))
        v.addStretch(1)
        return page

    # ---------------------------------------------------------------- connections
    def _connections(self):
        page = QWidget()
        v = QVBoxLayout(page)
        integrations = []
        try:
            integrations = self.host.integrations()
        except Exception:
            pass
        if integrations:
            box = QGroupBox(f'From {self.host.label}')
            b = QVBoxLayout(box)
            for item in integrations:
                row = QHBoxLayout()
                lab = QLabel(f"<b>{html.escape(item['label'])}</b> — {html.escape(item.get('status', ''))}")
                lab.setWordWrap(True)
                row.addWidget(lab, 1)
                if item.get('open'):
                    btn = QPushButton('Settings…')
                    btn.clicked.connect(lambda _=False, f=item['open']: (f(self), self.core.refresh_backends()))
                    row.addWidget(btn)
                b.addLayout(row)
            b.addWidget(_hint('One source of truth: these buttons edit the same settings the host uses (no second '
                              'copy).'))
            v.addWidget(box)
        gh = QGroupBox('GitHub')
        g = QVBoxLayout(gh)
        g.addWidget(_hint('Everyone signs in with <b>their own</b> GitHub account (official GitHub CLI); GitHub '
                          'decides what that account may do. Your repositories: push, pull requests, releases. '
                          'Others: fork + pull request. Pushes and releases ask first unless full access is on.'))
        self.gh_state = QLabel('…')
        self.gh_state.setWordWrap(True)
        g.addWidget(self.gh_state)
        row = QHBoxLayout()
        self.gh_in = QPushButton('Sign in with GitHub…')
        self.gh_in.clicked.connect(lambda: self._gh_terminal(False))
        self.gh_out = QPushButton('Sign out')
        self.gh_out.clicked.connect(lambda: self._gh_terminal(True))
        check = QPushButton('Check again')
        check.clicked.connect(self._gh_check)
        for w in (self.gh_in, self.gh_out, check):
            row.addWidget(w)
        row.addStretch(1)
        g.addLayout(row)
        v.addWidget(gh)
        v.addWidget(_hint('E-mail accounts, calendar sync and the to-do list have their own pages (left). Claude '
                          'Code also uses the MCP servers you configured for it; any MCP tool that sends or '
                          'publishes something asks you every time.'))
        v.addStretch(1)
        self._gh_check()
        return page

    def _gh_check(self):
        self.gh_state.setText('Checking…')
        self._job(lambda log, progress: self.core.refresh_github(), self._gh_show)

    def _gh_show(self, status):
        from .. import github
        if isinstance(status, Exception):
            self.gh_state.setText(html.escape(str(status)))
            return
        if not status.get('installed'):
            self.gh_state.setText('The GitHub CLI (gh) is not installed. Install it with: <code>' +
                                  html.escape(github.install_hint()) + '</code>, then press Check again.')
        elif status.get('login'):
            self.gh_state.setText(f"Signed in as <b>{html.escape(status['login'])}</b>.")
        else:
            self.gh_state.setText('Not signed in.' + (f" ({html.escape(status['error'])})" if status.get('error') else ''))
        self.gh_in.setEnabled(bool(status.get('installed')))
        self.gh_out.setEnabled(bool(status.get('login')))

    def _gh_terminal(self, sign_out):
        from .. import github
        from ..agents import platform_util as pu
        script = github.sign_in_script(Path(self.core.root) / 'launchers', sign_out=sign_out)
        manual = pu.open_terminal(script)
        if manual:
            QMessageBox.information(self, 'GitHub', 'Run this in a terminal:\n\n' + manual)

    # ---------------------------------------------------------------- projects
    def _projects(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_hint('A new chat outside a project is matched against the projects (their words and names). '
                          'When one clearly fits, the hub proposes to move it there. Each project has '
                          'instructions and a memory (notes) you control.'))
        self.sort_group = self._radios(v, [('ask', 'Propose to move it (one key: Enter)'),
                                           ('auto', 'Move it automatically'), ('off', 'Never')],
                                       self.conf['auto_sort'], self)
        restore = QPushButton('Restore the built-in projects')
        restore.clicked.connect(self._restore)
        v.addWidget(restore, 0, Qt.AlignmentFlag.AlignLeft)
        exp = QPushButton('Export all chats and projects (JSON, no keys)…')
        exp.clicked.connect(self._export_all)
        v.addWidget(exp, 0, Qt.AlignmentFlag.AlignLeft)
        if hasattr(self.host, 'classic_histories'):
            imp = QPushButton(f'Import the conversations of the classic {self.host.label} panel')
            imp.clicked.connect(self._import_classic)
            v.addWidget(imp, 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch(1)
        return page

    def _restore(self):
        n = self.core.store.restore_default_projects()
        self.core.chatsChanged.emit()
        QMessageBox.information(self, 'Projects', f'{n} built-in project(s) added back.' if n else
                                'All built-in projects are already there.')

    def _export_all(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export', str(Path.home() / 'agent-hub-export.json'), 'JSON (*.json)')
        if not path:
            return
        data = {'projects': self.core.store.projects(), 'chats': self.core.store.chats(archived=None)}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf8')

    def _import_classic(self):
        try:
            histories = self.host.classic_histories()
        except Exception as exc:
            QMessageBox.warning(self, 'Import', str(exc))
            return
        n = self.core.store.import_classic(histories)
        self.core.chatsChanged.emit()
        QMessageBox.information(self, 'Import', f'{n} conversation(s) imported into “Chats”.' if n else
                                'Nothing new to import (already imported, or no conversation).')

    # ---------------------------------------------------------------- permissions
    def _permissions(self):
        page = QWidget()
        v = QVBoxLayout(page)
        folders = ', '.join(str(p) for p in self.host.app_folders()) or 'none'
        v.addWidget(_hint('Always writable without asking: the project\'s working folder and the host folders ('
                          + html.escape(folders) + '). Choose where else the assistant may work without asking. '
                          'Outside these folders, and for commands that change things, pushes and deletions, it '
                          'asks above the message box (Allow / Always allow / Deny).'))
        self.mode_group = self._radios(v, [('app', 'These folders only'),
                                           ('folders', 'These folders + the folders below'),
                                           ('everywhere', 'Everywhere in my home folder')],
                                       self.conf['access_mode'], self)
        self.folders = QListWidget()
        for f in self.conf['extra_folders']:
            self.folders.addItem(f)
        row = QHBoxLayout()
        add = QPushButton('Add folder…')
        add.clicked.connect(self._add_folder)
        rem = QPushButton('Remove')
        rem.clicked.connect(lambda: [self.folders.takeItem(self.folders.row(i)) for i in self.folders.selectedItems()])
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        v.addWidget(self.folders)
        v.addLayout(row)
        self.full = QCheckBox('Full access — never ask (commands, files anywhere, GitHub pushes, moving chats)')
        self.full.setChecked(self.conf['full_access'])
        v.addWidget(self.full)
        v.addWidget(_hint('Full access is not a sandbox and is separate from model power: brainstorming stays '
                          'read-only, and “Start execution” never turns it on. Codex cannot ask during a run: '
                          'outside the allowed folders its actions are blocked unless full access is on. Retrieved '
                          'web pages, files and e-mails are treated as data: they never change these permissions.'))
        box = QGroupBox('“Always allow” answers')
        bl = QVBoxLayout(box)
        self.rules = QListWidget()
        for r in self.conf['always_rules']:
            text = {'bash': f"Command: {r.get('prefix', '')} …", 'write': f"Files in: {r.get('path', '')}"}.get(
                r.get('tool'), f"Tool: {r.get('tool')}")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.rules.addItem(item)
        bl.addWidget(self.rules)
        forget = QPushButton('Forget selected')
        forget.clicked.connect(lambda: [self.rules.takeItem(self.rules.row(i)) for i in self.rules.selectedItems()])
        bl.addWidget(forget, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(box, 1)
        return page

    def _add_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, 'Folder the assistant may change', str(Path.home()))
        if chosen and not self.folders.findItems(chosen, Qt.MatchFlag.MatchExactly):
            self.folders.addItem(chosen)
            if self.mode_group.checkedButton() is not None and \
                    self.mode_group.checkedButton().property('key') == 'app':
                self.mode_group.button(1).setChecked(True)

    # ---------------------------------------------------------------- usage
    def _usage(self):
        from ..usage import UNAVAILABLE, human
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_hint('Limits come only from what the providers report: Claude Code\'s rate-limit events (5-hour '
                          'and weekly windows of a Claude subscription, during a reply), Codex\'s own session log '
                          '(5-hour and weekly windows of a ChatGPT subscription) and API rate-limit headers. Anything '
                          f'not reported is shown as <b>{UNAVAILABLE.lower()}</b> — never guessed. Token counts are '
                          'those reported by the agent or provider; otherwise they are estimated from text length '
                          'and marked so. Monitoring never sends requests or uses tokens.'))
        self.rings = QCheckBox('Show one usage ring per connected account in the chat list')
        self.rings.setChecked(bool(self.conf.get('usage_rings', True)))
        v.addWidget(self.rings)
        from ..limits import human_reset
        from .usage_rings import accounts as ring_accounts
        for acc in ring_accounts(self.core):
            lim = self.core.limits.get(acc['key'])
            if lim and lim.get('windows'):
                parts = [f"{html.escape(w['label'])}: {round(100 * float(w['used']))} % used, "
                         f"{human_reset(w.get('resets_at'))}" for w in lim['windows'].values() if w.get('used') is not None]
                v.addWidget(_hint(f"<b>{html.escape(acc['long'])}</b> — " + ' · '.join(parts) +
                                  f" <i>({html.escape(lim.get('source', ''))})</i>"))
            else:
                v.addWidget(_hint(f"<b>{html.escape(acc['long'])}</b> — limits {UNAVAILABLE.lower()}"))
        rows = self.core.ledger.summary()
        if not rows:
            v.addWidget(QLabel('No usage recorded yet.'))
        for r in rows:
            text = (f"<b>{html.escape(GROUP_LABELS.get(r['group'], r['group']))}</b> · {html.escape(str(r['account']))}"
                    f"<br>models: {html.escape(', '.join(r['models']))}"
                    f"<br>last 5 h: {human(r['tokens_5h'])} tokens in {r['turns_5h']} replies · last 7 days: "
                    f"{human(r['tokens_week'])} tokens in {r['turns_week']} replies"
                    + (f" ({int(r['estimated_share'] * 100)} % estimated)" if r['estimated'] else ' (reported)')
                    + (f"<br>cost reported by the agent/API (7 days): ${r['cost_usd_week']:.2f}" if r['cost_usd_week']
                       else '')
                    + (f" — <a href=\"{r['official_page']}\">official usage page</a>" if r['official_page'] else ''))
            v.addWidget(_hint(text))
        form = QFormLayout()
        self.warn = QSpinBox()
        self.warn.setRange(0, 100_000_000)
        self.warn.setSingleStep(50000)
        self.warn.setSuffix(' tokens')
        self.warn.setValue(self.conf['usage_warn_tokens_5h'])
        form.addRow('Warn when one account exceeds in 5 h (observed here; 0 = off)', self.warn)
        v.addLayout(form)
        v.addStretch(1)
        return page

    # ---------------------------------------------------------------- monitoring
    def _monitor(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_hint('A small strip under the chats while a local model runs or is loaded: model and where it '
                          'runs, tokens/s and time to first token (Ollama\'s own counters), GPU use / memory / '
                          'temperature / power (NVIDIA via nvidia-smi, AMD on Linux), CPU, RAM. Values the system does '
                          'not expose are not shown. Nothing is sent anywhere; no elevated rights are requested.'))
        self.mon = QCheckBox('Show the local monitoring strip')
        self.mon.setChecked(self.conf['monitor'])
        v.addWidget(self.mon)
        form = QFormLayout()
        self.mon_ms = QSpinBox()
        self.mon_ms.setRange(250, 10000)
        self.mon_ms.setSingleStep(250)
        self.mon_ms.setSuffix(' ms')
        self.mon_ms.setValue(self.conf['monitor_interval_ms'])
        form.addRow('Refresh interval', self.mon_ms)
        v.addLayout(form)
        self.mon_now = _hint('')
        test = QPushButton('Read once now')
        test.clicked.connect(self._monitor_once)
        v.addWidget(test, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(self.mon_now)
        v.addStretch(1)
        return page

    def _monitor_once(self):
        def work(log, progress):
            from .. import monitor
            monitor.sample(None)
            import time as _t
            _t.sleep(0.5)
            return monitor.sample((self.core.ai_conf or {}).get('judge_url') or 'http://127.0.0.1:11434')
        self._job(work, lambda s: self.mon_now.setText('<pre>' + html.escape(json.dumps(
            {k: v for k, v in s.items() if k != 'ts'}, indent=1, default=str)) + '</pre>' if isinstance(s, dict)
            else html.escape(str(s))))

    # ---------------------------------------------------------------- desktop
    def _desktop(self):
        page = QWidget()
        v = QVBoxLayout(page)
        launcher = QPushButton('Create a launcher (application menu, terminal command agent-hub)…')
        launcher.clicked.connect(self._launcher)
        v.addWidget(launcher, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(_hint('Adds “Agent Hub” to your applications menu (Linux), a script on Windows / macOS, and the '
                          'command <code>agent-hub</code>. Bind it to a keyboard shortcut in your desktop settings. '
                          'Only one Agent Hub process owns the chats at a time; opening it again brings the running '
                          'one to the front.'))
        v.addStretch(1)
        return page

    def _launcher(self):
        from ..launcher import create
        try:
            created = create()
        except OSError as exc:
            QMessageBox.warning(self, 'Launcher', str(exc))
            return
        QMessageBox.information(self, 'Launcher', 'Created:\n' + '\n'.join(str(p) for p in created))

    # ---------------------------------------------------------------- remote
    def _remote(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_hint('<b>Not available in this build.</b> Planned: run the engine on one of your computers and '
                          'reach it from a browser or iPhone over your private network (e.g. Tailscale), with '
                          'application sign-in, device approval and the same approval cards. No server is started '
                          'and nothing listens on the network today (the approval channel listens on 127.0.0.1 '
                          'only, with a one-time token). See docs/SERVER_MODE.md.'))
        v.addStretch(1)
        return page

    # ---------------------------------------------------------------- diagnostics
    def _diagnostics(self):
        from .. import __version__
        from ..host import CONTRACT
        page = QWidget()
        v = QVBoxLayout(page)
        info = {'agent_hub': __version__, 'host_contract': '.'.join(map(str, CONTRACT)), 'host': self.host.name,
                'data folder': str(self.core.root), 'models': [b['key'] for b in self.core.backends],
                'migration': self.core.migration}
        self.diag = QPlainTextEdit(json.dumps(info, indent=1, default=str))
        self.diag.setReadOnly(True)
        v.addWidget(_hint('Diagnostics contain no keys, tokens or chat contents.'))
        v.addWidget(self.diag, 1)
        row = QHBoxLayout()
        copy = QPushButton('Copy diagnostics')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.diag.toPlainText()))
        row.addWidget(copy)
        row.addStretch(1)
        v.addLayout(row)
        return page

    # ---------------------------------------------------------------- save
    def _save(self):
        c = dict(self.conf)

        def picked(group, default):
            b = group.checkedButton()
            return b.property('key') if b is not None else default
        if self.host.name != 'standalone':
            c['open_mode'] = picked(self.open_group, 'panel')
            c['detached_close'] = picked(self.close_group, 'hide')
        c['send_with_enter'] = self.enter.isChecked()
        c['standalone_theme'] = self.theme.currentData() or 'light'
        c['font_scale'] = self.scale.value()
        c['routing_profile'] = self.profile.currentData() or 'balanced'
        c['default_backend'] = self.default_backend.currentData() or 'auto'
        c['preference'] = [p.strip() for p in self.preference.text().split(',') if p.strip()] or ['pi', 'claude-code', 'codex']
        c['local_for_small'] = self.local_small.isChecked()
        c['limits'] = {g: s.value() for g, s in self.limits.items()}
        c['when_busy'] = picked(self.busy_group, 'ask')
        c['brainstorm_backend'] = self.bs_backend.currentData() or 'auto'
        c['brainstorm_research'] = self.bs_research.isChecked()
        c['brainstorm_max_tool_calls'] = self.bs_calls.value()
        c['brainstorm_budget_tokens'] = self.bs_budget.value()
        c['voice_backend'] = self.voice_backend.currentData() or 'vosk'
        c['voice_language'] = self.voice_lang.currentData() or 'en'
        c['voice_device'] = self.voice_dev.currentData() or ''
        c['voice_shortcut'] = self.voice_key.text().strip() or 'F11'
        c['voice_cloud_connection'] = self.voice_conn.currentData() or ''
        c['voice_cloud_consent'] = self.voice_consent.isChecked()
        c['auto_sort'] = picked(self.sort_group, 'ask')
        c['access_mode'] = picked(self.mode_group, 'app')
        c['extra_folders'] = [self.folders.item(i).text() for i in range(self.folders.count())]
        if self.full.isChecked() and not self.conf['full_access']:
            if QMessageBox.question(self, 'Full access', 'Turn on full access? The assistant will never ask before '
                                    'running commands or changing files.') != QMessageBox.StandardButton.Yes:
                return
        c['full_access'] = self.full.isChecked()
        c['always_rules'] = [self.rules.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.rules.count())]
        c['usage_warn_tokens_5h'] = self.warn.value()
        c['usage_rings'] = self.rings.isChecked()
        for _title, _page, saver in self.extra_pages:
            if saver is not None:
                try:
                    saver(c)
                except Exception as exc:
                    QMessageBox.warning(self, 'Settings', f'{_title}: {exc}')
        c['monitor'] = self.mon.isChecked()
        c['monitor_interval_ms'] = self.mon_ms.value()
        self.core.save_settings(c)
        if self.host.name == 'standalone':
            from . import theme
            theme.set_standalone(c['standalone_theme'])
        self.core.refresh_backends()
        self.accept()
