"""v0.0.13: public guided tutorial on real KBr scans, beta tester client, signed extensions, public/private boundary."""
import base64
import hashlib
import io
import json
import os
import re
import secrets
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name, folder in (('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache')):
        monkeypatch.setenv(name, str(tmp_path / folder))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('SPM_STUDIO_BETA_NO_KEYRING', '1')
    monkeypatch.delenv('SPM_STUDIO_BETA_API', raising=False)
    (tmp_path / 'home').mkdir()
    return tmp_path


# ====================================================================== dataset
def test_bundled_scans_are_unmodified_and_load_with_the_real_reader(home):
    from spm_studio.core.io import read_scan
    from spm_studio.tutorial import dataset
    assert all(dataset.verify().values())
    sums = (dataset.bundled_dir() / 'SHA256SUMS.txt').read_text()
    for name, digest in dataset.FILES.items():
        assert f'{digest}  {name}' in sums
        assert dataset.manifest()['files'][list(dataset.FILES).index(name)]['sha256'] == digest
    main, up, cut = (read_scan(dataset.bundled_dir() / n) for n in dataset.FILES)
    assert main.channels['Z'].unit == 'm' and main.channels['Z'].get('forward').shape == (256, 256)
    assert set(main.channels['Z'].traces) == {'forward', 'backward'}
    assert cut.channels['Z'].get('forward').shape == (192, 192)
    assert 0.3 < np.isnan(cut.channels['Z'].get('forward')).mean() < 0.6          # incomplete, not invented
    assert not np.isnan(main.channels['Z'].get('forward')).any()
    assert not np.array_equal(main.channels['Z'].get('forward'), up.channels['Z'].get('forward'))
    before = {n: dataset.sha256(dataset.bundled_dir() / n) for n in dataset.FILES}
    folder = dataset.prepare_workspace()
    assert all(dataset.verify(folder).values())
    (folder / dataset.MAIN).write_bytes(b'damaged')                  # a damaged copy is replaced …
    dataset.prepare_workspace()
    assert dataset.verify(folder)[dataset.MAIN]
    assert before == {n: dataset.sha256(dataset.bundled_dir() / n) for n in dataset.FILES}   # … originals untouched


def test_dataset_metadata_is_safe_to_publish():
    from spm_studio.tutorial import dataset
    for name in dataset.FILES:
        raw = (dataset.bundled_dir() / name).read_bytes()
        header = raw[:raw.find(b':SCANIT_END:')].decode('latin1')
        assert not re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', header)                     # no e-mail address
        assert not re.search(r'\b\d{1,3}(\.\d{1,3}){3}\b', header)                   # no IP address
        assert not re.search(r'(?i)(password|token|secret|apikey|/home/|/Users/|C:\\Users)', header)


def test_tutorial_scans_are_package_data():
    text = (ROOT / 'pyproject.toml').read_text()
    assert '"resources/tutorial_scan/*"' in text


# ====================================================================== tutorial state & course
def test_onboarding_state(home):
    from spm_studio.tutorial import state
    assert state.startup_action('0.0.13') == 'welcome'
    state.update(skipped=True, welcome_shown=True)
    assert state.startup_action('0.0.13') is None                 # no nagging after a skip
    assert state.startup_action('0.0.13') is None
    assert state.startup_action('0.0.14') == 'whats_new'          # after an update: what's new, once
    state.update(whats_new_seen='0.0.14')
    assert state.startup_action('0.0.14') is None
    pages = state.whats_new_pages((ROOT / 'CHANGELOG.md').read_text(), '0.0.13')
    assert pages and any('tutorial' in p['title'].lower() for p in pages)


