"""Choose where the listed scans are copied (v0.0.5): any location, any folder name."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
                               QPushButton, QFileDialog, QDialogButtonBox)

INVALID = '<>:"/\\|?*'


def clean_folder_name(name: str) -> str:
    """A folder name that is valid on Linux, Windows and macOS ('' if nothing usable is left)."""
    cleaned = ''.join('_' if (c in INVALID or ord(c) < 32) else c for c in str(name)).strip().strip('.')
    return cleaned[:120]


class RecapFolderDialog(QDialog):
    """Location + folder name, with the resulting path shown before anything is copied."""

    def __init__(self, default_folder, count: int, parent=None):
        super().__init__(parent)
        default_folder = Path(default_folder)
        self.setWindowTitle('Copy listed scans to a folder')
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        intro = QLabel(f'Copy the {count} listed scan' + ('s' if count != 1 else '') +
                       ' into a folder and continue working there. The original files are not changed.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        row = QHBoxLayout()
        self.location = QLineEdit(str(default_folder.parent))
        self.location.setObjectName('RecapLocationV005')
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        row.addWidget(self.location, 1)
        row.addWidget(browse)
        form.addRow('Location', row)
        self.name = QLineEdit(default_folder.name)
        self.name.setObjectName('RecapNameV005')
        self.name.setPlaceholderText('Name of the folder (created if it does not exist)')
        form.addRow('Folder name', self.name)
        layout.addLayout(form)
        self.preview = QLabel('')
        self.preview.setObjectName('hint')
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText('Copy scans')
        self.ok.setProperty('primary', True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.location.textChanged.connect(self._update)
        self.name.textChanged.connect(self._update)
        self._update()

    def _browse(self):
        start = self.location.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, 'Choose where the folder is created', start)
        if chosen:
            self.location.setText(chosen)

    def folder(self):
        """The chosen folder, or ``None`` while the entry is not usable."""
        location = self.location.text().strip()
        name = clean_folder_name(self.name.text())
        if not location or not name:
            return None
        return Path(location).expanduser() / name

    def _update(self, *_):
        target = self.folder()
        if target is None:
            self.preview.setText('Enter a location and a folder name.')
            self.ok.setEnabled(False)
            return
        if not target.parent.is_dir():
            self.preview.setText(f'The location does not exist: {target.parent}')
            self.ok.setEnabled(False)
            return
        note = 'This folder exists: the scans are added to it (files with the same name are replaced).' \
            if target.exists() else 'This folder will be created.'
        self.preview.setText(f'{target}\n{note}')
        self.ok.setEnabled(True)
