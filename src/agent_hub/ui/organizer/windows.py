"""One calendar, one to-do and one e-mail window per process (raised when opened again)."""
from __future__ import annotations

_windows: dict[str, object] = {}


def open_window(which: str, ident: str = '', parent=None, organizer=None):
    win = _windows.get(which)
    try:
        if win is not None:
            win.isVisible()
    except RuntimeError:
        win = None
    if win is None:
        if which == 'calendar':
            from .calendar_view import CalendarWindow
            win = CalendarWindow(organizer)
        elif which == 'todo':
            from .todo_view import TodoWindow
            win = TodoWindow(organizer)
        elif which == 'mail':
            from .mail_view import MailWindow
            win = MailWindow(organizer)
        else:
            raise ValueError(which)
        try:
            icon = parent.windowIcon() if parent is not None else None
            if icon is not None and not icon.isNull():
                win.setWindowIcon(icon)
        except (RuntimeError, AttributeError):
            pass
        _windows[which] = win
    win.show()
    if win.isMinimized():
        win.showNormal()
    win.raise_()
    win.activateWindow()
    if ident:
        try:
            if which == 'calendar':
                ev = win.org.calendar.get(ident)
                if ev is not None:
                    from ...organizer.calendar import parse_time
                    import datetime as dt
                    start = parse_time(ev['start'])
                    win.set_date(start.date() if isinstance(start, dt.datetime) else start)
            elif which == 'todo':
                win.focus_task(ident)
            elif which == 'mail':
                win.show_outbox(ident)
        except Exception:
            pass
    return win


def close_all():
    for win in list(_windows.values()):
        try:
            win.close()
        except RuntimeError:
            pass
    _windows.clear()
