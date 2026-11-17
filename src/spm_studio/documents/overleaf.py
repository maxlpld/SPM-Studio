"""Overleaf through its Git integration (Qt-free).

Overleaf has no public upload API; every Overleaf project is however a Git repository
(*Menu › Integrations › Git* in the project; on overleaf.com it needs a plan with Git
integration — many universities provide one — and on Overleaf Server Pro / CE the Git bridge).
SPM Studio uses it with a **Git authentication token** created in *Account Settings › Git
integration*:

* the token is kept in the system keyring (or a private file of the account), never in a
  settings file, and is passed to ``git`` through its environment (``http.extraHeader``), never
  on the command line nor in the stored remote URL;
* each project is cloned once into ``<cache>/overleaf/<project id>``; *upload* copies the files
  into the chosen folder, commits and pushes; Overleaf shows them at once.

Projects are added by pasting their address (``https://www.overleaf.com/project/<id>``), since
Overleaf does not let other programs list them.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOKEN_NAME = 'overleaf_git_token'
DEFAULT_SERVER = 'https://www.overleaf.com'
EXCLUDES = ('.spm_build/', '.spm_latex.json', '*.synctex.gz', '.DS_Store')


class OverleafError(RuntimeError):
    """A plain message for the user."""


def git_executable() -> str | None:
    exe = shutil.which('git')
    if exe:
        return exe
    if sys.platform.startswith('win'):
        for candidate in (r'C:\Program Files\Git\cmd\git.exe', r'C:\Program Files (x86)\Git\cmd\git.exe',
                          os.path.expandvars(r'%LOCALAPPDATA%\Programs\Git\cmd\git.exe')):
            if os.path.isfile(candidate):
                return candidate
    return None


def project_id_from_url(text: str) -> str:
    """Project id from a project address, a Git URL or the id itself."""
    text = (text or '').strip()
    m = re.search(r'/project/([0-9a-fA-F]{24})\b', text) or re.search(r'git\.[^/]+/([0-9a-fA-F]{24})\b', text) \
        or re.search(r'/git/([0-9a-fA-F]{24})\b', text) or re.fullmatch(r'([0-9a-fA-F]{24})', text)
    if not m:
        raise OverleafError('Paste the address of the Overleaf project, e.g. '
                            'https://www.overleaf.com/project/0123456789abcdef01234567')
    return m.group(1).lower()


def server(conf: dict) -> str:
    return (conf.get('overleaf_server') or DEFAULT_SERVER).rstrip('/')


def git_base(conf: dict) -> str:
    if conf.get('overleaf_git_url'):
        return conf['overleaf_git_url'].rstrip('/')
    base = server(conf)
    if re.match(r'https?://(www\.)?overleaf\.com$', base):
        return 'https://git.overleaf.com'
    return base + '/git'


def git_url(project_id: str, conf: dict) -> str:
    return f'{git_base(conf)}/{project_id}'


def project_page(project_id: str, conf: dict) -> str:
    return f'{server(conf)}/project/{project_id}'


def get_token() -> str:
    try:
        from spm_studio.ai import lit_store
        return lit_store.get(TOKEN_NAME) or ''
    except Exception:
        return ''


def set_token(token: str) -> str:
    from spm_studio.ai import lit_store
    token = (token or '').strip()
    if not token:
        lit_store.clear(TOKEN_NAME)
        return 'removed'
    return lit_store.put(TOKEN_NAME, token)


def cache_root() -> Path:
    from spm_studio.core import paths
    d = paths.cache_dir() / 'overleaf'
    d.mkdir(parents=True, exist_ok=True)
    return d


class OverleafClient:
    def __init__(self, conf: dict | None = None, token: str | None = None, cache: Path | None = None):
        if conf is None:
            from . import settings
            conf = settings.load()
        self.conf = conf
        self.token = get_token() if token is None else token
        self.cache = Path(cache) if cache else cache_root()
        self.git = git_executable()

    # ------------------------------------------------------------------ plumbing
    def _env(self) -> dict:
        env = dict(os.environ)
        env['GIT_TERMINAL_PROMPT'] = '0'
        env['GCM_INTERACTIVE'] = 'never'
        env['LC_ALL'] = env.get('LC_ALL') or 'C'
        if self.token:
            basic = base64.b64encode(f'git:{self.token}'.encode()).decode()
            count = int(env.get('GIT_CONFIG_COUNT', '0') or 0)
            env['GIT_CONFIG_COUNT'] = str(count + 1)
            env[f'GIT_CONFIG_KEY_{count}'] = 'http.extraHeader'
            env[f'GIT_CONFIG_VALUE_{count}'] = f'Authorization: Basic {basic}'
        return env

    def _run(self, args, cwd=None, timeout=180) -> str:
        if not self.git:
            raise OverleafError('Git is not installed. Install it (https://git-scm.com/downloads) and try again.')
        command = [self.git, '-c', 'user.name=SPM Studio', '-c', 'user.email=spm-studio@users.noreply.local',
                   '-c', 'credential.helper=', '-c', 'core.autocrlf=false', *args]
        kwargs = {}
        if sys.platform.startswith('win'):
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            result = subprocess.run(command, cwd=str(cwd) if cwd else None, env=self._env(), capture_output=True,
                                    text=True, encoding='utf8', errors='replace', timeout=timeout, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise OverleafError('Overleaf did not answer in time (network?)') from exc
        if result.returncode != 0:
            raise OverleafError(self._explain(result.stderr or result.stdout))
        return result.stdout

    def _explain(self, message: str) -> str:
        text = (message or '').strip()
        if self.token:
            text = text.replace(self.token, '[token]')
        low = text.lower()
        if 'authentication failed' in low or '401' in low or '403' in low or 'could not read username' in low:
            return ('Overleaf refused the Git token. Create a new one in Overleaf › Account Settings › Git '
                    'integration and paste it in SPM Studio › Settings › Documents. (Git integration needs an '
                    'Overleaf plan that includes it, or Overleaf Server Pro.)')
        if 'not found' in low or '404' in low or 'does not appear to be a git repository' in low:
            return 'Overleaf does not know this project, or this account cannot open it. Check the project address.'
        if 'could not resolve host' in low or 'unable to access' in low:
            return 'Cannot reach Overleaf: check the network connection (and the server address in Settings).'
        if 'rejected' in low or 'non-fast-forward' in low:
            return 'Overleaf has newer changes; SPM Studio will merge them first. ' + text[-300:]
        return text[-800:] or 'git failed'

    def _exclude(self, repo: Path):
        info = repo / '.git' / 'info'
        info.mkdir(parents=True, exist_ok=True)
        exclude = info / 'exclude'
        current = exclude.read_text(encoding='utf8') if exclude.is_file() else ''
        missing = [e for e in EXCLUDES if e not in current.split('\n')]
        if missing:
            exclude.write_text(current.rstrip('\n') + ('\n' if current else '') + '\n'.join(missing) + '\n',
                               encoding='utf8')

    # ------------------------------------------------------------------ operations
    def test(self, project_id: str) -> str:
        self._run(['ls-remote', '--heads', git_url(project_id, self.conf)], timeout=60)
        return 'Connected'

    def checkout(self, project_id: str) -> Path:
        """Up-to-date private clone used for uploads."""
        repo = self.cache / project_id
        url = git_url(project_id, self.conf)
        if (repo / '.git').is_dir():
            self._run(['remote', 'set-url', 'origin', url], cwd=repo)
            self._run(['fetch', '--quiet', 'origin'], cwd=repo)
            branch = self._branch(repo)
            self._run(['reset', '--quiet', '--hard', f'origin/{branch}'], cwd=repo)
        else:
            if repo.exists():
                shutil.rmtree(repo, ignore_errors=True)
            self._run(['clone', '--quiet', url, str(repo)])
        self._exclude(repo)
        return repo

    def _branch(self, repo: Path) -> str:
        try:
            ref = self._run(['symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD'], cwd=repo).strip()
            if ref.startswith('origin/'):
                return ref[len('origin/'):]
        except OverleafError:
            pass
        heads = self._run(['branch', '-r'], cwd=repo)
        return 'master' if 'origin/master' in heads else 'main' if 'origin/main' in heads else 'master'

    def folders(self, project_id: str, repo: Path | None = None) -> list[str]:
        repo = repo or self.checkout(project_id)
        found = ['']
        for path in sorted(repo.rglob('*')):
            rel = path.relative_to(repo)
            if path.is_dir() and '.git' not in rel.parts and not any(p.startswith('.') for p in rel.parts):
                found.append(rel.as_posix())
        return found

    def files(self, project_id: str, repo: Path | None = None) -> list[str]:
        repo = repo or self.checkout(project_id)
        return [p.relative_to(repo).as_posix() for p in sorted(repo.rglob('*'))
                if p.is_file() and '.git' not in p.relative_to(repo).parts]

    def upload(self, project_id: str, files, folder: str = 'figures', message: str = '') -> list[str]:
        """Copy ``files`` into ``folder`` of the project and push. Returns the project paths."""
        folder = (folder or '').strip().strip('/').replace('\\', '/')
        if '..' in folder.split('/'):
            raise OverleafError('Choose a folder inside the project')
        repo = self.checkout(project_id)
        target = repo / folder if folder else repo
        target.mkdir(parents=True, exist_ok=True)
        placed = []
        for file in files:
            file = Path(file)
            if not file.is_file():
                continue
            shutil.copy2(file, target / file.name)
            placed.append(((Path(folder) / file.name).as_posix() if folder else file.name))
        if not placed:
            raise OverleafError('Nothing to upload')
        self._run(['add', '--', *placed], cwd=repo)
        status = self._run(['status', '--porcelain'], cwd=repo)
        if status.strip():
            self._run(['commit', '--quiet', '-m', message or f'SPM Studio: {", ".join(Path(p).name for p in placed)}'],
                      cwd=repo)
            self._push(repo)
        return placed

    def _push(self, repo: Path):
        branch = self._branch(repo)
        try:
            self._run(['push', '--quiet', 'origin', f'HEAD:{branch}'], cwd=repo)
        except OverleafError as exc:
            if 'newer changes' not in str(exc):
                raise
            self._run(['pull', '--quiet', '--rebase', 'origin', branch], cwd=repo)
            self._run(['push', '--quiet', 'origin', f'HEAD:{branch}'], cwd=repo)

    # ---------------------------------------------------------- whole projects (editor)
    def clone_project(self, project_id: str, destination: Path) -> Path:
        """Working copy for the LaTeX editor; the stored remote has no secret in it."""
        destination = Path(destination)
        if destination.exists() and any(destination.iterdir()):
            raise OverleafError(f'{destination} is not empty')
        self._run(['clone', '--quiet', git_url(project_id, self.conf), str(destination)])
        self._exclude(destination)
        return destination

    @staticmethod
    def linked_project(folder) -> str | None:
        """Overleaf project id of a LaTeX project folder cloned from Overleaf (else ``None``)."""
        config = Path(folder) / '.git' / 'config'
        try:
            text = config.read_text(encoding='utf8')
        except OSError:
            return None
        m = re.search(r'url\s*=\s*\S*/([0-9a-fA-F]{24})\s*$', text, re.M)
        return m.group(1).lower() if m else None

    def link_project(self, folder, project_id: str):
        """Connect an existing local project to an (empty or matching) Overleaf project."""
        folder = Path(folder)
        if not (folder / '.git').is_dir():
            self._run(['init', '--quiet'], cwd=folder)
        remotes = self._run(['remote'], cwd=folder).split()
        url = git_url(project_id, self.conf)
        self._run(['remote', 'set-url' if 'origin' in remotes else 'add', 'origin', url], cwd=folder)
        self._exclude(folder)

    def pull_project(self, folder) -> str:
        folder = Path(folder)
        self._commit_all(folder, 'SPM Studio: local changes')
        self._run(['fetch', '--quiet', 'origin'], cwd=folder)
        branch = self._branch(folder)
        try:
            self._run(['rebase', '--quiet', f'origin/{branch}'], cwd=folder)
        except OverleafError:
            try:
                self._run(['rebase', '--abort'], cwd=folder)
            except OverleafError:
                pass
            raise OverleafError('The same lines were changed on Overleaf and here. Nothing was lost; '
                                'resolve it on Overleaf or push from one side only.')
        return 'Up to date with Overleaf'

    def push_project(self, folder, message: str = '') -> str:
        folder = Path(folder)
        self._commit_all(folder, message or 'SPM Studio: update')
        try:
            self._run(['fetch', '--quiet', 'origin'], cwd=folder)
            branch = self._branch(folder)
            has_remote = True
        except OverleafError:
            branch, has_remote = 'master', False
        if has_remote:
            remote_head = self._run(['branch', '-r'], cwd=folder)
            if f'origin/{branch}' in remote_head:
                try:
                    self._run(['rebase', '--quiet', f'origin/{branch}'], cwd=folder)
                except OverleafError:
                    try:
                        self._run(['rebase', '--abort'], cwd=folder)
                    except OverleafError:
                        pass
                    raise OverleafError('Overleaf has changes to the same lines. Pull, check, then push again.')
        self._run(['push', '--quiet', 'origin', f'HEAD:{branch}'], cwd=folder)
        return 'Pushed to Overleaf'

    def _commit_all(self, folder: Path, message: str):
        self._exclude(folder)
        self._run(['add', '-A'], cwd=folder)
        if self._run(['status', '--porcelain'], cwd=folder).strip():
            self._run(['commit', '--quiet', '-m', message], cwd=folder)
