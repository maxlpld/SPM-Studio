"""Literature sources for the Assistant: Zotero and Consensus (Qt-free).

**Zotero** — read-only access to the user's own library. ``zotero_mode``:

* ``auto`` (what *Connect Zotero* sets): ask the Zotero app when it answers,
  otherwise read the database file. Nothing has to be configured.
* ``database``: read ``zotero.sqlite`` in the Zotero data folder (read-only and
  immutable, see ``zotero_db``). Any Zotero version, running or not.
* ``local``: the Zotero desktop app (7 or later) through its local API
  ``http://127.0.0.1:23119/api`` (Zotero › Settings › Advanced › *Allow other
  applications on this computer to communicate with Zotero*).
* ``web``: ``https://api.zotero.org`` with a library ID and a read-only API key.

**Consensus** (consensus.app) — search over peer-reviewed papers through
Consensus' MCP server, with the user's own sign-in done from Settings ›
Literature (``consensus`` module). A Zotero library linked inside the Consensus
account is used by Consensus itself.

How the assistant reaches them — all three are served by this package:

* **request lines** in its reply, run by SPM Studio and answered in the next
  message (``lit_protocol``). Works with every backend, with or without tools;
* a **command line** for agents that have a shell::

      python -m spm_studio.ai.literature search "kelvin probe graphene" --limit 10
      python -m spm_studio.ai.literature item ABCD2345
      python -m spm_studio.ai.literature collections
      python -m spm_studio.ai.literature fulltext ABCD2345
      python -m spm_studio.ai.literature consensus "does KPFM resolve single dopants?"
      python -m spm_studio.ai.literature status

* a small **MCP server** over stdio (``python -m spm_studio.ai.literature
  --mcp``) with the same read-only tools.

Secrets (zotero.org key, Consensus sign-in) are kept by ``lit_store``: the
system keyring, else a private file of the user's account. Nothing in this
package writes to Zotero, and nothing is contacted unless the user enabled the
source in the AI assistant settings › Literature.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

CONSENSUS_MCP_URL = 'https://mcp.consensus.app/mcp'
CONSENSUS_SERVER = 'consensus'
ZOTERO_SERVER = 'spm-zotero'
ZOTERO_LOCAL = 'http://127.0.0.1:23119/api'
ZOTERO_WEB = 'https://api.zotero.org'
# off · auto (app if it answers, else the database file) · local (app) · database (file) · web (zotero.org)
ZOTERO_MODES = ('off', 'auto', 'local', 'database', 'web')
ZOTERO_ON = ('auto', 'local', 'database', 'web')
ZOTERO_CONNECTOR = 'http://127.0.0.1:23119/connector/ping'
ZOTERO_KEY_NAME = 'zotero'            # CredentialStore entry
USER_AGENT = 'SPM-Studio (literature helper)'
MAX_RESULTS = 50


class LiteratureError(RuntimeError):
    """A message meant to be read by the user (or by the agent)."""


# ------------------------------------------------------------------------ settings
def settings() -> dict:
    from .config import load
    return load()


def zotero_enabled(conf: dict) -> bool:
    return conf.get('zotero_mode', 'off') in ZOTERO_ON


def consensus_enabled(conf: dict) -> bool:
    return bool(conf.get('consensus_enabled'))


def zotero_api_key() -> str:
    """zotero.org key: keyring or SPM Studio's private file (``lit_store``), else ``ZOTERO_API_KEY``."""
    try:
        from . import lit_store
        value = lit_store.get(ZOTERO_KEY_NAME)
        if value:
            return value
    except Exception:
        pass
    try:
        from .security import CredentialStore
        value = CredentialStore().get(ZOTERO_KEY_NAME)
        if value:
            return value
    except Exception:
        pass
    return os.environ.get('ZOTERO_API_KEY', '')


def _library_prefix(conf: dict) -> tuple[str, dict]:
    mode = conf.get('zotero_mode', 'off')
    if mode in ('local', 'auto'):
        return ZOTERO_LOCAL + '/users/0', {}
    if mode == 'web':
        library = str(conf.get('zotero_library_id', '')).strip()
        if not library.isdigit():
            raise LiteratureError('Zotero web access needs your numeric library ID '
                                  '(the AI assistant settings › Literature (Consensus & Zotero)).')
        key = zotero_api_key()
        if not key:
            raise LiteratureError('No Zotero API key stored (the AI assistant settings › Literature (Consensus & Zotero)).')
        kind = 'groups' if conf.get('zotero_library_type') == 'group' else 'users'
        return f'{ZOTERO_WEB}/{kind}/{library}', {'Zotero-API-Key': key}
    raise LiteratureError('Zotero is not connected. The user can connect it in '
                          'the AI assistant settings › Literature (Consensus & Zotero).')


