"""SPM Studio 0.0.7 — literature sources that connect from Settings and work in every chat mode.

* Zotero read from its database file (no setting in Zotero, any version), automatic choice
  between the app and the file, clear diagnostics.
* Consensus: sign-in done by SPM Studio itself (OAuth + PKCE on a loopback address) and search
  through Consensus' MCP server — tested against a local stand-in that follows the same specs.
* Lookups requested by the assistant in plain text, so they work without agent tools.
* Secrets survive a restart also on computers without a keyring.

No Qt needed.
"""
import hashlib
import base64
import io
import json
import os
import sqlite3
import stat
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    monkeypatch.delenv('ZOTERO_DATA_DIR', raising=False)
    monkeypatch.delenv('ZOTERO_API_KEY', raising=False)
    monkeypatch.delenv('CONSENSUS_API_KEY', raising=False)
    (tmp_path / 'home').mkdir()
    # No keyring in these tests: secrets go to SPM Studio's private file.
    from spm_studio.ai import lit_store
    monkeypatch.setattr(lit_store, '_keyring', lambda: None)
    return tmp_path


# ------------------------------------------------------------------ Zotero database
SCHEMA = """
CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT);
CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INT, dateAdded TEXT, dateModified TEXT,
                    libraryID INT, key TEXT);
CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value);
CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
CREATE TABLE itemCreators (itemID INT, creatorID INT, creatorTypeID INT, orderIndex INT);
CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE itemTags (itemID INT, tagID INT);
CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INT, note TEXT, title TEXT);
CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INT, linkMode INT, contentType TEXT, path TEXT);
CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT, parentCollectionID INT,
                          libraryID INT, key TEXT);
CREATE TABLE collectionItems (collectionID INT, itemID INT, orderIndex INT);
"""


def make_zotero(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / 'zotero.sqlite')
    db.executescript(SCHEMA)
    db.execute("INSERT INTO libraries VALUES (1,'user'),(2,'group')")
    db.executemany('INSERT INTO itemTypes VALUES (?,?)', [(1, 'journalArticle'), (2, 'attachment'), (3, 'note'),
                                                         (4, 'book')])
    fields = ['title', 'abstractNote', 'date', 'publicationTitle', 'DOI', 'url', 'volume', 'pages']
    db.executemany('INSERT INTO fields VALUES (?,?)', list(enumerate(fields, 1)))
    values = []

    def value(text):
        values.append(text)
        db.execute('INSERT INTO itemDataValues VALUES (?,?)', (len(values), text))
        return len(values)

    def item(item_id, type_id, key, modified, library=1, **data):
        db.execute('INSERT INTO items VALUES (?,?,?,?,?,?)', (item_id, type_id, '2024-01-01', modified, library, key))
        for name, text in data.items():
            db.execute('INSERT INTO itemData VALUES (?,?,?)', (item_id, fields.index(name) + 1, value(text)))

    item(1, 1, 'AAAA1111', '2024-05-01', title='Kelvin probe force microscopy of graphene',
         abstractNote='We measure the contact potential difference.', date='2019-03-01 March 2019',
         publicationTitle='Phys. Rev. B', DOI='10.1000/kpfm', volume='99')
    item(2, 1, 'BBBB2222', '2024-06-01', title='Scanning tunnelling spectroscopy of 100% twisted_bilayers',
         date='2021-00-00 2021', publicationTitle='Nature')
    item(3, 4, 'CCCC3333', '2024-07-01', title='Deleted book about graphene')
    item(4, 2, 'PDF00001', '2024-05-02', title='Meyer 2019.pdf')
    item(5, 3, 'NOTE0001', '2024-05-03')
    item(6, 1, 'GROUP001', '2024-08-01', library=2, title='Graphene paper of a group library')
    db.execute('INSERT INTO deletedItems VALUES (3)')
    db.executemany('INSERT INTO creators VALUES (?,?,?)', [(1, 'Ernst', 'Meyer'), (2, 'Thilo', 'Glatzel'),
                                                          (3, 'Ada', 'Lovelace')])
    db.executemany('INSERT INTO itemCreators VALUES (?,?,?,?)', [(1, 2, 1, 1), (1, 1, 1, 0), (2, 3, 1, 0)])
    db.executemany('INSERT INTO tags VALUES (?,?)', [(1, 'KPFM'), (2, 'STM')])
    db.executemany('INSERT INTO itemTags VALUES (?,?)', [(1, 1), (2, 2)])
    db.execute("INSERT INTO itemNotes VALUES (5,1,'<p>Check <b>figure 3</b> for the work function</p>','n')")
    db.execute("INSERT INTO itemAttachments VALUES (4,1,0,'application/pdf','storage:Meyer 2019.pdf')")
    db.executemany('INSERT INTO collections VALUES (?,?,?,?,?)', [(1, 'KPFM papers', None, 1, 'COLL0001'),
                                                                  (2, 'Graphene', 1, 1, 'COLL0002')])
    db.execute('INSERT INTO collectionItems VALUES (2,1,0)')
    db.commit()
    db.close()
    storage = folder / 'storage' / 'PDF00001'
    storage.mkdir(parents=True)
    (storage / '.zotero-ft-cache').write_text('Full text of the paper. ' * 20, encoding='utf8')
    return folder


