"""Calendar, to-do and e-mail tools of the assistant (Qt-free).

Every backend can use them, also plain chat models without tool calling: the assistant writes one or more
blocks in its reply::

    <hub-tool>{"tool": "calendar.create", "title": "Report", "start": "2026-12-01T09:00", "end": "…"}</hub-tool>

After the reply the engine runs them (:func:`dispatch`) and, when something was read or failed, sends the
results back automatically so the assistant can continue (at most :data:`MAX_ROUNDS` rounds per question).

Who decides (:func:`decision`), whatever the model asks:

* reading, searching, finding free time, planning → run;
* creating events, reminders and to-dos → run (marked as made by the assistant; shown as a card the user can
  undo or dismiss);
* changing or deleting an event or to-do **the user made** → an approval card, unless full access is on;
* **sending, replying, forwarding or moving e-mail → always the outbox**: a card with the full message and
  Edit / Send / Discard. Full access, automatic modes and "Always allow" rules do not change this, and no tool
  here can release a message (``mail.Outbox.execute`` needs the user's click).
"""
from __future__ import annotations

import datetime as dt
import json
import re

from .calendar import iso, parse_time
from .todo import PRIORITIES, due_date, parse_due

TAG = 'hub-tool'
BLOCK = re.compile(r'<hub-tool>\s*(\{.*?\})\s*</hub-tool>', re.S)
MAX_ROUNDS = 4
MAX_PER_REPLY = 12
READ = {'calendar.list', 'calendar.search', 'calendar.free_time', 'todo.list', 'todo.plan_day', 'mail.list',
        'mail.search', 'mail.read', 'mail.accounts', 'mail.outbox'}
CREATE = {'calendar.create', 'calendar.plan', 'calendar.remind', 'todo.create', 'todo.prepare_event',
          'admin.check'}
CHANGE = {'calendar.update', 'calendar.delete', 'todo.update', 'todo.complete', 'todo.delete'}
MAIL_OUT = {'mail.send', 'mail.reply', 'mail.forward', 'mail.move', 'mail.draft'}
NETWORK = {'mail.list', 'mail.search', 'mail.read', 'mail.reply', 'mail.forward', 'admin.check'}
TOOLS = READ | CREATE | CHANGE | MAIL_OUT


def parse(reply: str) -> list[dict]:
    out = []
    for m in BLOCK.finditer(reply or ''):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            out.append({'tool': '_invalid', 'error': 'Not valid JSON: ' + m.group(1)[:200]})
            continue
        if isinstance(data, dict) and data.get('tool'):
            out.append(data)
    return out[:MAX_PER_REPLY]


def strip(reply: str) -> str:
    return BLOCK.sub('', reply or '').strip()


def is_result_message(text: str) -> bool:
    return str(text or '').startswith('[Agent Hub — results of your tool requests]')


# ------------------------------------------------------------------------------------------ policy
def decision(request: dict, conf: dict, organizer) -> str:
    """'run' · 'ask' (approval card) · 'outbox' (mail card: Edit / Send / Discard) · 'refuse'."""
    tool = str(request.get('tool', ''))
    if tool not in TOOLS:
        return 'refuse'
    if tool in MAIL_OUT:
        return 'outbox'                              # never 'run': no setting changes this
    if tool in READ or tool in CREATE:
        return 'run'
    if conf.get('full_access'):
        return 'run'
    owner = _owner(tool, request, organizer)
    return 'run' if owner == 'assistant' else 'ask'


def _owner(tool: str, request: dict, organizer) -> str:
    try:
        if tool.startswith('calendar.'):
            ev = organizer.calendar.get(str(request.get('uid', '')))
            return (ev or {}).get('created_by', 'user')
        t = organizer.todo.find(request.get('id', ''))
        return t.get('created_by', 'user') if t.get('created_by') != 'migration' else 'user'
    except KeyError:
        return 'assistant'                           # nothing to protect: the call fails with "not found"