def _get(url: str, headers: dict, timeout: float = 20, raw: bool = False):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Zotero-API-Version': '3',
                                                   'Accept': 'application/json', **headers})
    try:
        if url.startswith('https://'):
            try:
                from .pi_setup import _ssl_context
                context = _ssl_context()
            except Exception:
                context = None
            response = urllib.request.urlopen(request, timeout=timeout, context=context)
        else:
            # Local API: never through a proxy.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            response = opener.open(request, timeout=timeout)
        with response:
            body = response.read(8_000_000)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            if url.startswith(ZOTERO_LOCAL):
                raise LiteratureError('Zotero refused the request. In Zotero: Settings › Advanced › tick '
                                      '“Allow other applications on this computer to communicate with Zotero”.') from exc
            raise LiteratureError('Zotero refused the API key (check it and its library access).') from exc
        if exc.code == 404:
            raise LiteratureError('Not found in the Zotero library.') from exc
        raise LiteratureError(f'Zotero answered HTTP {exc.code}.') from exc
    except (urllib.error.URLError, OSError) as exc:
        if url.startswith(ZOTERO_LOCAL):
            raise LiteratureError('Zotero is not reachable on this computer. Start the Zotero app (version 7 or '
                                  'later) and enable Settings › Advanced › “Allow other applications on this '
                                  'computer to communicate with Zotero”.') from exc
        raise LiteratureError(f'Could not reach zotero.org: {getattr(exc, "reason", exc)}') from exc
    if raw:
        return body
    try:
        return json.loads(body.decode('utf-8'))
    except ValueError as exc:
        raise LiteratureError('Unexpected answer from Zotero.') from exc


def _url(prefix: str, path: str, **params) -> str:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, '')})
    return prefix + path + ('?' + query if query else '')


# --------------------------------------------------------------------------- zotero
def _creators(data: dict) -> str:
    names = []
    for c in data.get('creators', []) or []:
        name = c.get('lastName') or c.get('name') or ''
        if name:
            names.append(name)
    if len(names) > 3:
        return ', '.join(names[:3]) + ' et al.'
    return ', '.join(names)


def _year(date) -> str:
    import re
    found = re.search(r'(1[5-9]|20)\d\d', str(date or ''))
    return found.group(0) if found else str(date or '')


def summarize(item: dict, *, abstract: bool = False) -> dict:
    """Compact, model-friendly view of one Zotero item."""
    data = item.get('data', item)
    out = {'key': data.get('key') or item.get('key', ''),
           'type': data.get('itemType', ''),
           'title': data.get('title', ''),
           'creators': _creators(data),
           'year': _year(data.get('date', '')),
           'publication': data.get('publicationTitle') or data.get('bookTitle') or data.get('publisher') or '',
           'doi': data.get('DOI', ''),
           'url': data.get('url', ''),
           'tags': [t.get('tag', '') for t in data.get('tags', []) or [] if t.get('tag')][:12]}
    if abstract:
        out['abstract'] = data.get('abstractNote', '')
        for key in ('volume', 'issue', 'pages', 'journalAbbreviation', 'extra'):
            if data.get(key):
                out[key] = data[key]
    return {k: v for k, v in out.items() if v not in ('', [], None)}


# ---- which way into the library
def _local_api_answers(timeout: float = 1.5) -> bool:
    try:
        _get(_url(ZOTERO_LOCAL + '/users/0', '/items/top', limit=1, format='json'), {}, timeout=timeout)
        return True
    except LiteratureError:
        return False


def zotero_data_dir(conf: dict):
    """Folder of ``zotero.sqlite`` (the configured one, else the usual places), or ``None``."""
    from . import zotero_db
    return zotero_db.find_data_dir(str(conf.get('zotero_data_dir', '') or ''))


