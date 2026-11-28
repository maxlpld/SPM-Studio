"""Cards of the calendar / to-do / e-mail tools, shown above the message box of a chat (or in the mail view).

* :class:`MailCard` — the **only** way a message leaves: it shows the complete message (account, recipients,
  subject, body, attachments with a preview) and the buttons *Edit*, *Send*, *Discard*. *Send* approves exactly
  the digest of what is displayed (``mail.Outbox.approve``) and then delivers it in a worker thread.
* :class:`ResultCard` — something the assistant created (event, to-do, reminder, planned blocks): *Open*,
  *Undo* / *Dismiss*.
* :class:`ToolApprovalCard` — a change to an event or to-do the user made: *Allow* / *Deny*.
* :class:`AdminFormCard` — an administrative e-mail: only the missing values are asked; *Fill and review*
  shows the filled PDF and the drafted reply side by side; the reply goes to the outbox (a MailCard).
"""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QSizePolicy, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from .. import theme
from ..svg_icons import icon, set_icon


class _Job(QThread):
    done = Signal(object, str)                  # result, error

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(), '')
        except Exception as exc:
            from ...organizer.secrets import redact
            self.done.emit(None, redact(str(exc))[:400])


def _frame(kind: str) -> QFrame:
    f = QFrame()
    f.setObjectName('hubCard')
    f.setProperty('kind', kind)
    return f


def _head(lay, icon_name: str, title: str, token: str = 'accent'):
    row = QHBoxLayout()
    row.setSpacing(8)
    ic = QLabel()
    ic.setPixmap(icon(icon_name, theme.tokens().get(token)).pixmap(QSize(18, 18)))
    row.addWidget(ic)
    lab = QLabel(f'<b>{html.escape(title)}</b>')
    lab.setWordWrap(True)
    row.addWidget(lab, 1)
    lay.addLayout(row)
    return row


