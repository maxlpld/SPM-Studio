"""v0.0.18: ergonomics and one design everywhere — wheel scrolls the panel, short help texts, Logs closed by
default (opens on errors), one README viewer, normalised pop-up buttons, numbered steps."""
import os

import pytest


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


def test_short_text_keeps_the_essential():
    pytest.importorskip('PySide6')
    from spm_studio.shared.ergonomics import HINT_LIMIT, short_text
    assert short_text('Short hint.') == 'Short hint.'
    long = ('Values outside the range are printed flat. This cuts a too high peak so that the rest of the scan '
            'keeps its detail, and the colour bar shows the same range as the relief on the plate.')
    assert short_text(long) == 'Values outside the range are printed flat.'
    words = 'word ' * 60
    out = short_text(words)
    assert len(out) <= HINT_LIMIT + 1 and out.endswith('…')


def _wheel(widget, dy=-120):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def test_wheel_scrolls_the_panel_not_the_options(app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QScrollArea, QSpinBox, QVBoxLayout, QWidget
    area = QScrollArea()
    inner = QWidget()
    lay = QVBoxLayout(inner)
    combo = QComboBox()
    combo.addItems([str(i) for i in range(10)])
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(50)
    lay.addWidget(combo)
    lay.addWidget(spin)
    for _ in range(40):
        lay.addWidget(QComboBox())
    area.setWidget(inner)
    area.resize(300, 200)
    area.show()
    app.processEvents()
    assert combo.focusPolicy() == Qt.FocusPolicy.StrongFocus          # the wheel does not give focus
    before = area.verticalScrollBar().value()
    _wheel(combo)
    _wheel(spin)
    app.processEvents()
    assert combo.currentIndex() == 0 and spin.value() == 50              # values untouched
    assert area.verticalScrollBar().value() > before                     # the panel scrolled
    spin.setFocus()
    app.processEvents()
    if spin.hasFocus():                                                  # once chosen, the wheel works on it
        _wheel(spin, 120)
        assert spin.value() != 50
    area.close()


def test_long_hints_are_short_with_the_full_text_in_the_tooltip(app):
    from PySide6.QtWidgets import QLabel
    from spm_studio.shared import ergonomics
    full = ('Panel 1 is the source above; choose the channel of the other panels. The two colours are the low → '
            'high colour gradient of the 3MF export and of the live preview on the right.')
    label = QLabel(full)
    label.setObjectName('hint')
    label.show()
    app.processEvents()
    assert label.text() == 'Panel 1 is the source above; choose the channel of the other panels.'
    assert label.toolTip() == full
    ergonomics.set_full_help_texts(True)
    assert label.text() == full
    ergonomics.set_full_help_texts(False)
    assert label.text() != full
    short = QLabel('Short and clear.')
    short.setObjectName('hint')
    short.show()
    app.processEvents()
    assert short.text() == 'Short and clear.' and not short.toolTip()
    label.close()
    short.close()


def test_logs_closed_by_default_and_open_on_errors(window, app):
    assert not window.log_dock.isVisible()
    window._log('Information only', important=True)
    app.processEvents()
    assert not window.log_dock.isVisible()                               # marked on the button instead
    assert window.logs_toolbar_button.property('attention') is True
    assert 'Information only' in window.logs_toolbar_button.toolTip()
    window._log('Traceback: the script failed', error=True)
    app.processEvents()
    assert window.log_dock.isVisible()                                   # errors open the panel
    assert window.logs_toolbar_button.property('attention') is False
    window.log_dock.hide()
    window.settings.setValue('window_state', window.saveState())
    window.log_dock.show()
    window.settings.setValue('window_state', window.saveState())        # even if it was open last time …
    from spm_studio.ui.main_window import MainWindow
    again = MainWindow()
    again.show()
    app.processEvents()
    assert not again.log_dock.isVisible()                                # … it starts closed
    again.close()


def test_readme_viewer_is_themed_with_outline_and_find(app, tmp_path):
    from spm_studio.shared.docviewer import DocViewer, outline
    from spm_studio.ui.settings_dialog import GuideDialog
    text = '# Tool\n\nIntro.\n\n## Method\n\nText with `code`.\n\n```\n# not a heading\n```\n\n## Parameters\n\n' \
           '| Name | Unit |\n|---|---|\n| Size | nm |\n\n## Outputs\n\nFiles.\n'
    path = tmp_path / 'README.md'
    path.write_text(text, encoding='utf8')
    assert outline(text) == [(1, 'Tool'), (2, 'Method'), (2, 'Parameters'), (2, 'Outputs')]
    dialog = GuideDialog(path, 'Read me — Tool')
    assert isinstance(dialog, DocViewer) and dialog.path == path
    dialog.show()
    app.processEvents()
    assert dialog.outline.isVisible() and dialog.outline.count() == 4
    assert 'Method' in dialog.view.toPlainText() and dialog.find_text('Parameters')
    css = dialog.view.document().defaultStyleSheet()
    from spm_studio.shared.appearance import colors
    assert colors()['accent'] in css and 'pre' in css
    dialog.close()
    small = DocViewer(None, 'Note', text='Just a line.')
    small.show()
    app.processEvents()
    assert not small.outline.isVisible()
    small.close()


def test_popups_have_the_primary_button(app):
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Icon.Question, 'Delete?', 'Remove the file?',
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.show()
    app.processEvents()
    yes = box.button(QMessageBox.StandardButton.Yes)
    no = box.button(QMessageBox.StandardButton.No)
    assert yes.property('primary') is True and not no.property('primary')
    box.close()
    single = QMessageBox(QMessageBox.Icon.Information, 'Done', 'Finished.')
    single.show()
    app.processEvents()
    assert single.buttons()[0].property('primary') is True
    single.close()


def test_dialogs_fit_the_screen(app):
    from PySide6.QtWidgets import QDialog
    dialog = QDialog()
    dialog.resize(20000, 20000)
    dialog.show()
    app.processEvents()
    area = dialog.screen().availableGeometry()
    assert dialog.width() <= area.width() and dialog.height() <= area.height()
    dialog.close()


def test_numbered_steps_and_beta_badge_follow_the_theme(app):
    from spm_studio.beta.badge import beta_badge
    from spm_studio.shared.appearance import step_row
    row = step_row(3, 'Activate')
    assert row.badge.text() == '03' and row.badge.objectName() == 'stepBadge'
    assert row.badge.accessibleName() == 'Step 3' and row.title.text() == 'Activate'
    badge = beta_badge()
    assert badge.styleSheet() == ''                                      # styled by the app theme
    assert 'QLabel#BetaBadgeV0014' in app.styleSheet() and 'QLabel#stepBadge' in app.styleSheet()


def test_settings_offer_full_help_and_logs_on_run(window, app):
    from spm_studio.ui.settings_dialog import SettingsDialog
    dialog = SettingsDialog(window, 'general')
    assert not dialog.full_help.isChecked() and not dialog.logs_on_run.isChecked()
    dialog.logs_on_run.setChecked(True)
    assert window._logs_open_on_run()
    dialog.logs_on_run.setChecked(False)
    dialog.close()
