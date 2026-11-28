"""The ``<spm-doc>{"app": "todo", …}`` requests of the classic assistant, and the extension API's to-do count,
on the upgraded to-do list (0.1.0). Same actions and answers as before: read, add_task, update_task,
delete_task, set_notes / append_notes; tasks are referred to by their old id, new id or number."""
from __future__ import annotations


def organizer():
    from agent_hub import host as ah_host
    if ah_host.current().name == 'standalone':
        from .host import SPMHost
        ah_host.set_host(SPMHost())
    from agent_hub.organizer import shared
    return shared()


def open_count() -> int:
    return len(organizer().todo.tasks(include_done=False))


def as_text(org, include_done=True) -> str:
    lines = []
    for n, t in enumerate(org.todo.tasks(), 1):
        if not include_done and t['done']:
            continue
        lst = (org.todo.list_(t['list']) or {}).get('name', '')
        lines.append(f"#{n} [{'x' if t['done'] else ' '}] ({t.get('legacy_id') or t['id']}) "
                     f"{lst + ' · ' if lst and lst != 'Inbox' else ''}{t['title']}" +
                     (f"  (due {t['due'].replace('T', ' ')})" if t.get('due') else ''))
        for d in (t.get('notes') or '').strip().splitlines():
            lines.append('      ' + d)
    return '\n'.join(lines) if lines else '(no tasks)'


def ai_action(request: dict) -> str:
    org = organizer()
    action = request['action']
    if action == 'read':
        tasks = org.todo.tasks()
        open_ = sum(1 for t in tasks if not t['done'])
        return (f'{len(tasks)} tasks ({open_} open), notes {len(org.todo.notes())} characters\n\n'
                '### Tasks (#number [x = done] (id) list · text, then details)\n' + as_text(org) +
                f"\n\n### Notes\n{org.todo.notes() or '(empty)'}")
    if action == 'add_task':
        fields = {'title': request.get('text', '') or 'New task', 'notes': request.get('details', '')}
        category = request.get('category', '')
        if category:
            lst = org.todo.list_by_name(category) or org.todo.add_list(category)
            fields['list'] = lst['id']
        t = org.add_task(fields, created_by='assistant')
        return f"Added #{len(org.todo.tasks())} ({t['id']}) {t['title']}"
    if action == 'update_task':
        t = org.todo.find(request.get('item', ''))
        fields = {}
        if 'text' in request:
            fields['title'] = request['text'].strip() or t['title']
        if 'details' in request:
            fields['notes'] = request['details']
        if 'append' in request:
            fields['notes'] = (t.get('notes', '').rstrip() + '\n' + request['append']).strip()
        if 'category' in request and request['category']:
            lst = org.todo.list_by_name(request['category']) or org.todo.add_list(request['category'])
            fields['list'] = lst['id']
        if fields:
            t = org.update_task(t['id'], **fields)
        if 'done' in request:
            t = org.complete_task(t['id'], bool(request['done']))
        return f"Updated ({t['id']}) {t['title']}" + (' — done' if t['done'] else '')
    if action == 'delete_task':
        t = org.todo.find(request.get('item', ''))
        org.delete_task(t['id'])
        return f"Deleted ({t['id']}) {t['title']}"
    if action in ('set_notes', 'append_notes', 'write_notes'):
        text = request.get('text', '')
        if action == 'append_notes':
            text = (org.todo.notes().rstrip() + '\n\n' + text).strip()
        org.todo.set_notes(text)
        org.changed('todo')
        return 'Notes extended' if action == 'append_notes' else f'Notes saved ({len(text)} characters)'
    raise ValueError(f'Unknown to-do action {action}')
