"""Calendar subscriptions and two-way sync (Qt-free; network calls — run from a worker thread).

* **Subscription** (read-only): an iCal / webcal URL fetched every ``interval_min`` minutes; the calendar is
  replaced by the feed's events (local edits are refused: the calendar is read-only).
* **CalDAV** (iCloud, Nextcloud, Fastmail, a university server …): user name + app password (keyring
  ``caldav:<calendar id>``). Pull: ``REPORT calendar-query`` → events by UID with ETag. Push: events changed
  here since the last sync → ``PUT`` (``If-Match`` the ETag); deleted here → ``DELETE``.
* **Google Calendar** and **Microsoft 365 / Outlook**: OAuth with the user's own client id (``oauth.py``);
  the same pull / push over their REST APIs.

Conflicts: when an event changed on both sides since the last sync, the server's version wins and the local
version is kept as a copy (“… (conflict copy)”), so nothing is lost silently. Sync never sends invitations
(attendees are never written).
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import time
import uuid
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from . import ics, secrets
from .base import now_ts
from .calendar import CalendarStore, iso, local_zone_name, parse_time

DAV = '{DAV:}'
CAL = '{urn:ietf:params:xml:ns:caldav}'
CALDAV_PRESETS = {'icloud': 'https://caldav.icloud.com/', 'fastmail': 'https://caldav.fastmail.com/',
                  'nextcloud': 'https://<server>/remote.php/dav/', 'custom': ''}


def normalize_url(url: str) -> str:
    url = str(url or '').strip()
    if url.lower().startswith('webcal://'):
        url = 'https://' + url[9:]
    parts = urlparse(url)
    if parts.scheme not in ('https', 'http') or not parts.hostname:
        raise ValueError('Enter an https:// (or webcal://) address')
    if parts.scheme == 'http' and parts.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Only https:// addresses are accepted (http only for this computer)')
    return url


def _fetch(url: str, headers: dict | None = None, method: str = 'GET', data: bytes | None = None,
           timeout: int = 45) -> tuple[int, dict, bytes]:
    req = Request(url, data=data, method=method, headers={'User-Agent': 'AgentHub-Calendar/1.0', **(headers or {})})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read(10 * 2 ** 20)
    except Exception as exc:
        code = getattr(exc, 'code', 0)
        if code:
            return code, dict(getattr(exc, 'headers', {}) or {}), b''
        raise


# ------------------------------------------------------------------------------------------ subscriptions
def subscribe(store: CalendarStore, url: str, name: str = '', interval_min: int = 360, color: str = '') -> dict:
    url = normalize_url(url)
    cal = store.add_calendar(name or urlparse(url).hostname or 'Subscription', color, kind='subscription',
                             readonly=True, source={'url': url, 'interval_min': max(15, int(interval_min)),
                                                    'last_sync': 0, 'last_error': ''})
    return cal


def refresh_subscription(store: CalendarStore, cid: str) -> dict:
    cal = store.calendar(cid)
    if cal is None or cal.get('kind') != 'subscription':
        raise KeyError(cid)
    source = dict(cal.get('source') or {})
    try:
        status, _h, body = _fetch(source['url'])
        if status != 200:
            raise RuntimeError(f'HTTP {status}')
        text = body.decode('utf8', 'replace')
        if 'BEGIN:VCALENDAR' not in text:
            raise RuntimeError('The address did not return a calendar (.ics)')
        result = store.import_ics(text, calendar_id=cid, created_by='sync', replace=True)
        source.update(last_sync=time.time(), last_error='', events=result['added'] + result['updated'])
    except Exception as exc:
        source.update(last_error=secrets.redact(str(exc))[:200], last_attempt=time.time())
        store.update_calendar(cid, source=source)
        raise
    store.update_calendar(cid, source=source)
    return {'events': source['events']}


def due_subscriptions(store: CalendarStore, now: float | None = None) -> list[str]:
    now = now or time.time()
    out = []
    for c in store.calendars():
        if c.get('kind') == 'subscription':
            s = c.get('source') or {}
            last = max(float(s.get('last_sync') or 0), float(s.get('last_attempt') or 0))
            if now - last >= 60 * int(s.get('interval_min') or 360):
                out.append(c['id'])
    return out


# ------------------------------------------------------------------------------------------ two-way core
class RemoteCalendar:
    """Interface of a two-way remote: ``list() -> {remote_id: (etag, event dict)}``, ``put(event, remote_id,
    etag) -> (remote_id, etag)``, ``delete(remote_id, etag)``."""

    def list(self) -> dict:
        raise NotImplementedError

    def put(self, event: dict, remote_id: str = '', etag: str = '') -> tuple[str, str]:
        raise NotImplementedError

    def delete(self, remote_id: str, etag: str = ''):
        raise NotImplementedError


def two_way(store: CalendarStore, cid: str, remote: RemoteCalendar) -> dict:
    """One synchronisation of calendar ``cid`` with ``remote``. Returns counts."""
    cal = store.calendar(cid)
    source = dict(cal.get('source') or {})
    last = float(source.get('last_sync') or 0)
    known = dict(source.get('known') or {})            # remote id → {uid, etag}
    counts = {'pulled': 0, 'pushed': 0, 'deleted_here': 0, 'deleted_there': 0, 'conflicts': 0}
    remote_items = remote.list()
    local = {e['uid']: e for e in store.events(cid)}
    by_remote = {(e.get('remote') or {}).get('id'): e for e in local.values() if (e.get('remote') or {}).get('id')}
    pulled = set()
    # ---- deleted here since the last sync: delete on the server first (so the pull does not bring them back)
    deleted = store.file.data['deleted']
    for rid, info in list(known.items()):
        if info.get('uid') in deleted and info.get('uid') not in local:
            try:
                remote.delete(rid, info.get('etag', ''))
                counts['deleted_there'] += 1
            except Exception:
                pass
            known.pop(rid, None)
            remote_items.pop(rid, None)
    # ---- pull
    for rid, (etag, ev) in remote_items.items():
        here = by_remote.get(rid)
        fields = {k: ev[k] for k in ('title', 'start', 'end', 'all_day', 'tz', 'rrule', 'exdates', 'location',
                                     'description', 'reminders', 'overrides') if k in ev}
        fields['remote'] = {'id': rid, 'etag': etag}
        fields['calendar'] = cid
        if here is None:
            made = store.create(dict(fields, uid=ev.get('uid') if ev.get('uid') and ev['uid'] not in local else None),
                                created_by='sync', save=False)
            pulled.add(made['uid'])
            counts['pulled'] += 1
        elif (here.get('remote') or {}).get('etag') != etag:
            if float(here.get('updated', 0)) > last and last:
                copy = {k: here[k] for k in ('title', 'start', 'end', 'all_day', 'tz', 'location', 'description')}
                copy['title'] += ' (conflict copy)'
                copy['calendar'] = cid
                store.create(copy, created_by='sync', save=False)
                counts['conflicts'] += 1
            store.update(here['uid'], save=False, _sync=True, **fields)
            pulled.add(here['uid'])
            counts['pulled'] += 1
    # ---- deleted on the server
    for rid, info in list(known.items()):
        if rid not in remote_items:
            ev = by_remote.get(rid)
            if ev is not None:
                store.delete(ev['uid'], save=False)
                counts['deleted_here'] += 1
            known.pop(rid, None)
    store.file.save()
    # ---- push local changes
    for ev in store.events(cid):
        r = ev.get('remote') or {}
        if ev['uid'] in pulled or (ev.get('title', '').endswith('(conflict copy)') and r.get('id')):
            continue
        if r.get('id') and float(ev.get('updated', 0)) <= last:
            continue
        rid, etag = remote.put(ev, r.get('id', ''), r.get('etag', ''))
        store.update(ev['uid'], save=False, _sync=True, remote={'id': rid, 'etag': etag})
        known[rid] = {'uid': ev['uid'], 'etag': etag}
        counts['pushed'] += 1
    for ev in store.events(cid):
        r = ev.get('remote') or {}
        if r.get('id'):
            known[r['id']] = {'uid': ev['uid'], 'etag': r.get('etag', '')}
    store.file.save()
    source.update(known=known, last_sync=now_ts() + 0.001, last_error='')
    store.update_calendar(cid, source=source)
    return counts


# ------------------------------------------------------------------------------------------ CalDAV
class CalDAV(RemoteCalendar):
    def __init__(self, url: str, username: str, password: str):
        self.url = normalize_url(url)
        if not self.url.endswith('/'):
            self.url += '/'
        token = base64.b64encode(f'{username}:{password}'.encode()).decode()
        self.headers = {'Authorization': 'Basic ' + token}

    def _dav(self, method: str, url: str, body: str = '', depth: str = '1', extra: dict | None = None):
        headers = {**self.headers, 'Depth': depth, 'Content-Type': 'application/xml; charset=utf-8', **(extra or {})}
        return _fetch(url, headers, method, body.encode('utf8') if body else None)

    def discover(self) -> list[dict]:
        """Calendars of the account: [{'url', 'name', 'color'}] (principal → calendar-home-set → collections)."""
        status, _h, body = self._dav('PROPFIND', self.url, '<d:propfind xmlns:d="DAV:"><d:prop>'
                                     '<d:current-user-principal/></d:prop></d:propfind>', '0')
        if status == 401:
            raise PermissionError('The server refused the user name or app password')
        principal = self._href(body, 'current-user-principal') or self.url
        principal = urljoin(self.url, principal)
        status, _h, body = self._dav('PROPFIND', principal, '<d:propfind xmlns:d="DAV:" '
                                     'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-home-set/>'
                                     '</d:prop></d:propfind>', '0')
        home = urljoin(principal, self._href(body, 'calendar-home-set') or principal)
        status, _h, body = self._dav('PROPFIND', home, '<d:propfind xmlns:d="DAV:" '
                                     'xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:a="http://apple.com/ns/ical/">'
                                     '<d:prop><d:resourcetype/><d:displayname/><a:calendar-color/></d:prop>'
                                     '</d:propfind>', '1')
        out = []
        for resp in ET.fromstring(body or b'<x/>').iter(DAV + 'response'):
            if resp.find(f'.//{CAL}calendar') is None:
                continue
            href = resp.findtext(DAV + 'href') or ''
            name = resp.findtext(f'.//{DAV}displayname') or href.rstrip('/').rsplit('/', 1)[-1]
            color = resp.findtext('.//{http://apple.com/ns/ical/}calendar-color') or ''
            out.append({'url': urljoin(home, href), 'name': name, 'color': color[:7]})
        return out

    @staticmethod
    def _href(body: bytes, prop: str) -> str:
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return ''
        node = root.find(f'.//{DAV}{prop}/{DAV}href') or root.find(f'.//{CAL}{prop}/{DAV}href')
        return node.text if node is not None and node.text else ''

    def list(self) -> dict:
        start = (dt.datetime.utcnow() - dt.timedelta(days=400)).strftime('%Y%m%dT000000Z')
        end = (dt.datetime.utcnow() + dt.timedelta(days=800)).strftime('%Y%m%dT000000Z')
        body = ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/>'
                '<c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
                f'<c:time-range start="{start}" end="{end}"/></c:comp-filter></c:comp-filter></c:filter>'
                '</c:calendar-query>')
        status, _h, data = self._dav('REPORT', self.url, body, '1')
        if status not in (200, 207):
            raise RuntimeError(f'CalDAV REPORT failed (HTTP {status})')
        out = {}
        for resp in ET.fromstring(data or b'<x/>').iter(DAV + 'response'):
            href = resp.findtext(DAV + 'href') or ''
            etag = resp.findtext(f'.//{DAV}getetag') or ''
            text = resp.findtext(f'.//{CAL}calendar-data') or ''
            parsed = ics.parse_calendar(text, local_zone_name())['events']
            if parsed:
                out[href] = (etag, parsed[0])
        return out

    def put(self, event: dict, remote_id: str = '', etag: str = ''):
        href = remote_id or urlparse(self.url).path + re.sub(r'[^A-Za-z0-9@._-]', '_', event['uid']) + '.ics'
        clean = {k: v for k, v in event.items() if k not in ('links', 'created_by')}
        headers = {**self.headers, 'Content-Type': 'text/calendar; charset=utf-8'}
        if etag:
            headers['If-Match'] = etag
        else:
            headers['If-None-Match'] = '*'
        status, h, _b = _fetch(urljoin(self.url, href), headers, 'PUT', ics.to_ics([clean]).encode('utf8'))
        if status not in (200, 201, 204):
            raise RuntimeError(f'CalDAV PUT failed (HTTP {status})')
        return href, h.get('ETag') or h.get('etag') or ''

    def delete(self, remote_id: str, etag: str = ''):
        headers = dict(self.headers)
        if etag:
            headers['If-Match'] = etag
        _fetch(urljoin(self.url, remote_id), headers, 'DELETE')


# ------------------------------------------------------------------------------------------ Google / Microsoft
class GoogleCalendar(RemoteCalendar):
    BASE = 'https://www.googleapis.com/calendar/v3/calendars/'

    def __init__(self, account: dict, calendar_id: str = 'primary'):
        self.account, self.calendar_id = account, calendar_id

    def _req(self, method, path, body=None, params=''):
        from .oauth import access_token
        token = access_token('google', self.account)
        url = self.BASE + self.calendar_id + path + params
        status, _h, data = _fetch(url, {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                                  method, json.dumps(body).encode() if body is not None else None)
        if status >= 400:
            raise RuntimeError(f'Google Calendar: HTTP {status}')
        return json.loads(data or b'{}')

    def list(self) -> dict:
        out, page = {}, ''
        while True:
            data = self._req('GET', '/events', params='?maxResults=2500&singleEvents=false' +
                             (f'&pageToken={page}' if page else ''))
            for item in data.get('items', []):
                if item.get('status') == 'cancelled':
                    continue
                out[item['id']] = (item.get('etag', ''), _from_google(item))
            page = data.get('nextPageToken', '')
            if not page:
                return out

    def put(self, event, remote_id='', etag=''):
        body = _to_google(event)
        data = self._req('PUT' if remote_id else 'POST', '/events' + (f'/{remote_id}' if remote_id else ''), body)
        return data['id'], data.get('etag', '')

    def delete(self, remote_id, etag=''):
        self._req('DELETE', f'/events/{remote_id}')


def _from_google(item: dict) -> dict:
    s, e = item.get('start', {}), item.get('end', {})
    all_day = 'date' in s
    def t(x):
        return x['date'] if all_day else iso(parse_time(x.get('dateTime', '')))
    rule = next((r[6:] for r in item.get('recurrence', []) if r.startswith('RRULE:')), '')
    return {'uid': item.get('iCalUID', ''), 'title': item.get('summary', ''), 'start': t(s), 'end': t(e),
            'all_day': all_day, 'tz': s.get('timeZone', ''), 'rrule': rule, 'location': item.get('location', ''),
            'description': item.get('description', ''),
            'reminders': [o['minutes'] for o in (item.get('reminders') or {}).get('overrides', [])]}


def _to_google(ev: dict) -> dict:
    tz = ev.get('tz') or local_zone_name() or 'UTC'
    def t(x):
        return {'date': x[:10]} if ev.get('all_day') else {'dateTime': x, 'timeZone': tz}
    body = {'summary': ev.get('title', ''), 'location': ev.get('location', ''),
            'description': ev.get('description', ''), 'start': t(ev['start']), 'end': t(ev['end'])}
    if ev.get('rrule'):
        body['recurrence'] = ['RRULE:' + ev['rrule']]
    if ev.get('reminders'):
        body['reminders'] = {'useDefault': False,
                             'overrides': [{'method': 'popup', 'minutes': m} for m in ev['reminders'][:5]]}
    return body


class MicrosoftCalendar(RemoteCalendar):
    BASE = 'https://graph.microsoft.com/v1.0/me/calendar'

    def __init__(self, account: dict):
        self.account = account

    def _req(self, method, path, body=None):
        from .oauth import access_token
        token = access_token('microsoft', self.account)
        status, _h, data = _fetch(self.BASE + path, {'Authorization': 'Bearer ' + token,
                                                      'Content-Type': 'application/json',
                                                      'Prefer': 'outlook.timezone="UTC"'},
                                  method, json.dumps(body).encode() if body is not None else None)
        if status >= 400:
            raise RuntimeError(f'Microsoft Graph: HTTP {status}')
        return json.loads(data or b'{}')

    def list(self) -> dict:
        out = {}
        data = self._req('GET', '/events?$top=500')
        for item in data.get('value', []):
            start = parse_time(item['start']['dateTime'][:19]).replace(tzinfo=dt.timezone.utc).astimezone() \
                .replace(tzinfo=None)
            end = parse_time(item['end']['dateTime'][:19]).replace(tzinfo=dt.timezone.utc).astimezone() \
                .replace(tzinfo=None)
            all_day = bool(item.get('isAllDay'))
            out[item['id']] = (item.get('@odata.etag', ''), {
                'uid': item.get('iCalUId', ''), 'title': item.get('subject', ''),
                'start': start.date().isoformat() if all_day else iso(start),
                'end': end.date().isoformat() if all_day else iso(end), 'all_day': all_day, 'tz': '',
                'location': (item.get('location') or {}).get('displayName', ''),
                'description': (item.get('bodyPreview') or ''),
                'reminders': [item['reminderMinutesBeforeStart']] if item.get('isReminderOn') else []})
        return out

    def put(self, event, remote_id='', etag=''):
        start, end = parse_time(event['start']), parse_time(event['end'])
        def t(x):
            if event.get('all_day'):
                return {'dateTime': (x if not isinstance(x, dt.datetime) else x.date()).isoformat() + 'T00:00:00',
                        'timeZone': 'UTC'}
            return {'dateTime': x.astimezone(dt.timezone.utc).replace(tzinfo=None).isoformat(), 'timeZone': 'UTC'}
        body = {'subject': event.get('title', ''), 'start': t(start), 'end': t(end), 'isAllDay': bool(event.get('all_day')),
                'location': {'displayName': event.get('location', '')},
                'body': {'contentType': 'text', 'content': event.get('description', '')}}
        if event.get('reminders'):
            body.update(isReminderOn=True, reminderMinutesBeforeStart=int(event['reminders'][0]))
        data = self._req('PATCH' if remote_id else 'POST', '/events' + (f'/{remote_id}' if remote_id else ''), body)
        return data.get('id', remote_id), data.get('@odata.etag', '')

    def delete(self, remote_id, etag=''):
        self._req('DELETE', f'/events/{remote_id}')


def remote_for(store: CalendarStore, cid: str, mail_store=None) -> RemoteCalendar:
    cal = store.calendar(cid)
    source = cal.get('source') or {}
    if cal.get('kind') == 'caldav':
        return CalDAV(source['url'], source.get('username', ''), secrets.get('caldav:' + cid))
    account = {'id': source.get('account_id') or cid, 'address': source.get('address', ''),
               'oauth': {'client_id': source.get('client_id', ''), 'tenant': source.get('tenant', '')}}
    if cal.get('kind') == 'google':
        return GoogleCalendar(account, source.get('remote_calendar', 'primary'))
    if cal.get('kind') == 'microsoft':
        return MicrosoftCalendar(account)
    raise ValueError('This calendar is not synchronised')


def sync_due(store: CalendarStore, now: float | None = None) -> list[str]:
    now = now or time.time()
    return [c['id'] for c in store.calendars() if c.get('kind') in ('caldav', 'google', 'microsoft') and
            now - float((c.get('source') or {}).get('last_sync') or 0) >= 60 *
            int((c.get('source') or {}).get('interval_min') or 30)]
