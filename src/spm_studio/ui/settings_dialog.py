"""Settings (v0.0.5): one window behind the gear button of the top bar.

Pages (v0.0.20: every option is in exactly one place)
-----------------------------------------------------
* **General** — projects and crash recovery, scans, logs, keyboard, assistant, maintenance.
* **Appearance** — theme, Theme Studio, help texts, pop-ups, outline of the selected channel.
* **Library** — import / export / edit / remove scripts, profiles, export profiles,
  themes, colormaps, plot styles and shortcut files (``core.library``); built-in tools.
* v0.1.0: every AI option (assistant, providers, Consensus and Zotero …) lives in the AI assistant's own
  settings (Agent Hub › Settings); General keeps one line that opens them.
* **Documents** — v0.0.8: LaTeX editor, presentation editor, Overleaf (``documents``).
* **Updates**, **Tutorials**, **Beta Tester**, **About** — version, author, project page.

v0.0.20: a page is built the first time it is shown, so the window opens at once.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QSize, QThread, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase, QPixmap
from spm_studio.shared.docviewer import DocViewer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
                               QListWidgetItem, QStackedWidget, QWidget, QComboBox, QCheckBox, QGroupBox,
                               QFormLayout, QLineEdit, QPlainTextEdit, QTextBrowser, QFileDialog,
                               QScrollArea, QFrame, QAbstractItemView, QProgressBar)

from spm_studio.core import library, paths
from spm_studio.shared.dialogs import MessageDialog, TextInputDialog
from spm_studio.shared.ui_strings import ui_label

PAGES = (('general', 'General', 'gear'), ('appearance', 'Appearance', 'theme'), ('library', 'Library', 'folder'),
         ('documents', 'Documents', 'latex'),
         ('updates', 'Updates', 'refresh'), ('tutorials', 'Tutorials', 'run'), ('beta', 'Beta Tester', 'ai'),
         ('about', 'About', 'info'))


def open_url(url: str):
    QDesktopServices.openUrl(QUrl(url))


def open_folder(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName('hint')
    label.setWordWrap(True)
    return label


def _icon_button(text: str, icon_name: str | None, tooltip: str = '') -> QPushButton:
    button = QPushButton(text)
    if tooltip:
        button.setToolTip(tooltip)
    if icon_name:
        try:
            from spm_studio.shared.appearance import set_icon
            set_icon(button, icon_name)
        except Exception:
            pass
    return button


# ------------------------------------------------------------------------- viewers
class GuideDialog(DocViewer):
    """Read a Markdown file (a tool's README, a folder guide) inside the app.

    v0.0.18: the shared document viewer (``shared.docviewer``): themed headings, code and tables, an outline of
    long documents, find-in-page, a readable text column.
    """

    def __init__(self, path, title: str = '', parent=None):
        super().__init__(path, title, parent)


class TextEditDialog(QDialog):
    """Edit one library text file; it is saved only if it still validates."""

    def __init__(self, kind: str, name: str, parent=None):
        super().__init__(parent)
        self.kind, self.name = kind, name
        target = library.editable_file(kind, name)
        self.setWindowTitle(f'Edit {target.name}' + (f' — {name}' if target.name != name else ''))
        self.resize(760, 640)
        layout = QVBoxLayout(self)
        note = 'The file is checked before it is saved; the previous version is kept as ' + target.name + '.bak.'
        if kind == 'scripts' and target.name == 'module.json':
            note += ' The Python code (module.py) is edited with your own editor: use “Open folder”.'
        layout.addWidget(_hint(note))
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setPlainText(library.read_text(kind, name))
        layout.addWidget(self.editor, 1)
        self.message = QLabel('')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QHBoxLayout()
        folder = _icon_button('Open folder', 'folder')
        folder.clicked.connect(lambda: open_folder(target.parent))
        guide_path = library.guide(kind)
        guide = _icon_button('Read the guide', 'book')
        guide.setEnabled(guide_path is not None)
        guide.clicked.connect(lambda: GuideDialog(guide_path, 'Guide — ' + library.KINDS[kind].label, self).exec())
        row.addWidget(folder)
        row.addWidget(guide)
        row.addStretch(1)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        save = QPushButton('Save')
        save.setProperty('primary', True)
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)

    def _save(self):
        try:
            library.save_text(self.kind, self.name, self.editor.toPlainText())
        except Exception as exc:
            self.message.setText('Not saved — ' + str(exc))
            self.message.setStyleSheet('color: palette(bright-text);')
            return
        self.accept()


class _Task(QThread):
    """Run a plain function off the GUI thread; emits (task, result, error text).

    The signal is always connected to a *bound method* of the dialog: PySide runs a plain function
    or lambda connected to a signal in the emitting (worker) thread, where widgets must not be touched.
    """
    finished_with = Signal(object, object, str)

    def __init__(self, fn, on_done, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.on_done = on_done

    def run(self):
        try:
            self.finished_with.emit(self, self.fn(), '')
        except Exception as exc:
            self.finished_with.emit(self, None, str(exc))


class _ConsensusSignIn(QThread):
    """Browser sign-in to Consensus (ai/consensus.py) without blocking the window."""
    opened = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        from spm_studio.ai import consensus
        self.flow = consensus.SignIn()

    def cancel(self):
        self.flow.cancel()

    def run(self):
        from spm_studio.ai import consensus
        try:
            self.opened.emit(self.flow.start())
            result = self.flow.wait(timeout=300)
            self.done.emit(str(result.get('stored', 'stored')))
        except consensus.ConsensusError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')
        finally:
            self.flow.close()


# ---------------------------------------------------------------------------- dialog
def fit_navigation(nav: QListWidget, minimum: int = 176):
    """v0.0.20: the page list of a settings window is as wide as its longest entry (never cut, never wrapped)."""
    from PySide6.QtGui import QFont, QFontMetrics
    nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    nav.setTextElideMode(Qt.TextElideMode.ElideNone)
    nav.setWordWrap(False)
    nav.setSpacing(1)
    nav.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    bold = QFont(nav.font())
    bold.setBold(True)                      # the selected entry may be bold in some themes
    metrics = QFontMetrics(bold)
    longest = max((metrics.horizontalAdvance(nav.item(i).text()) for i in range(nav.count())), default=80)
    icon = nav.iconSize().width() + 10
    nav.setFixedWidth(max(minimum, longest + icon + 44))
    for i in range(nav.count()):
        nav.item(i).setSizeHint(QSize(0, max(32, metrics.height() + 14)))


class SettingsDialog(QDialog):
    def __init__(self, window, page: str = 'general'):
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle('Settings')
        self.setObjectName('SettingsDialogV005')
        self.resize(960, 680)
        root = QHBoxLayout(self)
        root.setSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName('SettingsNavigationV005')
        self.nav.setIconSize(QSize(18, 18))
        self.stack = QStackedWidget()
        root.addWidget(self.nav)
        root.addWidget(self.stack, 1)
        self._builders = {'general': self._general_page, 'appearance': self._appearance_page,
                          'library': self._library_page,
                          'documents': self._documents_page, 'updates': self._updates_page,
                          'tutorials': self._tutorials_page, 'beta': self._beta_page, 'about': self._about_page}
        self._page_keys = []
        self._built = set()
        pages = list(PAGES)
        # v0.0.13: pages added by installed extensions (none without an extension)
        api = getattr(window, 'extension_api', None)
        from spm_studio.beta.badge import beta_label
        for key, (_ext, label, factory) in (getattr(api, 'settings_pages', {}) or {}).items():
            if str(key).endswith(':theme-studio'):
                continue                    # v0.0.20: Theme Studio is built in (Settings › Appearance)
            if str(key).endswith(':agent-hub'):
                continue                    # v0.1.0: the assistant is built in, with its own settings window
            pages.insert(len(pages) - 1, (key, beta_label(label), 'ai'))
            self._builders[key] = lambda factory=factory, label=label: self._extension_page(factory, label)
        from spm_studio.shared.appearance import icon
        for key, label, icon_name in pages:
            item = QListWidgetItem(label)
            try:
                item.setIcon(icon(icon_name))
            except Exception:
                pass
            item.setToolTip(label)
            self.nav.addItem(item)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.stack.addWidget(scroll)
            self._page_keys.append(key)
        fit_navigation(self.nav)
        self.nav.currentRowChanged.connect(self._show_row)
        self.show_page(page)

    def _show_row(self, row: int):
        if row < 0:
            return
        self._build(row)
        self.stack.setCurrentIndex(row)

    def _build(self, row: int):
        """Build a page the first time it is shown (v0.0.20: opening Settings no longer builds all of them)."""
        key = self._page_keys[row]
        if key in self._built:
            return
        self._built.add(key)
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            widget = self._builders[key]()
        except Exception as exc:              # a broken page must never break Settings
            widget = QWidget()
            QVBoxLayout(widget).addWidget(_hint(f'This page could not be built: {exc}'))
        finally:
            QApplication.restoreOverrideCursor()
        self.stack.widget(row).setWidget(widget)

    def build_all(self):
        """Build every page (tests, screenshots)."""
        for row in range(len(self._page_keys)):
            self._build(row)

    def show_page(self, page: str):
        row = self._page_keys.index(page) if page in self._page_keys else 0
        if self.nav.currentRow() == row:
            self._show_row(row)
        else:
            self.nav.setCurrentRow(row)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _page(title: str, subtitle: str = ''):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 0, 10, 8)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName('heading')
        layout.addWidget(heading)
        if subtitle:
            layout.addWidget(_hint(subtitle))
        return widget, layout

    def _outline_rows(self, v, w):
        """v0.0.19: the outline around the selected channel of the scan preview."""
        from PySide6.QtWidgets import QColorDialog, QSpinBox
        from PySide6.QtGui import QColor
        get = getattr(w, 'tile_outline_settings', None)
        cfg = get() if get else {'enabled': True, 'color': '', 'width': 2, 'radius': 10}

        def refresh():
            if hasattr(w, '_apply_tile_outline'):
                try:
                    w._apply_tile_outline()
                except Exception:
                    pass

        def store(key, value):
            w.settings.setValue(f'view/outline_{key}', value)
            refresh()

        self.outline_enabled = QCheckBox('Shown')
        self.outline_enabled.setObjectName('SettingsOutlineEnabledV0019')
        self.outline_enabled.setChecked(bool(cfg['enabled']))
        self.outline_enabled.toggled.connect(lambda on: store('enabled', bool(on)))
        self._action_row(v, 'Selected channel outline',
                         'A contour around the channel selected with the mouse or the arrows.', self.outline_enabled)

        self.outline_color = QPushButton('Theme accent' if not cfg['color'] else cfg['color'])
        self.outline_color.setObjectName('SettingsOutlineColorV0019')

        def pick():
            start = QColor(cfg['color'] or '#FF6B2C')
            color = QColorDialog.getColor(start, self, 'Outline colour')
            if color.isValid():
                cfg['color'] = color.name()
                self.outline_color.setText(color.name())
                store('color', color.name())

        def reset():
            cfg['color'] = ''
            self.outline_color.setText('Theme accent')
            store('color', '')
        self.outline_color.clicked.connect(pick)
        reset_button = QPushButton('Accent')
        reset_button.setToolTip('Use the colour of the theme')
        reset_button.clicked.connect(reset)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.outline_color)
        h.addWidget(reset_button)
        self._action_row(v, 'Outline colour', '', row)

        self.outline_width = QSpinBox()
        self.outline_width.setObjectName('SettingsOutlineWidthV0019')
        self.outline_width.setRange(1, 8)
        self.outline_width.setSuffix(' px')
        self.outline_width.setValue(int(cfg['width']))
        self.outline_width.valueChanged.connect(lambda n: store('width', int(n)))
        self._action_row(v, 'Outline thickness', '', self.outline_width)

        self.outline_radius = QSpinBox()
        self.outline_radius.setObjectName('SettingsOutlineRadiusV0019')
        self.outline_radius.setRange(0, 24)
        self.outline_radius.setSuffix(' px')
        self.outline_radius.setValue(int(cfg['radius']))
        self.outline_radius.valueChanged.connect(lambda n: store('radius', int(n)))
        self._action_row(v, 'Outline corner radius', '', self.outline_radius)


    def _popup_rows(self, v, w):
        self.rounded_popups = QCheckBox('Rounded')
        self.rounded_popups.setObjectName('SettingsRoundedPopupsV0019')
        from spm_studio.shared.dialogs import rounded_popups_enabled
        self.rounded_popups.setChecked(rounded_popups_enabled())
        self.rounded_popups.toggled.connect(lambda on: w.settings.setValue('ui/rounded_popups', bool(on)))
        self._action_row(v, 'Message pop-ups', 'All corners rounded, moved by dragging them.', self.rounded_popups)

    @staticmethod
    def _action_row(form_layout, title: str, hint: str, widget):
        """One setting: name and explanation on the left, its control on the right."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(1)
        name = QLabel(title)
        text.addWidget(name)
        if hint:
            text.addWidget(_hint(hint))
        h.addLayout(text, 1)
        widget.setMinimumWidth(190)
        h.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        form_layout.addWidget(row)
        return row

    def _log(self, text: str, important: bool = False):
        try:
            self.window_._log(text, important=important)
        except Exception:
            pass

    # ------------------------------------------------------------------ v0.0.13 pages
    def _updates_page(self):
        from spm_studio.beta.settings_pages import UpdatesPage
        return UpdatesPage(self.window_)

    def _tutorials_page(self):
        from spm_studio.beta.settings_pages import TutorialsPage
        return TutorialsPage(self.window_)

    def _beta_page(self):
        from spm_studio.beta.settings_pages import BetaPage
        return BetaPage(self.window_)

    def _extension_page(self, factory, label):
        """An extension's page, always under a BETA banner (only beta testers have it)."""
        from spm_studio.beta.badge import beta_badge
        holder = QWidget()
        holder.setObjectName('ExtensionPageV0014')
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        banner = QHBoxLayout()
        banner.addWidget(beta_badge(holder))
        note = QLabel('Only available to beta testers (private extension).')
        note.setObjectName('hint')
        banner.addWidget(note)
        banner.addStretch(1)
        v.addLayout(banner)
        try:
            v.addWidget(factory(self), 1)
        except Exception as exc:                      # a broken extension page must not break Settings
            v.addWidget(_hint(f'This page could not be built: {exc}'))
            v.addStretch(1)
        return holder

    # ------------------------------------------------------------------ Documents
    def _documents_page(self):
        from spm_studio.documents.ui.settings_page import build_page
        return build_page(self)

    # ------------------------------------------------------------------ General
    def _general_page(self):
        """v0.0.20: behaviour only; everything about the look is on the Appearance page, tools and folders in
        Library, updates on the Updates page, the project page and licence in About (no option twice)."""
        from PySide6.QtWidgets import QSpinBox
        w = self.window_
        page, layout = self._page('General')

        box = QGroupBox('Projects and recovery')
        v = QVBoxLayout(box)
        self.reopen_last = QCheckBox('Reopen')
        self.reopen_last.setObjectName('SettingsReopenLastV0020')
        self.reopen_last.setChecked(str(w.settings.value('project/reopen_last', True)).lower() in ('true', '1'))
        self.reopen_last.toggled.connect(lambda on: w.settings.setValue('project/reopen_last', bool(on)))
        self._action_row(v, 'At start', 'Reopen the projects and the scan you were working on (also after a crash).',
                         self.reopen_last)
        self.autosave = QSpinBox()
        self.autosave.setObjectName('SettingsAutosaveV0020')
        self.autosave.setRange(5, 300)
        self.autosave.setSuffix(' s')
        try:
            self.autosave.setValue(int(float(w.settings.value('project/autosave_seconds', 15))))
        except (TypeError, ValueError):
            self.autosave.setValue(15)

        def autosave_changed(n):
            w.settings.setValue('project/autosave_seconds', int(n))
            if hasattr(w, 'projects'):
                w.projects.set_interval(int(n))
        self.autosave.valueChanged.connect(autosave_changed)
        self._action_row(v, 'Save the project state every',
                         'Display, processing, crops, selections and tool settings are written to '
                         '“spm-studio-project.json” in the project folder (scan files are never changed).',
                         self.autosave)
        layout.addWidget(box)

        box = QGroupBox('Scans and results')
        v = QVBoxLayout(box)
        self.autocrop = QCheckBox('Enabled')
        self.autocrop.setChecked(w.profile_autocrop.isChecked())
        self.autocrop.toggled.connect(w.profile_autocrop.setChecked)
        self._action_row(v, 'Auto-crop incomplete scans',
                         'When a profile that asks for it is applied, crop the unmeasured part of an aborted scan.',
                         self.autocrop)
        b = QPushButton('Results && figures…')
        b.clicked.connect(w.open_plot_options)
        self._action_row(v, 'Results and figures', 'Plot style, output formats and what opens after a run.', b)
        self.logs_on_run = QCheckBox('Open')
        self.logs_on_run.setObjectName('SettingsLogsOnRunV0018')
        self.logs_on_run.setChecked(w._logs_open_on_run() if hasattr(w, '_logs_open_on_run') else False)
        self.logs_on_run.toggled.connect(lambda on: w.settings.setValue('logs/open_on_run', bool(on)))
        self._action_row(v, 'Logs when a script runs', 'Errors always open the Logs panel.', self.logs_on_run)
        layout.addWidget(box)

        box = QGroupBox('Keyboard')
        v = QVBoxLayout(box)
        b = QPushButton('Keyboard shortcuts…')
        b.clicked.connect(w.open_shortcut_options)
        self._action_row(v, 'Keyboard shortcuts', 'See and change every shortcut.', b)
        layout.addWidget(box)
        # v0.1.0: the one line about the assistant; all of its options are in its own settings window.
        b = QPushButton('Open its settings')
        b.setObjectName('OpenAssistantSettingsV010')
        b.clicked.connect(lambda: w.open_assistant_settings())
        self._action_row(layout, 'AI assistant: open its settings', '', b)

        box = QGroupBox('Performance and diagnostics')
        v = QVBoxLayout(box)
        b = QPushButton('Clear preview cache')
        b.clicked.connect(w._clear_cache)
        self._action_row(v, 'Preview cache', 'Free the memory used by scan previews.', b)
        self.record_freezes = QCheckBox('Record')
        self.record_freezes.setObjectName('SettingsRecordFreezesV0020')
        from spm_studio.shared import watchdog
        self.record_freezes.setChecked(watchdog.enabled())
        self.record_freezes.toggled.connect(watchdog.set_enabled)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.record_freezes)
        report = QPushButton('Open report')
        report.setToolTip(str(watchdog.report_path()))
        report.clicked.connect(lambda: open_folder(watchdog.report_path().parent))
        h.addWidget(report)
        self._action_row(v, 'Slow moments', 'When the window stops responding for more than a second, note what it '
                         'was doing in a small report (send it with a bug report).', row)
        layout.addWidget(box)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ Appearance
    def _appearance_page(self):
        w = self.window_
        page, layout = self._page('Appearance')

        box = QGroupBox('Theme')
        v = QVBoxLayout(box)
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName('SettingsThemeComboV005')
        self._fill_themes()
        self.theme_combo.activated.connect(lambda _=0: w._apply_theme(str(self.theme_combo.currentData())))
        self._action_row(v, 'Theme', 'Colours and font of the interface. Add your own with Theme Studio or '
                         'Library › Themes.', self.theme_combo)
        studio = _icon_button('Open Theme Studio', 'theme',
                              'Restyle any control by clicking it, save your own theme, import an SVG skin')
        studio.setObjectName('OpenThemeStudio')

        def open_studio():
            from spm_studio import theme_studio
            ts = theme_studio.instance() or theme_studio.install(w)
            if ts is None:
                MessageDialog.warning(self, 'Theme Studio', 'Theme Studio could not be started (see Logs).')
                return
            self.accept()                    # Settings is modal: close it so that the window can be picked from
            ts.open()
        studio.clicked.connect(open_studio)
        self.theme_studio_button = studio
        self._action_row(v, 'Theme Studio', 'Visual theme editor: click a control to restyle it, profiles, '
                         'SVG skins.', studio)
        layout.addWidget(box)

        box = QGroupBox('Texts and pop-ups')
        v = QVBoxLayout(box)
        # v0.0.18: help texts are short by default; the full versions stay one tick away
        from spm_studio.shared import ergonomics
        self.full_help = QCheckBox('Show')
        self.full_help.setObjectName('SettingsFullHelpV0018')
        self.full_help.setChecked(ergonomics.full_help_texts())
        self.full_help.toggled.connect(ergonomics.set_full_help_texts)
        self._action_row(v, 'Full help texts', 'Long explanations under the options (otherwise in their tooltip).',
                         self.full_help)
        self._popup_rows(v, w)
        layout.addWidget(box)

        box = QGroupBox('Scan preview')
        v = QVBoxLayout(box)
        self._outline_rows(v, w)
        layout.addWidget(box)
        layout.addStretch(1)
        return page

    def _fill_themes(self):
        if not hasattr(self, 'theme_combo'):
            return                           # Appearance page not built yet
        w = self.window_
        current = str(w.settings.value('theme', 'graphite'))
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        for theme_path in w._theme_files():
            self.theme_combo.addItem(ui_label(theme_path.stem), theme_path.stem)
        index = self.theme_combo.findData(current)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        self.theme_combo.blockSignals(False)

    def _open_customization_guide(self):
        guide = paths.customization_dir() / 'README_CUSTOMIZATION.md'
        if guide.is_file():
            GuideDialog(guide, 'Customization guide', self).exec()
        else:
            open_folder(paths.customization_dir())

    # ------------------------------------------------------------------ Library
    def _library_page(self):
        page, layout = self._page(
            'Library',
            'Everything you can add to SPM Studio. Export… writes one .zip that a colleague installs with '
            'Import…. Removed items are moved to a “removed” folder, never deleted.')
        top = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName('LibraryKindComboV005')
        for key, kind in library.KINDS.items():
            self.kind_combo.addItem(kind.label, key)
        top.addWidget(QLabel('Show'))
        top.addWidget(self.kind_combo, 1)
        layout.addLayout(top)
        self.kind_description = _hint('')
        layout.addWidget(self.kind_description)
        body = QHBoxLayout()
        self.items = QListWidget()
        self.items.setObjectName('LibraryItemsV005')
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.items.itemDoubleClicked.connect(lambda _item: self._library_edit())
        self.items.itemSelectionChanged.connect(self._library_buttons)
        body.addWidget(self.items, 1)
        column = QVBoxLayout()
        column.setSpacing(6)

        def add(text, icon_name, slot, tip=''):
            button = _icon_button(text, icon_name, tip)
            button.clicked.connect(slot)
            column.addWidget(button)
            return button

        self.lib_import_file = add('Import file…', 'import', self._library_import_file,
                                   'A file of this kind, or a .zip exported from SPM Studio')
        self.lib_import_folder = add('Import folder…', 'folder', self._library_import_folder,
                                     'A folder of files of this kind (for scripts: one tool folder, or a folder of tools)')
        self.lib_gwyddion = add('Import Gwyddion gradients…', None, self._library_gwyddion)
        self.lib_new_template = add('New template…', 'plus', self._library_new_template,
                                    'Start a new template (then Edit…, or build it in the editor and use '
                                    '“Save as template”)')
        self.lib_export = add('Export…', 'export', self._library_export,
                              'Write the selected items into one .zip to send to someone')
        column.addSpacing(8)
        self.lib_edit = add('Edit…', 'edit', self._library_edit)
        self.lib_readme = add('Read me', 'book', self._library_readme, 'Open the README of the selected script')
        self.lib_duplicate = add('Duplicate…', 'copy', self._library_duplicate)
        self.lib_remove = add('Remove', 'trash', self._library_remove)
        self.lib_remove.setProperty('destructive', True)
        column.addStretch(1)
        self.lib_guide = add('How to build one', 'book', self._library_guide,
                             'The guide of this folder — also read by the assistant before it creates a file')
        add('Open folder', 'folder', lambda: open_folder(library.kind_dir(self._kind())))
        add('Refresh', 'refresh', self._library_refresh_all)
        # v0.0.20: was in General › Updates and maintenance
        self.lib_restore = add('Restore built-in tools…', 'undo', self.window_.restore_builtin_tools,
                               'Put back the lattice and molecule tools shipped with this version (a backup is kept)')
        body.addLayout(column)
        layout.addLayout(body, 1)
        self.library_status = _hint('')
        layout.addWidget(self.library_status)
        self.kind_combo.currentIndexChanged.connect(lambda _=0: self._library_refresh())
        self._library_refresh()
        return page

    def _kind(self) -> str:
        return str(self.kind_combo.currentData() or 'scripts')

    def _selected(self) -> list[str]:
        return [str(item.data(Qt.ItemDataRole.UserRole)) for item in self.items.selectedItems()]

    def _library_refresh(self):
        if not hasattr(self, 'items'):
            return
        kind = self._kind()
        info = library.KINDS[kind]
        self.kind_description.setText(info.description + '  Folder: ' + str(library.kind_dir(kind)))
        self.items.clear()
        for entry in library.list_items(kind):
            text = entry.label + (f'   —   {entry.detail}' if entry.detail else '')
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry.name)
            item.setToolTip(str(entry.path))
            if not entry.valid:
                item.setForeground(self.palette().brightText())
            self.items.addItem(item)
        self.lib_gwyddion.setVisible(kind == 'colormaps')
        self.lib_readme.setVisible(kind == 'scripts')
        self.lib_restore.setVisible(kind == 'scripts')
        self.lib_new_template.setVisible(kind in library.TEMPLATE_KINDS)
        self.lib_import_folder.setText('Import tool folder…' if kind == 'scripts' else 'Import folder…')
        self.lib_guide.setEnabled(library.guide(kind) is not None)
        self._library_buttons()

    def _library_refresh_all(self):
        """Read the folder again; for scripts also the Tools list of the main window."""
        if self._kind() == 'scripts':
            try:
                self.window_.refresh_modules()
            except Exception as exc:
                self._log(f'Tools not refreshed: {exc}', important=True)
        self._library_refresh()

    def _library_buttons(self):
        chosen = self._selected()
        kind = self._kind()
        self.lib_export.setEnabled(bool(chosen))
        self.lib_remove.setEnabled(bool(chosen))
        self.lib_duplicate.setEnabled(len(chosen) == 1)
        editable = len(chosen) == 1 and kind != 'colormaps'
        self.lib_edit.setEnabled(editable)
        readme = None
        if kind == 'scripts' and len(chosen) == 1:
            readme = paths.module_readme(library.kind_dir(kind) / chosen[0])
        self.lib_readme.setEnabled(readme is not None)

    def _library_changed(self, message: str):
        kind = self._kind()
        try:
            self.window_.reload_library(kind)
        except Exception as exc:
            self._log(f'Library reload failed: {exc}', important=True)
        if kind == 'themes':
            self._fill_themes()
        self._library_refresh()
        self.library_status.setText(message)
        self._log(message)

    def _import(self, source):
        kind = self._kind()
        info = library.KINDS[kind]
        try:
            installed = library.import_path(kind, source)
        except library.ConflictError as conflict:
            box = MessageDialog(self)
            box.setWindowTitle('Already in the library')
            box.setIcon(MessageDialog.Icon.Question)
            box.setText('These items already exist:\n' + '\n'.join(conflict.names) +
                        '\n\nReplace them, or keep both (the imported ones get a new name)?')
            replace = box.addButton('Replace', MessageDialog.ButtonRole.DestructiveRole)
            both = box.addButton('Keep both', MessageDialog.ButtonRole.AcceptRole)
            cancel = box.addButton(MessageDialog.StandardButton.Cancel)
            box.setDefaultButton(cancel)
            box.exec()
            clicked = box.clickedButton()
            box.deleteLater()
            if clicked is replace:
                policy = 'replace'
            elif clicked is both:
                policy = 'rename'
            else:
                return
            try:
                installed = library.import_path(kind, source, on_conflict=policy)
            except Exception as exc:
                MessageDialog.warning(self, 'Import failed', str(exc))
                return
        except Exception as exc:
            MessageDialog.warning(self, 'Import failed', str(exc))
            return
        names = ', '.join(p.name for p in installed)
        self._library_changed(f'Imported {len(installed)} {info.singular}(s): {names}. Nothing was executed.')

    def _library_import_file(self):
        kind = self._kind()
        info = library.KINDS[kind]
        patterns = ' '.join('*' + s for s in info.suffixes)
        if kind == 'scripts':
            patterns = '*.py module.json'
        selected, _ = QFileDialog.getOpenFileName(
            self, 'Import ' + info.singular, str(Path.home()),
            f'{info.label} ({patterns} *.zip);;SPM Studio pack (*.zip);;All files (*)')
        if selected:
            self._import(selected)

    def _library_import_folder(self):
        selected = QFileDialog.getExistingDirectory(self, 'Import a folder of ' + library.KINDS[self._kind()].label.lower(),
                                                    str(Path.home()))
        if selected:
            self._import(selected)

    def _library_new_template(self):
        kind = self._kind()
        name, ok = TextInputDialog.getText(self, 'New template', 'Name of the template:')
        if not ok or not name.strip():
            return
        import json
        from spm_studio.documents import latex_project, templates, deck as deck_model
        try:
            if kind == 'latex_templates':
                target = latex_project.unique_folder(library.kind_dir(kind), name.strip().replace(' ', '_'))
                target.mkdir(parents=True)
                (target / 'main.tex').write_text(latex_project.MINIMAL_DOCUMENT, encoding='utf-8')
                (target / 'figures').mkdir()
                (target / 'template.json').write_text(json.dumps(
                    {'name': name.strip(), 'description': 'My template', 'main': 'main.tex',
                     'category': 'My templates'}, indent=2) + '\n', encoding='utf-8')
                created = target.name
            else:
                target = templates.save_slides_template(
                    {'size': '16:9', 'theme': dict(deck_model.DEFAULT_THEME), 'slides': []}, name.strip(),
                    'My template', include_slides=False)
                created = target.name
        except (OSError, ValueError) as exc:
            MessageDialog.warning(self, 'New template', str(exc))
            return
        self._library_refresh()
        for i in range(self.items.count()):
            if self.items.item(i).data(Qt.ItemDataRole.UserRole) == created:
                self.items.setCurrentRow(i)
        self._library_changed(f'Created template {created}. Edit it, or read “How to build one”.')

    def _library_gwyddion(self):
        self.window_.import_gwyddion_gradients()
        self._library_refresh()

    def _library_export(self):
        kind = self._kind()
        chosen = self._selected()
        if not chosen:
            return
        stem = Path(chosen[0]).stem if len(chosen) == 1 else f'spm-studio-{kind}'
        suggested = Path(str(self.window_.settings.value('library_export_folder', str(Path.home())))) / f'{stem}.zip'
        target, _ = QFileDialog.getSaveFileName(self, 'Export ' + library.KINDS[kind].label.lower(), str(suggested),
                                                'SPM Studio pack (*.zip)')
        if not target:
            return
        try:
            written = library.export_items(kind, chosen, target)
        except Exception as exc:
            MessageDialog.warning(self, 'Export failed', str(exc))
            return
        self.window_.settings.setValue('library_export_folder', str(written.parent))
        self.library_status.setText(f'Exported {len(chosen)} item(s) to {written}. '
                                    'Send this file; the other person uses Import file….')
        self._log(f'Library export: {written}')

    def _library_edit(self):
        chosen = self._selected()
        kind = self._kind()
        if len(chosen) != 1 or kind == 'colormaps':
            return
        try:
            dialog = TextEditDialog(kind, chosen[0], self)
        except Exception as exc:
            MessageDialog.warning(self, 'Edit', str(exc))
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._library_changed(f'Saved {chosen[0]}')

    def _library_readme(self):
        chosen = self._selected()
        if len(chosen) != 1:
            return
        readme = paths.module_readme(library.kind_dir('scripts') / chosen[0])
        if readme is not None:
            GuideDialog(readme, 'Read me — ' + chosen[0], self).exec()

    def _library_duplicate(self):
        chosen = self._selected()
        if len(chosen) != 1:
            return
        kind = self._kind()
        base = Path(chosen[0]).stem if not (library.kind_dir(kind) / chosen[0]).is_dir() else chosen[0]
        name, ok = TextInputDialog.getText(self, 'Duplicate', 'Name of the copy', text=base + '_copy')
        if not ok or not name.strip():
            return
        safe = ''.join(c if c.isalnum() or c in '-_ .' else '_' for c in name.strip())
        try:
            created = library.duplicate_item(kind, chosen[0], safe)
        except Exception as exc:
            MessageDialog.warning(self, 'Duplicate', str(exc))
            return
        self._library_changed(f'Created {created.name}')

    def _library_remove(self):
        chosen = self._selected()
        if not chosen:
            return
        kind = self._kind()
        if not MessageDialog.confirm(
                self, 'Remove from the library',
                'Remove ' + ', '.join(chosen) + '?\n\nThe files are moved to the “removed” folder of SPM Studio '
                'and can be put back from there.', action='Remove'):
            return
        moved = []
        for name in chosen:
            try:
                moved.append(library.remove_item(kind, name))
            except Exception as exc:
                MessageDialog.warning(self, 'Remove', str(exc))
        if moved:
            self._library_changed(f'Removed {len(moved)} item(s); kept in {moved[0].parent}')

    def _library_guide(self):
        guide = library.guide(self._kind())
        if guide is not None:
            GuideDialog(guide, 'How to build: ' + library.KINDS[self._kind()].label, self).exec()

    def done(self, result):
        # Leaving the window ends a pending sign-in and waits briefly for background checks.
        signin = getattr(self, '_signin', None)
        if signin is not None and signin.isRunning():
            signin.cancel()
            signin.wait(3000)
        for task in list(getattr(self, '_lit_tasks', [])):
            task.wait(4000)
        super().done(result)

    # -------------------------------------------------------------------- About
    def _about_page(self):
        from spm_studio.core.updates import current_version
        page, layout = self._page('About')
        head = QHBoxLayout()
        head.setSpacing(16)
        logo = QLabel()
        logo.setFixedSize(72, 72)
        logo.setScaledContents(True)
        icon_path = Path(__file__).resolve().parents[1] / 'resources' / 'spm-studio.png'
        if icon_path.is_file():
            logo.setPixmap(QPixmap(str(icon_path)))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel('SPM Studio')
        title.setObjectName('aboutTitle')
        text.addWidget(title)
        self.about_version = QLabel(f'Version {current_version()}')
        self.about_version.setObjectName('muted')
        self.about_version.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.addWidget(self.about_version)
        text.addWidget(_hint('Scientific image and data analysis for scanning probe microscopy (STM · AFM · KPFM).'))
        head.addLayout(text, 1)
        layout.addLayout(head)

        box = QGroupBox('Author')
        v = QVBoxLayout(box)
        author = QLabel(
            f'SPM Studio is developed and maintained by <a href="{paths.AUTHOR_URL}">{paths.AUTHOR_NAME}</a>.<br><br>'
            'Questions, bug reports and suggestions are welcome on the project’s GitHub page: '
            f'<a href="{paths.GITHUB_URL}/issues">open an issue</a> to report a problem or propose an improvement, '
            f'or contact the author through <a href="{paths.AUTHOR_URL}">GitHub</a>.')
        author.setObjectName('AboutAuthorV005')
        author.setTextFormat(Qt.TextFormat.RichText)
        author.setOpenExternalLinks(True)
        author.setWordWrap(True)
        v.addWidget(author)
        row = QHBoxLayout()
        github = _icon_button('Open the project on GitHub', 'link')
        github.setObjectName('AboutGitHubButtonV005')
        github.setProperty('primary', True)
        github.clicked.connect(lambda: open_url(paths.GITHUB_URL))
        issue = QPushButton('Report a problem')
        issue.clicked.connect(lambda: open_url(paths.GITHUB_URL + '/issues/new'))
        row.addWidget(github)
        row.addWidget(issue)
        row.addStretch(1)
        v.addLayout(row)
        layout.addWidget(box)

        box = QGroupBox('Licence and privacy')
        v = QVBoxLayout(box)
        v.addWidget(_hint('Free and open-source software, released under the MIT Licence. SPM Studio analyses saved '
                          'data only and never connects to a microscope. It uses the network for the update check '
                          '(it can be switched off in Settings › Updates) and, only if you set them up, for the '
                          'AI assistant and the literature sources.'))
        row = QHBoxLayout()
        licence = QPushButton('Read the licence')
        licence_file = paths.bundled_studio_root() / 'LICENSE'
        licence.clicked.connect(lambda: GuideDialog(licence_file, 'Licence', self).exec() if licence_file.is_file()
                                else open_url(paths.GITHUB_URL + '/blob/main/LICENSE'))
        row.addWidget(licence)
        row.addStretch(1)
        v.addLayout(row)
        layout.addWidget(box)
        layout.addStretch(1)
        return page
