"""Which agent actions run at once and which ones wait for the user (Qt-free).

One place decides for every backend: Claude Code asks through the approval MCP tool, Pi through the
SPM gate extension, the hub itself before moving a chat. ``decide()`` returns ``'allow'`` or ``'ask'``
(nothing is denied silently: what is not allowed is shown to the user, who chooses).

Rules, in order:

0. Anything that would send something away on the user's behalf — a push, a pull request or release, an
   upload, a web form post, an e-mail or chat message, an MCP tool that sends or publishes — always asks,
   **also with full access**, and can never become an "Always allow" rule (``outbound()``). E-mail from the
   hub's own mail tools goes through the outbox (``organizer.mail``), which needs the user's click as well.
1. Full access → allow everything else.
2. Reading, searching and the agent's own bookkeeping → allow.
3. Creating / changing a file inside the allowed folders → allow. The SPM Studio folders (scripts,
   customization, documents, the app) are always allowed; the user adds folders or "everywhere".
4. A shell command made only of read-only or check commands (ls, cat, git status, py_compile …) → allow.
5. An "Always allow" answer that matches → allow.
6. Everything else (other commands, git push, deleting, files elsewhere, web posts) → ask.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

READ_TOOLS = {'read', 'glob', 'grep', 'ls', 'find', 'web', 'todo', 'task', 'plan', 'notebookread'}
WRITE_TOOLS = {'edit', 'write'}
SAFE_COMMANDS = {'ls', 'cat', 'head', 'tail', 'wc', 'pwd', 'echo', 'grep', 'rg', 'find', 'file', 'stat', 'du',
                 'df', 'which', 'whoami', 'date', 'tree', 'sort', 'uniq', 'diff', 'cmp', 'basename', 'dirname',
                 'realpath', 'readlink', 'true', 'test', 'printf', 'jq', 'sha256sum', 'md5sum', 'nproc', 'uname'}
SAFE_GIT = {'status', 'diff', 'log', 'show', 'branch', 'remote', 'rev-parse', 'ls-files', 'describe', 'tag',
            'fetch', 'blame', 'config'}
SAFE_GH = {('auth', 'status'), ('repo', 'view'), ('release', 'list'), ('release', 'view'), ('pr', 'list'),
           ('pr', 'view'), ('pr', 'status'), ('run', 'list'), ('run', 'view'), ('api', 'user')}
SAFE_PYTHON_MODULES = {'py_compile', 'json.tool', 'compileall', 'pytest', 'pyflakes', 'pip'}
_SPLIT = re.compile(r'\s*(?:&&|\|\||;|\|)\s*')
_REDIRECT = re.compile(r'(?<![0-9&])>{1,2}(?!\s*/dev/null)|(?<=[0-9])>(?!&)')


_OUTBOUND_SHELL = [
    (r'\bgit\s+(?:-\S+\s+)*push\b', 'Push to a Git remote'),
    (r'\bgit\s+(?:-\S+\s+)*send-email\b', 'Send e-mail with git'),
    (r'\bgh\s+(?:pr|issue|release|repo|gist|discussion)\s+(?:create|edit|comment|merge|close|reopen|review|upload|'
     r'delete|fork|rename|archive|sync|ready)\b', 'Publish on GitHub'),
    (r'\bgh\s+api\b(?=.*(?:\s-X\s*(?:POST|PUT|PATCH|DELETE)|\s--method\s+(?:POST|PUT|PATCH|DELETE)|\s-[fF]\s|'
     r'\s--field|\s--raw-field|\s--input))', 'Change something on GitHub'),
    (r'\bcurl\b(?=.*(?:\s-X\s*(?:POST|PUT|PATCH|DELETE)|\s--request\s+(?:POST|PUT|PATCH|DELETE)|\s-d\b|\s--data|'
     r'\s-F\b|\s--form|\s-T\b|\s--upload-file|\s--json|\s--mail-rcpt|smtps?://))', 'Send data to a web server'),
    (r'\bwget\b(?=.*(?:--post-data|--post-file|--method|--body-data|--body-file))', 'Send data to a web server'),
    (r'\b(?:http|https|xh)\s+(?:POST|PUT|PATCH|DELETE)\b', 'Send data to a web server'),
    (r'(?:^|\s|;|&|\|)(?:scp|sftp|ftp|lftp|rsync)\s(?=.*\S+:\S*)', 'Copy files to another computer'),
    (r'(?:^|\s|;|&|\|)ssh\s+(?!-V)\S+', 'Connect to another computer'),
    (r'(?:^|\s|;|&|\|)(?:nc|ncat|netcat|socat|telnet)\s', 'Open a network connection'),
    (r'(?:^|\s|;|&|\|)(?:sendmail|mail|mailx|mutt|msmtp|swaks|neomutt|s-nail|xdg-email)\b', 'Send an e-mail'),
    (r'\b(?:twine\s+upload|npm\s+publish|yarn\s+publish|pnpm\s+publish|cargo\s+publish|gem\s+push|'
     r'docker\s+push|podman\s+push|poetry\s+publish|flit\s+publish|uv\s+publish)\b', 'Publish a package'),
    (r'\baws\s+s3\s+(?:cp|sync|mv)\b(?=.*s3://)', 'Upload to cloud storage'),
    (r'\b(?:gsutil|gcloud\s+storage)\s+(?:cp|rsync|mv)\b(?=.*gs://)', 'Upload to cloud storage'),
    (r'\brclone\s+(?:copy|sync|move|copyto|moveto)\b', 'Upload to cloud storage'),
    (r'\b(?:requests|httpx|urllib3?|aiohttp)\b.*\.(?:post|put|patch|delete)\s*\(', 'Send data from a script'),
    (r'\bsmtplib\b|\bSMTP\s*\(', 'Send an e-mail from a script'),
    (r'\burlopen\s*\(.*data\s*=', 'Send data from a script'),
    (r'\bInvoke-(?:WebRequest|RestMethod)\b(?=.*-Method\s+(?:Post|Put|Patch|Delete))', 'Send data to a web server'),
    (r'\bSend-MailMessage\b', 'Send an e-mail'),
]
_OUTBOUND_NAMES = re.compile(r'(?:^|[_\-.])(?:send|post|publish|upload|submit|reply|forward|share|tweet|toot|'
                             r'invite|email|mail|message|comment|create[_\-]?(?:issue|pull|pr|post|comment|message|'
                             r'release|event[_\-]?invite)|push|transfer|pay|order|purchase|book)(?:$|[_\-.]|s\b)',
                             re.I)


def outbound(tool: str, tool_input: dict) -> str:
    """Why this action would send something away on the user's behalf ('' when it would not)."""
    kind = normalize(tool)
    if kind == 'bash':
        cmd = command_text(tool_input)
        for pattern, why in _OUTBOUND_SHELL:
            if re.search(pattern, cmd, re.I | re.S):
                return why
        return ''
    if kind in ('mcp', 'unknown') or kind not in (READ_TOOLS | WRITE_TOOLS | {'internal', 'hub_move', 'hub_route',
                                                                               'bash'}):
        name = str(tool or '')
        if name.lower().startswith('mcp__spmhub__'):
            return ''
        if _OUTBOUND_NAMES.search(name.split('__')[-1]):
            return 'Send or publish with a connected tool'
    if kind == 'web':
        method = str((tool_input or {}).get('method', 'GET')).upper()
        if method not in ('GET', 'HEAD', ''):
            return 'Send data to a web server'
    return ''


