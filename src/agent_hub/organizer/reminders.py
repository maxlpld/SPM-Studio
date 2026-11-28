"""Reminder scheduling (Qt-free): which reminders fall due in a time range, what was missed while the app was
closed, and what is coming up. The Qt layer (``ui/organizer/notifier.py``) shows desktop notifications.

A reminder is (event uid, instance start, minutes before). It fires once: fired keys are remembered in
``reminders.json`` for 14 days. Tasks with a due time remind at the due time (and with a due date only, at
9:00 that day) unless the task is done.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from .base import atomic_write, read_json
from .todo import parse_due

KEEP_DAYS = 14


def key_of(r: dict) -> str:
    return f"{r['kind']}|{r['id']}|{r['instance']}|{r['minutes']}"


def due_between(organizer, start: dt.datetime, end: dt.datetime) -> list[dict]:
    """Every reminder whose firing time is in ``[start, end)`` (events and tasks), sorted by time."""
    out = []
    horizon = end + dt.timedelta(days=31)
    for o in organizer.calendar.occurrences(start - dt.timedelta(days=1), horizon):
        if (o.get('links') or {}).get('todo'):
            continue                                  # the task itself reminds
        begin = o['start'] if isinstance(o['start'], dt.datetime) else dt.datetime.combine(o['start'], dt.time(9))
        for minutes in o.get('reminders') or []:
            at = begin - dt.timedelta(minutes=int(minutes))
            if start <= at < end:
                out.append({'kind': 'event', 'id': o['uid'], 'instance': o['instance'], 'minutes': int(minutes),
                            'at': at, 'title': o['title'], 'start': begin, 'all_day': o['all_day'],
                            'location': o.get('location', '')})
    for t in organizer.todo.tasks(include_done=False):
        due = parse_due(t.get('due'))
        if due is None:
            continue
        at = due if isinstance(due, dt.datetime) else dt.datetime.combine(due, dt.time(9))
        if start <= at < end:
            out.append({'kind': 'task', 'id': t['id'], 'instance': t['due'], 'minutes': 0, 'at': at,
                        'title': t['title'], 'start': at, 'all_day': not isinstance(due, dt.datetime),
                        'location': ''})
    out.sort(key=lambda r: r['at'])
    return out


class ReminderLog:
    def __init__(self, root: Path):
        self.path = Path(root) / 'reminders.json'
        self.data = read_json(self.path, {})
        self.data.setdefault('fired', {})
        self.data.setdefault('last_run', '')

    def fired(self, r: dict) -> bool:
        return key_of(r) in self.data['fired']

    def mark(self, reminders: list[dict], now: dt.datetime | None = None):
        now = now or dt.datetime.now()
        for r in reminders:
            self.data['fired'][key_of(r)] = now.isoformat(timespec='seconds')
        limit = (now - dt.timedelta(days=KEEP_DAYS)).isoformat()
        self.data['fired'] = {k: v for k, v in self.data['fired'].items() if v >= limit}
        self.save()

    def last_run(self) -> dt.datetime | None:
        try:
            return dt.datetime.fromisoformat(self.data['last_run']) if self.data['last_run'] else None
        except ValueError:
            return None

    def set_last_run(self, when: dt.datetime):
        self.data['last_run'] = when.isoformat(timespec='seconds')
        self.save()

    def save(self):
        atomic_write(self.path, self.data)


def pending(organizer, log: ReminderLog, now: dt.datetime | None = None, lookback: dt.timedelta | None = None):
    """Reminders that should fire now: due since the last check (or ``lookback``) and not fired yet."""
    now = now or dt.datetime.now()
    since = log.last_run() or (now - (lookback or dt.timedelta(minutes=5)))
    since = max(since, now - dt.timedelta(days=7))
    return [r for r in due_between(organizer, since, now + dt.timedelta(seconds=1)) if not log.fired(r)]


def start_summary(organizer, log: ReminderLog, now: dt.datetime | None = None, hours_ahead: int = 24) -> dict:
    """On app start: reminders missed while closed (since the last run, at most 7 days) and what comes in the
    next ``hours_ahead`` hours (events and tasks), plus overdue tasks."""
    now = now or dt.datetime.now()
    last = log.last_run()
    missed = []
    if last is not None:
        since = max(last, now - dt.timedelta(days=7))
        missed = [r for r in due_between(organizer, since, now) if not log.fired(r)]
    upcoming = []
    for o in organizer.calendar.occurrences(now, now + dt.timedelta(hours=hours_ahead)):
        if (o.get('links') or {}).get('todo'):
            continue
        upcoming.append({'kind': 'event', 'title': o['title'], 'start': o['start'], 'all_day': o['all_day'],
                         'id': o['uid']})
    for t in organizer.todo.view('open'):
        due = parse_due(t.get('due'))
        if due is None:
            continue
        at = due if isinstance(due, dt.datetime) else dt.datetime.combine(due, dt.time(23, 59))
        if now <= at <= now + dt.timedelta(hours=hours_ahead):
            upcoming.append({'kind': 'task', 'title': t['title'], 'start': at,
                             'all_day': not isinstance(due, dt.datetime), 'id': t['id']})
    overdue = [t for t in organizer.todo.view('overdue')]
    upcoming.sort(key=lambda u: u['start'] if isinstance(u['start'], dt.datetime)
                  else dt.datetime.combine(u['start'], dt.time()))
    return {'missed': missed, 'upcoming': upcoming, 'overdue': overdue, 'last_run': last}
