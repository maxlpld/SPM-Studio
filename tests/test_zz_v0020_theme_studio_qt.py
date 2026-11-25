"""Theme Studio in the real SPM Studio window (v0.0.20: built in).

Named to run last: it changes the application style sheet many times, and every change repolishes all live
widgets. Earlier test files leave closed windows alive; they are deleted first so these tests stay fast, and
nothing these tests change can reach another test file."""
import os
import time

import pytest


@pytest.fixture
def app_window(tmp_path, monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    for name in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('SPM_STUDIO_NO_UPDATE_CHECK', '1')
    monkeypatch.setenv('SPM_STUDIO_BETA_API', 'http://127.0.0.1:9')
    (tmp_path / 'home').mkdir()
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QMessageBox
    # a modal question would wait forever on a headless CI runner: answer "Yes" automatically
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: QMessageBox.StandardButton.Ok)
    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QCoreApplication, QEvent
    for widget in list(app.topLevelWidgets()):       # windows left by earlier test files (all finished)
        try:
            widget.hide()
            widget.deleteLater()                       # no closeEvent: nothing may ask a question here
        except RuntimeError:
            pass
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'qt'))
    from spm_studio.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    app.processEvents()
    from spm_studio import theme_studio
    studio = theme_studio.instance()
    assert studio is not None and studio.window is win
    app.processEvents()
    yield app, win, studio
    from PySide6.QtCore import QCoreApplication, QEvent
    win.close()
    win.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def wait(app, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_edit_preview_save_apply_cancel_and_restart(app_window):
    from spm_studio.theme_studio import model
    from spm_studio.theme_studio.runtime import MARK, Runtime
    app, win, studio = app_window
    base_sheet = app.styleSheet()
    ui = studio.open()
    ui.change(lambda p: model.set_prop(p, 'button', 'normal', 'background', '#3366FF80'))
    assert 'rgba(51, 102, 255, 128)' in ui.gallery.styleSheet()              # immediate preview (gallery)
    assert MARK not in app.styleSheet()                                       # app unchanged until preview/apply
    ui.live.setChecked(True)
    wait(app)
    assert 'rgba(51, 102, 255, 128)' in app.styleSheet()                      # temporary whole-app preview
    ui.live.setChecked(False)
    wait(app)
    assert MARK not in app.styleSheet()                                       # Cancel/stop → exactly as before
    ui.undo()
    assert model.get_prop(ui.profile, 'button', 'normal', 'background') is None
    ui.redo()
    from PySide6.QtWidgets import QInputDialog
    import unittest.mock as mock
    with mock.patch.object(QInputDialog, 'getText', return_value=('Lab blue', True)):
        assert ui.save_as()
    assert ui.slug == 'lab_blue' and 'lab_blue' in studio.store.list()
    ui.apply()
    wait(app)
    assert win.settings.value('theme') == 'studio_lab_blue'
    assert 'rgba(51, 102, 255, 128)' in app.styleSheet()
    # the normal theme menu re-applies the theme: the overlay comes back
    win._apply_theme('studio_lab_blue')
    wait(app)
    assert 'rgba(51, 102, 255, 128)' in app.styleSheet()
    # another theme → no overlay; the studio profile again → overlay
    win._apply_theme('graphite')
    wait(app)
    assert MARK not in app.styleSheet()
    studio.runtime.activate_profile('lab_blue')
    wait(app)
    # "restart": a new runtime with the same folders re-applies the active profile
    studio.runtime.shutdown()
    app.setStyleSheet(base_sheet)
    studio.runtime = Runtime(studio.store, win, studio.store.root / 'prefs.json')
    wait(app)
    assert 'rgba(51, 102, 255, 128)' in app.styleSheet()
    ui.close()


def test_pick_mode_never_runs_the_control(app_window):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    app, win, studio = app_window
    ui = studio.open()
    fired = []
    danger = QPushButton('Start acquisition', win)
    danger.setProperty('primary', True)
    danger.clicked.connect(lambda: fired.append(True))
    danger.show()
    picked = []
    ui.picker.picked.connect(lambda role, w: picked.append(role))
    ui.pick_button.setChecked(True)
    QTest.mouseClick(danger, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    wait(app)
    assert fired == [] and picked == ['button.primary'] and ui.role == 'button.primary'
    QTest.keyClick(ui, Qt.Key.Key_Escape)
    wait(app)
    assert not ui.picker.active and not ui.pick_button.isChecked()
    QTest.mouseClick(danger, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    assert fired == [True]                                                    # normal again after Esc
    ui.close()


def test_svg_skin_import_renders_and_keeps_buttons_working(app_window, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    from spm_studio.theme_studio import svgskin
    app, win, studio = app_window
    ui = studio.open()
    before = ui.gallery.styleSheet()
    ui.install_demo()
    assert 'Imported' in ui.report.toPlainText() and ui.profile['skin']
    sheet = ui.gallery.styleSheet()
    assert sheet != before and 'border-image: url(' in sheet and '#ThemePreview QPushButton {' in sheet
    folder = studio.store.skins_dir / ui.profile['skin']
    assert list((folder / '.raster').glob('button__normal__*@2x.png'))        # HiDPI copies
    button = next(b for b in ui.gallery.findChildren(QPushButton) if b.text() == 'Run')
    clicks = []
    button.clicked.connect(lambda: clicks.append(1))
    QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert clicks == [1]                                                      # still a normal button
    # export reflects the installed skin; a broken package changes nothing
    pkg = tmp_path / 'out.zip'
    svgskin.export_template(pkg, 'x', ui.profile, ui.tokens(), None, svgskin.skin_files(folder))
    bad = tmp_path / 'bad.zip'
    import zipfile
    with zipfile.ZipFile(pkg) as src, zipfile.ZipFile(bad, 'w') as dst:
        for name in src.namelist():
            if name != 'svg/panel/normal.svg':
                dst.writestr(name, src.read(name))
    skin_before = ui.profile['skin']
    assert ui.import_skin_path(bad) is False
    assert 'Missing required file svg/panel/normal.svg' in ui.report.toPlainText()
    assert ui.profile['skin'] == skin_before
    ui.close()


def test_role_detection(app_window):
    from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QProgressBar, QPushButton
    from spm_studio.theme_studio.runtime import role_of
    log = QPlainTextEdit()
    log.setReadOnly(True)
    delete = QPushButton()
    delete.setProperty('destructive', True)
    assert role_of(QPushButton()) == 'button' and role_of(delete) == 'button.destructive'
    assert role_of(QLineEdit()) == 'input' and role_of(log) == 'log' and role_of(log.viewport()) == 'log'
    assert role_of(QProgressBar()) == 'progress.track'
