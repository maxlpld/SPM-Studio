"""Update check and installer launch from the project's GitHub repository.

Source of truth: GitHub Releases of ``update_config.json → repository``
(``owner/name``); if the project publishes only tags, the newest version tag
and the matching ``CHANGELOG.md`` sections are used instead.

* ``check()`` returns the newest version, whether it is newer than the
  running one, and the release notes of every version in between.
* ``prepare()`` downloads the source archive of that version (HTTPS from
  github.com), extracts it safely and returns the folder with the installer.
* ``installer_argv()`` is the same per-OS installer a fresh install uses:
  a new isolated release is built and self-tested next to the current one,
  so a failed update never breaks the working version.

Command line (also ``spm-studio --check-update`` / ``spm-studio --update``):
    python -m spm_studio.core.updates --check
    python -m spm_studio.core.updates --update [--yes]

Network use: one request to api.github.com per check, only when the user
presses *Check for updates* or (if enabled) at most once a day at startup.
Nothing about the user or their data is sent.

Private repositories: a read-only credential is taken, in this order, from
``SPM_STUDIO_GITHUB_TOKEN``, ``GH_TOKEN``, ``GITHUB_TOKEN`` or the GitHub CLI
(``gh auth token``, i.e. the sign-in made once with ``gh auth login``, which
the CLI keeps in the operating system's credential store). SPM Studio never
writes the credential anywhere, sends it only to the GitHub API, and drops it
when GitHub redirects a download to another host. Public repositories need
no credential. ``SPM_STUDIO_USE_GH_CLI=0`` disables the GitHub CLI lookup.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

CONFIG_FILE = Path(__file__).resolve().parents[1] / 'update_config.json'
API = os.environ.get('SPM_STUDIO_UPDATE_API', 'https://api.github.com')
RAW = os.environ.get('SPM_STUDIO_UPDATE_RAW', 'https://raw.githubusercontent.com')
PLACEHOLDER = 'YOUR_GITHUB_USER/SPM-Studio'
TOKEN_ENV = ('SPM_STUDIO_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN')
PRIVATE_HINT = ('If the repository is private, sign in once with the GitHub CLI (`gh auth login`) '
                'or set SPM_STUDIO_GITHUB_TOKEN to a read-only token; see README › Private repository.')


class UpdateError(RuntimeError):
    pass


# ------------------------------------------------------------------ config & versions
def config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf8'))
    except (OSError, ValueError):
        data = {}
    repo = os.environ.get('SPM_STUDIO_UPDATE_REPO') or data.get('repository') or PLACEHOLDER
    return {'repository': repo, 'branch': data.get('branch', 'main'),
            'include_prereleases': bool(data.get('include_prereleases', False))}


def repository() -> str:
    repo = config()['repository']
    if repo == PLACEHOLDER or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise UpdateError('No GitHub repository is configured for updates yet '
                          '(src/spm_studio/update_config.json).')
    return repo


def current_version() -> str:
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version('spm-studio')
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    toml = Path(__file__).resolve().parents[3] / 'pyproject.toml'
    m = re.search(r'^version = "(.+)"', toml.read_text(encoding='utf8'), re.M) if toml.is_file() else None
    return m.group(1) if m else '0.0.0'


def parse(v: str) -> tuple:
    """'v0.8.10' → (0, 8, 10, 1); pre-releases ('0.9.0rc1', '0.9.0-beta') sort before the release."""
    m = re.match(r'^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$', str(v or ''))
    if not m:
        return (0, 0, 0, 0)
    major, minor, patch, rest = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), m.group(4).strip()
    return (major, minor, patch, 0 if rest else 1)


def is_version_tag(name: str) -> bool:
    return bool(re.fullmatch(r'v?\d+\.\d+(\.\d+)?([-.]?(a|b|rc|alpha|beta|dev)\.?\d*)?', name or ''))


# ------------------------------------------------------------------ credentials (private repositories)
_GH_CLI_TOKEN: list = []          # per-process cache of `gh auth token`; never written to disk


def _gh_cli_token() -> str:
    if os.environ.get('SPM_STUDIO_USE_GH_CLI', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return ''
    if _GH_CLI_TOKEN:
        return _GH_CLI_TOKEN[0]
    token = ''
    gh = shutil.which('gh')
    if gh:
        try:
            r = subprocess.run([gh, 'auth', 'token', '--hostname', 'github.com'], capture_output=True,
                               text=True, timeout=10, stdin=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if r.returncode == 0:
                token = r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            token = ''
    _GH_CLI_TOKEN.append(token)
    return token


def github_token() -> str:
    """Credential for a private repository, or '' (public repositories need none)."""
    for var in TOKEN_ENV:
        value = os.environ.get(var, '').strip()
        if value:
            return value
    return _gh_cli_token()


class _StripAuthOnRedirect(HTTPRedirectHandler):
    """GitHub answers archive requests with a redirect to a signed download URL on another host:
    never forward the credential there."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            for name in [k for k in new.headers if k.lower() == 'authorization']:
                del new.headers[name]
            new.unredirected_hdrs.pop('Authorization', None)
        return new


