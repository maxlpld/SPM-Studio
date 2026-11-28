"""Brainstorming mode (Qt-free): refine an idea cheaply before any expensive execution.

The restrictions are enforced by the engine, not only asked of the model:

* ``tool_decision()`` — in a brainstorming chat every tool call that could change something is **denied**
  (writes, edits, commands, pushes, installs, sub-agents, connected tools). Reading/searching is allowed only
  when the user enabled "bounded read-only research" for brainstorming, and then at most ``max_tool_calls``.
* ``agent_flags()`` — agents run read-only: Claude Code ``--permission-mode plan``, Codex sandbox
  ``read-only``, Pi with the approval gate (and the denials above).
* ``choose_backend()`` — economical first: a conversational local model, then a cheap API connection, then an
  agent in read-only mode; never an escalation the user did not choose.
* a token budget per brainstorming chat (reported tokens, or estimates when nothing is reported).

``final_prompt_request()`` builds the message that turns the session into an implementation prompt; the
reply is shown for editing and is never executed automatically.
"""
from __future__ import annotations

from . import policy

READ_ONLY = {'read', 'glob', 'grep', 'ls', 'find', 'web', 'notebookread', 'todo'}

INSTRUCTIONS = """## Brainstorming mode (economical, no execution)
You are helping the user refine an idea BEFORE any implementation. In this mode:
- Do not write or change files, run commands, install anything, push, release, send messages or start
  sub-agents: those tools are blocked by the application. Do not try them.
- Discuss goals, alternatives, constraints, architecture and trade-offs; ask the few clarifying questions that
  matter most; point out missing requirements and technical limits.
- Keep answers concise. After each answer, maintain a short running specification in this exact format:

<spec>
Objective: …
Decisions: - …
Constraints / preserve: - …
Open questions: - …
</spec>

- When more capable models or research are needed, say why and let the user decide; never assume it."""

FINAL_PROMPT_REQUEST = """[Generate final prompt]
Write the complete implementation prompt for this brainstorming session, ready to give to a coding agent.
Use Markdown with these sections:
1. Project context
2. Objective and scope
3. Existing functionality to preserve
4. Requirements and constraints
5. Agreed technical decisions
6. Assumptions (marked as such)
7. Unresolved questions (clearly marked; do not invent answers)
8. Deliverables
9. Acceptance criteria and tests
10. Release and rollback instructions (if applicable)
Use only what was agreed in this conversation and the running specification. Output only the prompt."""


def tool_decision(tool: str, conf: dict, calls_so_far: int) -> tuple[str, str]:
    """('allow' | 'deny', reason) for a tool call in a brainstorming chat."""
    kind = policy.normalize(tool)
    if kind == 'internal':
        return 'allow', ''
    if kind in READ_ONLY and conf.get('brainstorm_research', False):
        limit = int(conf.get('brainstorm_max_tool_calls', 12))
        if calls_so_far < limit:
            return 'allow', ''
        return 'deny', f'Brainstorming research budget reached ({limit} read-only tool calls).'
    if kind in READ_ONLY:
        return 'deny', ('Brainstorming mode: research is off. Enable "bounded read-only research" in '
                        'Settings › Brainstorming to let the assistant read files or the web.')
    return 'deny', 'Brainstorming mode: execution is blocked. Generate the final prompt, then Start execution.'


def agent_flags(kind: str) -> dict:
    return {'claude-code': {'permission_mode': 'plan'}, 'codex': {'sandbox': 'read-only'},
            'pi': {'gate': True}}.get(kind, {})


def choose_backend(backends: list[dict], conf: dict, running: dict | None = None) -> str:
    """Key of the economical model for brainstorming ('' if nothing is set up)."""
    from .scheduler import capacity
    running = running or {}
    wanted = conf.get('brainstorm_backend', 'auto')
    if wanted != 'auto' and any(b['key'] == wanted for b in backends):
        return wanted
    profile = conf.get('routing_profile', 'balanced')
    pool = [b for b in backends if b['group'] == 'local'] if profile == 'local' else list(backends)
    judge = str((conf.get('judge_model') or '')).lower()
    local = sorted([b for b in pool if b['kind'] in ('ollama', 'api') and b['group'] == 'local'
                    and b.get('model', '').lower() != judge], key=lambda b: -b.get('size', 0))
    # the Judge-size model (≤1B) is for classification, not conversation
    local = [b for b in local if not any(t in b.get('model', '').lower() for t in (':0.5b', ':0.6b', ':0.8b', ':1b'))] \
        or local
    cheap_api = [b for b in pool if b['kind'] == 'api' and b['group'] != 'local']
    agents = [b for b in pool if b['tools']]
    for b in local + cheap_api + agents:
        if capacity(b, running, conf) > 0:
            return b['key']
    return (local + cheap_api + agents or [{'key': ''}])[0]['key']


def final_prompt_request() -> str:
    return FINAL_PROMPT_REQUEST


def latest_spec(messages: list[dict]) -> str:
    """The last ``<spec>…</spec>`` block the assistant wrote ('' if none)."""
    import re
    for m in reversed(messages):
        if m.get('role') == 'assistant':
            found = re.findall(r'<spec>(.*?)</spec>', m.get('content', ''), re.S)
            if found:
                return found[-1].strip()
    return ''


def strip_spec(text: str) -> str:
    import re
    return re.sub(r'\s*<spec>.*?</spec>\s*', '\n', text or '', flags=re.S).strip()
