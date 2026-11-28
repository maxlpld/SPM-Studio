"""One-time copy of the classic assistant's state into Agent Hub (0.1.0). Only reads the old data; it never
changes or deletes it, so going back to 0.0.x keeps working with everything as it was.

Copied once (a marker ``spm_classic_migrated.json`` in the hub folder records when and what):

* conversations of the classic panel (``<data>/ai/sessions``) → chats “… (classic panel)”;
* the model it used → the hub's default model for new chats (the Pi, Claude Code, Codex or the direct API
  connection keep their own settings, which the hub reads in place);
* docked / floating window → docked panel or detached window;
* the to-do list (``<data>/todo/todo.json``) is copied by the organizer the first time it opens.

Nothing else needs copying: Consensus, Zotero, the Pi set-up and API keys stay in the same settings file and
keyring and are edited from the Agent Hub settings now.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

MARKER = 'spm_classic_migrated.json'


def default_backend(old: dict) -> str:
    backend = str(old.get('backend') or 'none')
    if backend in ('pi', 'claude-code', 'codex'):
        return backend
    if backend not in ('none', '') and old.get('model'):
        return f"api:{old.get('provider') or backend}/{old['model']}"
    return 'auto'


def run(core, host, main_settings=None) -> dict:
    """Returns {'chats': n, 'default_backend': key or '', 'detached': bool} (empty dict when already done)."""
    marker = Path(core.root) / MARKER
    if marker.exists():
        return {}
    result = {'chats': 0, 'default_backend': '', 'detached': False}
    try:
        result['chats'] = core.store.import_classic(host.classic_histories())
    except Exception:
        pass
    try:
        from spm_studio.ai.config import load
        old = load()
    except Exception:
        old = {}
    hub_settings = Path(core.root) / 'settings.json'
    fresh = not hub_settings.exists() or core.conf.get('default_backend', 'auto') == 'auto'
    key = default_backend(old)
    if fresh and key != 'auto':
        conf = dict(core.conf)
        conf['default_backend'] = key
        core.save_settings(conf)
        result['default_backend'] = key
    try:
        from PySide6.QtCore import QSettings
        hub_q = QSettings('SPM Studio', 'Agent Hub')
        if main_settings is not None and hub_q.value('detached') is None:
            floating = str(main_settings.value('ai_dock_floating', 'false')).lower() == 'true'
            hub_q.setValue('detached', floating)
            result['detached'] = floating
    except Exception:
        pass
    marker.write_text(json.dumps({'at': time.strftime('%Y-%m-%d %H:%M:%S'), **result}, indent=1),
                      encoding='utf8')
    if result['chats']:
        core.chatsChanged.emit()
    return result
