"""v26 SPM Studio: scan-selection recap export, transparent figure export, colourbar units
that follow the typed unit (nm / Å / mV), and the Bias figure button leaving the top bar."""
from pathlib import Path
import ast
import importlib.util
import json
import os

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / 'src' / 'spm_studio'
pyside = importlib.util.find_spec('PySide6')
needs_qt = pytest.mark.skipif(pyside is None, reason='PySide6 missing')


def test_unit_requests_convert_from_the_channel_base_unit():
    from spm_studio.core.models import display_unit_for, unit_to_si, preferred_display_unit
    assert unit_to_si('nm') == ('m', 1e-9)
    assert unit_to_si('Å') == ('m', 1e-10) and unit_to_si('angstrom') == ('m', 1e-10)
    assert unit_to_si('mV') == ('V', 1e-3) and unit_to_si('m') == ('m', 1.0)
    assert unit_to_si('bananas') is None and unit_to_si('') is None
    values = np.array([0.0, 9.21e-11])
    # Empty or identical: automatic SI scale as before (pm for a 92 pm range).
    assert display_unit_for('', 'm', values) == preferred_display_unit('m', values) == ('pm', 1e12)
    assert display_unit_for('m', 'm', values) == ('pm', 1e12)
    # The user typed a unit: the numbers follow it.
    label, mult = display_unit_for('nm', 'm', values)
    assert label == 'nm' and mult == pytest.approx(1e9)
    assert f'{9.21e-11 * mult:.3g}' == '0.0921'
    label, mult = display_unit_for('Å', 'm', values)
    assert label == 'Å' and mult == pytest.approx(1e10) and f'{9.21e-11 * mult:.3g}' == '0.921'
    assert display_unit_for('mV', 'V', np.array([0.0, 0.25])) == ('mV', pytest.approx(1e3))
    # Unknown or incompatible units are shown verbatim without rescaling (previous behaviour).
    assert display_unit_for('counts', 'm', values) == ('counts', 1.0)
    assert display_unit_for('nm', 'V', values) == ('nm', 1.0)


def test_recap_folder_is_a_sibling_named_after_the_dataset(tmp_path):
    from spm_studio.core.paths import scan_recap_folder
    data = tmp_path / 'Data' / '20261106'
    assert scan_recap_folder(data) == tmp_path / 'Data' / '20261106_scan_recap'
    assert scan_recap_folder(tmp_path / 'Data' / '20261106_scan_recap') == tmp_path / 'Data' / '20261106_scan_recap'


def test_bias_figure_button_left_the_top_bar_but_the_composer_stays_reachable():
    source = (SRC / 'ui' / 'main_window.py').read_text()
    ast.parse(source)
    assert 'self.topbar.addWidget(self.bias_figure_button)' not in source
    assert 'self.bias_figure_button.hide()' in source
    assert "'__bias_figure_composer__'" in source
    assert "self._action(tools,'Bias figure composer…',None,self.open_bias_figure_composer)" in source
    assert 'self.browser.exportSelectionRequested.connect(self.export_scan_selection)' in source
    assert 'transparent=dialog.transparent_background()' in source
    browser = (SRC / 'ui' / 'browser_panel.py').read_text()
    assert "ExportScanSelectionV26" in browser and 'exportSelectionRequested.emit' in browser


def _scan(tmp_path):
    from spm_studio.core.models import Scan, Channel, Geometry
    geom = Geometry((20, 40), (2e-8, 1e-8), (0.0, 0.0), 0.0)
    data = np.linspace(0, 9.21e-11, 800).reshape(20, 40)
    (tmp_path / 'image.sxm').write_bytes(b'synthetic scan placeholder')  # export provenance stats it
    return Scan(tmp_path / 'image.sxm', {'Z': Channel('Z', 'm', {'forward': data}, geom)})


@needs_qt
def test_transparent_export_leaves_the_page_unpainted(tmp_path):
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    QApplication.instance() or QApplication([])
    from spm_studio.core.export_layout import export_publication, panel_defaults
    from spm_studio.core.presets import DEFAULT_EXPORT
    scan = _scan(tmp_path)
    preset = dict(DEFAULT_EXPORT)
    spec = panel_defaults(scan, {'kind': 'channel', 'channel': 'Z'}, 'forward')
    spec['unit'] = 'nm'
    opaque = export_publication(scan, [dict(spec)], tmp_path / 'opaque.png', preset)
    clear = export_publication(scan, [dict(spec)], tmp_path / 'clear.png', preset, transparent=True)
    a = QImage(str(opaque)); b = QImage(str(clear))
    assert a.pixelColor(2, 2).alpha() == 255 and a.pixelColor(2, 2).red() == 255
    assert b.pixelColor(2, 2).alpha() == 0, 'the page corner is transparent'
    assert b.hasAlphaChannel()
    provenance = json.loads((clear.with_name(clear.name + '.provenance.json')).read_text())
    assert provenance['transparent_background'] is True and provenance['panels'][0]['unit'] == 'nm'
    jpeg = export_publication(scan, [dict(spec)], tmp_path / 'clear.jpg', preset, transparent=True)
    assert QImage(str(jpeg)).pixelColor(2, 2).red() == 255, 'JPEG has no alpha and stays white'


@needs_qt
def test_export_dialog_offers_transparency_and_unit_shortcuts(tmp_path):
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from spm_studio.ui.export_dialog import PublicationDialog
    dialog = PublicationDialog(_scan(tmp_path), selected_channel='Z')
    assert dialog.transparent_background() is False
    dialog.transparent.setChecked(True)
    assert dialog.transparent_background() is True
    left = dialog.controls[0]
    assert left['unit'].text() == '' and 'auto' in left['unit'].placeholderText()
    buttons = {value: button for button, value in left['unit_buttons']}
    assert set(buttons) == {'', 'nm', 'Å', 'pm'} and all(b.isEnabled() for b in buttons.values())
    buttons['Å'].click()
    assert left['unit'].text() == 'Å'
    assert dialog.selection()[0]['unit'] == 'Å'
    buttons[''].click()
    assert dialog.selection()[0]['unit'] == ''


@needs_qt
def test_browser_panel_export_selection_button_follows_the_list(tmp_path):
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication, QListWidgetItem
    QApplication.instance() or QApplication([])
    from spm_studio.ui.browser_panel import BrowserPanel
    panel = BrowserPanel()
    fired = []
    panel.exportSelectionRequested.connect(lambda: fired.append(True))
    assert not panel.export_selection_button.isEnabled()
    panel.files.addItem(QListWidgetItem('scan001'))
    panel.update_selection_actions()
    assert panel.export_selection_button.isEnabled()
    panel.export_selection_button.click()
    assert fired == [True]
