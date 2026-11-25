"""v0.0.20: projects + crash recovery, Files panel multi-selection, instant channel switching, Compare results
redesign, Settings (lazy pages, one place per option), Theme Studio built in, Windows freeze fixes."""
import json
import os
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------- pure project format (no Qt)
def test_project_document_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    from spm_studio.core import project as proj
    from spm_studio.core.models import ImageStyle, ProcessingStep, ROI, Geometry
    from spm_studio.core.cropping import CropRegion
    style = ImageStyle(colormap='afmhot', range_mode='manual', low=-1.0, high=2.0, gamma=1.3)
    assert proj.style_from_dict(proj.style_to_dict(style)) == style
    steps = [ProcessingStep('plane', {'order': 1}), ProcessingStep('median', {'size': 3}, False)]
    assert proj.steps_from_list(json.loads(json.dumps(proj.steps_to_list(steps)))) == steps
    geom = Geometry(shape=(64, 64), size_m=(1e-8, 1e-8))
    crop = CropRegion(0.1, 0.2, 0.7, 0.9, geom)
    back = proj.crop_from_dict(json.loads(json.dumps(proj.crop_to_dict(crop))))
    assert (back.left, back.top, back.right, back.bottom) == (0.1, 0.2, 0.7, 0.9) and back.reference == geom
    roi = ROI('line', ((1.0, 2.0), (30.5, 40.0)))
    assert proj.roi_from_dict(roi.to_dict()) == roi
    folder = tmp_path / 'project'
    (folder / 'sub').mkdir(parents=True)
    scan = folder / 'sub' / 'a.sxm'
    scan.write_bytes(b'x')
    stored = proj.to_stored_path(str(scan), folder)
    assert stored == 'sub/a.sxm'
    assert proj.from_stored_path(stored, folder) == str(scan.resolve())
    outside = tmp_path / 'b.sxm'
    assert proj.to_stored_path(str(outside), folder) == str(outside)
    key = (str(scan), 'Z', 'forward')
    assert proj.key_from_text(proj.key_text(key)) == key


def test_project_file_is_atomic_with_backup(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    from spm_studio.core import project as proj
    folder = tmp_path / 'p'
    folder.mkdir()
    doc = proj.new_document('My project', folder)
    proj.save_project(folder, doc)
    assert proj.is_project_folder(folder) and proj.load_project(folder)['name'] == 'My project'
    doc['name'] = 'Second'
    proj.save_project(folder, doc)
    assert (folder / (proj.PROJECT_FILE + '.bak')).is_file()
    # a damaged file (power cut while writing) falls back to the previous version
    (folder / proj.PROJECT_FILE).write_text('{ broken', encoding='utf8')
    assert proj.load_project(folder)['name'] == 'My project'
    assert not list(folder.glob('*.tmp'))
    newer = dict(doc, version=proj.VERSION + 1)
    proj.write_json_atomic(folder / proj.PROJECT_FILE, newer)
    with pytest.raises(ValueError):
        proj.load_project(folder)
    state = proj.save_state(open=[{'folder': str(folder)}], active=0, clean_exit=False)
    assert proj.load_state()['open'][0]['folder'] == str(folder) and state['clean_exit'] is False


# ---------------------------------------------------------------------- Qt
@pytest.fixture
def home(tmp_path, monkeypatch):
    for name, folder in (('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache')):
        monkeypatch.setenv(name, str(tmp_path / folder))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('SPM_STUDIO_BETA_NO_KEYRING', '1')
    monkeypatch.setenv('SPM_STUDIO_BETA_API', 'http://127.0.0.1:9')
    monkeypatch.setenv('SPM_STUDIO_NO_UPDATE_CHECK', '1')
    monkeypatch.setenv('SPM_STUDIO_NO_ONBOARDING', '1')
    (tmp_path / 'home').mkdir()
    return tmp_path


@pytest.fixture
def app(home):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(home / 'qt'))
    from spm_studio.shared.appearance import BUILTIN_THEMES, apply_theme
    apply_theme(BUILTIN_THEMES['graphite'], application)
    return application


@pytest.fixture
def window(app):
    from spm_studio.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1450, 900)
    win.show()
    app.processEvents()
    yield win
    win.close()
    app.processEvents()


def wait_until(condition, timeout=20.0):
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return bool(condition())


def make_scans(folder, names=('one', 'two', 'three'), channels=4):
    from test_fast_scan_opening import create_large_sparse_sxm
    folder.mkdir(parents=True, exist_ok=True)
    return [Path(create_large_sparse_sxm(folder / f'{n}.sxm', nx=48, ny=48, channels=channels)).resolve()
            for n in names]


