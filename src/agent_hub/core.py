"""Agent Hub engine (Qt, no widgets): one ``ChatRun`` per open chat, approvals, queue, capacity, usage.

The engine lives outside every view: the embedded panel, the detached window and the standalone window all
show the same ``HubCore``. Moving a view (detach / re-dock) never touches a running agent.
"""
from __future__ import annotations

import json
import secrets
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcessEnvironment, QThread, QTimer, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer

from . import brainstorm
from . import context as ctx
from . import policy, scheduler
from . import settings as hubsettings
from .host import current as current_host
from .store import Store
from .usage import Ledger, estimate_tokens
from .limits import Limits, from_claude, from_codex, from_headers

HERE = Path(__file__).resolve().parent
GATE = HERE / 'pi_gate' / 'spm-hub-gate.ts'
MCP = HERE / 'approval_mcp.py'
ACTIVE = ('running', 'approval')


# ====================================================================== approval socket
class ApprovalServer(QObject):
    """127.0.0.1 socket for approval_mcp.py (Claude Code). One JSON line in, one JSON line out; a one-time
    token per process authenticates the caller."""
    request = Signal(str, str, dict, object)          # chat id, tool, input, reply(decision: dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = secrets.token_hex(16)
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._accept)
        self.server.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0)

    @property
    def port(self) -> int:
        return int(self.server.serverPort())

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.setProperty('buffer', b'')
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock):
        data = bytes(sock.property('buffer') or b'') + bytes(sock.readAll())
        if len(data) > 2_000_000:
            sock.abort()
            return
        sock.setProperty('buffer', data)
        if b'\n' not in data:
            return
        line = data.split(b'\n', 1)[0]
        try:
            msg = json.loads(line.decode('utf8'))
        except ValueError:
            sock.abort()
            return
        if not secrets.compare_digest(str(msg.get('token', '')), self.token):
            sock.write(b'{"behavior":"deny","message":"bad token"}\n')
            sock.disconnectFromHost()
            return
        state = {'done': False}

        def reply(decision: dict, s=sock, st=state):
            if st['done']:
                return
            st['done'] = True
            try:
                s.write((json.dumps(decision) + '\n').encode('utf8'))
                s.flush()
                s.disconnectFromHost()
            except RuntimeError:
                pass
        tool_input = msg.get('input') if isinstance(msg.get('input'), dict) else {}
        self.request.emit(str(msg.get('chat', '')), str(msg.get('tool', '')), tool_input, reply)