def _backend(conf: dict):
    """('api', prefix, headers) or ('db', data_dir) for the configured way of reading Zotero."""
    mode = conf.get('zotero_mode', 'off')
    if mode == 'database' or (mode == 'auto' and not _local_api_answers()):
        folder = zotero_data_dir(conf)
        if folder is not None:
            return ('db', folder)
        if mode == 'database':
            raise LiteratureError('No Zotero database (zotero.sqlite) was found. Choose your Zotero data folder in '
                                  'the AI assistant settings › Literature (Consensus & Zotero) (Zotero shows it in Settings › Advanced › '
                                  'Files and Folders).')
        raise LiteratureError('No Zotero library was found on this computer: the Zotero app does not answer and '
                              'there is no Zotero data folder in the usual places. Install or start Zotero, or '
                              'choose the data folder in the AI assistant settings › Literature (Consensus & Zotero).')
    prefix, headers = _library_prefix(conf)
    return ('api', prefix, headers)


def _db(folder):
    from . import zotero_db
    try:
        return zotero_db.Library(folder)
    except zotero_db.ZoteroDbError as exc:
        raise LiteratureError(str(exc)) from exc


def zotero_search(query: str, limit: int = 10, collection: str = '', conf: dict | None = None) -> list[dict]:
    """Items whose title, creators, year, tags or notes (and, through the app, full text) match ``query``."""
    conf = conf or settings()
    backend = _backend(conf)
    limit = max(1, min(int(limit or 10), MAX_RESULTS))
    if backend[0] == 'db':
        with _db(backend[1]) as library:
            return [summarize({'data': d}) for d in library.search(query, limit, collection)]
    _kind, prefix, headers = backend
    path = f'/collections/{urllib.parse.quote(collection)}/items/top' if collection else '/items/top'
    items = _get(_url(prefix, path, q=query, qmode='everything', limit=limit, sort='date', direction='desc',
                      format='json'), headers)
    if not isinstance(items, list):
        raise LiteratureError('Unexpected answer from Zotero.')
    return [summarize(i) for i in items]


def _with_children(out: dict, children) -> dict:
    notes, attachments = [], []
    for child in children if isinstance(children, list) else []:
        data = child.get('data', {})
        if data.get('itemType') == 'note':
            notes.append(_strip_html(data.get('note', ''))[:4000])
        elif data.get('itemType') == 'attachment':
            attachments.append({'key': data.get('key', ''), 'title': data.get('title', ''),
                                'type': data.get('contentType', '')})
    if notes:
        out['notes'] = notes
    if attachments:
        out['attachments'] = attachments
    return out


def zotero_item(key: str, conf: dict | None = None) -> dict:
    """One item with abstract, notes and attachment names."""
    conf = conf or settings()
    backend = _backend(conf)
    if backend[0] == 'db':
        from . import zotero_db
        with _db(backend[1]) as library:
            try:
                data, children = library.item(key)
            except zotero_db.ZoteroDbError as exc:
                raise LiteratureError(str(exc)) from exc
        return _with_children(summarize({'data': data}, abstract=True), children)
    _kind, prefix, headers = backend
    key = urllib.parse.quote(str(key).strip())
    item = _get(_url(prefix, f'/items/{key}', format='json'), headers)
    try:
        children = _get(_url(prefix, f'/items/{key}/children', format='json'), headers)
    except LiteratureError:
        children = []
    return _with_children(summarize(item, abstract=True), children)


def zotero_collections(conf: dict | None = None) -> list[dict]:
    conf = conf or settings()
    backend = _backend(conf)
    if backend[0] == 'db':
        with _db(backend[1]) as library:
            return library.collections()
    _kind, prefix, headers = backend
    found = _get(_url(prefix, '/collections', limit=100, format='json'), headers)
    return [{'key': c.get('key', ''), 'name': c.get('data', {}).get('name', ''),
             'parent': c.get('data', {}).get('parentCollection') or ''} for c in found if isinstance(c, dict)]


NO_FULLTEXT = ('Zotero has no indexed full text for this item (open the PDF in Zotero once, or check '
               'Zotero › Settings › General › File Handling / Search › PDF indexing).')


