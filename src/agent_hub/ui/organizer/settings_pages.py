"""Settings pages of the calendar, the to-do list, e-mail and the assistant's use of them. They are pages of
the Agent Hub settings window (``ui/settings_dialog.py``); ``open_organizer_settings`` opens that window on the
right page, or — without an engine (calendar / to-do used without any AI) — a small window with the same page.
Credentials typed here go to the system keyring only."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ...organizer import secrets
from .. import theme
from ..svg_icons import icon, set_icon

DOCS = 'docs/EMAIL_CALENDAR_OAUTH.md'


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setObjectName('hubHint')
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setOpenExternalLinks(True)
    return lab


def _keyring_note() -> str:
    return ('Passwords and tokens are stored in the system keyring.' if secrets.secure() else
            '<b>No secure keyring was found</b>: passwords and tokens are kept in memory for this session only '
            '(nothing is written to a file). Install a Secret Service / KWallet keyring to keep them.')


class _Job:
    def __init__(self, parent, fn, done):
        from .cards import _Job as J
        self.job = J(fn, parent)
        self.job.done.connect(done)
        self.job.start()


# ====================================================================== calendar
class CalendarPage(QWidget):
    title = 'Calendar'

    def __init__(self, organizer, conf: dict, parent=None):
        super().__init__(parent)
        self.org = organizer
        self.jobs = []
        lay = QVBoxLayout(self)
        box = QGroupBox('Display and reminders')
        f = QFormLayout(box)
        self.week = QComboBox()
        self.week.addItem('Monday', 0)
        self.week.addItem('Sunday', 6)
        self.week.setCurrentIndex(1 if conf.get('calendar_week_start') == 6 else 0)
        f.addRow('Week starts on', self.week)
        self.view = QComboBox()
        for k, label in (('day', 'Day'), ('week', 'Week'), ('month', 'Month'), ('schedule', 'Schedule')):
            self.view.addItem(label, k)
        self.view.setCurrentIndex(max(0, self.view.findData(conf.get('calendar_default_view', 'week'))))
        f.addRow('Opens in', self.view)
        self.day_start = QSpinBox()
        self.day_start.setRange(0, 12)
        self.day_start.setValue(int(conf.get('calendar_day_start', 8)))
        self.day_start.setSuffix(':00')
        f.addRow('Day and week views scroll to', self.day_start)
        row = QHBoxLayout()
        self.work_start = QSpinBox()
        self.work_start.setRange(0, 23)
        self.work_start.setValue(int(conf.get('calendar_work_start', 9)))
        self.work_end = QSpinBox()
        self.work_end.setRange(1, 24)
        self.work_end.setValue(int(conf.get('calendar_work_end', 18)))
        row.addWidget(self.work_start)
        row.addWidget(QLabel('to'))
        row.addWidget(self.work_end)
        row.addStretch(1)
        f.addRow('Working hours (free time, planning)', row)
        self.reminder = QComboBox()
        for label, m in (('None', -1), ('At the start', 0), ('5 minutes before', 5), ('10 minutes before', 10),
                         ('30 minutes before', 30), ('1 hour before', 60), ('1 day before', 1440)):
            self.reminder.addItem(label, m)
        self.reminder.setCurrentIndex(max(0, self.reminder.findData(int(conf.get('calendar_default_reminder', 10)))))
        f.addRow('Default notification for new events', self.reminder)
        self.notify = QCheckBox('Desktop notifications for reminders while the app runs')
        self.notify.setChecked(bool(conf.get('calendar_notifications', True)))
        f.addRow(self.notify)
        self.summary = QCheckBox('On start, show missed and upcoming reminders')
        self.summary.setChecked(bool(conf.get('calendar_start_summary', True)))
        f.addRow(self.summary)
        lay.addWidget(box)
        box = QGroupBox('Import, export and subscriptions')
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        b = QPushButton('Import an .ics file…')
        set_icon(b, 'import')
        b.clicked.connect(self.import_ics)
        row.addWidget(b)
        b = QPushButton('Export all as .ics…')
        set_icon(b, 'export')
        b.clicked.connect(self.export_ics)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        row = QHBoxLayout()
        self.sub_url = QLineEdit()
        self.sub_url.setPlaceholderText('https://… or webcal://… (read-only)')
        self.sub_interval = QSpinBox()
        self.sub_interval.setRange(15, 10080)
        self.sub_interval.setValue(360)
        self.sub_interval.setSuffix(' min')
        self.sub_interval.setToolTip('Refresh interval')
        add = QPushButton('Subscribe')
        set_icon(add, 'link')
        add.clicked.connect(self.subscribe)
        row.addWidget(self.sub_url, 1)
        row.addWidget(self.sub_interval)
        row.addWidget(add)
        v.addLayout(row)
        self.subs = QListWidget()
        self.subs.setMaximumHeight(110)
        v.addWidget(self.subs)
        row = QHBoxLayout()
        b = QPushButton('Refresh selected')
        b.clicked.connect(self.refresh_selected)
        r = QPushButton('Remove selected')
        r.clicked.connect(self.remove_selected)
        row.addWidget(b)
        row.addWidget(r)
        row.addStretch(1)
        v.addLayout(row)
        lay.addWidget(box)
        box = QGroupBox('Two-way sync (optional)')
        v = QVBoxLayout(box)
        v.addWidget(_hint('Google Calendar and Microsoft 365 / Outlook use <b>your own OAuth client id</b> (free; '
                          f'step-by-step guide in <code>{DOCS}</code>). iCloud and other CalDAV servers use your user '
                          'name and an <b>app-specific password</b>. ' + _keyring_note() +
                          ' Sync never sends invitations.'))
        f = QFormLayout()
        self.provider = QComboBox()
        for label, key in (('iCloud (CalDAV)', 'icloud'), ('Other CalDAV server (Nextcloud, Fastmail, university…)',
                                                           'caldav'),
                           ('Google Calendar (OAuth)', 'google'), ('Microsoft 365 / Outlook (OAuth)', 'microsoft')):
            self.provider.addItem(label, key)
        f.addRow('Service', self.provider)
        self.url = QLineEdit('https://caldav.icloud.com/')
        f.addRow('Server address', self.url)
        self.user = QLineEdit()
        self.user.setPlaceholderText('Apple ID / user name / e-mail')
        f.addRow('Account', self.user)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText('app-specific password (kept in the keyring)')
        f.addRow('Password', self.password)
        self.client_id = QLineEdit()
        self.client_id.setPlaceholderText('your OAuth client id')
        f.addRow('OAuth client id', self.client_id)
        self.client_secret = QLineEdit()
        self.client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret.setPlaceholderText('Google desktop client only: its client secret (keyring)')
        f.addRow('OAuth client secret', self.client_secret)
        self.interval = QSpinBox()
        self.interval.setRange(5, 1440)
        self.interval.setValue(30)
        self.interval.setSuffix(' min')
        f.addRow('Sync every', self.interval)
        v.addLayout(f)
        row = QHBoxLayout()
        self.connect_b = QPushButton('Connect and add calendar…')
        set_icon(self.connect_b, 'refresh')
        self.connect_b.clicked.connect(self.connect_sync)
        self.sync_now = QPushButton('Sync now')
        self.sync_now.clicked.connect(self.sync_all)
        row.addWidget(self.connect_b)
        row.addWidget(self.sync_now)
        row.addStretch(1)
        v.addLayout(row)
        self.sync_status = _hint('')
        v.addWidget(self.sync_status)
        lay.addWidget(box)
        lay.addStretch(1)
        self.provider.currentIndexChanged.connect(self._provider)
        self._provider()
        self.fill()

    def _provider(self):
        key = self.provider.currentData()
        caldav = key in ('icloud', 'caldav')
        for w in (self.url, self.user, self.password):
            w.setEnabled(caldav)
        self.client_id.setEnabled(not caldav)
        self.client_secret.setEnabled(key == 'google')
        if key == 'icloud':
            self.url.setText('https://caldav.icloud.com/')
        elif key == 'caldav' and 'icloud' in self.url.text():
            self.url.setText('https://')

    def fill(self):
        self.subs.clear()
        for c in self.org.calendar.calendars():
            if c.get('kind') in ('subscription', 'caldav', 'google', 'microsoft'):
                s = c.get('source') or {}
                state = s.get('last_error') or ('synchronised' if s.get('last_sync') else 'not synchronised yet')
                item = QListWidgetItem(theme.dot_icon(c['color']), f"{c['name']} · {c['kind']} · {state}")
                item.setData(Qt.ItemDataRole.UserRole, c['id'])
                self.subs.addItem(item)

    def import_ics(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import an .ics file', '', 'Calendar (*.ics *.ical)')
        if path:
            from pathlib import Path
            try:
                r = self.org.calendar.import_ics(Path(path).read_text(encoding='utf8', errors='replace'),
                                                 name=Path(path).stem)
                self.org.changed('calendar')
                QMessageBox.information(self, 'Import', f"{r['added']} event(s) added, {r['updated']} updated.")
            except Exception as exc:
                QMessageBox.warning(self, 'Import', str(exc))
            self.fill()

    def export_ics(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export', 'calendar.ics', 'Calendar (*.ics)')
        if path:
            from pathlib import Path
            Path(path).write_text(self.org.calendar.export_ics(), encoding='utf8')

    def subscribe(self):
        from ...organizer import sync
        try:
            cal = sync.subscribe(self.org.calendar, self.sub_url.text(), interval_min=self.sub_interval.value())
        except ValueError as exc:
            QMessageBox.warning(self, 'Subscribe', str(exc))
            return
        self.sub_url.clear()
        self.jobs.append(_Job(self, lambda: sync.refresh_subscription(self.org.calendar, cal['id']),
                              lambda r, err: (self.sync_status.setText(err or f"{r['events']} event(s) loaded."),
                                              self.org.changed('calendar'), self.fill())))
        self.fill()

    def _selected(self):
        item = self.subs.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ''

    def refresh_selected(self):
        cid = self._selected()
        if not cid:
            return
        from ...organizer import sync
        cal = self.org.calendar.calendar(cid)
        if cal.get('kind') == 'subscription':
            fn = lambda: sync.refresh_subscription(self.org.calendar, cid)
        else:
            fn = lambda: sync.two_way(self.org.calendar, cid, sync.remote_for(self.org.calendar, cid))
        self.sync_status.setText('Working…')
        self.jobs.append(_Job(self, fn, lambda r, err: (self.sync_status.setText(err or f'Done: {r}'),
                                                        self.org.changed('calendar'), self.fill())))

    def remove_selected(self):
        cid = self._selected()
        if cid and QMessageBox.question(self, 'Remove', 'Remove this calendar from this computer (it stays on its '
                                        'server)?') == QMessageBox.StandardButton.Yes:
            self.org.calendar.delete_calendar(cid)
            secrets.delete('caldav:' + cid)
            self.org.changed('calendar')
            self.fill()

    def connect_sync(self):
        from ...organizer import sync
        key = self.provider.currentData()
        if key in ('icloud', 'caldav'):
            url, user, password = self.url.text().strip(), self.user.text().strip(), self.password.text()
            if not (url and user and password):
                QMessageBox.warning(self, 'Sync', 'Enter the server, the account and the app password.')
                return
            self.sync_status.setText('Looking for your calendars…')

            def found(cals, err):
                if err:
                    self.sync_status.setText('Could not connect: ' + err)
                    return
                if not cals:
                    self.sync_status.setText('No calendar found on this account.')
                    return
                names = [c['name'] for c in cals]
                choice, ok = QInputDialog.getItem(self, 'CalDAV', 'Calendar to synchronise:', names, 0, False)
                if not ok:
                    return
                c = cals[names.index(choice)]
                cal = self.org.calendar.add_calendar(c['name'], c['color'] or '', kind='caldav',
                                                     source={'url': c['url'], 'username': user,
                                                             'interval_min': self.interval.value()})
                where = secrets.put('caldav:' + cal['id'], password)
                self.password.clear()
                self.sync_status.setText(f"Added “{c['name']}” (password in the {where}). Synchronising…")
                self.jobs.append(_Job(self, lambda: sync.two_way(self.org.calendar, cal['id'],
                                                                 sync.remote_for(self.org.calendar, cal['id'])),
                                      lambda r, e: (self.sync_status.setText(e or f'Synchronised: {r}'),
                                                    self.org.changed('calendar'), self.fill())))
            self.jobs.append(_Job(self, lambda: sync.CalDAV(url, user, password).discover(), found))
            return
        cid = self.client_id.text().strip()
        if not cid:
            QMessageBox.warning(self, 'Sync', f'Enter your OAuth client id first (guide: {DOCS}).')
            return
        if key == 'google' and self.client_secret.text():
            secrets.put('oauth-secret:google', self.client_secret.text())
            self.client_secret.clear()
        cal = self.org.calendar.add_calendar('Google Calendar' if key == 'google' else 'Outlook calendar',
                                             kind=key, source={'client_id': cid, 'interval_min': self.interval.value()})
        cal['source']['account_id'] = cal['id']
        self.org.calendar.update_calendar(cal['id'], source=cal['source'])
        from ...organizer import oauth
        account = {'id': cal['id'], 'address': '', 'oauth': {'client_id': cid}}
        scopes = oauth.PROVIDERS[key]['calendar_scopes']
        self.sync_status.setText('Your browser opens to sign in…')

        def signed(r, err):
            if err:
                self.org.calendar.delete_calendar(cal['id'])
                self.sync_status.setText('Sign-in failed: ' + err)
            else:
                self.sync_status.setText('Signed in. Synchronising…')
                self.jobs.append(_Job(self, lambda: sync.two_way(self.org.calendar, cal['id'],
                                                                 sync.remote_for(self.org.calendar, cal['id'])),
                                      lambda r2, e2: (self.sync_status.setText(e2 or f'Synchronised: {r2}'),
                                                      self.org.changed('calendar'))))
            self.fill()
        self.jobs.append(_Job(self, lambda: oauth.authorize(key, account, scopes), signed))

    def sync_all(self):
        from ...organizer import sync
        ids = [c['id'] for c in self.org.calendar.calendars() if c.get('kind') in ('caldav', 'google', 'microsoft')]
        if not ids:
            self.sync_status.setText('No synchronised calendar yet.')
            return

        def work():
            out = {}
            for cid in ids:
                try:
                    out[cid] = sync.two_way(self.org.calendar, cid, sync.remote_for(self.org.calendar, cid))
                except Exception as exc:
                    out[cid] = secrets.redact(str(exc))[:120]
            return out
        self.sync_status.setText('Synchronising…')
        self.jobs.append(_Job(self, work, lambda r, err: (self.sync_status.setText(err or f'Done: {r}'),
                                                          self.org.changed('calendar'), self.fill())))

    def save(self, conf: dict):
        conf.update(calendar_week_start=self.week.currentData(), calendar_default_view=self.view.currentData(),
                    calendar_day_start=self.day_start.value(), calendar_work_start=self.work_start.value(),
                    calendar_work_end=max(self.work_start.value() + 1, self.work_end.value()),
                    calendar_default_reminder=self.reminder.currentData(),
                    calendar_notifications=self.notify.isChecked(), calendar_start_summary=self.summary.isChecked())


# ====================================================================== to-do
class TodoPage(QWidget):
    title = 'To-do'

    def __init__(self, organizer, conf: dict, parent=None):
        super().__init__(parent)
        self.org = organizer
        lay = QVBoxLayout(self)
        box = QGroupBox('To-do list')
        f = QFormLayout(box)
        self.default = QComboBox()
        for l in organizer.todo.lists():
            self.default.addItem(icon(l.get('icon', 'list'), l['color']), l['name'], l['id'])
        self.default.setCurrentIndex(max(0, self.default.findData(conf.get('todo_default_list', ''))))
        f.addRow('New tasks go to', self.default)
        self.completed = QCheckBox('Show completed tasks in lists')
        self.completed.setChecked(bool(conf.get('todo_show_completed', True)))
        f.addRow(self.completed)
        self.on_cal = QCheckBox('Tasks with a deadline appear in the calendar (linked both ways)')
        self.on_cal.setChecked(bool(conf.get('todo_on_calendar', True)))
        f.addRow(self.on_cal)
        lay.addWidget(box)
        lay.addWidget(_hint('Quick add understands dates and times (<i>friday 10am</i>, <i>tomorrow</i>, <i>dec 5</i>, '
                            '<i>in 3 days</i>, <i>every monday</i>), <i>#tags</i>, <i>!high</i> / <i>!med</i> / '
                            '<i>!low</i> and <i>@List</i>. Your first to-do list was copied into this one once; the '
                            'original file is kept unchanged.'))
        lay.addStretch(1)

    def save(self, conf: dict):
        conf.update(todo_default_list=self.default.currentData() or '', todo_show_completed=self.completed.isChecked(),
                    todo_on_calendar=self.on_cal.isChecked())
        self.org.options['todo_on_calendar'] = self.on_cal.isChecked()


# ====================================================================== e-mail
class AccountDialog(QDialog):
    def __init__(self, organizer, account: dict | None = None, parent=None):
        super().__init__(parent)
        from ...organizer.mail import PRESETS
        self.org = organizer
        self.account = account
        self.setWindowTitle('E-mail account')
        self.resize(560, 600)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.preset = QComboBox()
        for key, p in PRESETS.items():
            self.preset.addItem(p['label'], key)
        self.method = QComboBox()
        self.method.addItem('Password or app password (IMAP / SMTP)', 'imap')
        self.method.addItem('Sign in with Google (OAuth, Gmail)', 'gmail')
        self.method.addItem('Sign in with Microsoft (OAuth, Microsoft Graph)', 'microsoft')
        self.address = QLineEdit()
        self.label = QLineEdit()
        self.label.setPlaceholderText('optional name shown in the app')
        self.username = QLineEdit()
        self.username.setPlaceholderText('usually the address')
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText('kept in the system keyring' if not account else 'leave empty to keep it')
        self.client_id = QLineEdit()
        self.client_id.setPlaceholderText('your OAuth client id (guide in the docs)')
        self.client_secret = QLineEdit()
        self.client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret.setPlaceholderText('Google desktop client: its secret (keyring only)')
        self.tenant = QLineEdit()
        self.tenant.setPlaceholderText('common (or your organisation\'s tenant id)')
        self.imap_host, self.imap_port, self.smtp_host, self.smtp_port = QLineEdit(), QSpinBox(), QLineEdit(), QSpinBox()
        for sp in (self.imap_port, self.smtp_port):
            sp.setRange(1, 65535)
        self.imap_sec, self.smtp_sec = QComboBox(), QComboBox()
        for c in (self.imap_sec, self.smtp_sec):
            c.addItem('SSL/TLS', 'ssl')
            c.addItem('STARTTLS', 'starttls')
        self.folders = QLineEdit('INBOX')
        self.poll = QSpinBox()
        self.poll.setRange(1, 240)
        self.poll.setValue(5)
        self.poll.setSuffix(' min')
        self.idle = QCheckBox('Use IMAP IDLE when the server supports it (new mail at once)')
        self.idle.setChecked(True)
        self.admin = QCheckBox('Turn administrative e-mails (forms, home-office reports …) into a to-do + form')
        self.admin.setChecked(True)
        self.enabled = QCheckBox('Enabled (checked in the background)')
        self.enabled.setChecked(True)
        f.addRow('Provider', self.preset)
        f.addRow('Sign-in', self.method)
        f.addRow('E-mail address', self.address)
        f.addRow('Name', self.label)
        f.addRow('User name', self.username)
        f.addRow('Password', self.password)
        f.addRow('OAuth client id', self.client_id)
        f.addRow('OAuth client secret', self.client_secret)
        f.addRow('Microsoft tenant', self.tenant)
        row = QHBoxLayout()
        row.addWidget(self.imap_host, 1)
        row.addWidget(self.imap_port)
        row.addWidget(self.imap_sec)
        f.addRow('IMAP server', row)
        row = QHBoxLayout()
        row.addWidget(self.smtp_host, 1)
        row.addWidget(self.smtp_port)
        row.addWidget(self.smtp_sec)
        f.addRow('SMTP server', row)
        f.addRow('Folders to watch', self.folders)
        f.addRow('Check every', self.poll)
        f.addRow(self.idle)
        f.addRow(self.admin)
        f.addRow(self.enabled)
        lay.addLayout(f)
        self.hint = _hint('')
        lay.addWidget(self.hint)
        lay.addWidget(_hint(_keyring_note() + ' The assistant can read and draft; it can never send — every '
                            'message waits in the outbox for your Send click.'))
        self.status = _hint('')
        lay.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        test = buttons.addButton('Test connection', QDialogButtonBox.ButtonRole.ActionRole)
        test.clicked.connect(self.test)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.preset.currentIndexChanged.connect(self._preset)
        self.method.currentIndexChanged.connect(self._method)
        self.saved = None
        self.jobs = []
        if account:
            self._load(account)
        else:
            self._preset()
        self._method()

    def _preset(self):
        from ...organizer.mail import PRESETS
        p = PRESETS[self.preset.currentData()]
        self.imap_host.setText(p['imap']['host'])
        self.imap_port.setValue(p['imap']['port'])
        self.imap_sec.setCurrentIndex(self.imap_sec.findData(p['imap']['security']))
        self.smtp_host.setText(p['smtp']['host'])
        self.smtp_port.setValue(p['smtp']['port'])
        self.smtp_sec.setCurrentIndex(self.smtp_sec.findData(p['smtp']['security']))
        self.hint.setText(html.escape(p.get('hint', '')))
        if self.preset.currentData() == 'gmail' and self.method.currentData() == 'microsoft':
            self.method.setCurrentIndex(0)

    def _method(self):
        m = self.method.currentData()
        self.password.setEnabled(m == 'imap')
        self.client_id.setEnabled(m != 'imap')
        self.client_secret.setEnabled(m == 'gmail')
        self.tenant.setEnabled(m == 'microsoft')
        for w in (self.imap_host, self.imap_port, self.smtp_host, self.smtp_port, self.imap_sec, self.smtp_sec):
            w.setEnabled(m != 'microsoft')

    def _load(self, a):
        self.preset.setCurrentIndex(max(0, self.preset.findData(a.get('preset', 'custom'))))
        self.method.setCurrentIndex(max(0, self.method.findData(a.get('kind', 'imap'))))
        self.address.setText(a['address'])
        self.address.setEnabled(False)
        self.label.setText(a.get('label', ''))
        self.username.setText(a.get('username', ''))
        self.client_id.setText((a.get('oauth') or {}).get('client_id', ''))
        self.tenant.setText((a.get('oauth') or {}).get('tenant', ''))
        self.imap_host.setText(a['imap'].get('host', ''))
        self.imap_port.setValue(int(a['imap'].get('port') or 993))
        self.imap_sec.setCurrentIndex(max(0, self.imap_sec.findData(a['imap'].get('security', 'ssl'))))
        self.smtp_host.setText(a['smtp'].get('host', ''))
        self.smtp_port.setValue(int(a['smtp'].get('port') or 587))
        self.smtp_sec.setCurrentIndex(max(0, self.smtp_sec.findData(a['smtp'].get('security', 'starttls'))))
        self.folders.setText(', '.join(a.get('folders') or ['INBOX']))
        self.poll.setValue(int(a.get('poll_minutes') or 5))
        self.idle.setChecked(bool(a.get('idle', True)))
        self.admin.setChecked(bool(a.get('admin_detection', True)))
        self.enabled.setChecked(bool(a.get('enabled', True)))

    def fields(self) -> dict:
        return {'preset': self.preset.currentData(), 'kind': self.method.currentData(),
                'address': self.address.text().strip(), 'label': self.label.text().strip(),
                'username': self.username.text().strip(),
                'imap': {'host': self.imap_host.text().strip(), 'port': self.imap_port.value(),
                         'security': self.imap_sec.currentData()},
                'smtp': {'host': self.smtp_host.text().strip(), 'port': self.smtp_port.value(),
                         'security': self.smtp_sec.currentData()},
                'folders': [x.strip() for x in self.folders.text().split(',') if x.strip()] or ['INBOX'],
                'poll_minutes': self.poll.value(), 'idle': self.idle.isChecked(),
                'admin_detection': self.admin.isChecked(), 'enabled': self.enabled.isChecked(),
                'oauth': {'client_id': self.client_id.text().strip(), 'tenant': self.tenant.text().strip()}}

    def save(self):
        fields = self.fields()
        try:
            if self.account:
                acc = self.org.mail.update_account(self.account['id'], **{k: v for k, v in fields.items()
                                                                          if k not in ('address', 'preset', 'kind')})
                if self.password.text():
                    self.org.mail.set_secret(acc['id'], self.password.text())
            else:
                acc = self.org.mail.add_account(fields, self.password.text())
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, 'E-mail account', str(exc))
            return
        self.password.clear()
        if fields['kind'] == 'gmail' and self.client_secret.text():
            secrets.put('oauth-secret:google', self.client_secret.text())
            self.client_secret.clear()
        self.saved = acc
        if fields['kind'] in ('gmail', 'microsoft') and not secrets.get(
                f"oauth-refresh:{'google' if fields['kind'] == 'gmail' else 'microsoft'}:{acc['id']}"):
            self._oauth(acc)
            return
        self.accept()

    def _oauth(self, acc):
        from ...organizer import oauth
        provider = 'google' if acc['kind'] == 'gmail' else 'microsoft'
        self.status.setText('Your browser opens to sign in…')
        self.jobs.append(_Job(self, lambda: oauth.authorize(provider, acc, oauth.PROVIDERS[provider]['mail_scopes']),
                              lambda r, err: (self.status.setText('Sign-in failed: ' + err) if err else self.accept())))

    def test(self):
        fields = self.fields()
        password = self.password.text()
        self.status.setText('Connecting…')

        def work():
            from ...organizer.mail import GraphClient, ImapClient
            acc = dict(fields, id=(self.account or {}).get('id', 'test'))
            client = GraphClient(acc) if acc['kind'] == 'microsoft' else ImapClient(acc)
            if password and acc['kind'] == 'imap':
                client.secret = lambda: password
            return client.folders()
        self.jobs.append(_Job(self, work, lambda r, err: self.status.setText(
            ('Could not connect: ' + err) if err else f'Connected. {len(r)} folder(s): ' + ', '.join(r[:8]))))


class MailPage(QWidget):
    title = 'E-mail accounts'

    def __init__(self, organizer, conf: dict, parent=None):
        super().__init__(parent)
        self.org = organizer
        lay = QVBoxLayout(self)
        lay.addWidget(_hint('Connect any mailbox: Gmail, Outlook, iCloud, Yahoo, your university or work server '
                            '(IMAP / SMTP with an app password), or sign in with Google / Microsoft using your own '
                            f'OAuth client id (guide: <code>{DOCS}</code>). The assistant reads, searches, summarises '
                            'and drafts. <b>Sending, replying, forwarding and moving always show the full message '
                            'with Edit / Send / Discard</b> — full access does not change that.'))
        self.list = QListWidget()
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for text, ic, fn in (('Add account…', 'plus', self.add), ('Edit…', 'edit', self.edit),
                             ('Remove', 'trash', self.remove)):
            b = QPushButton(text)
            set_icon(b, ic)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.poll = QCheckBox('Check connected accounts in the background (nothing runs when none is connected)')
        self.poll.setChecked(bool(conf.get('mail_poll', True)))
        lay.addWidget(self.poll)
        lay.addWidget(_hint(_keyring_note()))
        lay.addStretch(1)
        self.fill()

    def fill(self):
        self.list.clear()
        for a in self.org.mail.accounts():
            kind = {'imap': 'IMAP/SMTP', 'gmail': 'Google sign-in', 'microsoft': 'Microsoft sign-in'}.get(a['kind'], '')
            item = QListWidgetItem(icon('mail'), f"{a['label']}  ·  {a['address']}  ·  {kind}"
                                   + ('' if a.get('enabled', True) else '  · disabled'))
            item.setData(Qt.ItemDataRole.UserRole, a['id'])
            self.list.addItem(item)
        if not self.list.count():
            self.list.addItem('No account yet.')

    def _current(self):
        item = self.list.currentItem()
        return self.org.mail.account(item.data(Qt.ItemDataRole.UserRole)) if item and \
            item.data(Qt.ItemDataRole.UserRole) else None

    def add(self):
        if AccountDialog(self.org, None, self).exec():
            self.org.changed('mail')
        self.fill()

    def edit(self):
        acc = self._current()
        if acc and AccountDialog(self.org, acc, self).exec():
            self.org.changed('mail')
        self.fill()

    def remove(self):
        acc = self._current()
        if acc and QMessageBox.question(self, 'Remove account', f"Remove {acc['address']} from this computer (the "
                                        'password / token is deleted from the keyring)?') == \
                QMessageBox.StandardButton.Yes:
            from ...organizer import oauth
            self.org.mail.remove_account(acc['id'])
            for provider in ('google', 'microsoft'):
                oauth.sign_out(provider, acc['id'])
            self.org.changed('mail')
            self.fill()

    def save(self, conf: dict):
        conf['mail_poll'] = self.poll.isChecked()


# ====================================================================== assistant behaviour
class AssistantOrganizerPage(QWidget):
    title = 'Assistant & Organizer'

    def __init__(self, organizer, conf: dict, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        box = QGroupBox('What the assistant may do with your calendar, to-do list and e-mail')
        v = QVBoxLayout(box)
        self.use = QCheckBox('Use the calendar and to-do tools (list, create, plan; changes to your own items ask '
                             'first unless full access is on)')
        self.use.setChecked(bool(conf.get('assistant_organizer', True)))
        self.mail = QCheckBox('Read, search and summarise e-mail, and draft replies')
        self.mail.setChecked(bool(conf.get('assistant_mail', True)))
        self.remind = QCheckBox('Add reminders on its own when something is important (shown as a card you can '
                                'dismiss)')
        self.remind.setChecked(bool(conf.get('assistant_reminders', True)))
        self.prep = QCheckBox('Propose preparation and follow-up to-dos for meetings, talks and deadlines')
        self.prep.setChecked(bool(conf.get('assistant_event_tasks', True)))
        self.admin = QCheckBox('Administrative e-mails become a to-do with the deadline and a form card')
        self.admin.setChecked(bool(conf.get('admin_mail_detection', True)))
        for w in (self.use, self.mail, self.remind, self.prep, self.admin):
            v.addWidget(w)
        lay.addWidget(box)
        lay.addWidget(_hint('<b>Sending rule</b> (built into the engine, not a setting): the assistant can never send '
                            'an e-mail, a message, a form or an upload on your behalf. E-mails wait in the outbox for '
                            'your Send click; any other command that would send something away asks every time, also '
                            'with full access, and cannot be “always allowed”.'))
        lay.addStretch(1)

    def save(self, conf: dict):
        conf.update(assistant_organizer=self.use.isChecked(), assistant_mail=self.mail.isChecked(),
                    assistant_reminders=self.remind.isChecked(), assistant_event_tasks=self.prep.isChecked(),
                    admin_mail_detection=self.admin.isChecked())


PAGES = [CalendarPage, TodoPage, MailPage, AssistantOrganizerPage]


def open_organizer_settings(which: str, parent=None):
    """The Agent Hub settings on the right page; without an engine, a small window with that page only."""
    title = {'calendar': 'Calendar', 'todo': 'To-do', 'mail': 'E-mail accounts'}.get(which, 'Calendar')
    hub = _find_hub(parent)
    if hub is not None:
        hub.open_settings(title)
        return
    from ... import settings as hubsettings
    from ...host import current
    from ...organizer import shared
    root = current().data_dir()
    conf = hubsettings.load(root)
    page_cls = {'Calendar': CalendarPage, 'To-do': TodoPage, 'E-mail accounts': MailPage}[title]
    dialog = QDialog(parent)
    dialog.setWindowTitle(title + ' settings')
    dialog.resize(720, 640)
    lay = QVBoxLayout(dialog)
    from PySide6.QtWidgets import QScrollArea
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    page = page_cls(shared(), conf)
    scroll.setWidget(page)
    lay.addWidget(scroll)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    lay.addWidget(buttons)
    if dialog.exec():
        page.save(conf)
        hubsettings.save(root, conf)


def _find_hub(parent):
    """The open HubWidget (embedded or standalone), if any."""
    from PySide6.QtWidgets import QApplication
    from ..window import HubWidget
    for w in QApplication.topLevelWidgets():
        try:
            found = w if isinstance(w, HubWidget) else w.findChild(HubWidget)
        except RuntimeError:
            continue
        if found is not None:
            return found
    return None
