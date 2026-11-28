"""Calendar, to-do and e-mail in SPM Studio — available without any AI connected.

The windows come from the Agent Hub organizer (shared data with the assistant and the standalone app). Reminders
run in the background while SPM Studio is open (started a few seconds after start-up, so opening the app stays
fast), with a “missed / upcoming” summary at start. E-mail is checked only when an account is connected."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer


class Organizer(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.notifier = None

    def _ensure_host(self):
        """The organizer needs a host for its data folder and theme; the assistant's host is set when it opens."""
        from agent_hub import host as ah_host
        current = ah_host.current()
        if current.name == 'standalone' or getattr(current, 'main_window', None) is not self.main_window:
            from .host import SPMHost
            ah_host.set_host(SPMHost(self.main_window))

    def organizer(self):
        self._ensure_host()
        from agent_hub.organizer import shared
        org = shared()
        try:
            org.options['todo_on_calendar'] = bool(self._conf().get('todo_on_calendar', True))
        except Exception:
            pass
        return org

    def _conf(self) -> dict:
        from agent_hub import host as ah_host, settings as hubsettings
        return hubsettings.load(ah_host.current().data_dir())

    def open(self, which: str, ident: str = ''):
        from agent_hub.ui.organizer.windows import open_window
        return open_window(which, ident, parent=self.main_window, organizer=self.organizer())

    def start_background(self, delay_ms: int = 4000):
        QTimer.singleShot(delay_ms, self._start)

    def _start(self):
        try:
            from agent_hub.ui.organizer.notifier import Notifier
            self.notifier = Notifier(self.organizer(), self._conf, notify=None, parent=self)
            self.notifier.summaryReady.connect(self._summary)
            self.notifier.adminFound.connect(self._admin)
            self.notifier.start()
        except Exception as exc:
            try:
                self.main_window.log('Calendar reminders not started: ' + str(exc))
            except Exception:
                pass

    def _summary(self, summary: dict):
        from .start_summary import StartSummary
        dialog = StartSummary(summary, self.main_window)
        dialog.openCalendar.connect(lambda: self.open('calendar'))
        dialog.openTodo.connect(lambda: self.open('todo'))
        dialog.show()

    def _admin(self, card: dict):
        """An administrative e-mail arrived: its to-do exists; the form card waits in the e-mail window."""
        try:
            win = self.open('mail')
            from agent_hub.ui.organizer.cards import AdminFormCard
            widget = AdminFormCard(win.org, card, win)
            widget.closed.connect(widget.deleteLater)
            widget.outboxed.connect(lambda _i: win.show_outbox())
            win.cards_box.addWidget(widget)
        except Exception:
            pass

    def stop(self):
        if self.notifier is not None:
            self.notifier.stop()
        try:
            from agent_hub.ui.organizer.windows import close_all
            close_all()
        except Exception:
            pass