def test_settings_open_fast_with_lazy_pages_and_no_duplicates(window, app):
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtGui import QFontMetrics
    from spm_studio.ui.settings_dialog import SettingsDialog, PAGES
    dialog = SettingsDialog(window, 'general')
    assert dialog._built == {'general'}                       # only the page shown is built
    assert dialog.stack.widget(1).widget() is None
    metrics = QFontMetrics(dialog.nav.font())
    widest = max(metrics.horizontalAdvance(dialog.nav.item(i).text()) for i in range(dialog.nav.count()))
    assert dialog.nav.width() >= widest + dialog.nav.iconSize().width() + 20   # labels never cut
    texts = [b.text() for b in dialog.findChildren(QPushButton)]
    for duplicate in ('Check for updates…', 'Refresh tools', 'Restore built-in tools…', 'Open scripts folder',
                      'Open customization folder', 'Open project page'):
        assert duplicate not in texts, duplicate                 # each lives on its own page now
    assert not hasattr(dialog, 'theme_combo')                     # the theme is on Appearance only
    assert dialog.reopen_last.isChecked() and dialog.autosave.value() == 15
    dialog.show_page('appearance')
    assert 'appearance' in dialog._built and dialog.theme_combo.findData('light_studio') >= 0
    assert dialog.findChild(QPushButton, 'OpenThemeStudio') is not None
    assert dialog.outline_enabled is not None and dialog.full_help is not None
    dialog.show_page('library')
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData('scripts'))
    assert dialog.lib_restore.isVisibleTo(dialog)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData('profiles'))
    assert not dialog.lib_restore.isVisibleTo(dialog)
    dialog.show_page('about')
    about = [b.text() for b in dialog.stack.currentWidget().widget().findChildren(QPushButton)]
    assert 'Check for updates…' not in about and 'Release notes' not in about
    dialog.build_all()
    assert dialog._built == {key for key, *_ in PAGES}
    dialog.close()


def test_theme_studio_is_built_in(window, app):
    import sys
    from spm_studio import theme_studio
    from spm_studio.shared import appearance
    studio = theme_studio.instance()
    assert studio is not None and studio.window is window
    assert appearance.apply_theme == studio.runtime._apply_theme_wrapper   # overlay re-added on every theme
    assert sys.modules['spm_beta_themes'].BUILTIN is True                   # beta copy not activated
    assert sys.modules['spm_beta_themes'].activate(None) is None
    assert theme_studio.root().is_dir() and theme_studio.root().parent.name == 'customization'
    win = studio.open()
    app.processEvents()
    assert win.isVisible() and 'beta' not in win.windowTitle().lower()
    win.close()
    # a profile becomes a normal theme and its overlay is applied with it
    from spm_studio.theme_studio import model
    from spm_studio.shared.appearance import BUILTIN_THEMES
    profile = model.new_profile('Lab theme', BUILTIN_THEMES['graphite'])
    model.set_prop(profile, 'button', 'normal', 'background', '#123456')
    slug = studio.store.save(profile)
    studio.runtime.activate_profile(slug)
    assert window.settings.value('theme') == f'studio_{slug}'
    assert wait_until(lambda: 'Theme Studio — generated overlay' in app.styleSheet(), 3)
    assert studio.active_profile_name() == 'Lab theme'
    window._apply_theme('graphite')
    assert wait_until(lambda: 'Theme Studio — generated overlay' not in app.styleSheet(), 3)


