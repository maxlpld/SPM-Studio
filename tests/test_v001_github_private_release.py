"""0.0.1 (GitHub repository): private-repository updates, release tooling, bootstrap scripts.

Everything runs against local HTTP servers and stub programs: no network, no real GitHub account.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from spm_studio.core import updates

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'ghp_TESTTOKEN_not_a_real_credential'
POSIX_USER = pytest.mark.skipif(os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0),
                                reason='POSIX, unprivileged user only (the scripts refuse root)')


def _archive(version: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        base = f'me-spm-abc1234/'                     # layout of GitHub's API zipball
        z.writestr(base + 'pyproject.toml', f'[project]\nname = "spm-studio"\nversion = "{version}"\n')
        z.writestr(base + 'src/spm_studio/__init__.py', '')
        for name in ('install_spm_studio_clean.sh', 'install_spm_studio_macos.sh'):
            info = zipfile.ZipInfo(base + name)
            info.external_attr = 0o100755 << 16
            z.writestr(info, '#!/bin/bash\necho "INSTALLER RAN $(sed -n \'s/^version = "\\(.*\\)"/\\1/p\' pyproject.toml) $*"\n')
        z.writestr(base + 'install_spm_studio_windows.ps1', 'Write-Host hi')
        z.writestr(base + 'padding.bin', os.urandom(20000))
    return buf.getvalue()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, data=b'', ctype='application/json', extra=None):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(code)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class _PrivateAPI(_Handler):
    """A private repository: everything is 404 without the right token (like GitHub)."""
    seen = []
    releases = []
    tags = []
    changelog = ''
    download_base = ''

    def do_GET(self):
        auth = self.headers.get('Authorization', '')
        _PrivateAPI.seen.append((self.path, auth))
        if auth and auth != 'Bearer ' + TOKEN:
            return self._send(401, {'message': 'Bad credentials'})
        if auth != 'Bearer ' + TOKEN:
            return self._send(404, {'message': 'Not Found'})
        p = self.path
        if p.startswith('/repos/me/spm/releases'):
            return self._send(200, _PrivateAPI.releases)
        if p.startswith('/repos/me/spm/tags'):
            return self._send(200, [{'name': t} for t in _PrivateAPI.tags])
        if p.startswith('/repos/me/spm/contents/CHANGELOG.md'):
            assert self.headers.get('Accept') == 'application/vnd.github.raw'
            return self._send(200, _PrivateAPI.changelog.encode(), 'text/plain')
        if p.startswith('/repos/me/spm/zipball/'):
            tag = p.rsplit('/', 1)[-1]
            return self._send(302, extra={'Location': f'{_PrivateAPI.download_base}/signed/{tag}.zip?token=signed'})
        self._send(404, {'message': 'Not Found'})


class _Codeload(_Handler):
    """The other host GitHub redirects archive downloads to: must never receive the credential."""
    seen = []

    def do_GET(self):
        _Codeload.seen.append((self.path, self.headers.get('Authorization', '')))
        tag = self.path.split('/signed/', 1)[1].split('.zip', 1)[0]
        self._send(200, _archive(tag.lstrip('v')), 'application/zip')


def _serve(handler):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}'


@pytest.fixture
def private(monkeypatch, tmp_path):
    api, api_url = _serve(_PrivateAPI)
    dl, dl_url = _serve(_Codeload)          # different port = different host:port, as with codeload.github.com
    monkeypatch.setattr(updates, 'API', api_url)
    monkeypatch.setattr(updates, 'RAW', api_url + '/raw-must-not-be-used')
    monkeypatch.setenv('SPM_STUDIO_UPDATE_REPO', 'me/spm')
    monkeypatch.setenv('SPM_STUDIO_USE_GH_CLI', '0')
    for var in updates.TOKEN_ENV:
        monkeypatch.delenv(var, raising=False)
    for var, sub in (('XDG_CONFIG_HOME', 'c'), ('XDG_DATA_HOME', 'd'), ('XDG_CACHE_HOME', 'k')):
        monkeypatch.setenv(var, str(tmp_path / sub))
    _PrivateAPI.seen, _Codeload.seen = [], []
    _PrivateAPI.releases, _PrivateAPI.tags, _PrivateAPI.changelog = [], [], ''
    _PrivateAPI.download_base = dl_url
    yield api_url
    api.shutdown()
    dl.shutdown()


# ------------------------------------------------------------------ updater, private repository
def test_private_repo_without_sign_in_explains_what_to_do(private):
    with pytest.raises(updates.UpdateError) as err:
        updates.check('0.0.1')
    assert 'gh auth login' in str(err.value) and 'SPM_STUDIO_GITHUB_TOKEN' in str(err.value)


def test_private_repo_with_token_checks_downloads_and_never_leaks_the_token(private, monkeypatch):
    monkeypatch.setenv('SPM_STUDIO_GITHUB_TOKEN', TOKEN)
    _PrivateAPI.releases = [{'tag_name': 'v0.0.2', 'body': '- private fix', 'html_url': 'u',
                             'published_at': '2026-12-01T00:00:00Z'},
                            {'tag_name': 'v0.0.1', 'body': 'first'}]
    r = updates.check('0.0.1')
    assert r['update'] and r['latest'] == '0.0.2' and r['authenticated']
    assert r['archive'] == f'{private}/repos/me/spm/zipball/v0.0.2'
    assert '- private fix' in updates.notes_markdown(r)
    source = updates.prepare(r)
    assert (source / 'install_spm_studio_clean.sh').is_file()
    assert os.access(source / 'install_spm_studio_clean.sh', os.X_OK) or os.name == 'nt'
    assert all(auth == 'Bearer ' + TOKEN for _, auth in _PrivateAPI.seen)
    assert _Codeload.seen and all(auth == '' for _, auth in _Codeload.seen)   # dropped on redirect


def test_private_repo_tags_only_reads_changelog_through_the_api(private, monkeypatch):
    monkeypatch.setenv('GH_TOKEN', TOKEN)
    _PrivateAPI.tags = ['v0.0.1', 'v0.0.3', 'notes']
    _PrivateAPI.changelog = '# Changelog\n\n## 0.0.3 — 2027-01-01\n\n- three\n\n## 0.0.1\n\n- one\n'
    r = updates.check('0.0.1')
    assert r['source'] == 'tags' and r['latest'] == '0.0.3' and r['notes'][0]['notes'] == '- three'
    assert not any('raw-must-not-be-used' in path for path, _ in _PrivateAPI.seen)


def test_bad_token_gives_a_clear_message(private, monkeypatch):
    monkeypatch.setenv('SPM_STUDIO_GITHUB_TOKEN', 'expired')
    with pytest.raises(updates.UpdateError) as err:
        updates.check('0.0.1')
    assert 'gh auth login' in str(err.value)


def test_token_is_not_sent_to_other_hosts(monkeypatch):
    monkeypatch.setenv('SPM_STUDIO_GITHUB_TOKEN', TOKEN)
    captured = {}

    class _Opener:
        def open(self, req, timeout):
            captured['headers'] = dict(req.header_items())
            raise OSError('stop')

    monkeypatch.setattr(updates, 'build_opener', lambda *h: _Opener())
    with pytest.raises(updates.UpdateError):
        updates._get('https://example.org/file.zip')
    assert 'Authorization' not in captured['headers']
    with pytest.raises(updates.UpdateError):
        updates._get(updates.API + '/repos/me/spm/releases')
    assert captured['headers']['Authorization'] == 'Bearer ' + TOKEN


def test_token_sources_order_and_gh_cli(monkeypatch, tmp_path):
    for var in updates.TOKEN_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(updates, '_GH_CLI_TOKEN', [])
    monkeypatch.setenv('SPM_STUDIO_USE_GH_CLI', '0')
    assert updates.github_token() == ''
    monkeypatch.setenv('GITHUB_TOKEN', 'c')
    monkeypatch.setenv('GH_TOKEN', 'b')
    assert updates.github_token() == 'b'
    monkeypatch.setenv('SPM_STUDIO_GITHUB_TOKEN', 'a')
    assert updates.github_token() == 'a'
    if os.name == 'nt':
        return
    for var in updates.TOKEN_ENV:
        monkeypatch.delenv(var)
    fake = tmp_path / 'gh'
    fake.write_text('#!/bin/sh\n[ "$1 $2" = "auth token" ] && echo from-gh-cli\n')
    fake.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{os.environ.get("PATH", "")}')
    monkeypatch.setenv('SPM_STUDIO_USE_GH_CLI', '1')
    assert updates.github_token() == 'from-gh-cli'


def test_public_repo_keeps_the_plain_archive_url(monkeypatch):
    monkeypatch.setenv('SPM_STUDIO_USE_GH_CLI', '0')
    for var in updates.TOKEN_ENV:
        monkeypatch.delenv(var, raising=False)
    assert updates.archive_url('me/spm', 'v1.2.3') == 'https://github.com/me/spm/archive/refs/tags/v1.2.3.zip'


# ------------------------------------------------------------------ version, changelog, release tools
def _tool(*args, cwd=ROOT):
    return subprocess.run([sys.executable, str(Path(cwd) / 'tools/release_tools.py'), *args],
                          capture_output=True, text=True)


def test_single_version_source_and_changelog():
    v = updates.current_version()
    assert v == '0.0.1' or updates.parse(v) > updates.parse('0.0.1')
    sections = updates.changelog_sections((ROOT / 'CHANGELOG.md').read_text(encoding='utf8'))
    assert sections and sections[0][0] == v, 'newest CHANGELOG section must be the pyproject version'
    # Internal 0.7-0.8 history lives in docs/, so it can never be offered as "newer" release notes.
    assert all(updates.parse(s) <= updates.parse(v) for s, _ in sections)
    assert _tool('check-changelog').returncode == 0
    assert '0.8.3' in (ROOT / 'docs/DEVELOPMENT_HISTORY.md').read_text(encoding='utf8')


def test_check_repo_and_set_repo(tmp_path):
    copy = tmp_path / 'SPM-Studio'
    for rel in ['tools/release_tools.py', 'pyproject.toml', 'CHANGELOG.md', 'README.md', 'get-spm-studio.sh',
                'get-spm-studio.ps1', 'src/spm_studio/update_config.json', 'GITHUB_FIRST_UPLOAD.md']:
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, copy / rel)
    json.loads((copy / 'src/spm_studio/update_config.json').read_text())
    cfg = copy / 'src/spm_studio/update_config.json'
    data = json.loads(cfg.read_text())
    data['repository'] = 'YOUR_GITHUB_USER/SPM-Studio'
    cfg.write_text(json.dumps(data))
    for name in ('get-spm-studio.sh', 'get-spm-studio.ps1', 'README.md'):
        text = (copy / name).read_text(encoding='utf8')
        repo = json.loads((ROOT / 'src/spm_studio/update_config.json').read_text())['repository']
        (copy / name).write_text(text.replace(repo, 'YOUR_GITHUB_USER/SPM-Studio'), encoding='utf8')
    r = _tool('check-repo', 'alice/SPM-Studio', cwd=copy)
    assert r.returncode != 0 and 'set-repo alice/SPM-Studio' in r.stderr
    assert _tool('set-repo', 'alice/SPM-Studio', cwd=copy).returncode == 0
    assert _tool('check-repo', 'Alice/spm-studio', cwd=copy).returncode == 0      # GitHub names: any case
    assert _tool('check-repo', 'bob/SPM-Studio', cwd=copy).returncode != 0
    sh = (copy / 'get-spm-studio.sh').read_text()
    assert 'REPO="${SPM_REPO:-alice/SPM-Studio}"' in sh and 'repos/alice/SPM-Studio/contents/' in sh
    assert 'YOUR_GITHUB_USER/*' in sh                                         # the guard itself stays
    readme = (copy / 'README.md').read_text(encoding='utf8')
    assert 'raw.githubusercontent.com/alice/SPM-Studio/main/get-spm-studio.sh' in readme
    assert 'YOUR_GITHUB_USER/SPM-Studio' not in readme


def test_release_archive_is_one_clean_cross_platform_zip(tmp_path):
    r = _tool('archive', str(tmp_path / 'dist'))
    assert r.returncode == 0, r.stderr
    zips = list((tmp_path / 'dist').glob('*.zip'))
    v = updates.current_version()
    assert [z.name for z in zips] == [f'SPM-Studio-{v}.zip']
    with zipfile.ZipFile(zips[0]) as z:
        names = z.namelist()
        assert all(n.startswith(f'SPM-Studio-{v}/') for n in names)
        for need in ('pyproject.toml', 'install_spm_studio_clean.sh', 'install_spm_studio_macos.sh',
                     'install_spm_studio_windows.ps1', 'src/spm_studio/app.py', 'src/spm_studio/core/updates.py'):
            assert f'SPM-Studio-{v}/{need}' in names, need
        assert not [n for n in names if '__pycache__' in n or n.endswith('.pyc') or '/.git/' in n
                    or n.rsplit('/', 1)[-1] in ('auth.json', '.env', '.DS_Store')]
        mode = (z.getinfo(f'SPM-Studio-{v}/install_spm_studio_clean.sh').external_attr >> 16) & 0o777
        assert mode & 0o111


def test_workflows_least_privilege_and_tests_before_release():
    yaml = pytest.importorskip('yaml')
    wf = ROOT / '.github/workflows'
    rel = yaml.safe_load((wf / 'release.yml').read_text())
    tests = yaml.safe_load((wf / 'tests.yml').read_text())
    suite = yaml.safe_load((wf / 'test-suite.yml').read_text())
    assert rel['permissions'] == {} and tests['permissions'] == {'contents': 'read'}
    assert suite['permissions'] == {'contents': 'read'}
    assert rel['jobs']['verify']['permissions'] == {'contents': 'read'}
    assert rel['jobs']['tests']['permissions'] == {'contents': 'read'}
    assert rel['jobs']['publish']['permissions'] == {'contents': 'write'}
    assert set(rel['jobs']['publish']['needs']) == {'verify', 'tests'}
    verify = ' '.join(s.get('run', '') for s in rel['jobs']['verify']['steps'])
    for step in ('check-tag', 'check-repo', 'check-changelog'):
        assert step in verify
    oses = {m['os'] for m in rel['jobs']['tests']['strategy']['matrix']['include']}
    assert oses == {'ubuntu-latest', 'windows-latest', 'macos-latest'}      # every release, every OS
    steps = ' '.join(s.get('run', '') for s in suite['jobs']['test']['steps'])
    assert 'pytest' in steps and '--smoke-test' in steps and 'install.py' in steps
    for job in ('linux', 'windows-macos'):
        assert tests['jobs'][job]['uses'] == './.github/workflows/test-suite.yml'
    assert 'private' in tests['jobs']['windows-macos']['if']
    on = tests.get('on') or tests.get(True)
    assert on['push']['tags-ignore'] == ['v*'] and 'pull_request' in on


def test_installers_do_not_need_git():
    for name in ('get-spm-studio.sh', 'get-spm-studio.ps1', 'install_spm_studio_clean.sh',
                 'install_spm_studio_macos.sh', 'install_spm_studio_windows.ps1', 'install.py'):
        text = (ROOT / name).read_text(encoding='utf8')
        assert 'git clone' not in text and 'git rev-parse' not in text and '.git/' not in text, name


# ------------------------------------------------------------------ get-spm-studio.sh, private repository
def _stub_curl(tmp_path, zip_bytes):
    stub = tmp_path / 'bin'
    stub.mkdir()
    (tmp_path / 'v0.0.2.zip').write_bytes(zip_bytes)
    log = tmp_path / 'curl.log'
    (stub / 'curl').write_text(f'''#!/bin/bash
echo "ARGV: $*" >> "{log}"
out=""; url=""; auth=""
while [[ $# -gt 0 ]]; do case "$1" in
  -o) out="$2"; shift 2;;
  -H) [[ "$2" == @* ]] && auth="$(cat "${{2#@}}")"; shift 2;;
  -*) shift;;
  *) url="$1"; shift;;
esac; done
echo "URL: $url AUTH: $auth" >> "{log}"
[[ "$auth" == "Authorization: Bearer {TOKEN}" ]] || exit 22          # private repository
case "$url" in
  */releases/latest) printf '{{\\n  "tag_name": "v0.0.2"\\n}}';;
  */zipball/v0.0.2) cp "{tmp_path}/v0.0.2.zip" "$out";;
  *) exit 22;;
esac
''')
    (stub / 'curl').chmod(0o755)
    return stub, log


@POSIX_USER
def test_get_script_private_repository_with_token(tmp_path):
    stub, log = _stub_curl(tmp_path, _archive('0.0.2'))
    env = dict(os.environ, PATH=f'{stub}:/usr/bin:/bin', HOME=str(tmp_path), SPM_REPO='me/spm',
               SPM_INSTALL_ARGS='--stage', SPM_SKIP_SYSTEM_PACKAGES='1', SPM_STUDIO_USE_GH_CLI='0',
               SPM_STUDIO_GITHUB_TOKEN=TOKEN, GH_TOKEN='', GITHUB_TOKEN='', TMPDIR=str(tmp_path))
    r = subprocess.run(['bash', str(ROOT / 'get-spm-studio.sh')], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'INSTALLER RAN 0.0.2 --stage' in r.stdout
    text = log.read_text()
    assert 'zipball/v0.0.2' in text
    assert not [line for line in text.splitlines() if line.startswith('ARGV:') and TOKEN in line], \
        'the token must never be on a command line'
    assert not list(tmp_path.glob('tmp.*/auth.header'))                     # cleaned up


@POSIX_USER
def test_get_script_private_repository_without_sign_in_explains(tmp_path):
    stub, _ = _stub_curl(tmp_path, _archive('0.0.2'))
    env = dict(os.environ, PATH=f'{stub}:/usr/bin:/bin', HOME=str(tmp_path), SPM_REPO='me/spm',
               SPM_SKIP_SYSTEM_PACKAGES='1', SPM_STUDIO_USE_GH_CLI='0',
               SPM_STUDIO_GITHUB_TOKEN='', GH_TOKEN='', GITHUB_TOKEN='')
    r = subprocess.run(['bash', str(ROOT / 'get-spm-studio.sh')], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode != 0 and 'gh auth login' in r.stderr


@POSIX_USER
def test_get_script_refuses_the_unconfigured_placeholder(tmp_path):
    text = (ROOT / 'get-spm-studio.sh').read_text()
    repo = json.loads((ROOT / 'src/spm_studio/update_config.json').read_text())['repository']
    script = tmp_path / 'get.sh'
    script.write_text(text.replace(f'REPO="${{SPM_REPO:-{repo}}}"', 'REPO="${SPM_REPO:-YOUR_GITHUB_USER/SPM-Studio}"'))
    env = {k: v for k, v in os.environ.items() if k != 'SPM_REPO'}
    r = subprocess.run(['bash', str(script)], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=30)
    assert r.returncode == 2 and 'not configured' in r.stderr
