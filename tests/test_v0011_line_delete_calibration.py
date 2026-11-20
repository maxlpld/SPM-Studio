"""v0.0.11: delete the selected line (renumber, keep colours) and the microscope calibration tool."""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'scripts' / 'microscope_calibration'


# ------------------------------------------------------------------ microscope calibration tool
def test_calibration_tool_is_bundled_and_valid():
    from spm_studio.core.registry import load_manifest
    manifest = load_manifest(TOOL / 'module.json')
    assert manifest.name.startswith('Microscope X/Y calibration')
    for name in ('module.py', 'calibration_core.py', 'calibration_plots.py', 'README.md', 'test_module.py'):
        assert (TOOL / name).is_file(), name
    readme = (TOOL / 'README.md').read_text(encoding='utf8')
    assert 'Thermal drift' in readme and 'Hinaut' in readme


def test_calibration_tool_own_tests_pass():
    """Synthetic lattices with known calibration error and drift, plus a full run on SXM files.

    With PySide6 installed, the before → after figure must come from the Export-panel renderer.
    """
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen',
               PYTHONPATH=os.pathsep.join([str(ROOT / 'src'), os.environ.get('PYTHONPATH', '')]))
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                             str(TOOL / 'test_module.py')], cwd=str(ROOT / 'scripts'), env=env,
                            capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert ' passed' in result.stdout


def test_new_tool_is_offered_once_to_existing_installs(tmp_path, monkeypatch):
    from spm_studio.core import paths
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    monkeypatch.setattr(paths, 'scripts_dir', lambda: scripts)
    assert paths.install_new_factory_modules() == ['microscope_calibration: new tool installed']
    assert (scripts / 'microscope_calibration' / 'module.json').is_file()
    # a user who deletes it does not get it back
    import shutil
    shutil.rmtree(scripts / 'microscope_calibration')
    assert paths.install_new_factory_modules() == []
    assert not (scripts / 'microscope_calibration').exists()
    assert json.loads((scripts / '.factory_new_modules.json').read_text()) == ['microscope_calibration']


def test_existing_custom_copy_is_never_overwritten(tmp_path, monkeypatch):
    from spm_studio.core import paths
    scripts = tmp_path / 'scripts'
    (scripts / 'microscope_calibration').mkdir(parents=True)
    (scripts / 'microscope_calibration' / 'module.py').write_text('# my version\n')
    monkeypatch.setattr(paths, 'scripts_dir', lambda: scripts)
    assert paths.install_new_factory_modules() == []
    assert (scripts / 'microscope_calibration' / 'module.py').read_text() == '# my version\n'


# ------------------------------------------------------------------ lines: select + delete
@pytest.fixture(scope='module')
def app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def _viewer(viewer=None):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from spm_studio.ui.image_view import ImageView
    from spm_studio.core.models import ImageStyle, Geometry
    viewer = viewer or ImageView()
    viewer.resize(640, 640)
    raster = np.arange(10000, dtype=float).reshape(100, 100)
    img = QImage(100, 100, QImage.Format.Format_RGB888)
    img.fill(Qt.GlobalColor.black)
    viewer.set_scan(img, raster, Geometry((100, 100), (1e-8, 1e-8)), ImageStyle(), (0, 9999), 'Z', 'm')
    return viewer


def _three_lines(viewer):
    from spm_studio.core.models import ROI
    viewer.extra_rois = [ROI('line', ((10., 10.), (90., 10.))), ROI('line', ((10., 50.), (90., 50.))),
                         ROI('line', ((10., 90.), (90., 90.)))]
    viewer.roi = None


def test_colours_are_persistent_and_names_follow_the_order(app):
    viewer = _viewer()
    _three_lines(viewer)
    looks = viewer.line_appearance()
    assert [n for _i, _c, n in looks] == ['L1', 'L2', 'L3']
    colours = [c for _i, c, _n in looks]
    assert len(set(colours)) == 3
    third = viewer.extra_rois[2]
    viewer.forget_roi(viewer.extra_rois[1])
    viewer.extra_rois.pop(1)
    viewer.renumber_lines()
    looks = viewer.line_appearance()
    assert [n for _i, _c, n in looks] == ['L1', 'L2']           # renumbered
    assert [c for _i, c, _n in looks] == [colours[0], colours[2]]   # colours unchanged
    assert viewer.line_color_of(third) == colours[2]
    # a new line takes the free colour, not one already shown
    from spm_studio.core.models import ROI
    viewer.extra_rois.append(ROI('line', ((20., 30.), (80., 30.))))
    assert viewer.line_appearance()[-1][1] not in (colours[0], colours[2])


def test_named_lines_keep_custom_names_and_default_names_renumber(app):
    viewer = _viewer()
    _three_lines(viewer)
    keys = [viewer.line_key(r) for r in viewer.extra_rois]
    viewer.line_styles = {keys[0]: ('#111111', 'L1', 1.0), keys[1]: ('#222222', 'Terrace', 1.0),
                          keys[2]: ('#333333', 'L3', 1.0)}
    viewer.forget_roi(viewer.extra_rois[0])
    viewer.extra_rois.pop(0)
    viewer.renumber_lines()
    assert [n for _i, _c, n in viewer.line_appearance()] == ['Terrace', 'L2']
    assert [c for _i, c, _n in viewer.line_appearance()] == ['#222222', '#333333']


def test_click_on_a_line_selects_it(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    viewer = _viewer()
    viewer.show()
    app.processEvents()
    _three_lines(viewer)
    viewer.set_roi_tool('line')
    picked = []
    viewer.roiSelected.connect(picked.append)
    QTest.mouseClick(viewer, Qt.MouseButton.LeftButton, pos=viewer._to_screen((50, 50)).toPoint())
    assert picked == [1] and viewer.selected_roi_index == 1
    assert len(viewer.extra_rois) == 3                     # the click drew nothing new
    deleted = []
    viewer.deleteSelectedRequested.connect(lambda: deleted.append(viewer.selected_roi_index))
    QTest.keyClick(viewer, Qt.Key.Key_Delete)
    assert deleted == [1]
    viewer.close()


def test_main_window_deletes_exactly_the_selected_line(app, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtTest import QTest
    from spm_studio.ui.main_window import MainWindow
    for name, folder in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache')]:
        monkeypatch.setenv(name, str(tmp_path / folder))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'config'))
    win = MainWindow()
    win.show()
    app.processEvents()
    viewer = _viewer(win.viewer)
    _three_lines(viewer)
    colours = [c for _i, c, _n in viewer.line_appearance()]
    win._sync_selection_list()
    viewer.set_roi_tool('line')
    app.processEvents()
    QTest.mouseClick(viewer, Qt.MouseButton.LeftButton, pos=viewer._to_screen((50, 10)).toPoint())
    assert viewer.selected_roi_index == 0
    assert win.module_panel.selection_list.currentRow() == 0
    QTest.keyClick(viewer, Qt.Key.Key_Delete)
    app.processEvents()
    assert [r.points_px[0][1] for r in viewer.extra_rois] == [50., 90.]     # the first line went
    assert [n for _i, _c, n in viewer.line_appearance()] == ['L1', 'L2']
    assert [c for _i, c, _n in viewer.line_appearance()] == colours[1:]
    assert viewer.selected_roi_index == -1
    # Delete with nothing selected removes nothing
    QTest.keyClick(viewer, Qt.Key.Key_Delete)
    win._delete_selection(-1)
    assert len(viewer.extra_rois) == 2
    # Undo last still removes the most recent line
    win._undo_line()
    assert [r.points_px[0][1] for r in viewer.extra_rois] == [50.]
    win.close()
