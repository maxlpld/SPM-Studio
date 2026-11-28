"""iCalendar (.ics, RFC 5545) import and export for the calendar (Qt-free, standard library only).

Reads ``VEVENT`` (summary, start/end or duration, all-day dates, ``TZID``, UTC ``Z`` times, ``RRULE``,
``EXDATE``, ``RDATE``, ``RECURRENCE-ID`` overrides, location, description, ``VALARM`` display reminders,
``CATEGORIES``, colour) and ``VTODO`` (as to-do candidates). Writes the same, with folded lines and escaping,
so an export → import round trip keeps every field the calendar uses.
"""
from __future__ import annotations

import datetime as dt
import re
import uuid

from . import rrule

PRODID = '-//Agent Hub//Calendar 1.0//EN'


# ------------------------------------------------------------------------------------------------ lines
def unfold(text: str) -> list[str]:
    lines = []
    for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if raw.startswith((' ', '\t')) and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def fold(line: str) -> str:
    """Lines longer than 75 octets are folded (continuation lines start with one space)."""
    out, current = [], b''
    for ch in line:
        b = ch.encode('utf8')
        if len(current) + len(b) > (75 if not out else 74):
            out.append(current.decode('utf8'))
            current = b
        else:
            current += b
    out.append(current.decode('utf8'))
    return '\r\n '.join(out)


