"""Claude Code and OpenAI Codex CLI as assistant backends — Qt-free part.

Both agents are used through their documented non-interactive modes and their
own sign-in (Claude Pro/Max/Team or Anthropic Console account for Claude Code;
ChatGPT account or API key for Codex). SPM Studio never reads their tokens.

* Claude Code: ``claude -p --output-format stream-json --verbose
  --include-partial-messages [--resume <session_id>] --permission-mode <mode>``;
  the prompt is written to stdin. Events: ``system/init`` (session_id, model),
  ``stream_event`` (text deltas), ``assistant`` (full message), ``result``.
* Codex: ``codex exec --json --skip-git-repo-check --sandbox <mode> -`` and
  ``codex exec resume <thread_id> --json … -`` for follow-ups; the prompt is
  read from stdin (``-``). Events: ``thread.started`` (thread_id),
  ``item.started``/``item.completed`` (agent_message, command_execution, …),
  ``turn.completed``, ``turn.failed``, ``error``.
"""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

from . import platform_util as pu

AGENTS = {
    'claude-code': {'label': 'Claude Code', 'exe': 'claude',
                    'login': [], 'login_hint': 'Claude Code opens; follow its sign-in (type /login if asked), then /exit.',
                    'install_unix': 'curl -fsSL https://claude.ai/install.sh | bash',
                    'install_windows': 'irm https://claude.ai/install.ps1 | iex',
                    'docs': 'https://docs.claude.com/en/docs/claude-code/setup'},
    'codex': {'label': 'OpenAI Codex CLI', 'exe': 'codex',
              'login': ['login'], 'login_hint': 'Your browser opens to sign in with ChatGPT (or use an API key).',
              'npm': '@openai/codex',
              'docs': 'https://developers.openai.com/codex/cli'},
}


def detect(agent: str) -> str:
    """Path of the agent CLI if installed (PATH, usual per-user locations, SPM runtime)."""
    meta = AGENTS[agent]
    found = shutil.which(meta['exe'])
    if found:
        return found
    home = Path.home()
    names = [meta['exe'] + ('.exe' if pu.IS_WINDOWS else '')]
    if pu.IS_WINDOWS:
        names.append(meta['exe'] + '.cmd')
    folders = [home / '.local' / 'bin', home / '.claude' / 'local', home / '.npm-global' / 'bin']
    if pu.IS_WINDOWS:
        import os
        folders += [Path(os.environ.get('APPDATA', home)) / 'npm', home / '.local' / 'bin']
    from .pi_setup import runtime_dir
    folders.append(runtime_dir() / 'node_modules' / '.bin')
    for folder in folders:
        for name in names:
            p = folder / name
            if p.is_file():
                return str(p)
    return ''


def version(executable: str) -> str:
    try:
        program, prefix = pu.resolve_command(executable)
        r = subprocess.run([program, *prefix, '--version'], capture_output=True, text=True, timeout=20,
                           env=pu.command_env(), **pu.hidden_window())
        return (r.stdout or r.stderr).strip().splitlines()[0][:80] if (r.stdout or r.stderr).strip() else ''
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return ''


def build_args(agent: str, session: str, tools: bool, system_text: str = '',
               allowed_tools=()) -> list[str]:
    if agent == 'claude-code':
        args = ['-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
                # plan = read-only analysis; acceptEdits = may write files in its working folder
                '--permission-mode', 'acceptEdits' if tools else 'plan']
        if allowed_tools:
            # v0.0.5: the read-only literature servers (Consensus, Zotero) the user connected in
            # Settings › Literature may be called without a prompt; a non-interactive turn cannot ask.
            args += ['--allowedTools', ','.join(allowed_tools)]
        if session:
            args += ['--resume', session]
        if system_text:
            args += ['--append-system-prompt', system_text]
        return args
    if agent == 'codex':
        sandbox = 'workspace-write' if tools else 'read-only'
        if session:
            return ['exec', 'resume', session, '--json', '--skip-git-repo-check',
                    '-c', f'sandbox_mode="{sandbox}"', '-']
        return ['exec', '--json', '--skip-git-repo-check', '--sandbox', sandbox, '-']
    raise ValueError('Unknown agent ' + agent)


class CliEvents:
    """Reduce one agent's JSON lines to (kind, value): text · replace · log · activity ·
    error · done · model · session."""
    def __init__(self, agent: str):
        self.agent = agent
        self.streamed = False
        self.any_text = False

    def interpret(self, event: dict):
        out = self._claude(event) if self.agent == 'claude-code' else self._codex(event)
        if any(k == 'text' and v.strip() for k, v in out):
            self.any_text = True
        return out

    def _claude(self, e):
        typ = e.get('type')
        if typ == 'system' and e.get('subtype') == 'init':
            out = [('session', str(e.get('session_id', '')))]
            if e.get('model'):
                out.append(('model', str(e['model'])))
            return out
        if typ == 'stream_event':
            ev = e.get('event') or {}
            delta = ev.get('delta') or {}
            if ev.get('type') == 'content_block_delta' and delta.get('type') == 'text_delta':
                self.streamed = True
                return [('text', str(delta.get('text', '')))]
            return []
        if typ == 'assistant':
            out = []
            for part in ((e.get('message') or {}).get('content') or []):
                if part.get('type') == 'tool_use':
                    out.append(('activity', 'Running tool: ' + str(part.get('name', 'tool'))))
                elif part.get('type') == 'text' and not self.streamed:
                    out.append(('text', str(part.get('text', ''))))
            if self.streamed:
                out.append(('text', '\n\n'))          # message boundary between tool rounds
            return out
        if typ == 'result':
            out = [('session', str(e.get('session_id', '')))] if e.get('session_id') else []
            if e.get('is_error') or e.get('subtype') not in (None, 'success'):
                out.append(('error', str(e.get('result') or e.get('subtype') or 'Claude Code error')))
            elif not self.any_text and e.get('result'):
                out.append(('replace', str(e['result'])))
            out.append(('done', 'result'))
            return out
        return []

    def _codex(self, e):
        typ = e.get('type')
        if typ == 'thread.started':
            return [('session', str(e.get('thread_id', '')))]
        if typ in ('item.started', 'item.completed'):
            item = e.get('item') or {}
            kind = item.get('type') or item.get('item_type')
            if typ == 'item.completed' and kind in ('agent_message', 'assistant_message'):
                text = str(item.get('text', ''))
                piece = ('\n\n' + text) if self.streamed else text
                self.streamed = True
                return [('text', piece)]
            if typ == 'item.started' and kind == 'command_execution':
                return [('activity', 'Running tool: ' + str(item.get('command', 'command'))[:80])]
            if typ == 'item.completed' and kind == 'file_change':
                return [('log', 'Codex changed files')]
            if typ == 'item.completed' and kind == 'error':
                return [('log', 'Codex: ' + str(item.get('message', '')))]
            return []
        if typ == 'turn.completed':
            return [('done', 'turn.completed')]
        if typ == 'turn.failed':
            err = e.get('error') or {}
            return [('error', str(err.get('message') if isinstance(err, dict) else err) or 'Codex turn failed'),
                    ('done', 'turn.failed')]
        if typ == 'error':
            return [('error', str(e.get('message') or 'Codex error'))]
        return []
