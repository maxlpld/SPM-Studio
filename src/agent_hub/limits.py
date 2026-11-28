"""Subscription and API limits as **reported by the providers** (Qt-free). Never estimated, never invented.

Sources (only documented or observable output of the tools the user already runs):

* **Claude subscription** — Claude Code's ``stream-json`` output carries ``rate_limit_event`` lines with
  ``rate_limit_info`` (read by Claude Code from Anthropic's ``anthropic-ratelimit-unified-*`` response headers):
  ``unifiedWindows.five_hour`` / ``seven_day`` with ``utilization`` (fraction used) and ``resetsAt`` (epoch s),
  or the single limiting window (``rateLimitType``, ``utilization``, ``resetsAt``). Only seen while a Claude
  Code turn runs in Agent Hub; absent for API-key sessions.
* **ChatGPT subscription (Codex)** — Codex reports ``rate_limits`` (``primary`` = 5-hour window,
  ``secondary`` = weekly; ``used_percent``, ``window_minutes``, ``resets_at``) in its ``token_count`` events,
  which it also writes to its own session logs (``~/.codex/sessions/**/rollout-*.jsonl``). Agent Hub reads the
  newest log read-only; no request is made.
* **API keys** — the ``x-ratelimit-*`` (OpenAI-compatible) and ``anthropic-ratelimit-*`` headers of the last
  reply: per-minute request / token limits, not a monthly quota.
* **Pi accounts** — Pi exposes no limit information: “not available from provider”. When Pi signs in with a
  ChatGPT account the ChatGPT figures above are the account's own (same account group).

Each value keeps when it was observed; a window whose reset time has passed is shown as reset, not as used.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

WINDOW_LABELS = {'five_hour': '5-hour window', 'seven_day': 'Weekly', 'seven_day_opus': 'Weekly (Opus)',
                 'seven_day_sonnet': 'Weekly (Sonnet)', 'seven_day_overage_included': 'Weekly (with extra usage)',
                 'primary': '5-hour window', 'secondary': 'Weekly', 'requests': 'Requests per minute',
                 'tokens': 'Tokens per minute', 'overage': 'Extra usage'}


class Limits:
    def __init__(self, root: Path):
        self.path = Path(root) / 'limits.json'

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding='utf8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def record(self, group: str, windows: dict, source: str, account: str = ''):
        """``windows``: {name: {'used': 0..1+, 'resets_at': epoch|None, 'status': str, 'window_s': int}}."""
        if not windows:
            return
        data = self._load()
        entry = data.get(group) or {'windows': {}}
        for name, w in windows.items():
            clean = {'used': float(w['used']) if w.get('used') is not None else None,
                     'resets_at': float(w['resets_at']) if w.get('resets_at') else None,
                     'status': str(w.get('status') or ''), 'window_s': int(w.get('window_s') or 0),
                     'remaining': w.get('remaining'), 'limit': w.get('limit'), 'observed': time.time()}
            entry['windows'][name] = clean
        entry.update(source=source, account=account or entry.get('account', ''), observed=time.time())
        data[group] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name('.limits.tmp')
        tmp.write_text(json.dumps(data, indent=1), encoding='utf8')
        os.replace(tmp, self.path)

    def get(self, group: str, now: float | None = None) -> dict | None:
        """Current view: windows past their reset are marked ``reset`` (usage unknown since)."""
        now = now or time.time()
        if group == 'openai':
            self.refresh_codex()
        entry = self._load().get(group)
        if not entry:
            return None
        out = dict(entry, windows={})
        for name, w in (entry.get('windows') or {}).items():
            w = dict(w)
            w['reset'] = bool(w.get('resets_at') and w['resets_at'] <= now)
            w['label'] = WINDOW_LABELS.get(name, name.replace('_', ' '))
            out['windows'][name] = w
        return out

    def refresh_codex(self, home: Path | None = None):
        """Read the newest Codex session log (read-only) for its last ``rate_limits``."""
        found = codex_rate_limits(home)
        if found:
            windows, observed = found
            data = self._load().get('openai') or {}
            if float(data.get('observed') or 0) < observed - 1:
                self.record('openai', windows, 'reported by OpenAI (Codex session log)')


# ------------------------------------------------------------------------------------------ parsers
def from_claude(info: dict) -> dict:
    """``rate_limit_info`` of Claude Code → windows."""
    windows = {}
    unified = info.get('unifiedWindows') if isinstance(info.get('unifiedWindows'), dict) else {}
    for name, w in unified.items():
        if isinstance(w, dict) and w.get('utilization') is not None:
            windows[name] = {'used': w.get('utilization'), 'resets_at': w.get('resetsAt'), 'status': w.get('status', ''),
                             'window_s': 5 * 3600 if name == 'five_hour' else 7 * 86400}
    if not windows and info.get('rateLimitType'):
        name = info['rateLimitType']
        windows[name] = {'used': info.get('utilization'), 'resets_at': info.get('resetsAt'),
                         'status': info.get('status', ''), 'window_s': 5 * 3600 if name == 'five_hour' else 7 * 86400}
    return windows


def from_codex(rate_limits: dict, observed: float | None = None) -> dict:
    windows = {}
    for name in ('primary', 'secondary'):
        w = rate_limits.get(name)
        if not isinstance(w, dict) or w.get('used_percent') is None:
            continue
        resets = w.get('resets_at')
        if resets is None and w.get('resets_in_seconds') is not None:
            resets = (observed or time.time()) + float(w['resets_in_seconds'])
        minutes = int(w.get('window_minutes') or (300 if name == 'primary' else 10080))
        key = 'five_hour' if minutes <= 360 else 'seven_day' if minutes >= 10000 else name
        windows[key] = {'used': float(w['used_percent']) / 100.0, 'resets_at': resets, 'window_s': minutes * 60}
    return windows


def codex_rate_limits(home: Path | None = None):
    """(windows, observed epoch) from the newest Codex rollout log, or None."""
    base = Path(home or Path.home()) / '.codex' / 'sessions'
    if not base.is_dir():
        return None
    try:
        files = sorted(base.glob('*/*/*/rollout-*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    except OSError:
        return None
    for path in files:
        try:
            size = path.stat().st_size
            with open(path, 'rb') as f:
                f.seek(max(0, size - 400_000))
                tail = f.read().decode('utf8', 'replace')
        except OSError:
            continue
        for line in reversed(tail.splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            payload = event.get('payload') if isinstance(event.get('payload'), dict) else event
            rl = payload.get('rate_limits') if isinstance(payload, dict) else None
            if isinstance(rl, dict):
                windows = from_codex(rl, path.stat().st_mtime)
                if windows:
                    return windows, path.stat().st_mtime
    return None


def _seconds(text) -> float | None:
    """'6m0s' / '1s' / '20ms' / '12' / RFC 3339 time → seconds from now."""
    if text is None:
        return None
    text = str(text).strip()
    if re.fullmatch(r'\d+(\.\d+)?', text):
        return float(text)
    if 'T' in text and '-' in text:
        try:
            import datetime as dt
            return dt.datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp() - time.time()
        except ValueError:
            return None
    total, found = 0.0, False
    for value, unit in re.findall(r'(\d+(?:\.\d+)?)(ms|h|m|s)', text):
        found = True
        total += float(value) * {'ms': 0.001, 'h': 3600, 'm': 60, 's': 1}[unit]
    return total if found else None


def from_headers(headers: dict) -> dict:
    """Rate-limit headers of an API reply → windows (requests / tokens per minute)."""
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    windows = {}
    for kind in ('requests', 'tokens'):
        for prefix in ('x-ratelimit-', 'anthropic-ratelimit-'):
            if prefix == 'x-ratelimit-':
                limit, remaining, reset = h.get(f'x-ratelimit-limit-{kind}'), h.get(f'x-ratelimit-remaining-{kind}'), \
                    h.get(f'x-ratelimit-reset-{kind}')
            else:
                limit, remaining, reset = h.get(f'anthropic-ratelimit-{kind}-limit'), \
                    h.get(f'anthropic-ratelimit-{kind}-remaining'), h.get(f'anthropic-ratelimit-{kind}-reset')
            try:
                limit_n, remaining_n = float(limit), float(remaining)
            except (TypeError, ValueError):
                continue
            secs = _seconds(reset)
            windows[kind] = {'used': (1 - remaining_n / limit_n) if limit_n else None,
                             'resets_at': time.time() + secs if secs is not None else None,
                             'limit': limit_n, 'remaining': remaining_n, 'window_s': 60}
            break
    return windows


def human_reset(resets_at: float | None, now: float | None = None) -> str:
    if not resets_at:
        return 'reset time not reported'
    left = resets_at - (now or time.time())
    if left <= 0:
        return 'has reset'
    if left < 3600:
        return f'resets in {int(left // 60)} min'
    if left < 86400:
        return f'resets in {int(left // 3600)} h {int(left % 3600 // 60):02d} min'
    return f'resets in {int(left // 86400)} d {int(left % 86400 // 3600)} h'
