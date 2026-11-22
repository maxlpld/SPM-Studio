"""Settings pages added in v0.0.13: Updates, Tutorials / Guided tour, Beta Tester.

Network work runs in a QThread; results come back through signals connected to bound methods of the page
(so widgets are only touched in the GUI thread). Errors are shown in words, never as tracebacks or tokens.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from . import client, extensions


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName('hint')
    label.setWordWrap(True)
    return label


def _heading(layout, title, subtitle=''):
    head = QLabel(title)
    head.setObjectName('heading')
    layout.addWidget(head)
    if subtitle:
        layout.addWidget(_hint(subtitle))


class Worker(QThread):
    done = Signal(object, object, object)            # (tag, result, error)

    def __init__(self, tag, fn, parent=None):
        super().__init__(parent)
        self.tag, self.fn = tag, fn

    def run(self):
        try:
            self.done.emit(self.tag, self.fn(), None)
        except Exception as exc:
            self.done.emit(self.tag, None, exc)


# ====================================================================== Updates
class UpdatesPage(QWidget):
    def __init__(self, window):
        super().__init__()
        from spm_studio.core.updates import current_version, load_state
        self.window_ = window
        self.setObjectName('SettingsUpdatesPageV0013')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 10, 8)
        _heading(layout, 'Updates', 'SPM Studio and private beta extensions are updated separately. Updating '
                                    'SPM Studio never removes your profiles, scripts, scans, AI settings or to-dos.')
        box = QGroupBox('SPM Studio (stable)')
        v = QVBoxLayout(box)
        v.addWidget(QLabel(f'Current version: <b>{current_version()}</b> · Channel: <b>Stable</b>'))
        self.status = _hint('')
        v.addWidget(self.status)
        row = QHBoxLayout()
        check = QPushButton('Check for public updates…')
        check.setObjectName('UpdatesCheckV0013')
        check.setProperty('primary', True)
        check.clicked.connect(lambda: self.window_.open_update_dialog())
        notes = QPushButton('View public changelog')
        notes.clicked.connect(self.show_changelog)
        row.addWidget(check)
        row.addWidget(notes)
        row.addStretch(1)
        v.addLayout(row)
        self.auto = QCheckBox('Check for public updates once a day (nothing is installed without asking)')
        self.auto.setChecked(bool(load_state().get('auto_check', True)))
        self.auto.toggled.connect(self._auto)
        v.addWidget(self.auto)
        layout.addWidget(box)
        state = client.load_state()
        beta = QGroupBox('Private beta extensions')
        bv = QVBoxLayout(beta)
        bv.addWidget(_hint('Beta testers check and install private extension updates in Settings › Beta Tester. '
                           + ('This computer is signed in to the beta.' if state.get('status') == 'active'
                              else 'This computer is not part of the beta.')))
        layout.addWidget(beta)
        layout.addStretch(1)

    def _auto(self, on):
        from spm_studio.core.updates import save_state
        save_state(auto_check=bool(on))

    def show_changelog(self):
        from spm_studio.core import paths
        try:
            text = (paths.bundled_studio_root() / 'CHANGELOG.md').read_text(encoding='utf8')
        except OSError:
            QDesktopServices.openUrl(QUrl(paths.GITHUB_URL + '/releases'))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Changelog')
        dialog.resize(760, 620)
        v = QVBoxLayout(dialog)
        view = QTextBrowser()
        view.setMarkdown(text)
        v.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        v.addWidget(buttons)
        dialog.exec()


# ====================================================================== Tutorials
class TutorialsPage(QWidget):
    def __init__(self, window):
        super().__init__()
        from spm_studio.tutorial import state
        self.window_ = window
        self.setObjectName('SettingsTutorialsPageV0013')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 10, 8)
        _heading(layout, 'Tutorials / Guided tour',
                 'A guided tour on three real KBr(001) scans bundled with SPM Studio. It works offline, needs no '
                 'AI and never changes your data. Esc ends it at any time.')
        self.progress = _hint('')
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        for label, slot, name in (('Start basics', self.start, 'TutorialSettingsStartV0013'),
                                  ('Resume', self.resume, 'TutorialSettingsResumeV0013'),
                                  ('Replay what’s new', self.whats_new, 'TutorialSettingsNewsV0013'),
                                  ('Reset tutorial progress', self.reset, 'TutorialSettingsResetV0013')):
            button = QPushButton(label)
            button.setObjectName(name)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        folder = QPushButton('Open the KBr tutorial scans')
        folder.clicked.connect(self.open_scans)
        layout.addWidget(folder, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self._state = state
        self.refresh()

    def refresh(self):
        s = self._state.load()
        if s['completed']:
            text = 'Basics tour: finished.'
        elif s['started']:
            text = f"Basics tour: started, next step {s['resume_position'] + 1} / 12."
        elif s['skipped']:
            text = 'Basics tour: skipped (start it whenever you like).'
        else:
            text = 'Basics tour: not started.'
        self.progress.setText(text)

    def _close_settings(self):
        dialog = self.window()
        if isinstance(dialog, QDialog):
            dialog.accept()

    def start(self):
        self._close_settings()
        self.window_.start_tutorial(0)

    def resume(self):
        self._close_settings()
        self.window_.start_tutorial(self._state.load()['resume_position'])

    def whats_new(self):
        self._close_settings()
        self.window_.start_whats_new()

    def reset(self):
        self._state.update(started=False, completed=False, skipped=False, resume_position=0, whats_new_seen='')
        self.refresh()

    def open_scans(self):
        self._close_settings()
        self.window_.open_tutorial_scans()


# ====================================================================== Beta Tester
class BetaPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.session = getattr(window, 'beta_session', None) or client.Session()
        self.setObjectName('SettingsBetaPageV0013')
        self._workers = []
        self.manifest = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 10, 8)
        _heading(layout, 'Beta Tester', 'Private beta program: invited testers get optional private extensions. '
                                        'SPM Studio itself is the same for everyone and needs no account.')
        # -- not activated: three explicit steps
        self.join = QGroupBox('Join the beta on this computer')
        self.join.setObjectName('BetaJoinBoxV0014')
        jv = QVBoxLayout(self.join)
        jv.addWidget(_hint('Do this once on each computer you use (the same key works on several computers, 5 by '
                           'default). The key is sent once over HTTPS and is not stored.'))
        step1 = QLabel('<b>Step 1</b> — paste the invitation key you received (SPM-BETA-…)')
        jv.addWidget(step1)
        self.key = QLineEdit()
        self.key.setObjectName('BetaInvitationKeyV0013')
        self.key.setPlaceholderText('SPM-BETA-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX')
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setAccessibleName('Invitation key')
        jv.addWidget(self.key)
        jv.addWidget(QLabel('<b>Step 2</b> — give this computer a name you will recognise (Desktop, Laptop, Lab PC …)'))
        self.label = QLineEdit(client.load_state().get('device_label') or client.default_device_label())
        self.label.setObjectName('BetaDeviceLabelV0013')
        self.label.setMaxLength(40)
        self.label.setToolTip('Only this nickname is sent (no hostname, no hardware identifier).')
        jv.addWidget(self.label)
        jv.addWidget(QLabel('<b>Step 3</b> — activate; SPM Studio then looks for the private extension and offers '
                            'to install it.'))
        row = QHBoxLayout()
        self.activate = QPushButton('Activate beta access')
        self.activate.setObjectName('BetaActivateV0013')
        self.activate.setProperty('primary', True)
        self.activate.clicked.connect(self.redeem)
        row.addWidget(self.activate)
        row.addStretch(1)
        jv.addLayout(row)
        service_row = QHBoxLayout()
        self.service_label = QLabel()
        self.service_label.setObjectName('hint')
        self.service_label.setWordWrap(True)
        service_row.addWidget(self.service_label, 1)
        service = QPushButton('Change…')
        service.setObjectName('BetaServiceAddressV0013')
        service.setFlat(True)
        service.setToolTip('Only if the administrator gave you another beta service address')
        service.clicked.connect(self.set_service)
        service_row.addWidget(service)
        jv.addLayout(service_row)
        layout.addWidget(self.join)
        # -- active
        self.active = QGroupBox('Beta access')
        av = QVBoxLayout(self.active)
        self.account = QLabel()
        self.account.setObjectName('BetaAccountV0013')
        self.account.setWordWrap(True)
        av.addWidget(self.account)
        row = QHBoxLayout()
        self.devices_button = QPushButton('My computers…')
        self.devices_button.setObjectName('BetaDevicesV0013')
        self.devices_button.clicked.connect(self.show_devices)
        self.rename_button = QPushButton('Rename this computer…')
        self.rename_button.clicked.connect(self.rename)
        self.disconnect_button = QPushButton('Disconnect this computer')
        self.disconnect_button.setObjectName('BetaDisconnectV0013')
        self.disconnect_button.clicked.connect(lambda: self.sign_out(unlink=True))
        self.sign_out_button = QPushButton('Sign out')
        self.sign_out_button.clicked.connect(lambda: self.sign_out(unlink=False))
        self.admin_button = QPushButton('Open Admin Console')
        self.admin_button.setObjectName('BetaAdminConsoleV0013')
        self.admin_button.clicked.connect(self.open_admin)
        for button in (self.devices_button, self.rename_button, self.disconnect_button, self.sign_out_button,
                       self.admin_button):
            row.addWidget(button)
        row.addStretch(1)
        av.addLayout(row)
        layout.addWidget(self.active)
        # -- extension
        self.ext_box = QGroupBox('Private extension')
        ev = QVBoxLayout(self.ext_box)
        self.ext_state = QLabel()
        self.ext_state.setObjectName('BetaExtensionStateV0013')
        self.ext_state.setWordWrap(True)
        ev.addWidget(self.ext_state)
        row = QHBoxLayout()
        self.check_button = QPushButton('Check private extension updates')
        self.check_button.setObjectName('BetaCheckV0013')
        self.check_button.clicked.connect(self.check)
        self.install_button = QPushButton('Install or update…')
        self.install_button.setObjectName('BetaInstallV0013')
        self.install_button.setProperty('primary', True)
        self.install_button.clicked.connect(self.install)
        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName('BetaToggleExtensionV0013')
        self.toggle_button.clicked.connect(self.toggle_extension)
        self.remove_button = QPushButton('Uninstall')
        self.remove_button.clicked.connect(self.uninstall)
        for button in (self.check_button, self.install_button, self.toggle_button, self.remove_button):
            row.addWidget(button)
        row.addStretch(1)
        ev.addLayout(row)
        self.auto = QCheckBox('Check for private extension updates automatically (once a day, never installs by '
                              'itself)')
        self.auto.setObjectName('BetaAutoCheckV0013')
        self.auto.setChecked(bool(client.load_state().get('auto_check')))
        self.auto.toggled.connect(lambda on: client.save_state(auto_check=bool(on)))
        ev.addWidget(self.auto)
        stable = QPushButton('Return to stable-only updates')
        stable.setObjectName('BetaReturnStableV0013')
        stable.clicked.connect(self.return_to_stable)
        ev.addWidget(stable, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.ext_box)
        self.message = QLabel()
        self.message.setObjectName('BetaMessageV0013')
        self.message.setWordWrap(True)
        self.message.setAccessibleName('Beta status message')
        layout.addWidget(self.message)
        layout.addStretch(1)
        self.refresh()
        if self.session.signed_in():
            self._run('me', self.session.me)

    # ------------------------------------------------------------------ helpers
    def _run(self, tag, fn):
        worker = Worker(tag, fn, self)
        worker.done.connect(self._done)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        self._busy(True)
        worker.start()

    def _busy(self, on):
        for button in (self.activate, self.check_button, self.install_button, self.devices_button,
                       self.disconnect_button, self.sign_out_button):
            button.setEnabled(not on)

    def say(self, text, error=False):
        self.message.setText(('⚠ ' if error else '') + text)

    def refresh(self):
        state = client.load_state()
        signed = self.session.signed_in()
        try:
            self.service_label.setText(f'Beta service: {client.api_base()}')
        except client.BetaError:
            self.service_label.setText('Beta service: not set — press Change… and paste the address you received.')
        self.join.setVisible(not signed)
        self.active.setVisible(signed)
        self.ext_box.setVisible(signed or bool(extensions.installed()))
        role = state.get('role', '')
        if signed:
            devices = ''
            if state.get('max_devices') is not None:
                limit = state['max_devices'] if state['max_devices'] else 'unlimited'
                devices = f"<br>Registered computers: {state.get('active_devices', '?')} / {limit}"
            checked = time.strftime('%Y-%m-%d %H:%M', time.localtime(state['last_verified'])) \
                if state.get('last_verified') else 'never'
            who = 'Administrator' if role == 'admin' else 'Beta tester'
            self.account.setText(f"<b>Beta access active</b> · {who}"
                                 + (f" · {state['account_label']}" if state.get('account_label') else '')
                                 + f"<br>This computer: {state.get('device_label', '')}{devices}"
                                 + f"<br>Last verified: {checked}")
        self.admin_button.setVisible(signed and role == 'admin')
        installed = extensions.installed()
        if installed:
            parts = []
            for info in installed.values():
                d = info['descriptor']
                parts.append(f"{d['name']} {d['version']} — {'enabled' if info['enabled'] else 'disabled'}"
                             + (f" (last error: {info['error']})" if info['error'] else ''))
            text = 'Installed: ' + '; '.join(parts)
            first = next(iter(installed.values()))
            self.toggle_button.setText('Disable' if first['enabled'] else 'Enable')
        else:
            text = 'No private extension installed.'
        if self.manifest:
            text += f"<br>Available: {self.manifest['name']} {self.manifest['version']}"
        self.ext_state.setText(text)
        self.toggle_button.setVisible(bool(installed))
        self.remove_button.setVisible(bool(installed))
        self.install_button.setEnabled(bool(self.manifest))
        self.check_button.setVisible(signed)
        self.install_button.setVisible(signed)

    # ------------------------------------------------------------------ actions
    def redeem(self):
        key = self.key.text().strip()
        label = self.label.text().strip()
        self.key.clear()                              # the raw key does not stay in the widget
        self.say('Activating…')
        self._run('redeem', lambda: self.session.redeem(key, label))

    def set_service(self):
        current = client.load_state().get('api_override', '')
        text, ok = QInputDialog.getText(self, 'Beta service address', 'https:// address given with your invitation '
                                        '(leave empty for the default)', text=current)
        if not ok:
            return
        text = text.strip().rstrip('/')
        previous = client.load_state().get('api_override')
        client.save_state(api_override=text or None)
        try:
            client.api_base()
        except client.BetaError as exc:
            client.save_state(api_override=previous)
            self.say(client.friendly(exc), True)
            return
        self.say('Beta service address saved.')

    def check(self):
        self.say('Checking…')
        self._run('check', self.session.latest_release)

    def install(self):
        m = self.manifest
        if not m:
            return
        installed = extensions.installed().get(m['id'])
        if installed:
            try:
                if extensions.parse_version(m['version']) < extensions.parse_version(installed['descriptor']['version']):
                    self.say('The available version is older than the installed one; nothing to do.', True)
                    return
            except ValueError:
                pass
        dialog = BetaInstallDialog(self, self.session, m)
        dialog.exec()
        if dialog.installed:
            self.say(f"Installed {m['name']} {m['version']}. Restart SPM Studio to start it.")
        self.refresh()

    def toggle_extension(self):
        installed = extensions.installed()
        if not installed:
            return
        ext_id, info = next(iter(installed.items()))
        if info['enabled']:
            extensions.set_enabled(ext_id, False)
            extensions.unload(ext_id, getattr(self.window_, 'extension_api', None))
            self.say('Disabled. Restart SPM Studio to make sure nothing of it remains in memory.')
        else:
            extensions.set_enabled(ext_id, True)
            self.say('Enabled; it starts at the next start of SPM Studio.')
        self.refresh()

    def uninstall(self):
        installed = extensions.installed()
        if not installed:
            return
        ext_id, info = next(iter(installed.items()))
        if QMessageBox.question(self, 'Uninstall', f"Uninstall {info['descriptor']['name']}? Your SPM Studio data "
                                                   'and settings are kept.') != QMessageBox.StandardButton.Yes:
            return
        extensions.unload(ext_id, getattr(self.window_, 'extension_api', None))
        extensions.uninstall(ext_id)
        self.say('Uninstalled. Restart SPM Studio to finish.')
        self.refresh()

    def return_to_stable(self):
        client.save_state(auto_check=False)
        self.auto.setChecked(False)
        for ext_id in extensions.installed():
            extensions.set_enabled(ext_id, False)
            extensions.unload(ext_id, getattr(self.window_, 'extension_api', None))
        self.say('Only stable SPM Studio updates are checked now; private extensions are disabled. Your beta '
                 'sign-in is kept (use Sign out to remove it).')
        self.refresh()

    def sign_out(self, unlink: bool):
        question = ('Disconnect this computer? It frees its place in your device limit; to use the beta here '
                    'again you will need your invitation key.') if unlink else \
            'Sign out on this computer? Enter your invitation key to sign in again.'
        if QMessageBox.question(self, 'Beta', question) != QMessageBox.StandardButton.Yes:
            return
        self._run('signout', lambda: self.session.logout(unlink=unlink))

    def rename(self):
        current = client.load_state().get('device_label', '')
        text, ok = QInputDialog.getText(self, 'Rename this computer', 'Nickname', text=current)
        if ok and text.strip():
            label = text.strip()[:40]
            self._run('rename', lambda: (self.session.rename_device(client.device_id(), label),
                                         client.save_state(device_label=label)))

    def show_devices(self):
        self._run('devices', self.session.devices)

    def open_admin(self):
        try:
            QDesktopServices.openUrl(QUrl(client.api_base() + '/admin'))
        except client.BetaError as exc:
            self.say(client.friendly(exc), True)

    # ------------------------------------------------------------------ results (GUI thread)
    def _done(self, tag, result, error):
        self._busy(False)
        if error is not None:
            if tag == 'signout':
                self.say('Signed out on this computer (the beta service could not be reached to confirm).')
            else:
                self.say(client.friendly(error), True)
            self.refresh()
            return
        if tag == 'redeem':
            self.say('Beta access is active on this computer. Looking for the private extension…')
            self.refresh()
            self.check()
            return
        elif tag == 'me':
            self.say('')
        elif tag == 'check':
            self.manifest = result
            installed = extensions.installed().get(result['id'])
            same = installed and installed['descriptor']['version'] == result['version']
            self.say('You have the latest private extension.' if same else
                     f"{result['name']} {result['version']} is available — press “Install or update…”.")
            self.install_button.setText('Install or update…' if not same else 'Reinstall…')
        elif tag == 'signout':
            self.say('Signed out on this computer.')
        elif tag == 'rename':
            self.say('Renamed.')
        elif tag == 'devices':
            DevicesDialog(self, result).exec()
        self.refresh()


class DevicesDialog(QDialog):
    """The tester's own computers (from the server) with Remove for an old one."""

    def __init__(self, page: BetaPage, data: dict):
        super().__init__(page)
        self.page = page
        self.setWindowTitle('My computers')
        self.resize(520, 360)
        v = QVBoxLayout(self)
        limit = data.get('max_devices') or 'unlimited'
        v.addWidget(QLabel(f"Registered computers: {data.get('active_devices', 0)} / {limit}"))
        self.list = QListWidget()
        self.list.setObjectName('BetaDeviceListV0013')
        mine = client.device_id()
        for d in data.get('devices', []):
            text = f"{d.get('label') or 'Computer'} — since {d.get('registered_at', '')[:10]}, last seen " \
                   f"{d.get('last_seen_at', '')[:10]}" + ('  (this computer)' if d.get('id') == mine else '')
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, d.get('id'))
            self.list.addItem(item)
        v.addWidget(self.list)
        row = QHBoxLayout()
        remove = QPushButton('Remove selected computer')
        remove.setObjectName('BetaRemoveDeviceV0013')
        remove.clicked.connect(self.remove)
        row.addWidget(remove)
        row.addStretch(1)
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)

    def remove(self):
        item = self.list.currentItem()
        if item is None:
            return
        ident = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, 'Remove computer', 'Remove this computer from your beta access? It will '
                                                         'need the invitation key again.') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.page.session.remove_device(ident)
        except Exception as exc:
            QMessageBox.warning(self, 'Remove computer', client.friendly(exc))
            return
        self.list.takeItem(self.list.row(item))
        self.page.refresh()


