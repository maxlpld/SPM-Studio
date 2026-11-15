"""Local Judge: hardware survey, three verified model profiles, Ollama helpers,
and real Fast/Smart classification calls.

Rules kept from earlier releases: never invent installable models or measured
benchmarks. Candidate tags come from a dated built-in catalog; at setup each
tag is verified against the official Ollama registry (exact download size).
If the registry is unreachable the last verified result (cached with its
timestamp) or the built-in catalog is shown and labelled as such.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from . import platform_util as pu

OLLAMA_URL = 'http://127.0.0.1:11434'
REGISTRY = 'https://registry.ollama.ai/v2/library'
CATALOG_DATE = '2026-11-14'
# Small instruction models suited to one-word routing decisions. Memory figures
# are the published approximate requirements for the default (Q4) Ollama tags.
CATALOG = [
    {'tag': 'qwen3.5:0.8b', 'params': '0.8 B', 'approx_gb': 1.0, 'need_gb': 2.0,
     'note': 'Tiny and very fast; good enough for a two-way Fast/Smart decision.'},
    {'tag': 'qwen3.5:2b', 'params': '2 B', 'approx_gb': 2.7, 'need_gb': 4.0,
     'note': 'More reliable on borderline requests, still sub-second on a GPU.'},
    {'tag': 'qwen3.5:4b', 'params': '4 B', 'approx_gb': 3.4, 'need_gb': 6.0,
     'note': 'Best judgement of the small models; slower on CPU-only machines.'},
    {'tag': 'qwen3.5:9b', 'params': '9 B', 'approx_gb': 6.6, 'need_gb': 8.0,
     'note': 'Heavier; only worth it with 8 GB+ of free GPU memory.'},
]
FAST_PROMPT = 'What is 2+2?'
SMART_PROMPT = ('Implement a multi-file Qt analysis plugin with a background worker, unit tests and a '
                'migration of the existing settings format, then debug the race condition it causes.')


def _prompt(message: str) -> str:
    return ('You route requests for a coding assistant. Classify the task as "Fast" (simple question, '
            'explanation, small script or small fix) or "Smart" (complex software development, multi-file '
            'changes, architecture or difficult debugging). Respond ONLY with JSON: '
            '{"tier":"Fast" or "Smart","confidence":0.0-1.0,"reason":"short reason"}.\nTask: ' + message[:1500])


# --------------------------------------------------------------------- ollama
def ollama_executable() -> str | None:
    found = shutil.which('ollama')
    if found:
        return found
    candidates = []
    if pu.IS_MAC:
        candidates += [Path('/Applications/Ollama.app/Contents/Resources/ollama'),
                       Path.home() / 'Applications/Ollama.app/Contents/Resources/ollama',
                       Path('/usr/local/bin/ollama'), Path('/opt/homebrew/bin/ollama')]
    if pu.IS_WINDOWS:
        local = os.environ.get('LOCALAPPDATA', '')
        if local:
            candidates.append(Path(local) / 'Programs' / 'Ollama' / 'ollama.exe')
    if pu.IS_LINUX:
        candidates += [Path('/usr/local/bin/ollama'), Path('/usr/bin/ollama')]
    return next((str(p) for p in candidates if p.is_file()), None)


def ollama_running(base: str = OLLAMA_URL, timeout: float = 2) -> str:
    """Version string if an Ollama server answers, else ''."""
    from .providers import endpoint
    try:
        with urlopen(endpoint('ollama', base) + '/api/version', timeout=timeout) as r:
            return str(json.load(r).get('version', 'unknown'))
    except (OSError, ValueError):
        return ''


def installed_models(base: str = OLLAMA_URL) -> list[dict]:
    from .providers import endpoint
    try:
        with urlopen(endpoint('ollama', base) + '/api/tags', timeout=3) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return []
    return [{'name': m.get('name', ''), 'size': m.get('size', 0),
             'parameter_size': (m.get('details') or {}).get('parameter_size', '')}
            for m in data.get('models', []) if m.get('name')]


def start_ollama() -> bool:
    """Start the Ollama server if it is installed but not running (per user)."""
    if ollama_running():
        return True
    exe = ollama_executable()
    try:
        if pu.IS_MAC:
            for app in (Path('/Applications/Ollama.app'), Path.home() / 'Applications/Ollama.app'):
                if app.is_dir():
                    subprocess.Popen(['open', '-g', str(app)])
                    break
            else:
                if not exe:
                    return False
                subprocess.Popen([exe, 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        elif exe:
            kwargs = pu.hidden_window() if pu.IS_WINDOWS else {'start_new_session': True}
            subprocess.Popen([exe, 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        else:
            return False
    except OSError:
        return False
    for _ in range(30):
        if ollama_running():
            return True
        time.sleep(0.5)
    return False


def ollama_install_plan() -> dict:
    """How Ollama can be installed here. Executed only after explicit consent."""
    if pu.IS_WINDOWS:
        if pu.winget():
            return {'kind': 'command', 'argv': [pu.winget(), 'install', '-e', '--id', 'Ollama.Ollama',
                                                '--accept-source-agreements', '--accept-package-agreements'],
                    'text': 'winget install Ollama.Ollama (official package, per-user installer window)'}
        return {'kind': 'installer', 'url': 'https://ollama.com/download/OllamaSetup.exe',
                'text': 'Download OllamaSetup.exe from ollama.com and run it'}
    if pu.IS_MAC:
        return {'kind': 'dmg', 'url': 'https://ollama.com/download/Ollama.dmg',
                'text': 'Download Ollama.dmg from ollama.com and copy Ollama.app to your Applications folder'}
    return {'kind': 'terminal', 'argv': ['bash', '-c', 'curl -fsSL https://ollama.com/install.sh | sh'],
            'text': 'Official script from ollama.com (asks for your password in a terminal window)'}


def install_ollama(log, cancel=None) -> str:
    """Install Ollama following ollama_install_plan(); returns '' or a manual hint."""
    from .pi_setup import download, managed_root
    plan = ollama_install_plan()
    if plan['kind'] == 'command':
        from .pi_setup import run_streaming
        code = run_streaming(plan['argv'], log, timeout=1800, cancel=cancel)
        if code != 0:
            return 'winget could not install Ollama; install it from https://ollama.com/download'
    elif plan['kind'] == 'installer':
        target = managed_root() / 'downloads'
        target.mkdir(parents=True, exist_ok=True)
        exe = target / 'OllamaSetup.exe'
        log('Downloading OllamaSetup.exe …')
        download(plan['url'], exe, cancel=cancel, timeout=300)
        log('Starting the Ollama installer; follow its window.')
        subprocess.run([str(exe)], check=False)
    elif plan['kind'] == 'dmg':
        target = managed_root() / 'downloads'
        target.mkdir(parents=True, exist_ok=True)
        dmg = target / 'Ollama.dmg'
        log('Downloading Ollama.dmg …')
        download(plan['url'], dmg, cancel=cancel, timeout=600)
        mount = Path(subprocess.run(['mktemp', '-d'], capture_output=True, text=True).stdout.strip())
        r = subprocess.run(['hdiutil', 'attach', '-nobrowse', '-quiet', '-mountpoint', str(mount), str(dmg)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return 'Could not open Ollama.dmg; open it from Downloads and drag Ollama to Applications'
        try:
            dest_root = Path('/Applications') if os.access('/Applications', os.W_OK) else Path.home() / 'Applications'
            dest_root.mkdir(exist_ok=True)
            app = next(mount.glob('*.app'), None)
            if app is None:
                return 'Ollama.dmg did not contain an application'
            dest = dest_root / app.name
            if dest.exists():
                log(f'{dest} already exists; keeping it.')
            else:
                log(f'Copying {app.name} to {dest_root} …')
                shutil.copytree(app, dest, symlinks=True)
        finally:
            subprocess.run(['hdiutil', 'detach', '-quiet', str(mount)], check=False)
    else:
        from .platform_util import open_terminal, write_terminal_script
        script = write_terminal_script(managed_root() / 'launchers', 'install-ollama', {}, plan['argv'],
                                       'Installing Ollama with the official script from ollama.com.\n'
                                       'It will ask for your password (sudo). Close this window when done.')
        manual = open_terminal(script)
        if manual:
            return 'Run in a terminal: curl -fsSL https://ollama.com/install.sh | sh'
        log('The Ollama installer runs in a terminal window; waiting for the server …')
        for _ in range(600):
            if cancel is not None and cancel.is_set():
                return 'Cancelled'
            if ollama_running():
                return ''
            time.sleep(1)
        return 'Ollama did not start yet; finish the installer and press Retry'
    log('Starting Ollama …')
    return '' if start_ollama() else 'Ollama is installed but not running yet; start it, then press Retry'


def pull_model(tag: str, log, progress=None, cancel: threading.Event | None = None, base: str = OLLAMA_URL):
    """Download a model through Ollama's REST API, reporting real progress."""
    from .providers import endpoint
    if not tag or any(x in tag for x in ('/', '..', '\n', ' ')) or len(tag) > 120:
        raise ValueError('Invalid model tag')
    req = Request(endpoint('ollama', base) + '/api/pull', method='POST',
                  headers={'Content-Type': 'application/json'},
                  data=json.dumps({'model': tag, 'stream': True}).encode())
    last = ''
    with urlopen(req, timeout=3600) as r:
        for raw in r:
            if cancel is not None and cancel.is_set():
                raise RuntimeError('Download cancelled (partial data is resumed next time)')
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if event.get('error'):
                raise RuntimeError('Ollama: ' + str(event['error']))
            status = str(event.get('status', ''))
            if event.get('total') and progress:
                progress(min(100, int(event.get('completed', 0) * 100 / event['total'])))
            if status and status != last:
                last = status
                if not status.startswith('pulling ') or 'manifest' in status:
                    log(status)
    log(f'{tag} downloaded.')