def zotero_fulltext(key: str, max_chars: int = 40000, conf: dict | None = None) -> dict:
    """Indexed text of an attachment (a PDF Zotero has indexed), or of an item's first indexed PDF."""
    conf = conf or settings()
    backend = _backend(conf)
    max_chars = max(1000, min(int(max_chars or 40000), 200000))
    key = str(key).strip()
    if backend[0] == 'db':
        from . import zotero_db
        with _db(backend[1]) as library:
            try:
                found = library.fulltext(key)
            except zotero_db.ZoteroDbError as exc:
                raise LiteratureError(str(exc)) from exc
        if found is None:
            raise LiteratureError(NO_FULLTEXT)
        candidate, text = found
        return {'key': candidate, 'characters': len(text), 'truncated': len(text) > max_chars,
                'text': text[:max_chars]}
    _kind, prefix, headers = backend
    candidates = [key]
    try:
        children = _get(_url(prefix, f'/items/{urllib.parse.quote(key)}/children', format='json'), headers)
        candidates += [c.get('data', {}).get('key', '') for c in children if isinstance(c, dict)
                       and c.get('data', {}).get('itemType') == 'attachment']
    except LiteratureError:
        pass
    for candidate in filter(None, candidates):
        try:
            data = _get(_url(prefix, f'/items/{urllib.parse.quote(candidate)}/fulltext'), headers)
        except LiteratureError:
            continue
        text = data.get('content', '') if isinstance(data, dict) else ''
        if text:
            return {'key': candidate, 'characters': len(text), 'truncated': len(text) > max_chars,
                    'text': text[:max_chars]}
    raise LiteratureError(NO_FULLTEXT)


def diagnose_local_app() -> str:
    """Why the Zotero app does not answer, in words (used when the local API fails)."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(ZOTERO_CONNECTOR, headers={'User-Agent': USER_AGENT})
        with opener.open(request, timeout=2) as response:
            version = response.headers.get('X-Zotero-Version', '')
    except urllib.error.HTTPError as exc:
        version = exc.headers.get('X-Zotero-Version', '') if exc.headers else ''
    except (urllib.error.URLError, OSError):
        return 'The Zotero app is not running.'
    try:
        major = int(str(version).split('.')[0])
    except ValueError:
        major = 0
    if major and major < 7:
        return (f'Zotero {version} is running, but only Zotero 7 or later can be asked directly. '
                'Use “Zotero database file” instead (works with every version).')
    return ('Zotero' + (f' {version}' if version else '') + ' is running, but it does not accept requests from other '
            'applications. In Zotero: Settings › Advanced › tick “Allow other applications on this computer to '
            'communicate with Zotero” — or use “Zotero database file”, which needs no setting.')


def zotero_status(conf: dict | None = None) -> dict:
    """Connection test used by the settings page and by ``status``."""
    conf = conf or settings()
    mode = conf.get('zotero_mode', 'off')
    if mode not in ZOTERO_ON:
        return {'connected': False, 'mode': 'off', 'message': 'Zotero is not connected.'}
    try:
        backend = _backend(conf)
        if backend[0] == 'db':
            with _db(backend[1]) as library:
                count = library.count()
            return {'connected': True, 'mode': mode, 'via': 'database', 'items': count,
                    'message': f'Connected — {count} items read from the Zotero database in {backend[1]}'}
        _kind, prefix, headers = backend
        items = _get(_url(prefix, '/items/top', limit=1, format='json'), headers, timeout=8)
        where = 'zotero.org library' if mode == 'web' else 'Zotero desktop app on this computer'
        return {'connected': True, 'mode': mode, 'via': 'web' if mode == 'web' else 'app',
                'message': where + (' — connected' if isinstance(items, list) else '')}
    except LiteratureError as exc:
        message = str(exc)
        if mode == 'local':
            hint = diagnose_local_app()
            if hint not in message and 'not running' not in hint:
                message = hint
        return {'connected': False, 'mode': mode, 'message': message}


def detect_zotero(conf: dict | None = None) -> dict:
    """What is on this computer, for the one-click “Connect Zotero” of the settings page."""
    conf = dict(conf or settings())
    app = _local_api_answers()
    folder = zotero_data_dir(conf)
    count = None
    if folder is not None:
        try:
            with _db(folder) as library:
                count = library.count()
        except LiteratureError:
            folder = None
    return {'app': app, 'data_dir': str(folder) if folder else '', 'items': count,
            'found': bool(app or folder), 'app_hint': '' if app else diagnose_local_app()}


def _strip_html(text: str) -> str:
    import html
    import re
    return html.unescape(re.sub(r'<[^>]+>', ' ', text or '')).strip()


# ------------------------------------------------------------- agent registrations
def helper_command(python: str | None = None) -> list[str]:
    return [python or sys.executable, '-m', 'spm_studio.ai.literature']


def mcp_registration(agent: str, executable: str, server: str, *, remove: bool = False) -> list[str]:
    """Command line that (un)registers one of the two servers with Claude Code or Codex."""
    if server not in (CONSENSUS_SERVER, ZOTERO_SERVER):
        raise ValueError('Unknown server ' + server)
    if agent == 'claude-code':
        if remove:
            return [executable, 'mcp', 'remove', '--scope', 'user', server]
        if server == CONSENSUS_SERVER:
            return [executable, 'mcp', 'add', '--scope', 'user', '--transport', 'http', server, CONSENSUS_MCP_URL]
        return [executable, 'mcp', 'add', '--scope', 'user', server, '--', *helper_command(), '--mcp']
    if agent == 'codex':
        if remove:
            return [executable, 'mcp', 'remove', server]
        if server == CONSENSUS_SERVER:
            return [executable, 'mcp', 'add', server, '--url', CONSENSUS_MCP_URL]
        return [executable, 'mcp', 'add', server, '--', *helper_command(), '--mcp']
    raise ValueError('MCP registration is done through a config file for ' + agent)


def pi_mcp_entries(conf: dict) -> dict:
    """``mcpServers`` entries for Pi's ``mcp.json`` (Pi 0.99 or later, or the pi-mcp-adapter package)."""
    servers = {}
    if conf.get('consensus_enabled'):
        servers[CONSENSUS_SERVER] = {'url': CONSENSUS_MCP_URL}
    if zotero_enabled(conf):
        command = helper_command()
        servers[ZOTERO_SERVER] = {'command': command[0], 'args': command[1:] + ['--mcp']}
    return servers


