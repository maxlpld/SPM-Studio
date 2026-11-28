"""Where Agent Hub keeps its data (Qt-free).

One folder per user, shared by every client on the computer (standalone app, SPM Studio panel, detached
window), so they see the same chats, projects and settings:

* ``$AGENT_HUB_DATA`` when set (tests, portable installs);
* Linux: ``$XDG_DATA_HOME/agent-hub`` (``~/.local/share/agent-hub``);
* macOS: ``~/Library/Application Support/Agent Hub``;
* Windows: ``%APPDATA%\\Agent Hub``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get('AGENT_HUB_DATA', '').strip()
    if env:
        folder = Path(env).expanduser()
    elif sys.platform == 'win32':
        folder = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'Agent Hub'
    elif sys.platform == 'darwin':
        folder = Path.home() / 'Library' / 'Application Support' / 'Agent Hub'
    else:
        folder = Path(os.environ.get('XDG_DATA_HOME', '') or Path.home() / '.local' / 'share') / 'agent-hub'
    folder.mkdir(parents=True, exist_ok=True)
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    return folder


def hub_dir() -> Path:
    """Chats, projects, settings (the 'store')."""
    folder = data_dir() / 'hub'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def models_dir() -> Path:
    from .host import current
    folder = current().models_dir() or data_dir() / 'models'
    Path(folder).mkdir(parents=True, exist_ok=True)
    return Path(folder)
