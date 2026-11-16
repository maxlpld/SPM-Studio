"""Guided, per-user installation and configuration of a *private* Pi agent.

Everything SPM Studio installs for Pi lives in its own folders:

    <data>/ai/node/current      private Node.js (only if no Node >= 22.19 exists)
    <data>/ai/runtime           npm prefix containing @earendil-works/pi-coding-agent
    <data>/ai/pi-agent          Pi's agent directory (PI_CODING_AGENT_DIR): settings,
                                auth.json, models.json, pi-shift-router.json, packages

``~/.pi`` (an existing personal Pi setup) is never read or written by this
module. Nothing needs administrator rights except, optionally, installing
Ollama on Linux (its official script asks for sudo in a visible terminal).

This module has no Qt dependency; the wizard (pi_wizard.py) runs these
functions in worker threads and shows their log lines.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from . import platform_util as pu
from .security import atomic_json, private_dir, redact

PI_PACKAGE = '@earendil-works/pi-coding-agent'
ROUTER_PACKAGE = 'npm:pi-shift-router'
SUBAGENTS_PACKAGE = 'npm:pi-subagents'
NODE_DIST = 'https://nodejs.org/dist'
LOCAL_PROVIDER = 'spm-local'           # models.json provider id for the local Judge (never "ollama")
DEFAULT_PROXY_PORT = 11436

# Subscription sign-ins that Pi itself supports via /login (browser OAuth).
# Claude Pro/Max is deliberately not offered here: Anthropic intends consumer
# subscription sign-in for its own apps, so SPM Studio routes Claude subscribers
# to the official Claude Code connection (or an Anthropic API key) instead.
SUBSCRIPTIONS = [
    ('openai', 'ChatGPT Plus / Pro (Sign in with ChatGPT)', '/login openai'),
    ('github-copilot', 'GitHub Copilot', '/login github-copilot'),
]
API_KEY_PROVIDERS = [  # (auth.json key, label, env var, key page)
    ('openai', 'OpenAI API', 'OPENAI_API_KEY', 'https://platform.openai.com/api-keys'),
    ('anthropic', 'Anthropic (Claude) API', 'ANTHROPIC_API_KEY', 'https://console.anthropic.com/settings/keys'),
    ('google', 'Google Gemini API', 'GEMINI_API_KEY', 'https://aistudio.google.com/apikey'),
    ('openrouter', 'OpenRouter', 'OPENROUTER_API_KEY', 'https://openrouter.ai/keys'),
    ('deepseek', 'DeepSeek', 'DEEPSEEK_API_KEY', 'https://platform.deepseek.com/api_keys'),
    ('mistral', 'Mistral', 'MISTRAL_API_KEY', 'https://console.mistral.ai/api-keys'),
    ('xai', 'xAI (Grok)', 'XAI_API_KEY', 'https://console.x.ai'),
    ('groq', 'Groq', 'GROQ_API_KEY', 'https://console.groq.com/keys'),
]


class SetupCancelled(RuntimeError):
    pass


# ------------------------------------------------------------------------ folders
def managed_root() -> Path:
    return pu.data_root() / 'ai'


def runtime_dir() -> Path:
    return managed_root() / 'runtime'


def agent_dir() -> Path:
    return managed_root() / 'pi-agent'


def package_dir(name: str = PI_PACKAGE) -> Path:
    return runtime_dir() / 'node_modules' / Path(*name.split('/'))


def managed_pi_entry() -> Path | None:
    """The JavaScript CLI entry of the private Pi (started with node on every OS)."""
    pkg = package_dir()
    try:
        meta = json.loads((pkg / 'package.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        return None
    binary = meta.get('bin')
    rel = (binary.get('pi') or next(iter(binary.values()), None)) if isinstance(binary, dict) else binary
    if not isinstance(rel, str):
        return None
    entry = (pkg / rel).resolve()
    return entry if entry.is_file() else None


def managed_pi_version() -> str:
    try:
        return json.loads((package_dir() / 'package.json').read_text(encoding='utf8')).get('version', '')
    except (OSError, ValueError):
        return ''


def is_managed(executable: str) -> bool:
    try:
        return Path(executable).expanduser().resolve().is_relative_to(runtime_dir().resolve())
    except (OSError, ValueError):
        return False


def pi_env(directory: Path | None = None) -> dict:
    return {'PI_CODING_AGENT_DIR': str(directory or agent_dir())}


def pi_command(extra_args: list[str]) -> list[str]:
    entry = managed_pi_entry()
    if entry is None:
        raise FileNotFoundError('The private Pi is not installed yet')
    program, prefix = pu.resolve_command(str(entry))
    return [program, *prefix, *extra_args]


# ---------------------------------------------------------------------- networking
def _ssl_context():
    """Use certifi's CA bundle when present: python.org builds on macOS ship
    without system certificates until 'Install Certificates.command' is run."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch(url: str, timeout: int = 30) -> bytes:
    req = Request(url, headers={'User-Agent': 'SPM-Studio-setup'})
    with urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        return r.read()