# --------------------------------------------------------------------- catalog
def registry_size(tag: str, timeout: float = 6) -> int | None:
    """Exact download size from the official registry manifest (sum of layers)."""
    from .pi_setup import _ssl_context
    name, _, version = tag.partition(':')
    req = Request(f'{REGISTRY}/{name}/manifests/{version or "latest"}',
                  headers={'Accept': 'application/vnd.docker.distribution.manifest.v2+json',
                           'User-Agent': 'SPM-Studio-setup'})
    with urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        manifest = json.load(r)
    return sum(int(layer.get('size', 0)) for layer in manifest.get('layers', [])) or None


def _cache_path() -> Path:
    from spm_studio.core import paths
    return paths.cache_dir() / 'judge_catalog.json'


def catalog(refresh: bool = False) -> dict:
    """{'source': 'registry'|'cache'|'builtin', 'checked': iso time, 'models': [...]}."""
    cache = _cache_path()
    if not refresh:
        try:
            data = json.loads(cache.read_text(encoding='utf8'))
            if data.get('models'):
                data['source'] = 'cache'
                return data
        except (OSError, ValueError):
            pass
    models, verified = [], 0
    for item in CATALOG:
        entry = dict(item)
        try:
            size = registry_size(item['tag'])
            if size:
                entry['download_bytes'] = size
                entry['verified'] = True
                verified += 1
        except Exception:
            entry['verified'] = False
        models.append(entry)
    result = {'source': 'registry' if verified else 'builtin', 'catalog_date': CATALOG_DATE,
              'checked': time.strftime('%Y-%m-%d %H:%M'), 'models': models}
    if verified:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(result, indent=1), encoding='utf8')
        except OSError:
            pass
    return result


