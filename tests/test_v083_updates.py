"""v0.8.3: update check, release notes, safe download, one-line installer (no network)."""
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


def _archive(version: str, prefix: str = 'SPM-Studio-') -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        base = f'{prefix}{version}/'
        z.writestr(base + 'pyproject.toml', f'[project]\nname = "spm-studio"\nversion = "{version}"\n')
        z.writestr(base + 'src/spm_studio/__init__.py', '')
        for name in ('install_spm_studio_clean.sh', 'install_spm_studio_macos.sh'):
            info = zipfile.ZipInfo(base + name)
            info.external_attr = 0o100755 << 16
            z.writestr(info, '#!/bin/bash\necho "INSTALLER RAN $(sed -n \'s/^version = "\\(.*\\)"/\\1/p\' pyproject.toml) $*"\n')
        z.writestr(base + 'install_spm_studio_windows.ps1', 'Write-Host hi')
        z.writestr(base + 'padding.bin', os.urandom(20000))
    return buf.getvalue()


class _GitHub(BaseHTTPRequestHandler):
    releases = []
    tags = []
    changelog = ''

    def log_message(self, *a):
        pass

    def _send(self, code, data, ctype='application/json'):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        p = self.path
        if p.startswith('/repos/me/spm/releases'):
            return self._send(200, _GitHub.releases)
        if p.startswith('/repos/me/spm/tags'):
            return self._send(200, [{'name': t} for t in _GitHub.tags])
        if p.endswith('/CHANGELOG.md'):
            return self._send(200, _GitHub.changelog.encode(), 'text/plain')
        if p.startswith('/archive/'):
            return self._send(200, _archive(p.rsplit('/v', 1)[-1][:-4]), 'application/zip')
        self._send(404, {'message': 'Not Found'})


@pytest.fixture
def github(monkeypatch, tmp_path):
    server = ThreadingHTTPServer(('127.0.0.1', 0), _GitHub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    monkeypatch.setattr(updates, 'API', base)
    monkeypatch.setattr(updates, 'RAW', base)
    monkeypatch.setenv('SPM_STUDIO_UPDATE_REPO', 'me/spm')
    monkeypatch.setenv('SPM_STUDIO_USE_GH_CLI', '0')          # never use the developer's own GitHub sign-in
    for var in updates.TOKEN_ENV:
        monkeypatch.delenv(var, raising=False)
    for var, sub in (('XDG_CONFIG_HOME', 'c'), ('XDG_DATA_HOME', 'd'), ('XDG_CACHE_HOME', 'k')):
        monkeypatch.setenv(var, str(tmp_path / sub))
    _GitHub.releases, _GitHub.tags, _GitHub.changelog = [], [], ''
    yield base
    server.shutdown()


def test_version_ordering():
    assert updates.parse('v0.8.10') > updates.parse('0.8.9') > updates.parse('0.8.3')
    assert updates.parse('0.9.0rc1') < updates.parse('0.9.0')
    assert updates.parse('1.0') == updates.parse('v1.0.0')
    assert updates.is_version_tag('v0.8.3') and not updates.is_version_tag('latest')


def test_changelog_sections():
    text = '# Changelog\n\n## 0.8.4 — 2026-12-01\n\n- new thing\n\n## 0.8.3 — 2026-11-14\n\n- older\n'
    assert updates.changelog_sections(text) == [('0.8.4', '- new thing'), ('0.8.3', '- older')]


def test_unconfigured_repository_is_reported(monkeypatch):
    monkeypatch.delenv('SPM_STUDIO_UPDATE_REPO', raising=False)
    monkeypatch.setattr(updates, 'CONFIG_FILE', Path('/nonexistent.json'))
    with pytest.raises(updates.UpdateError):
        updates.check('0.8.3')


def test_check_with_releases_lists_every_newer_version(github):
    _GitHub.releases = [
        {'tag_name': 'v0.9.0', 'body': 'Big update', 'html_url': 'u90', 'published_at': '2026-12-20T00:00:00Z'},
        {'tag_name': 'v0.9.1rc1', 'body': 'pre', 'prerelease': True},
        {'tag_name': 'v0.8.4', 'body': '- fix', 'html_url': 'u84', 'published_at': '2026-12-01T00:00:00Z'},
        {'tag_name': 'v0.8.3', 'body': 'current'},
        {'tag_name': 'nightly', 'body': 'x'},
        {'tag_name': 'v1.0.0', 'draft': True},
    ]
    r = updates.check('0.8.3')
    assert r['update'] and r['latest'] == '0.9.0' and r['tag'] == 'v0.9.0'
    assert [n['version'] for n in r['notes']] == ['0.9.0', '0.8.4']
    md = updates.notes_markdown(r)
    assert '## 0.9.0 — 2026-12-20' in md and 'Big update' in md and '- fix' in md and 'current' not in md
    assert r['archive'].endswith('/me/spm/archive/refs/tags/v0.9.0.zip')
    assert not updates.check('0.9.0')['update']


def test_check_with_tags_only_uses_changelog(github):
    _GitHub.tags = ['v0.8.3', 'v0.8.10', 'v0.8.9', 'experiment']
    _GitHub.changelog = '## 0.8.10\n\n- ten\n\n## 0.8.9\n\n- nine\n\n## 0.8.3\n\n- three\n'
    r = updates.check('0.8.3')
    assert r['source'] == 'tags' and r['latest'] == '0.8.10'
    assert [(n['version'], n['notes']) for n in r['notes']] == [('0.8.10', '- ten'), ('0.8.9', '- nine')]


def test_prepare_downloads_and_validates(github, monkeypatch):
    result = {'tag': 'v0.9.0', 'latest': '0.9.0', 'archive': github + '/archive/refs/tags/v0.9.0.zip'}
    source = updates.prepare(result)
    assert (source / 'pyproject.toml').is_file() and source.name == 'SPM-Studio-0.9.0'
    if os.name != 'nt':
        assert os.access(source / 'install_spm_studio_clean.sh', os.X_OK)
    argv = updates.installer_argv(source)
    assert argv[-1].endswith(('install_spm_studio_clean.sh', 'install_spm_studio_macos.sh',
                              'install_spm_studio_windows.ps1'))
    with pytest.raises(updates.UpdateError):         # archive version must match the announced one
        updates.prepare({'tag': 'v0.9.0', 'latest': '0.9.5', 'archive': result['archive']})


def test_archive_traversal_is_rejected(tmp_path):
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr('../../evil.txt', 'x')
    with pytest.raises(updates.UpdateError):
        updates._safe_extract(bad, tmp_path / 'out')
    assert not (tmp_path / 'evil.txt').exists()


def test_cli_check_and_daily_state(github, capsys):
    _GitHub.releases = [{'tag_name': 'v99.0.0', 'body': '- shiny', 'html_url': 'x'}]
    assert updates.main(['--check']) == 0
    out = capsys.readouterr().out
    assert 'Latest: 99.0.0' in out and '- shiny' in out and 'spm-studio --update' in out
    assert not updates.auto_check_due()               # just checked
    updates.save_state(auto_check=False, last_check=0)
    assert not updates.auto_check_due()               # disabled by the user


def test_release_tools_notes_and_tag():
    v = updates.current_version()
    r = subprocess.run([sys.executable, str(ROOT / 'tools/release_tools.py'), 'check-tag', 'v' + v],
                       capture_output=True, text=True)
    assert r.returncode == 0
    r = subprocess.run([sys.executable, str(ROOT / 'tools/release_tools.py'), 'check-tag', 'v99.0.0'],
                       capture_output=True, text=True)
    assert r.returncode != 0
    r = subprocess.run([sys.executable, str(ROOT / 'tools/release_tools.py'), 'notes', v],
                       capture_output=True, text=True)
    assert 'Check for updates' in r.stdout


@pytest.mark.skipif(os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0),
                    reason='POSIX, unprivileged user only (the script refuses root)')
