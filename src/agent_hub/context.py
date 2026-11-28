"""Instructions sent with every conversation of the hub (Qt-free).

The host's own context (for SPM Studio: folders, guides, literature, editors) comes first, unchanged;
the hub adds: the project, the access rules of this conversation, how approvals work, GitHub, and how the
agent may propose to move the chat to another project.
"""
from __future__ import annotations

import re
from pathlib import Path

MOVE_TAG = re.compile(r'<spm-hub\s+move\s*=\s*"([^"]{1,80})"\s*/?>', re.I)


def app_folders() -> list[Path]:
    from .host import current
    try:
        return [Path(p) for p in current().app_folders()]
    except Exception:
        return []


def workspace_for(project: dict | None, hub_root: Path) -> Path:
    """The project's working folder: a host folder (e.g. SPM Studio scripts), a custom absolute folder, or
    the hub's own ``workspaces/<project>`` folder."""
    from .host import current
    key = (project or {}).get('folder', '') or 'general'
    try:
        folder = current().workspace(key)
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            return Path(folder)
    except Exception:
        pass
    if key != 'general':
        folder = Path(key).expanduser()
        if folder.is_absolute():
            folder.mkdir(parents=True, exist_ok=True)
            return folder
    slug = re.sub(r'[^a-z0-9]+', '-', (project or {}).get('id', 'general').lower()).strip('-') or 'general'
    folder = Path(hub_root) / 'workspaces' / slug
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _public_context(workspace: Path, tools: bool) -> str:
    from .host import current
    try:
        return current().base_context(workspace, tools) or ''
    except Exception:
        return ''


def hub_text(project: dict | None, projects: list[dict], conf: dict, roots: list[Path], tools: bool,
             github_login: str = '', github_text: str = '') -> str:
    name = (project or {}).get('name', 'No project (unsorted chats)')
    from .host import current
    host_label = current().label
    intro = ('You run in Agent Hub, the user\'s general assistant'
             + (f' (inside {host_label})' if host_label != 'Agent Hub' else '') +
             '. You help with science, programming, writing and everyday tasks: e-mails and letters (write drafts '
             'the user copies), administrative questions, planning, translations, research. Answer in the '
             'language the user writes in.')
    parts = ['# Agent Hub — this conversation', intro,
             f'\n## Project: {name}']
    if project and project.get('instructions'):
        parts.append(project['instructions'].strip())
    if project and project.get('notes', '').strip():
        parts.append('Project notes from the user (remember them in this project):\n' + project['notes'].strip())
    if tools:
        parts.append('\n## Access in this conversation')
        if conf.get('full_access'):
            parts.append('FULL ACCESS is on: your file and shell tools run without asking the user. Still never '
                         'delete data the user did not ask you to delete, and never touch credentials.')
        else:
            parts.append('You may create and change files without asking in:\n' +
                         '\n'.join(f'- `{r}`' for r in roots) +
                         '\nReading, searching and check commands (ls, git status, py_compile …) never need '
                         'approval. For anything else (other commands, git push, deleting, files elsewhere) '
                         'simply use the tool: Agent Hub shows the request to the user (Allow / Always allow '
                         '/ Deny) and waits for the answer.')
        parts.append('Never tell the user you are "not allowed" to work somewhere before trying the tool. If an '
                     'action is denied, say what you wanted to do and why; the user can widen the access in '
                     'Agent Hub › Settings › Permissions.')
    else:
        parts.append('\n## No file or shell tools in this conversation\nThis model answers in chat only. Give '
                     'complete file contents the user can copy, or suggest switching this chat to an agent '
                     '(Pi, Claude Code, Codex) with the model picker at the top of the chat.')
    others = [p['name'] for p in projects if not project or p['id'] != project.get('id')]
    if others:
        parts.append('\n## Keeping chats sorted\nIf this conversation clearly belongs to another project, write '
                     'on a line of its own: `<spm-hub move="Project name"/>` (one of: ' +
                     '; '.join(others[:20]) + '). Agent Hub moves the chat (after asking the user unless '
                     'automatic sorting is on). Do it at most once and only when it is obvious.')
    if tools and github_text:
        parts.append('\n' + github_text)
    return '\n'.join(parts)


def build(chat: dict, project: dict | None, projects: list[dict], conf: dict, hub_root: Path,
          workspace: Path, roots: list[Path], tools: bool, github_text: str = '') -> Path:
    base = _public_context(workspace, tools) if tools else ''
    text = (base + '\n\n' if base else '') + hub_text(project, projects, conf, roots, tools,
                                                      github_text=github_text)
    folder = Path(hub_root) / 'context'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{chat['id']}.md"
    target.write_text(text, encoding='utf8')
    return target


def recap(messages: list[dict], limit_chars: int = 9000) -> str:
    """The conversation so far, for a model that did not see it (switched backend)."""
    kept, size = [], 0
    for m in reversed([m for m in messages if m.get('role') in ('user', 'assistant')]):
        text = m['content'].strip()
        if len(text) > 2500:
            text = text[:2500] + ' […]'
        size += len(text)
        if size > limit_chars and kept:
            break
        kept.append(('User' if m['role'] == 'user' else 'Assistant') + ': ' + text)
    if not kept:
        return ''
    return ('[Conversation so far in this chat, answered by another model — continue from it]\n' +
            '\n\n'.join(reversed(kept)) + '\n[End of the conversation so far]\n\n')


def find_moves(reply: str) -> list[str]:
    return MOVE_TAG.findall(reply or '')


def strip_tags(reply: str) -> str:
    return MOVE_TAG.sub('', reply or '').strip()