def download(url: str, dest: Path, progress=None, cancel: threading.Event | None = None, timeout=60) -> Path:
    req = Request(url, headers={'User-Agent': 'SPM-Studio-setup'})
    with urlopen(req, timeout=timeout, context=_ssl_context()) as r, open(dest, 'wb') as out:
        total = int(r.headers.get('Content-Length') or 0)
        done = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise SetupCancelled('Download cancelled')
            chunk = r.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(min(100, done * 100 // total))
    return dest


def run_streaming(argv: list[str], log, env: dict | None = None, cwd: str | None = None,
                  timeout: int = 900, cancel: threading.Event | None = None) -> int:
    """Run a command, forwarding each output line to ``log`` (secrets redacted)."""
    log('$ ' + ' '.join(Path(a).name if i == 0 else a for i, a in enumerate(argv[:6]))
        + (' …' if len(argv) > 6 else ''))
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env=env, cwd=cwd, text=True, encoding='utf8', errors='replace',
                            **pu.hidden_window())
    start = time.monotonic()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(redact(line)[:400])
            if cancel is not None and cancel.is_set():
                proc.terminate()
                raise SetupCancelled('Cancelled')
            if time.monotonic() - start > timeout:
                proc.terminate()
                raise TimeoutError(f'{Path(argv[0]).name} did not finish within {timeout} s')
        return proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()


# -------------------------------------------------------------------- private node
def node_target() -> tuple[str, str]:
    """(nodejs.org platform name, archive extension) for this machine."""
    import platform
    machine = platform.machine().lower()
    arch = 'arm64' if machine in ('arm64', 'aarch64') else 'x64' if machine in ('x86_64', 'amd64', 'x64') else machine
    if pu.IS_WINDOWS:
        return f'win-{arch}', 'zip'
    if pu.IS_MAC:
        return f'darwin-{arch}', 'tar.gz'
    return f'linux-{arch}', 'tar.gz'


def pick_node_release(index: list[dict], target: str) -> str:
    """Newest LTS release that satisfies Pi's minimum and ships for this platform."""
    files_key = {'win-x64': 'win-x64-zip', 'win-arm64': 'win-arm64-zip',
                 'darwin-x64': 'osx-x64-tar', 'darwin-arm64': 'osx-arm64-tar'}.get(target, target)
    for release in index:                      # index.json is newest-first
        version = pu.parse_version(release.get('version', ''))
        if not release.get('lts') or not version or version < pu.NODE_MIN:
            continue
        if files_key in (release.get('files') or []):
            return release['version']
    raise RuntimeError(f'No Node.js LTS release >= {pu.version_text(pu.NODE_MIN)} published for {target}')


def _safe_extract(archive: Path, dest: Path):
    dest = dest.resolve()
    if archive.suffix == '.zip':
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if not (dest / member).resolve().is_relative_to(dest):
                    raise RuntimeError('Unsafe path in Node archive: ' + member)
            zf.extractall(dest)
    else:
        with tarfile.open(archive) as tf:
            try:
                tf.extractall(dest, filter='data')
            except TypeError:                                   # Python < 3.11.4
                for member in tf.getmembers():
                    if not (dest / member.name).resolve().is_relative_to(dest) or member.issym() and \
                            not (dest / member.name).parent.joinpath(member.linkname).resolve().is_relative_to(dest):
                        raise RuntimeError('Unsafe path in Node archive: ' + member.name)
                tf.extractall(dest)


def install_private_node(log, progress=None, cancel=None) -> str:
    """Download the official Node.js LTS build, verify its SHA-256, unpack per-user."""
    target, ext = node_target()
    log('Looking up the current Node.js LTS release on nodejs.org …')
    version = pick_node_release(json.loads(fetch(NODE_DIST + '/index.json')), target)
    name = f'node-{version}-{target}'
    filename = f'{name}.{ext}'
    sums = fetch(f'{NODE_DIST}/{version}/SHASUMS256.txt').decode('utf8', 'replace')
    expected = next((line.split()[0] for line in sums.splitlines()
                     if line.strip().endswith('  ' + filename) or line.strip().endswith(' ' + filename)), None)
    if not expected:
        raise RuntimeError('Checksum for ' + filename + ' not published; refusing to install')
    root = private_dir(pu.private_node_dir())
    with tempfile.TemporaryDirectory(prefix='node-', dir=root) as tmp:
        archive = Path(tmp) / filename
        log(f'Downloading {filename} (~30–50 MB) …')
        download(f'{NODE_DIST}/{version}/{filename}', archive, progress, cancel, timeout=120)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != expected:
            raise RuntimeError('Node.js download failed SHA-256 verification; nothing installed')
        log('SHA-256 verified. Unpacking …')
        unpack = Path(tmp) / 'unpack'
        unpack.mkdir()
        _safe_extract(archive, unpack)
        extracted = unpack / name
        if not extracted.is_dir():
            raise RuntimeError('Unexpected Node.js archive layout')
        current = root / 'current'
        old = root / ('previous-' + str(int(time.time())))
        if current.exists():
            current.rename(old)
        shutil.move(str(extracted), str(current))
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
    exe = pu.private_node_executable()
    if exe is None:
        raise RuntimeError('Node.js was unpacked but its executable is missing')
    log(f'Private Node.js {version} ready: {exe}')
    return str(exe)


def ensure_node(log, progress=None, cancel=None, allow_download=True) -> str:
    info = pu.node_info()
    if info['ok']:
        log(f"Using {info['source']} Node.js {pu.version_text(info['version'])}: {info['path']}")
        return info['path']
    if info['found']:
        log(f"Node.js {pu.version_text(info['version'])} is too old for Pi (needs "
            f"{pu.version_text(pu.NODE_MIN)}+). A private copy will be used; the system one is untouched.")
    if not allow_download:
        raise RuntimeError('Node.js 22.19+ is required')
    return install_private_node(log, progress, cancel)


# ---------------------------------------------------------------------- pi install
def install_pi(node: str, log, cancel=None) -> Path:
    npm = pu.npm_for_node(node)
    if not npm:
        raise RuntimeError('npm was not found next to Node.js')
    runtime = private_dir(runtime_dir())
    env = pu.command_env(node=node)
    code = run_streaming([*npm, 'install', '--prefix', str(runtime), '--ignore-scripts', '--no-fund',
                          '--no-audit', '--loglevel=error', PI_PACKAGE + '@latest'],
                         log, env=env, cwd=str(runtime), timeout=1200, cancel=cancel)
    entry = managed_pi_entry()
    if code != 0 or entry is None:
        raise RuntimeError(f'npm could not install Pi (exit {code}); your system is unchanged')
    log(f'Pi {managed_pi_version()} installed privately in {runtime}')
    return entry


def pi_version(env=None) -> str:
    try:
        r = subprocess.run(pi_command(['--version']), capture_output=True, text=True, timeout=30,
                           env=env or pu.command_env(pi_env()), **pu.hidden_window())
        return (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else ''
    except (OSError, subprocess.SubprocessError, FileNotFoundError):
        return ''


def install_extension(package: str, log, cancel=None) -> bool:
    """``pi install npm:<pkg>`` into the PRIVATE agent dir (records it in its settings.json)."""
    private_dir(agent_dir())
    env = pu.command_env(pi_env())
    code = run_streaming(pi_command(['install', package]), log, env=env, cwd=str(agent_dir()),
                         timeout=900, cancel=cancel)
    if code != 0:
        log(f'Could not install {package} (exit {code}); continuing without it.')
    return code == 0


def installed_packages() -> list[str]:
    settings = read_settings()
    out = []
    for entry in settings.get('packages', []) or []:
        source = entry.get('source') if isinstance(entry, dict) else entry
        if isinstance(source, str):
            out.append(source)
    return out


# --------------------------------------------------------------------- settings io
def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def read_settings(directory: Path | None = None) -> dict:
    return _read_json((directory or agent_dir()) / 'settings.json')


def update_settings(changes: dict, directory: Path | None = None) -> dict:
    path = (directory or agent_dir()) / 'settings.json'
    data = _read_json(path)
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    atomic_json(path, data)
    return data


def configure_platform_defaults():
    """Windows: point Pi at Git Bash explicitly when it is in a non-standard place."""
    if pu.IS_WINDOWS:
        bash = pu.git_bash()
        if bash:
            update_settings({'shellPath': bash})


# ---------------------------------------------------------------------------- auth
def auth_status(directory: Path | None = None) -> dict[str, str]:
    """{provider: 'api_key' | 'oauth'} — never returns secret values."""
    data = _read_json((directory or agent_dir()) / 'auth.json')
    out = {}
    for provider, entry in data.items():
        if isinstance(entry, dict):
            out[provider] = 'api_key' if entry.get('type') == 'api_key' else 'oauth'
    return out


def set_api_key(provider: str, key: str, directory: Path | None = None):
    key = key.strip()
    if not re.fullmatch(r'[a-z0-9][a-z0-9.\-]{1,60}', provider or ''):
        raise ValueError('Invalid provider id')
    if not key or len(key) > 4000 or any(c in key for c in '\r\n\t '):
        raise ValueError('The API key looks invalid (empty or contains spaces/new lines)')
    path = (directory or agent_dir()) / 'auth.json'
    private_dir(path.parent)
    data = _read_json(path)
    data[provider] = {'type': 'api_key', 'key': key}
    atomic_json(path, data)                     # 0600, atomic, never logged


def remove_auth(provider: str, directory: Path | None = None):
    path = (directory or agent_dir()) / 'auth.json'
    data = _read_json(path)
    if data.pop(provider, None) is not None:
        atomic_json(path, data)


def login_script(provider: str) -> Path:
    label = next((lab for p, lab, _ in SUBSCRIPTIONS if p == provider), provider)
    command = next((c for p, _, c in SUBSCRIPTIONS if p == provider), '/login')
    banner = (f'SPM Studio - sign in to {label} for the assistant\n'
              '\n'
              f'1. In the Pi screen below, type:   {command}   and press Enter.\n'
              '2. Your web browser opens: sign in and allow access.\n'
              '3. When Pi says you are logged in, type   /quit   and press Enter.\n'
              '\n'
              'SPM Studio detects the sign-in automatically. Nothing outside SPM Studio\'s\n'
              'own Pi folder is changed.\n')
    entry = managed_pi_entry()
    if entry is None:
        raise FileNotFoundError('Install Pi first')
    program, prefix = pu.resolve_command(str(entry))
    env = {**pi_env(), 'PI_SKIP_VERSION_CHECK': '1'}
    if Path(program).is_absolute():
        env['PATH'] = str(Path(program).parent) + os.pathsep + os.environ.get('PATH', '')
    return pu.write_terminal_script(managed_root() / 'launchers', 'pi-sign-in-' + provider, env,
                                    [program, *prefix], banner)


# -------------------------------------------------------------------------- models
def recommend_answering_models(models: list[dict], auth: dict[str, str]) -> dict:
    """Offer conservative, provider-aware defaults, never guess an unauthenticated model.

    Pi's catalog contains models that a signed-in account might not be entitled
    to use. In particular the modern 'openai' provider serves both API keys and
    ChatGPT OAuth; legacy GPT-4 catalog entries do NOT work with ChatGPT OAuth.
    These are suggestions only: the wizard must validate with a real Pi call.
    """
    usable = []
    seen = set()
    for entry in models:
        provider, model = entry.get('provider', ''), entry.get('id', '')
        if provider not in auth or not model or (provider, model) in seen:
            continue
        if provider == 'openai' and auth[provider] == 'oauth':
            # The ChatGPT login supports modern GPT-5/6-family models, not
            # older GPT-4 API models. Do not invent unlisted IDs.
            if not re.match(r'^gpt-[56](?:[.\-]|$)', model, flags=re.I):
                continue
        seen.add((provider, model))
        usable.append((provider, model))

    def priority(provider):
        # Prefer an already-connected subscription over a metered API key.
        subscription = auth.get(provider) == 'oauth'
        return (0 if subscription else 1,
                0 if provider in ('openai', 'openai-codex') else 1,
                provider)

    providers = sorted({p for p, _ in usable}, key=priority)
    if not providers:
        return {'fast': [], 'smart': [], 'router': False}

    provider = providers[0]
    choices = [name for p, name in usable if p == provider]

    def latest(name):
        version = re.search(r'gpt-(\d+)(?:\.(\d+))?', name, flags=re.I)
        version_score = (int(version[1]), int(version[2] or 0)) if version else (0, 0)
        return (version_score,
                1 if 'codex' in name.lower() else 0,
                0 if any(x in name.lower() for x in ('mini', 'nano', 'small')) else 1,
                name)

    ranked = sorted(choices, key=latest, reverse=True)
    smart = (provider, ranked[0])
    # Small/mini models are appropriate for routine tasks, if actually listed.
    cheap = sorted((m for m in choices if any(
        x in m.lower() for x in ('mini', 'nano', 'small', 'flash', 'haiku'))),
        key=latest, reverse=True)
    fast = (provider, cheap[0]) if cheap else smart
    fast_fallbacks = [(provider, m) for m in cheap[1:] if m != fast[1]][:1]
    smart_fallbacks = [(provider, m) for m in ranked if m not in {smart[1], fast[1]}][:1]
    return {'fast': [fast, *fast_fallbacks],
            'smart': [smart, *smart_fallbacks],
            'router': fast != smart}


def parse_list_models(text: str) -> list[dict]:
    """Parse ``pi --list-models`` (a table: provider, model, context, …)."""
    models, seen = [], set()
    for line in (text or '').splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0].lower() in ('provider', 'no', 'warning:', 'error:') \
                or set(parts[0]) <= set('-─═|+'):
            continue
        provider, model = parts[0].strip('│|'), parts[1].strip('│|')
        if not re.fullmatch(r'[A-Za-z0-9][\w.\-]*', provider) or not model or (provider, model) in seen:
            continue
        seen.add((provider, model))
        models.append({'provider': provider, 'id': model})
    return models


def list_models(search: str = '', timeout: int = 60) -> list[dict]:
    args = ['--list-models'] + ([search] if search else [])
    r = subprocess.run(pi_command(args), capture_output=True, text=True, encoding='utf8', errors='replace',
                       timeout=timeout, env=pu.command_env(pi_env()), **pu.hidden_window())
    return parse_list_models(r.stdout)


def write_local_judge_model(judge_model: str, port: int, directory: Path | None = None):
    """Register the Judge under SPM's own provider id; other providers are untouched."""
    path = (directory or agent_dir()) / 'models.json'
    data = _read_json(path)
    providers = data.setdefault('providers', {})
    providers[LOCAL_PROVIDER] = {
        'baseUrl': f'http://127.0.0.1:{int(port)}/v1',
        'api': 'openai-completions',
        'apiKey': 'local',
        'compat': {'supportsDeveloperRole': False, 'supportsReasoningEffort': False},
        'models': [{'id': judge_model, 'name': judge_model + ' (local Judge)', 'reasoning': False,
                    'input': ['text']}],
    }
    atomic_json(path, data)


def set_judge_port(port: int, directory: Path | None = None) -> bool:
    """Keep models.json in sync with the port the in-app no-thinking proxy got."""
    path = (directory or agent_dir()) / 'models.json'
    data = _read_json(path)
    entry = (data.get('providers') or {}).get(LOCAL_PROVIDER)
    if not isinstance(entry, dict):
        return False
    url = f'http://127.0.0.1:{int(port)}/v1'
    if entry.get('baseUrl') != url:
        entry['baseUrl'] = url
        atomic_json(path, data)
    return True


def router_config(fast: list[tuple[str, str]], smart: list[tuple[str, str]], judge: str,
                  judge_model: str = '', economics: str = 'eco', orchestration: bool = False) -> dict:
    """pi-shift-router.json following its documented schema (docs/CONFIG.md)."""
    if not fast or not smart:
        raise ValueError('Choose at least one Fast and one Smart model')
    if judge not in ('local', 'cloud'):
        raise ValueError('Router needs a local or cloud Judge')
    if economics not in ('eco', 'default', 'sport'):
        raise ValueError('Economics must be eco, default or sport')

    def chain(items):
        return [{'provider': p, 'model': m, 'priority': i + 1} for i, (p, m) in enumerate(items)]
    judge_block = {'mode': 'fast-chain', 'models': []}
    if judge == 'local':
        if not judge_model:
            raise ValueError('Select the local Judge model')
        judge_block = {'mode': 'custom', 'models': [{'provider': LOCAL_PROVIDER, 'model': judge_model, 'priority': 1}]}
    return {
        'enabled': True,
        'tiers': {'fast': {'models': chain(fast)}, 'smart': {'models': chain(smart)}},
        'routing': {'mode': 'auto', 'judgeTimeout': 12000 if judge == 'local' else 5000,
                    'judge': judge_block, 'window': {'size': 5, 'minConfidence': 0.5},
                    'economics': {'mode': economics, 'downgradeMemory': 2}},
        'ux': {'quietMode': False, 'statusBar': True, 'inlineToast': True, 'routerLogVerbose': False},
        'orchestration': {'mode': 'auto' if orchestration else 'off', 'maxRounds': 3,
                          'escalationThreshold': 2, 'requireSmartModel': True},
    }


def apply_configuration(fast, smart, judge: str, judge_model: str, economics: str,
                        use_router: bool, orchestration: bool, port: int = DEFAULT_PROXY_PORT) -> dict:
    """Write models.json / pi-shift-router.json / settings.json in the PRIVATE agent dir."""
    directory = private_dir(agent_dir())
    default = (fast or smart)[0]
    update_settings({'defaultProvider': default[0], 'defaultModel': default[1]}, directory)
    summary = {'default': '/'.join(default), 'router': False, 'judge': 'none'}
    if use_router:
        if judge == 'local':
            write_local_judge_model(judge_model, port, directory)
        atomic_json(directory / 'pi-shift-router.json',
                    router_config(fast, smart, judge, judge_model, economics, orchestration))
        summary.update(router=True, judge=(judge_model if judge == 'local' else 'cloud (Fast tier)'))
    else:
        router = directory / 'pi-shift-router.json'
        if router.is_file():
            # Keep a copy rather than deleting user-edited configuration.
            router.replace(router.with_suffix('.json.disabled'))
    return summary


def read_router_summary(directory: Path | None = None) -> dict:
    cfg = _read_json((directory or agent_dir()) / 'pi-shift-router.json')
    if not cfg:
        return {}
    tiers = cfg.get('tiers') or {}

    def names(t):
        return [f"{m.get('provider')}/{m.get('model')}" for m in (tiers.get(t) or {}).get('models', [])]
    judge = ((cfg.get('routing') or {}).get('judge') or {})
    jm = judge.get('models') or []
    return {'enabled': bool(cfg.get('enabled', True)), 'fast': names('fast'), 'smart': names('smart'),
            'judge_mode': judge.get('mode', 'fast-chain'),
            'judge': (f"{jm[0].get('provider')}/{jm[0].get('model')}" if jm else 'Fast tier (cloud)'),
            'economics': ((cfg.get('routing') or {}).get('economics') or {}).get('mode', 'default'),
            'orchestration': (cfg.get('orchestration') or {}).get('mode', 'auto')}


def smoke_test(timeout: int = 120) -> tuple[bool, str]:
    """A real end-to-end call through Pi (print mode, no tools, no saved session)."""
    try:
        r = subprocess.run(pi_command(['-p', '--no-tools', '--no-session',
                                       'Reply with exactly the two words: SPM OK']),
                           capture_output=True, text=True, encoding='utf8', errors='replace', timeout=timeout,
                           env=pu.command_env(pi_env()), cwd=str(agent_dir()), stdin=subprocess.DEVNULL,
                           **pu.hidden_window())
    except subprocess.TimeoutExpired:
        return False, f'No answer within {timeout} s'
    except (OSError, FileNotFoundError) as exc:
        return False, str(exc)
    text = (r.stdout or '').strip()
    if r.returncode == 0 and text:
        return True, redact(text)[-300:]
    return False, redact((r.stderr or r.stdout or f'exit code {r.returncode}').strip())[-600:]
