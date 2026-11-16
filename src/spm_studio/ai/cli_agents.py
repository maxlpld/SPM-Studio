"""Qt backend running Claude Code / Codex CLI turns without blocking the GUI.

Same signal surface as PiRpcBackend, so the Assistant panel treats every
backend alike. One short-lived process per turn; the conversation continues
through the agent's own session id (``--resume`` / ``exec resume``).
"""
from __future__ import annotations
import json
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal, QTimer

from . import platform_util as pu
from .cli_events import AGENTS, CliEvents, build_args
from .security import atomic_json, redact


class CliAgentBackend(QObject):
    text = Signal(str)
    log = Signal(str)
    error = Signal(str)
    settled = Signal()
    model = Signal(str)
    ready = Signal()
    status = Signal(str)
    stopped = Signal()
    activity = Signal(str)

    def __init__(self, agent: str, executable: str, workspace: Path, state_file: Path, tools: bool,
                 system_append=None, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.executable = executable
        self.workspace = Path(workspace).expanduser()
        self.state_file = Path(state_file)
        self.tools = tools
        self.system_text = ''
        if system_append:
            try:
                self.system_text = Path(system_append).read_text(encoding='utf8')
            except OSError:
                pass
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._output)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._exit)
        self.process.errorOccurred.connect(self._process_error)
        self.process.started.connect(self._send_message)
        self._message = b''
        self.pending = False
        self.current_model = ''
        self._buffer = bytearray()
        self._reducer = None
        self._had_error = False
        self._finished_turn = False
        self._stderr_tail = ''
        self._aborting = False
        self._session = self._load_session()

    # ---- session persistence (agent's own session id, per SPM conversation)
    def _load_session(self) -> str:
        try:
            data = json.loads(self.state_file.read_text(encoding='utf8'))
            return str(data.get('session', '')) if data.get('agent') == self.agent else ''
        except (OSError, ValueError):
            return ''

    def _save_session(self, sid: str):
        if sid and sid != self._session:
            self._session = sid
            try:
                atomic_json(self.state_file, {'agent': self.agent, 'session': sid})
            except OSError:
                pass

    @property
    def running(self) -> bool:
        return bool(self.executable)

    def start(self):
        try:
            pu.resolve_command(self.executable)
        except (OSError, ValueError) as exc:
            self.error.emit(f"{AGENTS[self.agent]['label']} not found: {exc}")
            self.stopped.emit()
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.log.emit(f"{AGENTS[self.agent]['label']} ready (uses its own sign-in; one process per message).")
        self.ready.emit()
        if self.agent == 'codex':
            self.model.emit('Codex · model from your Codex settings')

    def prompt(self, message: str):
        if self.pending:
            self.error.emit('Wait for the current reply or stop it.')
            return
        program, prefix = pu.resolve_command(self.executable)
        system = self.system_text
        if self.agent == 'codex' and system and not self._session:
            message = '[SPM Studio context — instructions for the assistant]\n' + system + '\n\n[User message]\n' + message
            system = ''
        try:
            from .config import load as _load_conf
            from .literature import allowed_tools as _allowed
            allowed = _allowed(_load_conf())
        except Exception:
            allowed = []
        args = prefix + build_args(self.agent, self._session, self.tools,
                                   system if self.agent == 'claude-code' else '', allowed_tools=allowed)
        env = QProcessEnvironment.systemEnvironment()
        for key, value in pu.command_env().items():
            if key == 'PATH':
                env.insert(key, value)
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(self.workspace))
        self.process.setProgram(program)
        self.process.setArguments(args)
        self._buffer.clear()
        self._reducer = CliEvents(self.agent)
        self._had_error = False
        self._finished_turn = False
        self._stderr_tail = ''
        self._aborting = False
        self.pending = True
        self._message = message.encode('utf8')
        self.process.start()                         # prompt goes to stdin once started (never via argv)

    def _send_message(self):
        self.process.write(self._message)
        self.process.closeWriteChannel()
        self._message = b''

    def abort(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._aborting = True
            self.process.terminate()
            QTimer.singleShot(2500, lambda: self.process.kill()
                              if self.process.state() != QProcess.ProcessState.NotRunning else None)

    def shutdown(self):
        self.abort()

    # ---- process I/O
    def _output(self):
        self._buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self._buffer) > 8_000_000:
            self._buffer.clear()
            self.error.emit('Oversized agent output rejected')
            return
        while b'\n' in self._buffer:
            line, _, tail = self._buffer.partition(b'\n')
            self._buffer = bytearray(tail)
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line.decode('utf8'))
            except (UnicodeDecodeError, ValueError):
                self.log.emit(redact(line.decode('utf8', 'replace'))[:300])
                continue
            for kind, value in self._reducer.interpret(event) if isinstance(event, dict) else []:
                self._handle(kind, value)

    def _handle(self, kind, value):
        if kind in ('text', 'replace'):
            if value:
                self.text.emit(value)
        elif kind == 'session':
            self._save_session(value)
        elif kind == 'model':
            self.current_model = value
            self.model.emit(value)
        elif kind == 'activity':
            self.activity.emit(value)
            self.log.emit(value)
        elif kind == 'log':
            self.log.emit(redact(value))
        elif kind == 'error':
            self._had_error = True
            hint = ''
            if any(w in value.lower() for w in ('authentication', 'not logged in', 'login', 'unauthorized', 'api key')):
                hint = ' — sign in: Settings › AI assistant… › Claude / Codex › Sign in…'
            self.error.emit(redact(value)[:600] + hint)
        elif kind == 'done':
            self._finished_turn = True

    def _stderr(self):
        text = bytes(self.process.readAllStandardError()).decode('utf8', 'replace')
        if text.strip():
            self._stderr_tail = (self._stderr_tail + text)[-3000:]
            self.log.emit(redact(text[-1500:]))

    def _process_error(self, _err):
        if self.pending and self.process.state() == QProcess.ProcessState.NotRunning:
            self.error.emit(f"Could not start {AGENTS[self.agent]['label']}: {self.process.errorString()}")
            self.pending = False
            self.settled.emit()

    def _exit(self, code, _status):
        if self._buffer.strip():
            self._buffer.extend(b'\n')
            self._output()
        if not self.pending:
            return
        self.pending = False
        if self._aborting:
            self.log.emit('Stopped.')
        elif code != 0 and not self._had_error:
            tail = self._stderr_tail.strip().splitlines()[-1:] or [f'exit code {code}']
            hint = ''
            low = self._stderr_tail.lower()
            if any(w in low for w in ('login', 'log in', 'auth', 'unauthorized', 'api key')):
                hint = ' — sign in first: Settings › AI assistant… › Sign in'
            self.error.emit(f"{AGENTS[self.agent]['label']} stopped: {redact(tail[0])[:300]}{hint}")
        self.settled.emit()