def write_pi_mcp(agent_dir, conf: dict):
    """Merge SPM Studio's two servers into ``<agent_dir>/mcp.json``; other servers are kept."""
    from pathlib import Path
    path = Path(agent_dir) / 'mcp.json'
    try:
        data = json.loads(path.read_text(encoding='utf8'))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    servers = data.get('mcpServers')
    if not isinstance(servers, dict):
        servers = {}
    wanted = pi_mcp_entries(conf)
    for name in (CONSENSUS_SERVER, ZOTERO_SERVER):
        if name in wanted:
            servers[name] = wanted[name]
        else:
            servers.pop(name, None)
    data['mcpServers'] = servers
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf8')
    temp.replace(path)
    return path


def allowed_tools(conf: dict) -> list[str]:
    """Claude Code ``--allowedTools`` entries so the literature tools need no prompt per call."""
    tools = []
    if conf.get('consensus_enabled'):
        tools.append('mcp__' + CONSENSUS_SERVER)
    if zotero_enabled(conf):
        tools.append('mcp__' + ZOTERO_SERVER)
    return tools


REQUEST_TAG = 'spm-literature'


def agent_context(conf: dict, python: str | None = None, shell: bool = True) -> str:
    """Paragraphs added to the Assistant's instructions (empty when no source is connected).

    The assistant asks for a lookup by writing a request line; SPM Studio runs it and sends the
    result back (``lit_protocol``). That works with every backend, with or without agent tools.
    ``shell=True`` also documents the equivalent command line for agents that have a shell.
    """
    consensus = consensus_enabled(conf)
    zotero = zotero_enabled(conf)
    if not consensus and not zotero:
        return ''
    command = ' '.join(f'"{part}"' if ' ' in part else part for part in helper_command(python))
    lines = ['', '## Literature sources the user connected',
             'Use them whenever the user asks for literature, references, prior work, a value from a paper, '
             'or what is in their library. Cite what you use (authors, year, title, DOI or link) and never '
             'invent a reference: if a search finds nothing, say so.',
             '',
             '### How to look something up (works in every mode, also without tools)',
             f'Write a request on its own line, exactly in this form, then END YOUR MESSAGE (write nothing after it):',
             f'`<{REQUEST_TAG}>{{"source": "zotero", "action": "search", "query": "kelvin probe graphene"}}</{REQUEST_TAG}>`',
             'SPM Studio runs it and immediately sends you the result as the next message; then answer the user. '
             'You may put up to 4 requests in one message and ask again after seeing results. Do not show the '
             'request syntax to the user and do not ask them to run anything.']
    if zotero:
        where = {'web': 'their zotero.org library', 'database': 'the Zotero database on this computer',
                 'local': 'the Zotero desktop app on this computer'}.get(
                     conf.get('zotero_mode'), 'Zotero on this computer')
        lines += ['',
                  f'### Zotero — the user\'s own reference library ({where}), read-only',
                  'Look here first for anything the user may already have collected. Requests:',
                  '- `{"source": "zotero", "action": "search", "query": "<words>", "limit": 10}` '
                  '(optional `"collection": "<KEY>"`) → records with their item `key`',
                  '- `{"source": "zotero", "action": "item", "key": "<KEY>"}` → abstract, notes, attachments',
                  '- `{"source": "zotero", "action": "collections"}`',
                  '- `{"source": "zotero", "action": "fulltext", "key": "<KEY>"}` → indexed PDF text, when Zotero has it',
                  '- You cannot add, change or delete anything in Zotero.']
        if shell:
            lines += [f'- If you have a shell, the same is available as JSON on stdout: '
                      f'`{command} search "<words>" --limit 10`, `{command} item <KEY>`, '
                      f'`{command} collections`, `{command} fulltext <KEY>`. '
                      f'MCP clients may also list the `{ZOTERO_SERVER}` server with the same tools.']
    if consensus:
        lines += ['',
                  '### Consensus (consensus.app) — search engine over peer-reviewed papers',
                  f'Signed in with the user\'s own Consensus account (their institution\'s licence applies; '
                  f'server {CONSENSUS_MCP_URL}). Request:',
                  '- `{"source": "consensus", "action": "search", "query": "<a question or topic in plain words>"}` '
                  '→ papers with takeaways and links',
                  '- Use it for questions about the published literature: findings, agreement on a question, '
                  'papers on a topic. If the user linked Zotero inside Consensus, Consensus uses that library itself.',
                  '- If the result says the sign-in is missing or expired, tell the user to open '
                  'the AI assistant settings › Literature (Consensus & Zotero) and click “Sign in to Consensus”. Never ask for a password.']
        if shell:
            lines += [f'- With a shell: `{command} consensus "<question>"`.']
    return '\n'.join(lines) + '\n'


