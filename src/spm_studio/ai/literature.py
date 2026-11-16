"""Literature sources for the Assistant: Zotero and Consensus (Qt-free).

**Zotero** — read-only access to the user's own library, two ways:

* ``local``: the Zotero desktop app (7 or later) on this computer, through its
  local API ``http://127.0.0.1:23119/api`` (Zotero › Settings › Advanced ›
  *Allow other applications on this computer to communicate with Zotero*).
  No account, no key, nothing leaves the computer.
* ``web``: ``https://api.zotero.org`` with the user's library ID and a
  read-only API key (zotero.org › Settings › Security › *Create new private
  key*). The key is kept in the OS keyring, never in a settings file.

The Assistant reaches it in two equivalent ways, both served by this module:

* a command line every agent can run from its shell::

      python -m spm_studio.ai.literature search "kelvin probe graphene" --limit 10
      python -m spm_studio.ai.literature item ABCD2345
      python -m spm_studio.ai.literature collections
      python -m spm_studio.ai.literature fulltext ABCD2345
      python -m spm_studio.ai.literature status

* a small MCP server over stdio (``python -m spm_studio.ai.literature --mcp``)
  for agents with MCP support (Claude Code, Codex, Pi ≥ 0.99), exposing the
  same four read-only tools.

**Consensus** (consensus.app) — its hosted MCP server
``https://mcp.consensus.app/mcp`` with the user's own Consensus sign-in (a
university account works: the sign-in happens in the browser, on Consensus'
site). SPM Studio only registers that address with the agent; it never sees the
password or the token. A Zotero library linked inside the Consensus account is
used by Consensus itself.

Nothing in this module writes to Zotero, and nothing is contacted unless the
user enabled the source in Settings › Literature.
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
ZOTERO_MODES = ('off', 'local', 'web')
ZOTERO_KEY_NAME = 'zotero'            # CredentialStore entry
USER_AGENT = 'SPM-Studio (literature helper)'
MAX_RESULTS = 50


class LiteratureError(RuntimeError):
    """A message meant to be read by the user (or by the agent)."""


# ------------------------------------------------------------------------ settings
def settings() -> dict:
    from .config import load
    return load()


def zotero_api_key() -> str:
    """Key from the OS keyring; ``ZOTERO_API_KEY`` is the fallback for systems without one."""
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
    if mode == 'local':
        return ZOTERO_LOCAL + '/users/0', {}
    if mode == 'web':
        library = str(conf.get('zotero_library_id', '')).strip()
        if not library.isdigit():
            raise LiteratureError('Zotero web access needs your numeric library ID '
                                  '(SPM Studio › Settings › Literature).')
        key = zotero_api_key()
        if not key:
            raise LiteratureError('No Zotero API key stored (SPM Studio › Settings › Literature).')
        kind = 'groups' if conf.get('zotero_library_type') == 'group' else 'users'
        return f'{ZOTERO_WEB}/{kind}/{library}', {'Zotero-API-Key': key}
    raise LiteratureError('Zotero is not connected. The user can connect it in '
                          'SPM Studio › Settings › Literature.')


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


def zotero_search(query: str, limit: int = 10, collection: str = '', conf: dict | None = None) -> list[dict]:
    """Items whose title, creators, year, tags or full text match ``query``."""
    conf = conf or settings()
    prefix, headers = _library_prefix(conf)
    limit = max(1, min(int(limit or 10), MAX_RESULTS))
    path = f'/collections/{urllib.parse.quote(collection)}/items/top' if collection else '/items/top'
    items = _get(_url(prefix, path, q=query, qmode='everything', limit=limit, sort='date', direction='desc',
                      format='json'), headers)
    if not isinstance(items, list):
        raise LiteratureError('Unexpected answer from Zotero.')
    return [summarize(i) for i in items]


def zotero_item(key: str, conf: dict | None = None) -> dict:
    """One item with abstract, notes and attachment names."""
    conf = conf or settings()
    prefix, headers = _library_prefix(conf)
    key = urllib.parse.quote(str(key).strip())
    item = _get(_url(prefix, f'/items/{key}', format='json'), headers)
    out = summarize(item, abstract=True)
    try:
        children = _get(_url(prefix, f'/items/{key}/children', format='json'), headers)
    except LiteratureError:
        children = []
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


def zotero_collections(conf: dict | None = None) -> list[dict]:
    conf = conf or settings()
    prefix, headers = _library_prefix(conf)
    found = _get(_url(prefix, '/collections', limit=100, format='json'), headers)
    return [{'key': c.get('key', ''), 'name': c.get('data', {}).get('name', ''),
             'parent': c.get('data', {}).get('parentCollection') or ''} for c in found if isinstance(c, dict)]


def zotero_fulltext(key: str, max_chars: int = 40000, conf: dict | None = None) -> dict:
    """Indexed text of an attachment (a PDF Zotero has indexed), or of an item's first indexed PDF."""
    conf = conf or settings()
    prefix, headers = _library_prefix(conf)
    key = str(key).strip()
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
            max_chars = max(1000, min(int(max_chars or 40000), 200000))
            return {'key': candidate, 'characters': len(text), 'truncated': len(text) > max_chars,
                    'text': text[:max_chars]}
    raise LiteratureError('Zotero has no indexed full text for this item (open the PDF in Zotero once, or check '
                          'Zotero › Settings › General › File Handling / Search › PDF indexing).')


