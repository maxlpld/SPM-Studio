"""Session and connection settings, never provider access tokens.

Keep the settings separate from legacy Research Studio's local databases.
"""
from __future__ import annotations
import json
import os
import shutil
from pathlib import Path
from .security import atomic_json, private_dir

AGENT_BACKENDS = {'claude-code', 'codex'}            # official CLIs with their own sign-in (v0.8.2)
BACKENDS = {'none', 'pi', 'openai', 'anthropic', 'gemini', 'openrouter', 'custom', 'ollama'} | AGENT_BACKENDS
PROVIDERS = BACKENDS - {'none', 'pi'} - AGENT_BACKENDS
DEFAULT = {'backend': 'none', 'pi_executable': '', 'provider': 'openai', 'model': '',
           'api_base': '', 'workspace': '', 'judge': 'none', 'judge_model': '',
           'judge_url': 'http://127.0.0.1:11434', 'routing': 'manual',
           'session_name': 'Default', 'autonomy': 'ask', 'configured': False,
           'connections': [], 'fallback_enabled': False, 'fast_id': '', 'smart_id': '',
           # v0.8.1: Pi chat works as an agent (file + shell tools) in the SPM scripts folder,
           # after a one-time confirmation (chat_tools_ack). The toggle in the panel switches it off.
           'chat_tools': True, 'chat_tools_ack': False,
           # v0.8.2: Pi installed by SPM Studio (private Node/Pi/agent folder, never ~/.pi),
           # Claude Code / Codex CLI executable, and the port of the in-app Judge proxy.
           'pi_managed': False, 'agent_executable': '', 'judge_proxy_port': 11436,
           # v0.0.5: literature sources for the agent (Settings › Literature). The Zotero API key is
           # never stored here (OS keyring, see ai/literature.py).
           'consensus_enabled': False, 'zotero_mode': 'off', 'zotero_library_id': '',
           'zotero_library_type': 'user',
           # v0.0.7: zotero_mode also takes 'auto' and 'database'; optional Zotero data folder.
           'zotero_data_dir': '',
           # v0.0.12: the assistant may work everywhere in SPM Studio and use the literature sources
           # from the start (set once by the setup / the first start of this version).
           'permissions_v0012': False}
DEFAULT['consensus_enabled']=True
DEFAULT['zotero_mode']='auto'


def base_dir() -> Path:
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'spm-studio-ai'/'ai'


def session_dir() -> Path:
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'spm-studio-ai'/'ai'/'sessions'


def load() -> dict:
    path = base_dir()/'settings.json'
    try:
        found = json.loads(path.read_text(encoding='utf8'))
        if not isinstance(found,dict):return DEFAULT.copy()
    except (ValueError,OSError):
        return DEFAULT.copy()
    result = dict(DEFAULT)
    for key in DEFAULT:
        if key in found and isinstance(found[key],type(DEFAULT[key])):
            result[key] = found[key]
    if result['backend'] not in BACKENDS:result['backend']='none'
    if result['provider'] not in PROVIDERS:result['provider']='openai'
    if result['zotero_mode'] not in ('off','auto','local','database','web'):result['zotero_mode']='off'
    if result['zotero_library_type'] not in ('user','group'):result['zotero_library_type']='user'
    return result


def save(conf:dict) -> None:
    clean={key: conf.get(key, value) for key,value in DEFAULT.items()}
    if clean['backend'] not in BACKENDS:raise ValueError('Invalid backend')
    if clean['provider'] not in PROVIDERS:raise ValueError('Invalid provider')
    if clean['judge'] not in {'none', 'local'}:raise ValueError('Unsupported Judge')
    if clean['routing'] not in {'manual','eco','balanced','performance'}:raise ValueError('Invalid routing')
    if clean['autonomy'] not in {'ask','workspace'}:raise ValueError('Invalid autonomy')
    if clean['zotero_mode'] not in {'off','auto','local','database','web'}:raise ValueError('Invalid Zotero mode')
    if clean['zotero_library_type'] not in {'user','group'}:raise ValueError('Invalid Zotero library type')
    if clean['zotero_library_id'] and not str(clean['zotero_library_id']).isdigit():
        raise ValueError('The Zotero library ID is a number')
    atomic_json(base_dir()/'settings.json', clean)


def app_folders() -> list[Path]:
    """Every SPM Studio folder the assistant may change when its tools are on."""
    from spm_studio.core import paths
    folders = [paths.scripts_dir(), paths.customization_dir(), paths.data_dir(), paths.config_dir(),
               paths.bundled_studio_root()]
    try:
        from spm_studio.documents import settings as _ds
        dc = _ds.load()
        folders += [_ds.latex_root(dc), _ds.slides_root(dc), _ds.documents_home()]
    except Exception:
        pass
    out = []
    for f in folders:
        f = Path(f)
        if f not in out:
            out.append(f)
    return out


