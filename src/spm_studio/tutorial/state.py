"""Tutorial progress (separate from scientific profiles): ``<config>/tutorial.json``."""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULTS = {
    'started': False,
    'completed': False,
    'skipped': False,
    'resume_position': 0,
    'last_seen_app_version': '',
    'whats_new_seen': '',
    'welcome_shown': False,
}


def file() -> Path:
    from spm_studio.core import paths
    return paths.config_dir() / 'tutorial.json'


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        stored = json.loads(file().read_text(encoding='utf8'))
        if isinstance(stored, dict):
            data.update({k: stored[k] for k in DEFAULTS if k in stored})
    except (OSError, ValueError):
        pass
    return data


def save(data: dict) -> dict:
    clean = {k: data.get(k, v) for k, v in DEFAULTS.items()}
    path = file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(clean, indent=1), encoding='utf8')
    tmp.replace(path)
    return clean


def update(**changes) -> dict:
    data = load()
    data.update(changes)
    return save(data)


def startup_action(version: str) -> str | None:
    """What to offer when the main window is ready: ``'welcome'``, ``'whats_new'`` or ``None``.

    The welcome is offered once (new and existing installs alike); after a skip or a finished tour it never
    comes back by itself. After an update, a short *what's new* tour is offered once for that version.
    """
    data = load()
    previous = data['last_seen_app_version']
    action = None
    if not data['welcome_shown'] and not (data['started'] or data['completed'] or data['skipped']):
        action = 'welcome'
    elif previous and previous != version and data['whats_new_seen'] != version:
        action = 'whats_new'
    update(last_seen_app_version=version)
    return action


def whats_new_pages(changelog: str, version: str, limit: int = 6) -> list[dict]:
    """One page per ``### heading`` of this version's CHANGELOG section: ``{'title', 'text'}``."""
    from spm_studio.core.updates import changelog_sections
    body = ''
    for name, text in changelog_sections(changelog):
        if name.strip() == version:
            body = text
            break
    pages = []
    for block in re.split(r'^###\s+', body, flags=re.M)[1:]:
        title, _, rest = block.partition('\n')
        bullets = [re.sub(r'\*\*|`', '', line[2:].strip()) for line in rest.splitlines() if line.startswith('- ')]
        if title.strip():
            pages.append({'title': title.strip(), 'text': '\n'.join('• ' + b for b in bullets[:3])})
    if not pages and body.strip():
        bullets = [re.sub(r'\*\*|`', '', line[2:].strip()) for line in body.splitlines() if line.startswith('- ')]
        pages = [{'title': f'New in {version}', 'text': '\n'.join('• ' + b for b in bullets[:5])}]
    return pages[:limit]
