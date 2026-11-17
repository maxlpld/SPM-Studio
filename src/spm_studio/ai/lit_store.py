"""Secrets of the literature sources (Zotero key, Consensus sign-in), Qt-free.

The operating system's keyring is used when there is one. On systems without a
keyring (common on minimal Linux desktops) the value is written to a private
file, readable by the user only (mode 0600), in SPM Studio's settings folder.

Why a file here, when model API keys stay in memory without a keyring: the
literature tools also run in a separate helper process (the command line and
the MCP server the agent calls), which cannot see the memory of the app, and a
sign-in that is lost at every restart is exactly what made Zotero and Consensus
look "not connected" in 0.0.5 / 0.0.6. Both secrets are read-only and can be
revoked at any time on zotero.org / consensus.app.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SERVICE = 'spm-studio-ai'


def _file() -> Path:
    from .config import base_dir
    return base_dir() / 'literature_secrets.json'


def _keyring():
    try:
        from .security import CredentialStore
        return CredentialStore().keyring
    except Exception:
        return None


def _read_file() -> dict:
    try:
        data = json.loads(_file().read_text(encoding='utf8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_file(data: dict):
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        try:
            path.unlink()
        except OSError:
            pass
        return
    temp = path.with_name(path.name + '.tmp')
    # Created with owner-only permissions from the start (no window where it is world-readable).
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf8') as handle:
        json.dump(data, handle, indent=2)
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(path)


def put(name: str, value: str) -> str:
    """Store a secret; returns where it went, in words for the user."""
    ring = _keyring()
    if ring is not None:
        try:
            ring.set_password(SERVICE, name, value)
            data = _read_file()
            if data.pop(name, None) is not None:      # one copy only
                _write_file(data)
            return 'stored in the system keyring'
        except Exception:
            pass
    data = _read_file()
    data[name] = value
    _write_file(data)
    return 'stored in a private file of your account (no system keyring on this computer)'


def get(name: str) -> str:
    ring = _keyring()
    if ring is not None:
        try:
            value = ring.get_password(SERVICE, name)
            if value:
                return value
        except Exception:
            pass
    value = _read_file().get(name)
    return value if isinstance(value, str) else ''


def clear(name: str):
    ring = _keyring()
    if ring is not None:
        try:
            ring.delete_password(SERVICE, name)
        except Exception:
            pass
    data = _read_file()
    if data.pop(name, None) is not None:
        _write_file(data)