def test_zotero_is_read_from_its_database_without_any_setting(home, monkeypatch):
    from spm_studio.ai import literature, zotero_db
    folder = make_zotero(home / 'home' / 'Zotero')
    before = (folder / 'zotero.sqlite').read_bytes()
    assert zotero_db.find_data_dir() == folder                      # found in the usual place
    conf = {'zotero_mode': 'database'}
    found = literature.zotero_search('graphene', conf=conf)
    assert found == [{'key': 'AAAA1111', 'type': 'journalArticle', 'title': 'Kelvin probe force microscopy of graphene',
                      'creators': 'Meyer, Glatzel', 'year': '2019', 'publication': 'Phys. Rev. B',
                      'doi': '10.1000/kpfm', 'tags': ['KPFM']}]         # not the deleted book, not the group library
    # every word must match; creators, tags and notes are searched; LIKE wildcards are literal
    assert [i['key'] for i in literature.zotero_search('meyer kelvin', conf=conf)] == ['AAAA1111']
    assert [i['key'] for i in literature.zotero_search('STM', conf=conf)] == ['BBBB2222']
    assert [i['key'] for i in literature.zotero_search('work function', conf=conf)] == ['AAAA1111']
    assert literature.zotero_search('meyer tunnelling', conf=conf) == []
    assert [i['key'] for i in literature.zotero_search('100%', conf=conf)] == ['BBBB2222']
    assert literature.zotero_search('1_0', conf=conf) == []
    assert [i['key'] for i in literature.zotero_search('', conf=conf)] == ['BBBB2222', 'AAAA1111']   # newest first
    assert [i['key'] for i in literature.zotero_search('', collection='COLL0002', conf=conf)] == ['AAAA1111']
    assert literature.zotero_search("x'; DROP TABLE items;--", conf=conf) == []
    item = literature.zotero_item('AAAA1111', conf=conf)
    assert item['abstract'] == 'We measure the contact potential difference.' and item['volume'] == '99'
    assert item['notes'] == ['Check  figure 3  for the work function']
    assert item['attachments'] == [{'key': 'PDF00001', 'title': 'Meyer 2019.pdf', 'type': 'application/pdf'}]
    assert literature.zotero_collections(conf=conf) == [{'key': 'COLL0002', 'name': 'Graphene', 'parent': 'COLL0001'},
                                                        {'key': 'COLL0001', 'name': 'KPFM papers', 'parent': ''}]
    text = literature.zotero_fulltext('AAAA1111', max_chars=1000, conf=conf)       # through its PDF
    assert text['key'] == 'PDF00001' and text['text'].startswith('Full text') and text['truncated'] is False
    with pytest.raises(literature.LiteratureError, match='no indexed full text'):
        literature.zotero_fulltext('BBBB2222', conf=conf)
    with pytest.raises(literature.LiteratureError, match='Not found'):
        literature.zotero_item('ZZZZ9999', conf=conf)
    status = literature.zotero_status(conf)
    assert status['connected'] and status['items'] == 2 and status['via'] == 'database'
    # strictly read-only: the file is byte-identical and no journal was left behind
    assert (folder / 'zotero.sqlite').read_bytes() == before
    assert sorted(p.name for p in folder.iterdir()) == ['storage', 'zotero.sqlite']


