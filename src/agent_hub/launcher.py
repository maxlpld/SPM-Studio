"""Desktop launcher for the standalone app (Qt-free): ``agent-hub`` command + application menu entry.

The launcher runs the Python that has Agent Hub installed (its own virtual environment, see INSTALL.md), so it
does not depend on any host application.
"""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

ICON = Path(__file__).resolve().parent / 'resources' / 'agent-hub.svg'


def create(python: str | None = None) -> list[Path]:
    python = python or sys.executable
    created = []
    if os.name == 'nt':
        pythonw = Path(python).with_name('pythonw.exe')
        exe = str(pythonw if pythonw.is_file() else python)
        target = Path(os.environ.get('APPDATA', Path.home())) / 'Microsoft' / 'Windows' / 'Start Menu' / \
            'Programs' / 'Agent Hub.cmd'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f'@echo off\r\nstart "" "{exe}" -m agent_hub\r\n', encoding='utf8')
        return [target]
    bin_dir = Path.home() / '.local' / 'bin'
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / 'agent-hub'
    script.write_text(f'#!/bin/sh\nexec {shlex.quote(python)} -m agent_hub "$@"\n', encoding='utf8')
    script.chmod(0o755)
    created.append(script)
    if sys.platform == 'darwin':
        command = Path.home() / 'Applications' / 'Agent Hub.command'
        command.parent.mkdir(parents=True, exist_ok=True)
        command.write_text(f'#!/bin/sh\nexec {shlex.quote(str(script))}\n', encoding='utf8')
        command.chmod(0o755)
        created.append(command)
        return created
    apps = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'applications'
    apps.mkdir(parents=True, exist_ok=True)
    desktop = apps / 'agent-hub.desktop'
    desktop.write_text('[Desktop Entry]\nType=Application\nName=Agent Hub\n'
                       'Comment=AI assistant: chats, projects, several agents at once\n'
                       f'Exec={script}\n' + (f'Icon={ICON}\n' if ICON.is_file() else '') +
                       'Terminal=false\nCategories=Utility;Office;Development;\nStartupWMClass=agent-hub\n',
                       encoding='utf8')
    created.append(desktop)
    return created
