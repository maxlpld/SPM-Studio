"""Background services of the organizer while the app runs (Qt):

* reminders: desktop notifications at the right time (checked every 30 s, nothing fires twice), and on start
  a “missed / upcoming” summary;
* calendar subscriptions and two-way syncs, at their intervals;
* e-mail: checked only when an account is connected (IMAP IDLE when the server supports it, otherwise every
  ``poll_minutes``), and administrative e-mails become a to-do + a form card. With no account connected nothing
  runs at all.
"""
from __future__ import annotations

import datetime as dt
import time

from PySide6.QtCore import QObject, QThread, QTimer, Signal


class _Worker(QThread):
    result = Signal(str, object, str)

    def __init__(self, kind, fn, parent=None):
        super().__init__(parent)
        self.kind, self.fn = kind, fn

    def run(self):
        try:
            self.result.emit(self.kind, self.fn(), '')
        except Exception as exc:
            from ...organizer.secrets import redact
            self.result.emit(self.kind, None, redact(str(exc))[:300])


class Notifier(QObject):
    summaryReady = Signal(dict)            # start summary (missed, upcoming, overdue)
    reminder = Signal(dict)                # one reminder fired
    adminFound = Signal(dict)              # an administrative e-mail: card data for AdminFormCard

    def __init__(self, organizer, conf_fn, notify=None, parent=None):
        super().__init__(parent)
        from ...organizer import reminders
        self.org = organizer
        self.conf = conf_fn
        self.notify = notify
        self.log = reminders.ReminderLog(organizer.root)
        self.workers = []
        self._mail_next = 0.0
        self._sync_next = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self.tick)
        self._tray = None

    def start(self):
        from ...organizer import reminders
        if self.conf().get('calendar_start_summary', True):
            summary = reminders.start_summary(self.org, self.log)
            if summary['missed'] or summary['upcoming'] or summary['overdue']:
                self.summaryReady.emit(summary)
            if summary['missed']:
                self.log.mark(summary['missed'])
        self.log.set_last_run(dt.datetime.now())
        self.timer.start()
        QTimer.singleShot(4000, self.tick)

    def stop(self):
        self.timer.stop()
        for w in list(self.workers):
            w.wait(3000)

    # ---- every 30 s
    def tick(self):
        from ...organizer import reminders
        conf = self.conf()
        now = dt.datetime.now()
        if conf.get('calendar_notifications', True):
            fire = reminders.pending(self.org, self.log, now)
            for r in fire:
                self._show(r)
                self.reminder.emit(r)
            if fire:
                self.log.mark(fire, now)
        self.log.set_last_run(now)
        if time.time() >= self._sync_next:
            self._sync_next = time.time() + 300
            self._sync()
        accounts = self.org.mail.connected() if conf.get('mail_poll', True) else []
        if accounts and time.time() >= self._mail_next:
            self._mail_next = time.time() + 60 * min(int(a.get('poll_minutes') or 5) for a in accounts)
            self._check_mail(accounts, conf)

    def _show(self, r: dict):
        if r['kind'] == 'task':
            title, text = 'To-do due', r['title']
        else:
            when = 'now' if r['minutes'] == 0 else (f"in {r['minutes']} min" if r['minutes'] < 60 else
                                                    f"in {r['minutes'] // 60} h" if r['minutes'] < 1440 else
                                                    f"in {r['minutes'] // 1440} day(s)")
            text = f"{r['title']} — {'all day' if r['all_day'] else r['start'].strftime('%H:%M')} ({when})" + \
                (f" · {r['location']}" if r.get('location') else '')
            title = 'Calendar'
        shown = False
        if self.notify is not None:
            try:
                shown = bool(self.notify(title, text))
            except Exception:
                shown = False
        if not shown:
            self._tray_message(title, text)

    def _tray_message(self, title, text):
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self._tray is None:
            from ..svg_icons import icon
            self._tray = QSystemTrayIcon(icon('bell'), QApplication.instance())
            self._tray.show()
        self._tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 10_000)

    # ---- network work, off the GUI thread
    def _run(self, kind, fn):
        w = _Worker(kind, fn, self)
        w.result.connect(self._done)
        w.finished.connect(lambda w=w: self.workers.remove(w) if w in self.workers else None)
        self.workers.append(w)
        w.start()

    def _sync(self):
        from ...organizer import sync
        store = self.org.calendar
        for cid in sync.due_subscriptions(store):
            self._run('calendar', lambda c=cid: sync.refresh_subscription(store, c))
        for cid in sync.sync_due(store):
            self._run('calendar', lambda c=cid: sync.two_way(store, c, sync.remote_for(store, c)))

    def _check_mail(self, accounts, conf):
        from ...organizer import admin

        def work():
            found = []
            for acc in accounts:
                client = self.org.mail.client(acc['id'])
                for folder in acc.get('folders') or ['INBOX']:
                    msgs = client.recent(folder, days=3, limit=40)
                    self.org.mail.remember(msgs)
                    if not (conf.get('admin_mail_detection', True) and acc.get('admin_detection', True)):
                        continue
                    for m in msgs:
                        key = m.get('message_id') or f"{m['account']}|{m['uid']}"
                        if self.org.mail.processed(key):
                            continue
                        hit = admin.detect(m)
                        self.org.mail.mark_processed(key, 'admin' if hit else '')
                        if hit:
                            task, _created = admin.start(self.org, m, hit)
                            found.append({'kind': 'admin_form', 'account': m['account'], 'uid': m['uid'],
                                          'folder': folder, 'task': task['id'],
                                          'found': {k: v for k, v in hit.items() if k != 'pdf_attachments'},
                                          'pdfs': [a['index'] for a in hit.get('pdf_attachments') or []],
                                          'subject': m.get('subject', '')})
            return found
        self._run('mail', work)

    def _done(self, kind, result, error):
        if kind == 'calendar':
            self.org.changed('calendar')
        elif kind == 'mail':
            self.org.changed('mail')
            for card in result or []:
                self.org.changed('todo')
                self._show({'kind': 'task', 'title': 'Administrative e-mail: ' + card.get('subject', ''),
                            'id': card['task'], 'instance': '', 'minutes': 0, 'at': dt.datetime.now(),
                            'start': dt.datetime.now(), 'all_day': False})
                self.adminFound.emit(card)