def test_zotero_data_folder_is_found_in_other_places(home, monkeypatch):
    from spm_studio.ai import literature, zotero_db
    assert zotero_db.find_data_dir() is None
    with pytest.raises(literature.LiteratureError, match='No Zotero database'):
        literature.zotero_search('x', conf={'zotero_mode': 'database'})
    # a folder chosen in Zotero itself (profile preference)
    custom = make_zotero(home / 'elsewhere' / "My Zotero's data")
    profile = home / 'home' / '.zotero' / 'zotero' / 'abcd.default'
    profile.mkdir(parents=True)
    escaped = str(custom).replace('\\', '\\\\').replace('"', '\\"')
    (profile / 'prefs.js').write_text(f'user_pref("extensions.zotero.useDataDir", true);\n'
                                      f'user_pref("extensions.zotero.dataDir", "{escaped}");\n', encoding='utf8')
    monkeypatch.setattr(zotero_db.sys, 'platform', 'linux')
    assert zotero_db.find_data_dir() == custom
    # the folder chosen in SPM Studio wins; the environment variable works too
    chosen = make_zotero(home / 'chosen')
    assert zotero_db.find_data_dir(str(chosen)) == chosen
    assert literature.zotero_status({'zotero_mode': 'database', 'zotero_data_dir': str(chosen)})['connected']
    monkeypatch.setenv('ZOTERO_DATA_DIR', str(chosen))
    assert zotero_db.find_data_dir() == chosen


def test_automatic_mode_uses_the_app_when_it_answers_else_the_file(home, monkeypatch):
    from spm_studio.ai import literature
    make_zotero(home / 'home' / 'Zotero')
    monkeypatch.setattr(literature, 'ZOTERO_LOCAL', 'http://127.0.0.1:9/api')          # no app
    monkeypatch.setattr(literature, 'ZOTERO_CONNECTOR', 'http://127.0.0.1:9/connector/ping')
    conf = {'zotero_mode': 'auto'}
    assert literature.zotero_status(conf)['via'] == 'database'
    assert literature.zotero_search('kelvin', conf=conf)[0]['key'] == 'AAAA1111'
    detected = literature.detect_zotero(conf)
    assert detected['found'] and not detected['app'] and detected['items'] == 2
    assert detected['app_hint'] == 'The Zotero app is not running.'
    # with the app answering, it is preferred (it also searches the indexed full text)
    calls = []

    def fake_get(url, headers, timeout=20, raw=False):
        calls.append(url)
        return [{'key': 'APP00001', 'data': {'key': 'APP00001', 'itemType': 'book', 'title': 'From the app'}}]
    monkeypatch.setattr(literature, '_get', fake_get)
    assert literature.zotero_search('kelvin', conf=conf)[0]['key'] == 'APP00001'
    assert literature.zotero_status(conf)['via'] == 'app'
    assert all(u.startswith('http://127.0.0.1:9/api/users/0/') for u in calls)
    # nothing at all on the computer: one clear sentence
    monkeypatch.undo()


def test_nothing_found_is_explained(home, monkeypatch):
    from spm_studio.ai import literature
    monkeypatch.setattr(literature, 'ZOTERO_LOCAL', 'http://127.0.0.1:9/api')
    monkeypatch.setattr(literature, 'ZOTERO_CONNECTOR', 'http://127.0.0.1:9/connector/ping')
    status = literature.zotero_status({'zotero_mode': 'auto'})
    assert not status['connected'] and 'No Zotero library was found' in status['message']
    assert not literature.detect_zotero({'zotero_mode': 'off'})['found']


class _OldZotero(BaseHTTPRequestHandler):
    version = '6.0.36'
    api_status = 404

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith('/connector/ping'):
            self.send_response(200)
            self.send_header('X-Zotero-Version', self.version)
            self.end_headers()
            self.wfile.write(b'<html>Zotero is running</html>')
        else:
            self.send_response(self.api_status)
            self.end_headers()
            self.wfile.write(b'Local API is not enabled')


