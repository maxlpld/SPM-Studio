"""Non-blocking Pi JSONL RPC client for native Qt applications.

Verified against pi.dev RPC reference. Does not inspect or overwrite ~/.pi.
"""
from __future__ import annotations
import json,os,uuid
from pathlib import Path
from PySide6.QtCore import QObject,QProcess,QProcessEnvironment,Signal,QTimer
from .security import redact


from .rpc_events import RpcEvents


class PiRpcBackend(QObject):
    text = Signal(str)
    log = Signal(str)
    error = Signal(str)
    settled = Signal()
    model = Signal(str)
    ready = Signal()
    status = Signal(str)
    stopped = Signal()
    activity = Signal(str)

    def __init__(self, executable:str, workspace:Path, session:Path,
                 coding:bool=False, session_id:str="default", parent=None, system_append=None, env=None):
        super().__init__(parent)
        self.extra_env=dict(env or {})   # e.g. PI_CODING_AGENT_DIR for SPM Studio's private Pi
        self.executable=executable
        self.workspace=Path(workspace).expanduser()
        self.session=Path(session).expanduser()
        self.coding=coding
        self.session_id=session_id
        self.system_append=str(system_append) if system_append else ''
        self._context_pending=False   # compat level 2: context sent with the first prompt instead
        self.process=QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._output)
        self.process.readyReadStandardError.connect(self._diagnostics)
        self.process.errorOccurred.connect(lambda e:self.error.emit('Pi process error: '+self.process.errorString()))
        self.process.finished.connect(self._exit)
        self.process.started.connect(self._started)
        self._buffer=bytearray()
        self.reducer=RpcEvents()
        self.pending=False
        self.current_model=''
        self._stopping=False
        self._seen_settled=False
        self._compat=0              # 1: no --session-id/--no-approve · 2: also no --append-system-prompt
        self._stderr_tail=''
        self._got_output=False

    def start(self):
        if self.process.state()!=QProcess.ProcessState.NotRunning:return
        from . import platform_util as pu
        try:
            # Windows .cmd shims and "#!/usr/bin/env node" scripts are started as node + entry.js
            program,prefix=pu.resolve_command(self.executable)
        except (OSError,ValueError) as exc:
            self.error.emit('Pi executable not usable: '+str(exc));self.stopped.emit();return
        self.workspace.mkdir(parents=True,exist_ok=True)
        self.session.mkdir(parents=True,exist_ok=True)
        environment=QProcessEnvironment.systemEnvironment()
        for key,value in pu.command_env(self.extra_env).items():
            if key=='PATH' or key in self.extra_env or key=='PI_SKIP_VERSION_CHECK':
                environment.insert(key,value)
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(self.workspace))
        self.process.setProgram(program)
        args=list(prefix)+['--mode','rpc','--session-dir',str(self.session)]
        if self._compat<1:
            # --session-id keeps one Pi session per SPM conversation; --no-approve
            # ignores trust-gated project-local configuration (docs.pi.dev/latest/cli).
            args += ['--session-id',self.session_id,'--no-approve']
        if self.system_append and self._compat<2:
            args += ['--append-system-prompt',self.system_append]
        self._context_pending=bool(self.system_append and self._compat>=2)
        if not self.coding:
            args += ['--no-tools']
        self.process.setArguments(args)
        self._stopping=False
        self.process.start()

    @property
    def running(self)->bool:
        return self.process.state()==QProcess.ProcessState.Running

    def _started(self):
        self.log.emit('Pi RPC started (your global Pi settings are not modified).')
        self.ready.emit()
        self.command('get_state')

    def command(self,kind:str,**kwargs):
        if self.process.state()!=QProcess.ProcessState.Running:
            self.error.emit('Pi RPC is not connected.');return None
        id_='spm-'+uuid.uuid4().hex[:12]
        payload=json.dumps({'id':id_,'type':kind,**kwargs},ensure_ascii=False).encode('utf8')+b'\n'
        self.process.write(payload)
        return id_

    def prompt(self,message):
        if self.pending:
            self.error.emit('Wait for the current agent reply or cancel it.');return
        if self.process.state()!=QProcess.ProcessState.Running:
            self.error.emit('Pi RPC has not started.');return
        self.pending=True
        if self._context_pending:
            try:
                context=Path(self.system_append).read_text(encoding='utf8')
                message='[SPM Studio context — instructions for the assistant]\n'+context+'\n\n[User message]\n'+message
            except OSError:pass
            self._context_pending=False
        self.command('prompt',message=message)

    def abort(self):
        if self.process.state()==QProcess.ProcessState.Running:
            self.command('clear_queue');self.command('abort')

    def _output(self):
        self._got_output=True
        self._buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self._buffer)>8_000_000:
            self._buffer.clear();self.error.emit('Oversized Pi protocol record rejected');return
        while b'\n' in self._buffer:
            line,_,tail=self._buffer.partition(b'\n');self._buffer=bytearray(tail)
            if len(line)>2_000_000:self.error.emit('Large Pi RPC event rejected');continue
            try:event=json.loads(line.rstrip(b'\r').decode('utf8'))
            except (UnicodeDecodeError,ValueError):
                self.log.emit('Invalid Pi RPC record ignored');continue
            self._handle(event)

    def _handle(self,event):
        result=self.reducer.interpret(event)
        if result is None:return
        kind,value=result
        if kind=='text':self.text.emit(value)
        elif kind=='log' and value.startswith(('Running tool','Tool finished')):
            self.activity.emit(value);self.log.emit(value)
        elif kind=='log':self.log.emit(redact(value))
        elif kind=='error':
            self.error.emit(redact(value))
            if event.get('command')=='prompt':self.pending=False;self.settled.emit()
        elif kind=='done':
            if value=='agent_settled':self._seen_settled=True
            elif value=='agent_end' and self._seen_settled:return   # wait for agent_settled
            if not self.pending:return
            self.pending=False;self.command('get_state');self.settled.emit()
        elif kind=='model':
            provider,model=value
            self.current_model=(provider+'/' if provider else '')+model
            self.model.emit(self.current_model)
        elif kind=='extension_dialog':
            # Dialogs block Pi until answered. Never silently authorize: reply 'cancelled'
            # (documented extension_ui_response) so the agent continues without the action.
            if event.get('id') is not None and self.running:
                reply=json.dumps({'type':'extension_ui_response','id':event['id'],'cancelled':True}).encode('utf8')+b'\n'
                self.process.write(reply)
            self.log.emit('Pi extension asked for '+str(event.get('method','input'))+
                          (': '+str(event.get('title'))[:120] if event.get('title') else '')+' — declined in SPM Studio.')
        elif kind=='status':
            self.status.emit(redact(value)[:300])

    def _diagnostics(self):
        text_=bytes(self.process.readAllStandardError()).decode('utf8',errors='replace')
        if text_.strip():
            self._stderr_tail=(self._stderr_tail+text_)[-4000:]
            self.log.emit(redact(text_[-2500:]))

    def _exit(self,code,status):
        if self.pending:self.pending=False;self.settled.emit()
        tail=self._stderr_tail.lower()
        if (not self._stopping and self._compat<2 and not self._got_output and code!=0
                and ('unknown' in tail or 'unrecognized' in tail or 'invalid option' in tail)):
            # Older Pi without some options: retry with fewer flags (twice at most).
            self._compat+=1;self._stderr_tail=''
            self.log.emit('Pi rejected an option; retrying in compatibility mode.')
            QTimer.singleShot(200,self.start)
            return
        if not self._stopping:
            self.error.emit(f'Pi stopped (exit code {code}). Use Reconnect.')
            self.stopped.emit()

    def shutdown(self):
        self._stopping=True
        if self.process.state()==QProcess.ProcessState.Running:
            self.process.closeWriteChannel()
            self.process.terminate()
            # Escalation only after allowing graceful shutdown; never block event loop.
            QTimer.singleShot(2500,lambda:self.process.kill() if self.process.state()!=QProcess.ProcessState.NotRunning else None)
