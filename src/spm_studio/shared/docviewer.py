"""Read Markdown / text documents (READMEs, guides) inside the app, in the app's own design (v0.0.18).

One viewer for every README: a header with the title and the file, an optional outline of the headings, a
readable column of text styled from the current theme tokens (headings, code blocks, tables, quotes, links),
find-in-page, *Open folder* and *Close*.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut, QTextDocument
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

HEADING = re.compile(r'^(#{1,3})\s+(.+?)\s*#*\s*$')


def document_css(tokens: dict) -> str:
    """CSS (Qt rich-text subset) for documents, from the theme tokens."""
    t = tokens
    return f'''
body {{ color: {t['foreground']}; line-height: 150%; }}
h1 {{ font-size: 22px; font-weight: 700; margin: 4px 0 10px 0; }}
h2 {{ font-size: 17px; font-weight: 650; margin: 22px 0 8px 0; }}
h3 {{ font-size: 14px; font-weight: 650; margin: 16px 0 6px 0; }}
h4, h5, h6 {{ font-size: 13px; font-weight: 600; margin: 12px 0 4px 0; color: {t['muted']}; }}
p, li {{ margin: 4px 0; }}
a {{ color: {t['accent']}; text-decoration: none; }}
code {{ font-family: "JetBrains Mono", "DejaVu Sans Mono", "Consolas", monospace; background: {t['hover']};
        color: {t['foreground']}; }}
pre {{ font-family: "JetBrains Mono", "DejaVu Sans Mono", "Consolas", monospace; background: {t['surface']};
       color: {t['foreground']}; padding: 10px; margin: 8px 0; }}
blockquote {{ color: {t['muted']}; margin: 6px 0 6px 12px; }}
table {{ border-collapse: collapse; margin: 8px 0; }}
th {{ background: {t['surface']}; color: {t['muted']}; font-weight: 600; padding: 5px 10px; text-align: left; }}
td {{ padding: 5px 10px; border-bottom: 1px solid {t['border']}; }}
hr {{ color: {t['border']}; }}
'''


def outline(text: str) -> list[tuple[int, str]]:
    """(level, title) of the Markdown headings outside code blocks."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.strip().startswith('```'):
            fenced = not fenced
            continue
        m = None if fenced else HEADING.match(line)
        if m:
            title = re.sub(r'[`*_]', '', m.group(2)).strip()
            out.append((len(m.group(1)), title))
    return out


class DocViewer(QDialog):
    """A Markdown (or plain text) document in the app's design."""

    def __init__(self, path, title: str = '', parent=None, *, text: str | None = None):
        super().__init__(parent)
        self.setObjectName('DocViewerV0018')
        self.path = Path(path) if path else None
        self.setWindowTitle(title or (self.path.name if self.path else 'Document'))
        self.resize(980, 760)
        self.setMinimumSize(560, 420)
        if text is None:
            try:
                text = self.path.read_text(encoding='utf-8', errors='replace')
            except (OSError, AttributeError) as exc:
                text = f'Could not read {self.path}: {exc}'
        self.text = text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # header: title, file, find
        header = QFrame()
        header.setObjectName('docHeader')
        row = QHBoxLayout(header)
        row.setContentsMargins(20, 12, 16, 12)
        names = QVBoxLayout()
        names.setSpacing(0)
        heading = QLabel(title or (self.path.name if self.path else 'Document'))
        heading.setObjectName('docTitle')
        names.addWidget(heading)
        if self.path is not None:
            where = QLabel(self.path.name)
            where.setObjectName('docKind')
            where.setToolTip(str(self.path))
            names.addWidget(where)
        row.addLayout(names, 1)
        self.find = QLineEdit()
        self.find.setPlaceholderText('Find')
        self.find.setClearButtonEnabled(True)
        self.find.setMaximumWidth(220)
        self.find.returnPressed.connect(lambda: self.find_text(self.find.text()))
        row.addWidget(self.find)
        layout.addWidget(header)
        # body: outline + text
        self.view = QTextBrowser()
        self.view.setObjectName('docBody')
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._open_link)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.document().setDocumentMargin(28)
        self.outline = QListWidget()
        self.outline.setObjectName('docOutline')
        self.outline.itemClicked.connect(self._go_to)
        heads = outline(text) if self._is_markdown() else []
        for level, name in heads:
            item = QListWidgetItem(('    ' * (level - 1)) + name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            if level == 1:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.outline.addItem(item)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.outline)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 680])
        self.outline.setVisible(len(heads) >= 4)
        layout.addWidget(split, 1)
        # footer
        footer = QWidget()
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(16, 10, 16, 12)
        foot.addStretch(1)
        if self.path is not None:
            folder = QPushButton('Open folder')
            folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent))))
            foot.addWidget(folder)
        close = QPushButton('Close')
        close.setProperty('primary', True)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        layout.addWidget(footer)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=lambda: (self.find.setFocus(), self.find.selectAll()))
        self.render()

    def _is_markdown(self) -> bool:
        return self.path is None or self.path.suffix.lower() in ('.md', '.markdown', '')

    def render(self):
        from spm_studio.shared.appearance import colors
        doc = self.view.document()
        doc.setDefaultStyleSheet(document_css(colors()))
        if self._is_markdown():
            tmp = QTextDocument()
            tmp.setMarkdown(self.text)
            body = tmp.toHtml()
            self.view.setHtml(body)
        else:
            self.view.setHtml('<pre>' + html.escape(self.text) + '</pre>')
        # v0.0.19: the text follows the window width (no fixed narrow column); very wide windows keep a
        # readable line length by centring the column with side margins.
        self.view.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        self._fit_column()

    READABLE = 820                          # px: longest comfortable line

    def _fit_column(self):
        width = self.view.width()
        side = max(0, (width - self.READABLE) // 2)
        self.view.setViewportMargins(side, 0, side, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_column()

    def showEvent(self, event):
        super().showEvent(event)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._fit_column)

    def find_text(self, needle: str) -> bool:
        if not needle:
            return False
        if self.view.find(needle):
            return True
        cursor = self.view.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.view.setTextCursor(cursor)
        return self.view.find(needle)

    def _go_to(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        cursor = self.view.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self.view.setTextCursor(cursor)
        if self.view.find(name):
            self.view.ensureCursorVisible()

    def _open_link(self, url: QUrl):
        if url.isRelative() and self.path is not None and url.path():
            target = (self.path.parent / url.path()).resolve()
            if target.is_file() and target.suffix.lower() in ('.md', '.markdown', '.txt'):
                DocViewer(target, target.name, self).exec()
                return
            url = QUrl.fromLocalFile(str(target))
        if url.scheme() in ('http', 'https', 'mailto', 'file'):
            QDesktopServices.openUrl(url)
        elif url.hasFragment():
            self.view.scrollToAnchor(url.fragment())
