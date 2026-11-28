"""Standalone AI connections (Qt-free): direct API accounts and local endpoints, without Pi.

``ai.json`` next to the hub data holds only non-secret fields. API keys go to the OS keyring through
``agents.security.CredentialStore`` under ``<provider>#<connection id>`` (never in this file, logs or
exports).

Connection: ``{'id', 'provider', 'label', 'model', 'base', 'models': [...]}``. Providers:
``openai``, ``anthropic``, ``gemini``, ``openrouter``, ``mistral``, ``deepseek`` (API key) and
``ollama``, ``lmstudio``, ``llamacpp``, ``custom`` (local or self-hosted OpenAI-compatible endpoints).
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

PROVIDERS = {
    'openai': {'label': 'OpenAI (API key)', 'base': 'https://api.openai.com/v1', 'kind': 'api', 'wire': 'openai'},
    'anthropic': {'label': 'Anthropic (API key)', 'base': 'https://api.anthropic.com/v1', 'kind': 'api',
                  'wire': 'anthropic'},
    'gemini': {'label': 'Google Gemini (API key)', 'base': 'https://generativelanguage.googleapis.com/v1beta',
               'kind': 'api', 'wire': 'gemini'},
    'openrouter': {'label': 'OpenRouter (API key)', 'base': 'https://openrouter.ai/api/v1', 'kind': 'api',
                   'wire': 'openai'},
    'mistral': {'label': 'Mistral (API key)', 'base': 'https://api.mistral.ai/v1', 'kind': 'api', 'wire': 'openai'},
    'deepseek': {'label': 'DeepSeek (API key)', 'base': 'https://api.deepseek.com/v1', 'kind': 'api',
                 'wire': 'openai'},
    'ollama': {'label': 'Ollama (local)', 'base': 'http://127.0.0.1:11434', 'kind': 'local', 'wire': 'ollama'},
    'lmstudio': {'label': 'LM Studio (local server)', 'base': 'http://127.0.0.1:1234/v1', 'kind': 'local',
                 'wire': 'openai'},
    'llamacpp': {'label': 'llama.cpp server (local)', 'base': 'http://127.0.0.1:8080/v1', 'kind': 'local',
                 'wire': 'openai'},
    'custom': {'label': 'Other OpenAI-compatible endpoint', 'base': '', 'kind': 'custom', 'wire': 'openai'},
}

DEFAULT = {'connections': [], 'judge': 'none', 'judge_model': '', 'judge_url': 'http://127.0.0.1:11434'}


def _file() -> Path:
    from .paths import data_dir
    return data_dir() / 'ai.json'


def load_ai() -> dict:
    try:
        found = json.loads(_file().read_text(encoding='utf8'))
        if not isinstance(found, dict):
            found = {}
    except (OSError, ValueError):
        found = {}
    out = dict(DEFAULT)
    out.update({k: v for k, v in found.items() if k in DEFAULT})
    out['connections'] = [c for c in out.get('connections') or [] if isinstance(c, dict) and
                          c.get('provider') in PROVIDERS and c.get('id')]
    return out


def save_ai(conf: dict) -> dict:
    from .store import _atomic
    clean = load_ai()
    clean.update({k: conf[k] for k in DEFAULT if k in conf})
    for c in clean['connections']:
        for secret in ('api_key', 'key', 'token', 'password'):
            c.pop(secret, None)                       # never on disk
    _atomic(_file(), clean)
    return load_ai()


def secret_name(connection: dict) -> str:
    return f"{connection['provider']}#{connection['id']}"


def add_connection(provider: str, label: str = '', model: str = '', base: str = '', api_key: str = '') -> dict:
    if provider not in PROVIDERS:
        raise ValueError('Unknown provider')
    base = (base or PROVIDERS[provider]['base']).strip()
    if not base:
        raise ValueError('This provider needs an endpoint address')
    from .agents.providers import endpoint
    endpoint('openai' if provider not in ('ollama',) else 'ollama', base)        # validates the URL
    conn = {'id': uuid.uuid4().hex[:8], 'provider': provider, 'label': (label or PROVIDERS[provider]['label'])[:60],
            'model': model.strip(), 'base': base, 'models': []}
    conf = load_ai()
    conf['connections'].append(conn)
    save_ai(conf)
    if api_key:
        from .agents.security import CredentialStore
        CredentialStore().put(secret_name(conn), api_key.strip())
    return conn


def update_connection(conn_id: str, **fields) -> dict:
    conf = load_ai()
    for c in conf['connections']:
        if c['id'] == conn_id:
            for key in ('label', 'model', 'base', 'models'):
                if key in fields:
                    c[key] = fields[key]
            save_ai(conf)
            return c
    raise KeyError(conn_id)


def remove_connection(conn_id: str):
    conf = load_ai()
    gone = [c for c in conf['connections'] if c['id'] == conn_id]
    conf['connections'] = [c for c in conf['connections'] if c['id'] != conn_id]
    save_ai(conf)
    from .agents.security import CredentialStore
    for c in gone:
        CredentialStore().clear(secret_name(c))


def api_key(connection: dict) -> str:
    from .agents.security import CredentialStore
    store = CredentialStore()
    return store.get(secret_name(connection)) or (store.get(connection['provider'])
                                                   if PROVIDERS.get(connection['provider'], {}).get('kind') == 'api'
                                                   else '')


def wire(provider: str) -> str:
    return PROVIDERS.get(provider, {}).get('wire', 'openai')


def list_models(connection: dict, timeout: float = 8) -> list[str]:
    """Model ids the endpoint reports (GET /models or /api/tags). Raises with a readable message."""
    from urllib.request import Request, urlopen
    from .agents.providers import endpoint
    provider = connection['provider']
    w = wire(provider)
    base = endpoint('ollama' if w == 'ollama' else 'openai', connection.get('base') or PROVIDERS[provider]['base'])
    key = api_key(connection)
    if w == 'ollama':
        url, headers = base + '/api/tags', {}
    elif w == 'anthropic':
        url, headers = base + '/models', {'x-api-key': key, 'anthropic-version': '2023-06-01'}
    elif w == 'gemini':
        url, headers = base + '/models', {'x-goog-api-key': key}
    else:
        url, headers = base + '/models', ({'Authorization': 'Bearer ' + key} if key else {})
    with urlopen(Request(url, headers=headers), timeout=timeout) as r:
        data = json.load(r)
    if w == 'ollama':
        names = [m.get('name', '') for m in data.get('models', [])]
    elif w == 'gemini':
        names = [re.sub(r'^models/', '', m.get('name', '')) for m in data.get('models', [])]
    else:
        names = [m.get('id', '') for m in data.get('data', [])]
    return sorted(n for n in names if n)