def describe(request: dict, organizer=None) -> tuple[str, str]:
    """(title, detail) for the approval card."""
    tool = request.get('tool', '')
    if tool.startswith('calendar.'):
        ev = organizer.calendar.get(str(request.get('uid', ''))) if organizer else None
        name = (ev or {}).get('title', request.get('uid', ''))
        when = (ev or {}).get('start', '')
        if tool == 'calendar.delete':
            return 'Delete your event', f"{name} · {when}" + (f" (only {request['instance']})"
                                                              if request.get('instance') else '')
        changes = ', '.join(f'{k}: {v}' for k, v in request.items() if k not in ('tool', 'uid'))
        return 'Change your event', f'{name} · {when}\n→ {changes}'
    if tool.startswith('todo.'):
        try:
            t = organizer.todo.find(request.get('id', '')) if organizer else {}
        except KeyError:
            t = {}
        changes = ', '.join(f'{k}: {v}' for k, v in request.items() if k not in ('tool', 'id'))
        verb = {'todo.delete': 'Delete your to-do', 'todo.complete': 'Mark your to-do done'}.get(tool,
                                                                                               'Change your to-do')
        return verb, f"{t.get('title', request.get('id', ''))}" + (f'\n→ {changes}' if changes else '')
    return 'Use ' + tool, json.dumps({k: v for k, v in request.items() if k != 'tool'})[:600]


# ------------------------------------------------------------------------------------------ dispatch
def dispatch(request: dict, organizer, conf: dict | None = None, approved: bool = False, origin: str = 'assistant'):
    """Run one request after :func:`decision`. Returns ``{'ok', 'text', 'tool', 'card'?, 'pending'?}``.

    ``approved`` means the user answered an approval card for a change of their own event / to-do. It has no
    effect on e-mail: mail requests always end as an outbox proposal."""
    conf = conf or {}
    tool = str(request.get('tool', ''))
    try:
        verdict = decision(request, conf, organizer)
        if verdict == 'refuse':
            raise ValueError(f'Unknown tool {tool!r}. Available: ' + ', '.join(sorted(TOOLS)))
        if verdict == 'ask' and not approved:
            title, detail = describe(request, organizer)
            return {'ok': True, 'tool': tool, 'pending': 'approval', 'title': title, 'detail': detail,
                    'text': 'Waiting for the user to approve: ' + title}
        if verdict == 'outbox':
            return _mail_out(request, organizer, origin)
        handler = HANDLERS[tool]
        result = handler(request, organizer)
        if isinstance(result, str):
            result = {'text': result}
        return {'ok': True, 'tool': tool, **result}
    except Exception as exc:
        from .secrets import redact
        return {'ok': False, 'tool': tool, 'text': 'ERROR: ' + redact(str(exc))[:500]}


def needs_followup(results: list[dict]) -> bool:
    return any(r['tool'] in READ or not r['ok'] or r['tool'] in ('admin.check', 'calendar.plan', 'todo.plan_day')
               for r in results)


def result_message(results: list[dict]) -> str:
    parts = ['[Agent Hub — results of your tool requests]']
    for r in results:
        parts.append(f"### {r['tool']} — {'ok' if r['ok'] else 'failed'}\n{r['text']}")
    parts.append('Continue with the user\'s request. Do not repeat requests that already succeeded.')
    return '\n\n'.join(parts)


# ------------------------------------------------------------------------------------------ helpers
def _t(value, default=None):
    if value in (None, ''):
        return default
    text = str(value).strip()
    if len(text) == 10:
        return dt.date.fromisoformat(text)
    v = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
    return v.astimezone().replace(tzinfo=None) if v.tzinfo else v


def _fmt(o) -> str:
    s, e = o['start'], o['end']
    if o.get('all_day'):
        last = (e - dt.timedelta(days=1)) if isinstance(e, dt.date) else e
        span = s.isoformat() + ('' if last == s else f' → {last.isoformat()}')
        return f"{span} (all day)"
    return f"{s:%Y-%m-%d %a %H:%M}–{e:%H:%M}" if s.date() == e.date() else f"{s:%Y-%m-%d %H:%M} → {e:%Y-%m-%d %H:%M}"