def test_files_panel_buttons_and_shift_multi_selection(window, app, home):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    scans = make_scans(home / 'data_scans')
    panel = window.browser
    # pictogram buttons, visible (no "…" menu)
    for button in (panel.export_selection_button, panel.remove_file_button, panel.clear_files_button):
        assert button.isVisibleTo(window) and not button.icon().isNull() and button.text() == ''
    assert not hasattr(panel, 'more_button')
    for path in scans:
        window._add_file(path)
    assert wait_until(lambda: window.scan is not None)
    assert panel.files.currentRow() == 0
    # hold Shift: ↓ browses without selecting, Enter picks the scan shown
    window.viewer.setFocus()
    QTest.keyClick(window.viewer, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(window.viewer, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(window.viewer, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(window.viewer, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert panel.files.currentRow() == 2
    assert sorted(panel.selected_paths()) == sorted([str(scans[0]), str(scans[2])])
    # (QTest releases Shift after every click; a user keeps holding it — the selection is the same)
    QTest.keyRelease(window.viewer, Qt.Key.Key_Shift)
    app.processEvents()
    assert not panel._marking and len(panel.selected_paths()) == 2       # the picked scans stay selected
    assert panel.mark_hint.isVisibleTo(window) and '2 scans selected' in panel.mark_hint.text()
    # while Shift is held the hint says so
    panel.begin_marking()
    assert panel._marking and 'Selecting: 2' in panel.mark_hint.text()
    panel.end_marking()
    assert '2 selected' in panel.file_count.text()
    window.remove_scans(panel.selected_paths(), confirm=False)
    assert [panel.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(panel.files.count())] == [str(scans[1])]
    assert all(p.exists() for p in scans)                                 # never deleted from disk
    window.clear_scan_list(confirm=False)
    assert panel.files.count() == 0 and window.scan is None and not panel.clear_files_button.isEnabled()


def test_channel_switch_never_shows_the_previous_channel(window, app, home):
    scans = make_scans(home / 'ch', names=('multi',), channels=4)
    window._add_file(scans[0])
    assert wait_until(lambda: window.scan is not None)
    active = window._current_channel
    others = [c for c in window.scan.channels if c != active][:2]
    window.inspector.set_visible_channels([active] + others)
    assert wait_until(lambda: window._viewer_shows is not None and len(window._secondary_prepared) >= 1)
    first = window._viewer_shows
    assert first[1] == active
    old_image = window.viewer.image
    target = next(c for c in others if c in window._secondary_prepared)
    window.inspector.channel.setCurrentText(target)
    # right after the click: the new channel (its thumbnail) or an empty frame — never the old image
    assert window.viewer.image is not old_image
    assert window._viewer_shows in (None, (first[0], target, first[2]))
    assert window.viewer_title.text() == window.channel_title(target)
    # the channel we left keeps its picture in its tile at once
    holder, view = window._secondary_views[first[1]]
    assert view.image is not None
    assert wait_until(lambda: window._viewer_shows == (first[0], target, first[2]) and window.processed is not None)
    # back again: instant, from the cache
    window.inspector.channel.setCurrentText(first[1])
    assert window._viewer_shows == first and window.viewer.image is not None


def test_projects_save_restore_and_switch_without_interference(window, app, home):
    from PySide6.QtCore import Qt
    from spm_studio.core import project as proj
    from spm_studio.core.models import ImageStyle
    a_scans = make_scans(home / 'A', names=('a1', 'a2'))
    b_scans = make_scans(home / 'B', names=('b1',))
    slot_a = window.projects.open_folder(home / 'A')
    assert slot_a is not None and wait_until(lambda: window.browser.files.count() == 2)
    assert wait_until(lambda: window.scan is not None)
    key = (str(window.scan.path), window._current_channel, window.inspector.selected_trace())
    window.styles[key] = ImageStyle(colormap='afmhot', gamma=1.7)
    window.browser.files.setCurrentRow(1)
    assert wait_until(lambda: window.scan is not None and window.scan.path == a_scans[1])
    slot_b = window.projects.open_folder(home / 'B')
    assert wait_until(lambda: window.browser.files.count() == 1)
    assert window.projects.tabs.count() == 2 and window.projects.tabs.isVisibleTo(window)
    assert window.styles.get(key) is None                                  # nothing leaks into project B
    assert (home / 'A' / proj.PROJECT_FILE).is_file() or wait_until(
        lambda: (home / 'A' / proj.PROJECT_FILE).is_file(), 3)
    window.projects.activate(0)
    assert wait_until(lambda: window.browser.files.count() == 2)
    assert window.styles[key].colormap == 'afmhot'                         # A comes back exactly
    assert wait_until(lambda: window.scan is not None and window.scan.path == a_scans[1])
    # close (= what the next start reads), then a new window restores the open projects
    window.projects.shutdown()
    saved = proj.load_project(home / 'A')
    assert saved['current'] == 'a2.sxm' and saved['scans'] == ['a1.sxm', 'a2.sxm']
    assert any('afmhot' in json.dumps(v) for v in saved['state']['styles'].values())
    state = proj.load_state()
    assert state['clean_exit'] is True and [e['folder'] for e in state['open']] == [str(home / 'A'), str(home / 'B')]
    from spm_studio.ui.main_window import MainWindow
    other = MainWindow()
    try:
        assert other.projects.restore_at_start()
        assert wait_until(lambda: other.browser.files.count() == 2 and other.scan is not None)
        assert other.scan.path == a_scans[1] and other.projects.tabs.count() == 2
        assert other.styles[key].colormap == 'afmhot'
    finally:
        other.projects.timer.stop()
        other.close()


def test_unsaved_session_is_recovered_after_a_crash(window, app, home):
    from spm_studio.core import project as proj
    scans = make_scans(home / 'loose', names=('x1', 'x2'))
    for path in scans:
        window._add_file(path)
    assert wait_until(lambda: window.scan is not None)
    window.projects.autosave()
    window.projects._writer.flush()
    assert proj.read_json(proj.session_file())['scans'] == [str(p) for p in scans]
    proj.save_state(open=[{'folder': None}], active=0, clean_exit=False)    # what a crash leaves behind
    from spm_studio.ui.main_window import MainWindow
    other = MainWindow()
    try:
        assert other.projects.restore_at_start()
        assert wait_until(lambda: other.browser.files.count() == 2)
        assert other.projects.current().folder is None
    finally:
        other.projects.timer.stop()
        other.close()


def test_compare_results_groups_quantities_and_draws_them(app, tmp_path):
    from spm_studio.ui.research_compare import CompareDialog, collect, stats

    class Store:
        def __init__(self, runs):
            self._runs = runs

        def runs(self):
            return self._runs

    def run(rid, scan, value, created, preferred=False, extra=()):
        return {'result_id': rid, 'scan_id': scan, 'source_path': str(tmp_path / f'{scan}.sxm'),
                'module_id': 'lattice_measurements', 'status': 'completed', 'created_at': created,
                'preferred': preferred, 'run_folder': str(tmp_path / rid),
                'measurements': [{'key': 'a (nm)', 'table': 'Lattice', 'value': value, 'row': {'type': 'KBr'}},
                                 {'key': 'index', 'table': 'Lattice', 'value': 3}, *extra]}
    runs = [run('r1', 's1', 0.40, '2026-11-02T10:00'), run('r0', 's1', 0.55, '2026-11-01T10:00'),
            run('r2', 's2', 0.42, '2026-11-01T10:00'), run('r3', 's3', 0.41, '2026-11-01T09:00')]
    groups = collect(runs)
    assert list(groups) == [('lattice_measurements', 'Lattice', 'a (nm)', 'nm')]   # no "index" column
    assert sorted(e['value'] for e in groups[list(groups)[0]]) == [0.40, 0.41, 0.42]   # latest per scan
    assert len(collect(runs, latest_only=False)[list(groups)[0]]) == 4
    assert stats([1, 2, 3])['std'] == pytest.approx(1.0)
    dialog = CompareDialog(None, store=Store(runs))
    dialog.show()
    app.processEvents()
    assert dialog.current_group() == list(groups)[0] and dialog.table.rowCount() == 3
    assert len(dialog.chart.points) == 3 and 'n = 3' in dialog.summary.text() and 'mean 0.41 nm' in dialog.summary.text()
    from PySide6.QtCore import Qt
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert len(dialog.chart.points) == 2 and 'n = 2' in dialog.summary.text()
    csv_path = dialog.export_csv(str(tmp_path / 'c.csv'))
    lines = Path(csv_path).read_text(encoding='utf8').splitlines()
    assert lines[0].startswith('scan,detail,quantity,value,unit') and len(lines) == 3
    svg = dialog.save_chart(str(tmp_path / 'c.svg'))
    assert '<svg' in Path(svg).read_text(encoding='utf8')
    png = dialog.save_chart(str(tmp_path / 'c.png'))
    assert Path(png).stat().st_size > 1000
    dialog.close()
    empty = CompareDialog(None, store=Store([]))
    assert empty.empty.isVisibleTo(empty) or not empty._split.isVisibleTo(empty)
    assert 'No results to compare yet' in empty.empty.text()
    empty.close()


def test_folder_poller_reports_changes_off_the_gui_thread(app, tmp_path):
    import threading
    from spm_studio.ui.jobs import FolderPoller
    state = {'sig': 1}
    threads = []

    def signature():
        threads.append(threading.current_thread().name)
        return state['sig']
    poller = FolderPoller(signature, 0.05)
    seen = []
    poller.changed.connect(seen.append)
    poller.start()
    state['sig'] = 2
    assert wait_until(lambda: seen, 3) and seen[0] == 2
    assert 'spm-folder-poller' in threads
    poller.reference = 2
    count = len(seen)
    time.sleep(0.2)
    app.processEvents()
    assert len(seen) == count                                               # quiet once taken into account
    poller.stop()


def test_freeze_recorder_is_off_in_tests_and_writes_reports(app, home, monkeypatch):
    from spm_studio.shared import watchdog
    assert watchdog.install() is None                                       # headless: never runs by itself
    assert watchdog.report_path().parent.name == 'logs'
    monkeypatch.setenv('SPM_STUDIO_WATCHDOG', '1')
    dog = watchdog.install()
    try:
        assert dog is not None
        dog._write(1.7, '  File "x.py", line 1, in slow\n    time.sleep(2)\n', __import__('datetime').datetime.now())
        text = watchdog.report_path().read_text(encoding='utf8')
        assert 'not responding for 1.7 s' in text and 'time.sleep' in text
    finally:
        watchdog.shutdown()
