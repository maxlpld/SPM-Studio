"""Which model answers, and when (Qt-free).

* ``detect_backends()`` lists what is usable on this computer: SPM Studio's Pi (with its Fast/Smart router and
  local Judge, unchanged), a personal Pi, Claude Code, Codex, local Ollama models, direct API connections.
* Each backend belongs to an *account group* (Claude subscription, ChatGPT subscription, local, API …). A
  Pro / Plus subscription handles one long agent run at a time comfortably, so by default each group runs
  one request at a time (Settings › Parallel work).
* ``plan()`` decides for a new request: run it now, offer another free model (ask), switch automatically,
  or wait in the queue.
"""
from __future__ import annotations

import re

LABELS = {'pi': 'Pi', 'claude-code': 'Claude Code', 'codex': 'Codex (ChatGPT)', 'ollama': 'Local',
          'api': 'API'}
GROUP_LABELS = {'anthropic': 'Claude subscription', 'openai': 'ChatGPT subscription', 'pi': 'Pi accounts',
                'local': 'this computer', 'api': 'API keys'}


def detect_backends(conf=None, ollama_timeout: float = 1.5, host=None) -> list[dict]:
    """Every backend usable here. Never raises; missing parts are simply absent."""
    from .host import current
    host = host or current()
    out = []
    try:
        conf = conf if conf is not None else host.ai_config()
    except Exception:
        conf = {}
    # --- Pi: the host's managed Pi keeps its own router (Fast/Smart tiers, local Judge, subagents)
    try:
        managed = host.managed_pi()
        if managed:
            out.append({'key': 'pi', 'kind': 'pi', 'label': managed.get('label', 'Pi (managed)'),
                        'group': managed.get('group', 'pi'), 'tools': True, 'managed': True,
                        'executable': managed['executable'], 'env': managed.get('env', {}),
                        'note': managed.get('note', '')})
        else:
            import shutil
            personal = conf.get('pi_executable') or shutil.which('pi') or ''
            if personal:
                out.append({'key': 'pi', 'kind': 'pi', 'label': 'Pi (your own setup)', 'group': 'pi',
                            'tools': True, 'managed': False, 'executable': personal, 'env': {},
                            'note': 'your own Pi configuration (~/.pi, unchanged)'})
    except Exception:
        pass
    # --- Claude Code / Codex (their own sign-in)
    try:
        from .agents.cli_events import detect
        for key, group in (('claude-code', 'anthropic'), ('codex', 'openai')):
            exe = (conf.get('agent_executable') if conf.get('backend') == key else '') or detect(key)
            if exe:
                out.append({'key': key, 'kind': key, 'label': LABELS[key], 'group': group, 'tools': True,
                            'executable': exe, 'note': 'uses its own sign-in'})
    except Exception:
        pass
    # --- local models (Ollama), chat only
    try:
        from .agents import ollama
        base = conf.get('judge_url') or ollama.OLLAMA_URL
        if ollama.running(base, timeout=ollama_timeout):
            for m in ollama.installed(base):
                name = m.get('name', '')
                if not name or 'embed' in name:
                    continue
                out.append({'key': 'ollama:' + name, 'kind': 'ollama', 'label': 'Local · ' + name,
                            'group': 'local', 'tools': False, 'model': name, 'base': base,
                            'size': int(m.get('size') or 0), 'note': 'free, runs on this computer'})
    except Exception:
        pass
    # --- direct connections (API keys, LM Studio, llama.cpp, custom endpoints), chat only
    try:
        from . import settings_store as ss
        for c in conf.get('connections') or []:
            meta = ss.PROVIDERS.get(c.get('provider'), {})
            if not meta or not c.get('model') or c.get('provider') == 'ollama':
                continue
            local = meta['kind'] == 'local' or str(c.get('base', '')).startswith(('http://127.', 'http://localhost'))
            if meta['kind'] == 'api' and not ss.api_key(c):
                continue
            out.append({'key': f"api:{c['id']}", 'kind': 'api', 'label': f"{c.get('label') or meta['label']} · {c['model']}",
                        'group': 'local' if local else 'api', 'tools': False, 'provider': c['provider'],
                        'wire': meta['wire'], 'model': c['model'], 'base': c.get('base', ''), 'connection': c,
                        'account': c.get('label', ''), 'note': 'runs on this computer' if local else 'billed per token'})
        # a host's single legacy connection (e.g. SPM Studio's "Direct API" provider + model)
        if conf.get('provider') and conf.get('model') and conf.get('provider') != 'ollama':
            from .agents.security import CredentialStore
            if CredentialStore().get(conf['provider']):
                provider = conf['provider']
                out.append({'key': f"api:{provider}/{conf['model']}", 'kind': 'api',
                            'label': f"API · {provider}/{conf['model']}", 'group': 'api', 'tools': False,
                            'provider': provider, 'wire': ss.wire(provider) if provider in ss.PROVIDERS else 'openai',
                            'model': conf['model'], 'base': conf.get('api_base', ''),
                            'connection': {'id': '', 'provider': provider}, 'account': provider,
                            'note': 'billed per token'})
    except Exception:
        pass
    return out


def find(backends: list[dict], key: str) -> dict | None:
    return next((b for b in backends if b['key'] == key), None)


# ------------------------------------------------------------------ task size
_LARGE = re.compile(r'\b(implement|refactor|debug|patch|fix|build|create|write a (script|tool|module|plugin)|'
                    r'multi[- ]file|architecture|release|migrate|tests?|github|crée|créer|corrige|implémente|'
                    r'développe|script|module|plugin)\b', re.I)
