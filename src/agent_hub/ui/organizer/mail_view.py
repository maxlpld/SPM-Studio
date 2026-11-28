"""E-mail window: accounts and folders, the message list, a reading pane with *Reply* / *Forward* / *Move*
(each prepares a message in the outbox), *New message*, and the **outbox**: every waiting message as a full
card with Edit / Send / Discard. Nothing is sent from anywhere else."""
from __future__ import annotations

from ..theme import scale_font

import html

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import theme
from ..svg_icons import icon, set_icon
from ..widgets import icon_button
from .cards import AdminFormCard, MailCard, MailEditDialog, _Job
from .common import bridge, t

ROLE = Qt.ItemDataRole.UserRole


class MailWindow(QMainWindow):
    def __init__(self, organizer=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        from ...organizer import shared
        self.org = organizer or shared()
        self.bridge = bridge(self.org)
        self.setObjectName('AgentHubMail')
        self.setWindowTitle('E-mail')
        self.resize(1180, 780)
        self.jobs = []
        self.message = None
        root = QWidget()
        root.setObjectName('mailRoot')
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._toolbar())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._inbox(), icon('inbox', t('muted')), 'Inbox')
        self.tabs.addTab(self._outbox(), icon('outbox', t('muted')), 'Outbox')
        outer.addWidget(self.tabs, 1)
        self.bridge.mailChanged.connect(self.fill_outbox)
        self.apply_theme()
        self.fill_accounts()
        self.fill_outbox()
        QShortcut(QKeySequence('Ctrl+W'), self, self.close)
        QShortcut(QKeySequence('Ctrl+R'), self, self.reply)
        QShortcut(QKeySequence('Ctrl+N'), self, self.compose)
        QShortcut(QKeySequence('F5'), self, self.load)

    def _toolbar(self):
        bar = QWidget()
        bar.setObjectName('mailToolbar')
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        logo = QLabel()
        logo.setPixmap(icon('mail', t('accent')).pixmap(QSize(24, 24)))
        row.addWidget(logo)
        title = QLabel('E-mail')
        f = title.font()
        scale_font(f, 1.3)
        title.setFont(f)
        row.addWidget(title)
        row.addSpacing(16)
        self.account = QComboBox()
        self.account.setMinimumWidth(220)
        self.account.activated.connect(lambda _i: self.load())
        row.addWidget(self.account)
        self.folder = QComboBox()
        self.folder.setEditable(True)
        self.folder.addItem('INBOX')
        self.folder.activated.connect(lambda _i: self.load())
        row.addWidget(self.folder)
        refresh = icon_button('refresh', 'Check for new mail (F5)')
        refresh.clicked.connect(self.load)
        row.addWidget(refresh)
        row.addStretch(1)
        new = QPushButton('New message')
        new.setObjectName('hubSend')
        set_icon(new, 'mail-send', 'accent_fg')
        new.setToolTip('New message (Ctrl+N) — it goes to the outbox first')
        new.clicked.connect(self.compose)
        row.addWidget(new)
        settings = icon_button('gear', 'E-mail accounts (Agent Hub settings)')
        settings.clicked.connect(self.open_settings)
        row.addWidget(settings)
        return bar

    def _inbox(self):
        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setObjectName('mailList')
        self.list.currentItemChanged.connect(self._selected)
        split.addWidget(self.list)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 8)
        self.head = QLabel('')
        self.head.setWordWrap(True)
        self.head.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self.head)
        row = QHBoxLayout()
        self.reply_b = QPushButton('Reply')
        set_icon(self.reply_b, 'undo')
        self.forward_b = QPushButton('Forward')
        set_icon(self.forward_b, 'send')
        self.move_b = QPushButton('Move…')
        set_icon(self.move_b, 'folder')
        self.admin_b = QPushButton('Fill in (form / report)…')
        set_icon(self.admin_b, 'form')
        for b, fn in ((self.reply_b, self.reply), (self.forward_b, self.forward), (self.move_b, self.move),
                      (self.admin_b, self.admin)):
            b.clicked.connect(fn)
            b.setEnabled(False)
            row.addWidget(b)
        row.addStretch(1)
        rl.addLayout(row)
        self.body = QTextBrowser()
        self.body.setObjectName('mailBody')
        rl.addWidget(self.body, 1)
        self.cards_box = QVBoxLayout()
        rl.addLayout(self.cards_box)
        split.addWidget(right)
        split.setSizes([420, 720])
        self.status = QLabel('')
        self.status.setObjectName('hubHint')
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(split, 1)
        wl.addWidget(self.status)
        return wrap

    def _outbox(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        box = QWidget()
        self.outbox_lay = QVBoxLayout(box)
        self.outbox_lay.setContentsMargins(16, 12, 16, 12)
        self.outbox_lay.setSpacing(10)
        scroll.setWidget(box)
        return scroll

    def apply_theme(self):
        self.setStyleSheet(theme.stylesheet() + f"""
#mailRoot, #mailToolbar {{ background: {t('window')}; color: {t('text')}; }}
#mailToolbar {{ border-bottom: 1px solid {t('border')}; }}
#mailList {{ background: {t('surface')}; border: 1px solid {t('border')}; border-radius: 8px; }}
#mailList::item {{ padding: 6px; border-bottom: 1px solid {t('border')}; }}
#mailList::item:selected {{ background: {t('selection')}; color: {t('text')}; }}
#mailBody {{ background: {t('surface')}; border: 1px solid {t('border')}; border-radius: 8px; }}
""")

    def fill_accounts(self):
        self.account.clear()
        accounts = self.org.mail.accounts()
        for a in accounts:
            self.account.addItem(icon('mail', t('muted')), f"{a['label']}", a['id'])
        if not accounts:
            self.account.addItem('No account connected — Settings', '')
            self.status.setText('Connect an account in Agent Hub › Settings › E-mail accounts. Nothing is checked '
                                'in the background while no account is connected.')
        else:
            self.list.clear()
            for m in self.org.mail.cached(self.account.currentData() or '', limit=100):
                self._add(m)

    def _add(self, m: dict):
        unread = 'Seen' not in (m.get('flags') or [])
        text = f"{m.get('from', '')}\n{m.get('subject', '')}\n{(m.get('date') or '')[:16].replace('T', ' ')}"
        item = QListWidgetItem(text)
        item.setData(ROLE, m)
        if unread:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        if m.get('attachments'):
            item.setIcon(icon('attach', t('muted')))
        self.list.addItem(item)

    def load(self):
        aid = self.account.currentData()
        if not aid:
            return
        folder = self.folder.currentText() or 'INBOX'
        self.status.setText('Loading…')

        def work():
            msgs = self.org.mail.client(aid).recent(folder, days=30, limit=80)
            self.org.mail.remember(msgs)
            return msgs
        job = _Job(work, self)
        job.done.connect(self._loaded)
        self.jobs.append(job)
        job.start()

    def _loaded(self, msgs, error):
        if error:
            self.status.setText('Could not load: ' + error)
            return
        self.list.clear()
        for m in msgs or []:
            self._add(m)
        self.status.setText(f'{len(msgs or [])} message(s) in the last 30 days.')

    def _selected(self, item, _prev):
        m = item.data(ROLE) if item else None
        for b in (self.reply_b, self.forward_b, self.move_b, self.admin_b):
            b.setEnabled(m is not None)
        if m is None:
            return
        self.head.setText(f"<b>{html.escape(m.get('subject', ''))}</b><br>{html.escape(m.get('from', ''))} · "
                          f"{html.escape((m.get('date') or '')[:16].replace('T', ' '))}")
        self.body.setPlainText(m.get('snippet', '') + '\n\n(loading…)')
        aid, uid, folder = m['account'], m['uid'], m.get('folder', 'INBOX')
        job = _Job(lambda: self.org.mail.client(aid).message(uid, folder), self)
        job.done.connect(lambda full, err: self._show(full, err))
        self.jobs.append(job)
        job.start()

    def _show(self, full, error):
        if error:
            self.body.setPlainText('Could not open the message: ' + error)
            return
        self.message = full
        att = ''.join(f"<br>Attachment: {html.escape(a['name'])} ({max(1, a['size'] // 1024)} kB)"
                      for a in full.get('attachments', []))
        self.head.setText(self.head.text() + att)
        self.body.setPlainText(full.get('body', ''))

    # ---- outgoing (outbox only)
    def _card(self, item_id):
        card = MailCard(self.org, item_id, self)
        card.closed.connect(lambda *_a: self.fill_outbox())
        card.sent.connect(lambda *_a: self.fill_outbox())
        return card

    def _propose(self, action, draft):
        aid = self.account.currentData()
        try:
            item = self.org.mail.outbox.propose(action, aid, draft, origin='user')
        except ValueError as exc:
            QMessageBox.warning(self, 'E-mail', str(exc))
            return
        dialog = MailEditDialog(item, self)
        dialog.setWindowTitle('Write the message (it goes to the outbox)')
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.org.mail.outbox.edit(item['id'], **dialog.fields())
            except ValueError as exc:
                QMessageBox.warning(self, 'E-mail', str(exc))
        self.org.changed('mail')
        self.tabs.setCurrentIndex(1)

    def compose(self):
        if not self.account.currentData():
            QMessageBox.information(self, 'E-mail', 'Connect an account first (Settings › E-mail accounts).')
            return
        try:
            to, ok = QInputDialog.getText(self, 'New message', 'To:')
        except RuntimeError:
            return
        if ok and to.strip():
            self._propose('send', {'to': to, 'subject': '', 'body': ''})

    def reply(self):
        if not self.message:
            return
        from ...organizer.mail import reply_draft
        acc = self.org.mail.account(self.message['account']) or {}
        self._propose('reply', reply_draft(self.message, '', acc))

    def forward(self):
        if not self.message:
            return
        to, ok = QInputDialog.getText(self, 'Forward', 'To:')
        if ok and to.strip():
            from ...organizer.mail import forward_draft
            self._propose('forward', forward_draft(self.message, to))

    def move(self):
        if not self.message:
            return
        target, ok = QInputDialog.getText(self, 'Move', 'Move to folder:')
        if ok and target.strip():
            self._propose('move', {'uid': self.message['uid'], 'folder': target.strip(),
                                   'source_folder': self.message.get('folder', 'INBOX'),
                                   'subject': self.message.get('subject', '')})

    def admin(self):
        if not self.message:
            return
        from ...organizer import admin
        import datetime as dt
        found = admin.detect(self.message) or {'kind': 'reply', 'deadline': '', 'quantities': [],
                                                 'period': admin.find_period(self.message.get('body', ''),
                                                                             dt.date.today()), 'pdf_attachments': []}
        task, _created = admin.start(self.org, self.message, found)
        card = AdminFormCard(self.org, {'kind': 'admin_form', 'account': self.message['account'],
                                        'uid': self.message['uid'], 'folder': self.message.get('folder', 'INBOX'),
                                        'task': task['id'], 'found': {k: v for k, v in found.items()
                                                                      if k != 'pdf_attachments'},
                                        'pdfs': [a['index'] for a in found.get('pdf_attachments') or []]}, self)
        card.closed.connect(card.deleteLater)
        card.outboxed.connect(lambda _i: (self.fill_outbox(), self.tabs.setCurrentIndex(1)))
        self.cards_box.addWidget(card)

    def fill_outbox(self):
        while self.outbox_lay.count():
            w = self.outbox_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        items = self.org.mail.outbox.items('pending')
        head = QLabel(f'<b>{len(items)} message(s) waiting for you</b> — each one leaves only when you press Send.'
                      if items else 'The outbox is empty.')
        self.outbox_lay.addWidget(head)
        for item in items:
            self.outbox_lay.addWidget(self._card(item['id']))
        self.outbox_lay.addStretch(1)
        self.tabs.setTabText(1, f'Outbox ({len(items)})' if items else 'Outbox')

    def show_outbox(self, item_id: str = ''):
        self.fill_outbox()
        self.tabs.setCurrentIndex(1)

    def open_settings(self):
        from .settings_pages import open_organizer_settings
        open_organizer_settings('mail', self)
        self.fill_accounts()