def test_app_that_does_not_answer_is_diagnosed(home, monkeypatch):
    from spm_studio.ai import literature
    server = HTTPServer(('127.0.0.1', 0), _OldZotero)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    monkeypatch.setattr(literature, 'ZOTERO_LOCAL', base + '/api')
    monkeypatch.setattr(literature, 'ZOTERO_CONNECTOR', base + '/connector/ping')
    try:
        message = literature.zotero_status({'zotero_mode': 'local'})['message']
        assert 'Zotero 6.0.36 is running' in message and 'database file' in message
        monkeypatch.setattr(_OldZotero, 'version', '7.0.11')
        monkeypatch.setattr(_OldZotero, 'api_status', 403)
        message = literature.zotero_status({'zotero_mode': 'local'})['message']
        assert 'Allow other applications' in message
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------------- secrets
def test_secrets_survive_a_restart_without_a_keyring(home):
    from spm_studio.ai import lit_store, literature
    from spm_studio.ai.config import base_dir
    where = lit_store.put('zotero', 'ZOTEROKEY123')
    assert 'private file' in where
    secret_file = base_dir() / 'literature_secrets.json'
    assert secret_file.is_file()
    if os.name != 'nt':
        assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
    # a separate process (the helper the agent runs) reads it: that failed before 0.0.7
    lit_store.put('other', 'x')
    assert literature.zotero_api_key() == 'ZOTEROKEY123'
    lit_store.clear('zotero')
    assert literature.zotero_api_key() == '' and lit_store.get('other') == 'x'
    lit_store.clear('other')
    assert not secret_file.exists()
    # the secrets are never in the ordinary settings file
    from spm_studio.ai.config import load, save
    conf = load()
    conf['zotero_mode'] = 'web'
    conf['zotero_library_id'] = '42'
    save(conf)
    lit_store.put('zotero', 'ZOTEROKEY123')
    assert 'ZOTEROKEY123' not in (base_dir() / 'settings.json').read_text(encoding='utf8')


def test_keyring_is_preferred_when_there_is_one(home, monkeypatch):
    from spm_studio.ai import lit_store
    lit_store.put('zotero', 'old-file-value')

    class Ring:
        data = {}

        def set_password(self, service, name, value):
            self.data[(service, name)] = value

        def get_password(self, service, name):
            return self.data.get((service, name))

        def delete_password(self, service, name):
            self.data.pop((service, name), None)
    ring = Ring()
    monkeypatch.setattr(lit_store, '_keyring', lambda: ring)
    assert lit_store.get('zotero') == 'old-file-value'              # still readable after a keyring appears
    assert lit_store.put('zotero', 'new') == 'stored in the system keyring'
    assert ring.data == {('spm-studio-ai', 'zotero'): 'new'} and lit_store.get('zotero') == 'new'
    assert not lit_store._file().exists()                           # one copy only
    lit_store.clear('zotero')
    assert lit_store.get('zotero') == ''


