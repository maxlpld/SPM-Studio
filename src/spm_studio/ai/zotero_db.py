"""Read a Zotero library straight from its database file (read-only, Qt-free).

Works with every Zotero version (5, 6, 7, 8…), whether Zotero is running or
not, and needs nothing to be enabled in Zotero: no local API, no account, no
key. The database is opened read-only and *immutable*, so SPM Studio can never
change or lock it; if Zotero happens to be writing at that instant, the read is
retried on a private temporary copy.

Only what the assistant needs is read: bibliographic fields, creators, tags,
collections, child notes, attachment names and the text Zotero indexed for
PDFs (``storage/<key>/.zotero-ft-cache``).
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

SKIP_TYPES = ('attachment', 'note', 'annotation')


class ZoteroDbError(RuntimeError):
    pass


# ----------------------------------------------------------------------- locate
def _profile_dirs() -> list[Path]:
    home = Path.home()
    if sys.platform.startswith('win'):
        roots = [Path(os.environ.get('APPDATA', home / 'AppData' / 'Roaming')) / 'Zotero' / 'Zotero' / 'Profiles']
    elif sys.platform == 'darwin':
        roots = [home / 'Library' / 'Application Support' / 'Zotero' / 'Profiles']
    else:
        roots = [home / '.zotero' / 'zotero',
                 home / 'snap' / 'zotero-snap' / 'common' / '.zotero' / 'zotero',
                 home / '.var' / 'app' / 'org.zotero.Zotero' / '.zotero' / 'zotero']
    found = []
    for root in roots:
        try:
            found += [p for p in root.iterdir() if p.is_dir()]
        except OSError:
            continue
    return found


def _custom_data_dirs() -> list[Path]:
    """Data folders chosen in Zotero (Settings › Advanced › Files and Folders)."""
    found = []
    for profile in _profile_dirs():
        try:
            prefs = (profile / 'prefs.js').read_text(encoding='utf8', errors='replace')
        except OSError:
            continue
        match = re.search(r'user_pref\("extensions\.zotero\.dataDir",\s*"((?:[^"\\]|\\.)*)"\)', prefs)
        if match:
            found.append(Path(match.group(1).replace('\\\\', '\\').replace('\\"', '"')))
    return found


def candidate_dirs(configured: str = '') -> list[Path]:
    home = Path.home()
    dirs = []
    if configured:
        dirs.append(Path(configured).expanduser())
    if os.environ.get('ZOTERO_DATA_DIR'):
        dirs.append(Path(os.environ['ZOTERO_DATA_DIR']).expanduser())
    dirs += _custom_data_dirs()
    dirs += [home / 'Zotero',
             home / 'snap' / 'zotero-snap' / 'common' / 'Zotero',
             home / '.var' / 'app' / 'org.zotero.Zotero' / 'data' / 'Zotero',
             home / 'Documents' / 'Zotero']
    unique = []
    for d in dirs:
        if d not in unique:
            unique.append(d)
    return unique


def find_data_dir(configured: str = ''):
    """The Zotero data folder (the one containing ``zotero.sqlite``), or ``None``."""
    for folder in candidate_dirs(configured):
        try:
            if (folder / 'zotero.sqlite').is_file():
                return folder
        except OSError:
            continue
    return None


# ------------------------------------------------------------------------- open
class Library:
    """One read-only view of ``zotero.sqlite``. Use as a context manager."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / 'zotero.sqlite'
        if not self.path.is_file():
            raise ZoteroDbError(f'No Zotero database in {self.data_dir}')
        self._temp = None
        self.db = self._open()

    def _open(self):
        uri = self.path.resolve().as_uri() + '?mode=ro&immutable=1'
        try:
            db = sqlite3.connect(uri, uri=True, timeout=2)
            db.execute('SELECT COUNT(*) FROM items').fetchone()
            return db
        except sqlite3.Error:
            # Zotero was writing: read a private copy instead (never the original in write mode).
            self._temp = tempfile.mkdtemp(prefix='spm-zotero-')
            copy = Path(self._temp) / 'zotero.sqlite'
            try:
                shutil.copy2(self.path, copy)
                db = sqlite3.connect(copy.resolve().as_uri() + '?mode=ro&immutable=1', uri=True, timeout=2)
                db.execute('SELECT COUNT(*) FROM items').fetchone()
                return db
            except (sqlite3.Error, OSError) as exc:
                self.close()
                raise ZoteroDbError(f'The Zotero database could not be read ({exc}).') from exc

    def close(self):
        try:
            if getattr(self, 'db', None) is not None:
                self.db.close()
        except sqlite3.Error:
            pass
        if self._temp:
            shutil.rmtree(self._temp, ignore_errors=True)
            self._temp = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------ helpers
    def _library_id(self) -> int:
        try:
            row = self.db.execute("SELECT libraryID FROM libraries WHERE type='user'").fetchone()
            if row:
                return int(row[0])
        except sqlite3.Error:
            pass
        return 1

    def _has(self, table: str) -> bool:
        return self.db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is not None

    def _record(self, item_id: int, key: str, type_name: str) -> dict:
        """Item in the shape of the Zotero web API ``data`` object (what ``summarize`` expects)."""
        data = {'key': key, 'itemType': type_name}
        for name, value in self.db.execute(
                'SELECT f.fieldName, v.value FROM itemData d JOIN fields f USING(fieldID) '
                'JOIN itemDataValues v USING(valueID) WHERE d.itemID=?', (item_id,)):
            data[name] = value
        # Dates are stored as "2019-03-01 March 2019": keep the readable part.
        if isinstance(data.get('date'), str):
            parts = data['date'].split(' ', 1)
            data['date'] = parts[1] if len(parts) == 2 and re.match(r'\d{4}-\d\d-\d\d$', parts[0]) and parts[1] \
                else parts[0]
        data['creators'] = [{'firstName': first or '', 'lastName': last or ''} for first, last in self.db.execute(
            'SELECT c.firstName, c.lastName FROM itemCreators ic JOIN creators c USING(creatorID) '
            'WHERE ic.itemID=? ORDER BY ic.orderIndex', (item_id,))]
        data['tags'] = [{'tag': name} for (name,) in self.db.execute(
            'SELECT g.name FROM itemTags t JOIN tags g USING(tagID) WHERE t.itemID=? ORDER BY g.name', (item_id,))]
        return data

    def _item_row(self, key: str):
        row = self.db.execute('SELECT i.itemID, i.key, t.typeName FROM items i JOIN itemTypes t USING(itemTypeID) '
                              'WHERE i.key=? AND i.libraryID=?', (str(key).strip(), self._library_id())).fetchone()
        if row is None:
            raise ZoteroDbError('Not found in the Zotero library.')
        return row

    # ------------------------------------------------------------------- public
    def count(self) -> int:
        marks = ','.join('?' * len(SKIP_TYPES))
        return int(self.db.execute(
            f'SELECT COUNT(*) FROM items i JOIN itemTypes t USING(itemTypeID) WHERE i.libraryID=? '
            f'AND t.typeName NOT IN ({marks}) AND i.itemID NOT IN (SELECT itemID FROM deletedItems)',
            (self._library_id(), *SKIP_TYPES)).fetchone()[0])

    def search(self, query: str, limit: int = 10, collection: str = '') -> list[dict]:
        """Items matching every word of ``query`` in a field, a creator, a tag or a child note."""
        marks = ','.join('?' * len(SKIP_TYPES))
        sql = [f'SELECT i.itemID, i.key, t.typeName FROM items i JOIN itemTypes t USING(itemTypeID) '
               f'WHERE i.libraryID=? AND t.typeName NOT IN ({marks}) '
               f'AND i.itemID NOT IN (SELECT itemID FROM deletedItems)']
        args = [self._library_id(), *SKIP_TYPES]
        for word in [w for w in re.split(r'\s+', str(query or '').strip()) if w][:12]:
            like = '%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            sql.append("AND (EXISTS(SELECT 1 FROM itemData d JOIN itemDataValues v USING(valueID) "
                       "WHERE d.itemID=i.itemID AND v.value LIKE ? ESCAPE '\\') "
                       "OR EXISTS(SELECT 1 FROM itemCreators ic JOIN creators c USING(creatorID) "
                       "WHERE ic.itemID=i.itemID AND (c.lastName LIKE ? ESCAPE '\\' OR c.firstName LIKE ? ESCAPE '\\')) "
                       "OR EXISTS(SELECT 1 FROM itemTags g JOIN tags n USING(tagID) "
                       "WHERE g.itemID=i.itemID AND n.name LIKE ? ESCAPE '\\') "
                       "OR EXISTS(SELECT 1 FROM itemNotes o WHERE o.parentItemID=i.itemID AND o.note LIKE ? ESCAPE '\\'))")
            args += [like] * 5
        if collection:
            sql.append('AND i.itemID IN (SELECT ci.itemID FROM collectionItems ci JOIN collections c '
                       'USING(collectionID) WHERE c.key=?)')
            args.append(str(collection).strip())
        sql.append('ORDER BY i.dateModified DESC LIMIT ?')
        args.append(max(1, min(int(limit or 10), 200)))
        rows = self.db.execute(' '.join(sql), args).fetchall()
        return [self._record(*row) for row in rows]

    def item(self, key: str) -> tuple[dict, list[dict]]:
        """(item data, children) — children are notes and attachments in web-API shape."""
        item_id, key, type_name = self._item_row(key)
        children = []
        for (note,) in self.db.execute(
                'SELECT n.note FROM itemNotes n WHERE n.parentItemID=? AND n.itemID NOT IN '
                '(SELECT itemID FROM deletedItems)', (item_id,)):
            children.append({'data': {'itemType': 'note', 'note': note or ''}})
        for child_id, child_key, content_type in self.db.execute(
                'SELECT a.itemID, i.key, a.contentType FROM itemAttachments a JOIN items i USING(itemID) '
                'WHERE a.parentItemID=? AND a.itemID NOT IN (SELECT itemID FROM deletedItems)', (item_id,)):
            title = self.db.execute(
                "SELECT v.value FROM itemData d JOIN fields f USING(fieldID) JOIN itemDataValues v USING(valueID) "
                "WHERE d.itemID=? AND f.fieldName='title'", (child_id,)).fetchone()
            children.append({'data': {'itemType': 'attachment', 'key': child_key, 'title': title[0] if title else '',
                                      'contentType': content_type or ''}})
        return self._record(item_id, key, type_name), children

    def collections(self) -> list[dict]:
        rows = self.db.execute(
            'SELECT c.key, c.collectionName, p.key FROM collections c LEFT JOIN collections p '
            'ON p.collectionID=c.parentCollectionID WHERE c.libraryID=? ORDER BY c.collectionName',
            (self._library_id(),)).fetchall()
        return [{'key': key, 'name': name, 'parent': parent or ''} for key, name, parent in rows]

    def fulltext(self, key: str):
        """(attachment key, text) of the item itself or of its first indexed attachment; ``None`` if none."""
        item_id, key, _type = self._item_row(key)
        keys = [key] + [k for (k,) in self.db.execute(
            'SELECT i.key FROM itemAttachments a JOIN items i USING(itemID) WHERE a.parentItemID=?', (item_id,))]
        for candidate in keys:
            cache = self.data_dir / 'storage' / candidate / '.zotero-ft-cache'
            try:
                if cache.is_file():
                    text = cache.read_text(encoding='utf8', errors='replace')
                    if text.strip():
                        return candidate, text
            except OSError:
                continue
        return None
