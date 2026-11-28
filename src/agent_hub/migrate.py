"""Safe, versioned migration of older stores into the shared one (Qt-free).

* A legacy folder named by the host (``Host.legacy_data_dirs()``) is **copied**, never
  moved or modified, so the previous version keeps working on its own data (rollback).
* It runs only when the shared store has no chats yet; existing newer data is never overwritten.
* A marker ``.migrated.json`` records what was copied and when; ``backups/`` keeps a copy of any shared file
  replaced by a schema upgrade.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

SCHEMA = 2           # 1: Agent Hub 0.1 · 2: + pinned/archived/mode/links per chat


def _has_chats(folder: Path) -> bool:
    return any((folder / 'chats').glob('*.json'))


def migrate_legacy(root: Path, legacy_dirs: list) -> dict:
    root = Path(root)
    marker = root / '.migrated.json'
    if marker.exists():
        try:
            return json.loads(marker.read_text(encoding='utf8'))
        except (OSError, ValueError):
            return {'copied': ''}
    result = {'copied': '', 'schema': SCHEMA, 'at': time.strftime('%Y-%m-%d %H:%M:%S')}
    if not _has_chats(root):
        for folder in [Path(p) for p in legacy_dirs or []]:
            if folder.is_dir() and _has_chats(folder) and folder.resolve() != root.resolve():
                for name in ('chats', 'projects.json', 'settings.json', 'usage.jsonl', 'workspaces'):
                    src, dst = folder / name, root / name
                    if not src.exists() or dst.exists() and name != 'chats':
                        continue
                    if src.is_dir():
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                result['copied'] = str(folder)
                break
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(result, indent=1), encoding='utf8')
    return result
