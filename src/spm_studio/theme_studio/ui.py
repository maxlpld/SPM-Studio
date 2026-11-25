"""Theme Studio window (Qt): Library · Visual Editor · SVG Skins, with a live preview gallery."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QFontComboBox,
                               QFormLayout, QFrame, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QSlider, QSpinBox, QSplitter, QTabWidget,
                               QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import model, svgskin
from .runtime import Picker, render_check, theme_name

SHIPPED = {'graphite', 'porcelain', 'light_studio', 'dark_studio'}
BASE_FIELDS = (('accent', 'Accent'), ('background', 'Window background'), ('surface', 'Panels'),
               ('raised', 'Buttons'), ('input', 'Inputs'), ('foreground', 'Text'), ('muted', 'Secondary text'),
               ('border', 'Borders'), ('danger', 'Danger / delete'), ('success', 'Success'), ('warning', 'Warning'))




class ColorField(QWidget):
    """Swatch + #RRGGBBAA field + picker (with alpha) + clear."""

    def __init__(self, on_change, allow_alpha=True, clearable=True):
        super().__init__()
        self.on_change, self.allow_alpha = on_change, allow_alpha
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(28, 22)
        self.swatch.setToolTip('Choose a colour')
        self.swatch.clicked.connect(self.pick)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText('#RRGGBB' + ('AA' if allow_alpha else ''))
        self.edit.setMaxLength(9 if allow_alpha else 7)
        self.edit.editingFinished.connect(self._typed)
        row.addWidget(self.swatch)
        row.addWidget(self.edit, 1)
        if clearable:
            clear = QToolButton()
            clear.setText('×')
            clear.setToolTip('Use the inherited value')
            clear.clicked.connect(lambda: self.on_change(None))
            row.addWidget(clear)

    def set_value(self, value, inherited=''):
        self.edit.blockSignals(True)
        self.edit.setText(value or '')
        self.edit.setPlaceholderText(f'inherited {inherited}' if inherited and not value else
                                     '#RRGGBB' + ('AA' if self.allow_alpha else ''))
        self.edit.blockSignals(False)
        shown = value or inherited or '#00000000'
        try:
            r, g, b, a = model.parse_color(shown)
            self.swatch.setStyleSheet(f'background: rgba({r},{g},{b},{a}); border: 1px solid gray;')
        except ValueError:
            pass

    def pick(self):
        current = self.edit.text() or self.edit.placeholderText().replace('inherited ', '')
        try:
            r, g, b, a = model.parse_color(current)
            start = QColor(r, g, b, a)
        except ValueError:
            start = QColor('#808080')
        if self.allow_alpha:
            color = QColorDialog.getColor(start, self, 'Choose a colour',
                                          QColorDialog.ColorDialogOption.ShowAlphaChannel)
        else:
            color = QColorDialog.getColor(start, self, 'Choose a colour')
        if color.isValid():
            value = f'#{color.red():02X}{color.green():02X}{color.blue():02X}'
            if self.allow_alpha and color.alpha() < 255:
                value += f'{color.alpha():02X}'
            self.on_change(value)

    def _typed(self):
        text = self.edit.text().strip()
        if not text:
            self.on_change(None)
            return
        try:
            model.parse_color(text if text.startswith('#') else '#' + text)
        except ValueError as exc:
            QMessageBox.warning(self, 'Colour', str(exc))
            return
        self.on_change((text if text.startswith('#') else '#' + text).upper())


