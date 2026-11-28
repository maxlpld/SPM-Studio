"""SPM Studio as an Agent Hub host (contract 1.x). Everything SPM-specific lives here; the engine in
``src/agent_hub`` imports no SPM Studio module."""
from __future__ import annotations

import json
import re
from pathlib import Path

from agent_hub import host as ah_host

SPM_PROJECTS = [
    {'id': 'scripts', 'name': 'Scripts & analysis tools', 'folder': 'scripts',
     'keywords': ['script', 'tool', 'module', 'analysis tool', 'module.json', 'module.py', 'fit', 'lattice',
                  'herringbone', 'molecule', 'fft', 'spectroscopy', 'python', 'plot', 'histogram', 'outil',
                  'analyse', 'ajuster'],
     'instructions': 'Analysis tools of SPM Studio (scripts folder). Read the folder guide before creating or '
                     'changing a tool, validate it, and say where it appears in the Tools list.'},
    {'id': 'personalisation', 'name': 'Personalisation', 'folder': 'customization',
     'keywords': ['theme', 'colour', 'color', 'colormap', 'profile', 'export preset', 'export profile',
                  'shortcut', 'font', 'plot style', 'customization', 'customisation', 'thème', 'couleur',
                  'raccourci', 'profil', 'police', 'personnalis'],
     'instructions': 'SPM Studio customization files (themes, colormaps, profiles, export presets, plot styles, '
                     'shortcuts). Read the README.md of the folder first; keep every file importable.'},
    {'id': 'documents', 'name': 'LaTeX & presentations', 'folder': 'documents',
     'keywords': ['latex', 'overleaf', 'slide', 'presentation', 'beamer', 'tex', 'paper', 'article', 'poster',
                  'figure caption', 'diapo', 'présentation'],
     'instructions': 'LaTeX projects and presentations of SPM Studio. Use the editor requests or edit the '
                     'project files directly; the editors reload changed files.'},
    {'id': 'app', 'name': 'SPM Studio app (patches & releases)', 'folder': 'app',
     'keywords': ['patch', 'bug', 'crash', 'feature', 'release', 'github', 'commit', 'pull request', 'push',
                  'version', 'source code', 'main_window', 'settings dialog', 'interface', 'gui', 'button',
                  'correctif', 'fonctionnalité'],
     'instructions': 'Changes to SPM Studio itself. Back up each edited file (name.bak), keep changes minimal, '
                     'check with py_compile, and say when a restart is needed. Releases go through GitHub.'},
]
_SYMBOLS = re.compile('[%s-%s%s-%s%s-%s%s-%s]%s?\\s?' % (chr(0x1F000), chr(0x1FFFF), chr(0x2600), chr(0x27BF),
                                                         chr(0x2B00), chr(0x2BFF), chr(0x25A0), chr(0x25FF),
                                                         chr(0xFE0F)))