def recommend(hw: dict, cat: dict, installed: list[dict] | None = None) -> dict:
    """Three hardware-appropriate profiles (fastest / balanced / higher quality).

    Memory budget: usable GPU memory when a GPU was found, otherwise half the
    system RAM (CPU inference). Returns honest notes when fewer fit.
    """
    gib = 1024 ** 3
    installed_names = {m.get('name') for m in installed or []}
    gpu_mem = hw.get('gpu_memory_bytes') or 0
    ram = hw.get('ram_bytes') or 0
    models = cat.get('models', [])
    fitting = []
    for m in models:
        need = m['need_gb'] * gib
        where = 'GPU' if gpu_mem and need <= gpu_mem * 0.9 else 'CPU' if ram and need <= ram * 0.5 else None
        if where:
            fitting.append({**m, 'runs_on': where, 'installed': m['tag'] in installed_names})
    notes = []
    if not ram and not gpu_mem:
        notes.append('Memory could not be measured; profiles assume a typical 8 GB machine.')
        fitting = [{**m, 'runs_on': 'CPU (assumed)', 'installed': m['tag'] in installed_names}
                   for m in models if m['need_gb'] <= 4]
    gpu_fit = [m for m in fitting if m['runs_on'] == 'GPU']
    pool = gpu_fit if len(gpu_fit) >= 2 else fitting
    # CPU-only: anything above 4 B is too slow for a per-turn decision.
    if pool and all(m['runs_on'] != 'GPU' for m in pool):
        pool = [m for m in pool if m['need_gb'] <= 6.0]
        notes.append('No usable GPU memory detected: the Judge runs on the CPU, so smaller models are preferred.')
    profiles = {}
    if pool:
        profiles['fastest'] = pool[0]
        if len(pool) >= 2:
            profiles['balanced'] = pool[1]
        if len(pool) >= 3:
            profiles['quality'] = pool[-1]
    if len(profiles) < 3:
        notes.append(f'Only {len(profiles)} distinct candidate(s) fit this hardware; '
                     'a cloud Judge (your Fast model) is the alternative.')
    return {'profiles': profiles, 'notes': notes}