def _occ_line(o) -> str:
    bits = [f"- {_fmt(o)} · {o['title']}", f"[uid {o['uid']}" + (f", instance {o['instance']}" if o['recurring']
                                                                 else '') + ']',
            f"calendar {o['calendar_name']}", 'made by ' + o.get('created_by', 'user')]
    if o.get('location'):
        bits.append('at ' + o['location'])
    if (o.get('links') or {}).get('todo'):
        bits.append('to-do ' + o['links']['todo'])
    return ' · '.join(bits)


def _task_line(t, store) -> str:
    lst = store.list_(t.get('list', '')) or {}
    bits = [f"- [{'x' if t['done'] else ' '}] {t['title']}", f"(id {t['id']})", f"list {lst.get('name', '?')}"]
    if t.get('due'):
        bits.append('due ' + t['due'].replace('T', ' '))
    if t.get('priority'):
        bits.append('priority ' + PRIORITIES[t['priority']].lower())
    if t.get('tags'):
        bits.append(' '.join('#' + x for x in t['tags']))
    if t.get('rrule'):
        bits.append('repeats ' + t['rrule'])
    if t.get('subtasks'):
        bits.append(f"{sum(s['done'] for s in t['subtasks'])}/{len(t['subtasks'])} subtasks")
    if (t.get('links') or {}).get('for_event'):
        bits.append(f"for event {t['links']['for_event']} ({t['links'].get('purpose', 'prep')})")
    bits.append('made by ' + t.get('created_by', 'user'))
    return ' · '.join(bits)


def _event_fields(r: dict, organizer) -> dict:
    fields = {}
    for key in ('title', 'location', 'description', 'color', 'rrule', 'tz'):
        if key in r:
            fields[key] = r[key]
    if 'all_day' in r:
        fields['all_day'] = bool(r['all_day'])
    for key in ('start', 'end'):
        if r.get(key):
            v = _t(r[key])
            fields[key] = iso(v)
    if 'reminders' in r:
        fields['reminders'] = [int(x) for x in r['reminders']]
    if r.get('calendar'):
        cal = next((c for c in organizer.calendar.calendars() if c['id'] == r['calendar'] or
                    c['name'].lower() == str(r['calendar']).lower()), None)
        if cal is None:
            raise ValueError(f"No calendar named {r['calendar']!r}")
        fields['calendar'] = cal['id']
    return fields


# ------------------------------------------------------------------------------------------ calendar
def cal_list(r, org):
    start = _t(r.get('start'), dt.date.today())
    end = _t(r.get('end'), start + dt.timedelta(days=7))
    occ = org.calendar.occurrences(start, end, visible_only=False)
    if r.get('query'):
        q = str(r['query']).lower()
        occ = [o for o in occ if q in o['title'].lower() or q in o['location'].lower()]
    lines = [_occ_line(o) for o in occ[:200]]
    return f"{len(occ)} event(s) from {start} to {end}:\n" + ('\n'.join(lines) or '(none)')


def cal_search(r, org):
    found = org.calendar.search(r.get('query', ''))
    return f'{len(found)} match(es):\n' + ('\n'.join(_occ_line(o) for o in found) or '(none)')


def cal_create(r, org):
    fields = _event_fields(r, org)
    if 'start' not in fields:
        raise ValueError('calendar.create needs a start')
    ev = org.create_event(dict(fields, links={k: r[k] for k in ('todo', 'email', 'chat') if r.get(k)}),
                          created_by='assistant')
    card = {'kind': 'created_event', 'uid': ev['uid'], 'title': ev['title'], 'start': ev['start'], 'end': ev['end'],
            'all_day': ev['all_day']}
    return {'text': f"Created “{ev['title']}” {ev['start']} → {ev['end']} (uid {ev['uid']})", 'card': card}


def cal_update(r, org):
    uid = str(r.get('uid', ''))
    if org.calendar.get(uid) is None:
        raise KeyError(f'No event {uid}')
    fields = _event_fields(r, org)
    if r.get('instance'):
        ev = org.calendar.update_occurrence(uid, r['instance'], **fields)
        org.event_changed(uid)
        org.changed('calendar')
    else:
        ev = org.update_event(uid, **fields)
    return f"Updated “{ev['title']}” ({uid})"