# ------------------------------------------------------------------ http
def _ssl():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get(url: str, timeout: float = 15, accept: str = 'application/vnd.github+json') -> bytes:
    headers = {'Accept': accept, 'User-Agent': 'SPM-Studio-updater'}
    token = github_token() if url.startswith(API) else ''   # only ever sent to the GitHub API
    if token:
        headers['Authorization'] = 'Bearer ' + token
    handlers = [_StripAuthOnRedirect()]
    if url.startswith('https://'):
        handlers.append(HTTPSHandler(context=_ssl()))
    try:
        with build_opener(*handlers).open(Request(url, headers=headers), timeout=timeout) as r:
            return r.read()
    except HTTPError as exc:
        if exc.code == 404:
            raise FileNotFoundError(url) from exc
        if exc.code == 401:
            raise UpdateError('GitHub rejected the sign-in (expired or invalid token). Run `gh auth login` '
                              'again or replace SPM_STUDIO_GITHUB_TOKEN.') from exc
        if exc.code == 403 and 'rate limit' in exc.read().decode('utf8', 'replace').lower():
            raise UpdateError('GitHub rate limit reached; try again in an hour.') from exc
        raise UpdateError(f'GitHub answered HTTP {exc.code}') from exc
    except OSError as exc:
        raise UpdateError(f'Cannot reach GitHub ({exc}). Check the internet connection.') from exc


def _json(url: str):
    return json.loads(_get(url).decode('utf8'))


# ------------------------------------------------------------------ changelog
def changelog_sections(text: str) -> list[tuple[str, str]]:
    """[(version, markdown body)] from '## 0.8.2 — date' style headings."""
    out, current, body = [], None, []
    for line in (text or '').splitlines():
        m = re.match(r'^##\s+\[?v?(\d+\.\d+(?:\.\d+)?[^\]\s]*)\]?', line)
        if m:
            if current:
                out.append((current, '\n'.join(body).strip()))
            current, body = m.group(1), []
        elif current:
            body.append(line)
    if current:
        out.append((current, '\n'.join(body).strip()))
    return out


# ------------------------------------------------------------------ check
def check(current: str | None = None, timeout: float = 15) -> dict:
    """Newest available version and notes for everything newer than ``current``."""
    repo = repository()
    current = current or current_version()
    allow_pre = config()['include_prereleases']
    releases = []
    try:
        for rel in _json(f'{API}/repos/{repo}/releases?per_page=30'):
            if rel.get('draft') or (rel.get('prerelease') and not allow_pre):
                continue
            tag = rel.get('tag_name', '')
            if not is_version_tag(tag):
                continue
            releases.append({'version': tag.lstrip('v'), 'tag': tag, 'notes': (rel.get('body') or '').strip(),
                             'url': rel.get('html_url', ''), 'published': (rel.get('published_at') or '')[:10]})
    except FileNotFoundError:
        if github_token():
            raise UpdateError(f'Repository {repo} not found, or your GitHub account has no access to it.')
        raise UpdateError(f'Repository {repo} not found. ' + PRIVATE_HINT)
    source = 'releases'
    if not releases:                                        # project publishes tags only
        source = 'tags'
        tags = [t.get('name', '') for t in _json(f'{API}/repos/{repo}/tags?per_page=100')]
        tags = [t for t in tags if is_version_tag(t) and (allow_pre or parse(t)[3] == 1)]
        if not tags:
            return {'repository': repo, 'current': current, 'latest': None, 'update': False, 'notes': [],
                    'source': source, 'message': 'No published version yet.'}
        tag = max(tags, key=parse)
        notes = {}
        try:
            if github_token():          # private: raw.githubusercontent.com would need the token too
                url, accept = f'{API}/repos/{repo}/contents/CHANGELOG.md?ref={tag}', 'application/vnd.github.raw'
            else:
                url, accept = f'{RAW}/{repo}/{tag}/CHANGELOG.md', 'text/plain'
            text = _get(url, accept=accept).decode('utf8', 'replace')
            notes = dict(changelog_sections(text))
        except (FileNotFoundError, UpdateError):
            pass
        for t in tags:
            v = t.lstrip('v')
            releases.append({'version': v, 'tag': t, 'notes': notes.get(v, ''), 'published': '',
                             'url': f'https://github.com/{repo}/releases/tag/{t}'})
    releases.sort(key=lambda r: parse(r['version']), reverse=True)
    latest = releases[0]
    newer = [r for r in releases if parse(r['version']) > parse(current)]
    return {'repository': repo, 'current': current, 'latest': latest['version'], 'tag': latest['tag'],
            'update': bool(newer), 'notes': newer, 'url': latest['url'], 'source': source,
            'authenticated': bool(github_token()), 'archive': archive_url(repo, latest['tag'])}