def test_course_steps_complete_only_on_the_real_state(home):
    from spm_studio.tutorial import course, dataset
    steps = course.basics()
    assert len(steps) == 12 and steps[0].action == '' and all(s.action and s.check for s in steps[1:])
    by_id = {s.id: s for s in steps}
    trace = SimpleNamespace(data='forward', currentData=lambda: trace.data, currentText=lambda: trace.data,
                            count=lambda: 2)
    inspector = SimpleNamespace(channel=SimpleNamespace(currentText=lambda: 'Z'), trace=trace)
    win = SimpleNamespace(_source_paths=[], scan=None, inspector=inspector, tutorial_counters={},
                          module_panel=SimpleNamespace(module=None), ai_dock=SimpleNamespace(is_open=lambda: False),
                          last_export_dir=str(home / 'exports'))
    ctx = course.Context(win, visible_window_types=lambda: set())
    assert not by_id['dataset'].check(ctx)
    win._source_paths = [str(home / n) for n in dataset.FILES]
    assert by_id['dataset'].check(ctx)
    assert not by_id['import'].check(ctx)
    win.scan = SimpleNamespace(path=home / dataset.MAIN)
    assert by_id['import'].check(ctx)
    by_id['channel'].setup(ctx)
    assert not by_id['channel'].check(ctx)                       # Z but trace unchanged
    trace.data = 'backward'
    assert by_id['channel'].check(ctx)
    by_id['profile'].setup(ctx)
    assert not by_id['profile'].check(ctx)
    win.tutorial_counters['profile_applied'] = 1
    assert by_id['profile'].check(ctx)
    by_id['tool'].setup(ctx)
    win.module_panel.module = SimpleNamespace(id='line_profile')
    assert by_id['tool'].check(ctx)
    assert not by_id['guides'].check(ctx)
    assert by_id['guides'].check(course.Context(win, visible_window_types=lambda: {'GuideDialog'}))
    win.ai_dock = SimpleNamespace(is_open=lambda: True)
    assert by_id['assistant'].check(ctx)
    export_ctx = course.Context(win)
    by_id['export'].setup(export_ctx)
    assert not by_id['export'].check(export_ctx)
    (home / 'exports').mkdir()
    (home / 'exports' / 'figure.png').write_bytes(b'x')
    assert by_id['export'].check(export_ctx)
    assert course.resolve(SimpleNamespace(a=SimpleNamespace(b=5)), 'a.b') == 5
    assert course.resolve(SimpleNamespace(), 'missing.x') is None


# ====================================================================== signatures & extensions
def test_ed25519_matches_rfc8032_vector_and_cryptography():
    from spm_studio.beta import ed25519
    # RFC 8032, test 1
    sk = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
    pk = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
    sig = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b'
                        '46bd25bf5f0595bbe24655141438e7a100b')
    assert ed25519.public_key(sk) == pk and ed25519.sign(sk, b'') == sig
    assert ed25519.verify(pk, b'', sig) and not ed25519.verify(pk, b'x', sig)
    assert not ed25519.verify(pk, b'', sig[:63] + bytes([sig[63] ^ 1]))


def _extension_zip(path: Path, ext_id='demo-ext', version='1.0.0', body='def activate(api):\n    api.log("hi")\n',
                   extra=None):
    descriptor = {'id': ext_id, 'name': 'Demo', 'vendor': 'tests', 'version': version, 'core_api': '>=1,<2',
                  'entry': 'demo_pkg:activate', 'permissions': ['settings_page']}
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('extension.json', json.dumps(descriptor))
        zf.writestr('demo_pkg/__init__.py', body)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return descriptor


def _manifest(path: Path, descriptor: dict, secret: bytes):
    from spm_studio.beta import ed25519, extensions
    data = path.read_bytes()
    manifest = dict(descriptor, artifact={'name': path.name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                                          'download_path': f"/v1/beta/releases/{descriptor['version']}/asset/{path.name}"})
    return manifest, base64.b64encode(ed25519.sign(secret, extensions.canonical(manifest))).decode()