def grant_full_access(conf: dict) -> dict:
    """Tools on (file + shell, everywhere in SPM Studio) and literature sources on.

    Used when the assistant is set up (the setup window says so) and once when v0.0.12 starts.
    Consensus still needs its sign-in (Settings › Literature); Zotero 'auto' uses the local
    Zotero when it exists. Nothing else is changed.
    """
    conf = dict(conf)
    conf['chat_tools'] = True
    conf['chat_tools_ack'] = True
    conf['consensus_enabled'] = True
    if conf.get('zotero_mode', 'off') == 'off':
        conf['zotero_mode'] = 'auto'
    conf['permissions_v0012'] = True
    return conf


def detect_pi(include_managed: bool = False) -> list[str]:
    """Existing (personal) Pi installs. SPM Studio's private Pi is listed only on request."""
    home=Path.home()
    possible=[shutil.which('pi'),home/'.local/bin/pi',home/'.npm-global/bin/pi',
              Path('/opt/homebrew/bin/pi'),Path('/usr/local/bin/pi')]
    if os.name=='nt':
        appdata=Path(os.environ.get('APPDATA',home/'AppData/Roaming'))
        possible+=[appdata/'npm'/'pi.cmd',home/'.local/bin/pi.exe',home/'.local/bin/pi.cmd']
    found=[]
    for p in possible:
        if p and Path(p).is_file() and (os.name=='nt' or os.access(p,os.X_OK)):
            found.append(str(p))
    from .pi_setup import managed_pi_entry,is_managed
    found=[p for p in found if not is_managed(p)]
    if include_managed and managed_pi_entry() is not None:
        found.append(str(managed_pi_entry()))
    return list(dict.fromkeys(found))


def public_summary(settings:dict) -> str:
    return ('Backend: '+settings['backend']+'\n'+'Model: '+(settings['model'] or 'Pi selects')+'\n'
            +'Routing: '+settings['routing']+'\n'+'Judge: '+(settings['judge_model'] if settings['judge']=='local' else 'none')
            +'\nWorkspace: '+(settings['workspace'] or 'not selected'))


def history_path(name:str) -> Path:
    import hashlib
    digest=hashlib.sha256(name.encode('utf8')).hexdigest()[:20]
    return session_dir()/(digest+'.json')


def save_history(name:str,messages:list[dict]):
    kept=[]
    for m in messages[-150:]:
        if m.get('role') in ('user','assistant') and isinstance(m.get('content'),str):
            kept.append({'role':m['role'],'content':m['content'][:60000]})
    atomic_json(history_path(name),{'name':name,'messages':kept})


def load_history(name:str) -> list[dict]:
    try:
        data=json.loads(history_path(name).read_text(encoding='utf8'))
        return [m for m in data.get('messages',[]) if isinstance(m,dict)
                and m.get('role') in ('user','assistant') and isinstance(m.get('content'),str)]
    except (OSError,ValueError,AttributeError):return []


def list_histories() -> list[str]:
    path=session_dir()
    if not path.is_dir():return []
    names=[]
    for p in path.glob('*.json'):
        try:
            n=json.loads(p.read_text(encoding='utf8')).get('name')
            if isinstance(n,str) and n not in names:names.append(n)
        except (OSError,ValueError):pass
    return names