def archive_url(repo: str, tag: str) -> str:
    """Source archive of a tag. Private repositories go through the authenticated API endpoint."""
    if github_token():
        return f'{API}/repos/{repo}/zipball/{tag}'
    return f'https://github.com/{repo}/archive/refs/tags/{tag}.zip'


def notes_markdown(result: dict) -> str:
    parts = []
    for r in result.get('notes', []):
        head = f"## {r['version']}" + (f" — {r['published']}" if r.get('published') else '')
        parts.append(head + '\n\n' + (r['notes'] or '_No release notes._'))
    return '\n\n'.join(parts)


# ------------------------------------------------------------------ state (daily auto-check)
def _state_path() -> Path:
    from spm_studio.core import paths
    return paths.config_dir() / 'updates.json'


def load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding='utf8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(**changes) -> dict:
    data = load_state()
    data.update(changes)
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding='utf8')
    return data


def auto_check_due(interval_s: int = 86400) -> bool:
    s = load_state()
    return bool(s.get('auto_check', True)) and time.time() - float(s.get('last_check', 0)) > interval_s


# ------------------------------------------------------------------ download & install
def _safe_extract(archive: Path, dest: Path) -> Path:
    dest = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest) or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError('Unsafe entry in the downloaded archive: ' + info.filename)
        zf.extractall(dest)
        for info in zf.infolist():                          # keep +x on the shell installers
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir():
                try:
                    (dest / info.filename).chmod(mode | 0o600)
                except OSError:
                    pass
    roots = [p.parent for p in dest.rglob('pyproject.toml') if len(p.relative_to(dest).parts) <= 3]
    roots = [r for r in roots if (r / 'src' / 'spm_studio').is_dir()]
    if not roots:
        raise UpdateError('The downloaded archive does not contain SPM Studio')
    return min(roots, key=lambda p: len(p.parts))


def prepare(result: dict, progress=None) -> Path:
    """Download + extract the newest version; returns the folder containing the installers."""
    from spm_studio.core import paths
    tag = result['tag']
    base = paths.cache_dir() / 'updates'
    target = base / tag
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    archive = base / f'{tag}.zip'
    data = _get(result['archive'], timeout=120, accept='application/zip')
    if len(data) < 10_000:
        raise UpdateError('Download incomplete')
    archive.write_bytes(data)
    source = _safe_extract(archive, target)
    found = re.search(r'^version = "(.+)"', (source / 'pyproject.toml').read_text(encoding='utf8'), re.M)
    if not found or parse(found.group(1)) != parse(result['latest']):
        raise UpdateError(f"Archive version {found.group(1) if found else '?'} does not match {result['latest']}")
    return source


def installer_argv(source: Path) -> list[str]:
    if sys.platform.startswith('win'):
        return ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                str(source / 'install_spm_studio_windows.ps1')]
    if sys.platform == 'darwin':
        return ['bash', str(source / 'install_spm_studio_macos.sh')]
    return ['bash', str(source / 'install_spm_studio_clean.sh')]


def launch_installer(source: Path, version: str) -> str:
    """Open the installer in a visible terminal. '' on success, else a manual command."""
    from spm_studio.ai import platform_util as pu
    banner = (f'Updating SPM Studio to {version}.\n'
              'The new version is built and self-tested next to the current one;\n'
              'if anything fails, your current version keeps working.\n'
              'When it says "installed successfully", close SPM Studio and open it again.')
    script = pu.write_terminal_script(source, 'run-update', {}, installer_argv(source), banner)
    return pu.open_terminal(script)


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog='spm-studio-update', description='Check for and install SPM Studio updates')
    ap.add_argument('--check', action='store_true', help='only report whether an update exists')
    ap.add_argument('--update', action='store_true', help='download and run the installer of the newest version')
    ap.add_argument('--yes', action='store_true', help='do not ask for confirmation')
    args = ap.parse_args(argv)
    try:
        result = check()
    except UpdateError as exc:
        print('Update check failed:', exc)
        return 2
    save_state(last_check=time.time(), last_seen=result.get('latest'))
    print(f"Installed: {result['current']}   Latest: {result['latest'] or 'none'}   ({result['repository']})")
    if not result['update']:
        print('SPM Studio is up to date.')
        return 0
    print('\nWhat is new:\n')
    print(notes_markdown(result))
    if not args.update:
        print('\nInstall with:  spm-studio --update')
        return 0
    if not args.yes and input(f"\nInstall {result['latest']} now? [Y/n] ").strip().lower() not in ('', 'y', 'yes'):
        print('Cancelled.')
        return 1
    source = prepare(result)
    import subprocess
    return subprocess.call(installer_argv(source), cwd=str(source))


if __name__ == '__main__':
    raise SystemExit(main())