def test_signed_manifest_and_safe_install(home, monkeypatch):
    from spm_studio.beta import ed25519, extensions
    from spm_studio.beta.client import BetaError
    secret = secrets.token_bytes(32)
    keys = [ed25519.public_key(secret)]
    archive = home / 'demo.zip'
    d = _extension_zip(archive)
    manifest, sig = _manifest(archive, d, secret)
    assert extensions.verify_manifest(manifest, sig, keys)['id'] == 'demo-ext'
    for forged in (dict(manifest, version='2.0.0'), dict(manifest, core_api='>=7')):
        with pytest.raises(BetaError):
            extensions.verify_manifest(forged, sig, keys)
    with pytest.raises(BetaError):
        extensions.verify_manifest(manifest, sig, [ed25519.public_key(secrets.token_bytes(32))])
    with pytest.raises(BetaError):
        extensions.verify_manifest(manifest, sig, [])
    extensions.check_artifact(archive, manifest)
    damaged = home / 'damaged.zip'
    raw = bytearray(archive.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    damaged.write_bytes(bytes(raw))
    with pytest.raises(BetaError):
        extensions.check_artifact(damaged, manifest)
    assert extensions.install_archive(archive, manifest)['version'] == '1.0.0'
    archive2 = home / 'demo2.zip'
    _extension_zip(archive2, version='1.1.0')
    extensions.install_archive(archive2)
    info = extensions.installed()['demo-ext']
    assert info['descriptor']['version'] == '1.1.0' and info['previous'] == '1.0.0'
    assert extensions.rollback('demo-ext') == '1.0.0'
    assert extensions.installed()['demo-ext']['descriptor']['version'] == '1.0.0'
    extensions.uninstall('demo-ext')
    assert extensions.installed() == {}


@pytest.mark.parametrize('name', ['../evil.py', '/abs.py', 'a/../../b.py', 'C:\\x.py', 'dir\\x.py'])
def test_unsafe_archives_are_refused(home, name):
    if os.name == 'nt' and name == 'dir\\x.py':
        pytest.skip('zipfile itself reads backslashes as folder separators on Windows (dir/x.py, harmless)')
    from spm_studio.beta import extensions
    from spm_studio.beta.client import BetaError
    archive = home / 'bad.zip'
    _extension_zip(archive, extra={name: 'x'})
    with pytest.raises(BetaError):
        extensions.install_archive(archive)
    assert not (home / 'evil.py').exists()


def test_symlinks_and_zip_bombs_are_refused(home):
    from spm_studio.beta import extensions
    from spm_studio.beta.client import BetaError
    archive = home / 'link.zip'
    _extension_zip(archive)
    with zipfile.ZipFile(archive, 'a') as zf:
        info = zipfile.ZipInfo('demo_pkg/link')
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, '/etc/passwd')
    with pytest.raises(BetaError):
        extensions.install_archive(archive)
    bomb = home / 'bomb.zip'
    _extension_zip(bomb)
    with zipfile.ZipFile(bomb, 'a', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('demo_pkg/zeros.bin', b'\0' * (5 * 1024 * 1024))
    with pytest.raises(BetaError):
        extensions.install_archive(bomb)


def test_loader_activates_isolates_failures_and_respects_beta_state(home):
    from spm_studio.beta import extensions
    good, bad = home / 'good.zip', home / 'bad.zip'
    _extension_zip(good, 'good-ext', body='CALLS = []\ndef activate(api):\n    CALLS.append(api.descriptor["id"])\n')
    _extension_zip(bad, 'bad-ext', body='def activate(api):\n    raise RuntimeError("boom")\n')
    # both use the package name demo_pkg; rename the second to keep imports apart
    with zipfile.ZipFile(bad) as zf:
        files = {n: zf.read(n) for n in zf.namelist()}
    d = json.loads(files['extension.json'])
    d['entry'] = 'bad_pkg:activate'
    with zipfile.ZipFile(bad, 'w') as zf:
        zf.writestr('extension.json', json.dumps(d))
        zf.writestr('bad_pkg/__init__.py', files['demo_pkg/__init__.py'])
    extensions.install_archive(good)
    extensions.install_archive(bad)
    cleaned = []
    api = SimpleNamespace(for_extension=lambda desc: SimpleNamespace(descriptor=desc), cleanup=cleaned.append)
    assert extensions.load_enabled(api, beta_ok=False) == {'good-ext': 'beta access not verified',
                                                           'bad-ext': 'beta access not verified'}
    report = extensions.load_enabled(api, beta_ok=True)
    assert report['good-ext'] == 'ok' and report['bad-ext'].startswith('failed')
    assert cleaned == ['bad-ext'] and not extensions.installed()['bad-ext']['enabled']
    assert 'boom' in extensions.installed()['bad-ext']['error']


# ====================================================================== beta client against a fake service
class FakeService(BaseHTTPRequestHandler):
    calls = []
    mode = {}

    def log_message(self, *a):
        pass

    def _reply(self, status, payload, headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'] or 0)) or b'{}')
        FakeService.calls.append((self.path, body, self.headers.get('Authorization', '')))
        if self.path == '/v1/auth/redeem':
            if FakeService.mode.get('full'):
                return self._reply(409, {'error': 'DEVICE_LIMIT_REACHED', 'message': 'full', 'active_devices': 5,
                                         'max_devices': 5})
            return self._reply(200, {'access_token': 'A' * 40, 'refresh_token': 'R' * 60, 'expires_in': 900,
                                     'account': {'role': 'tester', 'label': 'Ana', 'active_devices': 2,
                                                 'max_devices': 5}})
        if self.path == '/v1/auth/refresh':
            if FakeService.mode.get('revoked'):
                return self._reply(403, {'error': 'REVOKED', 'message': 'revoked'})
            return self._reply(200, {'access_token': 'B' * 40, 'refresh_token': 'S' * 60, 'expires_in': 900,
                                     'account': {'role': 'tester', 'active_devices': 2, 'max_devices': 5}})
        if self.path == '/v1/auth/logout':
            return self._reply(200, {'ok': True})
        self._reply(404, {'error': 'NOT_FOUND'})

    def do_GET(self):
        FakeService.calls.append((self.path, None, self.headers.get('Authorization', '')))
        if self.path == '/v1/auth/me':
            return self._reply(200, {'role': 'tester', 'active_devices': 2, 'max_devices': 5})
        if self.path == '/redirect':
            return self._reply(302, {}, {'Location': 'https://example.com/'})
        self._reply(404, {'error': 'NOT_FOUND'})


@pytest.fixture
def fake_service(monkeypatch):
    FakeService.calls, FakeService.mode = [], {}
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), FakeService)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv('SPM_STUDIO_BETA_API', f'http://127.0.0.1:{httpd.server_address[1]}')
    yield FakeService
    httpd.shutdown()
    httpd.server_close()