class SPMHost(ah_host.Host):
    name = 'spm-studio'
    label = 'SPM Studio'
    FOLDERS = [('scripts', 'SPM Studio analysis tools'), ('customization', 'SPM Studio customization'),
               ('documents', 'Documents (LaTeX, presentations)'), ('app', 'SPM Studio app source')]

    def __init__(self, main_window=None):
        self.main_window = main_window
        self._workers = []

    # ---- storage
    def models_dir(self):
        try:
            from spm_studio.core import paths
            return paths.models_dir()             # the offline speech model of the classic panel is reused
        except Exception:
            return None

    def legacy_todo_files(self) -> list[Path]:
        try:
            from spm_studio.documents import todo
            return [todo.file()]
        except Exception:
            return []

    # ---- appearance
    def colors(self) -> dict:
        try:
            from spm_studio.shared.appearance import colors
            return colors()
        except Exception:
            return {}

    def window_icon(self):
        try:
            return self.main_window.windowIcon() if self.main_window is not None else None
        except RuntimeError:
            return None

    # ---- agents
    def managed_pi(self):
        try:
            from spm_studio.ai import pi_setup
            entry = pi_setup.managed_pi_entry()
            if entry is None:
                return None
            auth = pi_setup.auth_status()
            group = 'openai' if auth.get('openai') == 'oauth' or auth.get('openai-codex') == 'oauth' else 'pi'
            router = pi_setup.read_router_summary()
            note = ('router: Fast ' + ', '.join(router.get('fast', [])[:1]) + ' · Smart ' +
                    ', '.join(router.get('smart', [])[:1]) + ' · Judge ' + str(router.get('judge', ''))) \
                if router else 'single model'
            return {'executable': str(entry), 'env': pi_setup.pi_env(), 'label': 'Pi (SPM Studio)', 'group': group,
                    'router': router, 'note': note}
        except Exception:
            return None

    def judge_port_hook(self):
        try:
            from spm_studio.ai import pi_setup
            if pi_setup.read_router_summary().get('judge_mode') == 'custom':
                from spm_studio.ai.judge_proxy import shared
                pi_setup.set_judge_port(shared().port)
        except Exception:
            pass

    def ai_config(self) -> dict:
        """SPM Studio's assistant settings (Judge, direct API, personal Pi) + the hub's own connections."""
        conf = {}
        try:
            from spm_studio.ai import config as aiconf
            conf = dict(aiconf.load())
            if not conf.get('pi_executable'):
                conf['pi_executable'] = next(iter(aiconf.detect_pi()), '')
        except Exception:
            pass
        try:
            from agent_hub.settings_store import load_ai
            conf['connections'] = list(conf.get('connections') or []) + load_ai()['connections']
        except Exception:
            pass
        return conf

    def app_folders(self) -> list[Path]:
        try:
            from spm_studio.ai.config import app_folders
            from .develop import staging_root
            return [Path(p) for p in app_folders()] + [staging_root()]
        except Exception:
            return []

    def workspace(self, key: str):
        try:
            from spm_studio.core import paths
            if key == 'scripts':
                return paths.scripts_dir()
            if key == 'customization':
                return paths.customization_dir()
            if key == 'app':
                return paths.bundled_studio_root()
            if key == 'documents':
                from spm_studio.documents import settings as ds
                return ds.documents_home()
        except Exception:
            pass
        return None

    def base_context(self, workspace: Path, tools: bool) -> str:
        try:
            from spm_studio.ai.config import spm_context_file
            text = spm_context_file(workspace, tools).read_text(encoding='utf8')
        except Exception:
            text = ''
        line = self._document_line()
        notes = self._extension_notes()
        return text + (f'\n\nThe user is working in: {line}' if line else '') + \
            (f'\n\nStyle for your replies (from an extension the user enabled): {notes}' if notes else '')

    def extra_instructions(self, kind: str) -> str:
        """Chat-only models have no system prompt: the editors' and literature instructions ride along."""
        parts = []
        try:
            from spm_studio.ai import lit_protocol
            from spm_studio.ai.config import load
            pre = lit_protocol.direct_chat_preamble(load())
            if pre:
                parts.append(pre[0]['content'].split(']\n', 1)[-1])
        except Exception:
            pass
        try:
            from spm_studio.documents import protocol, settings as ds
            dc = ds.load()
            text = protocol.agent_context(bool(dc.get('latex_enabled')), bool(dc.get('slides_enabled')),
                                          bool(dc.get('todo_enabled', True)))
            if text:
                parts.append(text)
        except Exception:
            pass
        line = self._document_line()
        if line:
            parts.append('The user is working in: ' + line)
        notes = self._extension_notes()
        if notes:
            parts.append('Style for your replies (from an extension the user enabled): ' + notes)
        return '\n\n'.join(parts)

    def _extension_notes(self) -> str:
        api = getattr(self.main_window, 'extension_api', None)
        try:
            return api.assistant_instructions() if api is not None else ''
        except Exception:
            return ''

    def _document_line(self) -> str:
        hub = getattr(self.main_window, 'documents', None)
        try:
            return hub.ai_context_line() if hub is not None else ''
        except Exception:
            return ''

    def agent_allowed_tools(self) -> list[str]:
        try:
            from spm_studio.ai.config import load
            from spm_studio.ai.literature import allowed_tools
            return list(allowed_tools(load()))
        except Exception:
            return []

    def extra_bin_dirs(self) -> list[Path]:
        try:
            from spm_studio.ai.pi_setup import runtime_dir
            return [runtime_dir() / 'node_modules' / '.bin']
        except Exception:
            return []

    def default_projects(self) -> list[dict]:
        extra = [p for p in ah_host.GENERAL_PROJECTS if p['id'] not in {q['id'] for q in SPM_PROJECTS}]
        return [dict(p) for p in SPM_PROJECTS] + [dict(p) for p in extra]

    # ---- the editors' and literature requests in a reply (``<spm-doc>``, literature lookups)
    def handle_reply(self, text: str, chat: dict, done) -> bool:
        from spm_studio.documents import protocol
        requests = protocol.parse_requests(text)
        hub = getattr(self.main_window, 'documents', None)
        if requests and hub is not None:
            results = hub.ai_execute(requests)
            summary = 'Editor: ' + '; '.join(protocol.describe(r) + (' (failed)' if t.startswith('ERROR') else '')
                                             for r, t in results)
            done(protocol.result_message(results) if protocol.needs_followup(requests, results) else None, summary)
            return True
        try:
            from spm_studio.ai import lit_protocol
            from spm_studio.ai.config import load
            conf = load()
            if not lit_protocol.enabled(conf):
                return False
            lookups = lit_protocol.parse_requests(text)
        except Exception:
            return False
        if not lookups:
            return False
        from PySide6.QtCore import QThread, Signal

        class Lookup(QThread):
            finished_text = Signal(str)

            def run(self_):
                try:
                    self_.finished_text.emit(lit_protocol.run_requests(lookups, conf))
                except Exception as exc:
                    from spm_studio.ai.security import redact
                    self_.finished_text.emit(lit_protocol.RESULT_HEADER + ' — Lookups: failed]\n\nERROR: ' +
                                             redact(str(exc)))
        worker = Lookup()
        self._workers.append(worker)
        worker.finished_text.connect(lambda result: done(result, 'Literature: ' + '; '.join(
            lit_protocol.describe(r) for r in lookups)))
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        worker.start()
        return True

    def ask_assistant(self, text: str, send: bool = True) -> bool:
        controller = getattr(self.main_window, 'ai_dock', None)
        if controller is None:
            return False
        return controller.ask(text, send=send) is not None

    def todo_writing_actions(self) -> list[tuple]:
        """The first to-do window's "write a report / paper / slides from my notes" (SPM Studio's editors)."""
        return [('A structured report (LaTeX editor)', 'a structured scientific report (LaTeX editor: create a new '
                 'project from the Article template, fill the sections, insert the figures that exist, compile)'),
                ('A paper draft (LaTeX editor)', 'a paper draft (LaTeX editor: new project; abstract, introduction, '
                 'methods, results, discussion, conclusion; mark missing data and references as TODO, never invent '
                 'results)'),
                ('A presentation (presentation editor)', 'a presentation (presentation editor: new presentation, one '
                 'idea per slide, short bullet points, speaker notes with the details)')]

    def display_text(self, text: str) -> str:
        try:
            from spm_studio.ai import lit_protocol
            from spm_studio.documents import protocol
            text = protocol.display_text('assistant', lit_protocol.display_text('assistant', text))
        except Exception:
            pass
        return _SYMBOLS.sub('', text)                 # the hub shows line icons only, never symbols

    # ---- host UI
    def open_setup(self, parent=None) -> bool:
        from spm_studio.ai.setup_ui import SetupDialog
        SetupDialog(parent).exec()
        return True

    def integrations(self) -> list[dict]:
        try:
            from spm_studio.ai.config import load
            conf = load()
        except Exception:
            return []
        zotero = {'off': 'off', 'auto': 'automatic (local Zotero or database)', 'local': 'local Zotero app',
                  'database': 'Zotero database', 'web': 'Zotero web library'}.get(conf.get('zotero_mode', 'off'), '?')
        return [{'id': 'consensus', 'label': 'Consensus (literature search)',
                 'status': 'enabled' if conf.get('consensus_enabled') else 'off — see the Literature page'},
                {'id': 'zotero', 'label': 'Zotero (references)', 'status': zotero + ' — see the Literature page'}]

    def settings_pages(self) -> list[tuple]:
        """SPM Studio's AI pages inside the Agent Hub settings: literature sources and its own Pi / assistant
        set-up (moved here from SPM Studio's main Settings in 0.1.0)."""
        window = self.main_window

        def literature(parent):
            from .literature_page import LiteraturePage
            return LiteraturePage(window, changed=lambda: None, parent=parent)

        def setup(parent):
            from .setup_page import SetupPage
            return SetupPage(self, parent)
        return [('SPM Studio assistant & Pi setup', setup, None), ('Literature (Consensus & Zotero)', literature, None)]

    def project_actions(self, project: dict) -> list[tuple]:
        if project.get('id') != 'scripts':
            return []
        from . import develop
        return [('Develop a new analysis tool…', lambda hub: develop.start(hub, self.main_window)),
                ('Install a staged tool…', lambda hub: develop.install(hub, self.main_window))]

    def assistant_state(self, state: str):
        controller = getattr(self.main_window, 'ai_dock', None)
        try:
            if controller is not None:
                controller.agentState.emit(state)
        except Exception:
            pass

    def scientific_context(self) -> str:
        scan = getattr(self.main_window, 'scan', None)
        if scan is None:
            return ''
        info = {'filename': Path(scan.path).name, 'metadata': scan.metadata, 'channels': list(scan.channels)}
        return 'Active SPM scan (metadata only, no image data):\n' + json.dumps(info, default=str,
                                                                               ensure_ascii=False)[:12000]

    def classic_histories(self) -> dict:
        from spm_studio.ai import config as aiconf
        return {name: aiconf.load_history(name) for name in aiconf.list_histories()}
