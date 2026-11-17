"""Consensus (consensus.app) for the assistant: sign-in and search, Qt-free.

SPM Studio is itself the client of Consensus' MCP server
``https://mcp.consensus.app/mcp`` (Streamable HTTP, one tool: ``search``):

* **Sign in** (Settings › Literature › *Sign in to Consensus*) is the standard
  OAuth 2.0 authorization-code flow with PKCE, exactly as documented by
  Consensus: the app registers itself (Dynamic Client Registration), opens the
  Consensus sign-in page in the browser, and receives the result on a
  temporary ``http://127.0.0.1:<port>/callback`` address. The password is typed
  on consensus.app only; SPM Studio receives a token limited to the ``search``
  scope and stores it with :mod:`lit_store`.
* **API key** (optional, for organisations that hand out keys): pasted in the
  same page and sent as ``Authorization: Bearer <key>``.
* **Search** is then available to every assistant backend — Pi, Claude Code,
  Codex or a direct API chat — because the app (or the helper command the
  agent runs) makes the call. No agent has to be configured or signed in.

Endpoints are read from Consensus' discovery document; the documented values
are the fallback.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import lit_store

MCP_URL = 'https://mcp.consensus.app/mcp'
DISCOVERY_URL = 'https://consensus.app/.well-known/oauth-authorization-server'
DEFAULT_ENDPOINTS = {'authorization_endpoint': 'https://consensus.app/oauth/authorize/',
                     'token_endpoint': 'https://consensus.app/oauth/token/',
                     'registration_endpoint': 'https://consensus.app/oauth/register/'}
SCOPE = 'search'
CLIENT_NAME = 'SPM Studio'
TOKEN_NAME = 'consensus_oauth'          # lit_store entries
API_KEY_NAME = 'consensus_api_key'
PROTOCOL_VERSION = '2025-06-18'
USER_AGENT = 'SPM-Studio (literature helper)'
MAX_TEXT = 24000

CALLBACK_PAGE = ('<!doctype html><html><head><meta charset="utf-8"><title>SPM Studio</title>'
                 '<style>body{{font-family:system-ui,sans-serif;margin:15vh auto;max-width:32em;'
                 'text-align:center;color:#222}}h1{{font-size:1.4em}}</style></head><body>'
                 '<h1>{title}</h1><p>{text}</p></body></html>')


class ConsensusError(RuntimeError):
    """A message meant to be read by the user (or by the agent)."""


# ---------------------------------------------------------------------------- HTTP
def _http(url: str, *, data=None, headers=None, timeout: float = 30):
    """(status, headers, body bytes). HTTP errors are returned, network errors raised as ConsensusError."""
    request = urllib.request.Request(url, data=data, headers={'User-Agent': USER_AGENT, **(headers or {})},
                                     method='POST' if data is not None else 'GET')
    context = None
    if url.startswith('https://'):
        try:
            from .pi_setup import _ssl_context
            context = _ssl_context()
        except Exception:
            context = None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return response.status, dict(response.headers.items()), response.read(8_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read(200_000)
    except (urllib.error.URLError, OSError) as exc:
        raise ConsensusError(f'Could not reach Consensus ({getattr(exc, "reason", exc)}). '
                             'Check the internet connection.') from exc


def _json_body(body: bytes) -> dict:
    try:
        data = json.loads(body.decode('utf-8', 'replace'))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _error_text(body: bytes) -> str:
    data = _json_body(body)
    text = data.get('error_description') or data.get('error') or data.get('message') or ''
    if isinstance(text, dict):
        text = text.get('message', '')
    return str(text or body.decode('utf-8', 'replace'))[:300].strip()


# ------------------------------------------------------------------------- sign-in
def endpoints() -> dict:
    """OAuth endpoints: discovery document first, documented values as fallback."""
    found = dict(DEFAULT_ENDPOINTS)
    try:
        status, _headers, body = _http(DISCOVERY_URL, timeout=10)
        if status == 200:
            for key, value in _json_body(body).items():
                if key in DEFAULT_ENDPOINTS and isinstance(value, str) and value.startswith(('https://', 'http://')):
                    found[key] = value
    except ConsensusError:
        pass
    return found


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode()
    return verifier, challenge


class SignIn:
    """One browser sign-in. ``start()`` → URL to open; ``wait()`` → blocks until done.

    Typical use (in a worker thread)::

        flow = SignIn()
        webbrowser.open(flow.start())
        flow.wait(timeout=300)          # raises ConsensusError, or returns when signed in
    """

    def __init__(self):
        self.state = secrets.token_urlsafe(24)
        self.verifier, self.challenge = _pkce()
        self.result = None              # query of the callback
        self._server = None
        self._cancelled = threading.Event()
        self.redirect_uri = ''
        self.client = {}
        self.meta = {}

    def start(self) -> str:
        flow = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != '/callback':
                    self.send_response(404)
                    self.end_headers()
                    return
                query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                ok = 'code' in query and query.get('state') == flow.state
                page = CALLBACK_PAGE.format(
                    title='Signed in to Consensus' if ok else 'Sign-in not completed',
                    text='You can close this tab and return to SPM Studio.' if ok else
                    'Return to SPM Studio and try again.').encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                flow.result = query

        # Loopback only, on a free port chosen by the system.
        self._server = HTTPServer(('127.0.0.1', 0), Handler)
        self._server.timeout = 0.5
        self.redirect_uri = f'http://127.0.0.1:{self._server.server_port}/callback'
        self.meta = endpoints()
        registration = {'client_name': CLIENT_NAME, 'redirect_uris': [self.redirect_uri],
                        'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
                        'token_endpoint_auth_method': 'none', 'scope': SCOPE,
                        'application_type': 'native'}
        status, _headers, body = _http(self.meta['registration_endpoint'], data=json.dumps(registration).encode(),
                                       headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        self.client = _json_body(body)
        if status not in (200, 201) or not self.client.get('client_id'):
            self.close()
            raise ConsensusError('Consensus did not accept the registration of SPM Studio '
                                 f'(HTTP {status}: {_error_text(body)}).')
        query = {'response_type': 'code', 'client_id': self.client['client_id'], 'redirect_uri': self.redirect_uri,
                 'scope': SCOPE, 'state': self.state, 'code_challenge': self.challenge,
                 'code_challenge_method': 'S256', 'resource': MCP_URL}
        separator = '&' if '?' in self.meta['authorization_endpoint'] else '?'
        return self.meta['authorization_endpoint'] + separator + urllib.parse.urlencode(query)

    def cancel(self):
        self._cancelled.set()

    def close(self):
        if self._server is not None:
            try:
                self._server.server_close()
            except OSError:
                pass
            self._server = None

    def wait(self, timeout: float = 300) -> dict:
        """Wait for the browser to come back, exchange the code, store the tokens."""
        if self._server is None:
            raise ConsensusError('Sign-in was not started.')
        deadline = time.monotonic() + timeout
        try:
            while self.result is None:
                if self._cancelled.is_set():
                    raise ConsensusError('Sign-in cancelled.')
                if time.monotonic() > deadline:
                    raise ConsensusError('No answer from the browser. Click “Sign in to Consensus” to try again.')
                try:
                    self._server.handle_request()
                except (OSError, socket.error):
                    pass
        finally:
            self.close()
        query = self.result
        if query.get('state') != self.state:
            raise ConsensusError('The answer did not belong to this sign-in. Try again.')
        if 'code' not in query:
            reason = query.get('error_description') or query.get('error') or 'no authorisation code'
            raise ConsensusError('Consensus did not authorise SPM Studio: ' + str(reason)[:200])
        form = {'grant_type': 'authorization_code', 'code': query['code'], 'redirect_uri': self.redirect_uri,
                'client_id': self.client['client_id'], 'code_verifier': self.verifier, 'resource': MCP_URL}
        if self.client.get('client_secret'):
            form['client_secret'] = self.client['client_secret']
        tokens = _token_request(self.meta['token_endpoint'], form)
        record = _token_record(tokens, self.client, self.meta['token_endpoint'])
        where = lit_store.put(TOKEN_NAME, json.dumps(record))
        return {'stored': where, 'expires_at': record.get('expires_at', 0)}


def _token_request(url: str, form: dict) -> dict:
    status, _headers, body = _http(url, data=urllib.parse.urlencode(form).encode(),
                                   headers={'Content-Type': 'application/x-www-form-urlencoded',
                                            'Accept': 'application/json'})
    data = _json_body(body)
    if status != 200 or not data.get('access_token'):
        raise ConsensusError(f'Consensus did not issue a token (HTTP {status}: {_error_text(body)}).')
    return data


def _token_record(tokens: dict, client: dict, token_endpoint: str, previous: dict | None = None) -> dict:
    previous = previous or {}
    record = {'access_token': tokens['access_token'],
              'refresh_token': tokens.get('refresh_token') or previous.get('refresh_token', ''),
              'client_id': client.get('client_id', ''), 'client_secret': client.get('client_secret', ''),
              'token_endpoint': token_endpoint, 'expires_at': 0}
    try:
        if tokens.get('expires_in'):
            record['expires_at'] = int(time.time() + float(tokens['expires_in']))
    except (TypeError, ValueError):
        pass
    return record


def _load_record() -> dict:
    try:
        data = json.loads(lit_store.get(TOKEN_NAME) or '{}')
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _refresh(record: dict) -> dict:
    if not record.get('refresh_token') or not record.get('token_endpoint'):
        raise ConsensusError('The Consensus sign-in has expired. Open SPM Studio › Settings › Literature and click '
                             '“Sign in to Consensus”.')
    form = {'grant_type': 'refresh_token', 'refresh_token': record['refresh_token'], 'client_id': record['client_id'],
            'resource': MCP_URL}
    if record.get('client_secret'):
        form['client_secret'] = record['client_secret']
    try:
        tokens = _token_request(record['token_endpoint'], form)
    except ConsensusError as exc:
        raise ConsensusError('The Consensus sign-in has expired. Open SPM Studio › Settings › Literature and click '
                             f'“Sign in to Consensus”. ({exc})') from exc
    new = _token_record(tokens, {'client_id': record['client_id'], 'client_secret': record.get('client_secret', '')},
                        record['token_endpoint'], previous=record)
    lit_store.put(TOKEN_NAME, json.dumps(new))
    return new


def api_key() -> str:
    import os
    return lit_store.get(API_KEY_NAME) or os.environ.get('CONSENSUS_API_KEY', '')


def signed_in() -> bool:
    return bool(api_key() or _load_record().get('access_token'))


def sign_out():
    lit_store.clear(TOKEN_NAME)
    lit_store.clear(API_KEY_NAME)


def _bearer(force_refresh: bool = False) -> str:
    key = api_key()
    if key:
        return key
    record = _load_record()
    if not record.get('access_token'):
        raise ConsensusError('Consensus is not signed in. Open SPM Studio › Settings › Literature and click '
                             '“Sign in to Consensus”.')
    expires = record.get('expires_at') or 0
    if force_refresh or (expires and time.time() > expires - 60):
        record = _refresh(record)
    return record['access_token']


# ----------------------------------------------------------------------------- MCP
def _parse_rpc(headers: dict, body: bytes, wanted_id):
    """JSON-RPC answer from a JSON or an SSE (text/event-stream) response."""
    content_type = next((v for k, v in headers.items() if k.lower() == 'content-type'), '')
    text = body.decode('utf-8', 'replace')
    candidates = []
    if 'text/event-stream' in content_type:
        chunk = []
        for line in text.splitlines() + ['']:
            if line.startswith('data:'):
                chunk.append(line[5:].lstrip())
            elif not line.strip() and chunk:
                candidates.append('\n'.join(chunk))
                chunk = []
    else:
        candidates.append(text)
    for raw in candidates:
        try:
            message = json.loads(raw)
        except ValueError:
            continue
        for item in message if isinstance(message, list) else [message]:
            if isinstance(item, dict) and item.get('id') == wanted_id and ('result' in item or 'error' in item):
                return item
    return None


class Session:
    """Minimal MCP client over Streamable HTTP (initialize → tools/list → tools/call)."""

    def __init__(self, url: str | None = None):
        self.url = url or MCP_URL
        self.session_id = ''
        self._next = 0
        self._initialized = False

    def _post(self, payload: dict, token: str, timeout: float):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'Authorization': 'Bearer ' + token, 'MCP-Protocol-Version': PROTOCOL_VERSION}
        if self.session_id:
            headers['Mcp-Session-Id'] = self.session_id
        return _http(self.url, data=json.dumps(payload).encode('utf-8'), headers=headers, timeout=timeout)

    def request(self, method: str, params: dict | None = None, timeout: float = 90):
        self._next += 1
        payload = {'jsonrpc': '2.0', 'id': self._next, 'method': method}
        if params is not None:
            payload['params'] = params
        status, headers, body = self._post(payload, _bearer(), timeout)
        if status in (401, 403):
            # One retry with a refreshed token (an API key cannot be refreshed).
            if not api_key():
                status, headers, body = self._post(payload, _bearer(force_refresh=True), timeout)
            if status in (401, 403):
                raise ConsensusError('Consensus refused the sign-in (HTTP %d). Open SPM Studio › Settings › '
                                     'Literature and sign in again.' % status)
        if status == 429:
            raise ConsensusError('Consensus search limit reached for now; try again later (your plan decides the limit).')
        if status >= 400:
            raise ConsensusError(f'Consensus answered HTTP {status}: {_error_text(body)}')
        session = next((v for k, v in headers.items() if k.lower() == 'mcp-session-id'), '')
        if session:
            self.session_id = session
        answer = _parse_rpc(headers, body, payload['id'])
        if answer is None:
            raise ConsensusError('Unexpected answer from Consensus.')
        if 'error' in answer:
            error = answer['error'] if isinstance(answer['error'], dict) else {'message': str(answer['error'])}
            raise ConsensusError('Consensus: ' + str(error.get('message', 'error'))[:300])
        return answer['result']

    def notify(self, method: str):
        try:
            self._post({'jsonrpc': '2.0', 'method': method}, _bearer(), 20)
        except ConsensusError:
            pass

    def initialize(self):
        if self._initialized:
            return
        self.request('initialize', {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {},
                                    'clientInfo': {'name': CLIENT_NAME, 'version': '1'}}, timeout=30)
        self.notify('notifications/initialized')
        self._initialized = True

    def tools(self) -> list[dict]:
        self.initialize()
        found = self.request('tools/list', {}, timeout=30).get('tools', [])
        return [t for t in found if isinstance(t, dict)]

    def call(self, name: str, arguments: dict) -> str:
        self.initialize()
        result = self.request('tools/call', {'name': name, 'arguments': arguments})
        parts = []
        for block in result.get('content', []) if isinstance(result, dict) else []:
            if isinstance(block, dict) and block.get('type') == 'text' and block.get('text'):
                parts.append(str(block['text']))
        if not parts and isinstance(result, dict) and result.get('structuredContent') is not None:
            parts.append(json.dumps(result['structuredContent'], ensure_ascii=False, indent=1))
        text = '\n'.join(parts).strip()
        if isinstance(result, dict) and result.get('isError'):
            raise ConsensusError('Consensus: ' + (text[:400] or 'the search failed'))
        return text


def _search_tool(tools: list[dict]) -> tuple[str, str]:
    """(tool name, name of its query argument) from the server's own tool list."""
    tool = next((t for t in tools if t.get('name') == 'search'), None) or \
        next((t for t in tools if 'search' in str(t.get('name', '')).lower()), None) or (tools[0] if tools else None)
    if tool is None:
        raise ConsensusError('Consensus offers no search tool to this account.')
    schema = tool.get('inputSchema') if isinstance(tool.get('inputSchema'), dict) else {}
    properties = schema.get('properties') if isinstance(schema.get('properties'), dict) else {}
    if 'query' in properties or not properties:
        return str(tool['name']), 'query'
    required = [k for k in schema.get('required', []) if isinstance(properties.get(k), dict)
                and properties[k].get('type') == 'string']
    strings = [k for k, v in properties.items() if isinstance(v, dict) and v.get('type') == 'string']
    return str(tool['name']), (required or strings or ['query'])[0]


def search(query: str, extra: dict | None = None) -> str:
    """Search peer-reviewed papers; returns Consensus' own text answer (papers with links)."""
    query = str(query or '').strip()
    if not query:
        raise ConsensusError('Give a question or some words to search for.')
    session = Session()
    name, argument = _search_tool(session.tools())
    arguments = {argument: query}
    for key, value in (extra or {}).items():
        if key not in arguments and isinstance(value, (str, int, float, bool)):
            arguments[key] = value
    text = session.call(name, arguments)
    if not text:
        return 'Consensus returned no result for this search.'
    return text[:MAX_TEXT] + ('\n[…truncated]' if len(text) > MAX_TEXT else '')


def status() -> dict:
    """Connection test for the settings page."""
    if not signed_in():
        return {'connected': False, 'message': 'Not signed in.'}
    try:
        tools = Session().tools()
    except ConsensusError as exc:
        return {'connected': False, 'message': str(exc)}
    names = ', '.join(str(t.get('name')) for t in tools) or 'none'
    how = 'API key' if api_key() else 'your Consensus account'
    return {'connected': True, 'message': f'Connected with {how} (tools: {names}).'}