def test_client_redeem_session_and_errors(home, fake_service):
    from spm_studio.beta import client
    session = client.Session()
    assert not session.signed_in()
    with pytest.raises(client.BetaError) as err:
        session.redeem('not a key')
    assert err.value.code == 'INVALID_KEY' and not fake_service.calls
    key = 'spm-beta-ABCDE-FGHJK-LMNPQ-RSTUV-WXYZ2-34567'
    session.redeem(key, 'Laptop')
    path, body, _auth = fake_service.calls[-1]
    assert body['invitation'] == key.upper() and len(body['device_id']) == 32 and body['device_label'] == 'Laptop'
    state_text = (home / 'config' / 'spm-studio-ai' / 'beta.json').read_text()
    assert key.upper() not in state_text and 'R' * 60 not in state_text           # neither key nor token here
    assert client.load_refresh() == 'R' * 60 and session.signed_in()
    assert client.load_state()['max_devices'] == 5 and client.offline_grace_ok()
    session.access = ''
    assert session.me()['active_devices'] == 2
    assert fake_service.calls[-1][2] == 'Bearer ' + 'B' * 40                        # refreshed, rotated
    assert client.load_refresh() == 'S' * 60
    fake_service.mode['full'] = True
    with pytest.raises(client.BetaError) as err:
        client.Session().redeem(key)
    assert err.value.code == 'DEVICE_LIMIT_REACHED' and '5 / 5' in client.friendly(err.value)
    fake_service.mode['revoked'] = True
    session.access = ''
    with pytest.raises(client.BetaError) as err:
        session.me()
    assert err.value.code == 'REVOKED' and not session.signed_in() and not client.offline_grace_ok()
    with pytest.raises(client.BetaError) as err:
        client.request('GET', '/redirect')
    assert err.value.code == 'BAD_RESPONSE'