def _button(text: str, icon_name: str = '', primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setObjectName('hubSend')
    if icon_name:
        set_icon(b, icon_name, 'accent_fg' if primary else None)
    return b


# ====================================================================== mail
class MailEditDialog(QDialog):
    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Edit the message')
        self.resize(640, 560)
        d = item['draft']
        form = QFormLayout(self)
        self.to = QLineEdit(', '.join(d.get('to', [])))
        self.cc = QLineEdit(', '.join(d.get('cc', [])))
        self.bcc = QLineEdit(', '.join(d.get('bcc', [])))
        self.subject = QLineEdit(d.get('subject', ''))
        self.body = QPlainTextEdit(d.get('body', ''))
        self.attachments = QListWidget()
        for p in d.get('attachments', []):
            self.attachments.addItem(p)
        row = QHBoxLayout()
        add = QPushButton('Add file…')
        rem = QPushButton('Remove')
        add.clicked.connect(self._add)
        rem.clicked.connect(lambda: [self.attachments.takeItem(self.attachments.row(i))
                                     for i in self.attachments.selectedItems()])
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        if item['action'] != 'move':
            form.addRow('To', self.to)
            form.addRow('Cc', self.cc)
            form.addRow('Bcc', self.bcc)
            form.addRow('Subject', self.subject)
            form.addRow(self.body)
            form.addRow('Attachments', self.attachments)
            form.addRow('', row)
        else:
            self.folder = QLineEdit(d.get('folder', ''))
            form.addRow('Move to folder', self.folder)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.item = item

    def _add(self):
        from PySide6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(self, 'Attach files')
        for p in paths:
            self.attachments.addItem(p)

    def fields(self) -> dict:
        if self.item['action'] == 'move':
            return {'folder': self.folder.text().strip()}
        return {'to': self.to.text(), 'cc': self.cc.text(), 'bcc': self.bcc.text(), 'subject': self.subject.text(),
                'body': self.body.toPlainText(),
                'attachments': [self.attachments.item(i).text() for i in range(self.attachments.count())]}


class MailCard(QFrame):
    """The complete message and Edit / Send / Discard. Nothing leaves without the Send click."""
    closed = Signal(str)                        # item id
    sent = Signal(str)

    def __init__(self, organizer, item_id: str, parent=None):
        super().__init__(parent)
        self.setObjectName('hubCard')
        self.setProperty('kind', 'mail')
        self.org = organizer
        self.item_id = item_id
        self.shown_digest = ''
        self.job = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        self.head = QLabel()
        self.head.setWordWrap(True)
        self.head.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.head)
        self.meta = QLabel()
        self.meta.setWordWrap(True)
        self.meta.setTextFormat(Qt.TextFormat.RichText)
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.meta)
        self.body = QTextBrowser()
        self.body.setObjectName('hubMailBody')
        self.body.setMinimumHeight(110)
        self.body.setMaximumHeight(260)
        lay.addWidget(self.body)
        self.files = QHBoxLayout()
        self.files.setSpacing(6)
        lay.addLayout(self.files)
        row = QHBoxLayout()
        self.edit_b = _button('&Edit', 'edit')
        self.send_b = _button('&Send', 'send', primary=True)
        self.discard_b = _button('&Discard', 'trash')
        self.status = QLabel('')
        self.status.setObjectName('hubHint')
        self.status.setWordWrap(True)
        for b in (self.send_b, self.edit_b, self.discard_b):
            row.addWidget(b)
        row.addWidget(self.status, 1)
        lay.addLayout(row)
        note = QLabel('Nothing is sent until you press Send. Full access does not change this.')
        note.setObjectName('hubHint')
        lay.addWidget(note)
        self.edit_b.clicked.connect(self.edit)
        self.send_b.clicked.connect(self.send)
        self.discard_b.clicked.connect(self.discard)
        self.refresh()

    def item(self) -> dict | None:
        return self.org.mail.outbox.get(self.item_id)

    def refresh(self):
        item = self.item()
        if item is None:
            self.head.setText('<b>This message is no longer in the outbox.</b>')
            for b in (self.edit_b, self.send_b, self.discard_b):
                b.setEnabled(False)
            return
        t = theme.tokens()
        d = item['draft']
        acc = self.org.mail.account(item['account']) or {}
        verb = {'send': 'Send this e-mail?', 'reply': 'Send this reply?', 'forward': 'Forward this e-mail?',
                'move': 'Move this e-mail?'}[item['action']]
        origin = 'proposed by the assistant' if item.get('origin') == 'assistant' else 'prepared for you'
        self.head.setText(f"<b>{verb}</b> <span style='color:{t['muted']}'>· {origin}</span>")
        e = html.escape
        if item['action'] == 'move':
            self.meta.setText(f"Account: {e(acc.get('label', ''))}<br>Message: {e(d.get('subject', '') or d.get('uid', ''))}"
                              f"<br>From folder <b>{e(d.get('source_folder', 'INBOX'))}</b> to <b>{e(d.get('folder', ''))}</b>")
            self.body.hide()
        else:
            rows = [f"<b>From</b> {e(acc.get('address', ''))}", f"<b>To</b> {e(', '.join(d.get('to', [])))}"]
            if d.get('cc'):
                rows.append(f"<b>Cc</b> {e(', '.join(d['cc']))}")
            if d.get('bcc'):
                rows.append(f"<b>Bcc</b> {e(', '.join(d['bcc']))}")
            rows.append(f"<b>Subject</b> {e(d.get('subject', ''))}")
            self.meta.setText('<br>'.join(rows))
            self.body.setPlainText(d.get('body', ''))
            self.body.show()
        while self.files.count():
            w = self.files.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for path in d.get('attachments', []):
            self.files.addWidget(self._attachment(Path(path)))
        if d.get('attachments'):
            self.files.addStretch(1)
        self.shown_digest = item['digest']                     # what is on screen is what Send approves
        pending = item['status'] == 'pending'
        for b in (self.edit_b, self.send_b, self.discard_b):
            b.setEnabled(pending)
        if item['status'] == 'done':
            self.status.setText('Sent.' if item['action'] != 'move' else 'Moved.')
        elif item['status'] == 'discarded':
            self.status.setText('Discarded.')

    def _attachment(self, path: Path) -> QWidget:
        box = QPushButton()
        box.setObjectName('hubAttachment')
        size = path.stat().st_size if path.exists() else 0
        box.setText(f'{path.name}  ({max(1, size // 1024)} kB)')
        set_icon(box, 'file-pdf' if path.suffix.lower() == '.pdf' else 'attach')
        box.setToolTip('Open to check it before sending: ' + str(path))
        if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp') and path.exists():
            from PySide6.QtGui import QIcon, QPixmap
            pix = QPixmap(str(path))
            if not pix.isNull():
                box.setIcon(QIcon(pix.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)))
                box.setIconSize(QSize(40, 40))
        box.clicked.connect(lambda: self._open(path))
        return box

    @staticmethod
    def _open(path: Path):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def edit(self):
        item = self.item()
        if item is None:
            return
        dialog = MailEditDialog(item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.org.mail.outbox.edit(self.item_id, **dialog.fields())
            except ValueError as exc:
                QMessageBox.warning(self, 'Edit', str(exc))
            self.refresh()

    def send(self):
        """The user's click: approve exactly the displayed digest, then deliver off the GUI thread."""
        from ...organizer.mail import ApprovalError
        try:
            ticket = self.org.mail.outbox.approve(self.item_id, self.shown_digest)
        except ApprovalError as exc:
            self.status.setText(str(exc))
            self.refresh()
            return
        for b in (self.edit_b, self.send_b, self.discard_b):
            b.setEnabled(False)
        self.status.setText('Sending…')
        self.job = _Job(lambda t=ticket: self.org.mail.outbox.execute(t), self)
        self.job.done.connect(self._sent)
        self.job.start()

    def _sent(self, result, error):
        if error:
            self.status.setText('Not sent: ' + error)
        else:
            self.sent.emit(self.item_id)
            self.org.changed('mail')
        self.refresh()

    def discard(self):
        try:
            self.org.mail.outbox.discard(self.item_id)
        except (KeyError, ValueError):
            pass
        self.org.changed('mail')
        self.refresh()
        self.closed.emit(self.item_id)


# ====================================================================== results
class ResultCard(QFrame):
    closed = Signal()
    openRequested = Signal(str, str)           # 'calendar' | 'todo', id

    def __init__(self, organizer, card: dict, parent=None):
        super().__init__(parent)
        self.setObjectName('hubCard')
        self.setProperty('kind', 'result')
        self.org, self.card = organizer, card
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)
        kind = card.get('kind')
        title, icon_name, detail = self._text(kind)
        _head(lay, icon_name, title)
        if detail:
            d = QLabel(html.escape(detail).replace('\n', '<br>'))
            d.setWordWrap(True)
            d.setObjectName('hubHint')
            lay.addWidget(d)
        row = QHBoxLayout()
        target = 'todo' if kind in ('created_task', 'created_tasks') else 'calendar'
        open_b = _button('&Open', 'calendar' if target == 'calendar' else 'todo')
        open_b.clicked.connect(lambda: self.openRequested.emit(target, card.get('uid') or card.get('id') or ''))
        undo = _button('&Undo' if kind != 'reminder' else '&Dismiss reminder', 'undo')
        undo.clicked.connect(self.undo)
        keep = _button('&Keep', 'check', primary=True)
        keep.clicked.connect(self.closed.emit)
        row.addWidget(keep)
        row.addWidget(open_b)
        row.addWidget(undo)
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel('')
        self.status.setObjectName('hubHint')
        lay.addWidget(self.status)

    def _text(self, kind):
        c = self.card
        if kind == 'created_event':
            when = c.get('start', '').replace('T', ' ')[:16]
            return f"Added to your calendar: {c.get('title', '')}", 'calendar', when
        if kind == 'planned':
            return f"Planned {c.get('minutes', 0)} min for “{c.get('title', '')}”", 'calendar-week', c.get('text', '')
        if kind == 'reminder':
            why = c.get('reason') or ''
            what = (f"{c.get('minutes')} min before “{c.get('title')}”" if c.get('added_to_existing') else
                    f"“{c.get('title')}” at {str(c.get('at', '')).replace('T', ' ')[:16]}")
            return 'The assistant added a reminder', 'bell', what + (f'\nWhy: {why}' if why else '')
        if kind == 'created_task':
            return f"Added to your to-do list: {c.get('title', '')}", 'todo', \
                ('due ' + c['due'].replace('T', ' ')) if c.get('due') else ''
        if kind == 'created_tasks':
            return 'Preparation / follow-up to-dos added', 'checklist', c.get('text', '')
        return c.get('text', 'Done'), 'check', ''

    def undo(self):
        c, org = self.card, self.org
        try:
            kind = c.get('kind')
            if kind == 'created_event':
                org.delete_event(c['uid'])
            elif kind == 'planned':
                for uid in c.get('uids', []):
                    org.delete_event(uid)
            elif kind == 'reminder':
                if c.get('added_to_existing'):
                    ev = org.calendar.get(c['uid'])
                    if ev is not None:
                        org.calendar.update(c['uid'], _sync=True,
                                            reminders=[m for m in ev.get('reminders', []) if m != c.get('minutes')])
                else:
                    org.delete_event(c['uid'])
            elif kind == 'created_task':
                org.delete_task(c['id'])
            elif kind == 'created_tasks':
                for tid in c.get('ids', []):
                    org.delete_task(tid)
            org.changed('calendar')
            org.changed('todo')
        except Exception as exc:
            self.status.setText('Could not undo: ' + str(exc))
            return
        self.closed.emit()