_SMALL = re.compile(r'\b(what is|what\'s|define|translate|summari[sz]e|reply|rewrite|reformulate|explain|'
                    r'qu\'est-ce|traduis|résume|reformule|réponds|corrige ce texte|e-?mail|mail)\b', re.I)


def task_size(text: str, conf=None) -> tuple[str, str]:
    """('small' | 'large', why). Uses the local Judge when one is configured, else simple rules."""
    text = str(text or '')
    try:
        conf = conf or {}
        if conf.get('judge') == 'local' and conf.get('judge_model'):
            from .agents import ollama
            d = ollama.classify(text, conf['judge_model'], conf.get('judge_url') or ollama.OLLAMA_URL, timeout=8)
            return ('large' if d['tier'] == 'Smart' else 'small'), f"local Judge: {d['tier']} ({d['reason']})"
    except Exception:
        pass
    if _LARGE.search(text) or len(text) > 1200 or '```' in text:
        return 'large', 'rules: development task'
    if _SMALL.search(text) or len(text) < 160:
        return 'small', 'rules: short request'
    return 'large', 'rules: long request'


# ------------------------------------------------------------------ capacity
def capacity(backend: dict, running: dict, conf: dict) -> int:
    """Free slots in the backend's account group (``running``: {group: count})."""
    group = backend.get('group', 'api')
    limit = int((conf.get('limits') or {}).get(group, 1))
    return limit - int(running.get(group, 0))


def _ordered(backends: list[dict], size: str, need_tools: bool, conf: dict) -> list[dict]:
    pref = list(conf.get('preference') or ['pi', 'claude-code', 'codex'])
    agents = sorted([b for b in backends if b['tools']],
                    key=lambda b: pref.index(b['key']) if b['key'] in pref else len(pref))
    local = sorted([b for b in backends if b['kind'] == 'ollama'], key=lambda b: b.get('size', 0))
    api = [b for b in backends if b['kind'] == 'api']
    if need_tools:
        return agents
    if size == 'small' and conf.get('local_for_small', True):
        # mid-size local model first: the smallest one is usually the Judge
        if len(local) > 1:
            local = local[1:] + local[:1]
        return local + agents + api
    return agents + api + local


def plan(requested: str, backends: list[dict], running: dict, conf: dict, size: str = 'large',
         need_tools: bool = True, busy_names: dict | None = None) -> dict:
    """Decide how to run a request.

    Returns ``{'action': 'run' | 'ask' | 'queue', 'backend': key or '', 'alternative': key or '',
    'reason': text}``. ``requested`` is ``'auto'`` or a backend key.
    """
    busy_names = busy_names or {}
    profile = conf.get('routing_profile', 'balanced')
    if profile == 'local':                       # never the cloud, not even as a fallback
        backends = [b for b in backends if b.get('group') == 'local']
        if not backends:
            return {'action': 'queue', 'backend': '', 'alternative': '',
                    'reason': 'Local only: no local model is available (start Ollama or a local server).'}
    elif profile == 'eco' and not need_tools:
        size = 'small'
    elif profile == 'performance':
        conf = {**conf, 'local_for_small': False}
    if profile == 'manual':
        conf = {**conf, 'when_busy': 'queue'}    # no automatic switching
    if not backends:
        return {'action': 'queue', 'backend': '', 'alternative': '',
                'reason': 'No model is set up yet: open Settings › AI assistant… first.'}
    if requested == 'auto' or (not find(backends, requested) and profile != 'local'):
        order = _ordered(backends, size, need_tools, conf) or backends
        for b in order:
            if capacity(b, running, conf) > 0:
                why = 'small request → ' + b['label'] if size == 'small' else 'development task → ' + b['label']
                return {'action': 'run', 'backend': b['key'], 'alternative': '', 'reason': why}
        return {'action': 'queue', 'backend': order[0]['key'], 'alternative': '',
                'reason': 'Every model is busy; this request starts as soon as one is free.'}
    chosen = find(backends, requested)
    if chosen is None:                           # e.g. a cloud model in local-only mode
        return {'action': 'queue', 'backend': '', 'alternative': '',
                'reason': f'{requested} is not allowed by the routing profile “{profile}”.'}
    if capacity(chosen, running, conf) > 0:
        return {'action': 'run', 'backend': chosen['key'], 'alternative': '', 'reason': ''}
    others = [b for b in _ordered(backends, size, need_tools or chosen['tools'], conf)
              if b['key'] != chosen['key'] and b['group'] != chosen['group'] and capacity(b, running, conf) > 0]
    busy = busy_names.get(chosen['group'], '')
    reason = (f"{chosen['label']} is already working" + (f' on “{busy}”' if busy else '') +
              f" ({GROUP_LABELS.get(chosen['group'], chosen['group'])}: "
              f"{(conf.get('limits') or {}).get(chosen['group'], 1)} at a time).")
    if not others:
        return {'action': 'queue', 'backend': chosen['key'], 'alternative': '', 'reason': reason +
                ' No other model is free, so it waits in the queue.'}
    alt = others[0]
    mode = 'auto' if conf.get('full_access') else conf.get('when_busy', 'ask')
    if mode == 'auto':
        return {'action': 'run', 'backend': alt['key'], 'alternative': chosen['key'],
                'reason': reason + f" Switched to {alt['label']}."}
    if mode == 'queue':
        return {'action': 'queue', 'backend': chosen['key'], 'alternative': alt['key'], 'reason': reason}
    return {'action': 'ask', 'backend': chosen['key'], 'alternative': alt['key'], 'reason': reason}
