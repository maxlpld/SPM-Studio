"""Native first-run choice and settings. Nothing is installed or signed in without consent.

Five starting paths: reuse an existing Pi · let SPM Studio set up its own Pi
(guided, automatic) · connect Claude Code or Codex CLI · direct cloud API ·
configure later.
"""
from __future__ import annotations
import os,shutil
from pathlib import Path
from PySide6.QtCore import QProcess,Qt,QThread,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,QLabel,QPushButton,QWidget,
    QComboBox,QLineEdit,QCheckBox,QStackedWidget,QFileDialog,QPlainTextEdit,QDialogButtonBox,QMessageBox,QListWidget)
from .config import load,save,detect_pi,PROVIDERS,AGENT_BACKENDS
from .providers import DEFAULT_URLS,endpoint
from .security import CredentialStore
from .judge import local_info,profiles,classify
from . import platform_util as pu

class JudgeSurvey(QThread):
    result=Signal(dict)
    error=Signal(str)
    def run(self):
        try:self.result.emit(local_info())
        except Exception as exc:self.error.emit(str(exc))


class JudgeBenchmark(QThread):
    result=Signal(str)
    def __init__(self,model,parent=None):
        super().__init__(parent);self.model=model
    def run(self):
        messages=['What is 2+2?', 'Implement a multi-file GUI, test plugin lifecycle, and fix concurrency bugs']
        try:
            outcomes=[classify(msg,self.model) for msg in messages]
            self.result.emit(' / '.join(f"{o['tier']} in {o['seconds']}s" for o in outcomes))
        except Exception as exc:self.result.emit('Judge benchmark failed: '+str(exc))



class SetupDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('AI assistant')
        self.resize(660,670)
        self.conf=load();self.credentials=CredentialStore()
        self.process=None
        self.survey=None
        self.benchmark=None
        layout=QVBoxLayout(self)
        layout.setSpacing(10)
        title=QLabel('Connect the assistant');title.setObjectName('heading')
        layout.addWidget(title)
        hint=QLabel('Optional — every scientific tool works without AI.');hint.setObjectName('hint')
        layout.addWidget(hint)
        # Four starting paths as one segmented choice (the combo stays as the model).
        self.mode=QComboBox()
        self.mode.addItems(['Connect existing Pi (preserve its configuration)',
                            'Guided setup of a Pi agent for SPM Studio (automatic)',
                            'Claude Code or OpenAI Codex (official apps, your subscription)',
                            'Direct model API • no Pi/Ollama required','Configure later / disabled'])
        self.mode.setVisible(False)
        from PySide6.QtWidgets import QButtonGroup, QFrame
        seg=QFrame();seg.setObjectName('segmented')
        seg_row=QHBoxLayout(seg);seg_row.setContentsMargins(2,2,2,2);seg_row.setSpacing(2)
        self._mode_group=QButtonGroup(self);self._mode_group.setExclusive(True)
        for i,(label,tip) in enumerate((('My Pi','Reuse your installed Pi agent and its settings (nothing is changed)'),
                                        ('Set up Pi','Recommended for new users: SPM Studio installs and configures '
                                         'everything (Pi, sign-in, models, optional local Judge)'),
                                        ('Claude / Codex','Use Claude Code or OpenAI Codex CLI with your own subscription'),
                                        ('Cloud API','Chat directly with a provider API — no Pi, no Ollama'),
                                        ('Later','Keep the assistant off'))):
            b=QPushButton(label);b.setCheckable(True);b.setProperty('segment',True);b.setToolTip(tip)
            self._mode_group.addButton(b,i);seg_row.addWidget(b,1)
        self._mode_group.idClicked.connect(self.mode.setCurrentIndex)
        layout.addWidget(seg)
        layout.addWidget(self.mode)
        self.pages=QStackedWidget()
        layout.addWidget(self.pages,1)
        self._create_pi_page(new=False)
        self._create_managed_page()
        self._create_agent_page()
        self._create_api_page()
        later=QLabel('The assistant stays off. Open Settings › AI assistant… at any time.')
        later.setObjectName('hint');later.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pages.addWidget(later)
        self.mode.currentIndexChanged.connect(self.pages.setCurrentIndex)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        # Judge / routing apply to direct API chat only (Pi's own router decides for Pi).
        self.judge_box=QGroupBox('Routing (optional)')
        jl=QVBoxLayout(self.judge_box)
        judge_row=QHBoxLayout()
        self.judge=QComboBox();self.judge.addItems(['No Judge / manual','Local Ollama Judge'])
        self.judge.setToolTip('A small local model classifies each request as Fast or Smart. It is not the answering model.')
        judge_row.addWidget(self.judge)
        self.judge_model=QComboBox();self.judge_model.setEditable(True)
        self.judge_model.setPlaceholderText('Ollama model tag')
        judge_row.addWidget(self.judge_model,1)
        self.detect_judge=QPushButton('Detect')
        self.detect_judge.setToolTip('Inspect RAM, GPU and the Ollama models already installed')
        self.detect_judge.clicked.connect(self._judge_models)
        judge_row.addWidget(self.detect_judge)
        jl.addLayout(judge_row)
        bench_row=QHBoxLayout()
        self.benchmark_button=QPushButton('Test Fast / Smart')
        self.benchmark_button.clicked.connect(self._benchmark)
        bench_row.addWidget(self.benchmark_button)
        self.pull_button=QPushButton('Download model…')
        self.pull_button.setToolTip('ollama pull <tag> — asks first, never automatic')
        self.pull_button.clicked.connect(self._pull_model)
        bench_row.addWidget(self.pull_button)
        bench_row.addStretch(1)
        bench_row.addWidget(QLabel('Mode'))
        self.routing=QComboBox();self.routing.addItems(['manual','eco','balanced','performance']);bench_row.addWidget(self.routing)
        jl.addLayout(bench_row)
        self.judge_results=QLabel('No model is downloaded automatically.')
        self.judge_results.setObjectName('hint')
        self.judge_results.setWordWrap(True)
        jl.addWidget(self.judge_results)
        layout.addWidget(self.judge_box)
        self.autonomy_row=QWidget();ar=QHBoxLayout(self.autonomy_row);ar.setContentsMargins(0,0,0,0)
        ar.addWidget(QLabel('Development tasks'))
        self.autonomy=QComboBox();self.autonomy.addItems(['ask','workspace'])
        self.autonomy.setToolTip('ask: confirm before each coding task · workspace: run inside the staging folder after one confirmation')
        ar.addWidget(self.autonomy);ar.addStretch(1)
        layout.addWidget(self.autonomy_row)
        self.info=QLabel('Chat runs without tools. Coding tasks ask for permission first.')
        self.info.setObjectName('hint')
        self.info.setWordWrap(True);layout.addWidget(self.info)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty('primary',True)
        buttons.accepted.connect(self._save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self._restore()
        self._mode_changed(self.mode.currentIndex())

    def _mode_changed(self,index):
        button=self._mode_group.button(index)
        if button is not None and not button.isChecked():button.setChecked(True)
        self.judge_box.setVisible(index==3)
        self.autonomy_row.setVisible(index in (0,1,2))
        self.info.setVisible(index!=4)
        if index==1:self._refresh_managed()
        if index==2:self._refresh_agent()

    def _create_pi_page(self,new=False):
        page=QGroupBox('Your installed Pi')
        v=QVBoxLayout(page)
        note=QLabel('Uses your Pi\'s own login, router and extensions — nothing in ~/.pi is changed.')
        note.setObjectName('hint');note.setWordWrap(True);v.addWidget(note)
        f=QHBoxLayout()
        line=QLineEdit();line.setPlaceholderText('Path to pi (pi.cmd on Windows)')
        found=detect_pi();line.setText(found[0] if found else '')
        f.addWidget(line,1)
        browse=QPushButton('Browse…');browse.clicked.connect(lambda _,l=line:self._browse_file(l));f.addWidget(browse)
        v.addLayout(f)
        if not found:
            v.addWidget(self._hint_label('No personal Pi was found on this computer. Choose “Set up Pi” to let '
                                         'SPM Studio install and configure one for you.'))
        self.pi_existing=line
        f=QHBoxLayout()
        f.addWidget(QLabel('Workspace'))
        space=QLineEdit(self.conf.get('workspace',''))
        space.setPlaceholderText('Folder for development tasks (optional)')
        f.addWidget(space,1)
        choose=QPushButton('Select…');choose.clicked.connect(lambda _,l=space:self._browse_dir(l));f.addWidget(choose)
        v.addLayout(f)
        self.work_existing=space
        v.addStretch(1)
        self.pages.addWidget(page)

    @staticmethod
    def _hint_label(text):
        label=QLabel(text);label.setObjectName('hint');label.setWordWrap(True);return label

    # ---- guided, SPM-managed Pi
    def _create_managed_page(self):
        page=QGroupBox('Pi set up by SPM Studio')
        v=QVBoxLayout(page)
        v.addWidget(self._hint_label('For people new to AI agents: SPM Studio installs its own Pi (and Node.js if '
            'needed) for your user account, helps you sign in with ChatGPT/Copilot or an API key, picks the '
            'models, and can add a free local “Judge” model that sends simple requests to a cheaper model to save '
            'tokens. Your own ~/.pi, if any, is never changed.'))
        self.managed_status=QLabel('');self.managed_status.setWordWrap(True)
        self.managed_status.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.managed_status)
        row=QHBoxLayout()
        self.wizard_button=QPushButton('Start guided setup…');self.wizard_button.setProperty('primary',True)
        self.wizard_button.clicked.connect(self._open_wizard)
        row.addWidget(self.wizard_button);row.addStretch(1)
        v.addLayout(row)
        self.pi_new=QLineEdit();self.pi_new.hide()          # kept for compatibility (holds the private Pi path)
        self.work_new=QLineEdit(self.conf.get('workspace',''));self.work_new.hide()
        v.addStretch(1)
        self.pages.addWidget(page)

    def _refresh_managed(self):
        from . import pi_setup
        entry=pi_setup.managed_pi_entry()
        if entry is None:
            self.managed_status.setText('Not installed yet. The guided setup takes about 5 minutes '
                                        '(download ~100–200 MB, more if you choose a local Judge).')
            self.wizard_button.setText('Start guided setup…');return
        self.pi_new.setText(str(entry))
        auth=pi_setup.auth_status();r=pi_setup.read_router_summary();st=pi_setup.read_settings()
        lines=[f'✓ Pi {pi_setup.managed_pi_version()} installed for SPM Studio',
               ('✓ Accounts: '+', '.join(auth)) if auth else '⚠ No account connected yet',
               ('Answering model: '+str(st.get('defaultProvider',''))+'/'+str(st.get('defaultModel',''))) if st.get('defaultModel') else '⚠ No model chosen yet']
        if r:lines.append(f"Router: Fast {', '.join(r['fast'])} · Smart {', '.join(r['smart'])} · Judge {r['judge']}")
        self.managed_status.setText('<br>'.join(lines))
        self.wizard_button.setText('Change setup…')

    def _open_wizard(self):
        from .pi_wizard import PiSetupWizard
        wizard=PiSetupWizard(self)
        accepted=wizard.exec()==QDialog.DialogCode.Accepted
        self._refresh_managed()
        if accepted:
            self._wizard_summary=wizard.summary
            self.info.setText('Pi is configured. Press Save to start using it.')

    # ---- Claude Code / Codex
    def _create_agent_page(self):
        from .cli_events import AGENTS
        page=QGroupBox('Official coding agents')
        v=QVBoxLayout(page)
        v.addWidget(self._hint_label('Use the app you already have a subscription for. Each agent signs in with '
            'its own account (Claude Pro/Max/Team or Console for Claude Code; ChatGPT or API key for Codex); '
            'SPM Studio never sees your password or tokens.'))
        row=QHBoxLayout()
        self.agent_choice=QComboBox()
        for key,meta in AGENTS.items():self.agent_choice.addItem(meta['label'],key)
        self.agent_choice.currentIndexChanged.connect(lambda _=0:self._refresh_agent(redetect=True))
        row.addWidget(self.agent_choice);row.addStretch(1)
        v.addLayout(row)
        f=QHBoxLayout()
        self.agent_path=QLineEdit();self.agent_path.setPlaceholderText('Detected automatically')
        f.addWidget(self.agent_path,1)
        b=QPushButton('Browse…');b.clicked.connect(lambda _=False:self._browse_file(self.agent_path));f.addWidget(b)
        v.addLayout(f)
        self.agent_status=QLabel('');self.agent_status.setWordWrap(True);v.addWidget(self.agent_status)
        buttons=QHBoxLayout()
        self.agent_install=QPushButton('Install…');self.agent_install.clicked.connect(self._install_agent)
        self.agent_login=QPushButton('Sign in…');self.agent_login.clicked.connect(self._login_agent)
        buttons.addWidget(self.agent_install);buttons.addWidget(self.agent_login);buttons.addStretch(1)
        v.addLayout(buttons)
        self.agent_log=QPlainTextEdit();self.agent_log.setReadOnly(True);self.agent_log.setMaximumHeight(80)
        v.addWidget(self.agent_log)
        v.addStretch(1)
        self.pages.addWidget(page)

    def _agent_key(self):return self.agent_choice.currentData()

    def _refresh_agent(self,redetect=False):
        from .cli_events import detect,version,AGENTS
        key=self._agent_key()
        if redetect or not self.agent_path.text().strip():
            self.agent_path.setText(detect(key))
        path=self.agent_path.text().strip()
        if path:
            v=version(path)
            self.agent_status.setText(f"✓ {AGENTS[key]['label']} found{' ('+v+')' if v else ''}. "
                                      'Sign in once (button below) if you have not used it on this computer yet.')
        else:
            self.agent_status.setText(f"{AGENTS[key]['label']} is not installed. Press Install… "
                                      f"(official installer) or see {AGENTS[key]['docs']}")

    def _install_agent(self):
        from .cli_events import AGENTS
        from . import pi_setup
        key=self._agent_key();meta=AGENTS[key]
        if key=='claude-code':
            cmd=meta['install_windows'] if pu.IS_WINDOWS else meta['install_unix']
            if QMessageBox.question(self,'Install Claude Code?','Run Anthropic\'s official installer in a terminal '
                    'window?\n\n'+cmd)!=QMessageBox.StandardButton.Yes:return
            argv=(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-Command',cmd] if pu.IS_WINDOWS
                  else ['bash','-c',cmd])
            script=pu.write_terminal_script(pi_setup.managed_root()/'launchers','install-claude-code',{},argv,
                                            'Installing Claude Code (official installer from claude.ai).')
            manual=pu.open_terminal(script)
            self.agent_log.appendPlainText(('Run manually: '+cmd) if manual else
                                           'Installer opened in a terminal. When it finishes, press Sign in….')
            return
        if QMessageBox.question(self,'Install Codex CLI?','Install @openai/codex from npm for SPM Studio only '
                '(private Node.js is downloaded first if needed)?')!=QMessageBox.StandardButton.Yes:return
        self._agent_job=_Job(self._install_codex_job,self)
        self._agent_job.log.connect(self.agent_log.appendPlainText)
        self._agent_job.finished.connect(self._agent_job_finished)     # bound method: runs in the GUI thread
        self.agent_install.setEnabled(False)
        self._agent_job.start()

    def _agent_job_finished(self):
        self.agent_install.setEnabled(True)
        self._refresh_agent(redetect=True)

    @staticmethod
    def _install_codex_job(log):
        from . import pi_setup
        node=pi_setup.ensure_node(log)
        npm=pu.npm_for_node(node)
        if not npm:raise RuntimeError('npm not found')
        code=pi_setup.run_streaming([*npm,'install','--prefix',str(pi_setup.runtime_dir()),'--ignore-scripts',
                                     '--no-fund','--no-audit','--loglevel=error','@openai/codex@latest'],
                                    log,env=pu.command_env(node=node),timeout=1200)
        log('Codex installed.' if code==0 else f'npm failed (exit {code}).')

    def _login_agent(self):
        from .cli_events import AGENTS
        from . import pi_setup
        key=self._agent_key();meta=AGENTS[key]
        path=self.agent_path.text().strip()
        if not path:
            QMessageBox.information(self,'Not installed','Install it first.');return
        try:program,prefix=pu.resolve_command(path)
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Agent',str(exc));return
        env={}
        if Path(program).is_absolute():
            env['PATH']=str(Path(program).parent)+os.pathsep+os.environ.get('PATH','')
        script=pu.write_terminal_script(pi_setup.managed_root()/'launchers','sign-in-'+key,env,
                                        [program,*prefix,*meta['login']],meta['login_hint'])
        manual=pu.open_terminal(script)
        self.agent_log.appendPlainText(('Run in a terminal: '+manual) if manual else
                                       'Sign-in window opened. Come back here and press Save when done.')

    def _create_api_page(self):
        page=QGroupBox('Cloud API')
        v=QVBoxLayout(page)
        note=QLabel('API keys (not account subscriptions). Stored in the OS keyring, otherwise kept in memory only.')
        note.setObjectName('hint');note.setWordWrap(True);v.addWidget(note)
        form=QFormLayout()
        self.provider=QComboBox()
        for name in ('openai','anthropic','gemini','openrouter','custom','ollama'):
            self.provider.addItem(name)
        self.provider.currentTextChanged.connect(self._provider_changed)
        form.addRow('Provider',self.provider)
        self.model=QLineEdit();self.model.setPlaceholderText('Exact model ID')
        form.addRow('Model ID',self.model)
        self.base=QLineEdit();self.base.setPlaceholderText('Default endpoint')
        form.addRow('Endpoint',self.base)
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('Leave empty if already stored / in environment')
        form.addRow('API key',self.key)
        v.addLayout(form)
        self.connection_list=QListWidget()
        self.connection_list.setMaximumHeight(90)
        cap=QLabel('Connections — first is primary, others are fallbacks');cap.setObjectName('sectionTitle');v.addWidget(cap)
        v.addWidget(self.connection_list)
        row=QHBoxLayout()
        add=QPushButton('Add / update');add.clicked.connect(self._add_connection)
        remove=QPushButton('Remove');remove.clicked.connect(self._remove_connection)
        row.addWidget(add);row.addWidget(remove);v.addLayout(row)
        self.fallback=QCheckBox('Fall back to the next connection on failure')
        v.addWidget(self.fallback)
        tier=QFormLayout()
        self.fast_model=QComboBox()
        self.fast_model.addItem('Primary (same model)', '')
        self.smart_model=QComboBox()
        self.smart_model.addItem('Primary (same model)', '')
        tier.addRow('Fast',self.fast_model)
        tier.addRow('Smart',self.smart_model)
        v.addLayout(tier)
        hint=QLabel('Chat only. Coding tasks need Pi.');hint.setObjectName('hint');v.addWidget(hint)
        self.pages.addWidget(page)

    def _provider_changed(self,value):
        self.base.setPlaceholderText(DEFAULT_URLS.get(value,'https://example.com/v1'))
        self.key.setEnabled(value!='ollama')

    def _browse_file(self,line):
        f,_=QFileDialog.getOpenFileName(self,'Locate the executable',str(Path.home()))
        if f:line.setText(f)

    def _browse_dir(self,line):
        d=QFileDialog.getExistingDirectory(self,'Select an authorized workspace',str(Path.home()))
        if d:line.setText(d)

    def _restore(self):
        c=self.conf
        if c['backend']=='pi':index=1 if c.get('pi_managed') else 0
        elif c['backend'] in AGENT_BACKENDS:index=2
        elif c['backend']!='none':index=3
        elif not c.get('configured'):
            index=0 if detect_pi() else 1        # first run: guided setup unless a personal Pi exists
        else:index=4
        self.mode.setCurrentIndex(index)
        self.pages.setCurrentIndex(index)
        if c['backend']=='pi' and not c.get('pi_managed') and c['pi_executable']:
            self.pi_existing.setText(c['pi_executable'])
        for w in (self.work_new,self.work_existing):w.setText(c['workspace'])
        if c['backend'] in AGENT_BACKENDS:
            self.agent_choice.setCurrentIndex(max(0,self.agent_choice.findData(c['backend'])))
            if c.get('agent_executable'):self.agent_path.setText(c['agent_executable'])
        self.judge.setCurrentIndex(1 if c['judge']=='local' else 0)
        self.judge_model.setEditText(c['judge_model'])
        self.routing.setCurrentText(c['routing']);self.autonomy.setCurrentText(c['autonomy'])
        self.provider.setCurrentText(c['provider']);self.model.setText(c['model']);self.base.setText(c['api_base'])
        self._refresh_connections()
        self.fallback.setChecked(c.get('fallback_enabled',False))
        self.fast_model.setCurrentIndex(max(0,self.fast_model.findData(c.get('fast_id',''))))
        self.smart_model.setCurrentIndex(max(0,self.smart_model.findData(c.get('smart_id',''))))

    def _refresh_connections(self):
        self.connection_list.clear()
        old_fast=getattr(self,'fast_model',None).currentData() if hasattr(self,'fast_model') else None
        old_smart=getattr(self,'smart_model',None).currentData() if hasattr(self,'smart_model') else None
        if hasattr(self,'fast_model'):
            self.fast_model.clear();self.fast_model.addItem('Primary (same model)','')
            self.smart_model.clear();self.smart_model.addItem('Primary (same model)','')
        for c in self.conf.get('connections',[]):
            if isinstance(c,dict):
                self.connection_list.addItem(c.get('provider','')+' • '+c.get('model',''))
                key=c.get('provider','')+'|'+c.get('model','')
                self.fast_model.addItem(key,key);self.smart_model.addItem(key,key)
        self.fast_model.setCurrentIndex(max(0,self.fast_model.findData(old_fast)))
        self.smart_model.setCurrentIndex(max(0,self.smart_model.findData(old_smart)))

    def _add_connection(self):
        provider=self.provider.currentText();model=self.model.text().strip()
        if not model:
            QMessageBox.warning(self,'Model','Enter an exact model identifier.');return
        base=self.base.text().strip()
        try:endpoint(provider,base)
        except ValueError as exc:
            QMessageBox.warning(self,'Endpoint',str(exc));return
        if self.key.text().strip():
            note=self.credentials.put(provider,self.key.text().strip())
            self.key.clear();self.info.setText(note)
        new={'provider':provider,'model':model,'base':base}
        old=[x for x in self.conf.get('connections',[]) if isinstance(x,dict)
             and (x.get('provider'),x.get('model'))!=(provider,model)]
        self.conf['connections']=old+[new];self._refresh_connections()

    def _remove_connection(self):
        idx=self.connection_list.currentRow()
        if idx<0:return
        old=list(self.conf.get('connections',[]));old.pop(idx)
        self.conf['connections']=old;self._refresh_connections()

    def _judge_models(self):
        self.detect_judge.setEnabled(False)
        self.judge_results.setText('Inspecting local RAM, GPU, and Ollama tags…')
        self.survey=JudgeSurvey(self)
        self.survey.result.connect(self._show_judge_info)
        self.survey.error.connect(lambda e:self.judge_results.setText('Hardware detection failed: '+e))
        self.survey.finished.connect(lambda:self.detect_judge.setEnabled(True))
        self.survey.start()

    def _show_judge_info(self,info):
        available=profiles(info)
        self.judge_model.clear()
        for m in info.get('models',[]):self.judge_model.addItem(m['name'])
        def display(m):return m['name']+(' ({:.2f} GB on disk)'.format(m.get('size',0)/1e9) if m.get('size') else '')
        self.judge_results.setText('RAM: '+(f"{info['ram_bytes']/1024**3:.1f} GiB" if info['ram_bytes'] else 'unknown')
            +'; GPU: '+str(info['gpu'])+'; detected local models: '+str(len(info.get('models',[])))
            +'. Size-ordered candidates: '+(', '.join(map(display,available)) if available else 'none')
            +'. No measured classification speed yet. Models not automatically installed.')

    def _benchmark(self):
        model=self.judge_model.currentText().strip()
        if not model:
            QMessageBox.information(self,'No model','Detect installed models or enter an exact Ollama model tag.');return
        self.benchmark_button.setEnabled(False)
        self.judge_results.setText('Testing local Fast and Smart classification…')
        self.benchmark=JudgeBenchmark(model,self)
        self.benchmark.result.connect(self.judge_results.setText)
        self.benchmark.finished.connect(lambda:self.benchmark_button.setEnabled(True))
        self.benchmark.start()

    def _pull_model(self):
        model=self.judge_model.currentText().strip()
        if not model or any(x in model for x in ('/', '..', '\n')) or len(model)>180:
            QMessageBox.warning(self,'Model identifier','Enter a single exact model tag without path separators.');return
        if not shutil.which('ollama'):
            QMessageBox.warning(self,'Ollama missing','Install Ollama from its official distribution first.');return
        if self.process is not None and self.process.state()!=QProcess.ProcessState.NotRunning:
            QMessageBox.information(self,'Busy','Another installation is still running.');return
        if QMessageBox.question(self,'Download local model',
            'Pull '+model+' from Ollama? Verify its published disk/memory requirements first. '
            'This may download gigabytes. The existing Ollama configuration is not overwritten.')!=QMessageBox.StandardButton.Yes:return
        self.process=QProcess(self)
        self.process.setProgram(shutil.which('ollama'))
        self.process.setArguments(['pull',model])
        self.process.readyReadStandardOutput.connect(lambda:self.judge_results.setText(
            bytes(self.process.readAllStandardOutput()).decode(errors='replace')[-400:]))
        self.process.readyReadStandardError.connect(lambda:self.judge_results.setText(
            bytes(self.process.readAllStandardError()).decode(errors='replace')[-400:]))
        self.process.finished.connect(lambda code,status:self.judge_results.setText(
            'Ollama pull finished successfully; refresh installed model list.' if code==0 else 'Ollama pull failed; previous models are unaffected.'))
        self.process.start()

    def reject(self):
        if any(w is not None and w.isRunning() for w in (self.survey,self.benchmark)):
            QMessageBox.information(self,'Background check running',
                'Finish local model detection or the short benchmark before closing the settings dialog.');return
        if self.process is not None and self.process.state()!=QProcess.ProcessState.NotRunning:
            QMessageBox.information(self,'Download in progress',
                'Wait for the current install or model pull to finish before closing settings.');return
        super().reject()

    def _save(self):
        if any(w is not None and w.isRunning() for w in (self.survey,self.benchmark)):
            QMessageBox.information(self,'Background check running',
                'Finish local model detection or the benchmark before saving.');return
        c=dict(self.conf);idx=self.mode.currentIndex()
        if self.process is not None and self.process.state()!=QProcess.ProcessState.NotRunning:
            QMessageBox.information(self,'Installation running','Installation must finish before closing this dialog.');return
        if idx==0:
            path=self.pi_existing.text().strip()
            if not path or not (Path(path).expanduser().is_file() or shutil.which(path)):
                QMessageBox.warning(self,'Pi unavailable','Select a valid Pi installation, or choose “Set up Pi”.');return
            c['backend']='pi';c['pi_managed']=False
            c['pi_executable']=str(Path(path).expanduser()) if Path(path).expanduser().is_file() else path
            c['workspace']=self.work_existing.text().strip()
        elif idx==1:
            from . import pi_setup
            entry=pi_setup.managed_pi_entry()
            if entry is None or not pi_setup.auth_status():
                QMessageBox.warning(self,'Setup not finished','Run the guided setup first (Start guided setup…).');return
            c['backend']='pi';c['pi_managed']=True;c['pi_executable']=str(entry)
            c['workspace']=self.work_new.text().strip()
            r=pi_setup.read_router_summary()
            c['routing']='eco' if r.get('economics')=='eco' else 'performance' if r.get('economics')=='sport' else 'balanced' if r else 'manual'
            if r.get('judge_mode')=='custom':c['judge']='local';c['judge_model']=r['judge'].split('/',1)[-1]
            else:c['judge']='none';c['judge_model']=''
        elif idx==2:
            path=self.agent_path.text().strip()
            try:pu.resolve_command(path)
            except (OSError,ValueError):
                QMessageBox.warning(self,'Agent unavailable','Install the agent first (Install…) or select its executable.');return
            c['backend']=self._agent_key();c['agent_executable']=path
        elif idx==3:
            c['backend']=self.provider.currentText();c['provider']=self.provider.currentText()
            c['model']=self.model.text().strip();c['api_base']=self.base.text().strip()
            if self.key.text().strip():self.credentials.put(c['provider'],self.key.text().strip())
            connections=list(c.get('connections',[]))
            current={'provider':c['provider'],'model':c['model'],'base':c['api_base']}
            if c['model'] and current not in connections:connections.insert(0,current)
            if not connections:
                QMessageBox.warning(self,'Provider','Add at least one model connection first.');return
            c['connections']=connections
            c['provider']=connections[0]['provider'];c['model']=connections[0]['model'];c['api_base']=connections[0].get('base','')
            c['backend']=c['provider']
            c['fallback_enabled']=self.fallback.isChecked()
            c['fast_id']=self.fast_model.currentData() or ''
            c['smart_id']=self.smart_model.currentData() or ''
        else:c['backend']='none'
        if idx==3:                                   # Judge box applies to direct API chat only
            c['judge']='local' if self.judge.currentIndex() else 'none'
            c['judge_model']=self.judge_model.currentText().strip()
            if c['judge']=='local' and not c['judge_model']:
                QMessageBox.warning(self,'Local Judge','Choose an installed model tag or disable the Judge.');return
            c['routing']=self.routing.currentText()
        c['autonomy']=self.autonomy.currentText();c['configured']=True
        try:save(c)
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Configuration not saved',str(exc));return
        self.conf=c;self.accept()


class _Job(QThread):
    log=Signal(str)
    def __init__(self,fn,parent=None):
        super().__init__(parent);self.fn=fn
    def run(self):
        try:self.fn(self.log.emit)
        except Exception as exc:self.log.emit('⚠ '+type(exc).__name__+': '+str(exc))
