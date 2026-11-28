"""Shared helpers of the organizer stores (Qt-free): atomic JSON files that tolerate a second writer.

Calendar and to-do data may be opened by two processes at once (SPM Studio's calendar window and the
standalone Agent Hub, for example). Every record carries an ``updated`` time; before each write the store
re-reads the file when it changed on disk and keeps, per record, the newer version. Deletions are kept as
tombstones (``deleted``) for 30 days so that a stale copy never brings a deleted item back.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

TOMBSTONE_DAYS = 30


def now_ts() -> float:
    return round(time.time(), 3)


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec='seconds')


def new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:14]


def atomic_write(path: Path, data) -> None:
    path = Path(path)
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
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:           # Windows: file briefly held by an indexer or antivirus
                time.sleep(0.05 * (attempt + 1))
        else:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf8')
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path, default):
    try:
        data = json.loads(Path(path).read_text(encoding='utf8'))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


class RecordFile:
    """``{'schema': n, <collections of {id: record}>, 'deleted': {id: ts}, 'meta': {...}}`` on disk."""
    collections: tuple = ()
    schema = 1

    def __init__(self, path: Path):
        self.path = Path(path)
        self._mtime = None
        self.data = self._empty()
        self.reload()

    def _empty(self) -> dict:
        return {'schema': self.schema, 'deleted': {}, 'meta': {}, **{c: {} for c in self.collections}}

    def _disk(self) -> dict:
        found = read_json(self.path, {})
        out = self._empty()
        if isinstance(found, dict):
            for c in self.collections:
                if isinstance(found.get(c), dict):
                    out[c] = {k: v for k, v in found[c].items() if isinstance(v, dict)}
            if isinstance(found.get('deleted'), dict):
                out['deleted'] = dict(found['deleted'])
            if isinstance(found.get('meta'), dict):
                out['meta'] = dict(found['meta'])
        return out

    def _stat(self):
        try:
            st = self.path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def reload(self) -> bool:
        """Re-read when the file changed on disk; returns True when something was read."""
        stat = self._stat()
        if stat is not None and stat == self._mtime:
            return False
        self.data = self._disk() if stat is not None else self._empty()
        self._mtime = stat
        return True

    def save(self):
        """Merge with a newer copy on disk (newer record wins), drop old tombstones, write atomically."""
        if self._stat() != self._mtime and self._stat() is not None:
            disk = self._disk()
            deleted = {**disk['deleted'], **self.data['deleted']}
            for c in self.collections:
                merged = dict(disk[c])
                for key, rec in self.data[c].items():
                    other = merged.get(key)
                    if other is None or float(rec.get('updated', 0)) >= float(other.get('updated', 0)):
                        merged[key] = rec
                for key, ts in deleted.items():
                    rec = merged.get(key)
                    if rec is not None and float(rec.get('updated', 0)) <= float(ts):
                        merged.pop(key)
                self.data[c] = merged
            self.data['deleted'] = deleted
            self.data['meta'] = {**disk['meta'], **self.data['meta']}
        limit = time.time() - TOMBSTONE_DAYS * 86400
        self.data['deleted'] = {k: v for k, v in self.data['deleted'].items() if float(v) >= limit}
        atomic_write(self.path, self.data)
        self._mtime = self._stat()

    def tombstone(self, key: str):
        self.data['deleted'][key] = now_ts()
