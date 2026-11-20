"""SPM Studio 0.0.7 — update inside the app window, assistant settings in two pages, and the
Literature page that connects Zotero and Consensus by itself.

The first part needs no Qt; the GUI part runs when PySide6 is installed (offscreen).
"""
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from spm_studio.core import updates

ROOT = Path(__file__).resolve().parents[1]

LINUX_TRANSCRIPT = """Python: 3.12.3 (/usr/bin/python3.12)
Requirement already satisfied: pip in ./venv/lib/python3.12/site-packages (24.0)
Collecting pip
  Downloading pip-25.3-py3-none-any.whl (1.8 MB)
Installing collected packages: pip
Successfully installed pip-25.3
Obtaining file:///home/u/.local/share/spm-studio-ai-app/releases/9.9.9/app
  Installing build dependencies: started
  Getting requirements to build editable: started
  Preparing metadata (pyproject.toml): started
Collecting numpy>=1.26
  Downloading numpy-2.3.4-cp312-cp312-manylinux_2_27_x86_64.whl (16.6 MB)
Collecting PySide6>=6.6
  Downloading pyside6-6.10.0-cp39-abi3-manylinux_2_28_x86_64.whl (558 kB)
Collecting scipy
  Using cached scipy-1.16.3-cp312-cp312-manylinux2014_x86_64.whl (35.7 MB)
Building wheels for collected packages: spm-studio
Installing collected packages: numpy, scipy, PySide6, spm-studio
Successfully installed PySide6-6.10.0 numpy-2.3.4 scipy-1.16.3 spm-studio-9.9.9
Standalone SPM Studio source: /home/u/.local/share/spm-studio-ai-app/releases/9.9.9/app/src/spm_studio/__init__.py
SMOKE ok    themes
SMOKE ok    menus
SMOKE PASSED
Release staged and tested: /home/u/.local/share/spm-studio-ai-app/releases/9.9.9
Standalone SPM Studio source: /home/u/.local/share/spm-studio-ai-app/releases/9.9.9/app/src/spm_studio/__init__.py
SMOKE ok    themes
SMOKE PASSED
SPM Studio 9.9.9 installed successfully.
Launch: /home/u/.local/bin/spm-studio
"""


# -------------------------------------------------------------- progress from output
def test_installer_output_becomes_a_progress_bar():
    progress = updates.InstallProgress(start=5)
    seen = [progress.percent]
    labels = []
    for line in LINUX_TRANSCRIPT.splitlines():
        if progress.feed(line):
            labels.append(progress.label)
        seen.append(progress.percent)
        assert not progress.success or 'installed successfully' in line or line.startswith('Launch')
    assert seen == sorted(seen), 'the bar never goes backwards'
    assert seen[0] == 5 and seen[-1] == 100 and progress.success and not progress.problem
    assert 16 < progress_at(LINUX_TRANSCRIPT, 'Collecting scipy') < 72        # the long pip part moves the bar
    assert progress_at(LINUX_TRANSCRIPT, 'SMOKE PASSED') >= 90
    for wanted in ('Installing the Python packages', 'Testing the new version', 'Activating the new version', 'Installed'):
        assert wanted in labels
    # Windows wording
    win = updates.InstallProgress()
    for line in ('Python: 3.12.7 (C:\\Python312\\python.exe)', 'Copying application files...',
                 'Creating the private Python environment...'):
        win.feed(line)
    assert win.percent == 12 and win.label == 'Creating its Python environment'


def progress_at(transcript, until):
    progress = updates.InstallProgress(start=5)
    for line in transcript.splitlines():
        progress.feed(line)
        if line.startswith(until):
            break
    return progress.percent


def test_failed_self_test_is_not_reported_as_installed():
    progress = updates.InstallProgress()
    for line in ('Python: 3.12.3', 'Successfully installed pip-25.3', 'SMOKE ok    themes',
                 'SMOKE FAIL  settings window', 'SMOKE FAILED: settings window'):
        progress.feed(line)
    assert not progress.success and progress.percent < 100 and 'SMOKE FAIL' in progress.problem
    partial = updates.InstallProgress()
    partial.feed('Partial release at /x/releases/9.9.9. Back it up / remove manually; refusing to overwrite.')
    assert 'Partial release' in partial.problem
    many = updates.InstallProgress()
    many.feed('Successfully installed pip-25.3')
    for _ in range(500):
        many.feed('Collecting something')
    assert many.percent <= 72                                   # pip lines alone never claim a later stage


