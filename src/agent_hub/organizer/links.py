"""Two-way link between to-dos and calendar events (Qt-free), by stable ids only (never by title).

* A task with a due date has one calendar entry in the *Tasks* calendar: ``task.links.event`` = event uid and
  ``event.links.todo`` = task id. An all-day entry for a date, a timed one (``duration_min``, default 30) for a
  date with a time.
* Editing the task (title, date, notes, done) updates its entry; moving or renaming the entry updates the task;
  completing either marks both done (the entry keeps showing, marked done); removing the task's date removes
  its entry; deleting the entry removes the task's date (the task itself stays).
* Preparation / follow-up tasks of an event point to it with ``task.links.for_event`` and a ``purpose``
  (``prep`` · ``follow-up`` · any short key). :meth:`Organizer.ensure_event_task` returns the existing task for
  the same (event, purpose) instead of creating a duplicate.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from .calendar import CalendarStore, iso, parse_time
from .todo import TodoStore, parse_due


class Organizer:
    """Calendar + to-do (+ mail, created lazily) of one user, linked together."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.calendar = CalendarStore(self.root)
        self.todo = TodoStore(self.root)
        self._mail = None
        self.listeners = []                 # callables(kind) — 'calendar' · 'todo' · 'mail'
        self.options = {'todo_on_calendar': True}

    @property
    def mail(self):
        if self._mail is None:
            from .mail import MailStore
            self._mail = MailStore(self.root)
        return self._mail

    def changed(self, kind: str):
        for fn in list(self.listeners):
            try:
                fn(kind)
            except Exception:
                pass

    # ------------------------------------------------------------------ to-do → calendar
    def _entry_fields(self, task: dict) -> dict | None:
        due = parse_due(task.get('due'))
        if due is None:
            return None
        title = task['title']
        fields = {'title': title, 'description': task.get('notes', ''), 'links': {'todo': task['id']},
                  'calendar': self.calendar.default_calendar('tasks')['id'], 'status': 'DONE' if task['done'] else ''}
        if isinstance(due, dt.datetime):
            minutes = int(task.get('duration_min') or 30)
            fields.update(all_day=False, start=iso(due), end=iso(due + dt.timedelta(minutes=minutes)), tz='')
        else:
            fields.update(all_day=True, start=due.isoformat(), end=(due + dt.timedelta(days=1)).isoformat())
        if task.get('rrule'):
            fields['rrule'] = ''                 # the entry shows the next due date only
        return fields

    def sync_task(self, task_or_id) -> dict | None:
        """Create, update or remove the calendar entry of a task. Returns the entry (or None)."""
        task = self.todo.get(task_or_id) if isinstance(task_or_id, str) else task_or_id
        if task is None:
            return None
        uid = (task.get('links') or {}).get('event', '')
        entry = self.calendar.get(uid) if uid else None
        if entry is None:                           # stable link from the event side (after a merge, say)
            entry = next((e for e in self.calendar.events() if (e.get('links') or {}).get('todo') == task['id']),
                         None)
        fields = self._entry_fields(task) if self.options.get('todo_on_calendar', True) else None
        if fields is None:
            if entry is not None and entry.get('created_by') == 'todo':
                self.calendar.delete(entry['uid'])
            if uid:
                links = dict(task.get('links') or {})
                links.pop('event', None)
                self.todo.update(task['id'], links=links)
            self.changed('calendar')
            return None
        if entry is None:
            entry = self.calendar.create(fields, created_by='todo')
        else:
            keep = {k: entry[k] for k in ('calendar', 'reminders', 'color', 'location') if entry.get(k)}
            if entry.get('created_by') != 'todo':
                fields.pop('calendar', None)
            fields['links'] = dict(entry.get('links') or {}, todo=task['id'])
            entry = self.calendar.update(entry['uid'], _sync=True, **{**fields, **keep})
        if (task.get('links') or {}).get('event') != entry['uid']:
            self.todo.update(task['id'], links=dict(task.get('links') or {}, event=entry['uid']))
        self.changed('calendar')
        return entry

    def add_task(self, fields: dict, created_by: str = 'user') -> dict:
        task = self.todo.create(fields, created_by=created_by)
        if task.get('due'):
            self.sync_task(task)
        self.changed('todo')
        return self.todo.get(task['id'])

    def update_task(self, tid: str, **fields) -> dict:
        task = self.todo.update(tid, **fields)
        if task.get('due') or (task.get('links') or {}).get('event'):
            self.sync_task(task)
        self.changed('todo')
        return self.todo.get(tid)

    def complete_task(self, tid: str, done: bool = True) -> dict:
        task = self.todo.complete(tid, done)
        self.sync_task(task)
        self.changed('todo')
        return self.todo.get(tid)

    def delete_task(self, tid: str) -> dict | None:
        task = self.todo.delete(tid)
        if task is not None:
            uid = (task.get('links') or {}).get('event')
            entry = self.calendar.get(uid) if uid else None
            if entry is not None and entry.get('created_by') == 'todo':
                self.calendar.delete(uid)
            elif entry is not None:
                links = dict(entry.get('links') or {})
                links.pop('todo', None)
                self.calendar.update(uid, _sync=True, links=links)
            self.changed('todo')
            self.changed('calendar')
        return task

    # ------------------------------------------------------------------ events (use these from views)
    def create_event(self, fields: dict, created_by: str = 'user') -> dict:
        ev = self.calendar.create(fields, created_by=created_by)
        self.changed('calendar')
        return ev

    def update_event(self, uid: str, **fields) -> dict:
        ev = self.calendar.update(uid, **fields)
        self.event_changed(uid)
        self.changed('calendar')
        return ev

    def move_event(self, uid: str, start, end=None) -> dict:
        ev = self.calendar.move(uid, start, end)
        self.event_changed(uid)
        self.changed('calendar')
        return ev

    def delete_event(self, uid: str) -> dict | None:
        ev = self.calendar.delete(uid)
        if ev is not None:
            self.event_deleted(ev)
            self.changed('calendar')
        return ev

    # ------------------------------------------------------------------ calendar → to-do
    def event_changed(self, uid: str):
        """Call after an event was edited (moved, renamed, marked done): its linked task follows."""
        ev = self.calendar.get(uid)
        if ev is None:
            return None
        tid = (ev.get('links') or {}).get('todo')
        task = self.todo.get(tid) if tid else None
        if task is None:
            return None
        start = parse_time(ev['start'])
        if ev.get('all_day'):
            due = (start.date() if isinstance(start, dt.datetime) else start).isoformat()
            extra = {}
        else:
            due = start.strftime('%Y-%m-%dT%H:%M')
            minutes = int((parse_time(ev['end']) - start).total_seconds() // 60)
            extra = {'duration_min': max(5, minutes)}
        done = ev.get('status') == 'DONE'
        changes = {}
        if task['title'] != ev['title']:
            changes['title'] = ev['title']
        if task.get('due') != due:
            changes['due'] = due
        if extra and task.get('duration_min') != extra['duration_min']:
            changes.update(extra)
        if task['done'] != done:
            if done:
                self.todo.complete(tid, True)
            else:
                changes['done'] = False
                changes['done_at'] = ''
        if changes:
            self.todo.update(tid, **changes)
        task = self.todo.get(tid)
        if task.get('rrule') and done:                 # a recurring task moved on: its entry follows
            self.sync_task(task)
        self.changed('todo')
        return task

    def event_deleted(self, event: dict):
        """Call after an event was deleted: a linked task loses its date (and stays)."""
        tid = (event.get('links') or {}).get('todo')
        task = self.todo.get(tid) if tid else None
        if task is not None:
            links = dict(task.get('links') or {})
            links.pop('event', None)
            self.todo.update(tid, due='', links=links)
        for t in self.todo.tasks():
            if (t.get('links') or {}).get('for_event') == event.get('uid'):
                links = dict(t['links'])
                links['for_event_deleted'] = links.pop('for_event')
                self.todo.update(t['id'], links=links)
        self.changed('todo')

    def set_event_done(self, uid: str, done: bool = True):
        self.calendar.update(uid, _sync=True, status='DONE' if done else '')
        return self.event_changed(uid)

    # ------------------------------------------------------------------ event preparation / follow-up
    def event_tasks(self, uid: str) -> list[dict]:
        return [t for t in self.todo.tasks() if (t.get('links') or {}).get('for_event') == uid]

    def ensure_event_task(self, uid: str, purpose: str, title: str, due=None, created_by: str = 'assistant',
                          notes: str = '') -> tuple[dict, bool]:
        """The task for (event, purpose), created once. Returns (task, created)."""
        purpose = str(purpose or 'prep').strip().lower()[:40]
        for t in self.event_tasks(uid):
            if (t.get('links') or {}).get('purpose', 'prep') == purpose:
                return t, False
        ev = self.calendar.get(uid)
        if ev is None:
            raise KeyError(uid)
        if due is None:
            start = parse_time(ev['start'])
            if purpose.startswith('follow'):
                due = (start.date() if isinstance(start, dt.datetime) else start) + dt.timedelta(days=1)
            else:
                day = (start.date() if isinstance(start, dt.datetime) else start) - dt.timedelta(days=1)
                due = day
        task = self.add_task({'title': title, 'notes': notes, 'due': due if isinstance(due, str) else
                              (due.strftime('%Y-%m-%dT%H:%M') if isinstance(due, dt.datetime) else due.isoformat()),
                              'links': {'for_event': uid, 'purpose': purpose}}, created_by=created_by)
        return task, True