def normalize(tool: str) -> str:
    """Claude Code / Pi tool names → one small vocabulary."""
    t = str(tool or '').strip()
    low = t.lower()
    if low.startswith('mcp__spmhub__'):
        return 'internal'
    if low.startswith('mcp__'):
        return 'mcp'
    return {'bash': 'bash', 'shell': 'bash', 'exec': 'bash', 'edit': 'edit', 'multiedit': 'edit',
            'notebookedit': 'edit', 'write': 'write', 'read': 'read', 'glob': 'glob', 'grep': 'grep',
            'ls': 'ls', 'find': 'find', 'webfetch': 'web', 'websearch': 'web', 'todowrite': 'todo',
            'task': 'task', 'agent': 'task', 'exitplanmode': 'plan', 'notebookread': 'notebookread',
            'hub_move': 'hub_move', 'hub_route': 'hub_route'}.get(low, low or 'unknown')


def target_path(tool_input: dict) -> str:
    for key in ('file_path', 'path', 'notebook_path', 'filePath', 'file'):
        value = (tool_input or {}).get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ''


def command_text(tool_input: dict) -> str:
    value = (tool_input or {}).get('command') or (tool_input or {}).get('cmd') or ''
    if isinstance(value, list):
        value = ' '.join(str(v) for v in value)
    return str(value)