# ------------------------------------------------------------- running the installer
def _script(tmp_path, body):
    path = tmp_path / 'fake_installer.py'
    path.write_text(body, encoding='utf8')
    return [sys.executable, '-u', str(path)]


def test_installer_runs_without_a_terminal_and_without_input(tmp_path):
    argv = _script(tmp_path, (
        'import os, sys\n'
        'print("Python: 3.12")\n'
        'sys.stdout.write("Downloading a\\rDownloading b\\r\\nCollecting c\\n"); sys.stdout.flush()\n'
        'print("stdin gives:", repr(sys.stdin.read()))\n'               # a prompt gets end-of-file, never hangs
        'print("unattended:", os.environ.get("PIP_NO_INPUT"), os.environ.get("SPM_STUDIO_IN_APP_UPDATE"))\n'
        'print("caf\\u00e9 \\u2713", file=sys.stderr)\n'
        'print("SPM Studio 9.9.9 installed successfully.")\n'))
    lines = []
    runner = updates.InstallRunner(argv, tmp_path, on_line=lines.append, env={'PYTHONIOENCODING': 'utf-8'})
    assert runner.run() == 0 and not runner.cancelled
    assert lines[:4] == ['Python: 3.12', 'Downloading a', 'Downloading b', 'Collecting c']
    assert "stdin gives: ''" in lines and 'unattended: 1 1' in lines and 'café ✓' in lines
    assert lines[-1] == 'SPM Studio 9.9.9 installed successfully.'
    failing = updates.InstallRunner(_script(tmp_path, 'import sys\nprint("boom")\nsys.exit(3)\n'), tmp_path,
                                    on_line=lines.append)
    assert failing.run() == 3
    missing = []
    assert updates.InstallRunner(['/no/such/program-xyz'], tmp_path, on_line=missing.append).run() == 127
    assert 'Could not start the installer' in missing[0]
    env = updates.installer_environment()
    assert env['PIP_NO_INPUT'] == '1' and env['PIP_PROGRESS_BAR'] == 'off' and env['PYTHONUTF8'] == '1'


def test_windows_carriage_return_redraws_do_not_create_phantom_blank_lines(tmp_path):
    # Python's Windows stdout can translate an explicit \r\n to \r\r\n.
    # Feed raw pipe bytes to reproduce the exact Windows failure on every OS.
    argv = _script(tmp_path, (
        'import sys\n'
        'sys.stdout.buffer.write(b"one\\rtwo\\r\\r\\nthree\\n")\n'
        'sys.stdout.buffer.flush()\n'))
    lines = []
    runner = updates.InstallRunner(argv, tmp_path, on_line=lines.append)
    assert runner.run() == 0
    assert lines == ['one', 'two', 'three']


@pytest.mark.skipif(os.name == 'nt', reason='process groups are checked on POSIX; Windows uses taskkill /T')
def test_cancel_stops_the_installer_and_what_it_started(tmp_path):
    marker = tmp_path / 'child_survived'
    argv = _script(tmp_path, (
        'import subprocess, sys, time\n'
        f'subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4); open({str(marker)!r}, \'w\').write(\'x\')"])\n'
        'print("started", flush=True)\n'
        'time.sleep(60)\n'))
    lines = []
    runner = updates.InstallRunner(argv, tmp_path, on_line=lines.append)
    result = {}
    thread = threading.Thread(target=lambda: result.update(code=runner.run()))
    thread.start()
    deadline = time.time() + 20
    while 'started' not in lines and time.time() < deadline:
        time.sleep(0.05)
    assert 'started' in lines
    started = time.time()
    runner.cancel()
    thread.join(20)
    assert not thread.is_alive() and result['code'] != 0 and runner.cancelled and time.time() - started < 15
    time.sleep(5)
    assert not marker.exists(), 'the program started by the installer was stopped too'


