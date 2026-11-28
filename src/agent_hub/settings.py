"""Agent Hub preferences (Qt-free). Stored next to the chats as ``settings.json``."""
from __future__ import annotations

import json
from pathlib import Path

from .store import _atomic

ACCESS_MODES = ('app', 'folders', 'everywhere')
SORT_MODES = ('ask', 'auto', 'off')
BUSY_MODES = ('ask', 'auto', 'queue')
GROUPS = ('anthropic', 'openai', 'pi', 'local', 'api')

DEFAULTS = {
    # Where the agent may create and change files without asking. The SPM Studio folders (scripts,
    # customization, documents, the app itself) are always included.
    'access_mode': 'app',
    'extra_folders': [],
    # Full access: no approval requests at all (commands, files anywhere, moving chats).
    'full_access': False,
    # "Always allow" answers: [{'tool': 'bash', 'prefix': 'git push'} | {'tool': 'write', 'path': '/x'} | {'tool': 'x'}]
    'always_rules': [],
    # Sorting new chats into projects: ask, move automatically, or never.
    'auto_sort': 'ask',
    # How many requests may run at the same time on one account (a Pro / Plus subscription copes with 1).
    'limits': {'anthropic': 1, 'openai': 1, 'pi': 1, 'local': 1, 'api': 3},
    # When the chosen model is busy: ask which other model to use, choose automatically, or wait.
    'when_busy': 'ask',
    # Model of new chats: 'auto' (the hub picks by task size and free capacity) or a backend key.
    'default_backend': 'auto',
    # Prefer a local model (Ollama) for small requests when one is installed.
    'local_for_small': True,
    # Order tried by 'auto' for large tasks.
    'preference': ['pi', 'claude-code', 'codex'],
    # The toolbar's Assistant button opens the hub (the classic panel stays reachable from the hub).
    'replace_classic': True,
    'layout': 'single',
    'sidebar': True,
    'send_with_enter': True,
    # ---- 0.2: routing profile — eco · balanced · performance · local (never the cloud) · manual
    'routing_profile': 'balanced',
    # ---- brainstorming
    'brainstorm_backend': 'auto',
    'brainstorm_research': False,          # bounded read-only research
    'brainstorm_max_tool_calls': 12,
    'brainstorm_budget_tokens': 60000,     # per brainstorming chat (reported, or estimated)
    # ---- voice
    'voice_backend': 'vosk',               # vosk (offline) · cloud (OpenAI-compatible, explicit consent)
    'voice_language': 'en',                # en · fr · de
    'voice_device': '',                    # '' = system default microphone
    'voice_cloud_consent': False,
    'voice_cloud_connection': '',
    'voice_shortcut': 'F11',               # hold to talk
    # ---- local monitoring
    'monitor': True,
    'monitor_interval_ms': 1000,
    # ---- usage
    'usage_warn_tokens_5h': 0,             # 0 = no warning
    # ---- embedding (hosts with a main window)
    'open_mode': 'panel',                  # panel (docked) · window
    'detached_close': 'hide',              # hide · redock
    'standalone_theme': 'light',           # light · dark · a theme file name
    'font_scale': 100,
    # ---- 0.3: calendar, to-do and e-mail for the assistant
    'assistant_organizer': True,           # the assistant may use the calendar / to-do tools
    'assistant_mail': True,                # … and read e-mail (sending always needs the user's click)
    'assistant_reminders': True,           # it may add reminders on its own initiative (dismissible cards)
    'assistant_event_tasks': True,         # it proposes preparation / follow-up to-dos for events
    'admin_mail_detection': True,          # administrative e-mails become a to-do + form card
    'calendar_week_start': 0,              # 0 Monday · 6 Sunday
    'calendar_day_start': 8,               # first hour shown in day / week views
    'calendar_work_start': 9,
    'calendar_work_end': 18,
    'calendar_default_view': 'week',       # day · week · month · schedule
    'calendar_default_reminder': 10,       # minutes before (-1 = none)
    'calendar_notifications': True,
    'calendar_start_summary': True,        # on start: missed and upcoming reminders
    'todo_default_list': '',
    'todo_show_completed': True,
    'todo_on_calendar': True,
    'mail_poll': True,                     # background checks only when an account is connected
    'usage_rings': True,                   # per-account usage indicators in the sidebar
}
PROFILES = ('eco', 'balanced', 'performance', 'local', 'manual')


def load(root: Path) -> dict:
    path = Path(root) / 'settings.json'
    try:
        found = json.loads(path.read_text(encoding='utf8'))
        if not isinstance(found, dict):
            found = {}
    except (OSError, ValueError):
        found = {}
    out = json.loads(json.dumps(DEFAULTS))
    for key, value in found.items():
        if key in DEFAULTS and isinstance(value, type(DEFAULTS[key])):
            out[key] = value
    if out['access_mode'] not in ACCESS_MODES:
        out['access_mode'] = 'app'
    if out['auto_sort'] not in SORT_MODES:
        out['auto_sort'] = 'ask'
    if out['when_busy'] not in BUSY_MODES:
        out['when_busy'] = 'ask'
    if out['routing_profile'] not in PROFILES:
        out['routing_profile'] = 'balanced'
    if out['voice_language'] not in ('en', 'fr', 'de'):
        out['voice_language'] = 'en'
    if out['voice_backend'] not in ('vosk', 'cloud'):
        out['voice_backend'] = 'vosk'
    if out['calendar_default_view'] not in ('day', 'week', 'month', 'schedule'):
        out['calendar_default_view'] = 'week'
    out['calendar_week_start'] = 6 if out['calendar_week_start'] == 6 else 0
    out['calendar_day_start'] = max(0, min(12, out['calendar_day_start']))
    if out['open_mode'] not in ('panel', 'window'):
        out['open_mode'] = 'panel'
    if out['detached_close'] not in ('hide', 'redock'):
        out['detached_close'] = 'hide'
    out['monitor_interval_ms'] = max(250, min(10000, out['monitor_interval_ms']))
    out['font_scale'] = max(70, min(200, out['font_scale']))
    limits = dict(DEFAULTS['limits'])
    for key, value in (found.get('limits') or {}).items() if isinstance(found.get('limits'), dict) else []:
        if key in limits and isinstance(value, int):
            limits[key] = max(1, min(8, value))
    out['limits'] = limits
    out['extra_folders'] = [str(f) for f in out['extra_folders'] if str(f).strip()][:50]
    out['always_rules'] = [r for r in out['always_rules'] if isinstance(r, dict) and r.get('tool')][:200]
    return out


def save(root: Path, conf: dict) -> dict:
    clean = load(root)
    for key in DEFAULTS:
        if key in conf and isinstance(conf[key], type(DEFAULTS[key])):
            clean[key] = conf[key]
    _atomic(Path(root) / 'settings.json', clean)
    return load(root)