def spm_context_file(workspace, tools: bool = True) -> Path:
    """System-prompt addition telling Pi where it runs inside SPM Studio (written on each start)."""
    from spm_studio.core import paths
    scripts=paths.scripts_dir()
    contract=scripts/'README_SCRIPT.md'
    if not contract.is_file():
        contract=paths.bundled_studio_root()/'scripts'/'README_SCRIPT.md'
    import sys as _sys
    python=_sys.executable
    custom=paths.customization_dir()
    # v0.0.5: every folder has a guide; the agent must read it before creating or editing there.
    try:paths.ensure_guides()
    except OSError:pass
    def _guide(folder):
        found=paths.guide_for(folder)
        return str(found) if found else '(no guide yet)'
    guides='\n'.join(f'- {label}: `{folder}` — guide: `{_guide(folder)}`' for label,folder in (
        ('Analysis tools (scripts)',scripts),
        ('Profiles (channels, processing, colormaps, titles)',custom/'profiles'),
        ('Export profiles (figure page, layout, panels)',custom/'export_presets'),
        ('Themes (interface colours, font)',custom/'themes'),
        ('Colormaps (RGB tables)',custom/'colormaps'),
        ('Plot styles (analysis plots)',custom/'plot_styles'),
        ('Keyboard shortcuts',custom/'shortcuts'),
        ('LaTeX templates (LaTeX editor)',custom/'latex_templates'),
        ('Presentation templates (presentation editor)',custom/'presentation_templates')))
    try:
        from .literature import agent_context as _literature_context
        literature=_literature_context(load(),python)
    except Exception:
        literature=''
    # v0.0.8: LaTeX and presentation editors (documents/protocol.py).
    try:
        from spm_studio.documents import protocol as _doc_protocol, settings as _doc_settings
        _dc=_doc_settings.load()
        documents=_doc_protocol.agent_context(bool(_dc.get('latex_enabled')),bool(_dc.get('slides_enabled')),
                                              bool(_dc.get('todo_enabled')))
        if documents:
            documents+=(f"\n- LaTeX projects are folders under `{_doc_settings.latex_root(_dc)}` (each has a root .tex); "
                        f"presentations are folders under `{_doc_settings.slides_root(_dc)}` (`<name>.spmdeck` JSON + `media/`). "
                        f"With file tools you may also edit those files directly: the editors reload files changed on disk.\n"
                        f"- Template folders: `{custom/'latex_templates'}` and `{custom/'presentation_templates'}` "
                        f"(each has a README.md guide; read it before creating a template).")
    except Exception:
        documents=''
    text=f"""# You are the AI assistant embedded in SPM Studio

SPM Studio is the user's desktop application for scanning-probe-microscopy (STM/AFM/KPFM) analysis.
You run inside its Assistant panel (Pi, Claude Code or Codex), with file and shell tools when enabled.

## Where you work
- Current working directory: {workspace}
- SPM Studio analysis tools ("Tools" list of the app): {scripts}
  Every sub-folder containing `module.json` + `module.py` is one tool. SPM Studio watches this
  folder and shows a new or changed tool in its Tools list within a few seconds — NO restart needed.
- Exact module contract (read it before writing a tool): {contract}
- User customization (themes, colormaps, profiles, figure presets): {paths.customization_dir()}
  General rules for all of them: {paths.customization_dir()/'README_CUSTOMIZATION.md'}

## Read the guide of a folder BEFORE you create or change anything in it
Each folder below contains a `README.md` that states exactly how its files must be built to work in
SPM Studio (required keys, allowed values, a complete example, how to check the result). When the user
asks for a new script, a new profile, an export profile, a theme, a colormap, a plot style or shortcuts:
1. read that folder's guide first, every time (it may have changed with an update);
2. build the file exactly as the guide says, in that folder;
3. run the checks the guide lists and fix what they report;
4. tell the user where the file is and how to select it in the app.
{guides}
New or changed files in these folders are picked up without restarting SPM Studio (tools within a few
seconds; profiles and export profiles when the user opens the list again or uses Settings › Library › Refresh).
- SPM Studio's own source code: {paths.bundled_studio_root()/'src'/'spm_studio'}
  You may patch it whenever the user asks for a change of the app itself (back up each file you edit
  as `name.bak` first, keep the change minimal, check it with `py_compile`); a restart of SPM Studio is
  then required — say so.

## Your permissions
{('You HAVE file and shell tools in this session. You are allowed to read, create and change files in '
  'every SPM Studio folder listed here (tools, customization, documents, to-do list, the app source) and '
  'to run commands with the Python above. Do not tell the user you lack access: do the work. Ask first '
  'only before deleting files or changing things outside SPM Studio.') if tools else
 ('This session runs WITHOUT file or shell tools (chat only). If the user asks you to create or change a '
  'file, tell them to switch tools on with the tools button in the Assistant header (one click), or give '
  'the file content to copy. Literature lookups and the editors\' <spm-doc> requests still work.')}

## Minimal working tool (adapt it)
`{scripts}/hello_spm/module.json`:
```json
{{"api_version": "1.0", "id": "hello_spm", "name": "Hello SPM", "version": "1.0.0",
 "description": "Example", "category": "Examples", "mode": "analysis", "status": "experimental",
 "entrypoint": "module:run", "interaction": "none", "snapshot_channels": "selected",
 "requires": ["numpy"], "parameters": {{}}}}
```
`{scripts}/hello_spm/module.py`:
```python
def run(ctx):
    ctx.log("Hello SPM user")          # appears in the app's Logs panel
    ctx.progress(100, "Done")
```
`ctx` also gives `ctx.data` (numpy array of the selected channel), `ctx.geometry`, `ctx.unit`,
`ctx.parameters`, `ctx.output_dir`, `ctx.result_file(path)`, `ctx.result_table(cols, rows)`.
The user runs a tool by selecting it in Tools (an open scan is required) and clicking Run analysis.

## Rules
- Create a NEW folder per tool; never overwrite another tool without being asked. Back up a file
  (`name.bak`) before editing an existing one.
- Every tool folder must contain a `README.md` (what the tool does, the method and its limits, each
  parameter, the files it writes). The app shows it with the “Read me” button of the Analysis panel.
- Validate JSON and Python syntax yourself with SPM Studio's own Python, which also runs the tools:
  `"{python}" -m json.tool module.json` and `"{python}" -m py_compile module.py`.
- Offline analysis of saved data only: never send commands to microscopes, Nanonis, heaters,
  vacuum or any laboratory hardware.
- Do not touch ~/.pi, ~/.claude, ~/.codex, Ollama, credentials or files outside the SPM Studio folders unless asked.
- When finished, say clearly what you created and that it is now in the Tools list.
{literature}
{documents}"""
    target=private_dir(base_dir())/'spm_context.md'
    target.write_text(text,encoding='utf8')
    return target
