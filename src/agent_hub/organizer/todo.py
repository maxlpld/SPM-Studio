"""To-do store (Qt-free): lists with colour and icon, tags, priority, deadline (date, optional time), start
date, recurrence, subtasks, notes, links (event, chat, e-mail, files), manual order, smart views, natural-
language quick add, and a one-time copy of an older to-do file (the original is never modified).

Task fields::

    id, title, notes, list, tags, priority (0 none · 1 low · 2 medium · 3 high)
    due ('' · 'YYYY-MM-DD' · 'YYYY-MM-DDTHH:MM'), start ('' · 'YYYY-MM-DD'), rrule
    subtasks [{id, title, done}], links {event, for_event, purpose, chat, email, files: [...]}
    done, done_at, order, created, updated, created_by (user · assistant · email · calendar · migration)
    legacy_id (id in the older file), history [done dates of a recurring task]
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from . import rrule
from .base import RecordFile, new_id, now_iso, now_ts, read_json

LIST_COLORS = ['#4285F4', '#0B8043', '#D50000', '#F4511E', '#8E24AA', '#039BE5', '#E67C73', '#F6BF26']
LIST_ICONS = ['inbox', 'list', 'flag', 'star', 'briefcase', 'home', 'book', 'code', 'chart', 'mail']
PRIORITIES = {0: 'None', 1: 'Low', 2: 'Medium', 3: 'High'}
VIEWS = ('today', 'upcoming', 'overdue', 'completed', 'all')
OLD_CATEGORY_ICONS = {'Analysis': 'chart', 'Script': 'code', 'Writing': 'book', 'Figure': 'star', 'Other': 'list'}


class TodoFile(RecordFile):
    collections = ('lists', 'tasks')
    schema = 2


def parse_due(text: str):
    """'' → None, 'YYYY-MM-DD' → date, 'YYYY-MM-DDTHH:MM[:SS]' → datetime."""
    text = str(text or '').strip()
    if not text:
        return None
    if len(text) == 10:
        return dt.date.fromisoformat(text)
    return dt.datetime.fromisoformat(text).replace(tzinfo=None, second=0, microsecond=0)


def due_text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, dt.datetime):
        return value.strftime('%Y-%m-%dT%H:%M')
    return value.isoformat()


def due_date(task: dict):
    d = parse_due(task.get('due', ''))
    return d.date() if isinstance(d, dt.datetime) else d


class TodoStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.file = TodoFile(self.root / 'todo.json')
        if not self.file.data['lists']:
            self.add_list('Inbox', LIST_COLORS[0], 'inbox', save=False)
            self.file.save()

    def reload(self) -> bool:
        return self.file.reload()

    # ------------------------------------------------------------------ lists
    def lists(self) -> list[dict]:
        self.file.reload()
        return sorted(self.file.data['lists'].values(), key=lambda l: (l.get('order', 0), l['name'].lower()))

    def list_(self, lid: str) -> dict | None:
        return self.file.data['lists'].get(lid)

    def list_by_name(self, name: str) -> dict | None:
        key = str(name or '').strip().lower()
        return next((l for l in self.lists() if l['name'].lower() == key), None)

    def inbox(self) -> dict:
        return next((l for l in self.lists() if l.get('icon') == 'inbox'), None) or self.lists()[0]

    def add_list(self, name: str, color: str = '', icon: str = 'list', save: bool = True) -> dict:
        n = len(self.file.data['lists'])
        lst = {'id': new_id('l'), 'name': str(name or 'List').strip()[:60] or 'List',
               'color': color or LIST_COLORS[n % len(LIST_COLORS)], 'icon': icon if icon in LIST_ICONS else 'list',
               'order': n, 'updated': now_ts()}
        self.file.data['lists'][lst['id']] = lst
        if save:
            self.file.save()
        return lst

    def update_list(self, lid: str, **fields) -> dict:
        lst = self.file.data['lists'][lid]
        for key in ('name', 'color', 'icon', 'order'):
            if key in fields:
                lst[key] = fields[key]
        lst['updated'] = now_ts()
        self.file.save()
        return lst

    def delete_list(self, lid: str, move_to: str = '') -> int:
        """Tasks of the list move to ``move_to`` (default: the inbox); never deleted with it."""
        target = move_to or self.inbox()['id']
        if target == lid:
            others = [l for l in self.lists() if l['id'] != lid]
            if not others:
                raise ValueError('The last list cannot be deleted')
            target = others[0]['id']
        moved = 0
        for t in self.file.data['tasks'].values():
            if t.get('list') == lid:
                t['list'] = target
                t['updated'] = now_ts()
                moved += 1
        self.file.data['lists'].pop(lid, None)
        self.file.tombstone(lid)
        self.file.save()
        return moved

    # ------------------------------------------------------------------ tasks
    def tasks(self, list_id: str | None = None, include_done: bool = True) -> list[dict]:
        self.file.reload()
        out = [t for t in self.file.data['tasks'].values()
               if (list_id is None or t.get('list') == list_id) and (include_done or not t.get('done'))]
        out.sort(key=lambda t: (t.get('done', False), t.get('order', 0), t.get('created', 0)))
        return out

    def get(self, tid: str) -> dict | None:
        self.file.reload()
        return self.file.data['tasks'].get(tid)

    def find(self, ref) -> dict:
        """By id, legacy id, or 1-based position in the open tasks (``3`` / ``#3``)."""
        ref = str(ref or '').strip().lstrip('#')
        tasks = self.file.data['tasks']
        if ref in tasks:
            return tasks[ref]
        for t in tasks.values():
            if t.get('legacy_id') == ref:
                return t
        ordered = self.tasks()
        if ref.isdigit() and 1 <= int(ref) <= len(ordered):
            return ordered[int(ref) - 1]
        raise KeyError(f'No task {ref!r}')

    def _clean(self, fields: dict, base: dict | None = None) -> dict:
        t = dict(base or {'id': '', 'title': 'New task', 'notes': '', 'list': '', 'tags': [], 'priority': 0,
                          'due': '', 'start': '', 'rrule': '', 'subtasks': [], 'links': {}, 'done': False,
                          'done_at': '', 'order': 0, 'created_by': 'user', 'history': []})
        for key in ('title', 'notes', 'list', 'tags', 'priority', 'due', 'start', 'rrule', 'subtasks', 'links',
                    'done', 'done_at', 'order', 'created_by', 'legacy_id', 'duration_min', 'history'):
            if key in fields:
                t[key] = fields[key]
        t['title'] = str(t.get('title') or 'New task').strip()[:500] or 'New task'
        t['notes'] = str(t.get('notes') or '')[:20000]
        t['tags'] = sorted({str(x).strip().lstrip('#').lower() for x in (t.get('tags') or []) if str(x).strip()})[:20]
        t['priority'] = max(0, min(3, int(t.get('priority') or 0)))
        t['due'] = due_text(parse_due(t.get('due')))
        t['start'] = due_text(parse_due(t.get('start')))
        if t['start'] and len(t['start']) > 10:
            t['start'] = t['start'][:10]
        if t.get('rrule'):
            rrule.parse(t['rrule'])
        if not t.get('list') or t['list'] not in self.file.data['lists']:
            t['list'] = self.inbox()['id']
        subs = []
        for s in t.get('subtasks') or []:
            if isinstance(s, dict) and str(s.get('title', '')).strip():
                subs.append({'id': s.get('id') or new_id('s'), 'title': str(s['title']).strip()[:300],
                             'done': bool(s.get('done'))})
        t['subtasks'] = subs[:100]
        links = dict(t.get('links') or {})
        links['files'] = [str(f) for f in links.get('files', []) if str(f).strip()][:30]
        t['links'] = {k: v for k, v in links.items() if v}
        t['done'] = bool(t.get('done'))
        return t

    def create(self, fields: dict, created_by: str = 'user', save: bool = True) -> dict:
        self.file.reload()
        t = self._clean(dict(fields, created_by=fields.get('created_by') or created_by))
        t['id'] = str(fields.get('id') or new_id('t'))
        if 'order' not in fields:
            t['order'] = max([x.get('order', 0) for x in self.file.data['tasks'].values()] or [0]) + 1
        t['created'] = t['updated'] = now_ts()
        if t['done'] and not t.get('done_at'):
            t['done_at'] = now_iso()
        self.file.data['tasks'][t['id']] = t
        if save:
            self.file.save()
        return t

    def update(self, tid: str, save: bool = True, **fields) -> dict:
        self.file.reload()
        old = self.file.data['tasks'].get(tid)
        if old is None:
            raise KeyError(tid)
        t = self._clean(fields, base=old)
        t['id'] = tid
        t['created'] = old.get('created', now_ts())
        t['updated'] = now_ts()
        self.file.data['tasks'][tid] = t
        if save:
            self.file.save()
        return t

    def complete(self, tid: str, done: bool = True) -> dict:
        """Done / not done. A recurring task moves to its next due date instead (history keeps the date)."""
        t = self.get(tid)
        if t is None:
            raise KeyError(tid)
        if done and t.get('rrule') and t.get('due'):
            nxt = self.next_due(t)
            if nxt is not None:
                history = list(t.get('history') or []) + [now_iso()]
                subs = [dict(s, done=False) for s in t.get('subtasks', [])]
                return self.update(tid, due=due_text(nxt), history=history[-50:], subtasks=subs, done=False)
        return self.update(tid, done=bool(done), done_at=now_iso() if done else '')

    @staticmethod
    def next_due(task: dict):
        due = parse_due(task.get('due'))
        if due is None or not task.get('rrule'):
            return None
        after = due + (dt.timedelta(minutes=1) if isinstance(due, dt.datetime) else dt.timedelta(days=1))
        found = rrule.expand(task['rrule'], due, after, None, limit=1)
        return found[0] if found else None

    def delete(self, tid: str, save: bool = True) -> dict | None:
        self.file.reload()
        t = self.file.data['tasks'].pop(tid, None)
        if t is not None:
            self.file.tombstone(tid)
            if save:
                self.file.save()
        return t

    def reorder(self, ids: list[str]):
        """New manual order (drag and drop) for the given tasks."""
        for n, tid in enumerate(ids):
            t = self.file.data['tasks'].get(tid)
            if t is not None and t.get('order') != n:
                t['order'] = n
                t['updated'] = now_ts()
        self.file.save()

    def toggle_subtask(self, tid: str, sid: str, done: bool) -> dict:
        t = self.get(tid)
        subs = [dict(s, done=bool(done)) if s['id'] == sid else s for s in t.get('subtasks', [])]
        return self.update(tid, subtasks=subs)

    # ---- notes (the "Notes" page of the to-do window; kept from the first to-do version)
    def notes(self) -> str:
        self.file.reload()
        return str(self.file.data['meta'].get('notes', ''))

    def set_notes(self, text: str):
        self.file.data['meta']['notes'] = str(text)[:500000]
        self.file.data['meta']['notes_updated'] = now_iso()
        self.file.save()

    def erase_all(self) -> Path | None:
        """Remove every task and the notes; a copy ``erased_<date>.json`` is kept beside the file first."""
        import datetime as _dt
        import json as _json
        self.file.reload()
        copy = None
        if self.file.data['tasks'] or str(self.file.data['meta'].get('notes', '')).strip():
            stamp = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
            copy = self.root / f'erased_{stamp}.json'
            copy.write_text(_json.dumps(self.file.data, indent=1, ensure_ascii=False), encoding='utf8')
        for tid in list(self.file.data['tasks']):
            self.file.data['tasks'].pop(tid)
            self.file.tombstone(tid)
        self.file.data['meta']['notes'] = ''
        self.file.save()
        return copy

    # ------------------------------------------------------------------ views
    def view(self, name: str, today: dt.date | None = None, query: str = '', tag: str = '',
             sort: str = 'manual', list_id: str = '') -> list[dict]:
        today = today or dt.date.today()
        tasks = self.tasks(list_id or None)
        if name == 'today':
            tasks = [t for t in tasks if not t['done'] and due_date(t) is not None and due_date(t) <= today]
        elif name == 'upcoming':
            tasks = [t for t in tasks if not t['done'] and due_date(t) is not None and due_date(t) > today]
        elif name == 'overdue':
            tasks = [t for t in tasks if not t['done'] and self.overdue(t)]
        elif name == 'completed':
            tasks = [t for t in tasks if t['done']]
        elif name == 'open':
            tasks = [t for t in tasks if not t['done']]
        if query:
            q = query.lower().strip()
            tasks = [t for t in tasks if q in t['title'].lower() or q in t['notes'].lower() or
                     any(q in s['title'].lower() for s in t.get('subtasks', [])) or q.lstrip('#') in t['tags']]
        if tag:
            tasks = [t for t in tasks if tag.lower().lstrip('#') in t['tags']]
        return self.sort(tasks, sort)

    @staticmethod
    def overdue(task: dict, now: dt.datetime | None = None) -> bool:
        if task.get('done'):
            return False
        due = parse_due(task.get('due'))
        now = now or dt.datetime.now()
        if due is None:
            return False
        if isinstance(due, dt.datetime):
            return due < now
        return due < now.date()

    @staticmethod
    def sort(tasks: list[dict], how: str = 'manual') -> list[dict]:
        far = dt.datetime(9999, 1, 1)

        def due_key(t):
            d = parse_due(t.get('due'))
            if d is None:
                return far
            return d if isinstance(d, dt.datetime) else dt.datetime.combine(d, dt.time(23, 59))
        keys = {'manual': lambda t: (t['done'], t.get('order', 0)),
                'due': lambda t: (t['done'], due_key(t), -t['priority']),
                'priority': lambda t: (t['done'], -t['priority'], due_key(t)),
                'title': lambda t: (t['done'], t['title'].lower()),
                'created': lambda t: (t['done'], -float(t.get('created', 0)))}
        return sorted(tasks, key=keys.get(how, keys['manual']))

    def tags(self) -> list[str]:
        return sorted({tag for t in self.tasks() for tag in t.get('tags', [])})

    def counts(self, today: dt.date | None = None) -> dict:
        return {v: len(self.view(v, today)) for v in ('today', 'upcoming', 'overdue', 'completed')}

    # ------------------------------------------------------------------ migration of the first version
    def migrate_v1(self, path: Path) -> dict:
        """Copy an SPM Studio 0.0.x ``todo.json`` once (categories → lists, notes kept). The file is only read.
        Returns {'copied': n, 'source': path} (0 when already done or nothing to copy)."""
        path = Path(path)
        done = self.file.data['meta'].get('migrated', {})
        key = str(path)
        if key in done or not path.is_file():
            return {'copied': 0, 'source': key}
        old = read_json(path, {})
        if not isinstance(old, dict):
            return {'copied': 0, 'source': key}
        lists = {l['name']: l for l in self.lists()}
        copied = 0
        for n, raw in enumerate(old.get('tasks') or []):
            if not isinstance(raw, dict):
                continue
            category = str(raw.get('category') or '')
            if category:
                if category not in lists:
                    lists[category] = self.add_list(category, '', OLD_CATEGORY_ICONS.get(category, 'list'),
                                                    save=False)
                list_id = lists[category]['id']
            else:
                list_id = self.inbox()['id']
            legacy = str(raw.get('id') or '')
            if legacy and any(t.get('legacy_id') == legacy for t in self.file.data['tasks'].values()):
                continue
            self.create({'title': str(raw.get('text') or 'Task'), 'notes': str(raw.get('details') or ''),
                         'list': list_id, 'done': bool(raw.get('done')), 'done_at': str(raw.get('done_at') or ''),
                         'legacy_id': legacy, 'order': n, 'created_by': 'migration'}, save=False)
            copied += 1
        notes = str(old.get('notes') or '')
        if notes.strip():
            current = str(self.file.data['meta'].get('notes', ''))
            self.file.data['meta']['notes'] = notes if not current.strip() else current + '\n\n' + notes
        done = dict(done)
        done[key] = {'at': now_iso(), 'tasks': copied}
        self.file.data['meta']['migrated'] = done
        self.file.save()
        return {'copied': copied, 'source': key}


# ---------------------------------------------------------------------------------------- quick add
WEEKDAYS = {'monday': 0, 'mon': 0, 'tuesday': 1, 'tue': 1, 'tues': 1, 'wednesday': 2, 'wed': 2, 'thursday': 3,
            'thu': 3, 'thur': 3, 'thurs': 3, 'friday': 4, 'fri': 4, 'saturday': 5, 'sat': 5, 'sunday': 6, 'sun': 6,
            'lundi': 0, 'mardi': 1, 'mercredi': 2, 'jeudi': 3, 'vendredi': 4, 'samedi': 5, 'dimanche': 6,
            'montag': 0, 'dienstag': 1, 'mittwoch': 2, 'donnerstag': 3, 'freitag': 4, 'samstag': 5, 'sonntag': 6}
MONTHS = {'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3, 'apr': 4, 'april': 4, 'may': 5,
          'jun': 6, 'june': 6, 'jul': 7, 'july': 7, 'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
          'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12}
PRIORITY_WORDS = {'high': 3, 'h': 3, '3': 3, 'urgent': 3, '!': 3, 'medium': 2, 'med': 2, 'm': 2, '2': 2,
                  'low': 1, 'l': 1, '1': 1}
RRULE_DAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']


def parse_quick(text: str, today: dt.date | None = None) -> dict:
    """Natural-language quick add. ``call Bob friday 10am #admin !high`` →
    {'title': 'call Bob', 'due': '<next Friday>T10:00', 'tags': ['admin'], 'priority': 3}.

    Understands: today / tomorrow / tonight (fr. aujourd'hui, demain; de. heute, morgen), weekday names (the
    next one; ``next friday`` = the week after), ``next week``, ``in 3 days`` / ``in 2 weeks``, ``dec 5`` /
    ``5 december`` / ``2026-12-05`` / ``5.12.`` / ``12/5``; times ``10am``, ``10:30``, ``2pm``, ``14h``,
    ``14:00``, ``at 3``; ``every day / week / monday / month``; ``#tag``; ``!high`` ``!med`` ``!low`` ``!!!``;
    ``@List`` (an existing list name)."""
    today = today or dt.date.today()
    words = str(text or '').strip()
    out = {'title': '', 'due': '', 'tags': [], 'priority': 0, 'rrule': '', 'list_name': ''}
    out['tags'] = [t.lower() for t in re.findall(r'(?<!\S)#([\w\-]+)', words)]
    words = re.sub(r'(?<!\S)#[\w\-]+', ' ', words)
    m = re.search(r'(?<!\S)!(high|medium|med|low|urgent|[123hml]|!{0,2})(?!\S)', words, re.I)
    if m:
        token = m.group(1).lower()
        out['priority'] = PRIORITY_WORDS.get(token, len(token) + 1 if set(token) <= {'!'} else 0)
        out['priority'] = max(0, min(3, out['priority']))
        words = words[:m.start()] + ' ' + words[m.end():]
    m = re.search(r'(?<!\S)@([\w\-]+)', words)
    if m:
        out['list_name'] = m.group(1).replace('-', ' ')
        words = words[:m.start()] + ' ' + words[m.end():]
    day, time_, rule = None, None, ''

    def take(pattern):
        nonlocal words
        found = re.search(pattern, words, re.I)
        if found:
            words = words[:found.start()] + ' ' + words[found.end():]
        return found
    m = take(r'\bevery\s+(day|week|month|year|weekday|(?:' + '|'.join(k for k in WEEKDAYS if len(k) > 3) + r'))\b')
    if m:
        unit = m.group(1).lower()
        if unit in ('day', 'week', 'month', 'year'):
            rule = 'FREQ=' + {'day': 'DAILY', 'week': 'WEEKLY', 'month': 'MONTHLY', 'year': 'YEARLY'}[unit]
        elif unit == 'weekday':
            rule = 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR'
        else:
            rule = 'FREQ=WEEKLY;BYDAY=' + RRULE_DAYS[WEEKDAYS[unit]]
            day = _next_weekday(today, WEEKDAYS[unit], include_today=True)
    m = take(r'\b(\d{4})-(\d{2})-(\d{2})\b')
    if m:
        day = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if day is None:
        m = take(r'\b(today|tonight|tomorrow|tmrw|aujourd\'hui|demain|heute|morgen)\b')
        if m:
            w = m.group(1).lower()
            day = today + dt.timedelta(days=1 if w in ('tomorrow', 'tmrw', 'demain', 'morgen') else 0)
            if w == 'tonight':
                time_ = dt.time(20)
    if day is None:
        m = take(r'\bnext\s+week\b')
        if m:
            day = today + dt.timedelta(days=7 - today.weekday())
    if day is None:
        m = take(r'\bin\s+(\d{1,3})\s+(day|days|week|weeks|month|months)\b')
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            day = today + (dt.timedelta(days=n) if unit.startswith('day') else dt.timedelta(weeks=n)
                           if unit.startswith('week') else dt.timedelta(days=30 * n))
    if day is None:
        names = '|'.join(sorted(WEEKDAYS, key=len, reverse=True))
        m = take(r'\b(next\s+|this\s+|on\s+)?(' + names + r')\b')
        if m:
            target = WEEKDAYS[m.group(2).lower()]
            day = _next_weekday(today, target, include_today=bool(m.group(1) and 'this' in m.group(1).lower()))
            if m.group(1) and 'next' in m.group(1).lower() and day - today < dt.timedelta(days=7):
                day += dt.timedelta(days=7) if (day - today).days <= (6 - today.weekday()) else dt.timedelta(0)
    if day is None:
        months = '|'.join(sorted(MONTHS, key=len, reverse=True))
        m = take(r'\b(' + months + r')\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b') or None
        if m:
            day = _future_date(today, MONTHS[m.group(1).lower()], int(m.group(2)))
        else:
            m = take(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(' + months + r')\b')
            if m:
                day = _future_date(today, MONTHS[m.group(2).lower()], int(m.group(1)))
    if day is None:
        m = take(r'(?<![\d:])(\d{1,2})\.(\d{1,2})\.(\d{2,4})?(?!\d)')
        if m:
            year = int(m.group(3)) if m.group(3) else None
            if year is not None and year < 100:
                year += 2000
            day = _safe_date(year, int(m.group(2)), int(m.group(1))) if year else \
                _future_date(today, int(m.group(2)), int(m.group(1)))
    if day is None:
        m = take(r'(?<![\d:/])(\d{1,2})/(\d{1,2})(?!\d)')
        if m:
            day = _future_date(today, int(m.group(1)), int(m.group(2)))
    m = take(r'\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b') or None
    if m:
        hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'pm' else 0)
        time_ = dt.time(min(hour, 23), int(m.group(2) or 0))
    else:
        m = take(r'\b(?:at\s+)?([01]?\d|2[0-3])(?::|h)([0-5]\d)?\b(?!\s*(?:days?|weeks?|%))')
        if m:
            time_ = dt.time(int(m.group(1)), int(m.group(2) or 0))
        else:
            m = take(r'\bat\s+([01]?\d|2[0-3])\b')
            if m:
                hour = int(m.group(1))
                time_ = dt.time(hour + 12 if 1 <= hour <= 7 else hour)
    if time_ is not None and day is None:
        day = today if dt.datetime.combine(today, time_) > dt.datetime.now() or today != dt.date.today() \
            else today + dt.timedelta(days=1)
    if rule and day is None:
        day = today                         # a repeating task starts today unless a date was given
    if day is not None:
        out['due'] = due_text(dt.datetime.combine(day, time_) if time_ is not None else day)
    out['rrule'] = rule
    title = re.sub(r'\s+', ' ', words).strip(' ,;-')
    title = re.sub(r'\b(on|at|by|due)$', '', title, flags=re.I).strip(' ,;-')
    out['title'] = title or str(text or '').strip() or 'New task'
    return out


def _safe_date(year, month, day):
    try:
        return dt.date(year, month, day)
    except (TypeError, ValueError):
        return None


def _future_date(today: dt.date, month: int, day: int):
    found = _safe_date(today.year, month, day)
    if found is not None and found < today:
        found = _safe_date(today.year + 1, month, day)
    return found


def _next_weekday(today: dt.date, weekday: int, include_today: bool = False) -> dt.date:
    delta = (weekday - today.weekday()) % 7
    if delta == 0 and not include_today:
        delta = 7
    return today + dt.timedelta(days=delta)