def test_client_requires_https_and_handles_offline(home, monkeypatch):
    from spm_studio.beta import client
    monkeypatch.setenv('SPM_STUDIO_BETA_API', 'http://beta.example.com')
    with pytest.raises(client.BetaError) as err:
        client.api_base()
    assert err.value.code == 'NOT_CONFIGURED'
    monkeypatch.delenv('SPM_STUDIO_BETA_API')
    with pytest.raises(client.BetaError):
        client.api_base()                                   # nothing configured in this version: clear message
    monkeypatch.setenv('SPM_STUDIO_BETA_API', 'http://127.0.0.1:9')
    with pytest.raises(client.BetaError) as err:
        client.request('GET', '/v1/auth/me')
    assert err.value.code == 'OFFLINE'
    assert client.signing_keys() and len(client.signing_keys()[0]) == 32
    assert client.device_id() == client.device_id()


# ====================================================================== public / private boundary
# Names that belong to the private extension only. Stored as truncated SHA-256 of single words and word pairs,
# so this public test does not itself reveal them.
PRIVATE_WORD_HASHES = {'08503405f4b9a29d',
                        '21bf1cbf6d6cb895',
                        '29ea2419bd2990dc',
                        '2db8301cae73953d',
                        '7ef12ca8e3b488f1',
                        '9b6d532ca9ab1d13',
                        'ea3fc5a76c7f10a4',
                        'f155ab53127717e7',
                        'f8e7bc470f1c9a42',
                        'fb45631099bb6147'}


def private_words(text: str) -> list[str]:
    words = re.findall(r'[A-Za-z_][A-Za-z0-9_-]*', text)
    found = []
    for item in words + [a + ' ' + b for a, b in zip(words, words[1:])]:
        if hashlib.sha256(item.encode()).hexdigest()[:16] in PRIVATE_WORD_HASHES:
            found.append(item)
    return found


def test_public_tree_holds_no_private_material():
    offenders = []
    for folder in ('src', 'scripts', 'tools', 'docs', '.github', 'tests'):
        for path in (ROOT / folder).rglob('*'):
            if path.is_file() and path.suffix in ('.py', '.json', '.md', '.txt', '.yml', '.yaml', '.html', '.js',
                                                  '.toml', '.cfg', '.ini', '.sh', '.ps1'):
                text = path.read_text(encoding='utf8', errors='ignore')
                if private_words(text):
                    offenders.append(str(path.relative_to(ROOT)))
    for name in ('README.md', 'CHANGELOG.md', 'pyproject.toml'):
        if private_words((ROOT / name).read_text(encoding='utf8')):
            offenders.append(name)
    assert not offenders
    # no image other than the existing app resources
    pngs = {p.name for p in (ROOT / 'src').rglob('*.png')}
    assert pngs <= {'spm-studio.png'} | {p.name for p in (ROOT / 'src' / 'spm_studio' / 'resources').glob('*.png')}


# ====================================================================== Qt
@pytest.fixture
def window(home, monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    monkeypatch.setenv('SPM_STUDIO_NO_UPDATE_CHECK', '1')
    app = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(home / 'qt'))
    from spm_studio.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    app.processEvents()
    yield win
    win.close()
    app.processEvents()


def wait_until(condition, seconds=30):
    from PySide6.QtWidgets import QApplication
    deadline = time.time() + seconds
    while time.time() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return bool(condition())


def _press_escape(widget):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))


def test_guided_tour_real_actions_and_escape(window):
    from PySide6.QtWidgets import QDialog
    from spm_studio.tutorial import dataset, state
    window.start_tutorial(0)
    manager = window.tutorial
    assert manager.active and manager.callout.step_label.text() == 'Step 1 / 12'
    manager.callout.next_button.click()
    assert manager.index == 1 and not manager.callout.next_button.isEnabled()      # an action is expected
    manager.callout.next.emit()
    assert manager.index == 1                                                        # Next alone does nothing
    manager.callout.extra_button.click()                                             # the user's own click
    assert wait_until(lambda: manager.done)
    assert len({p for p in window._source_paths if Path(p).name in dataset.FILES}) == 3
    manager.callout.next_button.click()
    from PySide6.QtCore import Qt
    item = next(window.browser.files.item(i) for i in range(window.browser.files.count())
                if Path(str(window.browser.files.item(i).data(Qt.ItemDataRole.UserRole))).name == dataset.MAIN)
    window.browser.files.setCurrentItem(item)
    assert wait_until(lambda: window.scan is not None and Path(window.scan.path).name == dataset.MAIN, 60)
    assert wait_until(lambda: manager.done)
    manager.callout.skip_button.click()                                              # explicit skip is allowed
    assert manager.index == 3
    # Esc inside a nested dialog ends the lesson and releases everything
    dialog = QDialog(window)
    dialog.show()
    _press_escape(dialog)
    assert wait_until(lambda: not manager.active)
    assert manager.highlight is None and manager.callout is None and not manager._timer.isActive()
    assert state.load()['resume_position'] == 3
    window.start_tutorial(state.load()['resume_position'])
    assert window.tutorial.index == 3
    _press_escape(window)
    assert wait_until(lambda: not window.tutorial.active)


