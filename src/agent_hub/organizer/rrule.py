"""RFC 5545 recurrence rules (Qt-free, standard library only).

Supported: ``FREQ`` (DAILY, WEEKLY, MONTHLY, YEARLY), ``INTERVAL``, ``COUNT``, ``UNTIL``, ``BYDAY`` (with
ordinals such as ``2MO`` or ``-1FR`` for monthly / yearly rules), ``BYMONTHDAY`` (negative counts from the end
of the month), ``BYMONTH``, ``BYSETPOS`` and ``WKST``. Exceptions (``EXDATE``) and extra dates (``RDATE``) are
applied by :func:`occurrences`.

Everything works on *wall-clock* datetimes of the event's own time zone (naive ``datetime``) or on ``date``
for all-day events, as iCalendar does; the calendar converts to the viewer's zone afterwards.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt

DAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
FREQS = ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY')
MAX_STEPS = 50_000            # periods examined at most (a malformed rule can never hang the app)


class RRuleError(ValueError):
    pass


def parse(text: str) -> dict:
    """``'FREQ=WEEKLY;BYDAY=MO,WE'`` (with or without ``RRULE:``) → dict with typed values."""
    text = (text or '').strip()
    if text.upper().startswith('RRULE:'):
        text = text[6:]
    rule = {'freq': '', 'interval': 1, 'count': None, 'until': None, 'byday': [], 'bymonthday': [],
            'bymonth': [], 'bysetpos': [], 'wkst': 'MO'}
    for part in filter(None, text.split(';')):
        if '=' not in part:
            raise RRuleError(f'Bad rule part {part!r}')
        key, value = part.split('=', 1)
        key = key.strip().upper()
        value = value.strip()
        try:
            if key == 'FREQ':
                if value.upper() not in FREQS:
                    raise RRuleError(f'Unsupported frequency {value}')
                rule['freq'] = value.upper()
            elif key == 'INTERVAL':
                rule['interval'] = max(1, int(value))
            elif key == 'COUNT':
                rule['count'] = max(1, int(value))
            elif key == 'UNTIL':
                rule['until'] = parse_ical_datetime(value)
            elif key == 'BYDAY':
                days = []
                for item in value.split(','):
                    item = item.strip().upper()
                    if len(item) < 2 or item[-2:] not in DAYS:
                        raise RRuleError(f'Bad BYDAY {item}')
                    n = int(item[:-2]) if item[:-2] not in ('', '+') else 0
                    days.append((n, DAYS.index(item[-2:])))
                rule['byday'] = days
            elif key == 'BYMONTHDAY':
                rule['bymonthday'] = [int(x) for x in value.split(',') if x.strip()]
            elif key == 'BYMONTH':
                rule['bymonth'] = [int(x) for x in value.split(',') if x.strip()]
            elif key == 'BYSETPOS':
                rule['bysetpos'] = [int(x) for x in value.split(',') if x.strip()]
            elif key == 'WKST':
                rule['wkst'] = value.upper() if value.upper() in DAYS else 'MO'
            # other parts (BYHOUR, BYMINUTE …) are kept by the ICS layer but ignored here
        except ValueError as exc:
            if isinstance(exc, RRuleError):
                raise
            raise RRuleError(f'Bad value in {part!r}') from None
    if not rule['freq']:
        raise RRuleError('The rule has no FREQ')
    return rule


def to_text(rule: dict) -> str:
    """Inverse of :func:`parse` (canonical order)."""
    parts = [f"FREQ={rule['freq']}"]
    if rule.get('interval', 1) != 1:
        parts.append(f"INTERVAL={rule['interval']}")
    if rule.get('count'):
        parts.append(f"COUNT={rule['count']}")
    if rule.get('until'):
        parts.append('UNTIL=' + format_ical(rule['until']))
    if rule.get('byday'):
        parts.append('BYDAY=' + ','.join((str(n) if n else '') + DAYS[d] for n, d in rule['byday']))
    if rule.get('bymonthday'):
        parts.append('BYMONTHDAY=' + ','.join(map(str, rule['bymonthday'])))
    if rule.get('bymonth'):
        parts.append('BYMONTH=' + ','.join(map(str, rule['bymonth'])))
    if rule.get('bysetpos'):
        parts.append('BYSETPOS=' + ','.join(map(str, rule['bysetpos'])))
    if rule.get('wkst', 'MO') != 'MO':
        parts.append('WKST=' + rule['wkst'])
    return ';'.join(parts)


def parse_ical_datetime(value: str):
    """``20261128`` → date, ``20261128T093000`` / ``…Z`` → datetime (a trailing Z gives an aware UTC value)."""
    value = value.strip()
    if 'T' not in value:
        return dt.datetime.strptime(value[:8], '%Y%m%d').date()
    utc = value.endswith('Z')
    base = dt.datetime.strptime(value.rstrip('Z')[:15], '%Y%m%dT%H%M%S')
    return base.replace(tzinfo=dt.timezone.utc) if utc else base


def format_ical(value) -> str:
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            return value.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        return value.strftime('%Y%m%dT%H%M%S')
    return value.strftime('%Y%m%d')


# ---------------------------------------------------------------------------------------------- expansion
def _month_days(year: int, month: int) -> int:
    return _cal.monthrange(year, month)[1]


def _nth_weekdays(year: int, month: int, n: int, weekday: int) -> list[dt.date]:
    days = [dt.date(year, month, d) for d in range(1, _month_days(year, month) + 1)
            if dt.date(year, month, d).weekday() == weekday]
    if n == 0:
        return days
    try:
        return [days[n - 1] if n > 0 else days[n]]
    except IndexError:
        return []


def _year_nth_weekdays(year: int, n: int, weekday: int) -> list[dt.date]:
    first = dt.date(year, 1, 1)
    days = [first + dt.timedelta(d) for d in range(366 if _cal.isleap(year) else 365)
            if (first + dt.timedelta(d)).weekday() == weekday]
    if n == 0:
        return days
    try:
        return [days[n - 1] if n > 0 else days[n]]
    except IndexError:
        return []


def _candidates(rule: dict, start: dt.date, period: int) -> list[dt.date]:
    """Dates of one period (the ``period``-th day / week / month / year after ``start``)."""
    freq, step = rule['freq'], rule['interval'] * period
    byday, bymonthday, bymonth = rule['byday'], rule['bymonthday'], rule['bymonth']
    if freq == 'DAILY':
        day = start + dt.timedelta(days=step)
        out = [day]
    elif freq == 'WEEKLY':
        wkst = DAYS.index(rule.get('wkst', 'MO'))
        week_start = start - dt.timedelta(days=(start.weekday() - wkst) % 7) + dt.timedelta(weeks=step)
        if byday:
            out = sorted(week_start + dt.timedelta(days=(d - wkst) % 7) for _n, d in byday)
        else:
            out = [week_start + dt.timedelta(days=(start.weekday() - wkst) % 7)]
    elif freq == 'MONTHLY':
        months = start.year * 12 + start.month - 1 + step
        year, month = divmod(months, 12)
        month += 1
        out = _month_set(rule, year, month, start)
    else:  # YEARLY
        year = start.year + step
        out = []
        if bymonth:
            for m in bymonth:
                if 1 <= m <= 12:
                    out += _month_set(rule, year, m, start, yearly=True)
        elif byday and not bymonthday:
            for n, d in byday:
                out += _year_nth_weekdays(year, n, d)
        elif bymonthday:
            out += _month_set(rule, year, start.month, start, yearly=True)
        else:
            try:
                out = [start.replace(year=year)]
            except ValueError:            # 29 February in a common year: skipped, as RFC 5545 says
                out = []
    if bymonth and freq in ('DAILY', 'WEEKLY', 'MONTHLY'):
        out = [d for d in out if d.month in bymonth]
    if byday and freq == 'DAILY':
        out = [d for d in out if d.weekday() in {w for _n, w in byday}]
    if bymonthday and freq in ('DAILY', 'WEEKLY'):
        out = [d for d in out if _matches_monthday(d, bymonthday)]
    out = sorted(set(out))
    if rule['bysetpos'] and out:
        picked = []
        for pos in rule['bysetpos']:
            try:
                picked.append(out[pos - 1] if pos > 0 else out[pos])
            except IndexError:
                pass
        out = sorted(set(picked))
    return out


def _matches_monthday(day: dt.date, monthdays: list[int]) -> bool:
    last = _month_days(day.year, day.month)
    return any(day.day == (m if m > 0 else last + 1 + m) for m in monthdays)


def _month_set(rule: dict, year: int, month: int, start: dt.date, yearly: bool = False) -> list[dt.date]:
    byday, bymonthday = rule['byday'], rule['bymonthday']
    last = _month_days(year, month)
    if bymonthday:
        days = []
        for m in bymonthday:
            d = m if m > 0 else last + 1 + m
            if 1 <= d <= last:
                days.append(dt.date(year, month, d))
        if byday:
            days = [d for d in days if d.weekday() in {w for _n, w in byday}]
        return days
    if byday:
        out = []
        for n, d in byday:
            out += _nth_weekdays(year, month, n, d)
        return out
    if start.day <= last:                 # 31st in a 30-day month: skipped (RFC 5545)
        return [dt.date(year, month, start.day)]
    return []


def expand(rule, dtstart, window_start=None, window_end=None, limit: int = 2000) -> list:
    """Occurrence starts of ``rule`` (text or parsed) from ``dtstart`` (date or naive datetime), limited to
    ``[window_start, window_end)`` when given. ``dtstart`` is always the first occurrence (RFC 5545)."""
    rule = parse(rule) if isinstance(rule, str) else rule
    is_dt = isinstance(dtstart, dt.datetime)
    start_date = dtstart.date() if is_dt else dtstart
    time_part = dtstart.time() if is_dt else None
    until = rule.get('until')
    if until is not None:
        if is_dt and not isinstance(until, dt.datetime):
            until = dt.datetime.combine(until, dt.time(23, 59, 59))
        elif not is_dt and isinstance(until, dt.datetime):
            until = until.date()
        if is_dt and isinstance(until, dt.datetime) and until.tzinfo is not None:
            until = until.astimezone().replace(tzinfo=None)
    out, count = [], 0
    first = [dt.datetime.combine(d, time_part) if is_dt else d for d in _candidates(rule, start_date, 0)]
    if dtstart not in first:               # DTSTART is always the first instance and counts (RFC 5545)
        count = 1
        if (window_start is None or dtstart >= window_start) and (window_end is None or dtstart < window_end):
            out.append(dtstart)
    for period in range(MAX_STEPS):
        days = _candidates(rule, start_date, period)
        stop = False
        for day in days:
            value = dt.datetime.combine(day, time_part) if is_dt else day
            if value <= dtstart and (value < dtstart or count):
                continue
            if until is not None and value > until:
                stop = True
                break
            count += 1
            if rule.get('count') and count > rule['count']:
                stop = True
                break
            if window_end is not None and value >= window_end:
                stop = True
                break
            if window_start is None or value >= window_start:
                out.append(value)
                if len(out) >= limit:
                    return out
        if stop:
            break
        if window_end is not None and days and (dt.datetime.combine(days[-1], time_part) if is_dt
                                                else days[-1]) >= window_end:
            break
    return out


def occurrences(rrule_text: str, dtstart, window_start=None, window_end=None, exdates=(), rdates=(),
                limit: int = 2000) -> list:
    """Starts after exceptions (``exdates``) and extra dates (``rdates``), sorted and unique."""
    if rrule_text:
        starts = expand(rrule_text, dtstart, window_start, window_end, limit)
    else:
        starts = [dtstart] if (window_start is None or dtstart >= window_start) and \
            (window_end is None or dtstart < window_end) else []
    for r in rdates:
        if (window_start is None or r >= window_start) and (window_end is None or r < window_end):
            starts.append(r)
    excluded = set(exdates)
    return sorted({s for s in starts if s not in excluded})


def describe(rrule_text: str) -> str:
    """Short human summary: 'Every 2 weeks on Mon, Wed · 10 times'."""
    if not rrule_text:
        return 'Does not repeat'
    try:
        r = parse(rrule_text)
    except RRuleError:
        return 'Custom'
    unit = {'DAILY': 'day', 'WEEKLY': 'week', 'MONTHLY': 'month', 'YEARLY': 'year'}[r['freq']]
    text = f'Every {unit}' if r['interval'] == 1 else f"Every {r['interval']} {unit}s"
    names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    if r['byday']:
        ords = {1: 'first', 2: 'second', 3: 'third', 4: 'fourth', -1: 'last'}
        text += ' on ' + ', '.join((ords.get(n, str(n)) + ' ' if n else '') + names[d] for n, d in r['byday'])
    if r['bymonthday']:
        text += ' on day ' + ', '.join(map(str, r['bymonthday']))
    if r['count']:
        text += f" · {r['count']} times"
    if r['until']:
        text += ' · until ' + (r['until'].date() if isinstance(r['until'], dt.datetime) else r['until']).isoformat()
    return text