class _InstallWorker(QThread):
    progress = Signal(int, str)
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, session, manifest, parent=None):
        super().__init__(parent)
        self.session, self.manifest = session, manifest
        self.cancelled = False

    def run(self):
        m = self.manifest
        size = int(m['artifact']['size'])
        path = None
        try:
            self.log.emit(f"Signature of the release manifest verified with the key built into SPM Studio.")
            self.log.emit(f"Downloading {m['artifact']['name']} ({size / 1e6:.1f} MB) from the beta service …")
            last = [-1]

            def tick(done, _total):
                if self.cancelled:
                    raise client.BetaError('CANCELLED', 'Cancelled')
                percent = int(80 * done / max(1, size))
                if percent != last[0]:
                    last[0] = percent
                    self.progress.emit(percent, f'Downloading … {done / 1e6:.1f} / {size / 1e6:.1f} MB')
            path = self.session.download(m, progress=tick)
            self.log.emit(f"Size and SHA-256 match the signed manifest ({m['artifact']['sha256'][:16]}…).")
            self.progress.emit(85, 'Unpacking safely …')
            descriptor = extensions.install_archive(path, m)
            folder = extensions.root() / descriptor['id'] / descriptor['version']
            self.log.emit(f'Installed in {folder}')
            self.progress.emit(100, 'Installed. Restart SPM Studio to start it.')
            self.done.emit(descriptor)
        except Exception as exc:
            self.failed.emit(client.friendly(exc))
        finally:
            if path is not None:
                path.unlink(missing_ok=True)