def zotero_status(conf: dict | None = None) -> dict:
    """Connection test used by the settings page and by ``status``."""
    conf = conf or settings()
    mode = conf.get('zotero_mode', 'off')
    if mode not in ('local', 'web'):
        return {'connected': False, 'mode': 'off', 'message': 'Zotero is not connected.'}
    try:
        prefix, headers = _library_prefix(conf)
        items = _get(_url(prefix, '/items/top', limit=1, format='json'), headers, timeout=8)
        return {'connected': True, 'mode': mode,
                'message': ('Zotero desktop app on this computer' if mode == 'local' else 'zotero.org library')
                + (' — connected' if isinstance(items, list) else '')}
    except LiteratureError as exc:
        return {'connected': False, 'mode': mode, 'message': str(exc)}


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
    if conf.get('zotero_mode') in ('local', 'web'):
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
    if conf.get('zotero_mode') in ('local', 'web'):
        tools.append('mcp__' + ZOTERO_SERVER)
    return tools


def agent_context(conf: dict, python: str | None = None) -> str:
    """Paragraphs added to the Assistant's system prompt (empty when no source is connected)."""
    consensus = bool(conf.get('consensus_enabled'))
    zotero = conf.get('zotero_mode') in ('local', 'web')
    if not consensus and not zotero:
        return ''
    command = ' '.join(f'"{part}"' if ' ' in part else part for part in helper_command(python))
    lines = ['', '## Literature sources the user connected',
             'Use them whenever the user asks for literature, references, prior work, a value from a paper, '
             'or what is in their library. Cite what you use (authors, year, title, DOI or link) and never '
             'invent a reference: if a search finds nothing, say so.']
    if zotero:
        where = ('the Zotero desktop app on this computer' if conf.get('zotero_mode') == 'local'
                 else 'their zotero.org library')
        lines += ['',
                  f'### Zotero — the user\'s own reference library ({where}), read-only',
                  'Look here first for anything the user may already have collected.',
                  f'- MCP tools, when your client lists the `{ZOTERO_SERVER}` server: `zotero_search`, '
                  '`zotero_item`, `zotero_collections`, `zotero_fulltext`.',
                  '- Otherwise run the same thing from the shell (JSON on stdout):',
                  f'  - `{command} search "<words>" --limit 10`',
                  f'  - `{command} item <KEY>`  (abstract, notes, attachments)',
                  f'  - `{command} collections`  and  `{command} search "<words>" --collection <KEY>`',
                  f'  - `{command} fulltext <KEY>`  (indexed PDF text, when Zotero has it)',
                  '- You cannot add, change or delete anything in Zotero.']
    if consensus:
        lines += ['',
                  '### Consensus (consensus.app) — search engine over peer-reviewed papers',
                  f'- Available as the MCP server `{CONSENSUS_SERVER}` ({CONSENSUS_MCP_URL}), signed in with the '
                  'user\'s own Consensus account (their institution\'s licence applies).',
                  '- Use it for questions about the published literature: findings, consensus on a question, '
                  'papers on a topic. If the user linked Zotero inside Consensus, Consensus uses that library itself.',
                  '- If its tools are not listed or answer “unauthorized”, tell the user to open '
                  'SPM Studio › Settings › Literature › Consensus › Sign in, then try again. Do not ask for a password.']
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


def call_tool(name: str, arguments: dict):
    arguments = arguments or {}
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
        return reply({'tools': TOOLS})
    if method == 'tools/call':
        params = message.get('params') or {}
        try:
            result = call_tool(params.get('name'), params.get('arguments') or {})
            text = json.dumps(result, ensure_ascii=False, indent=1)
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
                                     description='Read-only access to the Zotero library connected in SPM Studio.')
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
    sub.add_parser('status', help='check the connection')
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
        else:
            result = zotero_status()
    except LiteratureError as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stdout)
        return 1
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
