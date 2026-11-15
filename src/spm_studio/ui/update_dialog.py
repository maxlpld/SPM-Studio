"""Settings › Check for updates… — shows the newest version and what is new."""
from __future__ import annotations
import time
from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
                               QCheckBox, QMessageBox)

from spm_studio.core import updates


class _Check(QThread):
    done = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.done.emit(updates.check())
        except Exception as exc:                       # shown in the dialog, never raised in the GUI
            self.failed.emit(str(exc))


class _Prepare(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result

    def run(self):
        try:
            self.done.emit(updates.prepare(self.result))
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    def __init__(self, parent=None, result=None):
        super().__init__(parent)
        self.setWindowTitle('Check for updates')
        self.resize(620, 520)
        self.result = None
        self.worker = None
        v = QVBoxLayout(self)
        self.headline = QLabel('Checking GitHub for a newer version…')
        self.headline.setObjectName('heading')
        self.headline.setWordWrap(True)
        v.addWidget(self.headline)
        self.detail = QLabel(f'Installed version: {updates.current_version()}')
        self.detail.setObjectName('muted')
        self.detail.setWordWrap(True)
        v.addWidget(self.detail)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setPlaceholderText('Release notes appear here.')
        v.addWidget(self.notes, 1)
        self.auto = QCheckBox('Check automatically once a day when SPM Studio starts')
        self.auto.setChecked(bool(updates.load_state().get('auto_check', True)))
        self.auto.toggled.connect(self._auto_toggled)
        v.addWidget(self.auto)
        row = QHBoxLayout()
        self.recheck = QPushButton('Check again')
        self.recheck.clicked.connect(self.start_check)
        self.page = QPushButton('Open release page')
        self.page.clicked.connect(self._open_page)
        self.page.setEnabled(False)
        self.install = QPushButton('Install update')
        self.install.setProperty('primary', True)
        self.install.clicked.connect(self._install)
        self.install.setEnabled(False)
        close = QPushButton('Close')
        close.clicked.connect(self.reject)
        for b in (self.recheck, self.page):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.install)
        row.addWidget(close)
        v.addLayout(row)
        if result is not None:
            self._show(result)
        else:
            self.start_check()

    def _auto_toggled(self, on):
        updates.save_state(auto_check=bool(on))

    def start_check(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.headline.setText('Checking GitHub for a newer version…')
        self.install.setEnabled(False)
        self.recheck.setEnabled(False)
        self.worker = _Check(self)
        self.worker.done.connect(self._show)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _failed(self, message):
        self.recheck.setEnabled(True)
        self.headline.setText('Could not check for updates')
        self.detail.setText(message)

    def _show(self, result):
        self.recheck.setEnabled(True)
        self.result = result
        updates.save_state(last_check=time.time(), last_seen=result.get('latest'))
        self.page.setEnabled(bool(result.get('url')))
        repo = result.get('repository', '')
        if not result.get('latest'):
            self.headline.setText('No published version yet')
            self.detail.setText(f'Repository: {repo}')
            return
        if result['update']:
            self.headline.setText(f"SPM Studio {result['latest']} is available")
            self.detail.setText(f"Installed: {result['current']} · from github.com/{repo}. "
                                'Installing builds and tests the new version next to the current one; '
                                'your scans, results, tools, settings and AI accounts are kept.')
            self.notes.setMarkdown(updates.notes_markdown(result))
            self.install.setEnabled(True)
        else:
            self.headline.setText(f"SPM Studio is up to date ({result['current']})")
            self.detail.setText(f"Latest published version: {result['latest']} · github.com/{repo}")
            self.notes.setMarkdown('')

    def _open_page(self):
        if self.result and self.result.get('url'):
            QDesktopServices.openUrl(QUrl(self.result['url']))

    def _install(self):
        if not self.result or not self.result.get('update'):
            return
        if QMessageBox.question(self, 'Install update',
                                f"Download SPM Studio {self.result['latest']} from GitHub and run its installer "
                                'in a terminal window?\n\nYou can keep working; restart SPM Studio when the '
                                'installer says it finished.') != QMessageBox.StandardButton.Yes:
            return
        self.install.setEnabled(False)
        self.headline.setText(f"Downloading {self.result['latest']}…")
        self.worker = _Prepare(self.result, self)
        self.worker.done.connect(self._prepared)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _prepared(self, source):
        manual = updates.launch_installer(source, self.result['latest'])
        if manual:
            self.headline.setText('Run the installer in a terminal')
            self.detail.setText('No terminal application was found. Run:\n' + manual)
        else:
            self.headline.setText('The installer is running in a terminal window')
            self.detail.setText('When it reports “installed successfully”, close SPM Studio and open it again.')


class StartupCheck(QThread):
    """Silent once-a-day check; emits only when a newer version exists."""
    available = Signal(object)

    def run(self):
        try:
            if not updates.auto_check_due():
                return
            result = updates.check()
            updates.save_state(last_check=time.time(), last_seen=result.get('latest'))
            if result.get('update') and result.get('latest') != updates.load_state().get('dismissed'):
                self.available.emit(result)
        except Exception:
            pass                                        # offline / not configured: stay silent
