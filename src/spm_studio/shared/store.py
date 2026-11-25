"""Versioned local research index. Does NOT replace SPM/LaTeX original files.

Separate-process SQLite readers/writers use WAL and BEGIN IMMEDIATE, with
multi-process locking delegated to SQLite.  Events are durable, not a claimed
live authenticated IPC service.  Never mirror a live SQLite file using cloud
synchronization.  Graph facts from this index are *not* learned propositions.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, os, sqlite3, uuid


def utcnow(): return datetime.now(timezone.utc).isoformat()


def default_root() -> Path:
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'spm-studio-ai'/'records'


def fingerprint(path: Path, chunk_size=1024*1024) -> str:
    """Full SHA256; not a filename-based cache key."""
    digest=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(chunk_size),b''): digest.update(block)
    return digest.hexdigest()


def canonical_json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)


def input_fingerprint(source_hash, channel, direction, params, roi, processing, geometry, algorithm):
    data=dict(source_hash=source_hash,channel=channel,direction=direction,parameters=params,
              roi=roi,processing=processing,geometry=geometry,algorithm=algorithm)
    return hashlib.sha256(canonical_json(data).encode('utf-8')).hexdigest()


_WAL_READY: set = set()


class ResearchStore:
    VERSION=1
    def __init__(self,root=None):
        self.root=Path(root) if root is not None else default_root()
        self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/'research.sqlite3'
        self._create()

    @contextmanager
    def connection(self,write=False):
        con=sqlite3.connect(self.db,timeout=30,isolation_level=None)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA busy_timeout=30000')
        con.execute('PRAGMA foreign_keys=ON')
        if str(self.db) not in _WAL_READY:      # v0.0.20: persistent setting, needed once per process
            con.execute('PRAGMA journal_mode=WAL')
            _WAL_READY.add(str(self.db))
        try:
            if write:con.execute('BEGIN IMMEDIATE')
            yield con
            if write:con.execute('COMMIT')
        except BaseException:
            if write:con.execute('ROLLBACK')
            raise
        finally:con.close()

    def _create(self):
        with self.connection() as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,sha256 TEXT NOT NULL,
                bytes INTEGER NOT NULL,mtime_ns INTEGER NOT NULL,updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS scans_hash ON scans(sha256);
            CREATE TABLE IF NOT EXISTS analysis_runs(
                id TEXT PRIMARY KEY,scan_id TEXT NOT NULL,module_id TEXT NOT NULL,
                module_version TEXT NOT NULL,input_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,created_at TEXT NOT NULL,
                data_json TEXT NOT NULL,preferred INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(scan_id) REFERENCES scans(id));
            CREATE INDEX IF NOT EXISTS run_index ON analysis_runs(scan_id,module_id,created_at);
            CREATE INDEX IF NOT EXISTS run_cache ON analysis_runs(input_fingerprint,status);
            CREATE TABLE IF NOT EXISTS annotations(
                id TEXT PRIMARY KEY,run_id TEXT NOT NULL,text TEXT NOT NULL,
                epistemic_status TEXT NOT NULL,created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES analysis_runs(id));
            CREATE TABLE IF NOT EXISTS events(
                id TEXT PRIMARY KEY,type TEXT NOT NULL,payload TEXT NOT NULL,
                created_at TEXT NOT NULL,source TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS topics(
                id TEXT PRIMARY KEY,parent_id TEXT,name TEXT NOT NULL,
                review_state TEXT NOT NULL DEFAULT 'disabled',
                settings_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS flashcards(
                id TEXT PRIMARY KEY,topic_id TEXT NOT NULL,front TEXT NOT NULL,
                back TEXT NOT NULL,source_json TEXT NOT NULL,created_at TEXT NOT NULL,
                scheduler_json TEXT NOT NULL DEFAULT '{}',FOREIGN KEY(topic_id) REFERENCES topics(id));
            CREATE TABLE IF NOT EXISTS reviews(
                id TEXT PRIMARY KEY,card_id TEXT NOT NULL,grade INTEGER NOT NULL,
                reviewed_at TEXT NOT NULL,state_before TEXT NOT NULL,state_after TEXT NOT NULL,
                FOREIGN KEY(card_id) REFERENCES flashcards(id));
            CREATE TABLE IF NOT EXISTS manuscripts(
                id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,title TEXT NOT NULL,
                modified_at TEXT NOT NULL);
            ''')
            con.execute('INSERT OR IGNORE INTO schema_meta VALUES (?,?)',('schema_version',str(self.VERSION)))
            version=con.execute('SELECT value FROM schema_meta WHERE key=?',('schema_version',)).fetchone()
            if version and int(version['value'])>self.VERSION:
                raise RuntimeError(f'Research index schema {version["value"]} is newer than supported {self.VERSION}')

    def snapshot(self,destination):
        """Create a consistent SQLite backup safe for cloud-sync after completion."""
        dest=Path(destination).expanduser().resolve()
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest==self.db.resolve():raise ValueError('Backup must be separate')
        tmp=dest.with_name(dest.name+'.incomplete')
        try:
            with self.connection() as con,sqlite3.connect(tmp) as backup:
                con.backup(backup)
            os.replace(tmp,dest)
        finally:
            if tmp.exists():tmp.unlink()
        return dest

    def scan_id(self,path, full_hash=None):
        path=Path(path).expanduser().resolve()
        st=path.stat()
        with self.connection() as con:
            row=con.execute('SELECT * FROM scans WHERE path=?',(str(path),)).fetchone()
            if row and row['bytes']==st.st_size and row['mtime_ns']==st.st_mtime_ns:
                return row['id'],row['sha256']
        hash_=full_hash or fingerprint(path)
        with self.connection(write=True) as con:
            row=con.execute('SELECT * FROM scans WHERE path=?',(str(path),)).fetchone()
            if row:
                con.execute('UPDATE scans SET sha256=?,bytes=?,mtime_ns=?,updated_at=? WHERE id=?',
                    (hash_,st.st_size,st.st_mtime_ns,utcnow(),row['id']))
                return row['id'],hash_
            # Resolve renames only if the old file no longer exists. Two actual
            # copies with matching bytes get independent scan IDs.
            matches=con.execute('SELECT * FROM scans WHERE sha256=?',(hash_,)).fetchall()
            for match in matches:
                if not Path(match['path']).exists():
                    try:
                        con.execute('UPDATE scans SET path=?,bytes=?,mtime_ns=?,updated_at=? WHERE id=?',
                            (str(path),st.st_size,st.st_mtime_ns,utcnow(),match['id']))
                        return match['id'],hash_
                    except sqlite3.IntegrityError:pass
            id_=str(uuid.uuid4())
            con.execute('INSERT INTO scans VALUES (?,?,?,?,?,?)',
                (id_,str(path),hash_,st.st_size,st.st_mtime_ns,utcnow()))
            return id_,hash_

    def scan_by_path(self,path):
        # Fast selection lookup: no whole-file hashing on GUI thread.
        path=str(Path(path).expanduser().resolve())
        with self.connection() as con:
            r=con.execute('SELECT * FROM scans WHERE path=?',(path,)).fetchone()
        return dict(r) if r else None

    def save_run(self,data):
        payload=dict(data)
        id_=payload.get('result_id') or str(uuid.uuid4())
        payload['result_id']=id_
        payload.setdefault('schema_version',1)
        payload.setdefault('created_at',utcnow())
        with self.connection(write=True) as con:
            con.execute('''INSERT INTO analysis_runs(id,scan_id,module_id,module_version,
                input_fingerprint,status,created_at,data_json,preferred) VALUES (?,?,?,?,?,?,?,?,0)''',
                (id_,payload['scan_id'],payload['module_id'],payload['module_version'],
                 payload['input_fingerprint'],payload['status'],payload['created_at'],canonical_json(payload)))
            self._event(con,{'completed':'analysis.completed','stale':'analysis.stale','synthetic':'analysis.synthetic_fixture_imported'}.get(payload['status'],'analysis.failed'),
                {'result_id':id_,'scan_id':payload['scan_id'],'module_id':payload['module_id']},'spm-studio')
        return id_

    def _event(self,con,type_,payload,source):
        con.execute('INSERT INTO events VALUES(?,?,?,?,?)',
            (str(uuid.uuid4()),type_,canonical_json(payload),utcnow(),source))

    def recent_events(self,limit=100):
        with self.connection() as con:
            return [dict(r) for r in con.execute('SELECT * FROM events ORDER BY created_at DESC LIMIT ?', (limit,))]

    def runs(self,scan_id=None,module_id=None):
        sql='SELECT data_json,preferred FROM analysis_runs WHERE 1=1';args=[]
        if scan_id:sql+=' AND scan_id=?';args.append(scan_id)
        if module_id:sql+=' AND module_id=?';args.append(module_id)
        sql+=' ORDER BY created_at DESC'
        with self.connection() as con: rows=con.execute(sql,args).fetchall()
        result=[]
        for r in rows:
            d=json.loads(r['data_json']);d['preferred']=bool(r['preferred']);result.append(d)
        return result

    def run(self,id_):
        with self.connection() as con:
            r=con.execute('SELECT data_json FROM analysis_runs WHERE id=?',(id_,)).fetchone()
        return json.loads(r['data_json']) if r else None

    def matching(self,scan_id,module_id,fingerprint_):
        with self.connection() as con:
            r=con.execute('''SELECT data_json FROM analysis_runs WHERE scan_id=? AND module_id=?
                AND input_fingerprint=? AND status='completed' ORDER BY created_at DESC LIMIT 1''',
                (scan_id,module_id,fingerprint_)).fetchone()
        return json.loads(r['data_json']) if r else None

    def prefer(self,run_id):
        with self.connection(write=True) as con:
            r=con.execute('SELECT scan_id,module_id FROM analysis_runs WHERE id=?',(run_id,)).fetchone()
            if not r:return
            con.execute('UPDATE analysis_runs SET preferred=0 WHERE scan_id=? AND module_id=?',tuple(r))
            con.execute('UPDATE analysis_runs SET preferred=1 WHERE id=?',(run_id,))

    def annotate(self,run_id,text,status='observation'):
        if status not in ('observation','interpretation','hypothesis','contradiction','uncertainty','confirmed_conclusion'):
            raise ValueError('Unsupported epistemic status')
        if not text.strip():raise ValueError('Empty comment')
        with self.connection(write=True) as con:
            id_=str(uuid.uuid4())
            con.execute('INSERT INTO annotations VALUES(?,?,?,?,?)',(id_,run_id,text,status,utcnow()))
            self._event(con,'note.approved',{'run_id':run_id,'note_id':id_,'status':status},'spm-studio')
        return id_

    def annotations(self,run_id):
        with self.connection() as con:
            return [dict(r) for r in con.execute('SELECT * FROM annotations WHERE run_id=? ORDER BY created_at',(run_id,))]

    def topics(self):
        with self.connection() as con:
            return [dict(r) for r in con.execute('SELECT * FROM topics ORDER BY name')]

    def topic(self,name,parent_id=None):
        with self.connection(write=True) as con:
            r=con.execute('SELECT id FROM topics WHERE name=? AND parent_id IS ?', (name,parent_id)).fetchone()
            if r:return r['id']
            id_=str(uuid.uuid4())
            con.execute('INSERT INTO topics(id,name,parent_id) VALUES(?,?,?)',(id_,name,parent_id))
            return id_

    def set_topic_state(self,topic_id,state):
        if state not in ('disabled','active','paused','stopped'):raise ValueError('Invalid topic state')
        with self.connection(write=True) as con:
            con.execute('UPDATE topics SET review_state=? WHERE id=?',(state,topic_id))
            self._event(con,'review.state_changed',{'topic_id':topic_id,'state':state},'knowledge-companion')

    def cards(self,topic_id):
        with self.connection() as con:
            return [dict(r) for r in con.execute('SELECT * FROM flashcards WHERE topic_id=? ORDER BY created_at',(topic_id,))]

    def create_card(self,topic_id,front,back,source=None):
        if not front.strip() or not back.strip():raise ValueError('Front/back are required')
        id_=str(uuid.uuid4())
        with self.connection(write=True) as con:
            con.execute('INSERT INTO flashcards VALUES(?,?,?,?,?,?,?)',
                (id_,topic_id,front,back,canonical_json(source or {}),utcnow(),'{}'))
        return id_

    def review(self,card_id,grade,before,after):
        if grade not in (1,2,3,4):raise ValueError('Invalid grade')
        with self.connection(write=True) as con:
            con.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?)',
                (str(uuid.uuid4()),card_id,grade,utcnow(),canonical_json(before),canonical_json(after)))
            con.execute('UPDATE flashcards SET scheduler_json=? WHERE id=?',(canonical_json(after),card_id))

    def register_manuscript(self,path,title):
        path=str(Path(path).expanduser().resolve())
        with self.connection(write=True) as con:
            row=con.execute('SELECT id FROM manuscripts WHERE path=?',(path,)).fetchone()
            id_=row['id'] if row else str(uuid.uuid4())
            con.execute('INSERT OR REPLACE INTO manuscripts VALUES(?,?,?,?)',(id_,path,title,utcnow()))
            self._event(con,'manuscript.indexed',{'id':id_,'path':path},'paper-studio')
            return id_

    def manuscripts(self):
        with self.connection() as con:
            return [dict(r) for r in con.execute('SELECT * FROM manuscripts ORDER BY modified_at DESC')]