class BetaInstallDialog(QDialog):
    """Install a private extension like an update: what is new, progress bar, details, Restart now / Later."""

    def __init__(self, page, session, manifest):
        super().__init__(page)
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QPlainTextEdit, QProgressBar
        from .badge import beta_badge
        self.page, self.session, self.manifest = page, session, manifest
        self.installed = False
        self.worker = None
        self.setObjectName('BetaInstallDialogV0014')
        self.setWindowTitle('Install private extension')
        self.resize(640, 520)
        v = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel(f"<b>{manifest['name']} {manifest['version']}</b> — {manifest['vendor']}")
        title.setObjectName('heading')
        head.addWidget(title)
        head.addWidget(beta_badge(self))
        head.addStretch(1)
        v.addLayout(head)
        v.addWidget(_hint('Python code that runs inside SPM Studio. Its signature and checksum are verified before '
                          'it is installed; you can disable or uninstall it at any time, your data are not touched. '
                          'Permissions: ' + ', '.join(manifest.get('permissions', []))))
        notes = QTextBrowser()
        notes.setMarkdown(str(manifest.get('changelog') or 'No release notes.'))
        v.addWidget(notes, 1)
        self.bar = QProgressBar()
        self.bar.setObjectName('BetaInstallProgressV0014')
        self.bar.setRange(0, 100)
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setObjectName('BetaInstallLogV0014')
        self.log.setReadOnly(True)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log.hide()
        v.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.details = QCheckBox('Show details')
        self.details.toggled.connect(self.log.setVisible)
        row.addWidget(self.details)
        row.addStretch(1)
        self.later = QPushButton('Cancel')
        self.later.clicked.connect(self.reject)
        self.go = QPushButton('Install')
        self.go.setObjectName('BetaInstallStartV0014')
        self.go.setProperty('primary', True)
        self.go.clicked.connect(self.start)
        self.restart = QPushButton('Restart now')
        self.restart.setObjectName('BetaInstallRestartV0014')
        self.restart.setProperty('primary', True)
        self.restart.clicked.connect(self.restart_now)
        self.restart.hide()
        for button in (self.later, self.go, self.restart):
            row.addWidget(button)
        v.addLayout(row)

    def start(self):
        self.go.setEnabled(False)
        self.bar.show()
        self.bar.setValue(0)
        self.later.setText('Cancel')
        self.worker = _InstallWorker(self.session, self.manifest, self)
        self.worker.progress.connect(self._progress)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _progress(self, percent, text):
        self.bar.setValue(percent)
        self.status.setText(text)

    def _done(self, _descriptor):
        self.installed = True
        self.go.hide()
        self.later.setText('Later')
        self.restart.show()
        self.restart.setFocus()

    def _failed(self, message):
        self.status.setText('⚠ ' + message + ' Nothing was installed.')
        self.log.appendPlainText('ERROR: ' + message)
        self.details.setChecked(True)
        self.go.setEnabled(True)
        self.go.setText('Try again')

    def restart_now(self):
        from spm_studio.ui.update_dialog import restart_app
        window = getattr(self.page, 'window_', None)
        self.accept()
        restart_app(window)

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancelled = True
            self.worker.wait(15000)
        super().reject()
