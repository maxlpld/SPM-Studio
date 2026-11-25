"""Projects and crash recovery (v0.0.20) — Qt-free.

A **project** is a folder. Its state is one readable JSON file in that folder::

    <project folder>/spm-studio-project.json

It records everything needed to continue where you stopped: the listed scans (relative to the folder when they
are inside it, so the folder can be moved or shared), the scan and channel that were open, and for every scan its
display (colour map, contrast), processing steps, crop, visible channels, titles, profile, masks and drawn
selections, plus the analysis tool and its settings. Scan files are never written.

The file is saved automatically a few seconds after each change (atomic write: ``.tmp`` then rename, the previous
version kept as ``.bak``). Scans opened without a project live in an *unsaved session*, kept in
``<data>/recovery/session.json``. ``<data>/recovery/state.json`` remembers which projects were open, which one was
active and whether SPM Studio was closed normally, so that the next start (or the start after a crash) reopens them.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_FILE = 'spm-studio-project.json'
FORMAT = 'spm-studio-project'
VERSION = 1


def recovery_dir() -> Path:
    from . import paths
    folder = paths.data_dir() / 'recovery'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def session_file() -> Path:
    return recovery_dir() / 'session.json'


def state_file() -> Path:
    return recovery_dir() / 'state.json'


def project_file(folder) -> Path:
    folder = Path(folder)
    return folder if folder.suffix.lower() == '.json' and folder.name.endswith(PROJECT_FILE) else folder / PROJECT_FILE


def is_project_folder(folder) -> bool:
    try:
        return (Path(folder) / PROJECT_FILE).is_file()
    except OSError:
        return False


# ---------------------------------------------------------------------- atomic JSON
def write_json_atomic(path: Path, data: dict, *, backup: bool = True) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False, default=_json_default) + '\n'
    import threading
    tmp = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    with open(tmp, 'w', encoding='utf8') as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    if backup and path.is_file():
        try:
            bak = path.with_name(path.name + '.bak')
            if bak.exists():
                bak.unlink()
            os.replace(path, bak)
        except OSError:
            pass
    # Windows: a virus scanner may hold the target for a moment.
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))
    return path


def read_json(path: Path) -> dict | None:
    """The file, or its ``.bak`` copy when the file is damaged (e.g. power cut while writing)."""
    path = Path(path)
    for candidate in (path, path.with_name(path.name + '.bak')):
        try:
            data = json.loads(candidate.read_text(encoding='utf8'))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            continue
    return None


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if hasattr(value, 'tolist'):
        return value.tolist()
    if hasattr(value, '__dataclass_fields__'):
        return asdict(value)
    return str(value)


# ---------------------------------------------------------------------- paths inside a project
def to_stored_path(path: str, folder: Path | None) -> str:
    """Relative (with ``/``) when inside the project folder, absolute otherwise."""
    p = Path(path)
    if folder is not None:
        try:
            return p.resolve().relative_to(Path(folder).resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return str(p)


def from_stored_path(text: str, folder: Path | None) -> str:
    p = Path(text)
    if not p.is_absolute() and folder is not None:
        p = Path(folder) / p
    try:
        return str(p.resolve())
    except OSError:
        return str(p)


# ---------------------------------------------------------------------- (de)serialisation of model objects
def style_to_dict(style) -> dict:
    return asdict(style)


def style_from_dict(data: dict):
    from .models import ImageStyle
    fields = ImageStyle.__dataclass_fields__
    return ImageStyle(**{k: v for k, v in (data or {}).items() if k in fields})


def steps_to_list(steps) -> list:
    return [asdict(step) for step in steps or []]


def steps_from_list(items) -> list:
    from .models import ProcessingStep
    out = []
    for item in items or []:
        if isinstance(item, dict) and item.get('operation'):
            out.append(ProcessingStep(str(item['operation']), dict(item.get('params') or {}),
                                      bool(item.get('enabled', True))))
    return out


def crop_to_dict(region) -> dict | None:
    return region.to_dict() if region is not None else None


def crop_from_dict(data):
    if not data:
        return None
    from .cropping import CropRegion
    from .models import Geometry
    return CropRegion(float(data['left']), float(data['top']), float(data['right']), float(data['bottom']),
                      Geometry.from_dict(data['reference_geometry']))


def roi_from_dict(data):
    if not data:
        return None
    from .models import ROI
    return ROI(str(data['kind']), tuple(tuple(float(v) for v in p) for p in data.get('points_px', [])))


def key_text(key: tuple) -> str:
    """(path, channel, trace) → JSON object key."""
    return '\x1f'.join(str(part) for part in key)


def key_from_text(text: str) -> tuple:
    return tuple(text.split('\x1f'))


# ---------------------------------------------------------------------- project document
def new_document(name: str = '', folder: Path | None = None) -> dict:
    now = datetime.now().isoformat(timespec='seconds')
    return {'format': FORMAT, 'version': VERSION, 'id': str(uuid.uuid4()),
            'name': name or (Path(folder).name if folder else 'Unsaved session'),
            'created': now, 'saved': now, 'scans': [], 'current': None, 'state': {}}


def default_name(folder) -> str:
    return Path(folder).name or str(folder)


def load_project(folder) -> dict | None:
    data = read_json(project_file(folder))
    if data is None or data.get('format') != FORMAT:
        return None
    if int(data.get('version', 1)) > VERSION:
        raise ValueError(f'This project was saved by a newer SPM Studio (format {data.get("version")}).')
    data.setdefault('state', {})
    data.setdefault('scans', [])
    return data


def save_project(folder, document: dict) -> Path:
    document = dict(document)
    document['saved'] = datetime.now().isoformat(timespec='seconds')
    return write_json_atomic(project_file(folder), document)


# ---------------------------------------------------------------------- open projects across restarts
def load_state() -> dict:
    data = read_json(state_file()) or {}
    data.setdefault('open', [])          # [{'folder': str|None, 'id': str}]
    data.setdefault('active', 0)
    data.setdefault('clean_exit', True)
    data.setdefault('recent', [])
    return data


def save_state(**changes) -> dict:
    data = load_state()
    data.update(changes)
    try:
        write_json_atomic(state_file(), data, backup=False)
    except OSError:
        pass
    return data


def add_recent(folder) -> list:
    folder = str(Path(folder))
    recent = [f for f in load_state().get('recent', []) if f != folder]
    recent.insert(0, folder)
    save_state(recent=recent[:12])
    return recent[:12]


def summary(document: dict) -> dict[str, Any]:
    return {'name': document.get('name', ''), 'scans': len(document.get('scans', [])),
            'saved': document.get('saved', '')}
