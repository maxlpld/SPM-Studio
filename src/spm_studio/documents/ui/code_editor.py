"""LaTeX source editor: line numbers, syntax colours, completion, brackets, comments, find/replace."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QRect, QSize, Signal, QStringListModel, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QPainter, QSyntaxHighlighter, QTextCharFormat,
                           QTextCursor, QTextFormat, QKeySequence, QTextDocument, QShortcut)
from PySide6.QtWidgets import (QPlainTextEdit, QWidget, QTextEdit, QCompleter, QFrame, QHBoxLayout, QLineEdit,
                               QCheckBox, QLabel, QToolButton, QPlainTextDocumentLayout)


def _theme():
    try:
        from spm_studio.shared.appearance import colors, is_dark
        t = colors()
        return t, is_dark(t)
    except Exception:
        return {'foreground': '#1A1D22', 'muted': '#5E6672', 'subtle': '#8A929E', 'accent': '#0F7C6F',
                'surface': '#FFFFFF', 'input': '#FFFFFF', 'hover': '#EEF0F2', 'danger': '#C23A33',
                'warning': '#B7791F', 'border': '#D8DCE1'}, False


class LatexHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        t, dark = _theme()
        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QBrush(QColor(color)))
            if bold:
                f.setFontWeight(int(QFont.Weight.DemiBold.value))
            if italic:
                f.setFontItalic(True)
            return f
        self.f_command = fmt('#7FB8FF' if dark else '#1F5FA8')
        self.f_env = fmt('#E5A6FF' if dark else '#8A3FB0', bold=True)
        self.f_section = fmt(t['accent'], bold=True)
        self.f_math = fmt('#F2C46D' if dark else '#9A5B00')
        self.f_comment = fmt(t['subtle'] if dark else '#7A8290', italic=True)
        self.f_brace = fmt(t['muted'])
        self.f_arg = fmt('#9FE0B8' if dark else '#1E7B47')
        # (pattern, format, group): only the group is coloured (0 = the whole match)
        self.rules = [
            (re.compile(r'\\(?:begin|end)\{[^}]*\}'), self.f_env, 0),
            (re.compile(r'\\(?:part|chapter|section|subsection|subsubsection|paragraph|frametitle|title)\*?(?=[\[{])'),
             self.f_section, 0),
            (re.compile(r'\\(?:[A-Za-z@]+\*?|.)'), self.f_command, 0),
            (re.compile(r'[{}\[\]]'), self.f_brace, 0),
            (re.compile(r'\\(?:cite[a-zA-Z]*|ref|label|eqref|include|input|usepackage|includegraphics|documentclass)'
                        r'\*?(?:\[[^\]]*\])?(\{[^}]*\})'), self.f_arg, 1),
        ]
        self.math = re.compile(r'\$\$.*?\$\$|(?<!\\)\$.*?(?<!\\)\$|\\\(.*?\\\)|\\\[.*?\\\]')
        self.comment = re.compile(r'(?<!\\)%.*$')

    def highlightBlock(self, text):
        for pattern, fmt, group in self.rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(group), m.end(group) - m.start(group), fmt)
        # display math spanning lines: state 1 = inside \[ … \] or $$ … $$
        start = 0
        if self.previousBlockState() == 1:
            end = min([i for i in (text.find('\\]'), text.find('$$')) if i >= 0], default=-1)
            if end < 0:
                self.setFormat(0, len(text), self.f_math)
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 2, self.f_math)
            start = end + 2
        self.setCurrentBlockState(0)
        for m in self.math.finditer(text, start):
            self.setFormat(m.start(), m.end() - m.start(), self.f_math)
        rest = self.math.sub(lambda m: ' ' * len(m.group(0)), text[start:])
        opened = max(rest.rfind('\\['), rest.rfind('$$'))
        if opened >= 0 and rest.find('\\]', opened) < 0 and rest.find('$$', opened + 2) < 0:
            self.setFormat(start + opened, len(text) - start - opened, self.f_math)
            self.setCurrentBlockState(1)
        m = self.comment.search(text)
        if m:
            self.setFormat(m.start(), len(text) - m.start(), self.f_comment)


class _Gutter(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.setObjectName('lineGutter')
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_gutter(event)


PAIRS = {'{': '}', '[': ']', '(': ')', '$': '$'}


class CodeEditor(QPlainTextEdit):
    """``QPlainTextEdit`` for LaTeX. One editor shows the document of the selected tab."""
    cursorMoved = Signal(int, int)          # line, column (1-based)
    askAssistant = Signal(str)              # selected text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('latexCode')
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for family in ('JetBrains Mono', 'Fira Code', 'Source Code Pro', 'DejaVu Sans Mono', 'Menlo', 'Consolas'):
            if family in QFontDatabase.families():
                font = QFont(family)
                break
        font.setPointSize(11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 2)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.error_lines: dict[int, str] = {}
        self.warning_lines: dict[int, str] = {}
        self.gutter = _Gutter(self)
        self.blockCountChanged.connect(lambda _n: self._update_margins())
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._cursor_changed)
        self._update_margins()
        self.words = []
        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self.completer.setMaxVisibleItems(12)
        self.completer.activated[str].connect(self._insert_completion)
        self._completion_kind = 'command'
        self._model = QStringListModel(self)
        self.completer.setModel(self._model)
        self.provider = None      # callable(kind) -> list[str]  (commands, labels, citations, files)
        QShortcut(QKeySequence('Ctrl+/'), self, activated=self.toggle_comment,
                  context=Qt.ShortcutContext.WidgetShortcut)
        QShortcut(QKeySequence('Ctrl+Space'), self, activated=lambda: self._complete(force=True),
                  context=Qt.ShortcutContext.WidgetShortcut)

    # ---------------------------------------------------------------- gutter
    def gutter_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_margins(self):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margins()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        t, dark = _theme()
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor(t['surface']))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line = number + 1
                if line in self.error_lines or line in self.warning_lines:
                    color = QColor(t['danger'] if line in self.error_lines else t['warning'])
                    painter.setBrush(color)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRoundedRect(QRect(2, top + 2, 4, height - 4), 2, 2)
                painter.setPen(QColor(t['foreground'] if number == current else t['subtle']))
                painter.drawText(QRect(0, top, self.gutter.width() - 6, height),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(line))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1
        painter.end()

    def _cursor_changed(self):
        t, dark = _theme()
        extra = []
        line = QTextEdit.ExtraSelection()
        line.format.setBackground(QColor(t['hover']))
        line.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        line.cursor = self.textCursor()
        line.cursor.clearSelection()
        extra.append(line)
        for number in list(self.error_lines)[:200]:
            block = self.document().findBlockByNumber(number - 1)
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                sel.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
                sel.format.setUnderlineColor(QColor(t['danger']))
                sel.cursor = QTextCursor(block)
                sel.cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                extra.append(sel)
        self.setExtraSelections(extra)
        c = self.textCursor()
        self.cursorMoved.emit(c.blockNumber() + 1, c.positionInBlock() + 1)
        self.gutter.update()

    def set_markers(self, errors: dict, warnings: dict):
        self.error_lines = dict(errors)
        self.warning_lines = dict(warnings)
        self._cursor_changed()

    def event(self, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Type.ToolTip:
            cursor = self.cursorForPosition(ev.pos() - self.viewport().pos())
            line = cursor.blockNumber() + 1
            text = self.error_lines.get(line) or self.warning_lines.get(line)
            if text:
                from PySide6.QtWidgets import QToolTip
                QToolTip.showText(ev.globalPos(), text, self)
                return True
        return super().event(ev)

    # ------------------------------------------------------------- navigation
    def go_to_line(self, line: int, column: int = 1):
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor,
                            max(0, min(column - 1, block.length() - 1)))
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    def insert_snippet(self, text: str, cursor_marker: str = '§'):
        """Insert ``text`` at the cursor; ``§`` marks where the cursor goes (else the end)."""
        cursor = self.textCursor()
        selected = cursor.selectedText().replace('\u2029', '\n')
        if '¤' in text:
            text = text.replace('¤', selected)
        at = text.find(cursor_marker)
        clean = text.replace(cursor_marker, '')
        cursor.beginEditBlock()
        start = cursor.selectionStart()
        cursor.insertText(clean)
        cursor.endEditBlock()
        if at >= 0:
            cursor.setPosition(start + at)
            self.setTextCursor(cursor)
        self.setFocus()

    def wrap_selection(self, before: str, after: str):
        cursor = self.textCursor()
        text = cursor.selectedText().replace('\u2029', '\n')
        cursor.beginEditBlock()
        start = cursor.selectionStart()
        cursor.insertText(before + text + after)
        cursor.endEditBlock()
        if not text:
            cursor.setPosition(start + len(before))
            self.setTextCursor(cursor)
        self.setFocus()

    def toggle_comment(self):
        cursor = self.textCursor()
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(max(cursor.selectionStart(), cursor.selectionEnd() - (1 if cursor.hasSelection() else 0))).blockNumber()
        blocks = [doc.findBlockByNumber(n) for n in range(first, last + 1)]
        uncomment = all(b.text().lstrip().startswith('%') or not b.text().strip() for b in blocks)
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        for block in blocks:
            text = block.text()
            if not text.strip():
                continue
            if uncomment:
                index = text.find('%')
                edit.setPosition(block.position() + index)
                edit.setPosition(block.position() + index + (2 if text[index:index + 2] == '% ' else 1),
                                 QTextCursor.MoveMode.KeepAnchor)
                edit.removeSelectedText()
            else:
                edit.setPosition(block.position())
                edit.insertText('% ')
        edit.endEditBlock()

    # -------------------------------------------------------------- typing aids
    def keyPressEvent(self, event):
        popup = self.completer.popup()
        if popup.isVisible() and event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab,
                                                 Qt.Key.Key_Escape, Qt.Key.Key_Backtab):
            event.ignore()          # the completer takes these keys (Qt's completer pattern)
            return
        text = event.text()
        cursor = self.textCursor()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._newline(cursor)
            return
        if event.key() == Qt.Key.Key_Tab and cursor.hasSelection():
            self._indent(cursor, True)
            return
        if event.key() == Qt.Key.Key_Backtab:
            self._indent(cursor, False)
            return
        if text in PAIRS and not cursor.hasSelection():
            nxt = self._next_char(cursor)
            if text in (')', ']', '}', '$') and nxt == text and text != '{':
                cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(cursor)
                return
            if text == '$' and self._prev_char(cursor) == '\\':
                super().keyPressEvent(event)
                return
            if not nxt or nxt.isspace() or nxt in ')]}$':
                cursor.insertText(text + PAIRS[text])
                cursor.movePosition(QTextCursor.MoveOperation.Left)
                self.setTextCursor(cursor)
                self._maybe_complete(text)
                return
        if text in (')', ']', '}') and self._next_char(cursor) == text:
            cursor.movePosition(QTextCursor.MoveOperation.Right)
            self.setTextCursor(cursor)
            return
        if text and text in PAIRS.values() and cursor.hasSelection():
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Backspace and not cursor.hasSelection():
            prev, nxt = self._prev_char(cursor), self._next_char(cursor)
            if prev in PAIRS and PAIRS[prev] == nxt:
                cursor.deleteChar()
        super().keyPressEvent(event)
        self._maybe_complete(text)

    def _prev_char(self, cursor):
        pos = cursor.position()
        return self.document().characterAt(pos - 1) if pos > 0 else ''

    def _next_char(self, cursor):
        ch = self.document().characterAt(cursor.position())
        return '' if ch in ('\u2029', '\x00') else ch

    def _newline(self, cursor):
        block = cursor.block().text()
        indent = re.match(r'[ \t]*', block).group(0)
        before = block[:cursor.positionInBlock()]
        env = re.search(r'\\begin\{([^}]+)\}\s*(\[[^\]]*\])?\s*(\{[^}]*\})?\s*$', before)
        cursor.beginEditBlock()
        if env and f'\\end{{{env.group(1)}}}' not in self.toPlainText()[cursor.position():cursor.position() + 4000].split('\\begin{' + env.group(1) + '}')[0]:
            cursor.insertText('\n' + indent + '  ')
            keep = cursor.position()
            cursor.insertText('\n' + indent + f'\\end{{{env.group(1)}}}')
            cursor.setPosition(keep)
        elif re.match(r'\s*\\item\b', block) and before.strip() == '\\item':
            # empty \item + Enter ends the list item, like a word processor
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText(indent[:-2] if len(indent) >= 2 else '')
        elif re.match(r'\s*\\item\b', block):
            cursor.insertText('\n' + indent + '\\item ')
        else:
            cursor.insertText('\n' + indent)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _indent(self, cursor, inward: bool):
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        for n in range(first, last + 1):
            block = doc.findBlockByNumber(n)
            edit.setPosition(block.position())
            if inward:
                edit.insertText('  ')
            else:
                text = block.text()
                remove = len(text) - len(text.lstrip(' ')) if not text.startswith('\t') else 1
                remove = min(2, remove)
                if remove:
                    edit.setPosition(block.position() + remove, QTextCursor.MoveMode.KeepAnchor)
                    edit.removeSelectedText()
        edit.endEditBlock()

    # --------------------------------------------------------------- completion
    def _context(self):
        cursor = self.textCursor()
        before = cursor.block().text()[:cursor.positionInBlock()]
        m = re.search(r'\\(?:cite[a-zA-Z]*|ref|eqref|autoref|cref|Cref|pageref|input|include|includegraphics|begin|end|usepackage)'
                      r'(?:\[[^\]]*\])?\{([^}{]*)$', before)
        if m:
            head = before[:m.start(1)]
            kind = ('cite' if '\\cite' in head[-20:] or 'cite' in head.rsplit('\\', 1)[-1] else
                    'ref' if 'ref' in head.rsplit('\\', 1)[-1] else
                    'env' if head.rsplit('\\', 1)[-1].startswith(('begin', 'end')) else
                    'package' if head.rsplit('\\', 1)[-1].startswith('usepackage') else 'file')
            prefix = m.group(1).split(',')[-1].strip()
            return kind, prefix
        m = re.search(r'\\([A-Za-z@]*)$', before)
        if m:
            return 'command', m.group(1)
        return None, ''

    def _maybe_complete(self, typed: str):
        if not typed:
            return
        kind, prefix = self._context()
        if kind == 'command' and len(prefix) >= 2:
            self._complete()
        elif kind in ('cite', 'ref', 'env', 'file') and (typed in '{,' or len(prefix) >= 1):
            self._complete()
        else:
            self.completer.popup().hide()

    def _complete(self, force=False):
        kind, prefix = self._context()
        if kind is None or self.provider is None:
            return
        words = self.provider(kind) or []
        if not words:
            return
        self._completion_kind = kind
        self._model.setStringList(words)
        self.completer.setCompletionPrefix(prefix)
        if self.completer.completionCount() == 0 or (self.completer.completionCount() == 1 and
                                                     self.completer.currentCompletion() == prefix and not force):
            self.completer.popup().hide()
            return
        rect = self.cursorRect()
        rect.setWidth(max(260, self.completer.popup().sizeHintForColumn(0) + 30))
        self.completer.popup().setCurrentIndex(self.completer.completionModel().index(0, 0))
        self.completer.complete(rect)

    def _insert_completion(self, word: str):
        kind, prefix = self._context()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, len(prefix))
        cursor.insertText(word)
        if kind == 'env' and cursor.block().text()[:cursor.positionInBlock()].rstrip().endswith('\\begin{' + word):
            if self._next_char(cursor) == '}':
                cursor.movePosition(QTextCursor.MoveOperation.Right)
            self.setTextCursor(cursor)
            self._newline(cursor)
            return
        if kind == 'command' and word in ('begin', 'end', 'section', 'subsection', 'textbf', 'textit', 'emph',
                                          'label', 'ref', 'cite', 'caption', 'includegraphics', 'usepackage',
                                          'chapter', 'subsubsection', 'frametitle', 'mathrm', 'mathbf', 'text',
                                          'frac', 'sqrt', 'SI', 'si', 'num', 'eqref', 'href', 'url', 'input', 'title',
                                          'author', 'footnote', 'texttt', 'underline', 'textcolor'):
            if word == 'frac':
                cursor.insertText('{}{}')
                cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, 3)
            else:
                cursor.insertText('{}')
                cursor.movePosition(QTextCursor.MoveOperation.Left)
        self.setTextCursor(cursor)
        if kind == 'command' and word in ('begin', 'ref', 'cite', 'eqref', 'input', 'includegraphics'):
            QTimer.singleShot(0, lambda: self._complete(force=True))

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        selected = self.textCursor().selectedText().replace('\u2029', '\n')
        menu.addSeparator()
        action = menu.addAction('Ask the assistant about this' if selected else 'Ask the assistant about this line')
        action.triggered.connect(lambda: self.askAssistant.emit(selected or self.textCursor().block().text()))
        menu.addAction('Toggle comment\tCtrl+/', self.toggle_comment)
        menu.exec(event.globalPos())


def new_document(text: str = '') -> QTextDocument:
    doc = QTextDocument()
    doc.setDocumentLayout(QPlainTextDocumentLayout(doc))
    doc.setPlainText(text)
    doc.setModified(False)
    return doc


class FindBar(QFrame):
    """Find / replace under the editor (Ctrl+F, Ctrl+H)."""

    def __init__(self, editor_getter, parent=None):
        super().__init__(parent)
        self.setObjectName('findBar')
        self._editor = editor_getter
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        self.find = QLineEdit()
        self.find.setPlaceholderText('Find')
        self.find.setClearButtonEnabled(True)
        self.replace = QLineEdit()
        self.replace.setPlaceholderText('Replace with')
        self.case = QCheckBox('Aa')
        self.case.setToolTip('Match case')
        self.regex = QCheckBox('.*')
        self.regex.setToolTip('Regular expression')
        self.status = QLabel('')
        self.status.setObjectName('hint')
        from spm_studio.shared.appearance import tool_button
        prev = tool_button('', 'chevron-up', 'Previous (Shift+Enter)', icon_only=True)
        nxt = tool_button('', 'chevron-down', 'Next (Enter)', icon_only=True)
        one = QToolButton()
        one.setText('Replace')
        every = QToolButton()
        every.setText('All')
        close = tool_button('', 'close', 'Close (Esc)', icon_only=True)
        for w in (self.find, prev, nxt, self.case, self.regex, self.replace, one, every, self.status):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(close)
        self.find.returnPressed.connect(lambda: self.search(True))
        prev.clicked.connect(lambda: self.search(False))
        nxt.clicked.connect(lambda: self.search(True))
        one.clicked.connect(self.replace_one)
        every.clicked.connect(self.replace_all)
        close.clicked.connect(self.close_bar)
        QShortcut(QKeySequence('Shift+Return'), self.find, activated=lambda: self.search(False))
        QShortcut(QKeySequence('Escape'), self, activated=self.close_bar,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.hide()

    def open(self, replace=False):
        editor = self._editor()
        if editor is not None and editor.textCursor().hasSelection():
            self.find.setText(editor.textCursor().selectedText())
        self.replace.setVisible(True)
        self.show()
        (self.replace if replace and self.find.text() else self.find).setFocus()
        self.find.selectAll()

    def close_bar(self):
        self.hide()
        editor = self._editor()
        if editor is not None:
            editor.setFocus()

    def _flags(self, forward):
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        if self.case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def _query(self):
        if self.regex.isChecked():
            from PySide6.QtCore import QRegularExpression
            rx = QRegularExpression(self.find.text())
            if not self.case.isChecked():
                rx.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
            return rx
        return self.find.text()

    def search(self, forward=True) -> bool:
        editor = self._editor()
        if editor is None or not self.find.text():
            return False
        found = editor.find(self._query(), self._flags(forward))
        if not found:
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start if forward else QTextCursor.MoveOperation.End)
            editor.setTextCursor(cursor)
            found = editor.find(self._query(), self._flags(forward))
        self.status.setText('' if found else 'Not found')
        return found

    def replace_one(self):
        editor = self._editor()
        if editor is None:
            return
        cursor = editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(self.replace.text())
        self.search(True)

    def replace_all(self):
        editor = self._editor()
        if editor is None or not self.find.text():
            return
        text = editor.toPlainText()
        if self.regex.isChecked():
            try:
                pattern = re.compile(self.find.text(), 0 if self.case.isChecked() else re.I)
            except re.error as exc:
                self.status.setText(f'Invalid expression: {exc}')
                return
            new, count = pattern.subn(self.replace.text(), text)
        else:
            pattern = re.compile(re.escape(self.find.text()), 0 if self.case.isChecked() else re.I)
            new, count = pattern.subn(lambda _m: self.replace.text(), text)
        if count:
            cursor = editor.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(new)
            cursor.endEditBlock()
        self.status.setText(f'{count} replaced')