# ====================================================================== backends
def _pi_class():
    from .agents.pi_rpc import PiRpcBackend
    from .agents import platform_util as pu

    class HubPiBackend(PiRpcBackend):
        """Pi RPC with the approval gate (confirm dialogs go to the hub) and per-reply usage/model capture."""
        approval = Signal(dict)
        usage = Signal(dict)
        route = Signal(str)

        def __init__(self, *args, gate=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.gate = str(gate) if gate else ''

        def start(self):
            from PySide6.QtCore import QProcess as _QP
            if self.process.state() != _QP.ProcessState.NotRunning:
                return
            try:
                program, prefix = pu.resolve_command(self.executable)
            except (OSError, ValueError) as exc:
                self.error.emit('Pi executable not usable: ' + str(exc))
                self.stopped.emit()
                return
            self.workspace.mkdir(parents=True, exist_ok=True)
            self.session.mkdir(parents=True, exist_ok=True)
            environment = QProcessEnvironment.systemEnvironment()
            for key, value in pu.command_env(self.extra_env).items():
                if key == 'PATH' or key in self.extra_env or key == 'PI_SKIP_VERSION_CHECK':
                    environment.insert(key, value)
            self.process.setProcessEnvironment(environment)
            self.process.setWorkingDirectory(str(self.workspace))
            self.process.setProgram(program)
            args = list(prefix) + ['--mode', 'rpc', '--session-dir', str(self.session)]
            if self._compat < 1:
                args += ['--session-id', self.session_id, '--no-approve']
            if self.system_append and self._compat < 2:
                args += ['--append-system-prompt', self.system_append]
            self._context_pending = bool(self.system_append and self._compat >= 2)
            if self.gate:
                args += ['-e', self.gate]
            self.process.setArguments(args)
            self._stopping = False
            self.process.start()

        def _handle(self, event):
            typ = event.get('type')
            if typ == 'extension_ui_request' and event.get('method') == 'confirm':
                if event.get('title') == 'spm-hub-approval':
                    try:
                        payload = json.loads(event.get('message') or '{}')
                    except ValueError:
                        payload = {}
                    self.approval.emit({'id': event.get('id'), 'tool': str(payload.get('tool', '')),
                                        'input': payload.get('input') if isinstance(payload.get('input'), dict)
                                        else {}})
                else:
                    self.approval.emit({'id': event.get('id'), 'tool': 'pi-extension',
                                        'input': {'title': str(event.get('title', '')),
                                                  'message': str(event.get('message', ''))}})
                return
            if typ == 'message_end':
                message = event.get('message') or {}
                if message.get('role') == 'assistant':
                    u = message.get('usage') or {}
                    if isinstance(u, dict) and (u.get('input') or u.get('output')):
                        cost = u.get('cost') if isinstance(u.get('cost'), dict) else {}
                        self.usage.emit({'input_tokens': int(u.get('input') or 0),
                                         'output_tokens': int(u.get('output') or 0),
                                         'cached_tokens': int(u.get('cacheRead') or 0),
                                         'cost_usd': cost.get('total'), 'source': 'reported by Pi'})
                    if message.get('model'):
                        actual = f"{message.get('provider', '')}/{message['model']}".strip('/')
                        self.route.emit('answered by ' + actual)
            if typ == 'extension_ui_request' and event.get('method') in ('setStatus', 'notify', 'setWidget'):
                text = event.get('statusText') or event.get('message') or event.get('text')
                if text and any(w in str(text).lower() for w in ('route', 'fast', 'smart', 'judge', 'tier')):
                    self.route.emit(str(text)[:160])
            super()._handle(event)

        def answer(self, request_id, ok: bool):
            if request_id is not None and self.running:
                self.process.write(json.dumps({'type': 'extension_ui_response', 'id': request_id,
                                               'confirmed': bool(ok)}).encode('utf8') + b'\n')
    return HubPiBackend


def _cli_class():
    from .agents.cli_agents import CliAgentBackend
    from .agents.cli_events import CliEvents
    from .agents import platform_util as pu

    class HubCliBackend(CliAgentBackend):
        """Claude Code / Codex turns with the hub's access rules (approval tool, folders, full access) and the
        brainstorming read-only mode."""

        def __init__(self, agent, executable, workspace, state_file, *, roots, full, mcp_config='',
                     read_only=False, system_append=None, parent=None):
            super().__init__(agent, executable, workspace, state_file, True, system_append=system_append,
                             parent=parent)
            self.roots = [str(r) for r in roots]
            self.full = full
            self.read_only = read_only
            self.mcp_config = str(mcp_config)

        def build(self) -> list[str]:
            if self.agent == 'claude-code':
                args = ['-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages']
                if self.read_only:
                    args += ['--permission-mode', 'plan']
                    if self.mcp_config:
                        args += ['--permission-prompt-tool', 'mcp__spmhub__approve', '--mcp-config', self.mcp_config]
                else:
                    # Full access is decided by the hub's policy on every request (never bypassPermissions), so
                    # pushes, uploads and messages still come to the user.
                    args += ['--permission-mode', 'acceptEdits' if self.full else 'default',
                             '--permission-prompt-tool', 'mcp__spmhub__approve', '--mcp-config', self.mcp_config]
                if not self.read_only:
                    for d in self.roots:
                        args += ['--add-dir', d]
                allowed = list(current_host().agent_allowed_tools())
                if not self.read_only:
                    allowed += ['Read', 'Glob', 'Grep', 'LS', 'WebFetch', 'WebSearch', 'TodoWrite']
                if allowed:
                    args += ['--allowedTools', ','.join(dict.fromkeys(allowed))]
                if self._session:
                    args += ['--resume', self._session]
                if self.system_text:
                    args += ['--append-system-prompt', self.system_text]
                return args
            if self.read_only:
                extra = ['-c', 'sandbox_mode="read-only"', '-c', 'approval_policy="never"']
            else:
                # Codex cannot ask during a run, so its sandbox never has network access (nothing can leave on
                # the user's behalf without a click); full access widens the writable folders only.
                roots = list(self.roots) + ([str(Path.home())] if self.full else [])
                extra = ['-c', 'sandbox_mode="workspace-write"', '-c', 'approval_policy="never"',
                         '-c', 'sandbox_workspace_write.network_access=false',
                         '-c', 'sandbox_workspace_write.writable_roots=[' +
                         ','.join(json.dumps(d) for d in dict.fromkeys(roots)) + ']']
            if self._session:
                return ['exec', 'resume', self._session, '--json', '--skip-git-repo-check'] + extra + ['-']
            return ['exec', '--json', '--skip-git-repo-check'] + extra + ['-']

        def prompt(self, message: str):
            if self.pending:
                self.error.emit('Wait for the current reply or stop it.')
                return
            program, prefix = pu.resolve_command(self.executable)
            if self.agent == 'codex' and self.system_text and not self._session:
                message = ('[Context — instructions for the assistant]\n' + self.system_text +
                           '\n\n[User message]\n' + message)
            env = QProcessEnvironment.systemEnvironment()
            for key, value in pu.command_env().items():
                if key == 'PATH':
                    env.insert(key, value)
            env.insert('MCP_TOOL_TIMEOUT', str(24 * 3600 * 1000))      # the user may take time to answer
            self.process.setProcessEnvironment(env)
            self.process.setWorkingDirectory(str(self.workspace))
            self.process.setProgram(program)
            self.process.setArguments(list(prefix) + self.build())
            self._buffer.clear()
            self._reducer = CliEvents(self.agent)
            self._had_error = False
            self._finished_turn = False
            self._stderr_tail = ''
            self._aborting = False
            self.pending = True
            self._message = message.encode('utf8')
            self.process.start()
    return HubCliBackend


class _DirectWorker(QThread):
    chunk = Signal(str)
    answer = Signal(dict)
    failed = Signal(str)

    def __init__(self, backend: dict, messages: list[dict], parent=None):
        super().__init__(parent)
        self.backend = dict(backend)
        self.messages = list(messages)
        self.cancelled = False

    def run(self):
        b = self.backend
        try:
            if b['kind'] == 'ollama' or b.get('wire') == 'ollama':
                from .agents import ollama
                result = ollama.chat(b['model'], self.messages, b.get('base') or ollama.OLLAMA_URL,
                                     on_text=self.chunk.emit, cancelled=lambda: self.cancelled)
                result['usage'] = {'input_tokens': result['stats']['prompt_tokens'],
                                   'output_tokens': result['stats']['output_tokens'], 'source': 'reported by Ollama'}
            else:
                from .agents.providers import request_chat_full
                from . import settings_store as ss
                from .agents.security import CredentialStore
                conn = b.get('connection') or {'provider': b['provider'], 'id': ''}
                key = ss.api_key(conn) if conn.get('id') else CredentialStore().get(b['provider'])
                wire = b.get('wire') or ('openai' if b['provider'] not in ('anthropic', 'gemini') else b['provider'])
                provider = wire if wire in ('anthropic', 'gemini') else (
                    b['provider'] if b['provider'] in ('openai', 'openrouter') else 'custom')
                base = b.get('base') or ss.PROVIDERS.get(b['provider'], {}).get('base', '')
                result = request_chat_full(provider, b['model'], self.messages, key or 'local', base, timeout=300)
                result['stats'] = {}
            if not self.cancelled:
                self.answer.emit(result)
        except Exception as exc:
            if not self.cancelled:
                from .agents.security import redact
                self.failed.emit(redact(str(exc))[:600])


class DirectBackend(QObject):
    """Local model (Ollama, LM Studio, llama.cpp) or direct API: chat only, same signals as the agents."""
    text = Signal(str)
    log = Signal(str)
    error = Signal(str)
    settled = Signal()
    model = Signal(str)
    ready = Signal()
    status = Signal(str)
    stopped = Signal()
    activity = Signal(str)
    usage = Signal(dict)
    stats = Signal(dict)
    limits = Signal(dict)

    def __init__(self, backend: dict, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.worker = None
        self.pending = False
        self.running = True
        self._streamed = False

    def start(self):
        self.ready.emit()
        self.model.emit(self.backend.get('model', ''))

    def prompt_messages(self, messages: list[dict]):
        self.pending = True
        self._streamed = False
        self.worker = _DirectWorker(self.backend, messages, self)
        self.worker.chunk.connect(self._chunk)
        self.worker.answer.connect(self._answer)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _chunk(self, piece):
        if self.pending:
            self._streamed = True
            self.text.emit(piece)

    def _answer(self, result):
        if not self.pending:
            return
        self.pending = False
        if not self._streamed:
            self.text.emit(result.get('text', ''))
        if result.get('model'):
            self.model.emit(result['model'])
        if result.get('usage'):
            self.usage.emit(result['usage'])
        if result.get('stats'):
            self.stats.emit(result['stats'])
        if result.get('ratelimit'):
            self.limits.emit({'group': 'api', 'headers': result['ratelimit'],
                              'account': self.backend.get('provider', ''),
                              'source': 'reported by the provider API (rate-limit headers)'})
        self.settled.emit()

    def _failed(self, reason):
        if not self.pending:
            return
        self.pending = False
        self.error.emit(reason)
        self.settled.emit()

    def abort(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancelled = True
        if self.pending:
            self.pending = False
            self.log.emit('Stopped.')
            self.settled.emit()

    def shutdown(self):
        self.abort()
        if self.worker is not None:
            self.worker.wait(2000)


class _ToolWorker(QThread):
    """Runs the calendar / to-do / e-mail requests of one reply off the GUI thread."""
    done = Signal(list)

    def __init__(self, requests, organizer, conf, approved=False, parent=None):
        super().__init__(parent)
        self.requests, self.organizer, self.conf, self.approved = list(requests), organizer, dict(conf), approved

    def run(self):
        from .organizer import tools
        self.done.emit([dict(tools.dispatch(r, self.organizer, self.conf, approved=self.approved), request=r)
                        for r in self.requests])


# ====================================================================== one chat
class ChatRun(QObject):
    delta = Signal(str)                 # streamed text
    finished = Signal()                 # the turn ended (chat saved)
    stateChanged = Signal(str)          # idle · queued · running · approval · done · error
    approvalAsked = Signal(dict)        # {'title', 'detail', 'tool', 'rule'}
    routeAsked = Signal(dict)           # scheduler decision needing an answer
    budgetAsked = Signal(dict)          # brainstorming budget reached
    info = Signal(str)                  # one line under the chat header
    modelChanged = Signal(str)
    activity = Signal(str)
    finalPrompt = Signal(str)           # a "Generate final prompt" reply, for the editor
    toolCard = Signal(dict)             # result card of a calendar / to-do / e-mail tool (undo, dismiss, outbox…)
    toolApproval = Signal(dict)         # a change to the user's own event / to-do waiting for Allow / Deny

    def __init__(self, core: 'HubCore', chat_id: str):
        super().__init__(core)
        self.core = core
        self.chat_id = chat_id
        self.backend = None
        self.backend_info = None
        self.state = 'idle'
        self.partial = ''
        self.error_text = ''
        self.pending_prompt = None
        self.pending_route = None
        self.pending_budget = None
        self.approvals: list[dict] = []
        self.started_at = 0.0
        self.unread = False
        self.turn = {}
        self.tool_calls = 0
        self.tool_rounds = 0
        self.tool_approvals: list[dict] = []
        self._workers = []

    # ---- state
    def set_state(self, state: str):
        if state != self.state:
            self.state = state
            self.stateChanged.emit(state)
            self.core.stateChanged.emit(self.chat_id, state)

    @property
    def group(self) -> str:
        return (self.backend_info or {}).get('group', '')

    @property
    def busy(self) -> bool:
        return self.state in ACTIVE

    @property
    def chat(self) -> dict:
        return self.core.store.get_chat(self.chat_id) or {}

    @property
    def brainstorming(self) -> bool:
        return self.chat.get('mode') == 'brainstorm'

    # ---- sending
    def send(self, text: str, requested: str, kind: str = ''):
        chat = self.core.store.get_chat(self.chat_id)
        if chat is None or self.busy or self.state == 'queued':
            return
        extra = {'kind': kind} if kind else {}
        if not kind:
            self.tool_rounds = 0                    # a new question from the user
        self.core.store.add_message(self.chat_id, 'user', text, **extra)
        self.core.chatsChanged.emit()
        if self.brainstorming and not self._budget_ok(requested):
            return
        self.core.schedule(self, requested)

    def regenerate(self):
        if self.busy or self.state == 'queued':
            return
        if self.core.store.drop_last_reply(self.chat_id):
            self.core.chatsChanged.emit()
            self.core.schedule(self, self.chat.get('backend', 'auto'))

    def _budget_ok(self, requested) -> bool:
        limit = int(self.chat.get('budget') or self.core.conf.get('brainstorm_budget_tokens', 60000))
        used = self.core.ledger.chat_tokens(self.chat_id, mode='brainstorm')
        if limit and used >= limit:
            self.pending_budget = {'requested': requested, 'used': used, 'limit': limit}
            self.set_state('approval')
            self.budgetAsked.emit(dict(self.pending_budget))
            return False
        return True

    def answer_budget(self, choice: str):
        pending, self.pending_budget = self.pending_budget, None
        if not pending:
            return
        if choice == 'continue':
            self.core.store.set_meta(self.chat_id, budget=int(pending['limit'] * 1.5) + 1)
            self.set_state('idle')
            self.core.schedule(self, pending['requested'])
        else:
            self.set_state('idle')
            self.info.emit('Brainstorming budget reached: nothing was sent.')

    def resume_after_route(self, choice: str):
        """Answer of the route card: 'alternative' · 'queue' · 'anyway'."""
        decision, self.pending_route = self.pending_route, None
        if not decision:
            return
        if choice == 'alternative' and decision.get('alternative'):
            self.begin(decision['alternative'], note=f"Running on {self.core.label(decision['alternative'])}.")
        elif choice == 'anyway':
            self.begin(decision['backend'], note='Running in parallel on the same account.')
        else:
            self.core.enqueue(self, decision['backend'])

    def begin(self, key: str, note: str = ''):
        info = scheduler.find(self.core.backends, key)
        if info is None:
            self._fail(f'Model {key} is not available any more — choose another one in the message box.')
            return
        chat = self.core.store.get_chat(self.chat_id)
        project = self.core.store.project(chat.get('project', '')) if chat.get('project') else None
        workspace = ctx.workspace_for(project, self.core.root)
        conf = self.core.conf
        brainstorming = chat.get('mode') == 'brainstorm'
        roots = policy.allowed_roots(conf, ctx.app_folders(), workspace)
        try:
            context_file = ctx.build(chat, project, self.core.store.projects(), conf, self.core.root, workspace,
                                     roots, info['tools'] and not brainstorming, github_text=self.core.github_text())
            organizer_text = self.core.organizer_instructions() if not brainstorming else ''
            if brainstorming or organizer_text:
                context_file.write_text(context_file.read_text(encoding='utf8') + '\n\n' +
                                        (brainstorm.INSTRUCTIONS if brainstorming else organizer_text),
                                        encoding='utf8')
        except OSError:
            context_file = None
        messages = chat['messages']
        seen = int((chat.get('seen_by') or {}).get(key, 0))
        missed = messages[seen:-1] if messages and messages[-1]['role'] == 'user' else messages[seen:]
        text = messages[-1]['content'] if messages and messages[-1]['role'] == 'user' else ''
        if not text:
            return
        signature = self._signature(conf, roots, workspace, brainstorming)
        if (self.backend_info or {}).get('key') != key or self.backend is None or \
                (info['kind'] == 'pi' and not getattr(self.backend, 'running', False)) or \
                getattr(self, '_access_sig', None) != signature:
            self._make_backend(info, workspace, roots, context_file, brainstorming)
        self._access_sig = signature
        self.backend_info = info
        self.partial = ''
        self.error_text = ''
        self.started_at = time.monotonic()
        self.turn = {'usage': {}, 'stats': {}, 'route': [], 'model': '', 'prompt': text,
                     'kind': messages[-1].get('kind', '')}
        if note:
            self.turn['route'].append(note)
        self.tool_calls = 0
        self._talking = False
        self.set_state('running')
        self.core.detail_state('thinking')
        self.modelChanged.emit(info['label'])
        if note:
            self.info.emit(note)
        chat['last_backend'] = key
        self.core.store.save_chat(chat)
        if info['kind'] in ('ollama', 'api'):
            preamble = ctx.hub_text(project, self.core.store.projects(), conf, roots, False)
            if brainstorming:
                preamble += '\n\n' + brainstorm.INSTRUCTIONS
            else:
                preamble += self.core.organizer_instructions()
                try:
                    host_extra = current_host().extra_instructions('direct') or ''
                except Exception:
                    host_extra = ''
                if host_extra:
                    preamble += '\n\n' + host_extra
            history = [{'role': 'user', 'content': '[Instructions for this conversation]\n' + preamble},
                       {'role': 'assistant', 'content': 'Understood.'}]
            history += [{'role': m['role'], 'content': m['content']} for m in messages
                        if m['role'] in ('user', 'assistant')][-22:]
            self.backend.prompt_messages(history)
            return
        message = (ctx.recap(missed) if missed else '') + text
        if getattr(self.backend, 'running', False) and info['kind'] != 'pi':
            self.backend.prompt(message)
        elif info['kind'] == 'pi' and getattr(self.backend, '_hub_ready', False) and self.backend.running:
            self.backend.prompt(message)
        else:
            self.pending_prompt = message

    @staticmethod
    def _signature(conf, roots, workspace, brainstorming=False):
        return (bool(conf.get('full_access')), tuple(str(r) for r in roots), str(workspace), bool(brainstorming))

    def _make_backend(self, info: dict, workspace: Path, roots, context_file, brainstorming=False):
        self._drop_backend()
        conf = self.core.conf
        full = bool(conf.get('full_access')) and not brainstorming
        sessions = self.core.root / 'sessions'
        sessions.mkdir(parents=True, exist_ok=True)
        if info['kind'] == 'pi':
            if info.get('managed'):
                try:
                    current_host().judge_port_hook()
                except Exception:
                    pass
            cls = _pi_class()
            backend = cls(info.get('executable', ''), workspace, sessions / 'pi', coding=True,
                          session_id='hub' + self.chat_id[1:25] + ('b' if brainstorming else ''),
                          parent=self, system_append=context_file, env=info.get('env') or {},
                          gate=GATE)
            backend.approval.connect(self._pi_approval)
            backend.usage.connect(self._usage)
            backend.route.connect(self._route_event)
            backend._hub_ready = False

            def ready(b=backend):
                b._hub_ready = True
                if self.pending_prompt is not None:
                    message, self.pending_prompt = self.pending_prompt, None
                    QTimer.singleShot(150, lambda m=message: b.prompt(m))
            backend.ready.connect(ready)
        elif info['kind'] in ('claude-code', 'codex'):
            cls = _cli_class()
            mcp_config = ''
            if info['kind'] == 'claude-code':          # also with full access: outbound actions still ask
                mcp_config = self.core.mcp_config(self.chat_id)
            state = sessions / f"{info['kind']}-{self.chat_id}{'-brainstorm' if brainstorming else ''}.json"
            backend = cls(info['kind'], info['executable'], workspace, state, roots=roots, full=full,
                          mcp_config=mcp_config, read_only=brainstorming, system_append=context_file, parent=self)
            backend.usage.connect(self._usage)
            if hasattr(backend, 'limits'):
                backend.limits.connect(self.core.record_limits)
        else:
            backend = DirectBackend(info, self)
            backend.usage.connect(self._usage)
            backend.stats.connect(self._stats)
            if hasattr(backend, 'limits'):
                backend.limits.connect(self.core.record_limits)
        backend.text.connect(self._text)
        backend.error.connect(self._error)
        backend.settled.connect(self._settled)
        backend.model.connect(self._model)
        backend.activity.connect(self._activity)
        backend.status.connect(self.info.emit)
        backend.stopped.connect(self._stopped)
        self.backend = backend
        backend.start()

    def _drop_backend(self):
        if self.backend is not None:
            try:
                self.backend.shutdown()
            except RuntimeError:
                pass
            self.backend.deleteLater()
            self.backend = None

    # ---- backend events
    def _text(self, part: str):
        if not getattr(self, '_talking', False) and part.strip():
            self._talking = True
            self.core.detail_state('talking')
        self.partial += part
        if len(self.partial) > 400_000:
            self.partial = self.partial[-400_000:]
        self.delta.emit(part)

    def _model(self, m: str):
        label = (self.backend_info or {}).get('label', '')
        if m:
            self.turn['model'] = m
        self.modelChanged.emit(f'{label} · {m}' if m else label)

    def _activity(self, text: str):
        self._talking = False
        self.core.detail_state('working')
        self.turn.setdefault('activity', []).append(text[:160])
        self.turn['activity'] = self.turn['activity'][-40:]
        self.activity.emit(text)

    def _usage(self, u: dict):
        total = self.turn.setdefault('usage', {})
        for k in ('input_tokens', 'output_tokens', 'cached_tokens', 'cache_write_tokens'):
            if u.get(k) is not None:
                total[k] = int(total.get(k, 0)) + int(u[k] or 0)
        if u.get('cost_usd') is not None:
            total['cost_usd'] = round(float(total.get('cost_usd') or 0) + float(u['cost_usd']), 6)
        if u.get('source'):
            total['source'] = u['source']

    def _stats(self, s: dict):
        self.turn['stats'] = dict(s)
        self.core.localStats.emit(dict(s, model=(self.backend_info or {}).get('model', '')))

    def _route_event(self, text: str):
        route = self.turn.setdefault('route', [])
        if not route or route[-1] != text:
            route.append(text)
            if text.startswith('answered by '):
                self.turn['model'] = text[len('answered by '):]

    def _error(self, message: str):
        self.error_text = str(message)[:800]
        self.info.emit('Error: ' + self.error_text)

    def _stopped(self):
        if self.busy:
            self._fail(self.error_text or 'The agent stopped.')

    def _fail(self, reason: str):
        self.error_text = reason
        self.core.store.add_message(self.chat_id, 'note', 'Error: ' + reason)
        self.set_state('error')
        self.finished.emit()
        self.core.released()

    def _meta(self) -> dict:
        info = self.backend_info or {}
        duration = round(time.monotonic() - self.started_at, 1) if self.started_at else None
        meta = {'model': info.get('label', ''), 'backend': info.get('key', ''), 'group': info.get('group', ''),
                'account': info.get('account') or scheduler.GROUP_LABELS.get(info.get('group', ''), ''),
                'actual_model': self.turn.get('model', ''), 'local': info.get('group') == 'local',
                'connection': info.get('kind', ''), 'duration_s': duration,
                'route': list(self.turn.get('route', []))[-6:], 'activity': list(self.turn.get('activity', []))[-20:],
                'mode': 'brainstorm' if self.brainstorming else 'normal'}
        usage = dict(self.turn.get('usage') or {})
        if usage.get('input_tokens') or usage.get('output_tokens'):
            meta['usage'] = usage
        if self.turn.get('stats'):
            meta['stats'] = self.turn['stats']
        return meta

    def _settled(self):
        if not self.busy:
            return
        text = self.partial.strip()
        chat = self.core.store.get_chat(self.chat_id)
        key = (self.backend_info or {}).get('key', '')
        moves = ctx.find_moves(text)
        meta = self._meta()
        if text:
            kind = 'final_prompt' if self.turn.get('kind') == 'final_prompt_request' else ''
            self.core.store.add_message(self.chat_id, 'assistant', ctx.strip_tags(text) or text, **meta,
                                        **({'kind': kind} if kind else {}))
        elif self.error_text:
            self.core.store.add_message(self.chat_id, 'note', 'Error: ' + self.error_text)
        try:
            self.core.ledger.record(chat=self.chat_id, project=(chat or {}).get('project', ''), backend=key,
                                    group=meta['group'], account=meta['account'],
                                    model=meta['actual_model'] or meta['model'], usage=meta.get('usage'),
                                    prompt_text=self.turn.get('prompt', ''), reply_text=text,
                                    duration_s=meta['duration_s'], mode=meta['mode'], stats=meta.get('stats'))
            self.core.usageChanged.emit()
        except OSError:
            pass
        if chat is not None:
            chat.setdefault('seen_by', {})[key] = len(chat['messages'])
            if meta['mode'] == 'brainstorm':
                spec = brainstorm.latest_spec(chat['messages'])
                if spec:
                    chat['spec'] = spec
            self.core.store.save_chat(chat)
        self.partial = ''
        for request in list(self.approvals):        # the turn is over: nothing is waiting any more
            self._answer(request, False, silent=True)
        self.approvals.clear()
        self.unread = True
        self.set_state('error' if (self.error_text and not text) else 'done')
        self.finished.emit()
        self.core.chatsChanged.emit()
        self.core.released()
        if text and self.turn.get('kind') == 'final_prompt_request':
            self.finalPrompt.emit(ctx.strip_tags(brainstorm.strip_spec(text)))
        if moves:
            self.core.agent_move(self, moves[0])
        if text and not self.error_text:
            self._after_reply(text, key)

    # ---- calendar / to-do / e-mail tools and host follow-ups requested in a reply
    def _after_reply(self, text: str, key: str):
        from .organizer import tools
        requests = tools.parse(text) if self.core.organizer_enabled() else []
        if self.brainstorming:
            requests = [r for r in requests if r.get('tool') in tools.READ]
        if requests:
            if self.tool_rounds >= tools.MAX_ROUNDS:
                self.info.emit('Tool limit for one question reached; ask again to continue.')
                return
            self.tool_rounds += 1
            self.info.emit('Calendar · to-do · e-mail: ' + ', '.join(str(r.get('tool')) for r in requests))
            worker = _ToolWorker(requests, self.core.organizer, self.core.conf, parent=self)
            worker.done.connect(lambda results, k=key: self._tools_done(results, k))
            worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
            self._workers.append(worker)
            worker.start()
            return
        chat = self.chat
        try:
            handled = current_host().handle_reply(text, chat, lambda message, summary='', k=key:
                                                  self._host_done(message, summary, k))
        except Exception:
            handled = False
        if handled:
            self.info.emit('Working on the request in the application…')

    def _tools_done(self, results: list, key: str):
        from .organizer import tools
        summary = '; '.join(f"{r['tool']} {'ok' if r['ok'] else 'failed'}" for r in results)
        self.core.store.add_message(self.chat_id, 'note', 'Agent Hub tools: ' + summary, kind='tool_note',
                                    details=[{'tool': r['tool'], 'ok': r['ok'], 'text': r['text'][:2000]}
                                             for r in results])
        self.core.chatsChanged.emit()
        for r in results:
            if r.get('pending') == 'approval':
                request = {'request': r['request'], 'title': r['title'], 'detail': r['detail']}
                self.tool_approvals.append(request)
                self.toolApproval.emit(request)
            elif r.get('card'):
                self.toolCard.emit(dict(r['card'], text=r['text']))
        self.core.organizerChanged.emit()
        if tools.needs_followup(results) and not self.busy and self.state != 'queued':
            self.send(tools.result_message(results), key or self.chat.get('backend', 'auto'), kind='tool_result')

    def answer_tool(self, request: dict, allow: bool):
        """The user answered the approval card of a change to their own event / to-do."""
        if request in self.tool_approvals:
            self.tool_approvals.remove(request)
        if not allow:
            self.core.store.add_message(self.chat_id, 'note', 'Not changed (denied): ' + request['title'],
                                        kind='tool_note')
            self.core.chatsChanged.emit()
            return
        worker = _ToolWorker([request['request']], self.core.organizer, self.core.conf, approved=True, parent=self)

        def done(results):
            r = results[0]
            self.core.store.add_message(self.chat_id, 'note', ('Done: ' if r['ok'] else 'Failed: ') + r['text'],
                                        kind='tool_note')
            self.core.chatsChanged.emit()
            self.core.organizerChanged.emit()
        worker.done.connect(done)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _host_done(self, message, summary, key):
        if summary:
            self.info.emit(summary)
        if message and not self.busy and self.state != 'queued':
            if self.tool_rounds >= 4:
                self.info.emit('Action limit for one question reached; ask again to continue.')
                return
            self.tool_rounds += 1
            self.send(message, key or self.chat.get('backend', 'auto'), kind='host_result')

    def stop(self):
        if self.state == 'queued':
            self.core.dequeue(self)
            self.set_state('idle')
            return
        if self.pending_route is not None or self.pending_budget is not None:
            self.pending_route = self.pending_budget = None
            self.set_state('idle')
            return
        if self.backend is not None and self.busy:
            for request in list(self.approvals):
                self._answer(request, False, silent=True)
            self.approvals.clear()
            self.backend.abort()
            if self.backend_info and self.backend_info['kind'] in ('claude-code', 'codex', 'ollama', 'api'):
                return                                   # their settled signal follows
            QTimer.singleShot(4000, lambda: self._settled() if self.busy else None)

    def shutdown(self):
        self._drop_backend()

    # ---- approvals
    def _pi_approval(self, request: dict):
        backend = self.backend
        rid = request.get('id')
        self.ask(request['tool'], request['input'], lambda decision, b=backend, i=rid:
                 b.answer(i, decision.get('behavior') == 'allow') if b is not None else None)

    def ask(self, tool: str, tool_input: dict, reply):
        conf = self.core.conf
        chat = self.chat
        if chat.get('mode') == 'brainstorm':                   # enforced here, whatever the model does
            verdict, reason = brainstorm.tool_decision(tool, conf, self.tool_calls)
            if verdict == 'allow':
                self.tool_calls += 1
                reply({'behavior': 'allow'})
            else:
                self.turn.setdefault('route', []).append('blocked: ' + policy.normalize(tool))
                reply({'behavior': 'deny', 'message': reason})
            return
        project = self.core.store.project(chat.get('project', '')) if chat.get('project') else None
        workspace = ctx.workspace_for(project, self.core.root)
        roots = policy.allowed_roots(conf, ctx.app_folders(), workspace)
        if tool == 'pi-extension':
            verdict = 'allow' if conf.get('full_access') else 'ask'
            title, detail = tool_input.get('title') or 'Pi extension', tool_input.get('message', '')
        else:
            verdict = policy.decide(tool, tool_input, conf, roots, cwd=workspace)
            title, detail = policy.describe(tool, tool_input)
        if verdict == 'allow':
            reply({'behavior': 'allow'})
            return
        outbound = policy.outbound(tool, tool_input) if tool != 'pi-extension' else ''
        request = {'tool': tool, 'input': tool_input, 'reply': reply, 'title': title, 'detail': detail,
                   'outbound': outbound}
        self.approvals.append(request)
        self.set_state('approval')
        self.approvalAsked.emit({'title': title, 'detail': detail, 'tool': tool, 'outbound': outbound,
                                 'rule': policy.rule_for(tool, tool_input) if tool != 'pi-extension' else None})

    def answer_approval(self, choice: str):
        """'allow' · 'always' · 'deny' for the oldest waiting request."""
        if not self.approvals:
            return
        request = self.approvals.pop(0)
        if choice == 'always' and request['tool'] != 'pi-extension' and not request.get('outbound'):
            rule = policy.rule_for(request['tool'], request['input'])
            if rule:
                self.core.add_rule(rule)
        self._answer(request, choice in ('allow', 'always'))
        if self.approvals:
            nxt = self.approvals[0]
            self.approvalAsked.emit({'title': nxt['title'], 'detail': nxt['detail'], 'tool': nxt['tool'],
                                     'outbound': nxt.get('outbound', ''),
                                     'rule': policy.rule_for(nxt['tool'], nxt['input'])})
        elif self.state == 'approval':
            self.set_state('running')

    def _answer(self, request, ok: bool, silent=False):
        try:
            request['reply']({'behavior': 'allow'} if ok else
                             {'behavior': 'deny', 'message': 'The user denied this action.' if not silent else
                              'The turn ended before the user answered.'})
        except Exception:
            pass


# ====================================================================== the hub
class HubCore(QObject):
    stateChanged = Signal(str, str)     # chat id, state
    chatsChanged = Signal()
    settingsChanged = Signal()
    backendsChanged = Signal()
    usageChanged = Signal()
    localStats = Signal(dict)           # last local reply: tokens/s, time to first token (Ollama counters)
    moveSuggested = Signal(str, dict)   # chat id, {'project', 'name', 'by': 'agent'|'rules'}
    overall = Signal(str)               # aggregated state for host decorations: working · listening · success …
    limitsChanged = Signal()            # provider-reported limits (rate-limit events, headers, Codex logs)
    organizerChanged = Signal()         # the assistant changed the calendar / to-do / outbox

    def __init__(self, root: Path | None = None, parent=None):
        super().__init__(parent)
        host = current_host()
        self.root = Path(root) if root else Path(host.data_dir())
        self.root.mkdir(parents=True, exist_ok=True)
        from .migrate import migrate_legacy
        self.migration = migrate_legacy(self.root, host.legacy_data_dirs())
        self.store = Store(self.root, defaults=host.default_projects())
        self.store.restore_default_projects() if self.migration.get('copied') else None
        self.ledger = Ledger(self.root)
        self.limits = Limits(self.root)
        self._organizer = None
        self.conf = hubsettings.load(self.root)
        self.runs: dict[str, ChatRun] = {}
        self.queue: list[tuple[ChatRun, str]] = []
        self.backends: list[dict] = []
        self.ai_conf = {}
        self.github = {'installed': False, 'login': '', 'error': ''}
        self.approval_server = ApprovalServer(self)
        self.approval_server.request.connect(self._mcp_request)
        self.stateChanged.connect(lambda *_: self._emit_overall())
        self.refresh_backends()

    # ---- organizer (calendar, to-do, e-mail) — created on first use
    @property
    def organizer(self):
        if self._organizer is None:
            from . import organizer
            self._organizer = organizer.shared()
        return self._organizer

    def organizer_enabled(self) -> bool:
        return bool(self.conf.get('assistant_organizer', True))

    def organizer_instructions(self) -> str:
        if not self.organizer_enabled():
            return ''
        try:
            from .organizer import tools
            return '\n' + tools.instructions(self.organizer, bool(self.conf.get('assistant_mail', True)))
        except Exception:
            return ''

    def record_limits(self, payload: dict):
        try:
            group = payload.get('group', '')
            if 'info' in payload:
                windows = from_claude(payload['info'])
            elif 'codex' in payload:
                windows = from_codex(payload['codex'])
            else:
                windows = from_headers(payload.get('headers') or {})
            if windows:
                self.limits.record(group if group != 'api' else 'api:' + payload.get('account', ''), windows,
                                   payload.get('source', 'reported by the provider'), payload.get('account', ''))
                self.limitsChanged.emit()
        except (OSError, TypeError, ValueError):
            pass

    # ---- settings
    def save_settings(self, conf: dict):
        self.conf = hubsettings.save(self.root, conf)
        self.settingsChanged.emit()

    def add_rule(self, rule: dict):
        conf = dict(self.conf)
        rules = [r for r in conf.get('always_rules', []) if r != rule]
        conf['always_rules'] = rules + [rule]
        self.save_settings(conf)

    # ---- backends
    def refresh_backends(self):
        try:
            self.ai_conf = current_host().ai_config() or {}
        except Exception:
            self.ai_conf = {}
        self.backends = scheduler.detect_backends(self.ai_conf)
        self.backendsChanged.emit()

    def refresh_github(self):
        from . import github
        self.github = github.status()
        return self.github

    def github_text(self) -> str:
        from . import github
        return github.agent_context(self.github.get('login', ''))

    def label(self, key: str) -> str:
        if key == 'auto':
            return 'Auto'
        b = scheduler.find(self.backends, key)
        return b['label'] if b else key

    def mcp_config(self, chat_id: str) -> str:
        folder = self.root / 'context'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'mcp-{chat_id}.json'
        path.write_text(json.dumps({'mcpServers': {'spmhub': {
            'type': 'stdio', 'command': sys.executable,
            'args': [str(MCP), '--port', str(self.approval_server.port), '--token', self.approval_server.token,
                     '--chat', chat_id]}}}), encoding='utf8')
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return str(path)

    # ---- runs
    def run_for(self, chat_id: str) -> ChatRun:
        run = self.runs.get(chat_id)
        if run is None:
            run = ChatRun(self, chat_id)
            self.runs[chat_id] = run
        return run

    def close_run(self, chat_id: str):
        run = self.runs.get(chat_id)
        if run is not None and not run.busy and run.state != 'queued':
            run.shutdown()
            self.runs.pop(chat_id, None)
            run.deleteLater()

    def running_counts(self) -> dict:
        counts = {}
        for run in self.runs.values():
            working = run.state == 'running' or (run.state == 'approval' and run.approvals)
            if working and run.group:
                counts[run.group] = counts.get(run.group, 0) + 1
        return counts

    def busy_names(self) -> dict:
        names = {}
        for run in self.runs.values():
            if run.busy and run.group:
                chat = self.store.get_chat(run.chat_id) or {}
                names.setdefault(run.group, chat.get('title', ''))
        return names

    def schedule(self, run: ChatRun, requested: str):
        chat = self.store.get_chat(run.chat_id) or {}
        text = (chat.get('messages') or [{}])[-1].get('content', '')
        if chat.get('mode') == 'brainstorm' and requested == 'auto':
            requested = brainstorm.choose_backend(self.backends, self.conf, self.running_counts()) or 'auto'
            size, need_tools = 'small', False
        else:
            size, _why = scheduler.task_size(text, self.ai_conf)
            need_tools = requested == 'auto' and size == 'large'
        decision = scheduler.plan(requested, self.backends, self.running_counts(), self.conf, size=size,
                                  need_tools=need_tools, busy_names=self.busy_names())
        if decision['action'] == 'run':
            note = decision['reason'] if (requested == 'auto' or decision.get('alternative')) else ''
            if chat.get('mode') == 'brainstorm':
                note = 'Brainstorming (no execution) · ' + self.label(decision['backend'])
            run.begin(decision['backend'], note=note)
        elif decision['action'] == 'ask':
            run.pending_route = decision
            run.set_state('approval')
            run.routeAsked.emit({**decision, 'label': self.label(decision['backend']),
                                 'alt_label': self.label(decision['alternative'])})
        else:
            run.info.emit(decision['reason'])
            self.enqueue(run, decision['backend'])

    def enqueue(self, run: ChatRun, key: str):
        if not key:
            run._fail('No model is set up yet: open Settings › AI Providers & Accounts first.')
            return
        self.queue = [(r, k) for r, k in self.queue if r is not run] + [(run, key)]
        run.set_state('queued')

    def dequeue(self, run: ChatRun):
        self.queue = [(r, k) for r, k in self.queue if r is not run]

    def released(self):
        QTimer.singleShot(0, self._start_queued)

    def _start_queued(self):
        for run, key in list(self.queue):
            info = scheduler.find(self.backends, key)
            if info is None:
                continue
            if scheduler.capacity(info, self.running_counts(), self.conf) > 0:
                self.dequeue(run)
                run.begin(key, note='Started from the queue.')

    # ---- brainstorming → execution
    def generate_final_prompt(self, chat_id: str):
        run = self.run_for(chat_id)
        run.send(brainstorm.final_prompt_request(), self.store.get_chat(chat_id).get('backend', 'auto'),
                 kind='final_prompt_request')
        return run

    def start_execution(self, brainstorm_id: str, prompt: str, backend: str = 'auto') -> dict:
        """A new, linked chat that runs the approved prompt (never started without the user's approval)."""
        source = self.store.get_chat(brainstorm_id) or {}
        chat = self.store.new_chat(project=source.get('project', ''), backend=backend,
                                   title='Execution: ' + (source.get('title') or 'brainstorming')[:100])
        self.store.set_meta(chat['id'], links={'brainstorm': brainstorm_id})
        links = dict(source.get('links') or {})
        links['executions'] = list(links.get('executions', [])) + [chat['id']]
        if source:
            self.store.set_meta(brainstorm_id, links=links)
        self.chatsChanged.emit()
        run = self.run_for(chat['id'])
        run.send(prompt, backend, kind='execution_prompt')
        return chat

    # ---- approvals from Claude Code
    def _mcp_request(self, chat_id: str, tool: str, tool_input: dict, reply):
        run = self.runs.get(chat_id)
        if run is None:
            reply({'behavior': 'deny', 'message': 'This chat is no longer open in Agent Hub.'})
            return
        run.ask(tool, tool_input, reply)

    # ---- sorting
    def agent_move(self, run: ChatRun, project_name: str):
        project = self.store.project_by_name(project_name)
        chat = self.store.get_chat(run.chat_id)
        if project is None or chat is None or chat.get('project') == project['id']:
            return
        self.propose_move(run.chat_id, {'project': project['id'], 'name': project['name'], 'by': 'agent'})

    def propose_move(self, chat_id: str, suggestion: dict):
        verdict = policy.decide('hub_move', {'project_name': suggestion['name']}, self.conf, [])
        if verdict == 'allow':
            self.store.move_chat(chat_id, suggestion['project'])
            self.chatsChanged.emit()
            run = self.runs.get(chat_id)
            if run is not None:
                run.info.emit(f"Moved to the project “{suggestion['name']}”.")
            return
        chat = self.store.get_chat(chat_id)
        if chat is not None:
            chat['sort_asked'] = True
            self.store.save_chat(chat)
        self.moveSuggested.emit(chat_id, suggestion)

    # ---- overall state (for host decorations such as a mascot)
    def _emit_overall(self):
        states = [r.state for r in self.runs.values()]
        state = ('listening' if 'approval' in states else 'working' if 'running' in states else
                 'error' if 'error' in states else 'success' if 'done' in states else 'idle')
        self.overall.emit(state)
        try:
            current_host().assistant_state(state)
        except Exception:
            pass

    def detail_state(self, state: str):
        """Finer states for host decorations: thinking (a turn starts) · working (a tool runs) · talking (text
        arrives); the overall states (idle, working, listening, success, error) follow the runs."""
        self.overall.emit(state)
        try:
            current_host().assistant_state(state)
        except Exception:
            pass

    def active_runs(self) -> list[ChatRun]:
        return [r for r in self.runs.values() if r.busy or r.state == 'queued']

    def shutdown(self):
        for run in list(self.runs.values()):
            try:
                run.shutdown()
            except RuntimeError:
                pass
        self.runs.clear()