# ----------------------------------------------------------------------- Consensus
class _Consensus(BaseHTTPRequestHandler):
    """Stand-in for consensus.app: OAuth discovery, registration, token and the MCP endpoint."""
    state = {}

    def log_message(self, *args):
        pass

    def _json(self, status, body, headers=None):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        base = f'http://127.0.0.1:{self.server.server_port}'
        if self.path == '/.well-known/oauth-authorization-server':
            self._json(200, {'issuer': base, 'authorization_endpoint': base + '/oauth/authorize/',
                             'token_endpoint': base + '/oauth/token/',
                             'registration_endpoint': base + '/oauth/register/',
                             'code_challenge_methods_supported': ['S256'], 'scopes_supported': ['search']})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        s = type(self).state
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path == '/oauth/register/':
            s['registration'] = json.loads(body)
            self._json(201, {'client_id': 'client-123', **s['registration']})
        elif self.path == '/oauth/token/':
            form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode()).items()}
            s.setdefault('token_requests', []).append(form)
            if form.get('grant_type') == 'authorization_code':
                expected = base64.urlsafe_b64encode(hashlib.sha256(form.get('code_verifier', '').encode()).digest()) \
                    .rstrip(b'=').decode()
                if form.get('code') != 'CODE-1' or expected != s.get('challenge') or form.get('client_id') != 'client-123':
                    return self._json(400, {'error': 'invalid_grant', 'error_description': 'PKCE check failed'})
                self._json(200, {'access_token': 'ACCESS-1', 'refresh_token': 'REFRESH-1', 'expires_in': s.get('ttl', 3600),
                                 'token_type': 'Bearer', 'scope': 'search'})
            elif form.get('grant_type') == 'refresh_token' and form.get('refresh_token') == 'REFRESH-1':
                self._json(200, {'access_token': 'ACCESS-2', 'expires_in': 3600, 'token_type': 'Bearer'})
            else:
                self._json(400, {'error': 'invalid_grant'})
        elif self.path == '/mcp':
            s.setdefault('mcp', []).append((dict(self.headers), json.loads(body)))
            token = self.headers.get('Authorization', '')
            if token not in ('Bearer ' + t for t in s.get('valid', ('ACCESS-1', 'ACCESS-2', 'KEY-9'))):
                return self._json(401, {'error': 'invalid_token'})
            message = json.loads(body)
            method = message.get('method')
            if 'id' not in message:
                self.send_response(202)
                self.end_headers()
                return
            if method == 'initialize':
                result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'consensus', 'version': '1'}}
            elif method == 'tools/list':
                result = {'tools': [{'name': 'search', 'description': 'Search papers', 'inputSchema': {
                    'type': 'object', 'required': ['query'], 'properties': {'query': {'type': 'string'}}}}]}
            elif method == 'tools/call':
                query = message['params']['arguments'].get('query', '')
                result = {'content': [{'type': 'text', 'text': f'1. Meyer et al. (2019) on "{query}" — '
                                                               'https://consensus.app/papers/x'}], 'isError': False}
            else:
                return self._json(200, {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32601, 'message': 'no'}})
            answer = {'jsonrpc': '2.0', 'id': message['id'], 'result': result}
            if s.get('sse'):                                    # Streamable HTTP may answer as an event stream
                raw = ('event: message\ndata: ' + json.dumps(answer) + '\n\n').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                self._json(200, answer)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def consensus_site(home, monkeypatch):
    server = HTTPServer(('127.0.0.1', 0), _Consensus)
    _Consensus.state = {}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    from spm_studio.ai import consensus
    monkeypatch.setattr(consensus, 'MCP_URL', base + '/mcp')
    monkeypatch.setattr(consensus, 'DISCOVERY_URL', base + '/.well-known/oauth-authorization-server')
    monkeypatch.setattr(consensus, 'DEFAULT_ENDPOINTS', {k: 'http://127.0.0.1:9/none' for k in consensus.DEFAULT_ENDPOINTS})
    yield consensus
    server.shutdown()
    server.server_close()


def _browser_signs_in(url, state):
    """What the user's browser does: follow the authorisation URL, come back to the loopback address."""
    query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
    state['challenge'] = query['code_challenge']
    callback = query['redirect_uri'] + '?' + urllib.parse.urlencode({'code': 'CODE-1', 'state': query['state']})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(callback, timeout=5) as response:
        return query, response.read().decode()


