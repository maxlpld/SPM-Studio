"""Settings (v0.0.5): one window behind the gear button of the top bar.

Pages (v0.0.20: every option is in exactly one place)
-----------------------------------------------------
* **General** — projects and crash recovery, scans, logs, keyboard, assistant, maintenance.
* **Appearance** — theme, Theme Studio, help texts, pop-ups, outline of the selected channel.
* **Library** — import / export / edit / remove scripts, profiles, export profiles,
  themes, colormaps, plot styles and shortcut files (``core.library``); built-in tools.
* **Literature** — Consensus and Zotero for the assistant (``ai.literature``).
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
         ('literature', 'Literature', 'book'), ('documents', 'Documents', 'latex'),
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
                          'library': self._library_page, 'literature': self._literature_page,
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

        box = QGroupBox('Keyboard and assistant')
        v = QVBoxLayout(box)
        b = QPushButton('Keyboard shortcuts…')
        b.clicked.connect(w.open_shortcut_options)
        self._action_row(v, 'Keyboard shortcuts', 'See and change every shortcut.', b)
        b = QPushButton('AI assistant…')
        b.clicked.connect(lambda: w.ai_dock.setup())
        self._action_row(v, 'AI assistant', 'Choose and sign in to the assistant (Pi, Claude Code, Codex or an API).', b)
        layout.addWidget(box)

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

    # --------------------------------------------------------------- Literature
    # v0.0.7: both sources are connected here, by SPM Studio itself. No agent, terminal or
    # configuration file is involved, and the assistant can use them in every chat mode.
    def _literature_page(self):
        from spm_studio.ai import literature
        from spm_studio.ai.config import load
        conf = load()
        self._lit_tasks = []
        self._signin = None
        page, layout = self._page(
            'Literature',
            'Let the assistant look things up in the published literature and in your own reference library. '
            'It only reads; it can never change your library. Connect a source once here and it works with '
            'every assistant, in ordinary chat too.')

        # ---- Consensus
        box = QGroupBox('Consensus')
        v = QVBoxLayout(box)
        v.addWidget(_hint(
            'consensus.app searches peer-reviewed papers. Sign in with your own Consensus account — your '
            'university e-mail uses your institution’s licence — and, if you linked Zotero inside Consensus, '
            'Consensus uses it too. The sign-in page opens in your browser; SPM Studio never sees your password.'))
        self.consensus_state = QLabel('')
        self.consensus_state.setObjectName('ConsensusStateV007')
        self.consensus_state.setWordWrap(True)
        v.addWidget(self.consensus_state)
        row = QHBoxLayout()
        self.consensus_signin = _icon_button('Sign in to Consensus', 'link',
                                             'Opens the Consensus sign-in page in your browser')
        self.consensus_signin.setObjectName('ConsensusSignInV007')
        self.consensus_signin.setProperty('primary', True)
        self.consensus_signin.clicked.connect(self._consensus_sign_in)
        self.consensus_cancel = QPushButton('Cancel')
        self.consensus_cancel.clicked.connect(self._consensus_cancel)
        self.consensus_cancel.hide()
        self.consensus_test = QPushButton('Test')
        self.consensus_test.setToolTip('Check the connection to Consensus')
        self.consensus_test.clicked.connect(self._consensus_test)
        self.consensus_signout = QPushButton('Sign out')
        self.consensus_signout.clicked.connect(self._consensus_sign_out)
        for button in (self.consensus_signin, self.consensus_cancel, self.consensus_test, self.consensus_signout):
            row.addWidget(button)
        row.addStretch(1)
        v.addLayout(row)
        self.consensus_progress = QProgressBar()
        self.consensus_progress.setProperty('role', 'activity')
        self.consensus_progress.setRange(0, 0)
        self.consensus_progress.setTextVisible(False)
        self.consensus_progress.hide()
        v.addWidget(self.consensus_progress)
        self.consensus_status = _hint('')
        self.consensus_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.consensus_status)
        self.consensus_enabled = QCheckBox('Let the assistant use Consensus')
        self.consensus_enabled.setObjectName('ConsensusEnabledV005')
        self.consensus_enabled.setChecked(bool(conf.get('consensus_enabled')))
        self.consensus_enabled.clicked.connect(lambda _=False: self._literature_apply())
        v.addWidget(self.consensus_enabled)
        self.consensus_advanced = QGroupBox('Advanced: use an API key instead')
        self.consensus_advanced.setCheckable(True)
        self.consensus_advanced.setChecked(False)
        adv = QVBoxLayout(self.consensus_advanced)
        self.consensus_key_help = _hint('Only if your organisation gave you a Consensus API key (consensus.app › profile › '
                                        'API & MCP Dashboard › Keys). Otherwise use “Sign in to Consensus”.')
        adv.addWidget(self.consensus_key_help)
        key_row = QHBoxLayout()
        self.consensus_key = QLineEdit()
        self.consensus_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.consensus_key.setPlaceholderText('Consensus API key')
        self.consensus_key_save = QPushButton('Save key')
        self.consensus_key_save.clicked.connect(self._consensus_save_key)
        key_row.addWidget(self.consensus_key, 1)
        key_row.addWidget(self.consensus_key_save)
        adv.addLayout(key_row)
        self._consensus_advanced_widgets = (self.consensus_key_help, self.consensus_key, self.consensus_key_save)
        self.consensus_advanced.toggled.connect(self._consensus_advanced_toggled)
        self._consensus_advanced_toggled(False)
        v.addWidget(self.consensus_advanced)
        layout.addWidget(box)

        # ---- Zotero
        box = QGroupBox('Zotero')
        v = QVBoxLayout(box)
        v.addWidget(_hint('Your own references: the assistant can search your library and read abstracts, notes and '
                          'the text of indexed PDFs. Works with or without Consensus, and nothing leaves this computer.'))
        self.zotero_state = QLabel('')
        self.zotero_state.setObjectName('ZoteroStateV007')
        self.zotero_state.setWordWrap(True)
        v.addWidget(self.zotero_state)
        row = QHBoxLayout()
        self.zotero_connect = _icon_button('Connect Zotero', 'link', 'Find Zotero on this computer and connect it')
        self.zotero_connect.setObjectName('ZoteroConnectV007')
        self.zotero_connect.setProperty('primary', True)
        self.zotero_connect.clicked.connect(self._zotero_connect)
        self.zotero_test_button = QPushButton('Test')
        self.zotero_test_button.clicked.connect(self._zotero_test)
        self.zotero_disconnect = QPushButton('Disconnect')
        self.zotero_disconnect.clicked.connect(self._zotero_disconnect)
        for button in (self.zotero_connect, self.zotero_test_button, self.zotero_disconnect):
            row.addWidget(button)
        row.addStretch(1)
        v.addLayout(row)
        self.zotero_status = _hint('')
        self.zotero_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.zotero_status)

        self.zotero_advanced = QGroupBox('Advanced: choose how Zotero is read')
        self.zotero_advanced.setCheckable(True)
        self.zotero_advanced.setChecked(conf.get('zotero_mode') in ('local', 'database', 'web'))
        adv = QVBoxLayout(self.zotero_advanced)
        self.zotero_advanced_body = QWidget()
        form = QFormLayout(self.zotero_advanced_body)
        form.setContentsMargins(0, 0, 0, 0)
        self.zotero_mode = QComboBox()
        self.zotero_mode.setObjectName('ZoteroModeV005')
        self.zotero_mode.addItem('Not connected', 'off')
        self.zotero_mode.addItem('Automatic (recommended)', 'auto')
        self.zotero_mode.addItem('Zotero database file — any version, Zotero may be closed', 'database')
        self.zotero_mode.addItem('Zotero app — version 7 or later, must be running', 'local')
        self.zotero_mode.addItem('zotero.org account — library on the web', 'web')
        self.zotero_mode.setCurrentIndex(max(0, self.zotero_mode.findData(conf.get('zotero_mode', 'off'))))
        form.addRow('Read from', self.zotero_mode)
        self.zotero_mode_help = _hint('')
        form.addRow('', self.zotero_mode_help)
        folder_row = QWidget()
        fr = QHBoxLayout(folder_row)
        fr.setContentsMargins(0, 0, 0, 0)
        self.zotero_folder = QLineEdit(str(conf.get('zotero_data_dir', '')))
        self.zotero_folder.setPlaceholderText('Found automatically — fill in only if your Zotero data is elsewhere')
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._zotero_browse)
        fr.addWidget(self.zotero_folder, 1)
        fr.addWidget(browse)
        form.addRow('Data folder', folder_row)
        self.zotero_folder_row = (form.labelForField(folder_row), folder_row)
        self.zotero_type = QComboBox()
        self.zotero_type.addItem('My library', 'user')
        self.zotero_type.addItem('Group library', 'group')
        self.zotero_type.setCurrentIndex(max(0, self.zotero_type.findData(conf.get('zotero_library_type', 'user'))))
        self.zotero_id = QLineEdit(str(conf.get('zotero_library_id', '')))
        self.zotero_id.setPlaceholderText('Numeric user ID (zotero.org › Settings › Security) or group ID')
        self.zotero_key = QLineEdit()
        self.zotero_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.zotero_key.setPlaceholderText('Stored — leave empty to keep it' if literature.zotero_api_key()
                                           else 'Private key with read-only library access')
        self.zotero_web_rows = []
        for label, widget in (('Library', self.zotero_type), ('Library ID', self.zotero_id), ('API key', self.zotero_key)):
            form.addRow(label, widget)
            self.zotero_web_rows.append((form.labelForField(widget), widget))
        adv.addWidget(self.zotero_advanced_body)
        row = QHBoxLayout()
        self.zotero_save = QPushButton('Save and test')
        self.zotero_save.setObjectName('LiteratureApplyV005')
        self.zotero_save.clicked.connect(lambda: (self._literature_apply(), self._zotero_test()))
        keys = QPushButton('Open zotero.org key page')
        keys.clicked.connect(lambda: open_url('https://www.zotero.org/settings/security'))
        self.zotero_keys_button = keys
        row.addWidget(self.zotero_save)
        row.addWidget(keys)
        row.addStretch(1)
        self.zotero_advanced_buttons = QWidget()
        self.zotero_advanced_buttons.setLayout(row)
        adv.addWidget(self.zotero_advanced_buttons)
        self.zotero_advanced.toggled.connect(self._zotero_advanced_toggled)
        v.addWidget(self.zotero_advanced)
        layout.addWidget(box)

        self.literature_result = _hint('')
        layout.addWidget(self.literature_result)
        self.literature_agent = _hint('')
        layout.addWidget(self.literature_agent)
        layout.addStretch(1)
        self.zotero_mode.currentIndexChanged.connect(lambda _=0: self._literature_sync())
        self._zotero_advanced_toggled(self.zotero_advanced.isChecked())
        self._literature_sync()
        self._literature_refresh_state()
        return page

    # ---- shared state
    def _consensus_advanced_toggled(self, on):
        for widget in self._consensus_advanced_widgets:
            widget.setVisible(bool(on))

    def _zotero_advanced_toggled(self, on):
        self.zotero_advanced_body.setVisible(bool(on))
        self.zotero_advanced_buttons.setVisible(bool(on))

    def _literature_sync(self):
        mode = self.zotero_mode.currentData()
        self.zotero_mode_help.setText({
            'off': 'The assistant does not use Zotero.',
            'auto': 'Asks the Zotero app when it is running and allows it, otherwise reads the database file. '
                    'Nothing to set up.',
            'database': 'Reads zotero.sqlite in your Zotero data folder, read-only. Works with every Zotero version, '
                        'whether Zotero is open or not, and needs no setting in Zotero.',
            'local': 'Zotero 7 or later must be running, with Settings › Advanced › “Allow other applications on this '
                     'computer to communicate with Zotero” ticked. Also searches inside indexed PDFs.',
            'web': 'Reads your library on zotero.org. Create a private key with read-only library access at '
                   'zotero.org › Settings › Security; it is kept on this computer only.'}.get(mode, ''))
        for label_widget, widget in self.zotero_web_rows:
            widget.setVisible(mode == 'web')
            if label_widget is not None:
                label_widget.setVisible(mode == 'web')
        self.zotero_keys_button.setVisible(mode == 'web')
        folder_label, folder_widget = self.zotero_folder_row
        folder_widget.setVisible(mode in ('auto', 'database'))
        if folder_label is not None:
            folder_label.setVisible(mode in ('auto', 'database'))

    def _literature_refresh_state(self):
        """Status lines of both sources, from what is stored (no network)."""
        from spm_studio.ai import consensus, literature
        from spm_studio.ai.config import load
        conf = load()
        signed = consensus.signed_in()
        on = bool(conf.get('consensus_enabled'))
        if signed and on:
            self.consensus_state.setText('<b>● Connected.</b> The assistant can search Consensus.')
        elif signed:
            self.consensus_state.setText('<b>○ Signed in, but switched off.</b> Tick the box below to let the assistant use it.')
        else:
            self.consensus_state.setText('<b>○ Not connected.</b> Click “Sign in to Consensus”.')
        self.consensus_signin.setText('Sign in again' if signed else 'Sign in to Consensus')
        self.consensus_signout.setEnabled(signed)
        self.consensus_test.setEnabled(signed)
        self.consensus_enabled.setEnabled(signed)
        self.consensus_enabled.setChecked(on and signed)
        zotero_on = literature.zotero_enabled(conf)
        self.zotero_state.setText('<b>● Connected.</b> The assistant can read your Zotero library.' if zotero_on else
                                  '<b>○ Not connected.</b> Click “Connect Zotero”.')
        self.zotero_connect.setText('Connect again' if zotero_on else 'Connect Zotero')
        self.zotero_disconnect.setEnabled(zotero_on)
        self.zotero_test_button.setEnabled(zotero_on)
        backend = str(conf.get('backend', 'none'))
        self.literature_agent.setText(
            'No assistant is set up yet (General › AI assistant…): the sources are ready for when one is.'
            if backend == 'none' else
            'The assistant looks things up when you ask for literature, references or what is in your library — '
            'for example: “What does my Zotero library say about KPFM on graphene?”')

    def _restart_assistant(self):
        """The assistant is told about a changed source from its next message."""
        dock = getattr(self.window_, 'ai_dock', None)
        if dock is None:
            return
        if getattr(dock, '_running', False):
            self.literature_result.setText('The assistant uses the change after its current reply.')
            return
        try:
            dock._open_backend()
        except Exception as exc:
            self._log('Assistant restart failed: ' + str(exc))

    def _run_task(self, fn, on_done):
        """Run ``fn()`` off the GUI thread; ``on_done(result, error_text)`` back in the GUI thread."""
        task = _Task(fn, on_done, self)
        self._lit_tasks.append(task)
        task.finished_with.connect(self._task_finished)
        task.start()
        return task

    def _task_finished(self, task, result, error):
        if task in self._lit_tasks:
            self._lit_tasks.remove(task)
        task.on_done(result, error)

    def _literature_conf(self) -> dict:
        from spm_studio.ai.config import load
        conf = load()
        conf['consensus_enabled'] = self.consensus_enabled.isChecked()
        conf['zotero_mode'] = str(self.zotero_mode.currentData())
        conf['zotero_library_type'] = str(self.zotero_type.currentData())
        conf['zotero_library_id'] = self.zotero_id.text().strip()
        conf['zotero_data_dir'] = self.zotero_folder.text().strip()
        return conf

    def _store_zotero_key(self) -> str:
        key = self.zotero_key.text().strip()
        if not key:
            return ''
        from spm_studio.ai import lit_store, literature
        note = lit_store.put(literature.ZOTERO_KEY_NAME, key)
        self.zotero_key.clear()
        self.zotero_key.setPlaceholderText('Stored — leave empty to keep it')
        return 'Key ' + note

    def _literature_apply(self):
        """Save what the page shows (used by the tick box and by “Save and test”)."""
        from spm_studio.ai.config import save
        conf = self._literature_conf()
        if conf['zotero_mode'] == 'web' and not conf['zotero_library_id'].isdigit():
            self.literature_result.setText('The Zotero library ID is a number (zotero.org › Settings › Security).')
            return False
        key_note = self._store_zotero_key()
        try:
            save(conf)
        except (OSError, ValueError) as exc:
            self.literature_result.setText('Not saved: ' + str(exc))
            return False
        self.literature_result.setText('Saved.' + (f' {key_note}.' if key_note else ''))
        self._log('Literature sources saved')
        self._literature_refresh_state()
        self._restart_assistant()
        return True

    # ---- Consensus
    def _consensus_busy(self, on: bool, text: str = ''):
        self.consensus_progress.setVisible(on)
        self.consensus_cancel.setVisible(on)
        self.consensus_signin.setEnabled(not on)
        if text:
            self.consensus_status.setText(text)

    def _consensus_sign_in(self):
        if self._signin is not None and self._signin.isRunning():
            return
        worker = _ConsensusSignIn(self)
        self._signin = worker
        worker.opened.connect(self._consensus_opened)
        worker.done.connect(self._consensus_signed_in)
        worker.failed.connect(self._consensus_failed)
        self._consensus_busy(True, 'Contacting Consensus…')
        worker.start()

    def _consensus_opened(self, url):
        opened = QDesktopServices.openUrl(QUrl(url))
        self._signin_url = url
        self.consensus_status.setText(
            'Your browser opened the Consensus sign-in page. Sign in there (your university e-mail works), allow '
            'SPM Studio, then come back here — this page updates by itself.' if opened else
            'Open this address in your browser to sign in: ' + url)

    def _consensus_cancel(self):
        if self._signin is not None:
            self._signin.cancel()

    def _consensus_signed_in(self, stored):
        from spm_studio.ai.config import load, save
        self._consensus_busy(False)
        conf = load()
        conf['consensus_enabled'] = True
        try:
            save(conf)
        except (OSError, ValueError) as exc:
            self.consensus_status.setText('Signed in, but the setting could not be saved: ' + str(exc))
            return
        self.consensus_status.setText('Signed in. The sign-in is ' + stored + '.')
        self._log('Consensus: signed in')
        self._literature_refresh_state()
        self._restart_assistant()
        self.raise_()
        self.activateWindow()

    def _consensus_failed(self, message):
        self._consensus_busy(False)
        self.consensus_status.setText('Not signed in — ' + message)
        self._literature_refresh_state()

    def _consensus_test(self):
        from spm_studio.ai import consensus
        self.consensus_status.setText('Checking…')
        self.consensus_test.setEnabled(False)

        def done(result, error):
            self.consensus_test.setEnabled(True)
            if error:
                self.consensus_status.setText('✗ ' + error)
            else:
                self.consensus_status.setText(('✓ ' if result['connected'] else '✗ ') + result['message'])
        self._run_task(consensus.status, done)

    def _consensus_sign_out(self):
        from spm_studio.ai import consensus
        from spm_studio.ai.config import load, save
        consensus.sign_out()
        conf = load()
        conf['consensus_enabled'] = False
        try:
            save(conf)
        except (OSError, ValueError):
            pass
        self.consensus_status.setText('Signed out: the sign-in was removed from this computer.')
        self._literature_refresh_state()
        self._restart_assistant()

    def _consensus_save_key(self):
        from spm_studio.ai import consensus, lit_store
        from spm_studio.ai.config import load, save
        key = self.consensus_key.text().strip()
        if not key:
            self.consensus_status.setText('Paste the API key first.')
            return
        note = lit_store.put(consensus.API_KEY_NAME, key)
        self.consensus_key.clear()
        conf = load()
        conf['consensus_enabled'] = True
        try:
            save(conf)
        except (OSError, ValueError):
            pass
        self.consensus_status.setText('API key ' + note + '.')
        self._literature_refresh_state()
        self._restart_assistant()
        self._consensus_test()

    # ---- Zotero
    def _zotero_browse(self):
        start = self.zotero_folder.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, 'Zotero data folder (contains zotero.sqlite)', start)
        if chosen:
            self.zotero_folder.setText(chosen)

    def _zotero_connect(self):
        """One click: find Zotero on this computer (app or database file) and connect it."""
        from spm_studio.ai import literature
        conf = self._literature_conf()
        self.zotero_connect.setEnabled(False)
        self.zotero_status.setText('Looking for Zotero on this computer…')

        def done(found, error):
            self.zotero_connect.setEnabled(True)
            if error or not found or not found.get('found'):
                self.zotero_advanced.setChecked(True)
                self.zotero_status.setText(
                    '✗ ' + (error or 'No Zotero library was found on this computer. If Zotero is installed, start it '
                            'once, or choose its data folder below (Zotero shows it in Settings › Advanced › Files '
                            'and Folders). For a library kept only on zotero.org, choose “zotero.org account”.'))
                return
            self.zotero_mode.setCurrentIndex(self.zotero_mode.findData('auto'))
            if not self._literature_apply():
                return
            parts = []
            if found.get('data_dir'):
                parts.append(f"{found.get('items')} items in {found['data_dir']}")
            parts.append('the Zotero app answers too (indexed PDFs are searched as well)' if found.get('app') else
                         'read from the database file — Zotero does not need to be open')
            self.zotero_status.setText('✓ Connected: ' + '; '.join(parts) + '.')
        self._run_task(lambda: literature.detect_zotero(conf), done)

    def _zotero_test(self):
        from spm_studio.ai import literature
        conf = self._literature_conf()
        if conf['zotero_mode'] == 'off':
            self.zotero_status.setText('Not connected. Click “Connect Zotero”.')
            return
        self._store_zotero_key()
        self.zotero_status.setText('Checking…')

        def done(status, error):
            if error:
                self.zotero_status.setText('✗ ' + error)
            else:
                self.zotero_status.setText(('✓ ' if status['connected'] else '✗ ') + status['message'])
        self._run_task(lambda: literature.zotero_status(conf), done)

    def _zotero_disconnect(self):
        self.zotero_mode.setCurrentIndex(self.zotero_mode.findData('off'))
        if self._literature_apply():
            self.zotero_status.setText('Disconnected. Nothing was changed in Zotero.')

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
