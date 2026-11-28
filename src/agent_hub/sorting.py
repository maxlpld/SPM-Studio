"""Suggest the project a new chat belongs to (Qt-free, offline, instant).

Keyword scores per project (built-in keywords + the user's own + words of the project name). A suggestion is
made only when one project clearly wins, so ordinary questions stay where they are.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[a-zà-ÿ0-9_.\-']+", re.I)


def _keywords(project: dict) -> list[str]:
    words = [k.lower() for k in project.get('keywords', []) if k]
    for w in _WORD.findall(project.get('name', '').lower()):
        if len(w) > 3 and w not in ('with', 'and', 'the', 'pour', 'avec', 'app'):
            words.append(w)
    return list(dict.fromkeys(words))


def score(text: str, project: dict) -> tuple[float, list[str]]:
    low = ' ' + re.sub(r'\s+', ' ', str(text or '').lower()) + ' '
    hits, total = [], 0.0
    for kw in _keywords(project):
        if ' ' in kw or '.' in kw or kw.endswith("'"):
            found = kw in low
        elif kw.endswith(('is', 'ali')) or len(kw) >= 8:       # stems such as "personnalis"
            found = re.search(r'(?<![a-zà-ÿ])' + re.escape(kw), low) is not None
        else:
            found = re.search(r'(?<![a-zà-ÿ])' + re.escape(kw) + r's?(?![a-zà-ÿ])', low) is not None
        if found:
            hits.append(kw)
            total += 1.5 if (' ' in kw or len(kw) >= 7) else 1.0
    return total, hits


def suggest(text: str, projects: list[dict], current: str = '') -> dict | None:
    """``{'project': id, 'name': ..., 'score': s, 'hits': [...]}`` or ``None``."""
    ranked = []
    for p in projects:
        s, hits = score(text, p)
        if s > 0:
            ranked.append((s, p, hits))
    if not ranked:
        return None
    ranked.sort(key=lambda r: r[0], reverse=True)
    best, project, hits = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    if best < 1.5 or best - runner_up < 1.0 or project['id'] == current:
        return None
    return {'project': project['id'], 'name': project['name'], 'score': best, 'hits': hits[:5]}