def test_consensus_sign_in_from_the_app_and_search(consensus_site, home):
    consensus = consensus_site
    assert not consensus.signed_in() and consensus.status() == {'connected': False, 'message': 'Not signed in.'}
    flow = consensus.SignIn()
    url = flow.start()
    assert url.startswith(consensus.MCP_URL.replace('/mcp', '/oauth/authorize/?'))
    result = {}
    waiter = threading.Thread(target=lambda: result.update(flow.wait(timeout=10)))
    waiter.start()
    query, page = _browser_signs_in(url, _Consensus.state)
    waiter.join(10)
    assert 'Signed in to Consensus' in page and 'stored' in result
    # a public client on a loopback address, PKCE S256, only the "search" scope
    registration = _Consensus.state['registration']
    assert registration['token_endpoint_auth_method'] == 'none' and registration['client_name'] == 'SPM Studio'
    assert registration['redirect_uris'] == [query['redirect_uri']]
    assert query['redirect_uri'].startswith('http://127.0.0.1:') and query['redirect_uri'].endswith('/callback')
    assert query['code_challenge_method'] == 'S256' and query['scope'] == 'search' and query['response_type'] == 'code'
    assert query['resource'] == consensus.MCP_URL and len(query['state']) >= 20
    assert consensus.signed_in()
    # the search goes through the MCP endpoint with the token (JSON and event-stream answers)
    text = consensus.search('does KPFM resolve single dopants?')
    assert 'Meyer et al. (2019)' in text and 'single dopants' in text
    headers, call = _Consensus.state['mcp'][-1]
    assert headers['Authorization'] == 'Bearer ACCESS-1' and 'text/event-stream' in headers['Accept']
    assert call['method'] == 'tools/call' and call['params'] == {'name': 'search',
                                                               'arguments': {'query': 'does KPFM resolve single dopants?'}}
    assert [m[1].get('method') for m in _Consensus.state['mcp']][:3] == ['initialize', 'notifications/initialized',
                                                                        'tools/list']
    _Consensus.state['sse'] = True
    assert 'Meyer et al.' in consensus.search('graphene work function')
    assert consensus.status()['connected'] and 'search' in consensus.status()['message']
    # an expired or revoked token is renewed once, silently
    _Consensus.state['valid'] = ('ACCESS-2',)
    assert 'Meyer' in consensus.search('again')
    assert _Consensus.state['token_requests'][-1]['grant_type'] == 'refresh_token'
    assert json.loads(__import__('spm_studio.ai.lit_store', fromlist=['x']).get('consensus_oauth'))['refresh_token'] == 'REFRESH-1'
    # nothing secret in the settings file; sign out removes everything
    from spm_studio.ai.config import base_dir
    assert not (base_dir() / 'settings.json').exists() or 'ACCESS' not in (base_dir() / 'settings.json').read_text()
    consensus.sign_out()
    assert not consensus.signed_in()
    with pytest.raises(consensus.ConsensusError, match='not signed in'):
        consensus.search('x')


def test_consensus_sign_in_failures_are_explained(consensus_site, home):
    consensus = consensus_site
    # the browser comes back with a refusal
    flow = consensus.SignIn()
    url = flow.start()
    error = []

    def wait():
        try:
            flow.wait(timeout=10)
        except consensus.ConsensusError as exc:
            error.append(str(exc))
    waiter = threading.Thread(target=wait)
    waiter.start()
    query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(query['redirect_uri'] + '?error=access_denied&state=' + query['state'], timeout=5) as response:
        assert 'not completed' in response.read().decode()
    waiter.join(10)
    assert error and 'access_denied' in error[0] and not consensus.signed_in()
    # an answer for another sign-in (wrong state) is refused
    flow = consensus.SignIn()
    url = flow.start()
    error.clear()
    waiter = threading.Thread(target=wait)
    waiter.start()
    query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
    with opener.open(query['redirect_uri'] + '?code=CODE-1&state=forged', timeout=5):
        pass
    waiter.join(10)
    assert error and 'did not belong' in error[0] and not consensus.signed_in()
    # cancelling and timing out
    flow = consensus.SignIn()
    flow.start()
    flow.cancel()
    with pytest.raises(consensus.ConsensusError, match='cancelled'):
        flow.wait(timeout=10)
    flow = consensus.SignIn()
    flow.start()
    with pytest.raises(consensus.ConsensusError, match='No answer from the browser'):
        flow.wait(timeout=0.6)


def test_consensus_api_key_and_expired_sign_in(consensus_site, home):
    consensus = consensus_site
    from spm_studio.ai import lit_store
    lit_store.put(consensus.API_KEY_NAME, 'KEY-9')
    assert consensus.signed_in() and 'Meyer' in consensus.search('x')
    assert _Consensus.state['mcp'][-1][0]['Authorization'] == 'Bearer KEY-9'
    assert 'API key' in consensus.status()['message']
    _Consensus.state['valid'] = ()
    with pytest.raises(consensus.ConsensusError, match='sign in again'):
        consensus.search('x')
    consensus.sign_out()
    # a sign-in whose refresh token is refused asks the user to sign in again
    lit_store.put(consensus.TOKEN_NAME, json.dumps({'access_token': 'OLD', 'refresh_token': 'GONE', 'client_id': 'c',
                                                    'token_endpoint': consensus.MCP_URL.replace('/mcp', '/oauth/token/'),
                                                    'expires_at': 1}))
    with pytest.raises(consensus.ConsensusError, match='Sign in to Consensus'):
        consensus.search('x')