def cal_delete(r, org):
    uid = str(r.get('uid', ''))
    ev = org.calendar.get(uid)
    if ev is None:
        raise KeyError(f'No event {uid}')
    if r.get('instance'):
        org.calendar.delete_occurrence(uid, r['instance'])
        org.changed('calendar')
        return f"Removed the occurrence {r['instance']} of “{ev['title']}”"
    org.delete_event(uid)
    return f"Deleted “{ev['title']}”"


def cal_free(r, org):
    start = _t(r.get('start'), dt.datetime.now())
    end = _t(r.get('end'), (start if isinstance(start, dt.datetime) else dt.datetime.combine(start, dt.time()))
             + dt.timedelta(days=7))
    slots = org.calendar.free_slots(start, end, int(r.get('minutes', 60)), int(r.get('day_start', 9)),
                                    int(r.get('day_end', 18)), bool(r.get('weekdays_only', True)))
    return f'{len(slots)} free slot(s):\n' + '\n'.join(f"- {a:%Y-%m-%d %a %H:%M}–{b:%H:%M}" for a, b in slots[:60])


def cal_plan(r, org):
    """Block time: ``{"title", "minutes": 180, "start", "end", "block_minutes": 90, "todo": id}``."""
    total = int(r.get('minutes', 60))
    block = max(15, int(r.get('block_minutes', min(total, 120))))
    now = dt.datetime.now().replace(second=0, microsecond=0)
    start = _t(r.get('start'), now)
    if not isinstance(start, dt.datetime):
        start = dt.datetime.combine(start, dt.time())
    start = max(start, now)
    minute = (start.minute + 14) // 15 * 15
    start = start.replace(minute=0) + dt.timedelta(minutes=minute)
    end = _t(r.get('end'), start + dt.timedelta(days=7 - start.weekday() if start.weekday() < 5 else 7))
    if not isinstance(end, dt.datetime):
        end = dt.datetime.combine(end, dt.time()) + dt.timedelta(days=1)
    slots = org.calendar.free_slots(start, end, min(block, total), int(r.get('day_start', 9)),
                                    int(r.get('day_end', 18)))
    made, left = [], total
    for a, b in slots:
        while left > 0 and (b - a).total_seconds() >= 15 * 60:
            length = min(block, left, int((b - a).total_seconds() // 60))
            if length < min(30, left):
                break
            ev = org.create_event({'title': r.get('title', 'Focus time'), 'start': iso(a),
                                   'end': iso(a + dt.timedelta(minutes=length)),
                                   'description': r.get('description', ''),
                                   'links': {'todo': r['todo']} if r.get('todo') and not made else {}},
                                  created_by='assistant')
            made.append(ev)
            left -= length
            a += dt.timedelta(minutes=length + 15)
        if left <= 0:
            break
    text = f"Planned {total - left} of {total} min in {len(made)} block(s):\n" + \
        '\n'.join(f"- {e['start'].replace('T', ' ')} → {e['end'][11:16]} (uid {e['uid']})" for e in made)
    if left > 0:
        text += f'\nNot enough free time for {left} min before {end:%Y-%m-%d}.'
    return {'text': text, 'card': {'kind': 'planned', 'uids': [e['uid'] for e in made], 'title': r.get('title', ''),
                                   'minutes': total - left}}


def cal_remind(r, org):
    """A reminder the assistant adds on its own initiative (shown as a card the user can dismiss)."""
    reason = str(r.get('reason', ''))[:300]
    if r.get('uid'):
        ev = org.calendar.get(r['uid'])
        if ev is None:
            raise KeyError(f"No event {r['uid']}")
        minutes = int(r.get('minutes_before', 60))
        reminders = sorted(set(ev.get('reminders', [])) | {minutes})
        org.calendar.update(ev['uid'], _sync=True, reminders=reminders)
        org.changed('calendar')
        return {'text': f"Reminder {minutes} min before “{ev['title']}”",
                'card': {'kind': 'reminder', 'uid': ev['uid'], 'minutes': minutes, 'title': ev['title'],
                         'reason': reason, 'added_to_existing': True}}
    at = _t(r.get('at'))
    if at is None:
        raise ValueError('calendar.remind needs "uid" or "at"')
    if not isinstance(at, dt.datetime):
        at = dt.datetime.combine(at, dt.time(9))
    ev = org.create_event({'title': r.get('title') or 'Reminder', 'start': iso(at),
                           'end': iso(at + dt.timedelta(minutes=15)), 'reminders': [0],
                           'description': reason}, created_by='assistant')
    return {'text': f"Reminder “{ev['title']}” at {at:%Y-%m-%d %H:%M} (uid {ev['uid']})",
            'card': {'kind': 'reminder', 'uid': ev['uid'], 'minutes': 0, 'title': ev['title'], 'reason': reason,
                     'added_to_existing': False, 'at': iso(at)}}


# ------------------------------------------------------------------------------------------ to-do
def _task_fields(r, org) -> dict:
    fields = {}
    for key in ('title', 'notes', 'rrule', 'start'):
        if key in r:
            fields[key] = r[key]
    if 'due' in r:
        fields['due'] = r['due'] or ''
        if fields['due'] and 'T' in fields['due']:
            fields['due'] = fields['due'][:16]
    if 'priority' in r:
        p = r['priority']
        fields['priority'] = {'high': 3, 'medium': 2, 'low': 1, 'none': 0}.get(str(p).lower(), p)
    if 'tags' in r:
        fields['tags'] = r['tags'] if isinstance(r['tags'], list) else str(r['tags']).split()
    if r.get('list'):
        lst = org.todo.list_by_name(r['list']) or org.todo.list_(r['list'])
        if lst is None:
            lst = org.todo.add_list(str(r['list']))
        fields['list'] = lst['id']
    if 'subtasks' in r:
        fields['subtasks'] = [s if isinstance(s, dict) else {'title': str(s)} for s in r['subtasks']]
    return fields


def todo_list(r, org):
    view = r.get('view', 'open')
    tasks = org.todo.view(view if view in ('today', 'upcoming', 'overdue', 'completed', 'open', 'all') else 'open',
                          query=r.get('query', ''), tag=r.get('tag', ''), sort=r.get('sort', 'due'),
                          list_id=(org.todo.list_by_name(r['list']) or {}).get('id', '') if r.get('list') else '')
    lists = ', '.join(l['name'] for l in org.todo.lists())
    return f"{len(tasks)} task(s) ({view}); lists: {lists}\n" + ('\n'.join(_task_line(t, org.todo)
                                                                           for t in tasks[:200]) or '(none)')


def todo_create(r, org):
    fields = _task_fields(r, org)
    if r.get('for_event'):
        task, created = org.ensure_event_task(r['for_event'], r.get('purpose', 'prep'), fields.get('title', 'Task'),
                                              due=fields.get('due') or None, notes=fields.get('notes', ''))
        if not created:
            return f"Already exists (no duplicate): {task['title']} (id {task['id']})"
    else:
        task = org.add_task(fields, created_by='assistant')
    return {'text': f"Created to-do “{task['title']}” (id {task['id']})" +
            (f", due {task['due']}" if task.get('due') else ''),
            'card': {'kind': 'created_task', 'id': task['id'], 'title': task['title'], 'due': task.get('due', '')}}


def todo_prepare(r, org):
    """``{"uid": event, "tasks": [{"purpose": "prep", "title": "…", "due": "…"}]}`` — once per (event, purpose)."""
    uid = r.get('uid', '')
    if org.calendar.get(uid) is None:
        raise KeyError(f'No event {uid}')
    lines, cards = [], []
    for item in r.get('tasks') or [{'purpose': 'prep', 'title': 'Prepare: ' + org.calendar.get(uid)['title']}]:
        task, created = org.ensure_event_task(uid, item.get('purpose', 'prep'), item.get('title', 'Prepare'),
                                              due=item.get('due') or None, notes=item.get('notes', ''))
        lines.append(('created ' if created else 'already there ') + f"“{task['title']}” (id {task['id']}, "
                     f"due {task['due'] or '—'})")
        if created:
            cards.append(task['id'])
    return {'text': '\n'.join(lines), 'card': {'kind': 'created_tasks', 'ids': cards}} if cards else '\n'.join(lines)


def todo_update(r, org):
    task = org.todo.find(r.get('id', ''))
    t = org.update_task(task['id'], **_task_fields(r, org))
    return f"Updated “{t['title']}” (id {t['id']})"


def todo_complete(r, org):
    task = org.todo.find(r.get('id', ''))
    t = org.complete_task(task['id'], bool(r.get('done', True)))
    return f"“{t['title']}” " + ('done' if t['done'] else (f"next due {t['due']}" if t.get('rrule') and
                                                           r.get('done', True) else 'not done'))


def todo_delete(r, org):
    task = org.todo.find(r.get('id', ''))
    org.delete_task(task['id'])
    return f"Deleted “{task['title']}”"


def todo_plan_day(r, org):
    day = _t(r.get('date'), dt.date.today())
    if isinstance(day, dt.datetime):
        day = day.date()
    tasks = [t for t in org.todo.view('open', sort='priority')
             if due_date(t) is None or due_date(t) <= day + dt.timedelta(days=2)]
    occ = [o for o in org.calendar.occurrences(day, day + dt.timedelta(days=1), visible_only=False)
           if not (o.get('links') or {}).get('todo')]
    slots = org.calendar.free_slots(day, day + dt.timedelta(days=1), 30, int(r.get('day_start', 9)),
                                    int(r.get('day_end', 18)), weekdays_only=False)
    text = [f'Plan for {day:%A %d %B %Y}', 'Fixed events:'] + [_occ_line(o) for o in occ] + \
        ['Free time:'] + [f'- {a:%H:%M}–{b:%H:%M}' for a, b in slots] + \
        ['Open tasks (priority, due soon first):'] + [_task_line(t, org.todo) for t in tasks[:40]]
    text.append('Propose an order to the user; schedule blocks with calendar.plan only when they agree.')
    return '\n'.join(text)


# ------------------------------------------------------------------------------------------ mail (reading)
def _mail_account(r, org):
    accounts = org.mail.connected()
    if not accounts:
        raise ValueError('No e-mail account is connected (Agent Hub › Settings › E-mail accounts)')
    if r.get('account'):
        found = next((a for a in accounts if r['account'] in (a['id'], a['address'], a['label'])), None)
        if found is None:
            raise ValueError(f"No account {r['account']!r}")
        return found
    return accounts[0]


def _mail_line(m):
    att = f" · {len(m['attachments'])} attachment(s)" if m.get('attachments') else ''
    unread = '' if 'Seen' in (m.get('flags') or []) else ' · unread'
    return (f"- {m.get('date', '')[:16].replace('T', ' ')} · {m.get('from', '')} · {m.get('subject', '')}"
            f" [account {m['account']}, folder {m['folder']}, uid {m['uid']}]{unread}{att}\n  {m.get('snippet', '')}")


def mail_accounts(r, org):
    accounts = org.mail.connected()
    return '\n'.join(f"- {a['label']} <{a['address']}> (id {a['id']})" for a in accounts) or \
        'No e-mail account is connected.'


def mail_list(r, org):
    acc = _mail_account(r, org)
    msgs = org.mail.client(acc['id']).recent(r.get('folder', 'INBOX'), int(r.get('days', 7)),
                                             min(100, int(r.get('limit', 30))), bool(r.get('unread', False)))
    org.mail.remember(msgs)
    return f"{len(msgs)} message(s) in {acc['label']} / {r.get('folder', 'INBOX')}:\n" + \
        '\n'.join(_mail_line(m) for m in msgs)


def mail_search(r, org):
    acc = _mail_account(r, org)
    msgs = org.mail.client(acc['id']).search(r.get('query', ''), r.get('folder', 'INBOX'))
    org.mail.remember(msgs)
    return f'{len(msgs)} match(es):\n' + '\n'.join(_mail_line(m) for m in msgs)


def mail_read(r, org):
    acc = _mail_account(r, org)
    m = org.mail.client(acc['id']).message(str(r['uid']), r.get('folder', 'INBOX'))
    att = ', '.join(f"{a['name']} ({a['size'] // 1024} kB)" for a in m['attachments']) or 'none'
    return (f"From: {m['from']}\nTo: {m['to']}\nCc: {m['cc']}\nDate: {m['date']}\nSubject: {m['subject']}\n"
            f"Attachments: {att}\n\n{m['body'][:20000]}")


def mail_outbox(r, org):
    items = org.mail.outbox.items()
    return '\n'.join(f"- {i['action']} “{i['draft'].get('subject', '')}” to {', '.join(i['draft'].get('to', []))} "
                     f"(waiting for the user, id {i['id']})" for i in items) or 'The outbox is empty.'


def _mail_out(r, org, origin):
    """Every outgoing mail action ends here: a proposal the user releases (or not)."""
    tool = r['tool']
    acc = _mail_account(r, org)
    action = {'mail.send': 'send', 'mail.draft': 'send', 'mail.reply': 'reply', 'mail.forward': 'forward',
              'mail.move': 'move'}[tool]
    draft = {k: r[k] for k in ('to', 'cc', 'bcc', 'subject', 'body', 'attachments') if k in r}
    if action in ('reply', 'forward'):
        from .mail import forward_draft, reply_draft
        original = org.mail.client(acc['id']).message(str(r['uid']), r.get('folder', 'INBOX'))
        if action == 'reply':
            base = reply_draft(original, r.get('body', ''), acc, bool(r.get('all', False)))
        else:
            base = forward_draft(original, r.get('to', []), r.get('body', ''))
        base.update({k: v for k, v in draft.items() if k in ('to', 'cc', 'bcc', 'attachments') and v})
        if r.get('subject'):
            base['subject'] = r['subject']
        draft = base
    elif action == 'move':
        draft = {'uid': str(r.get('uid', '')), 'folder': r.get('target') or r.get('to_folder') or '',
                 'source_folder': r.get('folder', 'INBOX'), 'subject': r.get('subject', '')}
    item = org.mail.outbox.propose(action, acc['id'], draft, origin=origin, note=r.get('note', ''))
    org.changed('mail')
    return {'ok': True, 'tool': tool, 'pending': 'outbox', 'outbox_id': item['id'],
            'card': {'kind': 'mail', 'id': item['id']},
            'text': f"The {action} is waiting in the outbox for the user (id {item['id']}): they review it and press "
                    'Send themselves. Nothing was sent. Do not say it was sent.'}


def admin_check(r, org):
    """Run the administrative workflow on one message: to-do + gathered values + a form card."""
    from . import admin
    acc = _mail_account(r, org)
    client = org.mail.client(acc['id'])
    m = client.message(str(r['uid']), r.get('folder', 'INBOX'))
    found = admin.detect(m) or {'kind': 'reply', 'deadline': r.get('deadline', ''), 'quantities': [],
                                'period': admin.find_period(m['body'], dt.date.today()), 'pdf_attachments': []}
    task, created = admin.start(org, m, found)
    return {'text': f"Administrative request: to-do “{task['title']}” ({'created' if created else 'exists'}), "
                    f"deadline {found.get('deadline') or 'none found'}; the form card asks the user for the missing "
                    'values.',
            'card': {'kind': 'admin_form', 'account': acc['id'], 'uid': m['uid'], 'folder': m['folder'],
                     'task': task['id'], 'found': {k: v for k, v in found.items() if k != 'pdf_attachments'},
                     'pdfs': [a['index'] for a in found.get('pdf_attachments') or []]}}


HANDLERS = {
    'calendar.list': cal_list, 'calendar.search': cal_search, 'calendar.create': cal_create,
    'calendar.update': cal_update, 'calendar.delete': cal_delete, 'calendar.free_time': cal_free,
    'calendar.plan': cal_plan, 'calendar.remind': cal_remind,
    'todo.list': todo_list, 'todo.create': todo_create, 'todo.update': todo_update, 'todo.complete': todo_complete,
    'todo.delete': todo_delete, 'todo.plan_day': todo_plan_day, 'todo.prepare_event': todo_prepare,
    'mail.accounts': mail_accounts, 'mail.list': mail_list, 'mail.search': mail_search, 'mail.read': mail_read,
    'mail.outbox': mail_outbox, 'admin.check': admin_check,
}


# ------------------------------------------------------------------------------------------ instructions
def instructions(organizer, mail_enabled: bool = True) -> str:
    now = dt.datetime.now()
    from .calendar import local_zone_name
    cals = ', '.join(f"{c['name']}{' (read-only)' if c.get('readonly') else ''}" for c in organizer.calendar.calendars())
    lists = ', '.join(l['name'] for l in organizer.todo.lists())
    accounts = organizer.mail.connected() if mail_enabled else []
    text = f"""
## Calendar, to-do{' and e-mail' if accounts else ''} (Agent Hub tools)
Now: {now:%A %Y-%m-%d %H:%M} ({local_zone_name() or 'local time'}). Calendars: {cals}. To-do lists: {lists}.
Use a tool by writing, on its own line, `<hub-tool>{{"tool": "…", …}}</hub-tool>` (JSON, several blocks allowed).
Agent Hub runs them after your reply and sends you the results of reads; then continue. Times are local ISO
(`2026-12-01T14:00`, a date alone for all-day). Use the uid / id values from the results.
- calendar.list {{start, end, query?}} · calendar.search {{query}} · calendar.free_time {{start, end, minutes, day_start?, day_end?}}
- calendar.create {{title, start, end?, all_day?, rrule?, location?, description?, reminders?: [minutes], calendar?}}
- calendar.plan {{title, minutes, start?, end?, block_minutes?, todo?}} — books free time ("plan 3 hours for the report this week")
- calendar.update {{uid, instance?, …fields}} · calendar.delete {{uid, instance?}} — the user approves changes to events they made
- calendar.remind {{uid, minutes_before, reason}} or {{title, at, reason}} — add a reminder on your own initiative when
  something is important (a deadline in an e-mail, a conflict); the user sees it as a card and may dismiss it
- todo.list {{view: today|upcoming|overdue|completed|open|all, query?, tag?, list?}} · todo.plan_day {{date?}}
- todo.create {{title, due?, list?, tags?, priority?: high|medium|low, notes?, rrule?, subtasks?, for_event?, purpose?}}
- todo.prepare_event {{uid, tasks: [{{purpose: prep|follow-up|…, title, due?}}]}} — preparation / follow-up to-dos for a
  meeting, presentation or deadline, linked to the event (never duplicated)
- todo.update {{id, …}} · todo.complete {{id, done?}} · todo.delete {{id}}
A to-do with a due date appears in the calendar automatically (linked both ways): do not create a second event for it."""
    if accounts:
        names = ', '.join(f"{a['label']} (id {a['id']})" for a in accounts)
        text += f"""
E-mail accounts: {names}.
- mail.list {{account?, folder?, days?, unread?}} · mail.search {{query}} · mail.read {{account?, uid, folder?}} · mail.outbox {{}}
- mail.draft / mail.send {{to, cc?, subject, body, attachments?: [paths]}} · mail.reply {{uid, body, all?}} ·
  mail.forward {{uid, to, body?}} · mail.move {{uid, folder, target}}
- admin.check {{uid, folder?}} — an e-mail asking the user to fill something in (home-office days, a form, a timesheet):
  creates the to-do with the deadline, gathers values from the calendar and earlier answers, and shows a form card
SENDING RULE: you never send, reply, forward or move e-mail yourself. These requests only put a proposal in the outbox;
the user reads the full message and presses Send (or edits / discards it). Never claim a message was sent."""
    return text