def test_unfinished_release_is_removed_but_nothing_else(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    releases = updates.releases_dir()
    assert str(tmp_path) in str(releases) and releases.name == 'releases'
    finished = releases / '0.0.6'
    partial = releases / '0.0.7'
    for folder in (finished, partial):
        (folder / 'app').mkdir(parents=True)
    (finished / 'READY').write_text('0.0.6\n')
    assert not updates.remove_partial_release('0.0.6') and finished.is_dir()      # finished: never
    assert updates.remove_partial_release('0.0.7') and not partial.exists()       # interrupted: yes
    assert not updates.remove_partial_release('0.0.7')                            # nothing left
    for bad in ('', '..', '../0.0.6', '0.0.6/app', '.', '/', '*'):
        assert not updates.remove_partial_release(bad)
    assert finished.is_dir() and (finished / 'READY').is_file()
    # never the release this very process runs from
    running = releases / '9.9.9'
    (running / 'venv').mkdir(parents=True)
    monkeypatch.setattr(sys, 'prefix', str(running / 'venv'))
    assert not updates.remove_partial_release('9.9.9') and running.is_dir()


def test_restart_uses_the_installed_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert updates.restart_argv() == [sys.executable, '-m', 'spm_studio']        # source checkout
    launcher = tmp_path / '.local' / 'bin' / 'spm-studio'
    launcher.parent.mkdir(parents=True)
    launcher.write_text('#!/bin/sh\n')
    assert updates.restart_argv() == [str(launcher)]
    monkeypatch.setattr(sys, 'platform', 'darwin')
    assert updates.restart_argv() == [str(launcher)]
    (tmp_path / 'Applications' / 'SPM Studio.app').mkdir(parents=True)
    assert updates.restart_argv() == ['open', '-n', str(tmp_path / 'Applications' / 'SPM Studio.app')]
    monkeypatch.setattr(sys, 'platform', 'win32')
    cmd = tmp_path / 'local' / 'SPMStudio' / 'bin' / 'spm-studio.cmd'
    cmd.parent.mkdir(parents=True)
    cmd.write_text('@echo off\n')
    assert updates.restart_argv()[-2:] == ['/c', str(cmd)]


class _Files(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b'x' * 300_000
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_download_reports_its_progress():
    server = HTTPServer(('127.0.0.1', 0), _Files)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        seen = []
        data = updates._get(f'http://127.0.0.1:{server.server_port}/a.zip', accept='application/zip',
                            progress=lambda done, total: seen.append((done, total)))
    finally:
        server.shutdown()
        server.server_close()
    assert len(data) == 300_000 and len(seen) >= 2
    assert seen[-1] == (300_000, 300_000) and [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_no_terminal_is_opened_by_the_update_window():
    source = (ROOT / 'src' / 'spm_studio' / 'ui' / 'update_dialog.py').read_text(encoding='utf8')
    assert 'launch_installer' not in source and 'open_terminal' not in source
    assert 'InstallRunner' in source and 'Restart now' in source and "'Later'" in source
    notes = (ROOT / 'CHANGELOG.md').read_text(encoding='utf8')
    assert '## 0.0.7 — ' in notes


# ================================================================== GUI (needs Qt)
@pytest.fixture
def qt_home(tmp_path, monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setenv('SPM_STUDIO_NO_UPDATE_CHECK', '1')
    monkeypatch.delenv('ZOTERO_DATA_DIR', raising=False)
    monkeypatch.delenv('CONSENSUS_API_KEY', raising=False)
    (tmp_path / 'home').mkdir()
    from spm_studio.ai import lit_store
    monkeypatch.setattr(lit_store, '_keyring', lambda: None)
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'config'))
    from spm_studio.core import paths
    paths.install_factory_modules()
    paths.install_factory_customization()
    return tmp_path, app


def wait_until(app, condition, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    app.processEvents()
    return bool(condition())


RESULT = {'repository': 'owner/repo', 'current': '0.0.6', 'latest': '9.9.9', 'tag': 'v9.9.9', 'update': True,
          'url': 'https://example.org/r', 'archive': 'https://example.org/a.zip', 'source': 'releases',
          'notes': [{'version': '9.9.9', 'notes': '- new things', 'published': ''}]}


def _fake_update(monkeypatch, tmp_path, body):
    source = tmp_path / 'update-source'
    source.mkdir(exist_ok=True)
    script = source / 'installer.py'
    script.write_text(body, encoding='utf8')

    def prepare(result, progress=None):
        if progress:
            progress(500_000, 1_000_000)
            progress(1_000_000, 1_000_000)
        return source
    monkeypatch.setattr(updates, 'prepare', prepare)
    monkeypatch.setattr(updates, 'installer_argv', lambda src: [sys.executable, '-u', str(script)])
    return source


def test_update_installs_in_the_window_then_offers_restart(qt_home, monkeypatch):
    tmp_path, app = qt_home
    from PySide6.QtWidgets import QMainWindow
    from spm_studio.ui import update_dialog
    _fake_update(monkeypatch, tmp_path, 'import time\n' + ''.join(
        f'print({line!r}, flush=True); time.sleep(0.01)\n' for line in LINUX_TRANSCRIPT.splitlines()))
    window = QMainWindow()
    dialog = update_dialog.UpdateDialog(window, dict(RESULT))
    dialog.show()
    assert dialog.install.isEnabled() and dialog.progress_box.isHidden() and dialog.restart.isHidden()
    assert '9.9.9 is available' in dialog.headline.text()
    dialog.install.click()
    assert dialog.installing and not dialog.progress_box.isHidden() and dialog.close_button.text() == 'Cancel update'
    assert wait_until(app, lambda: not dialog.installing, 60)
    assert dialog.headline.text() == 'SPM Studio 9.9.9 is installed' and dialog.bar.value() == 100
    assert not dialog.restart.isHidden() and dialog.close_button.text() == 'Later' and dialog.install.isHidden()
    assert 'Restart now, or later' in dialog.detail.text()
    # the installer's output is one click away, not in a terminal
    assert dialog.log.isHidden() and 'SMOKE PASSED' in dialog.log.toPlainText()
    dialog.details.click()
    assert not dialog.log.isHidden() and dialog.details.text() == 'Hide details'
    # "Later": the window stays open and says a restart is pending
    dialog.close_button.click()
    app.processEvents()
    assert not dialog.isVisible() and '9.9.9 is installed' in window.statusBar().currentMessage()
    # "Restart now": the launcher is started and this instance quits
    from types import SimpleNamespace
    started = []
    monkeypatch.setattr(update_dialog, 'QProcess', SimpleNamespace(
        startDetached=lambda program, args: started.append([program, *args]) or (True, 1)))
    quits = []
    monkeypatch.setattr(update_dialog, 'QTimer', SimpleNamespace(singleShot=lambda ms, fn: quits.append(fn)))
    window.show()
    dialog._restart_now()
    assert started == [updates.restart_argv()] and len(quits) == 1 and not window.isVisible()


def test_failed_update_keeps_the_current_version_and_shows_why(qt_home, monkeypatch):
    tmp_path, app = qt_home
    from spm_studio.ui import update_dialog
    partial = updates.releases_dir() / '9.9.9'
    _fake_update(monkeypatch, tmp_path,
                 'import sys, pathlib\n'
                 f'pathlib.Path({str(partial)!r}).mkdir(parents=True)\n'
                 'print("Python: 3.12", flush=True)\nprint("SMOKE FAIL  themes", flush=True)\n'
                 'print("SMOKE FAILED - nothing was activated.", flush=True)\nsys.exit(2)\n')
    dialog = update_dialog.UpdateDialog(None, dict(RESULT))
    dialog.show()
    dialog.install.click()
    assert wait_until(app, lambda: not dialog.installing, 60)
    assert dialog.headline.text() == 'The update could not be installed'
    assert 'SMOKE FAIL' in dialog.detail.text() and 'current version is unchanged' in dialog.detail.text()
    assert dialog.restart.isHidden() and dialog.install.isEnabled() and dialog.install.text() == 'Try again'
    assert not dialog.log.isHidden(), 'the reason is shown without having to look for it'
    assert not partial.exists(), 'the unfinished release is removed so that “Try again” can work'
    dialog.close()


def test_cancelling_an_update_stops_it(qt_home, monkeypatch):
    tmp_path, app = qt_home
    from spm_studio.ui import update_dialog
    _fake_update(monkeypatch, tmp_path, 'import time\nprint("Python: 3.12", flush=True)\ntime.sleep(120)\n')
    dialog = update_dialog.UpdateDialog(None, dict(RESULT))
    dialog.show()
    dialog.install.click()
    assert wait_until(app, lambda: 'Python: 3.12' in dialog.log.toPlainText(), 60)
    from types import SimpleNamespace
    buttons = update_dialog.QMessageBox.StandardButton
    monkeypatch.setattr(update_dialog, 'QMessageBox', SimpleNamespace(
        StandardButton=buttons, question=lambda *a, **k: buttons.Yes, information=lambda *a, **k: None))
    started = time.time()
    dialog.close_button.click()                       # “Cancel update”
    assert time.time() - started < 30 and not dialog.installing and dialog.isVisible()
    assert dialog.headline.text() == 'The update was cancelled' and dialog.close_button.text() == 'Close'
    assert wait_until(app, lambda: not dialog.installer.isRunning(), 30)
    dialog.close()


def test_assistant_settings_have_a_quick_start_and_an_advanced_page(qt_home, monkeypatch):
    tmp_path, app = qt_home
    from spm_studio.ai import setup_ui, cli_events
    from spm_studio.ai.config import load
    monkeypatch.setattr(setup_ui, 'detect_pi', lambda: [])
    monkeypatch.setattr(cli_events, 'detect', lambda key: '')
    dialog = setup_ui.SetupDialog(None)
    dialog.show()
    app.processEvents()
    assert [dialog.nav.item(i).text() for i in range(dialog.nav.count())] == ['Quick start', 'Advanced']
    assert dialog.sections.currentIndex() == 0
    assert list(dialog.cards) == ['managed', 'claude-code', 'codex', 'own-pi', 'api', 'off']
    # a new user lands on the guided setup, which says what to do next
    assert dialog.mode.currentIndex() == 1 and dialog.cards['managed']['radio'].isChecked()
    assert dialog.cards['managed']['frame'].property('selected') is True
    assert 'Start guided setup' in dialog.next_step.text()
    assert not dialog.cards['managed']['actions'].isHidden() and dialog.cards['codex']['actions'].isHidden()
    assert dialog.cards['own-pi']['frame'].isHidden()            # no Pi on this computer: the card is not offered
    # choosing a card selects the matching expert setting, and the other way round
    dialog.cards['codex']['radio'].click()
    assert dialog.mode.currentIndex() == 2 and dialog.agent_choice.currentData() == 'codex'
    assert 'not installed yet' in dialog.cards['codex']['status'].text()
    assert not dialog.cards['codex']['buttons']['install'].isHidden() and 'Install' in dialog.next_step.text()
    dialog.mode.setCurrentIndex(4)
    assert dialog.cards['off']['radio'].isChecked() and dialog.next_step.text() == 'Ready — click Save.'
    # the expert fields are all still there, on their own page
    dialog.cards['api']['radio'].click()
    dialog.cards['api']['buttons']['configure'].click()
    assert dialog.sections.currentIndex() == 1 and dialog.mode.currentIndex() == 3
    for name in ('provider', 'model', 'base', 'key', 'connection_list', 'fallback', 'judge', 'routing',
                 'autonomy', 'pi_existing', 'agent_path', 'agent_log'):
        assert hasattr(dialog, name), name
    assert not dialog.judge_box.isHidden()
    # saving "No assistant" from the quick page
    dialog.nav.setCurrentRow(0)
    dialog.cards['off']['radio'].click()
    dialog.save_button.click()
    assert load()['backend'] == 'none' and load()['configured'] is True
    assert 'switched off' in setup_ui.SetupDialog(None).current_summary.text()


def test_installed_agent_is_one_click_from_ready(qt_home, monkeypatch):
    tmp_path, app = qt_home
    from spm_studio.ai import setup_ui, cli_events
    from spm_studio.ai.config import load
    fake = tmp_path / 'claude'
    fake.write_text('#!/bin/sh\necho 2.1.0\n')
    fake.chmod(0o755)
    monkeypatch.setattr(setup_ui, 'detect_pi', lambda: [])
    monkeypatch.setattr(cli_events, 'detect', lambda key: str(fake) if key == 'claude-code' else '')
    monkeypatch.setattr(cli_events, 'version', lambda path: '2.1.0')
    dialog = setup_ui.SetupDialog(None)
    dialog.show()
    dialog.cards['claude-code']['radio'].click()
    card = dialog.cards['claude-code']
    assert 'is installed (2.1.0)' in card['status'].text() and card['buttons']['install'].isHidden()
    assert not card['buttons']['login'].isHidden() and dialog.next_step.text() == 'Ready — click Save.'
    if os.name != 'nt':
        dialog.save_button.click()
        assert load()['backend'] == 'claude-code' and load()['agent_executable'] == str(fake)


def test_literature_page_connects_zotero_with_one_click(qt_home, monkeypatch):
    tmp_path, app = qt_home
    from PySide6.QtWidgets import QMainWindow
    from test_v007_literature_connections import make_zotero
    from spm_studio.ai import literature
    from spm_studio.ai.config import load, save
    from spm_studio.ui.settings_dialog import SettingsDialog
    save({**load(), 'zotero_mode': 'off'})          # v0.0.12 default is 'auto'; start from a disconnected Zotero
    monkeypatch.setattr(literature, 'ZOTERO_LOCAL', 'http://127.0.0.1:9/api')
    monkeypatch.setattr(literature, 'ZOTERO_CONNECTOR', 'http://127.0.0.1:9/connector/ping')
    monkeypatch.setattr(SettingsDialog, '_general_page', lambda self: __import__('PySide6.QtWidgets').QtWidgets.QWidget())
    monkeypatch.setattr(SettingsDialog, '_library_page', lambda self: __import__('PySide6.QtWidgets').QtWidgets.QWidget())
    window = QMainWindow()
    dialog = SettingsDialog(window, 'literature')
    dialog.show()
    assert 'Not connected' in dialog.zotero_state.text() and not dialog.zotero_disconnect.isEnabled()
    # nothing on the computer: a clear sentence and the advanced choices open
    dialog.zotero_connect.click()
    assert wait_until(app, lambda: dialog.zotero_status.text().startswith('✗'))
    assert 'No Zotero library was found' in dialog.zotero_status.text() and dialog.zotero_advanced.isChecked()
    assert load()['zotero_mode'] == 'off'
    # with a library in the usual place: one click
    make_zotero(tmp_path / 'home' / 'Zotero')
    dialog.zotero_connect.click()
    assert wait_until(app, lambda: dialog.zotero_status.text().startswith('✓'))
    assert load()['zotero_mode'] == 'auto' and '2 items' in dialog.zotero_status.text()
    assert 'Connected' in dialog.zotero_state.text() and dialog.zotero_disconnect.isEnabled()
    dialog.zotero_test_button.click()
    assert wait_until(app, lambda: 'Connected — 2 items' in dialog.zotero_status.text())
    dialog.zotero_disconnect.click()
    assert load()['zotero_mode'] == 'off' and 'Not connected' in dialog.zotero_state.text()
    dialog.close()


def test_consensus_sign_in_happens_in_the_settings_window(qt_home, monkeypatch):
    tmp_path, app = qt_home
    from PySide6.QtWidgets import QMainWindow
    import test_v007_literature_connections as lit
    from spm_studio.ai import consensus
    from spm_studio.ai.config import load
    from spm_studio.ui import settings_dialog
    server = HTTPServer(('127.0.0.1', 0), lit._Consensus)
    lit._Consensus.state = {}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    monkeypatch.setattr(consensus, 'MCP_URL', base + '/mcp')
    monkeypatch.setattr(consensus, 'DISCOVERY_URL', base + '/.well-known/oauth-authorization-server')
    opened = []

    def browser(url):                                   # the user's browser, signing in successfully
        opened.append(url.toString())
        threading.Thread(target=lambda: lit._browser_signs_in(url.toString(), lit._Consensus.state)).start()
        return True
    from types import SimpleNamespace
    monkeypatch.setattr(settings_dialog, 'QDesktopServices', SimpleNamespace(openUrl=browser))
    monkeypatch.setattr(settings_dialog.SettingsDialog, '_general_page',
                        lambda self: __import__('PySide6.QtWidgets').QtWidgets.QWidget())
    monkeypatch.setattr(settings_dialog.SettingsDialog, '_library_page',
                        lambda self: __import__('PySide6.QtWidgets').QtWidgets.QWidget())
    try:
        dialog = settings_dialog.SettingsDialog(QMainWindow(), 'literature')
        dialog.show()
        assert 'Not connected' in dialog.consensus_state.text() and not dialog.consensus_enabled.isEnabled()
        assert dialog.consensus_signin.text() == 'Sign in to Consensus'
        dialog.consensus_signin.click()
        assert wait_until(app, lambda: 'Connected' in dialog.consensus_state.text(), 30), dialog.consensus_status.text()
        assert len(opened) == 1 and urllib.parse.urlparse(opened[0]).path == '/oauth/authorize/'
        assert consensus.signed_in() and load()['consensus_enabled'] is True
        assert dialog.consensus_progress.isHidden() and dialog.consensus_cancel.isHidden()
        assert dialog.consensus_enabled.isChecked() and dialog.consensus_signin.text() == 'Sign in again'
        dialog.consensus_test.click()
        assert wait_until(app, lambda: dialog.consensus_status.text().startswith('✓'), 30)
        dialog.consensus_signout.click()
        assert not consensus.signed_in() and load()['consensus_enabled'] is False
        assert 'Not connected' in dialog.consensus_state.text()
        # a sign-in the user abandons can be cancelled from the same place
        monkeypatch.setattr(settings_dialog, 'QDesktopServices', SimpleNamespace(openUrl=lambda url: True))
        dialog.consensus_signin.click()
        assert wait_until(app, lambda: not dialog.consensus_cancel.isHidden(), 30)
        dialog.consensus_cancel.click()
        assert wait_until(app, lambda: 'cancelled' in dialog.consensus_status.text(), 30)
        assert dialog.consensus_cancel.isHidden() and not consensus.signed_in()
        dialog.close()
    finally:
        server.shutdown()
        server.server_close()


def test_chat_runs_the_lookup_the_assistant_asked_for(qt_home, monkeypatch):
    tmp_path, app = qt_home
    from test_v007_literature_connections import make_zotero
    from spm_studio.ai import literature
    from spm_studio.ai.config import load, save
    from spm_studio.ui.main_window import MainWindow
    monkeypatch.setattr(literature, 'ZOTERO_LOCAL', 'http://127.0.0.1:9/api')
    make_zotero(tmp_path / 'home' / 'Zotero')
    conf = load()
    conf.update(zotero_mode='auto', backend='none', configured=True)
    save(conf)
    window = MainWindow()
    dock = window.ai_dock
    sent = []
    monkeypatch.setattr(dock, '_dispatch', lambda text: sent.append(text))
    dock.history = [{'role': 'user', 'content': 'What do I have on KPFM of graphene?'}]
    dock._running = True
    dock.partial = ('Let me check your library.\n<spm-literature>{"source": "zotero", "action": "search", '
                    '"query": "graphene"}</spm-literature>')
    dock._lit_rounds = 0
    dock._settled()                                             # the reply ends: the lookup starts by itself
    assert dock._running and not dock.send.isEnabled()
    assert wait_until(app, lambda: bool(sent), 30)
    assert sent[0].startswith('[SPM Studio literature results') and '"key": "AAAA1111"' in sent[0]
    # what the user sees: a short line, never the protocol text or the raw data
    html = dock._message_html('assistant', dock.history[-1]['content'])
    assert 'Looking up: Zotero search' in html and 'spm-literature' not in html
    shown = dock._message_html('user', sent[0])
    assert 'SPM Studio' in shown and 'Looked up: Zotero search' in shown and 'AAAA1111' not in shown
    # a reply without a request ends the turn; a runaway model is stopped after a few rounds
    dock.partial = 'You have one paper: Meyer and Glatzel (2019).'
    dock._running = True
    dock._settled()
    assert not dock._running and len(sent) == 1
    dock._lit_rounds = 99
    assert dock._literature_followup(dock.history[-2]['content'] if len(dock.history) > 1 else '') is False
    window.close()