# ------------------------------------------------------------------------ MCP stdio
TOOLS = [
    {'name': 'zotero_search',
     'description': 'Search the user\'s Zotero library (title, authors, year, tags, indexed full text). '
                    'Returns compact records with their item key.',
     'inputSchema': {'type': 'object', 'required': ['query'], 'properties': {
         'query': {'type': 'string', 'description': 'Words to look for'},
         'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_RESULTS, 'default': 10},
         'collection': {'type': 'string', 'description': 'Optional collection key to search in'}}}},
    {'name': 'zotero_item',
     'description': 'One Zotero item by key: abstract, DOI, notes and attachment names.',
     'inputSchema': {'type': 'object', 'required': ['key'], 'properties': {'key': {'type': 'string'}}}},
    {'name': 'zotero_collections',
     'description': 'List the collections (folders) of the Zotero library.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'zotero_fulltext',
     'description': 'Indexed full text of a Zotero item or PDF attachment, when Zotero has indexed it.',
     'inputSchema': {'type': 'object', 'required': ['key'], 'properties': {
         'key': {'type': 'string'}, 'max_chars': {'type': 'integer', 'default': 40000}}}},
]


CONSENSUS_TOOL = {
    'name': 'consensus_search',
    'description': 'Search peer-reviewed papers with Consensus (consensus.app), using the user\'s own account. '
                   'Returns papers with takeaways and links.',
    'inputSchema': {'type': 'object', 'required': ['query'], 'properties': {
        'query': {'type': 'string', 'description': 'A question or topic in plain words'}}}}


def available_tools(conf: dict | None = None) -> list[dict]:
    """Zotero tools, plus Consensus when the user enabled it and is signed in."""
    try:
        conf = conf or settings()
        from . import consensus
        if consensus_enabled(conf) and consensus.signed_in():
            return TOOLS + [CONSENSUS_TOOL]
    except Exception:
        pass
    return TOOLS