def test_welcome_panel_and_settings_pages(window, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from spm_studio.tutorial import state
    window._maybe_onboard()
    panel = window._welcome
    assert panel is not None
    skip = panel.findChild(QPushButton, 'TutorialSkipWelcomeV0013')
    assert skip.text() == 'La science n’attend pas !'
    skip.click()
    assert window._welcome is None and state.load()['skipped']
    window._maybe_onboard()
    assert window._welcome is None                                                   # no nagging
    from spm_studio.ui.settings_dialog import SettingsDialog
    dialog = SettingsDialog(window, 'beta')
    page = dialog.findChild(type(dialog), None) or dialog
    beta = dialog.findChild(QPushButton, 'BetaActivateV0013')
    assert beta is not None and dialog.findChild(QPushButton, 'TutorialSettingsStartV0013') is not None
    assert dialog.findChild(QPushButton, 'UpdatesCheckV0013') is not None
    from spm_studio.beta.settings_pages import BetaPage
    page = dialog.findChild(BetaPage)
    page.key.setText('SPM-BETA-ABCDE-FGHJK-LMNPQ-RSTUV-WXYZ2-34567')
    beta.click()
    assert wait_until(lambda: 'beta service' in page.message.text().lower())       # not configured: clear words
    assert page.key.text() == ''                                                     # the key does not stay
    dialog.close()


def test_beta_page_activation_flow(window, fake_service):
    from spm_studio.ui.settings_dialog import SettingsDialog
    from spm_studio.beta.settings_pages import BetaPage
    dialog = SettingsDialog(window, 'beta')
    page = dialog.findChild(BetaPage)
    assert page.join.isVisibleTo(dialog) and not page.active.isVisibleTo(dialog)
    page.key.setText('SPM-BETA-ABCDE-FGHJK-LMNPQ-RSTUV-WXYZ2-34567')
    page.label.setText('Lab PC')
    page.activate.click()
    assert wait_until(lambda: 'active on this computer' in page.message.text())
    assert page.active.isVisibleTo(dialog) and '2 / 5' in page.account.text()
    assert not page.admin_button.isVisibleTo(dialog)                                 # role from the server
    dialog.close()


def test_assistant_states_and_extension_hooks(window):
    dock = window.ai_dock
    seen = []
    window.extension_api.assistantState.connect(seen.append)
    dock._running = True
    dock._set_busy(True)
    dock._activity('Running tool: read')
    dock._receive_delta('Hello')
    dock._settled()
    assert seen[:4] == ['thinking', 'working', 'talking', 'success']
    dock._running = True
    dock._error('provider down')
    assert seen[-1] == 'error'
    from spm_studio.beta.api import ExtensionAPI
    api = window.extension_api
    handle = api.for_extension({'id': 'demo-ext', 'permissions': ['settings_page', 'assistant_instructions']})
    from PySide6.QtWidgets import QLabel
    handle.add_settings_page('Demo page', lambda parent: QLabel('demo'))
    handle.set_assistant_instructions('be brief')
    assert api.assistant_instructions() == 'be brief'
    with pytest.raises(PermissionError):
        handle.open_todo_count()
    from spm_studio.ui.settings_dialog import SettingsDialog
    dialog = SettingsDialog(window, 'ext:demo-ext')
    assert 'ext:demo-ext' in dialog._page_keys
    dialog.close()
    api.cleanup('demo-ext')
    assert api.assistant_instructions() == '' and 'ext:demo-ext' not in api.settings_pages
    assert isinstance(api, ExtensionAPI)