def preview_gallery() -> QWidget:
    """Representative controls of SPM Studio (no action is connected)."""
    root = QFrame()
    root.setObjectName('ThemePreview')
    root.setAutoFillBackground(True)
    v = QVBoxLayout(root)
    title = QLabel('Preview')
    title.setObjectName('heading')
    hint = QLabel('These controls do nothing; they show the theme.')
    hint.setObjectName('hint')
    v.addWidget(title)
    v.addWidget(hint)
    row = QHBoxLayout()
    for text, prop in (('Run', 'primary'), ('Button', None), ('Delete', 'destructive')):
        b = QPushButton(text)
        if prop:
            b.setProperty(prop, True)
        row.addWidget(b)
    off = QPushButton('Disabled')
    off.setEnabled(False)
    row.addWidget(off)
    tool = QToolButton()
    tool.setText('Tool ▾')
    tool.setMenu(QMenu(tool))
    tool.menu().addAction('Menu item')
    tool.menu().addAction('Another item')
    tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    row.addWidget(tool)
    v.addLayout(row)
    form = QFormLayout()
    form.addRow('Input', QLineEdit('Editable text'))
    combo = QComboBox()
    combo.addItems(['Drop-down', 'Second'])
    form.addRow('List', combo)
    spin = QSpinBox()
    spin.setValue(42)
    form.addRow('Number', spin)
    v.addLayout(form)
    checks = QHBoxLayout()
    c = QCheckBox('Check box')
    c.setChecked(True)
    checks.addWidget(c)
    checks.addWidget(QRadioButton('Radio'))
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setValue(60)
    checks.addWidget(slider, 1)
    v.addLayout(checks)
    tabs = QTabWidget()
    log = QPlainTextEdit('12:00:01  Scan loaded\n12:00:02  Profile applied\n12:00:03  Export finished')
    log.setReadOnly(True)
    tabs.addTab(log, 'Log')
    table = QTableWidget(2, 2)
    table.setHorizontalHeaderLabels(['Channel', 'Unit'])
    for r, (a, b) in enumerate((('Z', 'm'), ('Current', 'A'))):
        table.setItem(r, 0, QTableWidgetItem(a))
        table.setItem(r, 1, QTableWidgetItem(b))
    tabs.addTab(table, 'Table')
    tabs.addTab(QPlainTextEdit('Editable notes'), 'Text')
    v.addWidget(tabs, 1)
    group = QGroupBox('Panel')
    gv = QVBoxLayout(group)
    bar = QProgressBar()
    bar.setValue(35)
    gv.addWidget(bar)
    timer = QTimer(root)
    timer.timeout.connect(lambda: bar.setValue((bar.value() + 1) % 101))
    timer.start(80)
    gv.addWidget(QLabel('Progress bars keep updating under any skin.'))
    v.addWidget(group)
    return root


