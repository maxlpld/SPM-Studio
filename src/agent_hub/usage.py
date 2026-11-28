"""Usage accounting (Qt-free) — honest by construction.

Every finished turn appends one line to ``usage.jsonl``: account group, account label, backend, model, the
token counts **reported by the agent or provider** (``source`` says by whom) or, when nothing was reported,
a character-based estimate marked ``estimated``. Nothing here asks a provider for anything, so monitoring costs
no AI request and no tokens.

What this module can *not* know, and therefore never shows as a number:

* the account-wide quota of a subscription (Claude Pro/Max, ChatGPT Plus/Pro …): usage on the website, other
  devices and other tools is invisible here, and the providers expose no supported quota API to these CLIs;
* reset times of five-hour or weekly windows;
* remaining tokens of a subscription (subscriptions are not metered in tokens for the user).

``summary()`` returns those as ``None`` with a reason, which the UI shows as “Not available from provider”.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

WINDOW_5H = 5 * 3600
WINDOW_WEEK = 7 * 24 * 3600
UNAVAILABLE = 'Not available from provider'
OFFICIAL_PAGES = {  # where the user can read the provider's own figures
    'api:openai': 'https://platform.openai.com/usage',
    'api:anthropic': 'https://console.anthropic.com/settings/usage',
    'api:openrouter': 'https://openrouter.ai/activity',
}


def estimate_tokens(text: str) -> int:
    """≈ 4 characters per token (marked as an estimate wherever shown)."""
    return max(0, round(len(text or '') / 4))


class Ledger:
    def __init__(self, root: Path):
        self.path = Path(root) / 'usage.jsonl'

    def record(self, *, chat: str, project: str, backend: str, group: str, account: str, model: str,
               usage: dict | None, prompt_text: str = '', reply_text: str = '', duration_s: float | None = None,
               mode: str = 'normal', stats: dict | None = None) -> dict:
        usage = dict(usage or {})
        if usage.get('input_tokens') or usage.get('output_tokens'):
            entry_usage = {k: usage.get(k) for k in ('input_tokens', 'output_tokens', 'cached_tokens',
                                                     'cache_write_tokens', 'cost_usd') if usage.get(k) is not None}
            source = usage.get('source') or 'reported'
            estimated = False
        else:
            entry_usage = {'input_tokens': estimate_tokens(prompt_text), 'output_tokens': estimate_tokens(reply_text)}
            source = 'estimated from text length'
            estimated = True
        entry = {'ts': round(time.time(), 1), 'chat': chat, 'project': project, 'backend': backend,
                 'group': group, 'account': account, 'model': model, 'mode': mode, 'duration_s': duration_s,
                 'source': source, 'estimated': estimated, **entry_usage}
        if stats:
            entry['stats'] = {k: v for k, v in stats.items() if k in ('tokens_per_s', 'ttft_s', 'total_s')}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'a', encoding='utf8') as f:
            f.write(json.dumps(entry) + '\n')
        return entry

    def entries(self, since: float = 0.0) -> list[dict]:
        out = []
        try:
            with open(self.path, encoding='utf8') as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict) and e.get('ts', 0) >= since:
                        out.append(e)
        except OSError:
            pass
        return out

    def chat_tokens(self, chat_id: str, mode: str | None = None) -> int:
        return sum(int(e.get('input_tokens') or 0) + int(e.get('output_tokens') or 0)
                   for e in self.entries() if e.get('chat') == chat_id and (mode is None or e.get('mode') == mode))

    def summary(self, now: float | None = None) -> list[dict]:
        """One row per (group, account): locally observed usage in the last 5 h / 7 days, how much of it was
        reported vs estimated, cost when reported — and the quota fields as unavailable."""
        now = now or time.time()
        rows: dict[tuple, dict] = {}
        for e in self.entries(now - WINDOW_WEEK):
            key = (e.get('group', ''), e.get('account') or e.get('backend', ''))
            r = rows.setdefault(key, {'group': key[0], 'account': key[1], 'models': set(), 'turns_5h': 0,
                                      'tokens_5h': 0, 'tokens_week': 0, 'turns_week': 0, 'estimated_share': 0,
                                      'cost_usd_week': None, 'quota': None, 'reset': None,
                                      'quota_reason': UNAVAILABLE})
            tokens = int(e.get('input_tokens') or 0) + int(e.get('output_tokens') or 0)
            r['models'].add(e.get('model') or '?')
            r['turns_week'] += 1
            r['tokens_week'] += tokens
            r['estimated_share'] += tokens if e.get('estimated') else 0
            if e.get('cost_usd') is not None:
                r['cost_usd_week'] = round((r['cost_usd_week'] or 0) + float(e['cost_usd']), 4)
            if e.get('ts', 0) >= now - WINDOW_5H:
                r['turns_5h'] += 1
                r['tokens_5h'] += tokens
        out = []
        for r in rows.values():
            r['models'] = sorted(r['models'])
            r['estimated'] = r['estimated_share'] > 0
            r['estimated_share'] = round(r['estimated_share'] / r['tokens_week'], 2) if r['tokens_week'] else 0
            r['official_page'] = OFFICIAL_PAGES.get(f"api:{r['account']}", '')
            out.append(r)
        out.sort(key=lambda r: -r['tokens_week'])
        return out


def human(n: int | None) -> str:
    if n is None:
        return UNAVAILABLE
    if n >= 1_000_000:
        return f'{n / 1e6:.1f}M'
    if n >= 1000:
        return f'{n / 1000:.1f}k'
    return str(n)