def escape(text: str) -> str:
    return (str(text).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\r\n', '\\n').replace('\n', '\\n'))


def unescape(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == '\\' and i + 1 < len(text):
            n = text[i + 1]
            out.append('\n' if n in 'nN' else n)
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


_PARAM = re.compile(r'^([A-Za-z0-9-]+)((?:;[^:;]+=(?:"[^"]*"|[^:;]*))*):(.*)$')


def parse_line(line: str):
    """``DTSTART;TZID=Europe/Zurich:20261128T090000`` → ('DTSTART', {'TZID': 'Europe/Zurich'}, '2026…')."""
    m = _PARAM.match(line)
    if not m:
        return None
    name, params_text, value = m.group(1).upper(), m.group(2), m.group(3)
    params = {}
    for p in re.findall(r';([^=;:]+)=("[^"]*"|[^;:]*)', params_text):
        params[p[0].upper()] = p[1].strip('"')
    return name, params, value


# ------------------------------------------------------------------------------------------------ times
def _zone(name: str):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def to_model_time(value: str, params: dict, default_tz: str = ''):
    """iCalendar value → (iso string, tz name, all_day)."""
    if params.get('VALUE', '').upper() == 'DATE' or (len(value) == 8 and value.isdigit()):
        return rrule.parse_ical_datetime(value).isoformat(), '', True
    parsed = rrule.parse_ical_datetime(value)
    tz = params.get('TZID', '')
    if parsed.tzinfo is not None:                         # UTC: keep it in the calendar's zone
        target = _zone(default_tz)
        local = parsed.astimezone(target) if target else parsed.astimezone()
        return local.replace(tzinfo=None).isoformat(timespec='seconds'), default_tz, False
    if tz and _zone(tz) is None:                           # unknown TZID (Windows names …): floating
        tz = ''
    return parsed.isoformat(timespec='seconds'), tz, False


def _duration(text: str) -> dt.timedelta:
    m = re.fullmatch(r'([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', text.strip())
    if not m:
        return dt.timedelta(0)
    sign = -1 if m.group(1) == '-' else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def _format_duration(minutes: int) -> str:
    sign = '-' if minutes > 0 else ''
    minutes = abs(int(minutes))
    if minutes and minutes % 1440 == 0:
        return f'{sign}P{minutes // 1440}D'
    if minutes and minutes % 60 == 0:
        return f'{sign}PT{minutes // 60}H'
    return f'{sign}PT{minutes}M'


# ------------------------------------------------------------------------------------------------ import
def parse_calendar(text: str, default_tz: str = '') -> dict:
    """``{'name', 'color', 'events': [...], 'todos': [...]}`` (events in the calendar's model)."""
    lines = unfold(text)
    events, todos, stack, current, alarm = [], [], [], None, None
    name, color = '', ''
    for line in lines:
        parsed = parse_line(line)
        if parsed is None:
            continue
        key, params, value = parsed
        if key == 'BEGIN':
            stack.append(value.upper())
            if value.upper() in ('VEVENT', 'VTODO'):
                current = {'_kind': value.upper(), '_props': []}
            elif value.upper() == 'VALARM' and current is not None:
                alarm = {}
            continue
        if key == 'END':
            kind = stack.pop() if stack else ''
            if kind == 'VALARM' and current is not None and alarm is not None:
                current.setdefault('_alarms', []).append(alarm)
                alarm = None
            elif kind in ('VEVENT', 'VTODO') and current is not None:
                (events if kind == 'VEVENT' else todos).append(current)
                current = None
            continue
        if alarm is not None:
            alarm[key] = (params, value)
            continue
        if current is not None:
            current['_props'].append((key, params, value))
        elif stack and stack[-1] == 'VCALENDAR':
            if key == 'X-WR-CALNAME':
                name = unescape(value)
            elif key in ('X-APPLE-CALENDAR-COLOR', 'COLOR'):
                color = value
    return {'name': name, 'color': color,
            'events': _merge_overrides([e for e in (_event(c, default_tz) for c in events) if e]),
            'todos': [t for t in (_todo(c) for c in todos) if t]}


def _event(raw: dict, default_tz: str) -> dict | None:
    ev = {'uid': '', 'title': '', 'start': '', 'end': '', 'all_day': False, 'tz': '', 'rrule': '',
          'exdates': [], 'rdates': [], 'location': '', 'description': '', 'color': '', 'reminders': [],
          'categories': [], 'status': '', 'recurrence_id': '', 'sequence': 0, 'url': ''}
    duration = None
    for key, params, value in raw['_props']:
        if key == 'UID':
            ev['uid'] = value.strip()
        elif key == 'SUMMARY':
            ev['title'] = unescape(value)
        elif key == 'DTSTART':
            ev['start'], ev['tz'], ev['all_day'] = to_model_time(value, params, default_tz)
        elif key == 'DTEND':
            ev['end'] = to_model_time(value, params, default_tz)[0]
        elif key == 'DURATION':
            duration = _duration(value)
        elif key == 'RRULE':
            try:
                rrule.parse(value)
                ev['rrule'] = value.strip()
            except rrule.RRuleError:
                ev['rrule'] = ''
        elif key in ('EXDATE', 'RDATE'):
            for part in value.split(','):
                if part.strip():
                    ev['exdates' if key == 'EXDATE' else 'rdates'].append(
                        to_model_time(part.strip(), params, default_tz)[0])
        elif key == 'RECURRENCE-ID':
            ev['recurrence_id'] = to_model_time(value, params, default_tz)[0]
        elif key == 'LOCATION':
            ev['location'] = unescape(value)
        elif key == 'DESCRIPTION':
            ev['description'] = unescape(value)
        elif key in ('COLOR', 'X-AGENT-HUB-COLOR'):
            ev['color'] = value.strip()
        elif key == 'CATEGORIES':
            ev['categories'] += [unescape(c).strip() for c in re.split(r'(?<!\\),', value) if c.strip()]
        elif key == 'STATUS':
            ev['status'] = value.strip().upper()
        elif key == 'SEQUENCE':
            try:
                ev['sequence'] = int(value)
            except ValueError:
                pass
        elif key == 'URL':
            ev['url'] = value.strip()
        elif key == 'X-AGENT-HUB-LINKS':
            try:
                import json
                ev['links'] = json.loads(unescape(value))
            except ValueError:
                pass
        elif key == 'X-AGENT-HUB-CREATED-BY':
            ev['created_by'] = value.strip()
    if not ev['start']:
        return None
    for alarm in raw.get('_alarms', []):
        trigger = alarm.get('TRIGGER')
        if trigger and trigger[0].get('VALUE', '').upper() != 'DATE-TIME':
            minutes = -int(_duration(trigger[1]).total_seconds() // 60)
            if minutes >= 0 and minutes not in ev['reminders']:
                ev['reminders'].append(minutes)
    ev['reminders'].sort()
    if not ev['end']:
        start = _parse_iso(ev['start'])
        if duration is not None:
            ev['end'] = _iso(start + duration, ev['all_day'])
        else:
            ev['end'] = _iso(start + (dt.timedelta(days=1) if ev['all_day'] else dt.timedelta(0)), ev['all_day'])
    ev['uid'] = ev['uid'] or ('imported-' + uuid.uuid4().hex)
    return ev


def _merge_overrides(events: list[dict]) -> list[dict]:
    """``RECURRENCE-ID`` instances become overrides of their series (or stay alone without one)."""
    series = {e['uid']: e for e in events if not e['recurrence_id']}
    out = list(series.values())
    for e in events:
        if not e['recurrence_id']:
            continue
        parent = series.get(e['uid'])
        if parent is None:
            e = dict(e, recurrence_id='')
            out.append(e)
            continue
        fields = {k: e[k] for k in ('title', 'start', 'end')}
        for k in ('location', 'description', 'color'):              # only what the instance changes
            if e.get(k) and e[k] != parent.get(k):
                fields[k] = e[k]
        if e.get('all_day') != parent.get('all_day'):
            fields['all_day'] = e.get('all_day')
        if e.get('status') == 'CANCELLED':
            parent['exdates'].append(e['recurrence_id'])
        else:
            parent.setdefault('overrides', {})[e['recurrence_id']] = fields
    return out


def _todo(raw: dict) -> dict | None:
    t = {'uid': '', 'title': '', 'due': '', 'notes': '', 'done': False, 'priority': 0, 'rrule': ''}
    for key, params, value in raw['_props']:
        if key == 'UID':
            t['uid'] = value.strip()
        elif key == 'SUMMARY':
            t['title'] = unescape(value)
        elif key == 'DUE':
            t['due'] = to_model_time(value, params)[0]
        elif key == 'DESCRIPTION':
            t['notes'] = unescape(value)
        elif key == 'STATUS':
            t['done'] = value.strip().upper() == 'COMPLETED'
        elif key == 'PRIORITY':
            try:
                p = int(value)
                t['priority'] = 3 if 1 <= p <= 4 else 2 if p == 5 else 1 if p >= 6 else 0
            except ValueError:
                pass
        elif key == 'RRULE':
            t['rrule'] = value.strip()
    return t if t['title'] else None


def _parse_iso(text: str):
    return dt.date.fromisoformat(text) if len(text) == 10 else dt.datetime.fromisoformat(text)


def _iso(value, all_day: bool) -> str:
    if all_day:
        return (value.date() if isinstance(value, dt.datetime) else value).isoformat()
    return value.isoformat(timespec='seconds')


# ------------------------------------------------------------------------------------------------ export
def _time_prop(name: str, iso: str, tz: str, all_day: bool) -> str:
    value = _parse_iso(iso)
    if all_day:
        day = value.date() if isinstance(value, dt.datetime) else value
        return f'{name};VALUE=DATE:{day.strftime("%Y%m%d")}'
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        value = dt.datetime.combine(value, dt.time())
    if tz and _zone(tz) is not None:
        return f'{name};TZID={tz}:{value.strftime("%Y%m%dT%H%M%S")}'
    return f'{name}:{value.strftime("%Y%m%dT%H%M%S")}'


def event_lines(ev: dict, stamp: str | None = None) -> list[str]:
    import json
    stamp = stamp or dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VEVENT', f"UID:{ev['uid']}", f'DTSTAMP:{stamp}',
             _time_prop('DTSTART', ev['start'], ev.get('tz', ''), ev.get('all_day', False)),
             _time_prop('DTEND', ev['end'] or ev['start'], ev.get('tz', ''), ev.get('all_day', False)),
             'SUMMARY:' + escape(ev.get('title', ''))]
    if ev.get('sequence'):
        lines.append(f"SEQUENCE:{int(ev['sequence'])}")
    if ev.get('rrule'):
        lines.append('RRULE:' + ev['rrule'])
    for x in ev.get('exdates', []):
        lines.append(_time_prop('EXDATE', x, ev.get('tz', ''), len(x) == 10))
    for x in ev.get('rdates', []):
        lines.append(_time_prop('RDATE', x, ev.get('tz', ''), len(x) == 10))
    for key, prop in (('location', 'LOCATION'), ('description', 'DESCRIPTION')):
        if ev.get(key):
            lines.append(f'{prop}:' + escape(ev[key]))
    if ev.get('color'):
        lines.append('X-AGENT-HUB-COLOR:' + ev['color'])
    if ev.get('categories'):
        lines.append('CATEGORIES:' + ','.join(escape(c) for c in ev['categories']))
    if ev.get('status'):
        lines.append('STATUS:' + ev['status'])
    if ev.get('url'):
        lines.append('URL:' + ev['url'])
    if ev.get('links'):
        lines.append('X-AGENT-HUB-LINKS:' + escape(json.dumps(ev['links'], sort_keys=True)))
    if ev.get('created_by'):
        lines.append('X-AGENT-HUB-CREATED-BY:' + ev['created_by'])
    for minutes in ev.get('reminders', []):
        lines += ['BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + escape(ev.get('title', 'Reminder')),
                  'TRIGGER:' + (_format_duration(int(minutes)) if minutes else 'PT0M'), 'END:VALARM']
    lines.append('END:VEVENT')
    for rid, fields in sorted((ev.get('overrides') or {}).items()):
        o = dict(ev, **fields)
        lines += ['BEGIN:VEVENT', f"UID:{ev['uid']}", f'DTSTAMP:{stamp}',
                  _time_prop('RECURRENCE-ID', rid, ev.get('tz', ''), len(rid) == 10),
                  _time_prop('DTSTART', o['start'], ev.get('tz', ''), o.get('all_day', False)),
                  _time_prop('DTEND', o['end'] or o['start'], ev.get('tz', ''), o.get('all_day', False)),
                  'SUMMARY:' + escape(o.get('title', ''))]
        for key, prop in (('location', 'LOCATION'), ('description', 'DESCRIPTION')):
            if fields.get(key):
                lines.append(f'{prop}:' + escape(fields[key]))
        if fields.get('color'):
            lines.append('X-AGENT-HUB-COLOR:' + fields['color'])
        lines.append('END:VEVENT')
    return lines


def to_ics(events: list[dict], name: str = '', color: str = '') -> str:
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:' + PRODID, 'CALSCALE:GREGORIAN']
    if name:
        lines.append('X-WR-CALNAME:' + escape(name))
    if color:
        lines.append('X-APPLE-CALENDAR-COLOR:' + color)
    for ev in events:
        lines += event_lines(ev)
    lines.append('END:VCALENDAR')
    return '\r\n'.join(fold(line) for line in lines) + '\r\n'
