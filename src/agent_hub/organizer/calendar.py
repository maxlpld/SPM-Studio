"""Calendar store (Qt-free): several calendars with colours, events with recurrence, exceptions, overrides,
time zones and reminders; occurrences in a date range; search; free time; .ics import / export.

Event fields::

    uid, calendar, title, start, end      ISO wall time in ``tz`` ('2026-11-28T09:00:00'), or dates when all_day
    all_day, tz                           IANA name ('' = floating: the computer's own zone)
    rrule, exdates, rdates, overrides     RFC 5545 rule; excluded / extra starts; {instance start: changed fields}
    location, description, color          colour '' = the calendar's colour
    reminders                             minutes before the start (several per event)
    created_by                            user · assistant · todo · import · sync
    links                                 {'todo': task id, 'email': message id, 'chat': chat id}
    created, updated

Calendar fields: ``id, name, color, visible, kind (local · subscription · caldav · google · microsoft),
readonly, source {url, interval_min, account …}, order``.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import ics, rrule
from .base import RecordFile, new_id, now_ts

PALETTE = ['#4285F4', '#0B8043', '#D50000', '#F4511E', '#8E24AA', '#039BE5', '#E67C73', '#F6BF26', '#33B679',
           '#7986CB', '#616161', '#3F51B5']
EVENT_FIELDS = ('title', 'start', 'end', 'all_day', 'tz', 'rrule', 'exdates', 'rdates', 'overrides', 'location',
                'description', 'color', 'reminders', 'calendar', 'links', 'status', 'categories', 'url',
                'created_by', 'remote')


def parse_time(text: str):
    if isinstance(text, (dt.date, dt.datetime)):
        return text
    text = str(text or '').strip()
    if len(text) == 10:
        return dt.date.fromisoformat(text)
    value = dt.datetime.fromisoformat(text)
    return value.replace(tzinfo=None) if value.tzinfo is None else value.astimezone().replace(tzinfo=None)


def iso(value) -> str:
    if isinstance(value, dt.datetime):
        return value.replace(microsecond=0).isoformat(timespec='seconds')
    return value.isoformat()


def _zone(name):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def to_local(value: dt.datetime, tz: str) -> dt.datetime:
    """Wall time of ``tz`` → naive wall time of this computer's zone."""
    zone = _zone(tz)
    if zone is None:
        return value
    return value.replace(tzinfo=zone).astimezone().replace(tzinfo=None)


def from_local(value: dt.datetime, tz: str) -> dt.datetime:
    zone = _zone(tz)
    if zone is None:
        return value
    return value.astimezone().astimezone(zone).replace(tzinfo=None) if value.tzinfo is None else \
        value.astimezone(zone).replace(tzinfo=None)


def local_zone_name() -> str:
    try:
        import time as _t
        key = getattr(dt.datetime.now().astimezone().tzinfo, 'key', '')
        if key:
            return key
        link = Path('/etc/localtime')
        if link.is_symlink():
            target = str(link.resolve())
            if 'zoneinfo/' in target:
                return target.split('zoneinfo/', 1)[1]
        return _t.tzname[0] if _zone(_t.tzname[0]) else ''
    except Exception:
        return ''


class CalendarFile(RecordFile):
    collections = ('calendars', 'events')


class CalendarStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.file = CalendarFile(self.root / 'calendar.json')
        if not self.file.data['calendars']:
            self.add_calendar('Personal', PALETTE[0], save=False)
            self.add_calendar('Work', PALETTE[1], save=False)
            self.add_calendar('Tasks', PALETTE[4], save=False, kind='tasks')
            self.file.save()

    # ------------------------------------------------------------------ calendars
    def reload(self) -> bool:
        return self.file.reload()

    def calendars(self) -> list[dict]:
        self.file.reload()
        return sorted(self.file.data['calendars'].values(), key=lambda c: (c.get('order', 0), c['name'].lower()))

    def calendar(self, cid: str) -> dict | None:
        return self.file.data['calendars'].get(cid)

    def default_calendar(self, kind: str = 'local') -> dict:
        cals = [c for c in self.calendars() if not c.get('readonly')]
        found = next((c for c in cals if c.get('kind', 'local') == kind), None)
        if found is None and kind == 'tasks':
            found = self.add_calendar('Tasks', PALETTE[4], kind='tasks')
        return found or next((c for c in cals if c.get('kind', 'local') == 'local'), None) or \
            self.add_calendar('Personal', PALETTE[0])

    def add_calendar(self, name: str, color: str = '', kind: str = 'local', readonly: bool = False,
                     source: dict | None = None, save: bool = True) -> dict:
        n = len(self.file.data['calendars'])
        cal = {'id': new_id('k'), 'name': str(name or 'Calendar')[:80], 'color': color or PALETTE[n % len(PALETTE)],
               'visible': True, 'kind': kind, 'readonly': bool(readonly), 'source': dict(source or {}), 'order': n,
               'updated': now_ts()}
        self.file.data['calendars'][cal['id']] = cal
        if save:
            self.file.save()
        return cal

    def update_calendar(self, cid: str, **fields) -> dict:
        cal = self.file.data['calendars'][cid]
        for key in ('name', 'color', 'visible', 'readonly', 'source', 'order'):
            if key in fields:
                cal[key] = fields[key]
        cal['updated'] = now_ts()
        self.file.save()
        return cal

    def delete_calendar(self, cid: str):
        for uid in [u for u, e in self.file.data['events'].items() if e.get('calendar') == cid]:
            self.file.data['events'].pop(uid)
            self.file.tombstone(uid)
        self.file.data['calendars'].pop(cid, None)
        self.file.tombstone(cid)
        self.file.save()

    # ------------------------------------------------------------------ events
    def events(self, calendar: str | None = None) -> list[dict]:
        self.file.reload()
        return [e for e in self.file.data['events'].values() if calendar is None or e.get('calendar') == calendar]

    def get(self, uid: str) -> dict | None:
        self.file.reload()
        return self.file.data['events'].get(uid)

    def _clean(self, fields: dict, base: dict | None = None) -> dict:
        ev = dict(base or {'uid': '', 'title': 'Event', 'start': '', 'end': '', 'all_day': False, 'tz': '',
                           'rrule': '', 'exdates': [], 'rdates': [], 'overrides': {}, 'location': '',
                           'description': '', 'color': '', 'reminders': [], 'calendar': '', 'links': {},
                           'created_by': 'user', 'status': '', 'categories': [], 'url': ''})
        for key in EVENT_FIELDS:
            if key in fields:
                ev[key] = fields[key]
        ev['title'] = str(ev.get('title') or '(no title)')[:300]
        ev['all_day'] = bool(ev.get('all_day'))
        start = parse_time(ev['start']) if ev.get('start') else None
        if start is None:
            raise ValueError('An event needs a start')
        if ev['all_day']:
            start = start.date() if isinstance(start, dt.datetime) else start
            end = parse_time(ev['end']) if ev.get('end') else start + dt.timedelta(days=1)
            end = end.date() if isinstance(end, dt.datetime) else end
            if end <= start:
                end = start + dt.timedelta(days=1)
        else:
            if not isinstance(start, dt.datetime):
                start = dt.datetime.combine(start, dt.time(9))
            end = parse_time(ev['end']) if ev.get('end') else start + dt.timedelta(hours=1)
            if not isinstance(end, dt.datetime):
                end = dt.datetime.combine(end, start.time())
            if end <= start:
                end = start + dt.timedelta(minutes=30)
        ev['start'], ev['end'] = iso(start), iso(end)
        if ev.get('rrule'):
            rrule.parse(ev['rrule'])                     # raises on a malformed rule
        ev['reminders'] = sorted({max(0, int(m)) for m in (ev.get('reminders') or [])})[:10]
        ev['exdates'] = sorted({str(x) for x in ev.get('exdates') or []})
        ev['rdates'] = sorted({str(x) for x in ev.get('rdates') or []})
        if not ev.get('calendar') or ev['calendar'] not in self.file.data['calendars']:
            ev['calendar'] = self.default_calendar()['id']
        ev.pop('_sync', None)
        ev['links'] = {k: v for k, v in dict(ev.get('links') or {}).items() if v}
        return ev

    def create(self, fields: dict, created_by: str = 'user', save: bool = True) -> dict:
        self.file.reload()
        fields = dict(fields)
        from_sync = fields.pop('_sync', False)
        cal = self.calendar(fields.get('calendar', '')) if fields.get('calendar') else None
        if cal is not None and cal.get('readonly') and not from_sync:
            raise PermissionError(f"The calendar “{cal['name']}” is read-only")
        ev = self._clean(dict(fields, created_by=fields.get('created_by') or created_by))
        ev['uid'] = str(fields.get('uid') or new_id('e'))
        ev['created'] = ev['updated'] = now_ts()
        self.file.data['events'][ev['uid']] = ev
        if save:
            self.file.save()
        return ev

    def update(self, uid: str, save: bool = True, **fields) -> dict:
        self.file.reload()
        old = self.file.data['events'].get(uid)
        if old is None:
            raise KeyError(uid)
        cal = self.calendar(old.get('calendar', ''))
        if cal is not None and cal.get('readonly') and not fields.pop('_sync', False):
            raise PermissionError(f"The calendar “{cal['name']}” is read-only")
        fields.pop('_sync', None)
        ev = self._clean(fields, base=old)
        ev['uid'] = uid
        ev['created'] = old.get('created', now_ts())
        ev['updated'] = now_ts()
        ev['sequence'] = int(old.get('sequence', 0)) + 1
        self.file.data['events'][uid] = ev
        if save:
            self.file.save()
        return ev

    def delete(self, uid: str, save: bool = True) -> dict | None:
        self.file.reload()
        ev = self.file.data['events'].pop(uid, None)
        if ev is not None:
            self.file.tombstone(uid)
            if save:
                self.file.save()
        return ev

    def move(self, uid: str, new_start, new_end=None) -> dict:
        """Drag in the grid: keeps the duration unless ``new_end`` is given."""
        ev = self.get(uid)
        start, end = parse_time(ev['start']), parse_time(ev['end'])
        new_start = parse_time(new_start)
        if new_end is None:
            new_end = new_start + (end - start)
        return self.update(uid, start=iso(new_start), end=iso(parse_time(new_end)))

    # ---- one instance of a recurring event
    def delete_occurrence(self, uid: str, instance: str) -> dict:
        ev = self.get(uid)
        return self.update(uid, exdates=list(ev.get('exdates', [])) + [instance])

    def update_occurrence(self, uid: str, instance: str, **fields) -> dict:
        ev = self.get(uid)
        overrides = dict(ev.get('overrides') or {})
        changed = dict(overrides.get(instance) or {})
        for key in ('title', 'start', 'end', 'location', 'description', 'color', 'all_day'):
            if key in fields:
                changed[key] = iso(parse_time(fields[key])) if key in ('start', 'end') else fields[key]
        overrides[instance] = changed
        return self.update(uid, overrides=overrides)

    def split_series(self, uid: str, instance: str, **fields) -> dict:
        """"This and following events": end the series before ``instance`` and start a new one there."""
        ev = self.get(uid)
        rule = rrule.parse(ev['rrule'])
        first = parse_time(instance)
        rule['count'] = None
        rule['until'] = (first - dt.timedelta(seconds=1)) if isinstance(first, dt.datetime) else \
            first - dt.timedelta(days=1)
        self.update(uid, rrule=rrule.to_text(rule))
        duration = parse_time(ev['end']) - parse_time(ev['start'])
        new = {k: ev[k] for k in EVENT_FIELDS if k in ev and k not in ('overrides', 'exdates')}
        new.update(start=iso(first), end=iso(first + duration), **fields)
        new['links'] = {}
        return self.create(new, created_by=ev.get('created_by', 'user'))

    # ------------------------------------------------------------------ occurrences
    def occurrences(self, start, end, calendars=None, visible_only: bool = True) -> list[dict]:
        """Every instance overlapping ``[start, end)`` (naive local datetimes or dates), sorted by start."""
        start, end = parse_time(start), parse_time(end)
        if not isinstance(start, dt.datetime):
            start = dt.datetime.combine(start, dt.time())
        if not isinstance(end, dt.datetime):
            end = dt.datetime.combine(end, dt.time())
        cals = {c['id']: c for c in self.calendars()}
        out = []
        for ev in self.events():
            cal = cals.get(ev.get('calendar'))
            if cal is None or (calendars is not None and ev['calendar'] not in calendars):
                continue
            if visible_only and not cal.get('visible', True):
                continue
            out += self._instances(ev, cal, start, end)
        out.sort(key=lambda o: (not o['all_day'], o['start'], o['title'].lower()))
        return out

    def _instances(self, ev: dict, cal: dict, start: dt.datetime, end: dt.datetime) -> list[dict]:
        s0, e0 = parse_time(ev['start']), parse_time(ev['end'])
        duration = e0 - s0
        all_day = ev.get('all_day', False)
        tz = ev.get('tz', '')
        if all_day:
            w0, w1 = start.date() - duration, end.date()
        else:
            margin = dt.timedelta(hours=15)            # time-zone shifts
            w0, w1 = from_local(start, tz) - duration - margin, from_local(end, tz) + margin
        exdates = {parse_time(x) for x in ev.get('exdates', [])}
        rdates = [parse_time(x) for x in ev.get('rdates', [])]
        try:
            starts = rrule.occurrences(ev.get('rrule', ''), s0, w0, w1, exdates, rdates, limit=1500)
        except rrule.RRuleError:
            starts = [s0] if w0 <= s0 < w1 else []
        out = []
        overrides = ev.get('overrides') or {}
        for s in starts:
            key = iso(s)
            o = overrides.get(key) or {}
            os_, oe = parse_time(o['start']) if o.get('start') else s, \
                parse_time(o['end']) if o.get('end') else s + duration
            if all_day:
                ls, le = (os_ if not isinstance(os_, dt.datetime) else os_.date()), \
                    (oe if not isinstance(oe, dt.datetime) else oe.date())
                if not (dt.datetime.combine(ls, dt.time()) < end and dt.datetime.combine(le, dt.time()) > start):
                    continue
            else:
                ls, le = to_local(os_, tz), to_local(oe, tz)
                if not (ls < end and le > start):
                    continue
            out.append({'uid': ev['uid'], 'instance': key, 'recurring': bool(ev.get('rrule')) or bool(rdates),
                        'start': ls, 'end': le, 'all_day': all_day, 'title': o.get('title', ev['title']),
                        'location': o.get('location', ev.get('location', '')),
                        'description': o.get('description', ev.get('description', '')),
                        'color': o.get('color') or ev.get('color') or cal.get('color', PALETTE[0]),
                        'calendar': cal['id'], 'calendar_name': cal['name'], 'readonly': bool(cal.get('readonly')),
                        'reminders': list(ev.get('reminders', [])), 'created_by': ev.get('created_by', 'user'),
                        'links': dict(ev.get('links') or {}), 'tz': tz})
        return out

    def search(self, query: str, start=None, end=None, limit: int = 50) -> list[dict]:
        q = str(query or '').lower().strip()
        start = start or dt.datetime.now() - dt.timedelta(days=365)
        end = end or dt.datetime.now() + dt.timedelta(days=730)
        found = [o for o in self.occurrences(start, end, visible_only=False)
                 if not q or q in o['title'].lower() or q in o['location'].lower() or q in o['description'].lower()]
        return found[:limit]

    def free_slots(self, start, end, minutes: int = 60, day_start: int = 9, day_end: int = 18,
                   weekdays_only: bool = True, calendars=None) -> list[tuple[dt.datetime, dt.datetime]]:
        """Free intervals of at least ``minutes`` inside working hours (all-day events do not block)."""
        start, end = parse_time(start), parse_time(end)
        if not isinstance(start, dt.datetime):
            start = dt.datetime.combine(start, dt.time())
        if not isinstance(end, dt.datetime):
            end = dt.datetime.combine(end, dt.time())
        busy = sorted((o['start'], o['end']) for o in self.occurrences(start, end, calendars)
                      if not o['all_day'])
        slots = []
        day = start.date()
        while dt.datetime.combine(day, dt.time()) < end:
            if not (weekdays_only and day.weekday() >= 5):
                s = max(start, dt.datetime.combine(day, dt.time(day_start)))
                e = min(end, dt.datetime.combine(day, dt.time(day_end)) if day_end < 24 else
                        dt.datetime.combine(day + dt.timedelta(days=1), dt.time()))
                cursor = s
                for b0, b1 in busy:
                    if b1 <= cursor or b0 >= e:
                        continue
                    if (b0 - cursor).total_seconds() >= minutes * 60:
                        slots.append((cursor, b0))
                    cursor = max(cursor, b1)
                if (e - cursor).total_seconds() >= minutes * 60:
                    slots.append((cursor, e))
            day += dt.timedelta(days=1)
        return slots

    # ------------------------------------------------------------------ import / export
    def import_ics(self, text: str, calendar_id: str = '', name: str = '', created_by: str = 'import',
                   replace: bool = False) -> dict:
        """Add (or update by UID) the events of an .ics text; returns {'added', 'updated', 'calendar'}."""
        parsed = ics.parse_calendar(text, local_zone_name())
        cal = self.calendar(calendar_id) if calendar_id else None
        if cal is None:
            cal = self.add_calendar(name or parsed['name'] or 'Imported', parsed['color'] or '')
        if replace:
            for ev in self.events(cal['id']):
                self.delete(ev['uid'], save=False)
        added = updated = 0
        for ev in parsed['events']:
            fields = {k: ev[k] for k in EVENT_FIELDS if k in ev}
            fields['calendar'] = cal['id']
            existing = self.file.data['events'].get(ev['uid'])
            try:
                if existing is not None and existing.get('calendar') == cal['id']:
                    self.update(ev['uid'], save=False, _sync=True, **fields)
                    updated += 1
                else:
                    uid = ev['uid'] if existing is None else new_id('e')
                    self.create(dict(fields, uid=uid, _sync=created_by == 'sync'),
                                created_by=ev.get('created_by') or created_by, save=False)
                    added += 1
            except (ValueError, PermissionError):
                continue
        self.file.save()
        return {'added': added, 'updated': updated, 'calendar': cal['id'], 'todos': parsed['todos']}

    def export_ics(self, calendar_ids=None) -> str:
        cals = [c for c in self.calendars() if calendar_ids is None or c['id'] in calendar_ids]
        events = [e for e in self.events() if e.get('calendar') in {c['id'] for c in cals}]
        name = cals[0]['name'] if len(cals) == 1 else 'Agent Hub calendars'
        return ics.to_ics(events, name=name, color=cals[0]['color'] if len(cals) == 1 else '')
