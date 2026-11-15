"""Full file-metadata inspector in the left Files / Tools / Metadata tab bar."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
    QPlainTextEdit, QLineEdit, QPushButton, QLabel)
from ..core.metadata_display import metadata_text, metadata_json, original_header


class MetadataPanel(QWidget):
    """Show scan acquisition parameters, the exact SXM header and reader JSON.

    All views scroll and support text selection, searching, and copying without
    mutating the scan or loading image arrays. The parent controls scan lifetime.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scan = None
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 8, 6, 6)
        root.setSpacing(6)
        self.heading = QLabel('No scan selected')
        self.heading.setWordWrap(True)
        self.heading.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.heading)

        self.view_mode = QComboBox()
        self.view_mode.addItem('All parameters', 'parameters')
        self.view_mode.addItem('Original SXM header', 'raw')
        self.view_mode.addItem('Reader metadata (JSON)', 'json')
        self.view_mode.setToolTip('Choose the readable view, exact original SXM header, or full reader metadata as JSON')
        root.addWidget(self.view_mode)

        self.search = QLineEdit()
        self.search.setPlaceholderText('Find parameter or value…')
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip('Find text in the current metadata view; Enter finds the next match')
        root.addWidget(self.search)
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        self.previous = QPushButton('Previous')
        self.next = QPushButton('Next')
        self.copy_all = QPushButton('Copy all')
        self.previous.setToolTip('Jump to the previous matching parameter')
        self.next.setToolTip('Jump to the next matching parameter')
        self.copy_all.setToolTip('Copy the entire current metadata view to the clipboard')
        nav.addWidget(self.previous)
        nav.addWidget(self.next)
        nav.addWidget(self.copy_all)
        root.addLayout(nav)

        self.document = QPlainTextEdit()
        self.document.setObjectName('ScanMetadataDocument')
        self.document.setReadOnly(True)
        self.document.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.document.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.document.setPlaceholderText('Open an SXM or GWY scan to inspect the acquisition parameters.')
        root.addWidget(self.document, 1)
        self.status = QLabel('Select a scan in Files to view its metadata.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.view_mode.currentIndexChanged.connect(self._update_view)
        self.search.textChanged.connect(self._search_changed)
        self.search.returnPressed.connect(self.find_next)
        self.previous.clicked.connect(self.find_previous)
        self.next.clicked.connect(self.find_next)
        self.copy_all.clicked.connect(self._copy_all)
        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled):
        self.view_mode.setEnabled(enabled)
        self.search.setEnabled(enabled)
        self.previous.setEnabled(enabled and bool(self.search.text()))
        self.next.setEnabled(enabled and bool(self.search.text()))
        self.copy_all.setEnabled(enabled)

    def clear(self):
        self._scan = None
        self.heading.setText('No scan selected')
        self.document.clear()
        self.search.clear()
        self.status.setText('Select a scan in Files to view its metadata.')
        self._set_controls_enabled(False)

    def set_loading(self, path):
        from pathlib import Path
        self._scan = None
        self.heading.setText(Path(path).name)
        self.document.setPlainText('Loading scan metadata…')
        self.status.setText('Reading file header…')
        self._set_controls_enabled(False)

    def set_error(self, message):
        self._scan = None
        self.document.setPlainText('Could not load metadata:\n' + str(message))
        self.status.setText('Could not read selected file')
        self._set_controls_enabled(False)

    def set_scan(self, scan):
        self._scan = scan
        self.heading.setText(scan.path.name)
        self.heading.setToolTip(str(scan.path))
        self._set_controls_enabled(True)
        self._update_view()

    def _update_view(self, *_args):
        if self._scan is None:
            return
        kind = self.view_mode.currentData()
        if kind == 'raw':
            content = original_header(self._scan)
        elif kind == 'json':
            content = metadata_json(self._scan)
        else:
            content = metadata_text(self._scan)
        self.document.setPlainText(content)
        self.document.moveCursor(QTextCursor.MoveOperation.Start)
        self.status.setText(f'{self.document.document().blockCount():,} lines • source file is read-only')
        if self.search.text():
            self._search_changed(self.search.text())

    def _search_changed(self, value):
        self.previous.setEnabled(self._scan is not None and bool(value))
        self.next.setEnabled(self._scan is not None and bool(value))
        if value and self._scan is not None:
            self.document.moveCursor(QTextCursor.MoveOperation.Start)
            self.find_next()
        elif self._scan is not None:
            self.status.setText(f'{self.document.document().blockCount():,} lines • source file is read-only')

    def find_next(self):
        self._find(backwards=False)

    def find_previous(self):
        self._find(backwards=True)

    def _find(self, *, backwards):
        term = self.search.text()
        if self._scan is None or not term:
            return
        flags = QTextDocument.FindFlag.FindBackward if backwards else QTextDocument.FindFlag(0)
        if not self.document.find(term, flags):
            self.document.moveCursor(QTextCursor.MoveOperation.End if backwards else QTextCursor.MoveOperation.Start)
            if not self.document.find(term, flags):
                self.status.setText(f'No match for “{term}”')
                return
        self.status.setText(f'Match: {term}')

    def _copy_all(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.document.toPlainText())
        self.status.setText('All displayed metadata copied to clipboard')