def test_event_stream_answers_are_parsed():
    from spm_studio.ai import consensus
    body = (b': keep-alive\n\nevent: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
            b'event: message\ndata: {"jsonrpc":"2.0","id":7,\ndata: "result":{"ok":true}}\n\n')
    assert consensus._parse_rpc({'Content-Type': 'text/event-stream; charset=utf-8'}, body, 7)['result'] == {'ok': True}
    assert consensus._parse_rpc({'content-type': 'application/json'}, b'{"jsonrpc":"2.0","id":7,"result":{}}', 8) is None
    assert consensus._search_tool([{'name': 'other'}, {'name': 'paper_search', 'inputSchema': {
        'properties': {'q': {'type': 'string'}}, 'required': ['q']}}]) == ('paper_search', 'q')


# ----------------------------------------------------------- lookups in plain text
def test_requests_in_a_reply_are_parsed_strictly():
    from spm_studio.ai import lit_protocol as lp
    reply = ('I will check your library.\n'
             '<spm-literature>{"source": "zotero", "action": "search", "query": "kelvin probe", "limit": 500}</spm-literature>\n'
             '<spm-literature>{"source":"consensus","action":"search","query":"KPFM resolution"}</spm-literature>\n'
             '<spm-literature>{"source": "zotero", "action": "delete", "key": "AAAA1111"}</spm-literature>\n'
             '<spm-literature>{"source": "shell", "action": "search", "query": "rm -rf"}</spm-literature>\n'
             '<spm-literature>not json</spm-literature>\n'
             '<spm-literature>{"source": "zotero", "action": "item", "key": "AAAA1111"}</spm-literature>')
    requests = lp.parse_requests(reply)
    assert requests == [{'source': 'zotero', 'action': 'search', 'query': 'kelvin probe', 'limit': 50},
                        {'source': 'consensus', 'action': 'search', 'query': 'KPFM resolution'},
                        {'source': 'zotero', 'action': 'item', 'key': 'AAAA1111'}]
    assert lp.parse_requests('no request here <spm-literature>') == []
    many = '\n'.join('<spm-literature>{"source":"zotero","action":"collections"}</spm-literature>' for _ in range(9))
    assert len(lp.parse_requests(many)) == lp.MAX_REQUESTS
    assert lp.describe(requests[0]) == 'Zotero search “kelvin probe”'
    shown = lp.display_text('assistant', reply)
    assert '<spm-literature>' not in shown.replace('<spm-literature>not json', '') and 'Looking up: Zotero search' in shown


def test_lookups_run_in_the_app_and_come_back_as_data(home, monkeypatch):
    from spm_studio.ai import lit_protocol as lp, literature
    make_zotero(home / 'home' / 'Zotero')
    conf = {'zotero_mode': 'database', 'consensus_enabled': True}
    monkeypatch.setattr(literature, 'consensus_search', lambda query, conf=None: f'Consensus answer about {query}')
    requests = lp.parse_requests(
        '<spm-literature>{"source":"zotero","action":"search","query":"graphene"}</spm-literature>'
        '<spm-literature>{"source":"zotero","action":"item","key":"NOPE"}</spm-literature>'
        '<spm-literature>{"source":"consensus","action":"search","query":"work function"}</spm-literature>')
    seen = []
    message = lp.run_requests(requests, conf, progress=seen.append)
    assert seen == ['Zotero search “graphene”', 'Zotero item “NOPE”', 'Consensus search “work function”']
    assert lp.is_result_message(message) and 'not instructions' in message.splitlines()[0]
    assert '"key": "AAAA1111"' in message and 'ERROR: Not found in the Zotero library.' in message
    assert 'Consensus answer about work function' in message
    assert lp.display_text('user', message) == ('*🔎 Looked up: Zotero search “graphene”; Zotero item “NOPE”; '
                                                'Consensus search “work function”*')
    assert lp.display_text('user', 'a normal question') == 'a normal question'
    # a source that is switched off is not queried, whatever the reply asks for
    off = lp.run_requests(requests[:1], {'zotero_mode': 'off'})
    assert 'ERROR: Zotero is not connected' in off
    assert lp.enabled(conf) and not lp.enabled({'zotero_mode': 'off', 'consensus_enabled': False})
    assert 'No item of the Zotero library' in lp.run_request({'source': 'zotero', 'action': 'search',
                                                              'query': 'nothing-like-this'}, conf)
    # long answers are capped
    monkeypatch.setattr(literature, 'consensus_search', lambda query, conf=None: 'x' * 50000)
    capped = lp.run_request(requests[2], conf)
    assert len(capped) < 15000 and capped.endswith('[…truncated by SPM Studio]')