class ThemeStudioWindow(QMainWindow):
    def __init__(self, ext):
        super().__init__(ext.window)
        self.ext, self.store, self.runtime = ext, ext.store, ext.runtime
        self.setObjectName('ThemeStudioWindow')
        self.setWindowTitle('Theme Studio — SPM Studio')
        self.resize(1180, 760)
        self.slug = ''                       # profile being edited ('' = not saved yet)
        self.profile = None
        self.saved = None
        self.undo_stack, self.redo_stack = [], []
        self.role, self.state = 'button', 'normal'
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName('heading')
        head.addWidget(self.title)
        self.dirty_label = QLabel()
        self.dirty_label.setObjectName('hint')
        head.addWidget(self.dirty_label)
        head.addStretch(1)
        root.addLayout(head)
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet('color: #E8B54D;')
        root.addWidget(self.warnings)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._library_tab(), 'Theme Library')
        self.tabs.addTab(self._editor_tab(), 'Visual Editor')
        self.tabs.addTab(self._skins_tab(), 'SVG Skins')
        split.addWidget(self.tabs)
        self.gallery = preview_gallery()
        split.addWidget(self.gallery)
        split.setSizes([680, 480])
        root.addWidget(split, 1)
        bar = QHBoxLayout()
        self.undo_button = QPushButton('Undo')
        self.redo_button = QPushButton('Redo')
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.live = QCheckBox('Preview on the whole app')
        self.live.setToolTip('Temporary: Cancel brings back the theme you had; Apply keeps it')
        self.live.toggled.connect(self._live_toggled)
        reset = QPushButton('Reset to saved')
        reset.clicked.connect(self.reset_to_saved)
        defaults = QPushButton('Restore defaults')
        defaults.setToolTip('Remove every Visual Editor change (keeps the base colours)')
        defaults.clicked.connect(self.restore_defaults)
        save = QPushButton('Save')
        save.clicked.connect(self.save)
        save_as = QPushButton('Save As…')
        save_as.clicked.connect(self.save_as)
        apply = QPushButton('Apply')
        apply.setProperty('primary', True)
        apply.clicked.connect(self.apply)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.cancel)
        for w in (self.undo_button, self.redo_button, self.live):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (reset, defaults, save, save_as, apply, cancel):
            bar.addWidget(w)
        root.addLayout(bar)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self.redo)
        self.picker = Picker(self)
        self.picker.picked.connect(self._picked)
        self.picker.finished.connect(lambda: self.pick_button.setChecked(False))
        self.open_current()
        self.refresh_library()
        self.refresh_skins()

    # ================================================================== profile state
    def open_current(self):
        slug = self.runtime.active_slug()
        profiles = self.store.list()
        if slug in profiles:
            self.load_profile(slug, profiles[slug])
        else:
            from spm_studio.shared.appearance import colors
            name = self.runtime.current_theme() or 'graphite'
            self.load_profile('', model.new_profile(f'{name} (custom)', colors(), name))

    def load_profile(self, slug, profile):
        self.slug, self.profile = slug, model.snapshot(profile)
        self.saved = model.snapshot(profile) if slug else None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.update_all()

    def dirty(self) -> bool:
        return self.saved is None or json.dumps(self.saved, sort_keys=True) != json.dumps(self.profile, sort_keys=True)

    def tokens(self) -> dict:
        from spm_studio.shared.appearance import complete_tokens
        return complete_tokens(self.profile['base'])

    def change(self, mutate):
        before = model.snapshot(self.profile)
        try:
            mutate(self.profile)
        except ValueError as exc:
            QMessageBox.warning(self, 'Theme Studio', str(exc))
            self.profile = before
            return
        self.undo_stack.append(before)
        self.redo_stack.clear()
        self.update_all()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(model.snapshot(self.profile))
            self.profile = self.undo_stack.pop()
            self.update_all()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(model.snapshot(self.profile))
            self.profile = self.redo_stack.pop()
            self.update_all()

    def update_all(self):
        """Gallery (and the app, if previewing) follow every change at once."""
        from spm_studio.shared.appearance import stylesheet
        tokens = self.tokens()
        scope = '#ThemePreview'
        sheet = (stylesheet(tokens) + f'\n#ThemePreview {{ background: {tokens["background"]}; }}\n'
                 + self.runtime.overlay_for(self.profile, scope))
        self.gallery.setStyleSheet(sheet)
        if self.live.isChecked():
            self.runtime.update_preview(self.profile)
        name = self.profile['name'] + ('' if self.slug else '  (not saved)')
        self.title.setText(f'Theme Studio — {name}')
        self.dirty_label.setText('● unsaved changes' if self.dirty() else 'saved')
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.redo_button.setEnabled(bool(self.redo_stack))
        warnings = model.contrast_warnings(self.profile, tokens)
        self.warnings.setText('⚠ ' + ' · '.join(warnings) if warnings else '')
        self._fill_props()
        self._fill_base()

    # ================================================================== library
    def _library_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel('Your themes. Shipped themes cannot be deleted; Theme Studio profiles also appear in the '
                           'normal theme menu (named “studio_…”).'))
        self.library = QListWidget()
        self.library.setObjectName('ThemeLibraryList')
        v.addWidget(self.library, 1)
        row = QHBoxLayout()
        for label, slot in (('Activate', self.lib_activate), ('Edit', self.lib_edit),
                            ('Duplicate…', self.lib_duplicate), ('Rename…', self.lib_rename),
                            ('Export…', self.lib_export), ('Import…', self.lib_import), ('Delete', self.lib_delete)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        return page

    def refresh_library(self):
        self.library.clear()
        current = self.runtime.current_theme()
        for path in self.ext.window._theme_files():
            if path.stem.startswith('studio_'):
                continue
            item = QListWidgetItem(f"{path.stem}  —  {'shipped' if path.stem in SHIPPED else 'theme file'}")
            item.setData(Qt.ItemDataRole.UserRole, ('theme', path.stem))
            if path.stem == current:
                item.setText(item.text() + '  ✓ active')
            self.library.addItem(item)
        for slug, profile in self.store.list().items():
            text = f"{profile['name']}  —  Theme Studio profile" + ('  + SVG skin' if profile['skin'] else '')
            if theme_name(slug) == current:
                text += '  ✓ active'
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, ('profile', slug))
            self.library.addItem(item)

    def _lib_selected(self):
        item = self.library.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else (None, None)

    def confirm_discard(self) -> bool:
        if not self.dirty() or (self.saved is None and not self.undo_stack):
            return True
        answer = QMessageBox.question(self, 'Unsaved changes', 'Discard the unsaved changes of this profile?')
        return answer == QMessageBox.StandardButton.Yes

    def lib_activate(self):
        kind, key = self._lib_selected()
        if not kind or not self.confirm_discard():
            return
        self.live.setChecked(False)
        if kind == 'theme':
            self.runtime.activate_theme(key)
        else:
            self.runtime.activate_profile(key)
        self.open_current()
        self.refresh_library()

    def lib_edit(self):
        kind, key = self._lib_selected()
        if not kind or not self.confirm_discard():
            return
        if kind == 'profile':
            self.load_profile(key, self.store.load(key))
        else:
            from spm_studio.core import paths
            from spm_studio.shared.appearance import complete_tokens
            data = json.loads((paths.customization_dir() / 'themes' / f'{key}.json').read_text(encoding='utf8'))
            self.load_profile('', model.new_profile(f'{key} (custom)', complete_tokens(data), key))
        self.tabs.setCurrentIndex(1)

    def _reserved(self):
        return {p.stem for p in self.ext.window._theme_files()} | SHIPPED

    def lib_duplicate(self):
        kind, key = self._lib_selected()
        if kind != 'profile':
            self.lib_edit()
            return
        name, ok = QInputDialog.getText(self, 'Duplicate', 'Name of the copy', text=self.store.load(key)['name'] + ' copy')
        if ok and name.strip():
            self.store.duplicate(key, name, self._reserved())
            self.refresh_library()

    def lib_rename(self):
        kind, key = self._lib_selected()
        if kind != 'profile':
            QMessageBox.information(self, 'Rename', 'Only Theme Studio profiles can be renamed here.')
            return
        name, ok = QInputDialog.getText(self, 'Rename', 'New name', text=self.store.load(key)['name'])
        if ok and name.strip():
            active = self.runtime.active_slug() == key
            new = self.store.rename(key, name, self._reserved())
            if new != key:
                self.runtime.remove_theme_file(key)
                if active:
                    self.runtime.activate_profile(new)
            self.refresh_library()

    def lib_export(self):
        kind, key = self._lib_selected()
        if kind != 'profile':
            QMessageBox.information(self, 'Export', 'Select a Theme Studio profile (theme files can be shared as '
                                                    'they are, from the themes folder).')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export theme package', f'{key}.spmtheme.zip', 'Theme package (*.zip)')
        if path:
            self.store.export_package(key, Path(path))
            QMessageBox.information(self, 'Export', f'Saved {path}')

    def lib_import(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import theme', '', 'Theme package or theme (*.zip *.json)')
        if not path:
            return
        try:
            slug, notes = self.store.import_package(Path(path), self._reserved())
        except Exception as exc:
            QMessageBox.warning(self, 'Import', f'Not imported (nothing changed):\n\n{exc}')
            return
        self.refresh_library()
        self.refresh_skins()
        QMessageBox.information(self, 'Import', f'Imported “{self.store.load(slug)["name"]}”.' +
                                ('\n' + '\n'.join(notes) if notes else ''))

    def lib_delete(self):
        kind, key = self._lib_selected()
        if kind != 'profile':
            QMessageBox.information(self, 'Delete', 'Shipped themes and theme files are not deleted here.')
            return
        if QMessageBox.question(self, 'Delete', f'Delete the profile “{self.store.load(key)["name"]}”?') != \
                QMessageBox.StandardButton.Yes:
            return
        if self.runtime.active_slug() == key:
            self.runtime.activate_theme('graphite')
        self.store.delete(key)
        self.runtime.remove_theme_file(key)
        if self.slug == key:
            self.open_current()
        self.refresh_library()

    # ================================================================== visual editor
    def _editor_tab(self):
        page = QWidget()
        h = QHBoxLayout(page)
        left = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search a control…')
        self.search.textChanged.connect(self._filter_tree)
        left.addWidget(self.search)
        self.pick_button = QPushButton('◎ Pick from the window')
        self.pick_button.setObjectName('ThemePickButton')
        self.pick_button.setCheckable(True)
        self.pick_button.setToolTip('Click any control in SPM Studio to edit its style. The click does NOT run the '
                                    'control. Esc to stop.')
        self.pick_button.toggled.connect(self._pick_toggled)
        left.addWidget(self.pick_button)
        self.tree = QTreeWidget()
        self.tree.setObjectName('ThemeRoleTree')
        self.tree.setHeaderHidden(True)
        base_item = QTreeWidgetItem(['Global colours & font'])
        base_item.setData(0, Qt.ItemDataRole.UserRole, '__base__')
        self.tree.addTopLevelItem(base_item)
        for category in model.CATEGORIES:
            cat = QTreeWidgetItem([category])
            cat.setFlags(cat.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for role, spec in model.ROLES.items():
                if spec['category'] == category:
                    child = QTreeWidgetItem([spec['label']])
                    child.setData(0, Qt.ItemDataRole.UserRole, role)
                    cat.addChild(child)
            self.tree.addTopLevelItem(cat)
        unsupported = QTreeWidgetItem(['Not editable here'])
        unsupported.setFlags(unsupported.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for name, why in model.NOT_EDITABLE.items():
            child = QTreeWidgetItem([name])
            child.setToolTip(0, why)
            child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            unsupported.addChild(child)
        self.tree.addTopLevelItem(unsupported)
        self.tree.expandAll()
        self.tree.currentItemChanged.connect(self._role_selected)
        left.addWidget(self.tree, 1)
        h.addLayout(left, 2)
        right = QVBoxLayout()
        self.role_title = QLabel()
        self.role_title.setObjectName('heading')
        self.role_title.setWordWrap(True)
        right.addWidget(self.role_title)
        self.role_scope = QLabel()
        self.role_scope.setObjectName('hint')
        self.role_scope.setWordWrap(True)
        right.addWidget(self.role_scope)
        srow = QHBoxLayout()
        srow.addWidget(QLabel('State'))
        self.state_combo = QComboBox()
        self.state_combo.currentIndexChanged.connect(self._state_changed)
        srow.addWidget(self.state_combo, 1)
        right.addLayout(srow)
        self.props_box = QWidget()
        self.props_form = QFormLayout(self.props_box)
        right.addWidget(self.props_box)
        self.base_box = QGroupBox('Global colours & font (the whole app)')
        self.base_form = QFormLayout(self.base_box)
        self.base_fields = {}
        for key, label in BASE_FIELDS:
            field = ColorField(lambda v, k=key: self._set_base(k, v), allow_alpha=False, clearable=False)
            self.base_fields[key] = field
            self.base_form.addRow(label, field)
        self.base_font = QFontComboBox()
        self.base_font.currentFontChanged.connect(lambda f: self._set_base('font_family', f.family()))
        self.base_size = QSpinBox()
        self.base_size.setRange(7, 20)
        self.base_size.valueChanged.connect(lambda v: self._set_base('font_size', float(v)))
        self.base_radius = QSpinBox()
        self.base_radius.setRange(0, 16)
        self.base_radius.valueChanged.connect(lambda v: self._set_base('radius', int(v)))
        self.base_form.addRow('Font', self.base_font)
        self.base_form.addRow('Font size (pt)', self.base_size)
        self.base_form.addRow('Corner radius (px)', self.base_radius)
        right.addWidget(self.base_box)
        right.addStretch(1)
        h.addLayout(right, 3)
        self._select_role('button')
        return page

    def _filter_tree(self, text):
        text = text.lower().strip()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            any_visible = False
            for j in range(top.childCount()):
                child = top.child(j)
                visible = not text or text in child.text(0).lower()
                child.setHidden(not visible)
                any_visible |= visible
            top.setHidden(bool(text) and not any_visible and text not in top.text(0).lower())

    def _select_role(self, role):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.data(0, Qt.ItemDataRole.UserRole) == role:
                self.tree.setCurrentItem(top)
                return
            for j in range(top.childCount()):
                if top.child(j).data(0, Qt.ItemDataRole.UserRole) == role:
                    self.tree.setCurrentItem(top.child(j))
                    return

    def _role_selected(self, item, _prev=None):
        role = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not role:
            return
        self.role = role
        self.state_combo.blockSignals(True)
        self.state_combo.clear()
        if role != '__base__':
            for st in model.ROLES[role]['states']:
                self.state_combo.addItem(st, st)
        self.state_combo.blockSignals(False)
        self.state = self.state_combo.currentData() or 'normal'
        if self.profile is not None:
            self._fill_props()

    def _state_changed(self, *_):
        self.state = self.state_combo.currentData() or 'normal'
        self._fill_props()

    def _clear_form(self):
        while self.props_form.rowCount():
            self.props_form.removeRow(0)

    def _fill_props(self):
        if not hasattr(self, 'props_form') or self.profile is None:
            return
        self._clear_form()
        base = self.role == '__base__'
        self.base_box.setVisible(base)
        self.props_box.setVisible(not base)
        self.state_combo.setVisible(not base)
        if base:
            self.role_title.setText('Global colours & font')
            self.role_scope.setText('Applies to everything; component roles below override it.')
            return
        spec = model.ROLES[self.role]
        self.role_title.setText(spec['label'])
        self.role_scope.setText(f"Changes apply to all “{spec['label'].lower()}” in the state “{self.state}”. "
                                f"Selectors: {', '.join(spec['selectors'])}" + (f" · {spec['note']}" if spec['note'] else ''))
        for prop in model.ALL:
            label, kind = model.PROPS[prop]
            value = model.get_prop(self.profile, self.role, self.state, prop)
            if prop not in spec['props']:
                na = QLabel('not supported for this control')
                na.setObjectName('hint')
                self.props_form.addRow(label, na)
                continue
            setter = (lambda v, p=prop: self.change(lambda pr: model.set_prop(pr, self.role, self.state, p, v)))
            if kind == 'color':
                field = ColorField(setter)
                field.set_value(value, '')
            elif kind.startswith('int:'):
                _, lo, hi = kind.split(':')
                field = QSpinBox()
                field.setRange(int(lo) - 1, int(hi))
                field.setSpecialValueText('inherited')
                field.setValue(value if value is not None else int(lo) - 1)
                field.editingFinished.connect(lambda s=field, f=setter, lo=int(lo):
                                              f(None if s.value() < lo else s.value()))
            elif kind.startswith('choice:'):
                field = QComboBox()
                field.addItem('inherited', None)
                for choice in kind[7:].split(','):
                    field.addItem(choice, choice)
                field.setCurrentIndex(max(0, field.findData(value)))
                field.activated.connect(lambda _i, c=field, f=setter: f(c.currentData()))
            elif kind == 'bool':
                field = QComboBox()
                for text, data in (('inherited', None), ('yes', True), ('no', False)):
                    field.addItem(text, data)
                field.setCurrentIndex({None: 0, True: 1, False: 2}[value])
                field.activated.connect(lambda _i, c=field, f=setter: f(c.currentData()))
            else:                                   # font
                field = QComboBox()
                field.setEditable(True)
                field.addItem('')
                from PySide6.QtGui import QFontDatabase
                field.addItems(sorted(QFontDatabase.families())[:600])
                field.setCurrentText(value or '')
                field.lineEdit().setPlaceholderText('inherited')
                field.lineEdit().editingFinished.connect(lambda c=field, f=setter: f(c.currentText().strip() or None))
            self.props_form.addRow(label, field)

    def _fill_base(self):
        if self.profile is None:
            return
        tokens = self.tokens()
        for key, field in self.base_fields.items():
            field.set_value(self.profile['base'].get(key) or tokens.get(key), tokens.get(key))
        for widget, value in ((self.base_size, int(tokens['font_size'])), (self.base_radius, int(tokens['radius']))):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.base_font.blockSignals(True)
        if tokens.get('font_family'):
            self.base_font.setCurrentText(tokens['font_family'])
        self.base_font.blockSignals(False)

    def _set_base(self, key, value):
        if value is None or self.profile is None:
            return
        if self.profile['base'].get(key) == value:
            return

        def mutate(p):
            p['base'][key] = value
            model.validate_profile(p)
        self.change(mutate)

    def _pick_toggled(self, on):
        if on:
            self.picker.start()
            self.statusBar().showMessage('Pick mode: click a control in SPM Studio (it will not run). Esc to stop.')
        else:
            self.picker.stop()
            self.statusBar().clearMessage()

    def _picked(self, role, _widget):
        self.tabs.setCurrentIndex(1)
        self._select_role(role)
        self.statusBar().showMessage(f'Picked: {model.ROLES[role]["label"]}. Click another control, or Esc to stop.')

    # ================================================================== SVG skins
    def _skins_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        rule = QLabel('⚠ <b>Exact names required.</b> To import an edited package, keep every required file at the '
                      'exact path and name it was exported with (e.g. <code>svg/button.primary/hover.svg</code>, '
                      'case-sensitive). Missing or renamed files → nothing is imported, you get the list.')
        rule.setWordWrap(True)
        rule.setObjectName('ThemeSkinNamingRule')
        rule.setStyleSheet('border: 2px solid #E8B54D; border-radius: 6px; padding: 8px;')
        v.addWidget(rule)
        row = QHBoxLayout()
        export = QPushButton('Export SVG customization template…')
        export.setObjectName('ThemeExportTemplate')
        export.clicked.connect(self.export_template)
        imp = QPushButton('Import SVG personalization package…')
        imp.setObjectName('ThemeImportSkin')
        imp.clicked.connect(lambda: self.import_skin(folder=False))
        imp_dir = QPushButton('Import folder…')
        imp_dir.clicked.connect(lambda: self.import_skin(folder=True))
        demo = QPushButton('Install demo skin')
        demo.clicked.connect(self.install_demo)
        for w in (export, imp, imp_dir, demo):
            row.addWidget(w)
        row.addStretch(1)
        v.addLayout(row)
        self.skin_list = QListWidget()
        self.skin_list.setObjectName('ThemeSkinList')
        v.addWidget(self.skin_list, 1)
        row = QHBoxLayout()
        use = QPushButton('Use in this profile')
        use.clicked.connect(self.use_skin)
        none = QPushButton('No skin')
        none.clicked.connect(lambda: self.change(lambda p: p.update(skin='')))
        exp = QPushButton('Export skin…')
        exp.clicked.connect(self.export_skin)
        delete = QPushButton('Delete skin')
        delete.clicked.connect(self.delete_skin)
        for w in (use, none, exp, delete):
            row.addWidget(w)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(QLabel('Validation report'))
        self.report = QPlainTextEdit()
        self.report.setObjectName('ThemeSkinReport')
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(150)
        v.addWidget(self.report)
        info = QLabel('SVGs replace the background and border of: buttons (normal, hover, pressed, disabled, focus), '
                      'primary buttons, inputs, panels, logs, progress bars (track and fill), tabs and menus. Text, '
                      'click areas, keyboard focus and data stay those of the real controls. Not skinnable: '
                      + '; '.join(svgskin.UNSUPPORTED) + '.')
        info.setObjectName('hint')
        info.setWordWrap(True)
        v.addWidget(info)
        return page

    def refresh_skins(self):
        self.skin_list.clear()
        for slug, manifest in svgskin.installed_skins(self.store.skins_dir).items():
            used = '  ✓ used by this profile' if self.profile and self.profile.get('skin') == slug else ''
            item = QListWidgetItem(f"{manifest['name']}  ({slug}){used}")
            item.setData(Qt.ItemDataRole.UserRole, slug)
            self.skin_list.addItem(item)

    def _contact_sheet(self) -> bytes:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        image = self.gallery.grab().toImage()
        buf = QByteArray()
        device = QBuffer(buf)
        device.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(device, 'PNG')
        return bytes(buf.data())

    def export_template(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export SVG customization template',
                                              f"{model.slug(self.profile['name'])}_svg_template.zip", 'Zip (*.zip)')
        if not path:
            return
        svgs, insets = None, None
        if self.profile.get('skin'):                 # an installed skin is exported as it is (edit it further)
            folder = self.store.skins_dir / self.profile['skin']
            svgs = svgskin.skin_files(folder)
            manifest = svgskin.installed_skins(self.store.skins_dir).get(self.profile['skin'], {})
            insets = {r: s['insets'] for r, s in manifest.get('roles', {}).items()}
        svgskin.export_template(Path(path), self.profile['name'], self.profile, self.tokens(), self._contact_sheet(),
                                svgs, insets)
        self.report.setPlainText(f'Template written: {path}\nRequired files: {len(svgskin.required_files())}, '
                                 f'optional: {len(svgskin.optional_files())}. Read README.md inside before editing.')

    def import_skin(self, folder=False):
        if folder:
            path = QFileDialog.getExistingDirectory(self, 'Import SVG personalization folder')
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Import SVG personalization package', '', 'Zip (*.zip)')
        if not path:
            return
        self.import_skin_path(Path(path))

    def import_skin_path(self, path: Path) -> bool:
        try:
            manifest, svgs = svgskin.validate_package(path)
            problems = render_check(svgs)
            if problems:
                raise svgskin.SkinError(problems)
        except svgskin.SkinError as exc:
            self.report.setPlainText('Not imported — nothing changed:\n\n' + '\n'.join('• ' + p for p in exc.problems))
            return False
        folder = svgskin.install(manifest, svgs, self.store.skins_dir)
        self.change(lambda p: p.update(skin=folder.name))
        self.refresh_skins()
        self.report.setPlainText(f"Imported “{manifest['name']}” ({len(svgs)} SVG files). It is shown in the preview; "
                                 'Apply or Save to keep it.')
        return True

    def install_demo(self):
        tmp = self.store.root / '.demo.zip'
        try:
            svgskin.demo_package(tmp, self.tokens())
            self.import_skin_path(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def _skin_selected(self):
        item = self.skin_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ''

    def use_skin(self):
        slug = self._skin_selected()
        if slug:
            self.change(lambda p: p.update(skin=slug))
            self.refresh_skins()

    def export_skin(self):
        slug = self._skin_selected()
        if not slug:
            return
        manifest = svgskin.installed_skins(self.store.skins_dir)[slug]
        path, _ = QFileDialog.getSaveFileName(self, 'Export SVG skin', f'{slug}.zip', 'Zip (*.zip)')
        if path:
            svgskin.export_template(Path(path), manifest['name'], self.profile, self.tokens(), None,
                                    svgskin.skin_files(self.store.skins_dir / slug),
                                    {r: s['insets'] for r, s in manifest['roles'].items()})

    def delete_skin(self):
        slug = self._skin_selected()
        if not slug:
            return
        users = [p['name'] for p in self.store.list().values() if p['skin'] == slug]
        if QMessageBox.question(self, 'Delete skin', 'Delete this skin?' + (f'\nUsed by: {", ".join(users)}' if users
                                                                            else '')) != QMessageBox.StandardButton.Yes:
            return
        import shutil
        shutil.rmtree(self.store.skins_dir / slug, ignore_errors=True)
        for s, p in self.store.list().items():
            if p['skin'] == slug:
                p['skin'] = ''
                self.store.save(p, s)
        if self.profile.get('skin') == slug:
            self.change(lambda p: p.update(skin=''))
        self.refresh_skins()
        self.runtime.reapply()

    # ================================================================== save / apply / cancel
    def _live_toggled(self, on):
        if on:
            self.runtime.start_preview(self.profile)
        else:
            self.runtime.cancel_preview()

    def reset_to_saved(self):
        if self.saved is not None:
            self.change(lambda p: (p.clear(), p.update(model.snapshot(self.saved))))

    def restore_defaults(self):
        self.change(lambda p: p.update(roles={}, skin=''))

    def save(self) -> bool:
        if not self.slug:
            return self.save_as()
        self.store.save(self.profile, self.slug)
        self.saved = model.snapshot(self.profile)
        self.runtime.write_theme_file(self.slug, self.profile)
        if self.runtime.active_slug() == self.slug and not self.live.isChecked():
            self.runtime.reapply()
        self.update_all()
        self.refresh_library()
        return True

    def save_as(self) -> bool:
        name, ok = QInputDialog.getText(self, 'Save As', 'Name of the new theme', text=self.profile['name'])
        if not ok or not name.strip():
            return False
        slug = self.store.unique_slug(name, self._reserved())     # never a shipped theme, never overwrites
        self.profile['name'] = model.clean_name(name)
        self.store.save(self.profile, slug, overwrite=False)
        self.slug = slug
        self.saved = model.snapshot(self.profile)
        self.runtime.write_theme_file(slug, self.profile)
        self.update_all()
        self.refresh_library()
        return True

    def apply(self):
        """Save (if needed) and make this profile the active theme of SPM Studio."""
        if self.dirty() and not self.save():
            return
        self.live.blockSignals(True)
        self.live.setChecked(False)
        self.live.blockSignals(False)
        self.runtime.preview_profile = None
        self.runtime.activate_profile(self.slug)
        self.refresh_library()

    def cancel(self):
        self.close()

    def closeEvent(self, event):
        if self.picker.active:
            self.picker.stop()
        if self.dirty() and self.undo_stack:
            answer = QMessageBox.question(self, 'Unsaved changes', 'Close Theme Studio without saving the changes?')
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.runtime.cancel_preview()
        super().closeEvent(event)