def allowed_roots(conf: dict, app_folders: list, workspace=None) -> list[Path]:
    roots = [Path(p) for p in app_folders]
    if workspace:
        roots.append(Path(workspace))
    if conf.get('access_mode') == 'folders':
        roots += [Path(p) for p in conf.get('extra_folders', [])]
    if conf.get('access_mode') == 'everywhere':
        roots.append(Path.home())
        roots += [Path(p) for p in conf.get('extra_folders', [])]
    out = []
    for r in roots:
        try:
            r = r.expanduser().resolve()
        except OSError:
            continue
        if r not in out:
            out.append(r)
    return out


def inside(path: str, roots: list[Path], cwd=None) -> bool:
    if not path:
        return False
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = Path(cwd or os.getcwd()) / p
    try:
        p = p.resolve()
    except OSError:
        return False
    return any(p == r or r in p.parents for r in roots)


def _segment_safe(segment: str) -> bool:
    try:
        words = shlex.split(segment)
    except ValueError:
        return False
    if not words:
        return True
    while words and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', words[0]):   # FOO=bar cmd
        words = words[1:]
    if not words:
        return True
    head = Path(words[0]).name
    if head in SAFE_COMMANDS:
        return not (head == 'find' and any(w in ('-delete', '-exec', '-execdir', '-ok') for w in words))
    if head == 'cd':
        return True
    if head == 'git':
        sub = next((w for w in words[1:] if not w.startswith('-')), '')
        if sub in ('branch', 'tag', 'remote', 'config'):
            # listing only: no name to create, delete or set
            rest = [w for w in words[2:] if w != sub]
            return all(w.startswith('-') and w not in ('-d', '-D', '--delete', '-m', '-M', '--unset', '--add')
                       for w in rest) or rest in ([], ['-v'], ['--list'], ['-l'], ['get-url', 'origin'])
        return sub in SAFE_GIT
    if head == 'gh':
        pair = tuple(w for w in words[1:3])
        return pair in SAFE_GH
    if re.fullmatch(r'python[0-9.]*(\.exe)?|py', head):
        if len(words) >= 3 and words[1] == '-m':
            module = words[2]
            if module == 'pip':
                return len(words) >= 4 and words[3] in ('list', 'show', 'freeze', '--version')
            return module in SAFE_PYTHON_MODULES
        return len(words) == 2 and words[1] in ('--version', '-V')
    if head in ('node', 'npm', 'pi', 'claude', 'codex', 'ollama'):
        return len(words) == 2 and words[1] in ('--version', '-v', 'list', 'ls')
    return False


def command_safe(command: str) -> bool:
    command = str(command or '').strip()
    if not command or '\n' in command.strip() or '`' in command or '$(' in command:
        return False
    if _REDIRECT.search(command):
        return False
    return all(_segment_safe(part) for part in _SPLIT.split(command) if part.strip())


