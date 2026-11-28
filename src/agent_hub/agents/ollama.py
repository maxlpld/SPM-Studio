"""Local Ollama server: detection, installed / loaded models, pulling, and chat with real statistics.

``chat()`` returns the provider-reported counters (prompt/eval token counts and durations), so tokens per
second shown in the hub are measured by Ollama, not estimated.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen

OLLAMA_URL = 'http://127.0.0.1:11434'


def executable() -> str:
    found = shutil.which('ollama')
    if found:
        return found
    for p in (Path('/usr/local/bin/ollama'), Path('/usr/bin/ollama'), Path('/opt/homebrew/bin/ollama'),
              Path.home() / 'AppData' / 'Local' / 'Programs' / 'Ollama' / 'ollama.exe'):
        if p.is_file():
            return str(p)
    return ''


def _get(base: str, path: str, timeout: float):
    with urlopen(Request(base.rstrip('/') + path), timeout=timeout) as r:
        return json.load(r)


def running(base: str = OLLAMA_URL, timeout: float = 1.5) -> str:
    """The server version, or '' when nothing answers."""
    try:
        return str(_get(base, '/api/version', timeout).get('version', '?'))
    except Exception:
        return ''


def installed(base: str = OLLAMA_URL, timeout: float = 3) -> list[dict]:
    try:
        return [m for m in _get(base, '/api/tags', timeout).get('models', []) if isinstance(m, dict)]
    except Exception:
        return []


def loaded(base: str = OLLAMA_URL, timeout: float = 1.5) -> list[dict]:
    """Models in memory now (``/api/ps``): name, size, size_vram (bytes), expires_at."""
    try:
        return [m for m in _get(base, '/api/ps', timeout).get('models', []) if isinstance(m, dict)]
    except Exception:
        return []


def start() -> bool:
    exe = executable()
    if not exe:
        return False
    kwargs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL, 'stdin': subprocess.DEVNULL}
    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs['start_new_session'] = True
    try:
        subprocess.Popen([exe, 'serve'], **kwargs)
    except OSError:
        return False
    for _ in range(30):
        if running():
            return True
        time.sleep(0.3)
    return False


def pull(tag: str, log=None, progress=None, base: str = OLLAMA_URL):
    req = Request(base.rstrip('/') + '/api/pull', data=json.dumps({'name': tag, 'stream': True}).encode(),
                  headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(req, timeout=3600) as r:
        for line in r:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('error'):
                raise RuntimeError(event['error'])
            if log and event.get('status'):
                log(event['status'])
            if progress and event.get('total'):
                progress(int(100 * event.get('completed', 0) / max(1, event['total'])))


def chat(model: str, messages: list[dict], base: str = OLLAMA_URL, timeout: float = 600,
         on_text=None, cancelled=lambda: False, think: bool | None = None) -> dict:
    """Streamed chat. Returns ``{'text', 'model', 'stats': {...}}`` with Ollama's own counters:
    ``prompt_tokens``, ``output_tokens``, ``ttft_s`` (time to first token, measured here),
    ``tokens_per_s`` (eval_count / eval_duration from Ollama), ``total_s``."""
    payload = {'model': model, 'messages': messages, 'stream': True}
    if think is not None:
        payload['think'] = bool(think)
    req = Request(base.rstrip('/') + '/api/chat', data=json.dumps(payload).encode(),
                  headers={'Content-Type': 'application/json'}, method='POST')
    started = time.monotonic()
    first = None
    parts = []
    final = {}
    with urlopen(req, timeout=timeout) as r:
        for line in r:
            if cancelled():
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('error'):
                raise RuntimeError(str(event['error'])[:300])
            piece = (event.get('message') or {}).get('content', '')
            if piece:
                if first is None:
                    first = time.monotonic() - started
                parts.append(piece)
                if on_text:
                    on_text(piece)
            if event.get('done'):
                final = event
                break
    eval_count = int(final.get('eval_count') or 0)
    eval_ns = int(final.get('eval_duration') or 0)
    stats = {'prompt_tokens': int(final.get('prompt_eval_count') or 0), 'output_tokens': eval_count,
             'ttft_s': round(first, 2) if first is not None else None,
             'tokens_per_s': round(eval_count / (eval_ns / 1e9), 1) if eval_count and eval_ns else None,
             'total_s': round(time.monotonic() - started, 2), 'source': 'reported by Ollama'}
    return {'text': ''.join(parts), 'model': final.get('model', model), 'stats': stats}


# ---------------------------------------------------------------- a model that fits this computer
CATALOG = [  # conversational models (not the Judge): tag, parameters, approx. download GB, min memory GB
    {'tag': 'qwen3.5:4b', 'params': '4B', 'gb': 3.4, 'min_gb': 6, 'note': 'good everyday chat, multilingual'},
    {'tag': 'qwen3.5:9b', 'params': '9B', 'gb': 6.6, 'min_gb': 10, 'note': 'stronger answers, needs a GPU or 16 GB'},
    {'tag': 'gemma3:4b', 'params': '4B', 'gb': 3.3, 'min_gb': 6, 'note': 'alternative small model'},
]


def suggest(hw: dict, installed_names: list[str] | None = None) -> dict | None:
    """The largest catalog model that fits the GPU memory (or RAM for CPU-only / unified memory)."""
    installed_names = installed_names or []
    gb = 1024 ** 3
    vram = (hw.get('gpu_memory_bytes') or 0) / gb
    ram = (hw.get('ram_bytes') or 0) / gb
    budget = vram if vram >= 4 else ram * 0.5
    fitting = [m for m in CATALOG if m['min_gb'] <= max(budget, 0) + 0.01]
    if not fitting:
        return None
    best = max(fitting, key=lambda m: m['gb'])
    return {**best, 'installed': best['tag'] in installed_names,
            'runs_on': 'GPU' if vram >= best['min_gb'] else 'CPU / shared memory'}


# ---------------------------------------------------------------- Judge (task size), as in SPM Studio's router
def _judge_prompt(message: str) -> str:
    return ('You route requests for a coding assistant. Classify the task as "Fast" (simple question, '
            'explanation, small script or small fix) or "Smart" (complex software development, multi-file '
            'changes, architecture or difficult debugging). Respond ONLY with JSON: '
            '{"tier":"Fast" or "Smart","confidence":0.0-1.0,"reason":"short reason"}.\nTask: ' + message[:1500])


def classify(message: str, model: str, base: str = OLLAMA_URL, timeout: float = 30) -> dict:
    """Local Judge: native Ollama call, thinking off, JSON output → {'tier', 'confidence', 'reason'}."""
    req = Request(base.rstrip('/') + '/api/generate', method='POST', headers={'Content-Type': 'application/json'},
                  data=json.dumps({'model': model, 'prompt': _judge_prompt(message), 'stream': False,
                                   'think': False, 'format': 'json', 'options': {'temperature': 0}}).encode())
    with urlopen(req, timeout=timeout) as r:
        text = str(json.load(r).get('response', '')).strip()
    start, end = text.find('{'), text.rfind('}')
    label = json.loads(text[start:end + 1] if start >= 0 and end > start else text)
    tier = str(label.get('tier', '')).strip().capitalize()
    if tier not in ('Fast', 'Smart'):
        raise ValueError('Judge result not Fast or Smart')
    return {'tier': tier, 'confidence': label.get('confidence'), 'reason': str(label.get('reason', ''))[:200]}
