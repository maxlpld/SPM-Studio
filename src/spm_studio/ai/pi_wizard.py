"""Guided Pi setup for people who have never used a coding agent.

Five steps, each doing the work itself instead of asking the user to type
commands: 1 install (private Node.js if needed, Pi, optional router +
subagents) · 2 sign in (ChatGPT/Copilot subscription in a browser, or paste an
API key) · 3 choose models · 4 optional local Judge (hardware survey, three
profiles, Ollama install, download, real Fast/Smart test) · 5 live test.

Everything goes into SPM Studio's private Pi folder; an existing ~/.pi is never
touched. Every download or installation is confirmed first.
"""
from __future__ import annotations
import threading
import webbrowser
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QWidget,
                               QStackedWidget, QPlainTextEdit, QProgressBar, QCheckBox, QComboBox, QLineEdit,
                               QRadioButton, QButtonGroup, QGroupBox, QMessageBox, QListWidget, QFormLayout)

from . import pi_setup, judge
from . import platform_util as pu


class Worker(QThread):
    log = Signal(str)
    progress = Signal(int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.cancel = threading.Event()

    def run(self):
        try:
            self.done.emit(self.fn(self.log.emit, self.progress.emit, self.cancel))
        except Exception as exc:                      # shown to the user, never raised in the GUI
            self.failed.emit(f'{type(exc).__name__}: {exc}')


def _hint(text):
    label = QLabel(text)
    label.setObjectName('hint')
    label.setWordWrap(True)
    return label


def _title(text):
    label = QLabel(text)
    label.setObjectName('heading')
    return label


class PiSetupWizard(QDialog):
    STEPS = ('Install', 'Sign in', 'Models', 'Judge', 'Test')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Set up the AI assistant (Pi)')
        self.resize(720, 640)
        self.worker = None
        self.models = []
        self.profile_choice = None
        self.judge_ok = False
        self.proxy = None
        self.summary = {}
        root = QVBoxLayout(self)
        self.steps_label = QLabel('')
        self.steps_label.setObjectName('muted')
        root.addWidget(self.steps_label)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        root.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.setMaximumBlockCount(800)
        self.log.setPlaceholderText('Progress appears here.')
        root.addWidget(self.log)
        nav = QHBoxLayout()
        self.back = QPushButton('Back')
        self.back.clicked.connect(lambda: self._go(self.pages.currentIndex() - 1))
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.reject)
        self.next = QPushButton('Next')
        self.next.setProperty('primary', True)
        self.next.clicked.connect(self._next)
        nav.addWidget(self.cancel_button)
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        root.addLayout(nav)
        for build in (self._page_install, self._page_login, self._page_models, self._page_judge, self._page_test):
            self.pages.addWidget(build())
        self.auth_timer = QTimer(self)
        self.auth_timer.setInterval(2000)
        self.auth_timer.timeout.connect(self._refresh_auth)
        self._go(0)
        self._check_install()

    # ------------------------------------------------------------------ helpers
    def _log(self, text):
        self.log.appendPlainText(str(text))

    def _busy(self):
        # Explicit flag: the done/failed signal can arrive before QThread.isRunning() turns False.
        return getattr(self, '_working', False)

    def _run(self, fn, on_done, label='Working…'):
        if self._busy():
            QMessageBox.information(self, 'Please wait', 'Another step is still running.')
            return
        self.progress.setValue(0)
        self.progress.show()
        self.next.setEnabled(False)
        self.back.setEnabled(False)
        self._log(label)
        self._working = True
        self._on_done = on_done
        self.worker = Worker(fn, self)
        # Bound methods of this QObject: Qt queues them to the GUI thread (never run widget code
        # in the worker thread, which a plain closure could do).
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.done.connect(self._worker_done)
        self.worker.failed.connect(self._worker_failed)
        self.worker.start()

    def _worker_done(self, result):
        self._working = False
        self.progress.hide()
        try:
            self._on_done(result)
        finally:
            self._update_nav()

    def _worker_failed(self, err):
        self._working = False
        self.progress.hide()
        self._log('⚠ ' + err)
        QMessageBox.warning(self, 'Step failed', err)
        self._update_nav()

    def _go(self, index):
        index = max(0, min(self.pages.count() - 1, index))
        self.pages.setCurrentIndex(index)
        self.steps_label.setText('   ›   '.join(('<b>%s</b>' % s if i == index else s)
                                               for i, s in enumerate(self.STEPS)))
        if index == 1:
            self._refresh_auth()
            self.auth_timer.start()
        else:
            self.auth_timer.stop()
        if index == 2 and not self.models:
            self._load_models()
        if index == 3:
            self._judge_mode_changed()
        self._update_nav()

    def _update_nav(self):
        i = self.pages.currentIndex()
        busy = self._busy()
        self.back.setEnabled(i > 0 and not busy)
        self.next.setText('Finish' if i == self.pages.count() - 1 else 'Next')
        ok = {0: pi_setup.managed_pi_entry() is not None,
              1: bool(pi_setup.auth_status()),
              2: bool(self._fast() and (self._smart() or not self.use_router.isChecked())),
              3: self._judge_choice() != 'local' or self.judge_ok,
              4: bool(self.summary)}.get(i, True)
        self.next.setEnabled(ok and not busy)

    def _next(self):
        i = self.pages.currentIndex()
        if i == self.pages.count() - 1:
            self.accept()
            return
        if i == 3 and self._judge_choice() == 'local' and not self.judge_ok:
            return
        self._go(i + 1)
        if i + 1 == 4:
            self._apply_and_test()

    def reject(self):
        if self._busy():
            if QMessageBox.question(self, 'Stop setup?', 'A step is still running. Stop it and close?') \
                    != QMessageBox.StandardButton.Yes:
                return
            self.worker.cancel.set()
            self.worker.wait(5000)
            self._working = False
        super().reject()

    # ------------------------------------------------------------- 1 install
    def _page_install(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_title('1 · Install the assistant engine'))
        v.addWidget(_hint('SPM Studio installs its own copy of Pi (an open-source coding agent) for your user '
                          'account only — no administrator rights, nothing outside SPM Studio\'s folders. '
                          'An existing personal Pi setup (~/.pi) is not modified.'))
        self.checks = QLabel('Checking this computer…')
        self.checks.setWordWrap(True)
        self.checks.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.checks)
        self.with_router = QCheckBox('Also install smart routing (pi-shift-router) and subagents (pi-subagents) — '
                                     'saves tokens by sending simple requests to a cheaper model')
        self.with_router.setChecked(True)
        v.addWidget(self.with_router)
        row = QHBoxLayout()
        self.install_button = QPushButton('Install')
        self.install_button.setProperty('primary', True)
        self.install_button.clicked.connect(self._install)
        self.git_button = QPushButton('Install Git for Windows…')
        self.git_button.clicked.connect(self._install_git)
        self.git_button.setVisible(False)
        row.addWidget(self.install_button)
        row.addWidget(self.git_button)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        return page

    def _check_install(self):
        node = pu.node_info()
        lines = []
        if node['ok']:
            lines.append(f"✓ Node.js {pu.version_text(node['version'])} ({node['source']})")
        elif node['found']:
            lines.append(f"• Node.js {pu.version_text(node['version'])} is too old — a private Node.js LTS "
                         f"(~40 MB, from nodejs.org, checksum-verified) will be downloaded")
        else:
            lines.append('• Node.js not found — a private Node.js LTS (~40 MB, from nodejs.org, checksum-verified) '
                         'will be downloaded')
        entry = pi_setup.managed_pi_entry()
        lines.append(f'✓ Pi {pi_setup.managed_pi_version()} already installed for SPM Studio' if entry else
                     '• Pi will be installed from npm (~60 MB, internet required)')
        if pu.IS_WINDOWS:
            bash = pu.git_bash()
            lines.append(f'✓ Git Bash: {bash}' if bash else
                         '⚠ Git for Windows (Git Bash) not found. Chat works without it, but Pi needs it to run '
                         'commands and build tools. Install it with the button below.')
            self.git_button.setVisible(not bash)
        packages = pi_setup.installed_packages() if entry else []
        if entry:
            lines.append('✓ Router installed' if any('pi-shift-router' in p for p in packages) else
                         '• Router not installed')
        self.checks.setText('<br>'.join(lines))
        self.install_button.setText('Reinstall / update' if entry else 'Install')
        self._update_nav()

    def _install(self):
        node = pu.node_info()
        what = ['Pi (@earendil-works/pi-coding-agent) from npm']
        if not node['ok']:
            what.insert(0, 'Node.js LTS from nodejs.org (verified with its SHA-256 checksum)')
        if self.with_router.isChecked():
            what.append('pi-shift-router and pi-subagents (Pi extensions from npm)')
        if QMessageBox.question(self, 'Download and install?',
                                'SPM Studio will download and install, for your user only:\n\n• ' + '\n• '.join(what) +
                                '\n\nAbout 100–200 MB. Continue?') != QMessageBox.StandardButton.Yes:
            return
        with_router = self.with_router.isChecked()

        def work(log, progress, cancel):
            node_path = pi_setup.ensure_node(log, progress, cancel)
            progress(0)
            pi_setup.install_pi(node_path, log, cancel)
            pi_setup.configure_platform_defaults()
            if with_router:
                for pkg in (pi_setup.ROUTER_PACKAGE, pi_setup.SUBAGENTS_PACKAGE):
                    pi_setup.install_extension(pkg, log, cancel)
            version = pi_setup.pi_version()
            log('Pi reports version: ' + (version or 'unknown'))
            return True
        self._run(work, lambda _: (self._check_install(), self._log('✓ Installation finished. Press Next.')),
                  'Installing…')

    def _install_git(self):
        if pu.winget():
            if QMessageBox.question(self, 'Install Git for Windows?',
                                    'Install Git.Git from the official winget source? A Windows installer '
                                    'window may ask for confirmation.') != QMessageBox.StandardButton.Yes:
                return
            # Pin the source: otherwise a broken/untrusted msstore source can stop
            # winget before it installs Git.Git from the working winget repository.
            def finished(code):
                self._check_install()
                if code != 0:
                    self._log('Git installation failed. Try from a normal PowerShell window: '
                              'winget install -e --id Git.Git --source winget '
                              '--accept-source-agreements --accept-package-agreements')
                    self._log('Or install Git Bash manually from https://git-scm.com/download/win '
                              'then restart SPM Studio.')
            self._run(lambda log, p, c: pi_setup.run_streaming(
                [pu.winget(), 'install', '-e', '--id', 'Git.Git', '--source', 'winget',
                 '--accept-source-agreements', '--accept-package-agreements'],
                log, timeout=1800, cancel=c), finished, 'Installing Git for Windows…')
        else:
            webbrowser.open('https://git-scm.com/download/win')

    # ------------------------------------------------------------- 2 sign in
    def _page_login(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_title('2 · Connect an AI account'))
        v.addWidget(_hint('Use a subscription you already pay for, or an API key (pay per use). '
                          'You can connect several; more providers means more model choices and fallbacks.'))
        sub = QGroupBox('Subscription (sign in with your browser)')
        sv = QVBoxLayout(sub)
        for provider, label, _cmd in pi_setup.SUBSCRIPTIONS:
            b = QPushButton('Sign in with ' + label + '…')
            b.clicked.connect(lambda _=False, p=provider: self._login(p))
            sv.addWidget(b)
        sv.addWidget(_hint('A small terminal window opens with Pi; type the /login command it shows, finish in the '
                           'browser, then /quit. This page notices the sign-in by itself.\n'
                           'Claude Pro/Max subscribers: choose "Claude Code / Codex" in the previous dialog '
                           '(official Claude app), or use an Anthropic API key below.'))
        v.addWidget(sub)
        keys = QGroupBox('API key')
        form = QFormLayout(keys)
        self.key_provider = QComboBox()
        for pid, label, _env, url in pi_setup.API_KEY_PROVIDERS:
            self.key_provider.addItem(label, (pid, url))
        self.key_value = QLineEdit()
        self.key_value.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_value.setPlaceholderText('Paste the key here')
        row = QHBoxLayout()
        save = QPushButton('Save key')
        save.clicked.connect(self._save_key)
        get = QPushButton('Get a key…')
        get.clicked.connect(lambda: webbrowser.open(self.key_provider.currentData()[1]))
        row.addWidget(save)
        row.addWidget(get)
        row.addStretch(1)
        form.addRow('Provider', self.key_provider)
        form.addRow('Key', self.key_value)
        form.addRow('', row)
        form.addRow('', _hint('Stored only in SPM Studio\'s private Pi folder (auth.json, readable by your user '
                              'account only). Never logged, exported or included in the app folder.'))
        v.addWidget(keys)
        v.addWidget(QLabel('Connected:'))
        self.connected = QListWidget()
        self.connected.setMaximumHeight(90)
        v.addWidget(self.connected)
        remove = QPushButton('Disconnect selected')
        remove.clicked.connect(self._remove_auth)
        v.addWidget(remove, 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch(1)
        return page

    def _refresh_auth(self):
        status = pi_setup.auth_status()
        current = [self.connected.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.connected.count())]
        if current != list(status):
            self.connected.clear()
            for provider, kind in status.items():
                self.connected.addItem(f"{provider}  ·  {'API key' if kind == 'api_key' else 'subscription sign-in'}")
                self.connected.item(self.connected.count() - 1).setData(Qt.ItemDataRole.UserRole, provider)
            if status and len(status) > len(current):
                self._log('✓ Connected: ' + ', '.join(status))
                self.models = []                    # new provider → refresh model list later
        self._update_nav()

    def _login(self, provider):
        try:
            script = pi_setup.login_script(provider)
        except OSError as exc:
            QMessageBox.warning(self, 'Sign in', str(exc))
            return
        manual = pu.open_terminal(script)
        if manual:
            QMessageBox.information(self, 'Open a terminal',
                                    'No terminal application was found. Open one and run:\n\n' + manual)
        else:
            self._log('Sign-in window opened. Follow its instructions; this page updates automatically.')

    def _save_key(self):
        provider = self.key_provider.currentData()[0]
        try:
            pi_setup.set_api_key(provider, self.key_value.text())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, 'API key', str(exc))
            return
        self.key_value.clear()
        self._log(f'Key saved for {provider}.')
        self._refresh_auth()

    def _remove_auth(self):
        item = self.connected.currentItem()
        if item is None:
            return
        provider = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, 'Disconnect', f'Remove the stored sign-in/key for {provider}?') \
                == QMessageBox.StandardButton.Yes:
            pi_setup.remove_auth(provider)
            self.models = []
            self._refresh_auth()

    # ------------------------------------------------------------- 3 models
    def _page_models(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_title('3 · Choose the answering models'))
        v.addWidget(_hint('Only models your connected accounts can use are listed. With routing, everyday questions '
                          'go to the Fast model and complex coding to the Smart model; the second choice in each '
                          'row is used automatically if the first is unavailable.'))
        self.use_router = QCheckBox('Use smart routing (Fast / Smart)')
        self.use_router.toggled.connect(self._router_toggled)
        v.addWidget(self.use_router)
        grid = QGridLayout()
        self.fast1, self.fast2, self.smart1, self.smart2 = (QComboBox() for _ in range(4))
        for combo in (self.fast1, self.fast2, self.smart1, self.smart2):
            combo.setEditable(True)
            combo.setMinimumWidth(260)
            combo.currentTextChanged.connect(lambda _=None: self._update_nav())
        self.fast_label = QLabel('Fast')
        grid.addWidget(self.fast_label, 0, 0)
        grid.addWidget(self.fast1, 0, 1)
        grid.addWidget(self.fast2, 0, 2)
        self.smart_label = QLabel('Smart')
        grid.addWidget(self.smart_label, 1, 0)
        grid.addWidget(self.smart1, 1, 1)
        grid.addWidget(self.smart2, 1, 2)
        grid.addWidget(QLabel('primary'), 2, 1)
        grid.addWidget(QLabel('fallback (optional)'), 2, 2)
        v.addLayout(grid)
        row = QHBoxLayout()
        row.addWidget(QLabel('Cost mode'))
        self.economics = QComboBox()
        self.economics.addItem('Eco — prefer the Fast model', 'eco')
        self.economics.addItem('Balanced', 'default')
        self.economics.addItem('Performance — prefer the Smart model', 'sport')
        row.addWidget(self.economics)
        row.addStretch(1)
        refresh = QPushButton('Reload model list')
        refresh.clicked.connect(self._load_models)
        row.addWidget(refresh)
        v.addLayout(row)
        v.addStretch(1)
        return page

    def _router_toggled(self, on):
        for w in (self.smart1, self.smart2, self.smart_label, self.economics):
            w.setEnabled(on)
        self.fast_label.setText('Fast' if on else 'Model')
        self._update_nav()

    def _load_models(self):
        def done(models):
            self.models = models or []
            entries = [''] + [f"{m['provider']}/{m['id']}" for m in self.models]
            for combo in (self.fast1, self.fast2, self.smart1, self.smart2):
                keep = combo.currentText()
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(entries)
                combo.setEditText(keep)
                combo.blockSignals(False)
            self._log(f'{len(self.models)} models available.' if self.models else
                      'Pi listed no models — check the sign-in step, or type a model as provider/model-id.')
            self._update_nav()
        router = any('pi-shift-router' in p for p in pi_setup.installed_packages())
        self.use_router.setEnabled(router)
        self.use_router.setChecked(router)
        self._router_toggled(router)
        self._run(lambda log, p, c: pi_setup.list_models(), done, 'Asking Pi which models your accounts can use…')

    @staticmethod
    def _split(text):
        text = (text or '').strip()
        if '/' not in text:
            return None
        provider, model = text.split('/', 1)
        return (provider.strip(), model.strip()) if provider.strip() and model.strip() else None

    def _chain(self, a, b):
        out = [x for x in (self._split(a.currentText()), self._split(b.currentText())) if x]
        return list(dict.fromkeys(out))

    def _fast(self):
        return self._chain(self.fast1, self.fast2)

    def _smart(self):
        return self._chain(self.smart1, self.smart2)

    # ------------------------------------------------------------- 4 judge
    def _page_judge(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_title('4 · Save tokens with a local Judge?'))
        v.addWidget(_hint('Would you like a small local AI model to pre-classify your requests and help route them to '
                          'the most suitable answering model? It runs on this computer for free (Ollama) and only '
                          'decides "Fast" or "Smart" — it never answers you itself.'))
        self.judge_group = QButtonGroup(self)
        self.judge_local = QRadioButton('Local Judge on this computer (recommended if your hardware allows it)')
        self.judge_cloud = QRadioButton('Cloud Judge — the Fast model decides (no download, costs a few tokens)')
        self.judge_none = QRadioButton('No automatic Judge')
        for i, b in enumerate((self.judge_local, self.judge_cloud, self.judge_none)):
            self.judge_group.addButton(b, i)
            v.addWidget(b)
        self.judge_cloud.setChecked(True)
        self.local_box = QGroupBox('Local Judge')
        lv = QVBoxLayout(self.local_box)
        self.hw_label = _hint('Press "Check this computer".')
        lv.addWidget(self.hw_label)
        self.profile_group = QButtonGroup(self)
        self.profile_buttons = []
        for i in range(3):
            b = QRadioButton('')
            b.setVisible(False)
            self.profile_group.addButton(b, i)
            self.profile_buttons.append(b)
            lv.addWidget(b)
        self.profile_group.idToggled.connect(lambda _i, _on: self._profile_changed())
        row = QHBoxLayout()
        self.survey_button = QPushButton('Check this computer')
        self.survey_button.clicked.connect(self._survey)
        self.ollama_button = QPushButton('Install Ollama…')
        self.ollama_button.clicked.connect(self._install_ollama)
        self.pull_button = QPushButton('Download && test')
        self.pull_button.setProperty('primary', True)
        self.pull_button.clicked.connect(self._pull_and_test)
        for b in (self.survey_button, self.ollama_button, self.pull_button):
            row.addWidget(b)
        row.addStretch(1)
        lv.addLayout(row)
        self.judge_result = _hint('')
        lv.addWidget(self.judge_result)
        v.addWidget(self.local_box)
        v.addStretch(1)
        for b in (self.judge_local, self.judge_cloud, self.judge_none):
            b.toggled.connect(lambda _=None: self._judge_mode_changed())
        return page

    def _judge_choice(self):
        if not hasattr(self, 'judge_local'):
            return 'cloud'
        if not self.use_router.isChecked():
            return 'none'
        return 'local' if self.judge_local.isChecked() else 'cloud' if self.judge_cloud.isChecked() else 'none'

    def _judge_mode_changed(self):
        router = self.use_router.isChecked()
        for b in (self.judge_local, self.judge_cloud):
            b.setEnabled(router)
        if not router:
            self.judge_none.setChecked(True)
        self.local_box.setVisible(self._judge_choice() == 'local')
        if self._judge_choice() == 'local' and not self.profile_buttons[0].isVisible() and not self._busy():
            self._survey()
        self._update_nav()

    def _survey(self):
        def work(log, progress, cancel):
            hw = pu.hardware()
            cat = judge.catalog(refresh=True)
            installed = judge.installed_models()
            return hw, cat, installed, judge.recommend(hw, cat, installed), judge.ollama_running()

        def done(result):
            hw, cat, installed, rec, version = result
            source = {'registry': 'verified now against the Ollama registry',
                      'cache': 'from the last verified check', 'builtin': 'built-in list (registry unreachable)'}
            text = (judge.describe_hardware(hw) + '.<br>Candidates: ' + source.get(cat['source'], cat['source'])
                    + f" ({cat.get('checked', cat.get('catalog_date'))}).")
            text += '<br>Ollama: ' + (f'running (version {version})' if version else
                                      'installed but not running' if judge.ollama_executable() else 'not installed')
            if rec['notes']:
                text += '<br>' + '<br>'.join(rec['notes'])
            self.hw_label.setText(text)
            self.ollama_button.setVisible(not version)
            names = {'fastest': 'Fastest / lightest', 'balanced': 'Balanced (recommended)',
                     'quality': 'Higher quality / heavier'}
            profiles = list(rec['profiles'].items())
            for i, b in enumerate(self.profile_buttons):
                if i < len(profiles):
                    key, m = profiles[i]
                    size = (f"{m['download_bytes'] / 1e9:.1f} GB download" if m.get('download_bytes') else
                            f"≈{m['approx_gb']} GB download")
                    b.setText(f"{names[key]}: {m['tag']} — {m['params']}, {size}, needs ≈{m['need_gb']:.0f} GB, "
                              f"runs on {m['runs_on']}{' · already downloaded' if m.get('installed') else ''}\n"
                              f"    {m['note']}")
                    b.setProperty('tag', m['tag'])
                    b.setVisible(True)
                else:
                    b.setVisible(False)
            default = 1 if len(profiles) >= 2 else 0
            if profiles:
                self.profile_buttons[default].setChecked(True)
            else:
                self.judge_result.setText('No local model fits this computer; please choose the cloud Judge.')
        self._run(work, done, 'Inspecting RAM, GPU and Ollama; verifying candidate models…')

    def _profile_changed(self):
        b = self.profile_group.checkedButton()
        self.profile_choice = b.property('tag') if b else None
        self.judge_ok = False
        self._update_nav()

    def _install_ollama(self):
        plan = judge.ollama_install_plan()
        if QMessageBox.question(self, 'Install Ollama?',
                                'Ollama runs local models. Install it now?\n\n' + plan['text'] +
                                '\n\nAbout 1 GB of disk. Existing Ollama models and settings are never changed.') \
                != QMessageBox.StandardButton.Yes:
            return

        def done(hint):
            if hint:
                self._log(hint)
                QMessageBox.information(self, 'Ollama', hint)
            self._survey()
        self._run(lambda log, p, c: judge.install_ollama(log, c), done, 'Installing Ollama…')

    def _pull_and_test(self):
        tag = self.profile_choice
        if not tag:
            QMessageBox.information(self, 'Choose a model', 'Select one of the three profiles first.')
            return
        if not judge.ollama_running() and not judge.start_ollama():
            QMessageBox.information(self, 'Ollama', 'Install or start Ollama first.')
            return
        already = any(m['name'] == tag for m in judge.installed_models())
        if not already and QMessageBox.question(self, 'Download model?', f'Download {tag} with Ollama now?') \
                != QMessageBox.StandardButton.Yes:
            return

        def work(log, progress, cancel):
            if not already:
                judge.pull_model(tag, log, progress, cancel)
            from .judge_proxy import shared
            from .config import load
            proxy = shared(int(load().get('judge_proxy_port') or pi_setup.DEFAULT_PROXY_PORT))
            log(f'Testing through the no-thinking proxy {proxy.base_v1} (same path the router uses) …')
            return proxy.port, judge.benchmark(tag, proxy.base_v1)

        def done(result):
            port, results = result
            self.proxy_port = port
            lines, correct = [], 0
            for r in results:
                correct += r['correct']
                conf = f", confidence {r['confidence']:.2f}" if r.get('confidence') is not None else ''
                lines.append(f"{'✓' if r['correct'] else '✗'} {r['expected']} prompt → {r['tier']} "
                             f"in {r['seconds']:.2f} s{conf}")
            slow = max(r['seconds'] for r in results) > 8
            self.judge_ok = True
            verdict = ('Works well.' if correct == 2 and not slow else
                       'Works, but it is slow on this computer — consider a lighter profile or the cloud Judge.'
                       if slow else 'It misclassified a test prompt — a heavier profile or the cloud Judge may route '
                                    'better. You can still use it.')
            self.judge_result.setText('<br>'.join(lines) + '<br><b>' + verdict + '</b>')
            self._log(' / '.join(lines))
        self._run(work, done, f'Preparing {tag} …')

    # ------------------------------------------------------------- 5 test
    def _page_test(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(_title('5 · Test'))
        self.test_label = QLabel('Saving the configuration and sending a test message…')
        self.test_label.setWordWrap(True)
        self.test_label.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.test_label)
        retry = QPushButton('Run the test again')
        retry.clicked.connect(self._apply_and_test)
        v.addWidget(retry, 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch(1)
        return page

    def _apply_and_test(self):
        router = self.use_router.isChecked()
        fast, smart = self._fast(), self._smart()
        if not router:
            smart = fast
        choice = self._judge_choice()
        try:
            self.summary = pi_setup.apply_configuration(
                fast, smart, choice if router else 'none', self.profile_choice or '',
                self.economics.currentData(), router and choice != 'none',
                orchestration=router and any('pi-subagents' in p for p in pi_setup.installed_packages()),
                port=getattr(self, 'proxy_port', pi_setup.DEFAULT_PROXY_PORT))
        except (ValueError, OSError) as exc:
            self.summary = {}
            self.test_label.setText('⚠ ' + str(exc))
            self._update_nav()
            return
        self.summary['judge_choice'] = choice
        if choice == 'local':
            from .judge_proxy import shared
            pi_setup.set_judge_port(shared().port)

        def done(result):
            ok, text = result
            s = self.summary
            head = (f"Answering model: <b>{s['default']}</b>" + (
                f"<br>Router on · Judge: <b>{s['judge']}</b> (classifier only)" if s.get('router') else
                '<br>Router off (single model)'))
            if ok:
                self.test_label.setText(head + '<br><br>✓ Pi answered: <i>' + text.replace('<', '&lt;')[:200] +
                                        '</i><br><br>Press <b>Finish</b>. The assistant is ready.')
            else:
                self.test_label.setText(head + '<br><br>⚠ The test message failed:<br><code>' +
                                        text.replace('<', '&lt;') + '</code><br><br>Go Back to check the sign-in '
                                        'or the model names, then run the test again. You can also Finish now.')
            self._update_nav()
        self._run(lambda log, p, c: pi_setup.smoke_test(), done, 'Sending a test message through Pi…')