class ToolApprovalCard(QFrame):
    answered = Signal(bool)

    def __init__(self, request: dict, parent=None):
        super().__init__(parent)
        self.setObjectName('hubCard')
        self.setProperty('kind', 'approval')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        _head(lay, 'warning', 'The assistant asks: ' + request['title'], 'warning')
        d = QLabel(html.escape(request.get('detail', '')).replace('\n', '<br>'))
        d.setWordWrap(True)
        lay.addWidget(d)
        row = QHBoxLayout()
        allow = _button('&Allow', 'check', primary=True)
        deny = _button('&Deny', 'close')
        allow.clicked.connect(lambda: self.answered.emit(True))
        deny.clicked.connect(lambda: self.answered.emit(False))
        row.addWidget(allow)
        row.addWidget(deny)
        row.addStretch(1)
        lay.addLayout(row)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Y, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.answered.emit(True)
        elif event.key() in (Qt.Key.Key_N, Qt.Key.Key_Escape):
            self.answered.emit(False)
        else:
            super().keyPressEvent(event)


# ====================================================================== administrative e-mail
class AdminFormCard(QFrame):
    """Ask only for what is missing; then fill the PDF / draft the reply and show both side by side."""
    closed = Signal()
    outboxed = Signal(str)                      # outbox item id

    def __init__(self, organizer, card: dict, parent=None):
        super().__init__(parent)
        self.setObjectName('hubCard')
        self.setProperty('kind', 'form')
        self.org, self.card = organizer, card
        self.message = None
        self.raw = b''
        self.pdf_fields = []
        self.job = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        _head(lay, 'form', 'An e-mail asks you to fill something in')
        found = card.get('found') or {}
        self.info = QLabel('Reading the e-mail…')
        self.info.setWordWrap(True)
        self.info.setObjectName('hubHint')
        lay.addWidget(self.info)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(8)
        lay.addLayout(self.grid)
        row = QHBoxLayout()
        self.fill_b = _button('&Fill and review', 'form', primary=True)
        self.fill_b.setEnabled(False)
        later = _button('&Later', 'clock')
        row.addWidget(self.fill_b)
        row.addWidget(later)
        row.addStretch(1)
        lay.addLayout(row)
        self.fill_b.clicked.connect(self.fill)
        later.clicked.connect(self.closed.emit)
        self.edits: dict[str, QLineEdit] = {}
        self.found = found
        self._load()

    def _load(self):
        from ...organizer import admin
        c = self.card

        def work():
            client = self.org.mail.client(c['account'])
            raw = client.raw(c['uid'], c.get('folder', 'INBOX')) if hasattr(client, 'raw') else b''
            msg = client.message(c['uid'], c.get('folder', 'INBOX'))
            fields = []
            pdf = None
            if raw and c.get('pdfs'):
                from ...organizer.mail import attachment_bytes
                name, data = attachment_bytes(raw, int(c['pdfs'][0]))
                folder = self.org.root / 'admin' / (c['uid'] or 'mail')
                folder.mkdir(parents=True, exist_ok=True)
                pdf = folder / Path(name).name
                pdf.write_bytes(data)
                fields = admin.pdf_fields(pdf)
            return msg, raw, pdf, fields
        self.job = _Job(work, self)
        self.job.done.connect(self._loaded)
        self.job.start()

    def _loaded(self, result, error):
        from ...organizer import admin
        if error:
            self.info.setText('Could not read the e-mail: ' + error)
            return
        self.message, self.raw, self.pdf, self.pdf_fields = result
        values = admin.gather(self.org, self.found, self.pdf_fields)
        deadline = self.found.get('deadline') or 'no deadline found'
        self.info.setText(f"“{self.message.get('subject', '')}” from {self.message.get('from', '')} · deadline: "
                          f"{deadline}. A to-do was added. Only the empty fields need you.")
        t = theme.tokens()
        for n, v in enumerate(values):
            lab = QLabel(html.escape(v['label']))
            edit = QLineEdit(v['value'])
            edit.setPlaceholderText('needed' if v['missing'] else '')
            if v['missing']:
                edit.setStyleSheet(f"border: 1px solid {t['warning']}; border-radius: 4px;")
            src = QLabel(html.escape(v.get('source') or ''))
            src.setObjectName('hubHint')
            src.setWordWrap(True)
            self.grid.addWidget(lab, n, 0)
            self.grid.addWidget(edit, n, 1)
            self.grid.addWidget(src, n, 2)
            self.edits[v['key']] = edit
            edit.setProperty('label', v['label'])
            edit.setProperty('pdf_field', bool(v.get('pdf_field')))
        if not values:
            self.info.setText(self.info.text() + ' Nothing to count automatically: write the answer in the next step.')
        self.fill_b.setEnabled(True)

    def values(self) -> list[dict]:
        return [{'key': k, 'label': e.property('label'), 'value': e.text().strip(), 'pdf_field': e.property('pdf_field')}
                for k, e in self.edits.items()]

    def fill(self):
        from ...organizer import admin
        values = self.values()
        admin.remember_answers(self.org.root, {v['key']: v['value'] for v in values})
        filled = None
        if self.pdf is not None:
            target = self.pdf.with_name(self.pdf.stem + ' (filled).pdf')
            try:
                admin.fill_pdf(self.pdf, target, {v['key']: v['value'] for v in values if v['pdf_field']} or
                               {v['label']: v['value'] for v in values}, overlay_writer=overlay_pdf)
                filled = target
            except Exception as exc:
                QMessageBox.warning(self, 'Fill the form', f'The PDF could not be filled: {exc}')
        reply = admin.reply_text(self.message, values, attached=filled is not None)
        dialog = AdminReviewDialog(self.org, self.card, self.message, filled, reply, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.item_id:
            self.outboxed.emit(dialog.item_id)
            self.closed.emit()


def overlay_pdf(values: dict) -> bytes:
    """A page listing the values, for a PDF without form fields (drawn with Qt)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QRectF
    from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QPdfWriter
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buf)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                     QMarginsF(20, 20, 20, 20), QPageLayout.Unit.Millimeter))
    p = QPainter(writer)
    font = QFont()
    font.setPointSize(12)
    p.setFont(font)
    y = 0
    p.drawText(QRectF(0, y, writer.width(), 400), 'Values entered for this form')
    y += 700
    for k, v in values.items():
        p.drawText(QRectF(0, y, writer.width(), 400), f'{k}: {v}')
        y += 450
    p.end()
    buf.close()
    return bytes(data)


class AdminReviewDialog(QDialog):
    """Filled PDF (left) and the drafted reply (right). *Put in the outbox* creates the proposal; the mail card
    then asks for the Send click."""

    def __init__(self, organizer, card, message, filled: Path | None, reply: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Review before sending')
        self.resize(1100, 720)
        self.org, self.card, self.message, self.filled = organizer, card, message, filled
        self.item_id = ''
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel('<b>Filled document</b>' + (f' — {html.escape(filled.name)}' if filled else
                                                          ' — no PDF in this e-mail')))
        viewer = self._viewer(filled)
        ll.addWidget(viewer, 1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel(f"<b>Reply</b> to {html.escape(message.get('from', ''))}"))
        self.reply = QPlainTextEdit(reply)
        rl.addWidget(self.reply, 1)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([560, 540])
        lay.addWidget(split, 1)
        hint = QLabel('Nothing is sent from here: the reply goes to the outbox, where you check it once more and '
                      'press Send.')
        hint.setObjectName('hubHint')
        lay.addWidget(hint)
        buttons = QDialogButtonBox()
        ok = buttons.addButton('Put the reply in the &outbox', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        ok.clicked.connect(self._outbox)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    @staticmethod
    def _viewer(path: Path | None) -> QWidget:
        if path is not None:
            try:
                from PySide6.QtPdf import QPdfDocument
                from PySide6.QtPdfWidgets import QPdfView
                doc = QPdfDocument()
                doc.load(str(path))
                view = QPdfView()
                view.setDocument(doc)
                view.setPageMode(QPdfView.PageMode.MultiPage)
                view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
                view._doc = doc
                return view
            except Exception:
                pass
        label = QLabel('Open the file to check it.' if path else 'This e-mail had no PDF to fill.')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _outbox(self):
        from ...organizer.mail import reply_draft
        acc = self.org.mail.account(self.card['account']) or {}
        draft = reply_draft(self.message, self.reply.toPlainText(), acc)
        if self.filled is not None:
            draft['attachments'] = [str(self.filled)]
        try:
            item = self.org.mail.outbox.propose('reply', self.card['account'], draft, origin='user',
                                                note='administrative e-mail')
        except ValueError as exc:
            QMessageBox.warning(self, 'Outbox', str(exc))
            return
        self.item_id = item['id']
        self.org.changed('mail')
        self.accept()


def make_card(organizer, card: dict, parent=None) -> QFrame:
    kind = card.get('kind')
    if kind == 'mail':
        return MailCard(organizer, card['id'], parent)
    if kind == 'admin_form':
        return AdminFormCard(organizer, card, parent)
    return ResultCard(organizer, card, parent)