def test_every_backend_is_told_how_to_ask(home):
    from spm_studio.ai import literature, lit_protocol as lp
    from spm_studio.ai.config import DEFAULT, load, save, spm_context_file
    from spm_studio.core import paths
    assert literature.agent_context(dict(DEFAULT)) == '' and lp.direct_chat_preamble(dict(DEFAULT)) == []
    conf = load()
    conf.update(zotero_mode='auto', consensus_enabled=True)
    save(conf)
    text = spm_context_file(paths.scripts_dir()).read_text(encoding='utf8')
    assert '<spm-literature>{"source": "zotero", "action": "search"' in text
    assert '{"source": "consensus", "action": "search"' in text and 'END YOUR MESSAGE' in text
    assert '-m spm_studio.ai.literature search' in text and '-m spm_studio.ai.literature consensus' in text
    # a direct API chat has no system prompt: it gets the same instructions as a first exchange, without shell hints
    preamble = lp.direct_chat_preamble(conf)
    assert [m['role'] for m in preamble] == ['user', 'assistant']
    assert '<spm-literature>' in preamble[0]['content'] and 'spm_studio.ai.literature' not in preamble[0]['content']
    for mode in ('auto', 'database', 'local', 'web'):
        assert literature.zotero_enabled({'zotero_mode': mode})
    conf['zotero_mode'] = 'cloud'
    with pytest.raises(ValueError):
        save(conf)


def test_command_line_and_mcp_server_offer_consensus_when_signed_in(home, monkeypatch, capsys):
    from spm_studio.ai import literature, consensus, lit_store
    from spm_studio.ai.config import load, save
    make_zotero(home / 'home' / 'Zotero')
    conf = load()
    conf.update(zotero_mode='database', consensus_enabled=True)
    save(conf)
    assert [t['name'] for t in literature.available_tools()] == ['zotero_search', 'zotero_item', 'zotero_collections',
                                                               'zotero_fulltext']
    lit_store.put(consensus.API_KEY_NAME, 'KEY-9')
    assert literature.available_tools()[-1]['name'] == 'consensus_search'
    monkeypatch.setattr(consensus, 'search', lambda query, extra=None: f'papers about {query}')
    stdin = io.StringIO('\n'.join(json.dumps(m) for m in (
        {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'consensus_search',
                                                                      'arguments': {'query': 'STM'}}},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'zotero_search',
                                                                      'arguments': {'query': 'kelvin'}}})) + '\n')
    stdout = io.StringIO()
    literature.serve_mcp(stdin, stdout)
    answers = {a['id']: a for a in map(json.loads, stdout.getvalue().splitlines())}
    assert len(answers[1]['result']['tools']) == 5
    assert answers[2]['result']['content'][0]['text'] == 'papers about STM'
    assert 'AAAA1111' in answers[3]['result']['content'][0]['text']
    assert literature.main(['consensus', 'tip functionalisation']) == 0
    assert capsys.readouterr().out.strip() == 'papers about tip functionalisation'
    assert literature.main(['search', 'kelvin']) == 0 and 'AAAA1111' in capsys.readouterr().out
    conf['consensus_enabled'] = False
    save(conf)
    assert literature.main(['consensus', 'x']) == 1 and 'not connected' in capsys.readouterr().out