def test_get_script_end_to_end_with_stub_curl(tmp_path):
    """get-spm-studio.sh: picks the release tag, downloads, extracts, runs that version's installer."""
    stub = tmp_path / 'bin'
    stub.mkdir()
    (tmp_path / 'v0.9.0.zip').write_bytes(_archive('0.9.0'))
    (stub / 'curl').write_text(f'''#!/bin/bash
out=""; url=""
while [[ $# -gt 0 ]]; do case "$1" in -o) out="$2"; shift 2;; -H) shift 2;; -*) shift;; *) url="$1"; shift;; esac; done
case "$url" in
  */releases/latest) printf '{{\\n  "tag_name": "v0.9.0",\\n  "name": "x"\\n}}';;
  */archive/refs/tags/v0.9.0.zip) cp "{tmp_path}/v0.9.0.zip" "$out";;
  *) exit 22;;
esac
''')
    (stub / 'curl').chmod(0o755)
    env = dict(os.environ, PATH=f'{stub}:/usr/bin:/bin', HOME=str(tmp_path), SPM_REPO='me/spm',
               SPM_INSTALL_ARGS='--stage', SPM_SKIP_SYSTEM_PACKAGES='1', SPM_STUDIO_USE_GH_CLI='0',
               SPM_STUDIO_GITHUB_TOKEN='', GH_TOKEN='', GITHUB_TOKEN='')
    r = subprocess.run(['bash', str(ROOT / 'get-spm-studio.sh')], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'SPM Studio 0.9.0' in r.stdout and 'INSTALLER RAN 0.9.0 --stage' in r.stdout
    r2 = subprocess.run(['bash', str(ROOT / 'get-spm-studio.sh')], capture_output=True, text=True,
                        env=dict(env, SPM_VERSION='0.9.0'), stdin=subprocess.DEVNULL, timeout=60)
    assert 'INSTALLER RAN 0.9.0' in r2.stdout


def test_bootstrap_scripts_and_docs_are_consistent():
    sh = (ROOT / 'get-spm-studio.sh').read_text()
    ps = (ROOT / 'get-spm-studio.ps1').read_text()
    repo = json.loads((ROOT / 'src/spm_studio/update_config.json').read_text())['repository']
    assert f'REPO="${{SPM_REPO:-{repo}}}"' in sh and f"'{repo}'" in ps
    readme = (ROOT / 'README.md').read_text()
    assert f'raw.githubusercontent.com/{repo}/main/get-spm-studio.sh | bash' in readme
    assert f'raw.githubusercontent.com/{repo}/main/get-spm-studio.ps1 | iex' in readme
    assert 'Check for updates' in readme
    wf = (ROOT / '.github/workflows/release.yml').read_text()
    assert 'check-tag' in wf and 'gh release create' in wf
