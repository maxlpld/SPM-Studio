"""In-app "no-thinking" proxy for the local Judge (127.0.0.1 only).

pi-shift-router calls its Judge through an OpenAI-style ``/v1/chat/completions``
endpoint. Small reasoning models served by Ollama (e.g. Qwen 3.5) think before
answering on that endpoint, which makes a one-word routing decision slow. This
proxy translates the request to Ollama's native ``/api/chat`` with
``"think": false`` (and JSON mode when requested) and translates the answer
back, streaming or not. It replaces the separate systemd user service used in
a hand-made setup, lives only while SPM Studio runs, binds to localhost, and
never touches an existing Ollama configuration.
"""
from __future__ import annotations
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_BODY = 4_000_000


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') in ('text', None))
    return '' if content is None else str(content)


def to_native(body: dict) -> dict:
    messages = []
    for m in body.get('messages') or []:
        role = m.get('role', 'user')
        role = 'system' if role == 'developer' else role
        if role not in ('system', 'user', 'assistant'):
            continue
        messages.append({'role': role, 'content': _text(m.get('content'))})
    options = {}
    for src, dst in (('temperature', 'temperature'), ('top_p', 'top_p'), ('seed', 'seed')):
        if body.get(src) is not None:
            options[dst] = body[src]
    limit = body.get('max_completion_tokens') or body.get('max_tokens')
    if limit:
        options['num_predict'] = int(limit)
    native = {'model': body.get('model', ''), 'messages': messages, 'stream': bool(body.get('stream')),
              'think': False, 'options': options}
    fmt = (body.get('response_format') or {}).get('type')
    if fmt in ('json_object', 'json_schema'):
        native['format'] = 'json'
    return native


def _usage(event: dict) -> dict:
    p, c = int(event.get('prompt_eval_count') or 0), int(event.get('eval_count') or 0)
    return {'prompt_tokens': p, 'completion_tokens': c, 'total_tokens': p + c}


class _Handler(BaseHTTPRequestHandler):
    server_version = 'SPMJudgeProxy/1'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):          # silence stderr
        pass

    def _json(self, code: int, data: dict):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip('/') != '/v1/models':
            return self._json(404, {'error': {'message': 'not found'}})
        try:
            with urlopen(self.server.upstream + '/api/tags', timeout=5) as r:
                tags = json.load(r)
            data = [{'id': m.get('name'), 'object': 'model', 'owned_by': 'ollama'} for m in tags.get('models', [])]
            self._json(200, {'object': 'list', 'data': data})
        except (OSError, ValueError) as exc:
            self._json(502, {'error': {'message': 'Ollama unavailable: ' + str(exc)}})

    def do_POST(self):
        if self.path.rstrip('/') != '/v1/chat/completions':
            return self._json(404, {'error': {'message': 'not found'}})
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0 or length > MAX_BODY:
            return self._json(413, {'error': {'message': 'invalid body size'}})
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            return self._json(400, {'error': {'message': 'invalid JSON'}})
        native = to_native(body)
        req = Request(self.server.upstream + '/api/chat', method='POST',
                      headers={'Content-Type': 'application/json'}, data=json.dumps(native).encode())
        cid = 'chatcmpl-' + uuid.uuid4().hex[:20]
        created = int(time.time())
        model = native['model']
        try:
            upstream = urlopen(req, timeout=self.server.timeout_s)
        except HTTPError as exc:
            detail = exc.read().decode('utf8', 'replace')[:500]
            return self._json(exc.code, {'error': {'message': 'Ollama: ' + detail}})
        except (URLError, OSError) as exc:
            return self._json(502, {'error': {'message': 'Ollama unavailable: ' + str(exc)}})
        with upstream:
            if not native['stream']:
                event = json.load(upstream)
                if event.get('error'):
                    return self._json(500, {'error': {'message': str(event['error'])}})
                return self._json(200, {
                    'id': cid, 'object': 'chat.completion', 'created': created, 'model': model,
                    'choices': [{'index': 0, 'finish_reason': 'stop',
                                 'message': {'role': 'assistant',
                                             'content': (event.get('message') or {}).get('content', '')}}],
                    'usage': _usage(event)})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True

            def send(data):
                self.wfile.write(b'data: ' + json.dumps(data).encode() + b'\n\n')
                self.wfile.flush()
            first = True
            for raw in upstream:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if event.get('error'):
                    send({'error': {'message': str(event['error'])}})
                    break
                delta = {'content': (event.get('message') or {}).get('content', '')}
                if first:
                    delta['role'] = 'assistant'
                    first = False
                done = bool(event.get('done'))
                chunk = {'id': cid, 'object': 'chat.completion.chunk', 'created': created, 'model': model,
                         'choices': [{'index': 0, 'delta': delta, 'finish_reason': 'stop' if done else None}]}
                if done:
                    chunk['usage'] = _usage(event)
                send(chunk)
                if done:
                    break
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()


class JudgeProxy:
    """Start with ``JudgeProxy().start()``; ``port`` is the bound port."""
    def __init__(self, upstream: str = 'http://127.0.0.1:11434', port: int = 11436, timeout_s: float = 120):
        self.upstream = upstream.rstrip('/')
        self.wanted = port
        self.timeout_s = timeout_s
        self.server = None
        self.thread = None

    @property
    def port(self) -> int:
        return self.server.server_address[1] if self.server else 0

    @property
    def base_v1(self) -> str:
        return f'http://127.0.0.1:{self.port}/v1'

    def start(self) -> 'JudgeProxy':
        if self.server is not None:
            return self
        for port in (self.wanted, 0):          # 0: any free port if the preferred one is taken
            try:
                self.server = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
                break
            except OSError:
                self.server = None
        if self.server is None:
            raise OSError('Could not open a local port for the Judge proxy')
        self.server.daemon_threads = True
        self.server.upstream = self.upstream
        self.server.timeout_s = self.timeout_s
        self.thread = threading.Thread(target=self.server.serve_forever, name='spm-judge-proxy', daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


_shared = None


def shared(port: int = 11436) -> JudgeProxy:
    """One proxy per SPM Studio process."""
    global _shared
    if _shared is None:
        _shared = JudgeProxy(port=port).start()
    return _shared
