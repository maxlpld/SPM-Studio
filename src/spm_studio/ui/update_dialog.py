"""Settings › Check for updates… — newest version, what is new, and the installation itself (in the window)."""
from __future__ import annotations
import time
from PySide6.QtCore import QThread, Signal, QUrl, QProcess, QTimer
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
                               QCheckBox, QMessageBox, QFrame, QProgressBar, QPlainTextEdit, QApplication)

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
    progress = Signal(int, int)          # bytes downloaded, total (0 when unknown)

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result

    def run(self):
        try:
            self.done.emit(updates.prepare(self.result, progress=self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class _Install(QThread):
    """Runs the installer of the downloaded version inside the app (no terminal window)."""
    line = Signal(str)
    done = Signal(int)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.runner = updates.InstallRunner(updates.installer_argv(source), source, on_line=self.line.emit)

    def cancel(self):
        self.runner.cancel()

    def run(self):
        self.done.emit(self.runner.run())


class UpdateDialog(QDialog):
    """Check, read what is new, install with a progress bar, then restart now or later.

    v0.0.7: the installer no longer opens a terminal. Its output drives the progress bar and is
    available behind “Show details”. The new version is built and tested next to the running one,
    so a failed or cancelled update leaves the current version untouched.
    """

    def __init__(self, parent=None, result=None):
        super().__init__(parent)
        self.setWindowTitle('Check for updates')
        self.resize(660, 600)
        self.result = None
        self.worker = None
        self.installer = None
        self.installing = False
        self.installed_version = ''
        self._progress = None
        v = QVBoxLayout(self)
        self.headline = QLabel('Checking GitHub for a newer version…')
        self.headline.setObjectName('heading')
        self.headline.setWordWrap(True)
        v.addWidget(self.headline)
        self.detail = QLabel(f'Installed version: {updates.current_version()}')
        self.detail.setObjectName('muted')
        self.detail.setWordWrap(True)
        v.addWidget(self.detail)
        # progress strip (only while installing and after)
        self.progress_box = QFrame()
        self.progress_box.setObjectName('activityStrip')
        strip = QVBoxLayout(self.progress_box)
        strip.setContentsMargins(10, 8, 10, 10)
        strip.setSpacing(6)
        self.step = QLabel('')
        self.step.setObjectName('UpdateStepV007')
        self.step.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setObjectName('UpdateProgressV007')
        self.bar.setProperty('role', 'activity')
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(True)
        self.bar.setFormat('%p %')
        strip.addWidget(self.step)
        strip.addWidget(self.bar)
        self.progress_box.hide()
        v.addWidget(self.progress_box)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setPlaceholderText('Release notes appear here.')
        v.addWidget(self.notes, 1)
        self.log = QPlainTextEdit()
        self.log.setObjectName('UpdateLogV007')
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log.setPlaceholderText('What the installer prints appears here.')
        self.log.hide()
        v.addWidget(self.log, 1)
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
        self.details = QPushButton('Show details')
        self.details.setObjectName('UpdateDetailsV007')
        self.details.setCheckable(True)
        self.details.setToolTip('Show or hide what the installer prints')
        self.details.toggled.connect(self._toggle_details)
        self.details.hide()
        self.copy_log = QPushButton('Copy details')
        self.copy_log.clicked.connect(lambda: QApplication.clipboard().setText(self.log.toPlainText()))
        self.copy_log.hide()
        self.install = QPushButton('Install update')
        self.install.setProperty('primary', True)
        self.install.clicked.connect(self._install)
        self.install.setEnabled(False)
        self.restart = QPushButton('Restart now')
        self.restart.setObjectName('UpdateRestartV007')
        self.restart.setProperty('primary', True)
        self.restart.clicked.connect(self._restart_now)
        self.restart.hide()
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.reject)
        for b in (self.recheck, self.page, self.details, self.copy_log):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.install)
        row.addWidget(self.restart)
        row.addWidget(self.close_button)
        v.addLayout(row)
        if result is not None:
            self._show(result)
        else:
            self.start_check()

    def _auto_toggled(self, on):
        updates.save_state(auto_check=bool(on))

    def _toggle_details(self, on):
        self.log.setVisible(on)
        self.notes.setVisible(not on)
        self.copy_log.setVisible(on)
        self.details.setText('Hide details' if on else 'Show details')

    def start_check(self):
        if self.installing or (self.worker is not None and self.worker.isRunning()):
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

    # ---- install inside the window
    def _set_progress(self, percent, text):
        self.progress_box.show()
        self.bar.setRange(0, 100)
        self.bar.setValue(max(0, min(100, int(percent))))
        if text:
            self.step.setText(text)

    def _append_log(self, text):
        self.log.appendPlainText(text)

    def _install(self):
        if not self.result or not self.result.get('update') or self.installing:
            return
        version = self.result['latest']
        self.installing = True
        self.install.setEnabled(False)
        self.recheck.setEnabled(False)
        self.close_button.setText('Cancel update')
        self.details.show()
        self.log.clear()
        self.headline.setText(f'Installing SPM Studio {version}…')
        self.detail.setText('You can keep working. The current version stays in place until the new one has been '
                            'built and tested.')
        self._set_progress(0, 'Downloading from GitHub…')
        if updates.remove_partial_release(version):
            self._append_log(f'Removed the unfinished files of an earlier attempt to install {version}.')
        self._append_log(f"Downloading {self.result.get('archive', '')}")
        self.worker = _Prepare(self.result, self)
        self.worker.progress.connect(self._download_progress)
        self.worker.done.connect(self._prepared)
        self.worker.failed.connect(self._install_failed)
        self.worker.start()

    def _download_progress(self, done, total):
        megabytes = done / 1e6
        if total:
            self._set_progress(5 * done / total, f'Downloading from GitHub… {megabytes:.1f} of {total / 1e6:.1f} MB')
        else:
            self._set_progress(2, f'Downloading from GitHub… {megabytes:.1f} MB')

    def _prepared(self, source):
        if not self.installing:                      # cancelled during the download
            return
        self._progress = updates.InstallProgress(start=5)
        self._set_progress(5, 'Starting the installer')
        self._append_log(f'Downloaded and unpacked to {source}')
        self._append_log('Running: ' + ' '.join(updates.installer_argv(source)))
        self.installer = _Install(source, self)
        self.installer.line.connect(self._installer_line)
        self.installer.done.connect(self._installer_done)
        self.installer.start()

    def _installer_line(self, text):
        self._append_log(text)
        if self._progress is not None and self._progress.feed(text):
            self._set_progress(self._progress.percent, self._progress.label + '…')

    def _installer_done(self, code):
        progress = self._progress
        cancelled = self.installer is not None and self.installer.runner.cancelled
        if cancelled and not self.installing:
            return                                    # already reported by reject()
        if cancelled:
            return self._install_failed('The update was cancelled.', cancelled=True)
        if code == 0 and progress is not None and progress.success:
            return self._install_succeeded()
        reason = (progress.problem if progress is not None and progress.problem else
                  f'The installer stopped with code {code}.')
        self._install_failed(reason)

    def _install_succeeded(self):
        version = self.result['latest']
        self.installing = False
        self.installed_version = version
        updates.save_state(installed_pending=version)
        self._set_progress(100, 'Installed and tested')
        self.headline.setText(f'SPM Studio {version} is installed')
        self.detail.setText('Restart SPM Studio to start using it. Restart now, or later whenever it suits you: '
                            'the new version starts the next time you open SPM Studio.')
        self.install.hide()
        self.recheck.setEnabled(False)
        self.restart.show()
        self.restart.setDefault(True)
        self.close_button.setText('Later')

    def _install_failed(self, message, cancelled=False):
        version = (self.result or {}).get('latest', '')
        self.installing = False
        removed = updates.remove_partial_release(version) if version else False
        self.close_button.setText('Close')
        self.recheck.setEnabled(True)
        self.install.setEnabled(bool(self.result and self.result.get('update')))
        self.install.setText('Try again')
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.step.setText('Cancelled' if cancelled else 'Not installed')
        self.headline.setText('The update was cancelled' if cancelled else 'The update could not be installed')
        self.detail.setText(('' if cancelled else str(message) + ' ') +
                            'Your current version is unchanged and keeps working.' +
                            (' The unfinished files were removed.' if removed else ''))
        self._append_log(str(message))
        if not cancelled:
            self.details.show()
            self.details.setChecked(True)             # show why, without the user having to look for it

    def _restart_now(self):
        """Close this SPM Studio and open the newly installed one."""
        window = self.parent()
        self.accept()
        restart_app(window)

    def reject(self):
        if self.installing:
            if QMessageBox.question(self, 'Cancel the update?',
                                    'The update is still being installed. Cancel it?\n\n'
                                    'Your current version stays as it is; you can install the update later.'
                                    ) != QMessageBox.StandardButton.Yes:
                return
            self.installing = False
            if self.installer is not None and self.installer.isRunning():
                self.installer.cancel()
                self.installer.wait(15000)
            if self.worker is not None and self.worker.isRunning():
                self.worker.wait(20000)
            self._install_failed('The update was cancelled.', cancelled=True)
            return
        if self.installed_version:
            window = self.parent()
            try:
                window.statusBar().showMessage(
                    f'SPM Studio {self.installed_version} is installed — restart to use it', 0)
            except (AttributeError, RuntimeError):
                pass
        super().reject()


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


def restart_app(window=None):
    """Close SPM Studio (saving layout, stopping the assistant) and start it again (updates, extensions)."""
    argv = updates.restart_argv()
    try:
        if window is not None:
            window.close()
    except RuntimeError:
        pass
    started = QProcess.startDetached(argv[0], argv[1:])
    if isinstance(started, tuple):
        started = started[0]
    app = QApplication.instance()
    if started and app is not None:
        QTimer.singleShot(0, app.quit)
    elif window is not None:
        try:
            window.show()
            QMessageBox.information(window, 'Restart', 'SPM Studio could not be started automatically. '
                                    'Close it and open it again.')
        except RuntimeError:
            pass
