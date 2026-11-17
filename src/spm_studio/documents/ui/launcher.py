"""Start screen of the editors: new from a template, open, import, recent projects."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QLineEdit,
                               QPushButton, QFileDialog, QFrame, QComboBox, QFormLayout)

from spm_studio.documents import settings as doc_settings, templates, latex_project, deck as deck_model
from spm_studio.shared.dialogs import MessageDialog


class Launcher(QDialog):
    def __init__(self, kind: str, hub, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.hub = hub
        self.result_path = None
        self.conf = doc_settings.load()
        latex = kind == 'latex'
        self.setWindowTitle('LaTeX editor' if latex else 'Presentation editor')
        self.setObjectName('DocumentLauncherV008')
        self.resize(900, 600)
        root = QHBoxLayout(self)
        root.setSpacing(16)
        # ---------------------------------------------------------- new
        new = QFrame()
        new.setObjectName('launcherCard')
        nl = QVBoxLayout(new)
        nl.setContentsMargins(16, 14, 16, 16)
        nl.setSpacing(8)
        title = QLabel('New project' if latex else 'New presentation')
        title.setObjectName('launcherTitle')
        nl.addWidget(title)
        hint = QLabel('Choose a template. Add your own in Settings › Library › ' +
                      ('LaTeX templates' if latex else 'Presentation templates') + '.')
        hint.setObjectName('hint')
        hint.setWordWrap(True)
        nl.addWidget(hint)
        self.templates = QListWidget()
        self.templates.setObjectName('LauncherTemplatesV008')
        self.templates.setIconSize(QSize(20, 20))
        default = self.conf.get('latex_default_template' if latex else 'slides_default_template', '')
        if latex:
            blank = QListWidgetItem('Blank article\n    Minimal document, nothing else')
            blank.setData(Qt.ItemDataRole.UserRole, None)
            self.templates.addItem(blank)
        for t in templates.list_templates('latex' if latex else 'slides'):
            item = QListWidgetItem(f'{t.label}\n    {t.description}' if t.description else t.label)
            item.setData(Qt.ItemDataRole.UserRole, str(t.path))
            item.setToolTip(str(t.path))
            self.templates.addItem(item)
            if t.name == default or Path(t.name).stem == default:
                self.templates.setCurrentItem(item)
        if self.templates.currentRow() < 0:
            self.templates.setCurrentRow(0)
        self.templates.itemDoubleClicked.connect(lambda _i: self._create())
        nl.addWidget(self.templates, 1)
        form = QFormLayout()
        self.name = QLineEdit('Untitled' if latex else 'Presentation')
        self.name.selectAll()
        form.addRow('Name', self.name)
        where = QHBoxLayout()
        root_dir = doc_settings.latex_root(self.conf) if latex else doc_settings.slides_root(self.conf)
        self.location = QLineEdit(str(root_dir))
        change = QPushButton('Change…')
        change.clicked.connect(self._change_location)
        where.addWidget(self.location, 1)
        where.addWidget(change)
        form.addRow('Save in', where)
        if not latex:
            self.size_combo = QComboBox()
            for key in doc_settings.SLIDE_SIZES:
                self.size_combo.addItem(key, key)
            self.size_combo.setCurrentIndex(self.size_combo.findData(self.conf.get('slides_size', '16:9')))
            form.addRow('Slide size', self.size_combo)
        nl.addLayout(form)
        folder_hint = QLabel('A folder with the project name is created there. The default place is set in '
                             'Settings › Documents.')
        folder_hint.setObjectName('hint')
        folder_hint.setWordWrap(True)
        nl.addWidget(folder_hint)
        create = QPushButton('Create')
        create.setProperty('primary', True)
        create.setDefault(True)
        create.clicked.connect(self._create)
        nl.addWidget(create, 0, Qt.AlignmentFlag.AlignRight)
        root.addWidget(new, 3)
        # ---------------------------------------------------------- open / import / recent
        side = QVBoxLayout()
        side.setSpacing(10)
        card = QFrame()
        card.setObjectName('launcherCard')
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 16)
        cl.setSpacing(6)
        t = QLabel('Open or import')
        t.setObjectName('launcherTitle')
        cl.addWidget(t)
        for text, slot in ((('Open a project folder…' if latex else 'Open a presentation…'), self._open),
                           (('Import a .zip (Overleaf “Download source”)…' if latex else
                             'Import a .zip (SPM Studio presentation)…'), self._import_zip)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            cl.addWidget(b)
        if latex:
            b = QPushButton('Import from Overleaf…')
            b.clicked.connect(self._from_overleaf)
            cl.addWidget(b)
            b = QPushButton('Import a LaTeX folder (copy)…')
            b.clicked.connect(self._import_folder)
            cl.addWidget(b)
        else:
            b = QPushButton('Import a PowerPoint file (.pptx)…')
            b.clicked.connect(self._import_pptx)
            cl.addWidget(b)
        side.addWidget(card)
        card = QFrame()
        card.setObjectName('launcherCard')
        rl = QVBoxLayout(card)
        rl.setContentsMargins(16, 14, 16, 16)
        t = QLabel('Recent')
        t.setObjectName('launcherTitle')
        rl.addWidget(t)
        self.recent = QListWidget()
        for path in doc_settings.recent(kind):
            label = path.name if latex else path.parent.name
            item = QListWidgetItem(f'{label}\n    {path.parent if latex else path.parent.parent}')
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.recent.addItem(item)
        if not self.recent.count():
            self.recent.addItem('Nothing yet')
            self.recent.setEnabled(False)
        self.recent.itemDoubleClicked.connect(self._open_recent)
        rl.addWidget(self.recent, 1)
        side.addWidget(card, 1)
        root.addLayout(side, 2)

    def _change_location(self):
        folder = QFileDialog.getExistingDirectory(self, 'Where to create the project', self.location.text())
        if folder:
            self.location.setText(folder)

    def _create(self):
        item = self.templates.currentItem()
        name = self.name.text().strip() or 'Untitled'
        root = Path(self.location.text().strip() or '.').expanduser()
        template = item.data(Qt.ItemDataRole.UserRole) if item else None
        try:
            if self.kind == 'latex':
                author = self.conf.get('author', '')
                self.result_path = latex_project.create_project(root, name, Path(template) if template else None,
                                                                author=author)
                doc_settings.update(latex_default_template=Path(template).name if template else 'Article')
            else:
                data = templates.load_slides_template(template) if template else None
                self.result_path = deck_model.create_project(root, name, size=self.size_combo.currentData(), template=data)
                doc_settings.update(slides_default_template=Path(template).stem if template else '',
                                    slides_size=self.size_combo.currentData())
        except (OSError, ValueError) as exc:
            MessageDialog.warning(self, 'Create', str(exc))
            return
        self.accept()

    def _open(self):
        if self.kind == 'latex':
            folder = QFileDialog.getExistingDirectory(self, 'Open LaTeX project folder', self.location.text())
            if folder:
                if not latex_project.is_project(folder):
                    MessageDialog.warning(self, 'Open', 'This folder has no .tex file with \\documentclass.')
                    return
                self.result_path = Path(folder)
                self.accept()
        else:
            file, _ = QFileDialog.getOpenFileName(self, 'Open presentation', self.location.text(),
                                                  f'Presentations (*{deck_model.SUFFIX})')
            if file:
                self.result_path = Path(file)
                self.accept()

    def _import_zip(self):
        archive, _ = QFileDialog.getOpenFileName(self, 'Import', str(Path.home()), 'Zip archives (*.zip)')
        if not archive:
            return
        try:
            self.result_path = (latex_project.import_zip(archive, self.location.text()) if self.kind == 'latex'
                                else deck_model.import_zip(archive, self.location.text()))
        except (ValueError, OSError) as exc:
            MessageDialog.warning(self, 'Import', str(exc))
            return
        self.accept()

    def _import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'LaTeX folder to copy', str(Path.home()))
        if not folder:
            return
        try:
            self.result_path = latex_project.import_folder(folder, self.location.text())
        except (ValueError, OSError) as exc:
            MessageDialog.warning(self, 'Import', str(exc))
            return
        self.accept()

    def _import_pptx(self):
        file, _ = QFileDialog.getOpenFileName(self, 'Import PowerPoint', str(Path.home()), 'PowerPoint (*.pptx)')
        if not file:
            return
        from .pptx_io import import_pptx
        try:
            self.result_path = import_pptx(file, self.location.text())
        except Exception as exc:
            MessageDialog.warning(self, 'Import PowerPoint', str(exc))
            return
        self.accept()

    def _from_overleaf(self):
        self.reject()
        self.hub.import_from_overleaf(self.parent())

    def _open_recent(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.result_path = Path(path)
            self.accept()
