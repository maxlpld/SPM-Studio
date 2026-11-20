"""To-do list and notes connected to the assistant (Qt-free model).

Everything is kept in ``<data>/todo/todo.json`` (never in the settings, never in a temporary
folder) and written atomically after each change, with the previous version kept as
``todo.json.bak``. Erasing everything first saves a copy ``erased_<date>.json`` in the same
folder, so nothing typed is lost by accident.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import uuid
from pathlib import Path

CATEGORIES = ('Analysis', 'Script', 'Writing', 'Figure', 'Other')
DONE_STYLES = ('strike', 'plain', 'hide')
MAX_TASKS = 2000
MAX_TEXT = 20000


def folder() -> Path:
    from spm_studio.core import paths
    return paths.data_dir() / 'todo'


def file() -> Path:
    return folder() / 'todo.json'


def now() -> str:
    return _dt.datetime.now().isoformat(timespec='seconds')


def empty() -> dict:
    return {'schema_version': 1, 'tasks': [], 'notes': '', 'updated': now()}


def _clean_task(t) -> dict | None:
    if not isinstance(t, dict):
        return None
    text = str(t.get('text', ''))[:MAX_TEXT]
    out = {'id': str(t.get('id') or new_id()), 'text': text, 'details': str(t.get('details', ''))[:MAX_TEXT],
           'done': bool(t.get('done', False)), 'category': str(t.get('category', '') or ''),
           'created': str(t.get('created') or now()), 'done_at': str(t.get('done_at') or '')}
    if out['category'] and out['category'] not in CATEGORIES:
        out['category'] = 'Other'
    return out


def load(path: Path | None = None) -> dict:
    path = path or file()
    for candidate in (path, path.with_name(path.name + '.bak')):
        try:
            data = json.loads(candidate.read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            tasks = [t for t in (_clean_task(x) for x in data.get('tasks', [])) if t][:MAX_TASKS]
            return {'schema_version': 1, 'tasks': tasks, 'notes': str(data.get('notes', ''))[:500000],
                    'updated': str(data.get('updated', ''))}
    return empty()


def save(data: dict, path: Path | None = None) -> Path:
    return _save(data, path)


def _save(data: dict, path: Path | None = None) -> Path:
    path = path or file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data['updated'] = now()
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if path.is_file():
        try:
            backup = path.with_name(path.name + '.bak')
            backup.write_bytes(path.read_bytes())
        except OSError:
            pass
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    tmp.write_text(text, encoding='utf8')
    os.replace(tmp, path)
    return path


def new_id() -> str:
    return 't' + uuid.uuid4().hex[:6]


def add_task(data: dict, text: str, details: str = '', category: str = '') -> dict:
    if len(data['tasks']) >= MAX_TASKS:
        raise ValueError('The list is full (2000 tasks)')
    task = _clean_task({'text': text.strip() or 'New task', 'details': details, 'category': category})
    data['tasks'].append(task)
    return task


def find(data: dict, ref) -> dict:
    """A task by id (``t3f9a2c``) or by its number in the list (1-based, ``3`` or ``#3``)."""
    ref = str(ref or '').strip().lstrip('#')
    for t in data['tasks']:
        if t['id'] == ref:
            return t
    if ref.isdigit() and 1 <= int(ref) <= len(data['tasks']):
        return data['tasks'][int(ref) - 1]
    raise ValueError(f'No task {ref!r} (use the id or the number shown by "read")')


def set_done(task: dict, done: bool):
    task['done'] = bool(done)
    task['done_at'] = now() if done else ''


def delete(data: dict, ref) -> dict:
    task = find(data, ref)
    data['tasks'].remove(task)
    return task


def erase_all(data: dict, path: Path | None = None) -> Path | None:
    """Empty the list and the notes; a copy is kept beside the file first."""
    path = path or file()
    copy = None
    if data['tasks'] or data['notes'].strip():
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
        copy = path.with_name(f'erased_{stamp}.json')
        copy.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf8')
    data['tasks'] = []
    data['notes'] = ''
    return copy


def as_text(data: dict, only=None, include_done=True) -> str:
    """Readable list for the assistant: ``#3 [ ] (t1a2b3c) Analysis · text`` + details + notes."""
    lines = []
    for n, t in enumerate(data['tasks'], 1):
        if only is not None and t['id'] not in only:
            continue
        if not include_done and t['done']:
            continue
        mark = 'x' if t['done'] else ' '
        cat = f"{t['category']} · " if t['category'] else ''
        lines.append(f"#{n} [{mark}] ({t['id']}) {cat}{t['text']}")
        for d in t['details'].strip().splitlines():
            lines.append('      ' + d)
    return '\n'.join(lines) if lines else '(no tasks)'


def summary(data: dict) -> str:
    open_ = sum(1 for t in data['tasks'] if not t['done'])
    return f"{len(data['tasks'])} tasks ({open_} open), notes {len(data['notes'])} characters"


def parse_quick(text: str):
    """``Analysis: fit the CPD of scan 12`` → ('fit the CPD of scan 12', 'Analysis')."""
    m = re.match(r'\s*([A-Za-z]+)\s*:\s*(.+)$', text or '')
    if m and m.group(1).capitalize() in CATEGORIES:
        return m.group(2).strip(), m.group(1).capitalize()
    return (text or '').strip(), ''


def ai_action(request: dict, data: dict | None = None, save: bool = True) -> str:
    """One assistant request (``<spm-doc>{"app": "todo", ...}``) on the list; saved unless ``save=False``."""
    data = load() if data is None else data
    action = request['action']
    if action == 'read':
        return (f'{summary(data)}\n\n### Tasks (#number [x = done] (id) category · text, then details)\n'
                f'{as_text(data)}\n\n### Notes\n{data["notes"] or "(empty)"}')
    if action == 'add_task':
        task = add_task(data, request.get('text', ''), request.get('details', ''), request.get('category', ''))
        result = f"Added #{len(data['tasks'])} ({task['id']}) {task['text']}"
    elif action == 'update_task':
        task = find(data, request.get('item', ''))
        if 'text' in request:
            task['text'] = request['text'].strip() or task['text']
        if 'details' in request:
            task['details'] = request['details']
        if 'append' in request:
            task['details'] = (task['details'].rstrip() + '\n' + request['append']).strip()
        if 'category' in request:
            task['category'] = request['category'] if request['category'] in CATEGORIES else 'Other'
        if 'done' in request:
            set_done(task, request['done'])
        result = f"Updated ({task['id']}) {task['text']}" + (' — done' if task['done'] else '')
    elif action == 'delete_task':
        task = delete(data, request.get('item', ''))
        result = f"Deleted ({task['id']}) {task['text']}"
    elif action == 'append_notes':
        data['notes'] = (data['notes'].rstrip() + '\n\n' + request.get('text', '')).strip()
        result = 'Notes extended'
    else:
        raise ValueError(f'Unknown to-do action {action}')
    if save:
        _save(data)
    return result