def consensus_search(query: str, conf: dict | None = None) -> str:
    conf = conf or settings()
    if not consensus_enabled(conf):
        raise LiteratureError('Consensus is not connected. The user can connect it in '
                              'the AI assistant settings › Literature (Consensus & Zotero).')
    from . import consensus
    try:
        return consensus.search(query)
    except consensus.ConsensusError as exc:
        raise LiteratureError(str(exc)) from exc


def call_tool(name: str, arguments: dict):
    arguments = arguments or {}
    if name == 'consensus_search':
        return consensus_search(str(arguments.get('query', '')))
    if name == 'zotero_search':
        return zotero_search(str(arguments.get('query', '')), arguments.get('limit', 10),
                             str(arguments.get('collection', '') or ''))
    if name == 'zotero_item':
        return zotero_item(str(arguments.get('key', '')))
    if name == 'zotero_collections':
        return zotero_collections()
    if name == 'zotero_fulltext':
        return zotero_fulltext(str(arguments.get('key', '')), arguments.get('max_chars', 40000))
    raise LiteratureError('Unknown tool ' + str(name))


def handle_mcp(message: dict):
    """Answer one JSON-RPC message; ``None`` for notifications."""
    method = message.get('method')
    msg_id = message.get('id')
    if msg_id is None:
        return None
    def reply(result):
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}
    if method == 'initialize':
        requested = (message.get('params') or {}).get('protocolVersion') or '2024-11-05'
        return reply({'protocolVersion': requested, 'capabilities': {'tools': {}},
                      'serverInfo': {'name': ZOTERO_SERVER, 'version': '1.0'},
                      'instructions': 'Read-only access to the user\'s Zotero library.'})
    if method == 'ping':
        return reply({})
    if method == 'tools/list':
        return reply({'tools': available_tools()})
    if method == 'tools/call':
        params = message.get('params') or {}
        try:
            result = call_tool(params.get('name'), params.get('arguments') or {})
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1)
            return reply({'content': [{'type': 'text', 'text': text}], 'isError': False})
        except LiteratureError as exc:
            return reply({'content': [{'type': 'text', 'text': str(exc)}], 'isError': True})
        except Exception as exc:                     # never crash the server on one bad call
            return reply({'content': [{'type': 'text', 'text': f'Internal error: {exc}'}], 'isError': True})
    if method in ('resources/list', 'prompts/list'):
        return reply({method.split('/')[0]: []})
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': -32601, 'message': 'Method not found: ' + str(method)}}


def serve_mcp(stdin=None, stdout=None) -> int:
    """Newline-delimited JSON-RPC over stdio (the MCP stdio transport)."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            answer = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        else:
            answer = handle_mcp(message) if isinstance(message, dict) else None
        if answer is not None:
            stdout.write(json.dumps(answer, ensure_ascii=False) + '\n')
            stdout.flush()
    return 0


# ------------------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    import argparse
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--mcp' in argv:
        return serve_mcp()
    parser = argparse.ArgumentParser(prog='python -m spm_studio.ai.literature',
                                     description='Read-only access to the literature sources connected in '
                                                 'SPM Studio (Zotero library, Consensus search).')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('search', help='search the library')
    s.add_argument('query')
    s.add_argument('--limit', type=int, default=10)
    s.add_argument('--collection', default='')
    i = sub.add_parser('item', help='one item with abstract and notes')
    i.add_argument('key')
    sub.add_parser('collections', help='list collections')
    f = sub.add_parser('fulltext', help='indexed text of an item or attachment')
    f.add_argument('key')
    f.add_argument('--max-chars', type=int, default=40000)
    c = sub.add_parser('consensus', help='search peer-reviewed papers with Consensus')
    c.add_argument('query')
    sub.add_parser('status', help='check the connections')
    args = parser.parse_args(argv)
    try:
        if args.command == 'search':
            result = zotero_search(args.query, args.limit, args.collection)
        elif args.command == 'item':
            result = zotero_item(args.key)
        elif args.command == 'collections':
            result = zotero_collections()
        elif args.command == 'fulltext':
            result = zotero_fulltext(args.key, args.max_chars)
        elif args.command == 'consensus':
            result = consensus_search(args.query)
        else:
            result = zotero_status()
    except LiteratureError as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stdout)
        return 1
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
