"""Chats and projects of the Agent Hub (Qt-free, plain JSON files).

Layout under the hub folder::

    projects.json          [{id, name, instructions, notes, keywords, folder, builtin, created}]
    chats/<id>.json        {id, title, project, backend, created, updated, messages: [...], ...}

Every write is atomic (temporary file + rename), so a crash never leaves half a chat.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

MAX_MESSAGES = 400
MAX_CONTENT = 120_000

# Built-in projects come from the host (``Host.default_projects()``); these are the standalone ones.
from .host import GENERAL_PROJECTS as DEFAULT_PROJECTS  # noqa: E402


def _now() -> float:
    return round(time.time(), 3)


def _atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding='utf8'))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def auto_title(text: str, limit: int = 48) -> str:
    """A short chat title from the first message (first line, no markdown)."""
    line = next((ln.strip() for ln in str(text or '').splitlines() if ln.strip()), '')
    line = re.sub(r'[`*_#>\[\]]+', '', line)
    line = re.sub(r'\s+', ' ', line).strip()
    if len(line) > limit:
        cut = line[:limit].rsplit(' ', 1)[0]
        line = (cut if len(cut) > limit // 2 else line[:limit]).rstrip(' ,.;:') + '…'
    return line or 'New chat'


class Store:
    """All chats and projects of one user."""

    def __init__(self, root: Path, defaults: list[dict] | None = None):
        self.root = Path(root)
        self.defaults = [dict(p) for p in (defaults if defaults is not None else DEFAULT_PROJECTS)]
        self.chat_dir = self.root / 'chats'
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        self._projects_file = self.root / 'projects.json'
        self._cache: dict[str, dict] = {}
        if not self._projects_file.is_file():
            self.restore_default_projects()

    # ------------------------------------------------------------------ projects
    def projects(self) -> list[dict]:
        found = _read(self._projects_file, [])
        return [p for p in found if isinstance(p, dict) and p.get('id') and p.get('name')]

    def project(self, project_id: str) -> dict | None:
        return next((p for p in self.projects() if p['id'] == project_id), None)

    def project_by_name(self, name: str) -> dict | None:
        key = str(name or '').strip().lower()
        return next((p for p in self.projects() if p['name'].lower() == key or p['id'] == key), None)

    def _save_projects(self, projects: list[dict]):
        _atomic(self._projects_file, projects)

    def restore_default_projects(self) -> int:
        """Add the built-in projects that are missing (never touches existing ones)."""
        projects = self.projects()
        have = {p['id'] for p in projects}
        added = 0
        for p in self.defaults:
            if p['id'] not in have:
                projects.append({**p, 'notes': '', 'builtin': True, 'created': _now()})
                added += 1
        self._save_projects(projects)
        return added

    def add_project(self, name: str, instructions: str = '', folder: str = '') -> dict:
        name = str(name or '').strip()[:80]
        if not name:
            raise ValueError('A project needs a name')
        if self.project_by_name(name):
            raise ValueError(f'A project named “{name}” already exists')
        project = {'id': 'p' + uuid.uuid4().hex[:10], 'name': name, 'instructions': instructions, 'notes': '',
                   'keywords': [], 'folder': folder, 'builtin': False, 'created': _now()}
        self._save_projects(self.projects() + [project])
        return project

    def update_project(self, project_id: str, **fields) -> dict:
        projects = self.projects()
        for p in projects:
            if p['id'] == project_id:
                for key in ('name', 'instructions', 'notes', 'folder', 'keywords', 'permissions', 'color',
                            'archived'):
                    if key in fields:
                        value = fields[key]
                        if key == 'name':
                            value = str(value or '').strip()[:80]
                            if not value:
                                raise ValueError('A project needs a name')
                            other = self.project_by_name(value)
                            if other and other['id'] != project_id:
                                raise ValueError(f'A project named “{value}” already exists')
                        if key == 'keywords':
                            value = [str(k).strip().lower() for k in value if str(k).strip()][:60]
                        p[key] = value
                self._save_projects(projects)
                return p
        raise KeyError(project_id)

    def delete_project(self, project_id: str, delete_chats: bool = False) -> int:
        """Remove a project; its chats become unsorted (or are deleted). Returns the number of chats."""
        chats = self.chats(project=project_id)
        for chat in chats:
            if delete_chats:
                self.delete_chat(chat['id'])
            else:
                self.move_chat(chat['id'], '')
        self._save_projects([p for p in self.projects() if p['id'] != project_id])
        return len(chats)

    # ------------------------------------------------------------------ chats
    def _chat_path(self, chat_id: str) -> Path:
        if not re.fullmatch(r'[a-z0-9]{6,40}', chat_id or ''):
            raise ValueError('Invalid chat id')
        return self.chat_dir / f'{chat_id}.json'

    def new_chat(self, project: str = '', backend: str = 'auto', title: str = '') -> dict:
        chat = {'id': 'c' + uuid.uuid4().hex[:16], 'title': title or 'New chat', 'titled': bool(title),
                'project': project if project and self.project(project) else '', 'backend': backend,
                'created': _now(), 'updated': _now(), 'messages': [], 'sort_asked': False,
                'pinned': False, 'archived': False, 'mode': 'normal', 'links': {}}
        self.save_chat(chat)
        return chat

    def get_chat(self, chat_id: str) -> dict | None:
        if chat_id in self._cache:
            return self._cache[chat_id]
        try:
            data = _read(self._chat_path(chat_id), {})
        except ValueError:
            return None
        if not data.get('id'):
            return None
        data.setdefault('messages', [])
        self._cache[chat_id] = data
        return data

    def save_chat(self, chat: dict):
        chat['messages'] = [m for m in chat.get('messages', [])
                            if isinstance(m, dict) and m.get('role') in ('user', 'assistant', 'note')][-MAX_MESSAGES:]
        for m in chat['messages']:
            m['content'] = str(m.get('content', ''))[:MAX_CONTENT]
        _atomic(self._chat_path(chat['id']), chat)
        self._cache[chat['id']] = chat

    def chats(self, project: str | None = None, query: str = '', archived: bool | None = False) -> list[dict]:
        """Newest first (pinned first). ``project=None``: all; ``''``: unsorted only.
        ``archived``: False hides archived chats, True lists only them, None lists both."""
        out = []
        for path in self.chat_dir.glob('*.json'):
            chat = self.get_chat(path.stem)
            if not chat:
                continue
            if archived is not None and bool(chat.get('archived')) != archived:
                continue
            if project is not None and chat.get('project', '') != project:
                continue
            if query and not self._matches(chat, query):
                continue
            out.append(chat)
        out.sort(key=lambda c: (bool(c.get('pinned')), c.get('updated', 0)), reverse=True)
        return out

    @staticmethod
    def _matches(chat: dict, query: str) -> bool:
        q = query.lower().strip()
        if q in chat.get('title', '').lower():
            return True
        return any(q in m.get('content', '').lower() for m in chat.get('messages', [])[-60:])

    def rename_chat(self, chat_id: str, title: str):
        chat = self.get_chat(chat_id)
        if chat is None:
            raise KeyError(chat_id)
        chat['title'] = str(title or '').strip()[:120] or 'New chat'
        chat['titled'] = True
        self.save_chat(chat)

    def move_chat(self, chat_id: str, project_id: str):
        chat = self.get_chat(chat_id)
        if chat is None:
            raise KeyError(chat_id)
        if project_id and self.project(project_id) is None:
            raise KeyError(project_id)
        chat['project'] = project_id or ''
        chat['sort_asked'] = True
        self.save_chat(chat)

    def set_flag(self, chat_id: str, flag: str, value: bool):
        """``pinned`` or ``archived``."""
        if flag not in ('pinned', 'archived'):
            raise ValueError(flag)
        chat = self.get_chat(chat_id)
        if chat is None:
            raise KeyError(chat_id)
        chat[flag] = bool(value)
        self.save_chat(chat)

    def set_meta(self, chat_id: str, **fields):
        """Small per-chat fields kept with the chat: mode, links, spec, draft, backend."""
        chat = self.get_chat(chat_id)
        if chat is None:
            raise KeyError(chat_id)
        for key in ('mode', 'links', 'spec', 'draft', 'backend', 'budget'):
            if key in fields:
                chat[key] = fields[key]
        self.save_chat(chat)

    def edit_last_user(self, chat_id: str) -> str:
        """Remove the last user message (and the replies after it); return its text for editing."""
        chat = self.get_chat(chat_id)
        if chat is None:
            raise KeyError(chat_id)
        idx = max((i for i, m in enumerate(chat['messages']) if m['role'] == 'user'), default=-1)
        if idx < 0:
            return ''
        text = chat['messages'][idx]['content']
        chat['messages'] = chat['messages'][:idx]
        chat['seen_by'] = {}
        self.save_chat(chat)
        return text

    def drop_last_reply(self, chat_id: str) -> bool:
        """For "Regenerate": remove the replies after the last user message."""
        chat = self.get_chat(chat_id)
        if chat is None:
            raise KeyError(chat_id)
        idx = max((i for i, m in enumerate(chat['messages']) if m['role'] == 'user'), default=-1)
        if idx < 0 or idx == len(chat['messages']) - 1:
            return False
        chat['messages'] = chat['messages'][:idx + 1]
        chat['seen_by'] = {}
        self.save_chat(chat)
        return True

    def delete_chat(self, chat_id: str):
        self._cache.pop(chat_id, None)
        try:
            self._chat_path(chat_id).unlink()
        except (OSError, ValueError):
            pass

    def add_message(self, chat_id: str, role: str, content: str, **extra) -> dict:
        chat = self.get_chat(chat_id)
        if chat is None:
            raise KeyError(chat_id)
        message = {'role': role, 'content': str(content), 'ts': _now(), **extra}
        chat['messages'].append(message)
        chat['updated'] = _now()
        if role == 'user' and not chat.get('titled'):
            chat['title'] = auto_title(content)
            chat['titled'] = True
        self.save_chat(chat)
        return message

    # ------------------------------------------------------------------ import
    def import_classic(self, histories: dict[str, list[dict]]) -> int:
        """Copy the classic panel's conversations once (``{name: messages}``); returns how many."""
        marker = self.root / '.classic_imported'
        if marker.exists():
            return 0
        count = 0
        for name, messages in histories.items():
            kept = [{'role': m['role'], 'content': m['content'], 'ts': 0} for m in messages
                    if m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str)]
            if not kept:
                continue
            chat = self.new_chat(title=f'{name} (classic panel)')
            chat['messages'] = kept
            self.save_chat(chat)
            count += 1
        marker.write_text(time.strftime('%Y-%m-%d %H:%M'), encoding='utf8')
        return count
