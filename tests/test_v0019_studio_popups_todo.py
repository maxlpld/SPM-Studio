"""v0.0.19: Studio Light / Studio Dark built in, readable checked buttons, pop-ups without icon buttons and with
rounded corners, windows sized to their content, channel tiles (same size, centred titles, outline, fixed
order), README width, compact to-do window."""
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_studio_theme_files_are_valid_and_studio():
    from spm_studio.core.presets import validate_theme
    for name, label in (('light_studio', 'Studio Light'), ('dark_studio', 'Studio Dark')):
        data = json.loads((ROOT / 'customization' / 'themes' / f'{name}.json').read_text(encoding='utf8'))
        tokens = validate_theme(data)
        assert tokens['design'] == 'studio' and data['name'] == label
        assert tokens['tint_a'].startswith('#') and tokens['tint_b'].startswith('#')
    with pytest.raises(ValueError):
        validate_theme({'schema_version': 1, 'design': 'weird'})
    with pytest.raises(ValueError):
        validate_theme({'schema_version': 1, 'tint_a': 'green'})


def test_studio_overlay_checked_buttons_stay_readable():
    from spm_studio.shared.studio_design import overlay, is_studio
    data = json.loads((ROOT / 'customization' / 'themes' / 'light_studio.json').read_text(encoding='utf8'))
    assert is_studio(data) and not is_studio({'background': '#000000'})
    qss = overlay({**data, 'font_size': 10.5})
    for line in qss.splitlines():
        if ':checked' in line and 'background:' in line:
            value = line.split('background:')[1].split(';')[0].strip()
            assert value not in ('@fg', '@foreground', '#000000', '#111111'), line
    assert 'QPushButton:checked, QToolButton:checked' in qss and '@accent_soft' in qss


def test_dark_studio_has_contrast():
    def lum(hex_colour):
        r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
        return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)

    def ratio(a, b):
        hi, lo = sorted((lum(a), lum(b)), reverse=True)
        return (hi + .05) / (lo + .05)
    d = json.loads((ROOT / 'customization' / 'themes' / 'dark_studio.json').read_text(encoding='utf8'))
    for surface in ('background', 'surface', 'tint_a', 'tint_b'):
        assert ratio(d['foreground'], d[surface]) >= 7, surface
    assert ratio(d['muted'], d['surface']) >= 4.5
    assert ratio(d['accent_fg'], d['accent']) >= 4.5


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
    win.show()
    app.processEvents()
    yield win
    win.close()
    app.processEvents()


def _studio_theme_applies_overlay_and_tones(window, app):
    from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget
    from spm_studio.shared.studio_design import TONES
    window._apply_theme('light_studio')
    app.processEvents()
    assert 'Studio design' in app.styleSheet() and TONES.enabled
    holder = QWidget()
    lay = QVBoxLayout(holder)
    boxes = [QGroupBox(f'Card {i}') for i in range(3)]
    for b in boxes:
        lay.addWidget(b)
    holder.show()
    app.processEvents()
    assert [b.property('studioTone') for b in boxes] == ['neutral', 'a', 'b']
    window._apply_theme('graphite')
    app.processEvents()
    assert 'Studio design' not in app.styleSheet() and not TONES.enabled
    assert boxes[1].property('studioTone') in (None, '')
    holder.close()


def test_popup_buttons_have_no_icons_and_rounded_corners(app):
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QVBoxLayout
    assert 'dialogbuttonbox-buttons-have-icons: 0' in app.styleSheet()
    dialog = QDialog()
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    pix = QPixmap(8, 8)
    pix.fill()
    box.button(QDialogButtonBox.StandardButton.Ok).setIcon(QIcon(pix))
    QVBoxLayout(dialog).addWidget(box)
    dialog.show()
    app.processEvents()
    assert all(b.icon().isNull() for b in box.buttons())
    dialog.close()
    message = QMessageBox(QMessageBox.Icon.Information, 'Export', 'Saved.')
    message.show()
    app.processEvents()
    assert message.property('spmRounded') is True
    from PySide6.QtCore import Qt
    assert message.windowFlags() & Qt.WindowType.FramelessWindowHint
    message.close()


def test_dialog_opens_large_enough_for_its_content(app):
    from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout, QWidget
    dialog = QDialog()
    outer = QVBoxLayout(dialog)
    area = QScrollArea()
    area.setWidgetResizable(True)
    inner = QWidget()
    inner.setMinimumSize(520, 420)
    QVBoxLayout(inner).addWidget(QLabel('content'))
    area.setWidget(inner)
    outer.addWidget(area)
    dialog.resize(200, 150)
    dialog.show()
    app.processEvents()
    screen = dialog.screen().availableGeometry()
    assert dialog.width() >= min(520, screen.width() - 40)
    assert dialog.height() >= min(420, screen.height() - 40)
    dialog.close()


def test_fixed_width_buttons_are_widened_for_their_text(app):
    from PySide6.QtWidgets import QPushButton
    button = QPushButton('auto')
    button.setFixedWidth(20)
    button.show()
    app.processEvents()
    assert button.width() >= button.fontMetrics().horizontalAdvance('auto') + 10
    button.close()


def test_readme_viewer_uses_a_wide_readable_column(app, tmp_path):
    from spm_studio.shared.docviewer import DocViewer
    path = tmp_path / 'README.md'
    path.write_text('# Title\n\n' + 'word ' * 400, encoding='utf8')
    viewer = DocViewer(path)
    viewer.show()
    app.processEvents()
    assert viewer.width() >= min(900, viewer.screen().availableGeometry().width() - 60)
    assert viewer.view.lineWrapMode().name == 'WidgetWidth'
    viewer.close()


def _outline_settings_and_order_of_channel_tiles(window, app):
    settings = window.tile_outline_settings()
    assert settings == {'enabled': True, 'color': '', 'width': 2, 'radius': 10}
    window.settings.setValue('view/outline_width', 30)
    assert window.tile_outline_settings()['width'] == 8
    window.settings.setValue('view/outline_width', 3)
    assert window.viewer_title.objectName() == 'sectionTitle'
    from PySide6.QtCore import Qt
    assert window.viewer_title.alignment() & Qt.AlignmentFlag.AlignHCenter
    from spm_studio.ui.settings_dialog import SettingsDialog
    dialog = SettingsDialog(window, 'general')
    assert dialog.outline_enabled.isChecked() and dialog.outline_width.value() == 3
    dialog.outline_radius.setValue(6)
    assert window.tile_outline_settings()['radius'] == 6
    dialog.outline_enabled.setChecked(False)
    assert window.tile_outline_settings()['enabled'] is False
    dialog.close()


def _todo_is_a_compact_post_it_window(window, app):
    from PySide6.QtCore import Qt
    win = window.documents.open_todo()
    app.processEvents()
    assert win.width() <= 480 and win.height() <= 700
    assert win.title.text() == 'To-do' and not win.tabs.tabBar().isVisible()
    win.quick.setText('Measure the step height')
    win.add_from_quick()
    assert win.segment_buttons[0].text() == 'Tasks (1)' and '1 open' in win.count.text()
    win.segment_buttons[1].click()
    assert win.tabs.currentIndex() == 1 and not win.quick.isVisible()
    win.pin.setChecked(True)
    assert win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    win.pin.setChecked(False)
    assert not win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    win.close()


def test_main_window_studio_outline_and_todo(window, app):
    """One main window for the three checks (window creation is slow on CI runners)."""
    _studio_theme_applies_overlay_and_tones(window, app)
    _outline_settings_and_order_of_channel_tiles(window, app)
    _todo_is_a_compact_post_it_window(window, app)