def describe_hardware(hw: dict) -> str:
    gib = 1024 ** 3
    ram = f"{hw['ram_bytes'] / gib:.1f} GiB RAM" if hw.get('ram_bytes') else 'RAM unknown'
    if hw.get('gpu_memory_bytes'):
        kind = 'measured' if hw.get('gpu_memory_measured') else 'estimated'
        gpu = f"{hw.get('gpu')} with {hw['gpu_memory_bytes'] / gib:.1f} GiB GPU memory ({kind})"
    else:
        gpu = f"GPU: {hw.get('gpu') or 'none detected'} (no usable GPU memory measured)"
    disk = f", {hw['free_disk_bytes'] / gib:.0f} GiB free disk" if hw.get('free_disk_bytes') else ''
    return f"{hw.get('os')} {hw.get('architecture')}, {hw.get('cpu_cores')} CPU threads, {ram}; {gpu}{disk}"


# --------------------------------------------------------------------- legacy helpers
def local_info(base: str = OLLAMA_URL) -> dict:
    hw = pu.hardware()
    hw['models'] = installed_models(base)
    return hw


def profiles(info: dict) -> list[dict]:
    """Installed models ordered by size (kept for the direct-API routing box)."""
    tagged = sorted(info.get('models', []), key=lambda m: int(m.get('size') or 0))
    if not tagged:
        return []
    if len(tagged) <= 2:
        return tagged
    return [tagged[0], tagged[len(tagged) // 2], tagged[-1]]


# --------------------------------------------------------------------- classification
def _parse_decision(text: str) -> dict:
    text = (text or '').strip()
    start, end = text.find('{'), text.rfind('}')
    label = json.loads(text[start:end + 1] if start >= 0 and end > start else text)
    tier = str(label.get('tier', '')).strip().capitalize()
    if tier not in ('Fast', 'Smart'):
        raise ValueError('Judge result not Fast or Smart')
    try:
        confidence = max(0.0, min(1.0, float(label.get('confidence', 0))))
    except (TypeError, ValueError):
        confidence = None
    return {'tier': tier, 'confidence': confidence, 'reason': str(label.get('reason', ''))[:200]}


def classify(message: str, model: str, base: str = OLLAMA_URL, timeout: float = 30) -> dict:
    """Native Ollama call with thinking disabled (``think: false``) and JSON output."""
    from .providers import endpoint
    request = Request(endpoint('ollama', base) + '/api/generate', method='POST',
                      headers={'Content-Type': 'application/json'},
                      data=json.dumps({'model': model, 'prompt': _prompt(message), 'stream': False,
                                       'think': False, 'format': 'json',
                                       'options': {'temperature': 0}}).encode())
    start = time.monotonic()
    with urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    result = _parse_decision(data.get('response', ''))
    result.update(model=model, seconds=round(time.monotonic() - start, 3), path='ollama native')
    return result


def classify_openai(message: str, model: str, base_v1: str, timeout: float = 30) -> dict:
    """The same decision through an OpenAI-style endpoint — the path pi-shift-router uses."""
    request = Request(base_v1.rstrip('/') + '/chat/completions', method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer local'},
                      data=json.dumps({'model': model, 'stream': False, 'temperature': 0,
                                       'response_format': {'type': 'json_object'},
                                       'messages': [{'role': 'user', 'content': _prompt(message)}]}).encode())
    start = time.monotonic()
    with urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    content = ((data.get('choices') or [{}])[0].get('message') or {}).get('content', '')
    result = _parse_decision(content)
    result.update(model=model, seconds=round(time.monotonic() - start, 3), path='router endpoint')
    return result


def benchmark(model: str, base_v1: str | None = None) -> list[dict]:
    """Fast prompt + Smart prompt; one warm-up call first (model load is not latency)."""
    call = (lambda m: classify_openai(m, model, base_v1)) if base_v1 else (lambda m: classify(m, model))
    try:
        call('hello')                      # loads the model into memory
    except Exception:
        pass
    out = []
    for expected, prompt in (('Fast', FAST_PROMPT), ('Smart', SMART_PROMPT)):
        r = call(prompt)
        r['expected'] = expected
        r['correct'] = r['tier'] == expected
        out.append(r)
    return out