def rule_for(tool: str, tool_input: dict) -> dict | None:
    """The rule stored by "Always allow" (deliberately narrow). None for outbound actions: those always ask."""
    if outbound(tool, tool_input):
        return None
    kind = normalize(tool)
    if kind == 'bash':
        try:
            words = shlex.split(command_text(tool_input))
        except ValueError:
            words = command_text(tool_input).split()
        words = [w for w in words if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', w)]
        prefix = ' '.join(words[:2]) if len(words) >= 2 and not words[1].startswith(('/', '.', '~')) else ' '.join(words[:1])
        return {'tool': 'bash', 'prefix': prefix}
    if kind in WRITE_TOOLS:
        path = target_path(tool_input)
        folder = str(Path(os.path.expanduser(path)).resolve().parent) if path else ''
        return {'tool': 'write', 'path': folder}
    return {'tool': kind}


def rule_matches(rule: dict, tool: str, tool_input: dict) -> bool:
    if outbound(tool, tool_input):
        return False
    kind = normalize(tool)
    if rule.get('tool') == 'bash' and kind == 'bash':
        prefix = str(rule.get('prefix', '')).strip()
        if not prefix:
            return False
        segments = [s.strip() for s in _SPLIT.split(command_text(tool_input)) if s.strip()]
        return bool(segments) and all(s == prefix or s.startswith(prefix + ' ') or command_safe(s)
                                      for s in segments) and any(s == prefix or s.startswith(prefix + ' ')
                                                                 for s in segments)
    if rule.get('tool') == 'write' and kind in WRITE_TOOLS:
        folder = rule.get('path')
        return bool(folder) and inside(target_path(tool_input), [Path(folder)])
    return rule.get('tool') == kind and kind not in ('bash', 'edit', 'write')


def decide(tool: str, tool_input: dict, conf: dict, roots: list[Path], cwd=None) -> str:
    kind = normalize(tool)
    if outbound(tool, tool_input):
        return 'ask'                     # never automatic: not with full access, not with an "Always allow" rule
    if conf.get('full_access'):
        return 'allow'
    if kind in READ_TOOLS or kind == 'internal':
        return 'allow'
    if kind == 'hub_move':
        return 'allow' if conf.get('auto_sort') == 'auto' else 'ask'
    if kind in WRITE_TOOLS and inside(target_path(tool_input), roots, cwd):
        return 'allow'
    if kind == 'bash' and command_safe(command_text(tool_input)):
        return 'allow'
    if any(rule_matches(r, tool, tool_input) for r in conf.get('always_rules', [])):
        return 'allow'
    return 'ask'


def describe(tool: str, tool_input: dict) -> tuple[str, str]:
    """(title, detail) shown on the approval card."""
    kind = normalize(tool)
    if kind == 'bash':
        cmd = command_text(tool_input)
        title = 'Run a command'
        why = outbound(tool, tool_input)
        if re.search(r'\bgit\s+push\b', cmd):
            title = 'Push to GitHub'
        elif re.search(r'\bgh\s+release\s+create\b', cmd):
            title = 'Publish a GitHub release'
        elif re.search(r'\bgh\s+pr\s+create\b', cmd):
            title = 'Open a pull request'
        elif why:
            title = why
        elif re.search(r'(^|\s)(rm|rmdir|unlink|del)\s', ' ' + cmd):
            title = 'Delete files'
        return title, cmd[:1500]
    if kind == 'write':
        return 'Create or overwrite a file', target_path(tool_input)
    if kind == 'edit':
        return 'Change a file', target_path(tool_input)
    if kind == 'hub_move':
        return 'Move this chat', str((tool_input or {}).get('project_name', ''))
    if kind == 'mcp':
        why = outbound(tool, tool_input)
        detail = str(tool) + ('\n' + ', '.join(f'{k}: {str(v)[:200]}' for k, v in list((tool_input or {}).items())[:6])
                              if tool_input else '')
        return (why or 'Use a connected tool'), detail
    text = ', '.join(f'{k}: {str(v)[:80]}' for k, v in list((tool_input or {}).items())[:4])
    return f'Use {tool}', text
