"""Literature sources of the assistant — Consensus and Zotero — as a page of the **Agent Hub settings**.

v0.1.0: moved here from SPM Studio's main Settings (one place for every AI option). The page is the same as
before (v0.0.7) and edits the same settings file, so nothing had to be copied: your connections, keys (in the
keyring) and choices are kept as they were.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from spm_studio.shared.dialogs import MessageDialog
from spm_studio.ui.settings_dialog import _ConsensusSignIn, _Task, _hint, _icon_button


class LiteraturePage(QWidget):
    """``LiteraturePage(window, changed=callable)``; ``stop()`` ends a pending sign-in and background checks."""
    title = 'Literature (Consensus & Zotero)'

    def __init__(self, window=None, changed=None, parent=None):
        super().__init__(parent)
        self.window_ = window
        self.changed = changed or (lambda: None)
        self._lit_tasks = []
        self._signin = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._literature_page())

    @staticmethod
    def _page(title: str, subtitle: str = ''):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 0, 10, 8)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName('heading')
        layout.addWidget(heading)
        if subtitle:
            layout.addWidget(_hint(subtitle))
        return widget, layout

    def _log(self, text: str, important: bool = False):
        try:
            self.window_.log(text) if self.window_ is not None and hasattr(self.window_, 'log') else None
        except Exception:
            pass

    def stop(self):
        signin = getattr(self, '_signin', None)
        if signin is not None and signin.isRunning():
            signin.cancel()
            signin.wait(3000)
        for task in list(getattr(self, '_lit_tasks', [])):
            task.wait(4000)

    def hideEvent(self, event):
        super().hideEvent(event)

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    def _literature_page(self):
        from spm_studio.ai import literature
        from spm_studio.ai.config import load
        conf = load()
        self._lit_tasks = []
        self._signin = None
        page, layout = self._page(
            'Literature',
            'Let the assistant look things up in the published literature and in your own reference library. '
            'It only reads; it can never change your library. Connect a source once here and it works with '
            'every assistant, in ordinary chat too.')

        # ---- Consensus
        box = QGroupBox('Consensus')
        v = QVBoxLayout(box)
        v.addWidget(_hint(
            'consensus.app searches peer-reviewed papers. Sign in with your own Consensus account — your '
            'university e-mail uses your institution’s licence — and, if you linked Zotero inside Consensus, '
            'Consensus uses it too. The sign-in page opens in your browser; SPM Studio never sees your password.'))
        self.consensus_state = QLabel('')
        self.consensus_state.setObjectName('ConsensusStateV007')
        self.consensus_state.setWordWrap(True)
        v.addWidget(self.consensus_state)
        row = QHBoxLayout()
        self.consensus_signin = _icon_button('Sign in to Consensus', 'link',
                                             'Opens the Consensus sign-in page in your browser')
        self.consensus_signin.setObjectName('ConsensusSignInV007')
        self.consensus_signin.setProperty('primary', True)
        self.consensus_signin.clicked.connect(self._consensus_sign_in)
        self.consensus_cancel = QPushButton('Cancel')
        self.consensus_cancel.clicked.connect(self._consensus_cancel)
        self.consensus_cancel.hide()
        self.consensus_test = QPushButton('Test')
        self.consensus_test.setToolTip('Check the connection to Consensus')
        self.consensus_test.clicked.connect(self._consensus_test)
        self.consensus_signout = QPushButton('Sign out')
        self.consensus_signout.clicked.connect(self._consensus_sign_out)
        for button in (self.consensus_signin, self.consensus_cancel, self.consensus_test, self.consensus_signout):
            row.addWidget(button)
        row.addStretch(1)
        v.addLayout(row)
        self.consensus_progress = QProgressBar()
        self.consensus_progress.setProperty('role', 'activity')
        self.consensus_progress.setRange(0, 0)
        self.consensus_progress.setTextVisible(False)
        self.consensus_progress.hide()
        v.addWidget(self.consensus_progress)
        self.consensus_status = _hint('')
        self.consensus_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.consensus_status)
        self.consensus_enabled = QCheckBox('Let the assistant use Consensus')
        self.consensus_enabled.setObjectName('ConsensusEnabledV005')
        self.consensus_enabled.setChecked(bool(conf.get('consensus_enabled')))
        self.consensus_enabled.clicked.connect(lambda _=False: self._literature_apply())
        v.addWidget(self.consensus_enabled)
        self.consensus_advanced = QGroupBox('Advanced: use an API key instead')
        self.consensus_advanced.setCheckable(True)
        self.consensus_advanced.setChecked(False)
        adv = QVBoxLayout(self.consensus_advanced)
        self.consensus_key_help = _hint('Only if your organisation gave you a Consensus API key (consensus.app › profile › '
                                        'API & MCP Dashboard › Keys). Otherwise use “Sign in to Consensus”.')
        adv.addWidget(self.consensus_key_help)
        key_row = QHBoxLayout()
        self.consensus_key = QLineEdit()
        self.consensus_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.consensus_key.setPlaceholderText('Consensus API key')
        self.consensus_key_save = QPushButton('Save key')
        self.consensus_key_save.clicked.connect(self._consensus_save_key)
        key_row.addWidget(self.consensus_key, 1)
        key_row.addWidget(self.consensus_key_save)
        adv.addLayout(key_row)
        self._consensus_advanced_widgets = (self.consensus_key_help, self.consensus_key, self.consensus_key_save)
        self.consensus_advanced.toggled.connect(self._consensus_advanced_toggled)
        self._consensus_advanced_toggled(False)
        v.addWidget(self.consensus_advanced)
        layout.addWidget(box)

        # ---- Zotero
        box = QGroupBox('Zotero')
        v = QVBoxLayout(box)
        v.addWidget(_hint('Your own references: the assistant can search your library and read abstracts, notes and '
                          'the text of indexed PDFs. Works with or without Consensus, and nothing leaves this computer.'))
        self.zotero_state = QLabel('')
        self.zotero_state.setObjectName('ZoteroStateV007')
        self.zotero_state.setWordWrap(True)
        v.addWidget(self.zotero_state)
        row = QHBoxLayout()
        self.zotero_connect = _icon_button('Connect Zotero', 'link', 'Find Zotero on this computer and connect it')
        self.zotero_connect.setObjectName('ZoteroConnectV007')
        self.zotero_connect.setProperty('primary', True)
        self.zotero_connect.clicked.connect(self._zotero_connect)
        self.zotero_test_button = QPushButton('Test')
        self.zotero_test_button.clicked.connect(self._zotero_test)
        self.zotero_disconnect = QPushButton('Disconnect')
        self.zotero_disconnect.clicked.connect(self._zotero_disconnect)
        for button in (self.zotero_connect, self.zotero_test_button, self.zotero_disconnect):
            row.addWidget(button)
        row.addStretch(1)
        v.addLayout(row)
        self.zotero_status = _hint('')
        self.zotero_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.zotero_status)

        self.zotero_advanced = QGroupBox('Advanced: choose how Zotero is read')
        self.zotero_advanced.setCheckable(True)
        self.zotero_advanced.setChecked(conf.get('zotero_mode') in ('local', 'database', 'web'))
        adv = QVBoxLayout(self.zotero_advanced)
        self.zotero_advanced_body = QWidget()
        form = QFormLayout(self.zotero_advanced_body)
        form.setContentsMargins(0, 0, 0, 0)
        self.zotero_mode = QComboBox()
        self.zotero_mode.setObjectName('ZoteroModeV005')
        self.zotero_mode.addItem('Not connected', 'off')
        self.zotero_mode.addItem('Automatic (recommended)', 'auto')
        self.zotero_mode.addItem('Zotero database file — any version, Zotero may be closed', 'database')
        self.zotero_mode.addItem('Zotero app — version 7 or later, must be running', 'local')
        self.zotero_mode.addItem('zotero.org account — library on the web', 'web')
        self.zotero_mode.setCurrentIndex(max(0, self.zotero_mode.findData(conf.get('zotero_mode', 'off'))))
        form.addRow('Read from', self.zotero_mode)
        self.zotero_mode_help = _hint('')
        form.addRow('', self.zotero_mode_help)
        folder_row = QWidget()
        fr = QHBoxLayout(folder_row)
        fr.setContentsMargins(0, 0, 0, 0)
        self.zotero_folder = QLineEdit(str(conf.get('zotero_data_dir', '')))
        self.zotero_folder.setPlaceholderText('Found automatically — fill in only if your Zotero data is elsewhere')
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._zotero_browse)
        fr.addWidget(self.zotero_folder, 1)
        fr.addWidget(browse)
        form.addRow('Data folder', folder_row)
        self.zotero_folder_row = (form.labelForField(folder_row), folder_row)
        self.zotero_type = QComboBox()
        self.zotero_type.addItem('My library', 'user')
        self.zotero_type.addItem('Group library', 'group')
        self.zotero_type.setCurrentIndex(max(0, self.zotero_type.findData(conf.get('zotero_library_type', 'user'))))
        self.zotero_id = QLineEdit(str(conf.get('zotero_library_id', '')))
        self.zotero_id.setPlaceholderText('Numeric user ID (zotero.org › Settings › Security) or group ID')
        self.zotero_key = QLineEdit()
        self.zotero_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.zotero_key.setPlaceholderText('Stored — leave empty to keep it' if literature.zotero_api_key()
                                           else 'Private key with read-only library access')
        self.zotero_web_rows = []
        for label, widget in (('Library', self.zotero_type), ('Library ID', self.zotero_id), ('API key', self.zotero_key)):
            form.addRow(label, widget)
            self.zotero_web_rows.append((form.labelForField(widget), widget))
        adv.addWidget(self.zotero_advanced_body)
        row = QHBoxLayout()
        self.zotero_save = QPushButton('Save and test')
        self.zotero_save.setObjectName('LiteratureApplyV005')
        self.zotero_save.clicked.connect(lambda: (self._literature_apply(), self._zotero_test()))
        keys = QPushButton('Open zotero.org key page')
        keys.clicked.connect(lambda: open_url('https://www.zotero.org/settings/security'))
        self.zotero_keys_button = keys
        row.addWidget(self.zotero_save)
        row.addWidget(keys)
        row.addStretch(1)
        self.zotero_advanced_buttons = QWidget()
        self.zotero_advanced_buttons.setLayout(row)
        adv.addWidget(self.zotero_advanced_buttons)
        self.zotero_advanced.toggled.connect(self._zotero_advanced_toggled)
        v.addWidget(self.zotero_advanced)
        layout.addWidget(box)

        self.literature_result = _hint('')
        layout.addWidget(self.literature_result)
        self.literature_agent = _hint('')
        layout.addWidget(self.literature_agent)
        layout.addStretch(1)
        self.zotero_mode.currentIndexChanged.connect(lambda _=0: self._literature_sync())
        self._zotero_advanced_toggled(self.zotero_advanced.isChecked())
        self._literature_sync()
        self._literature_refresh_state()
        return page

    # ---- shared state
    def _consensus_advanced_toggled(self, on):
        for widget in self._consensus_advanced_widgets:
            widget.setVisible(bool(on))

    def _zotero_advanced_toggled(self, on):
        self.zotero_advanced_body.setVisible(bool(on))
        self.zotero_advanced_buttons.setVisible(bool(on))

    def _literature_sync(self):
        mode = self.zotero_mode.currentData()
        self.zotero_mode_help.setText({
            'off': 'The assistant does not use Zotero.',
            'auto': 'Asks the Zotero app when it is running and allows it, otherwise reads the database file. '
                    'Nothing to set up.',
            'database': 'Reads zotero.sqlite in your Zotero data folder, read-only. Works with every Zotero version, '
                        'whether Zotero is open or not, and needs no setting in Zotero.',
            'local': 'Zotero 7 or later must be running, with Settings › Advanced › “Allow other applications on this '
                     'computer to communicate with Zotero” ticked. Also searches inside indexed PDFs.',
            'web': 'Reads your library on zotero.org. Create a private key with read-only library access at '
                   'zotero.org › Settings › Security; it is kept on this computer only.'}.get(mode, ''))
        for label_widget, widget in self.zotero_web_rows:
            widget.setVisible(mode == 'web')
            if label_widget is not None:
                label_widget.setVisible(mode == 'web')
        self.zotero_keys_button.setVisible(mode == 'web')
        folder_label, folder_widget = self.zotero_folder_row
        folder_widget.setVisible(mode in ('auto', 'database'))
        if folder_label is not None:
            folder_label.setVisible(mode in ('auto', 'database'))

    def _literature_refresh_state(self):
        """Status lines of both sources, from what is stored (no network)."""
        from spm_studio.ai import consensus, literature
        from spm_studio.ai.config import load
        conf = load()
        signed = consensus.signed_in()
        on = bool(conf.get('consensus_enabled'))
        if signed and on:
            self.consensus_state.setText('<b>Connected.</b> The assistant can search Consensus.')
        elif signed:
            self.consensus_state.setText('<b>Signed in, but switched off.</b> Tick the box below to let the assistant use it.')
        else:
            self.consensus_state.setText('<b>Not connected.</b> Click “Sign in to Consensus”.')
        self.consensus_signin.setText('Sign in again' if signed else 'Sign in to Consensus')
        self.consensus_signout.setEnabled(signed)
        self.consensus_test.setEnabled(signed)
        self.consensus_enabled.setEnabled(signed)
        self.consensus_enabled.setChecked(on and signed)
        zotero_on = literature.zotero_enabled(conf)
        self.zotero_state.setText('<b>Connected.</b> The assistant can read your Zotero library.' if zotero_on else
                                  '<b>Not connected.</b> Click “Connect Zotero”.')
        self.zotero_connect.setText('Connect again' if zotero_on else 'Connect Zotero')
        self.zotero_disconnect.setEnabled(zotero_on)
        self.zotero_test_button.setEnabled(zotero_on)
        backend = str(conf.get('backend', 'none'))
        self.literature_agent.setText(
            'No assistant is set up yet (General › AI assistant…): the sources are ready for when one is.'
            if backend == 'none' else
            'The assistant looks things up when you ask for literature, references or what is in your library — '
            'for example: “What does my Zotero library say about KPFM on graphene?”')

    def _restart_assistant(self):
        """The assistant uses a changed source from its next message (Agent Hub reads the same settings)."""
        try:
            self.changed()
        except Exception as exc:
            self._log('Could not tell the assistant: ' + str(exc))

    def _run_task(self, fn, on_done):
        """Run ``fn()`` off the GUI thread; ``on_done(result, error_text)`` back in the GUI thread."""
        task = _Task(fn, on_done, self)
        self._lit_tasks.append(task)
        task.finished_with.connect(self._task_finished)
        task.start()
        return task

    def _task_finished(self, task, result, error):
        if task in self._lit_tasks:
            self._lit_tasks.remove(task)
        task.on_done(result, error)

    def _literature_conf(self) -> dict:
        from spm_studio.ai.config import load
        conf = load()
        conf['consensus_enabled'] = self.consensus_enabled.isChecked()
        conf['zotero_mode'] = str(self.zotero_mode.currentData())
        conf['zotero_library_type'] = str(self.zotero_type.currentData())
        conf['zotero_library_id'] = self.zotero_id.text().strip()
        conf['zotero_data_dir'] = self.zotero_folder.text().strip()
        return conf

    def _store_zotero_key(self) -> str:
        key = self.zotero_key.text().strip()
        if not key:
            return ''
        from spm_studio.ai import lit_store, literature
        note = lit_store.put(literature.ZOTERO_KEY_NAME, key)
        self.zotero_key.clear()
        self.zotero_key.setPlaceholderText('Stored — leave empty to keep it')
        return 'Key ' + note

    def _literature_apply(self):
        """Save what the page shows (used by the tick box and by “Save and test”)."""
        from spm_studio.ai.config import save
        conf = self._literature_conf()
        if conf['zotero_mode'] == 'web' and not conf['zotero_library_id'].isdigit():
            self.literature_result.setText('The Zotero library ID is a number (zotero.org › Settings › Security).')
            return False
        key_note = self._store_zotero_key()
        try:
            save(conf)
        except (OSError, ValueError) as exc:
            self.literature_result.setText('Not saved: ' + str(exc))
            return False
        self.literature_result.setText('Saved.' + (f' {key_note}.' if key_note else ''))
        self._log('Literature sources saved')
        self._literature_refresh_state()
        self._restart_assistant()
        return True

    # ---- Consensus
    def _consensus_busy(self, on: bool, text: str = ''):
        self.consensus_progress.setVisible(on)
        self.consensus_cancel.setVisible(on)
        self.consensus_signin.setEnabled(not on)
        if text:
            self.consensus_status.setText(text)

    def _consensus_sign_in(self):
        if self._signin is not None and self._signin.isRunning():
            return
        worker = _ConsensusSignIn(self)
        self._signin = worker
        worker.opened.connect(self._consensus_opened)
        worker.done.connect(self._consensus_signed_in)
        worker.failed.connect(self._consensus_failed)
        self._consensus_busy(True, 'Contacting Consensus…')
        worker.start()

    def _consensus_opened(self, url):
        opened = QDesktopServices.openUrl(QUrl(url))
        self._signin_url = url
        self.consensus_status.setText(
            'Your browser opened the Consensus sign-in page. Sign in there (your university e-mail works), allow '
            'SPM Studio, then come back here — this page updates by itself.' if opened else
            'Open this address in your browser to sign in: ' + url)

    def _consensus_cancel(self):
        if self._signin is not None:
            self._signin.cancel()

    def _consensus_signed_in(self, stored):
        from spm_studio.ai.config import load, save
        self._consensus_busy(False)
        conf = load()
        conf['consensus_enabled'] = True
        try:
            save(conf)
        except (OSError, ValueError) as exc:
            self.consensus_status.setText('Signed in, but the setting could not be saved: ' + str(exc))
            return
        self.consensus_status.setText('Signed in. The sign-in is ' + stored + '.')
        self._log('Consensus: signed in')
        self._literature_refresh_state()
        self._restart_assistant()
        self.raise_()
        self.activateWindow()

    def _consensus_failed(self, message):
        self._consensus_busy(False)
        self.consensus_status.setText('Not signed in — ' + message)
        self._literature_refresh_state()

    def _consensus_test(self):
        from spm_studio.ai import consensus
        self.consensus_status.setText('Checking…')
        self.consensus_test.setEnabled(False)

        def done(result, error):
            self.consensus_test.setEnabled(True)
            if error:
                self.consensus_status.setText('Problem: ' + error)
            else:
                self.consensus_status.setText(('OK: ' if result['connected'] else 'Problem: ') + result['message'])
        self._run_task(consensus.status, done)

    def _consensus_sign_out(self):
        from spm_studio.ai import consensus
        from spm_studio.ai.config import load, save
        consensus.sign_out()
        conf = load()
        conf['consensus_enabled'] = False
        try:
            save(conf)
        except (OSError, ValueError):
            pass
        self.consensus_status.setText('Signed out: the sign-in was removed from this computer.')
        self._literature_refresh_state()
        self._restart_assistant()

    def _consensus_save_key(self):
        from spm_studio.ai import consensus, lit_store
        from spm_studio.ai.config import load, save
        key = self.consensus_key.text().strip()
        if not key:
            self.consensus_status.setText('Paste the API key first.')
            return
        note = lit_store.put(consensus.API_KEY_NAME, key)
        self.consensus_key.clear()
        conf = load()
        conf['consensus_enabled'] = True
        try:
            save(conf)
        except (OSError, ValueError):
            pass
        self.consensus_status.setText('API key ' + note + '.')
        self._literature_refresh_state()
        self._restart_assistant()
        self._consensus_test()

    # ---- Zotero
    def _zotero_browse(self):
        start = self.zotero_folder.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, 'Zotero data folder (contains zotero.sqlite)', start)
        if chosen:
            self.zotero_folder.setText(chosen)

    def _zotero_connect(self):
        """One click: find Zotero on this computer (app or database file) and connect it."""
        from spm_studio.ai import literature
        conf = self._literature_conf()
        self.zotero_connect.setEnabled(False)
        self.zotero_status.setText('Looking for Zotero on this computer…')

        def done(found, error):
            self.zotero_connect.setEnabled(True)
            if error or not found or not found.get('found'):
                self.zotero_advanced.setChecked(True)
                self.zotero_status.setText(
                    'Problem: ' + (error or 'No Zotero library was found on this computer. If Zotero is installed, start it '
                            'once, or choose its data folder below (Zotero shows it in Settings › Advanced › Files '
                            'and Folders). For a library kept only on zotero.org, choose “zotero.org account”.'))
                return
            self.zotero_mode.setCurrentIndex(self.zotero_mode.findData('auto'))
            if not self._literature_apply():
                return
            parts = []
            if found.get('data_dir'):
                parts.append(f"{found.get('items')} items in {found['data_dir']}")
            parts.append('the Zotero app answers too (indexed PDFs are searched as well)' if found.get('app') else
                         'read from the database file — Zotero does not need to be open')
            self.zotero_status.setText('OK: connected — ' + '; '.join(parts) + '.')
        self._run_task(lambda: literature.detect_zotero(conf), done)

    def _zotero_test(self):
        from spm_studio.ai import literature
        conf = self._literature_conf()
        if conf['zotero_mode'] == 'off':
            self.zotero_status.setText('Not connected. Click “Connect Zotero”.')
            return
        self._store_zotero_key()
        self.zotero_status.setText('Checking…')

        def done(status, error):
            if error:
                self.zotero_status.setText('Problem: ' + error)
            else:
                self.zotero_status.setText(('OK: ' if status['connected'] else 'Problem: ') + status['message'])
        self._run_task(lambda: literature.zotero_status(conf), done)

    def _zotero_disconnect(self):
        self.zotero_mode.setCurrentIndex(self.zotero_mode.findData('off'))
        if self._literature_apply():
            self.zotero_status.setText('Disconnected. Nothing was changed in Zotero.')
