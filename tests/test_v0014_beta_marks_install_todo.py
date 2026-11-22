"""v0.0.14: BETA marks, the beta install works like an update, simpler to-do window, shipped beta service address."""
import hashlib
import json
import os
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name, folder in (('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache')):
        monkeypatch.setenv(name, str(tmp_path / folder))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('SPM_STUDIO_BETA_NO_KEYRING', '1')
    monkeypatch.setenv('SPM_STUDIO_BETA_API', 'http://127.0.0.1:9')
    (tmp_path / 'home').mkdir()
    return tmp_path


def test_shipped_beta_service_address():
    data = json.loads((ROOT / 'src/spm_studio/update_config.json').read_text())
    assert data['beta_api'] == 'https://spm-beta.spm-beta.workers.dev' and data['extension_signing_keys']


# ---------------------------------------------------------------- a fake beta service that serves a signed release
def make_release(folder: Path, secret: bytes):
    import base64
    from spm_studio.beta import ed25519, extensions
    archive = folder / 'demo-ext-1.0.0.zip'
    descriptor = {'id': 'demo-ext', 'name': 'Demo', 'vendor': 'tests', 'version': '1.0.0', 'core_api': '>=1,<2',
                  'entry': 'demo_pkg:activate', 'permissions': ['settings_page']}
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('extension.json', json.dumps(descriptor))
        zf.writestr('demo_pkg/__init__.py', 'def activate(api):\n    pass\n')
        zf.writestr('demo_pkg/padding.bin', os.urandom(300_000))            # several progress steps
    data = archive.read_bytes()
    manifest = dict(descriptor, changelog='First demo release', artifact={
        'name': archive.name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
        'download_path': f'/v1/beta/releases/1.0.0/asset/{archive.name}'})
    sig = base64.b64encode(ed25519.sign(secret, extensions.canonical(manifest))).decode()
    return manifest, sig, data


class Service(BaseHTTPRequestHandler):
    release = None

    def log_message(self, *a):
        pass

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length'] or 0))
        if self.path in ('/v1/auth/redeem', '/v1/auth/refresh'):
            return self._json(200, {'access_token': 'A' * 40, 'refresh_token': 'R' * 60, 'expires_in': 900,
                                    'account': {'role': 'admin', 'label': 'Owner', 'active_devices': 1,
                                                'max_devices': 0}})
        self._json(404, {'error': 'NOT_FOUND'})

    def do_GET(self):
        manifest, sig, data = Service.release
        if self.path == '/v1/auth/me':
            return self._json(200, {'role': 'admin', 'active_devices': 1, 'max_devices': 0})
        if self.path == '/v1/beta/releases/latest':
            return self._json(200, {'manifest': manifest, 'signature': sig})
        if self.path == manifest['artifact']['download_path']:
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            for i in range(0, len(data), 65536):
                self.wfile.write(data[i:i + 65536])
            return
        self._json(404, {'error': 'NOT_FOUND'})


@pytest.fixture
def service(home, monkeypatch, tmp_path):
    import secrets
    from spm_studio.beta import client, ed25519
    secret = secrets.token_bytes(32)
    monkeypatch.setattr(client, 'signing_keys', lambda: [ed25519.public_key(secret)])
    Service.release = make_release(tmp_path, secret)
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Service)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv('SPM_STUDIO_BETA_API', f'http://127.0.0.1:{httpd.server_address[1]}')
    yield Service.release
    httpd.shutdown()
    httpd.server_close()


def test_download_reports_progress(service):
    from spm_studio.beta import client, extensions
    session = client.Session()
    session.redeem('SPM-BETA-ABCDE-FGHJK-LMNPQ-RSTUV-WXYZ2-34567', 'PC')
    manifest = session.latest_release()
    steps = []
    path = session.download(manifest, progress=lambda done, total: steps.append((done, total)))
    assert len(steps) >= 3 and steps[-1][0] == manifest['artifact']['size']
    assert all(a[0] <= b[0] for a, b in zip(steps, steps[1:]))
    assert extensions.install_archive(path, manifest)['id'] == 'demo-ext'


# ---------------------------------------------------------------- Qt
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


def test_extension_pages_carry_the_beta_mark(window):
    from PySide6.QtWidgets import QLabel
    from spm_studio.ui.settings_dialog import SettingsDialog
    handle = window.extension_api.for_extension({'id': 'demo-ext', 'permissions': ['settings_page']})
    handle.add_settings_page('Demo page', lambda parent: QLabel('demo content'))
    assert handle.beta_label('My tool') == 'My tool  · BETA'
    assert handle.beta_badge().text() == 'BETA'
    dialog = SettingsDialog(window, 'ext:demo-ext')
    labels = [dialog.nav.item(i).text() for i in range(dialog.nav.count())]
    assert 'Demo page  · BETA' in labels                                          # marked in the page list
    badge = dialog.findChild(QLabel, 'BetaBadgeV0014')
    assert badge is not None and badge.text() == 'BETA'                           # and on the page itself
    dialog.close()
    window.extension_api.cleanup('demo-ext')


def test_beta_activation_checks_and_installs_like_an_update(window, service, monkeypatch):
    from spm_studio.beta.settings_pages import BetaInstallDialog, BetaPage
    from spm_studio.ui import update_dialog
    from spm_studio.ui.settings_dialog import SettingsDialog
    restarted = []
    monkeypatch.setattr(update_dialog, 'restart_app', lambda w=None: restarted.append(w))
    dialog = SettingsDialog(window, 'beta')
    page = dialog.findChild(BetaPage)
    texts = ' '.join(label.text() for label in page.join.findChildren(type(page.service_label)))
    assert 'Step 1' in texts and 'Step 2' in texts and 'Step 3' in texts
    assert page.service_label.text().startswith('Beta service: http://127.0.0.1:')
    page.key.setText('SPM-BETA-ABCDE-FGHJK-LMNPQ-RSTUV-WXYZ2-34567')
    page.activate.click()
    # activation automatically looks for the private extension
    assert wait_until(lambda: page.manifest is not None and not page._workers)
    assert 'Install or update' in page.message.text() and page.install_button.isEnabled()
    assert page.admin_button.isVisibleTo(dialog)                                   # role from the server
    install = BetaInstallDialog(page, page.session, page.manifest)
    install.show()
    install.go.click()
    assert wait_until(lambda: install.installed)
    assert install.bar.value() == 100 and install.restart.isVisible() and install.later.text() == 'Later'
    assert 'SHA-256' in install.log.toPlainText() and 'Installed in' in install.log.toPlainText()
    install.restart.click()
    assert restarted == [window]
    dialog.close()


def test_simple_todo_window(window, home):
    from PySide6.QtCore import Qt
    win = window.documents.open_todo()
    assert win.empty.isVisible() and not win.list.isVisible()                     # explains what to do
    assert not win.panel.isVisible()
    win.quick.setText('Line profile across the step')
    win.add_from_quick()
    assert win.list.isVisible() and not win.empty.isVisible() and win.list.count() == 1
    assert win.tabs.tabText(0) == 'Tasks (1)'
    win.list.setCurrentRow(0)
    assert win.panel.isVisible() and 'Line profile' in win.detail_title.text()
    win.details.setPlainText('scan 0024, Z forward')
    win.list.item(0).setCheckState(Qt.CheckState.Checked)
    assert wait_until(lambda: win.data['tasks'][0]['done'])
    assert wait_until(lambda: win.tabs.tabText(0) == 'Tasks')
    win.delete_button.click()
    assert win.data['tasks'] == [] and win.empty.isVisible()
    win.close()
