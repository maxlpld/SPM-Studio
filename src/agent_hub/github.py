"""GitHub for the agent, through the official GitHub CLI (``gh``) — Qt-free.

Each user signs in with *their own* GitHub account (``gh auth login`` in a terminal, browser sign-in). The
token stays in gh's own secure storage; Agent Hub never reads it. GitHub itself decides what the account may
do: you can push and publish releases on your repositories; someone else signed in with their account can
only push to theirs, and for a repository they cannot write to the agent forks it and opens a pull request.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def gh_path() -> str:
    found = shutil.which('gh')
    if found:
        return found
    home = Path.home()
    for p in (home / '.local/bin/gh', Path('/usr/local/bin/gh'), Path('/opt/homebrew/bin/gh'),
              Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'GitHub CLI' / 'gh.exe'):
        if p.is_file():
            return str(p)
    return ''


def _run(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    exe = gh_path()
    if not exe:
        raise FileNotFoundError('GitHub CLI (gh) is not installed')
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = 0x08000000          # no console window
    env = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, env=env,
                          stdin=subprocess.DEVNULL, **kwargs)


def status() -> dict:
    """``{'installed': bool, 'login': str, 'error': str}`` (never a token)."""
    if not gh_path():
        return {'installed': False, 'login': '', 'error': ''}
    try:
        r = _run(['api', 'user', '--jq', '.login'])
    except (OSError, subprocess.SubprocessError) as exc:
        return {'installed': True, 'login': '', 'error': str(exc)[:200]}
    if r.returncode == 0 and r.stdout.strip():
        return {'installed': True, 'login': r.stdout.strip().splitlines()[0][:60], 'error': ''}
    return {'installed': True, 'login': '', 'error': (r.stderr or r.stdout).strip()[:200]}


def can_push(repo: str) -> bool | None:
    """True / False from GitHub for ``owner/name``; None when it cannot be checked."""
    if not repo or repo.count('/') != 1:
        return None
    try:
        r = _run(['api', f'repos/{repo}', '--jq', '.permissions.push'])
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() == 'true'


def install_hint() -> str:
    if os.name == 'nt':
        return 'winget install --id GitHub.cli'
    if shutil.which('brew'):
        return 'brew install gh'
    if shutil.which('apt'):
        return 'sudo apt install gh'
    return 'See https://cli.github.com for the installer'


def sign_in_script(folder: Path, sign_out: bool = False) -> Path:
    """A small visible script for a terminal: browser sign-in (or sign-out) with gh."""
    from .agents import platform_util as pu
    exe = gh_path() or 'gh'
    if sign_out:
        argv = [exe, 'auth', 'logout', '--hostname', 'github.com']
        banner = 'Agent Hub — sign out of GitHub\n\nConfirm below. Close this window when it is done.\n'
    else:
        argv = [exe, 'auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web']
        banner = ('Agent Hub — sign in to GitHub for the assistant\n\n'
                  'Copy the one-time code shown below, press Enter: your browser opens.\n'
                  'Sign in with YOUR GitHub account and paste the code.\n'
                  'git then uses this sign-in too (gh auth setup-git).\n'
                  'Close this window when it says "Logged in".\n')
    script = pu.write_terminal_script(folder, 'github-sign-out' if sign_out else 'github-sign-in', {}, argv, banner)
    if not sign_out:
        try:
            newline = '\r\n' if os.name == 'nt' else '\n'
            lines = script.read_text(encoding='utf8').split(newline)
            at = next(i for i, ln in enumerate(lines) if 'auth' in ln and 'login' in ln)
            import shlex
            setup = (f'"{exe}" auth setup-git' if os.name == 'nt'
                     else f'{shlex.quote(exe)} auth setup-git')
            lines.insert(at + 1, setup)
            script.write_text(newline.join(lines), encoding='utf8')
        except (OSError, StopIteration):
            pass
    return script


def agent_context(login: str) -> str:
    if not gh_path():
        return ('## GitHub\nThe GitHub CLI (gh) is not installed. If the user asks for GitHub work, tell them to '
                'install it and sign in from Agent Hub › Settings › Connections › GitHub.')
    if not login:
        return ('## GitHub\nGitHub CLI installed but not signed in. For GitHub work ask the user to sign in '
                '(Agent Hub › Settings › Connections › GitHub › Sign in).')
    return f"""## GitHub (signed in as `{login}` through the GitHub CLI)
- Use `git` and `gh` for GitHub work. Pushes, releases and pull requests are shown to the user for approval
  unless full access is on.
- Before pushing to `owner/repo`, check `gh api repos/owner/repo --jq .permissions.push`.
  * `true` (the user's own repositories, or ones they were invited to): you may push a branch, open a pull
    request (`gh pr create`) and publish a release (`gh release create vX.Y.Z --notes ...`).
  * `false`: do NOT try to push there. Fork it (`gh repo fork owner/repo --clone=false`), push the branch to
    `{login}/repo` and open a pull request to the original (`gh pr create --repo owner/repo --head {login}:branch`).
- Never change repository visibility, ownership, collaborators, branch protection or secrets, never force-push
  to a default branch, and never commit API keys, tokens or private files.
- Private repositories stay private: say clearly which repository (public or private) you push to."""
