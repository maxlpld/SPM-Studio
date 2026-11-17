"""LaTeX editor window (v0.0.8): project files, source, live PDF, logs — in the spirit of Overleaf.

Opened from the *LaTeX* button of the main window (shown when *Settings › Documents › LaTeX
editor* is on). Figures exported from SPM Studio arrive here through :mod:`.hub` (copied to
``figures/`` and included with ``\\includegraphics``); the assistant acts on it through the
``<spm-doc>`` requests of :mod:`spm_studio.documents.protocol`.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QEventLoop, QFileSystemWatcher, QSettings, QEvent
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor, QAction, QActionGroup
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabBar, QLabel,
                               QTreeWidget, QTreeWidgetItem, QMenu, QFileDialog, QFrame, QInputDialog, QSpinBox,
                               QDialog, QFormLayout, QDialogButtonBox, QCheckBox, QApplication)

from spm_studio.documents import settings as doc_settings, tex, latex_project, templates, overleaf
from spm_studio.shared.dialogs import MessageDialog, TextInputDialog
from .common import HeaderBar, Ribbon, button, open_path, run_in_thread, figure_for_latex
from .code_editor import CodeEditor, LatexHighlighter, new_document, FindBar
from .latex_parts import Compiler, PdfPane, LogPane, FileTree, symbol_menu

BINARY_PREVIEW = ('.png', '.jpg', '.jpeg', '.pdf', '.svg', '.gif', '.eps')
PACKAGES = sorted('''amsmath amssymb amsthm bm graphicx xcolor hyperref geometry siunitx booktabs tabularx
multirow float subcaption caption cleveref natbib biblatex babel csquotes fontenc inputenc lmodern microtype
tikz pgfplots listings minted algorithm2e enumitem fancyhdr titlesec setspace physics mhchem chemfig
wrapfig xspace url authblk lipsum mathtools braket'''.split())


def to_qt(text: str, index: int) -> int:
    """Python string index → QTextDocument position (UTF-16 code units)."""
    head = text[:index]
    return index if head.isascii() else len(head.encode('utf-16-le')) // 2


def from_qt(text: str, position: int) -> int:
    """QTextDocument position → Python string index."""
    if text.isascii():
        return position
    units = 0
    for i, ch in enumerate(text):
        if units >= position:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(text)


class LatexEditorWindow(QMainWindow):
    def __init__(self, project, hub=None):
        super().__init__()
        self.hub = hub
        self.conf = doc_settings.load()
        self.project = Path(project)
        self.docs = {}              # path str -> QTextDocument
        self._highlighters = {}
        self._cursors = {}
        self.current = None         # path str of the file in the editor
        self.summary = tex.LogSummary()
        self._pending_compile = False
        self._compile_waiters = []
        self._last_ok = None
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1480, 900)
        self.setAcceptDrops(True)
        self.compiler = Compiler(self)
        self.compiler.started.connect(self._compile_started)
        self.compiler.finished.connect(self._compile_finished)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._file_changed_on_disk)
        self._build()
        self._timers()
        self.set_project(self.project)
        geometry = QSettings('SPM Studio', 'Documents').value('latex_geometry')
        if geometry:
            self.restoreGeometry(geometry)

    # ================================================================== interface
    def _build(self):
        central = QWidget()
        central.setObjectName('workbenchRoot')
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = HeaderBar('LaTeX')
        self.menu_button = button('Menu', 'menu', 'Project: new, open, import, save as, templates, download')
        self.menu_button.setPopupMode(self.menu_button.ToolButtonPopupMode.InstantPopup)
        self.project_menu = QMenu(self)
        self.menu_button.setMenu(self.project_menu)
        self.header.row.insertWidget(0, self.menu_button)
        self.header.stretch()
        self.from_spm = button('From SPM Studio', 'send-to', 'Insert a scan or an analysis figure from SPM Studio')
        self.from_spm.setPopupMode(self.from_spm.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction('Export the open scan into this document…', self._export_from_scan)
        menu.addAction('Insert a figure file…', self._insert_figure_file)
        self.from_spm.setMenu(menu)
        self.header.add(self.from_spm)
        self.overleaf_button = button('Overleaf', 'overleaf', 'Push / pull this project to Overleaf')
        self.overleaf_button.setPopupMode(self.overleaf_button.ToolButtonPopupMode.InstantPopup)
        self.overleaf_menu = QMenu(self)
        self.overleaf_menu.aboutToShow.connect(self._fill_overleaf_menu)
        self.overleaf_button.setMenu(self.overleaf_menu)
        self.header.add(self.overleaf_button)
        self.assistant_button = button('Assistant', 'ai', 'Open the AI assistant next to this window')
        self.assistant_button.clicked.connect(lambda: self.hub.show_assistant(self) if self.hub else None)
        self.header.add(self.assistant_button)
        from spm_studio.shared.appearance import separator
        self.header.add(separator())
        self.auto_button = button('Auto-compile', 'refresh', 'Compile automatically while you type', checkable=True)
        self.auto_button.setObjectName('LatexAutoCompileV008')
        self.auto_button.setChecked(bool(self.conf.get('latex_autocompile', True)))
        self.auto_button.toggled.connect(self._auto_toggled)
        self.header.add(self.auto_button)
        self.compile_button = button('Recompile', 'run', 'Compile the project (Ctrl+Enter)', flat=False, primary=True)
        self.compile_button.setObjectName('LatexRecompileV008')
        compile_menu = QMenu(self)
        self.engine_group = QActionGroup(self)
        engines = compile_menu.addMenu('Compiler')
        found = tex.available_engines()
        for name, label in doc_settings.ENGINE_LABELS.items():
            action = engines.addAction(label + ('' if name in found else '  (not installed)'))
            action.setCheckable(True)
            action.setData(name)
            action.setChecked(name == self.engine())
            action.setEnabled(name in found)
            self.engine_group.addAction(action)
        self.engine_group.triggered.connect(lambda a: self._set_engine(a.data()))
        compile_menu.addAction('Recompile from scratch', lambda: self.compile(clean=True))
        compile_menu.addAction('Stop compilation', self.compiler.stop)
        compile_menu.addSeparator()
        compile_menu.addAction('Delete build files', self._clean_build)
        self.compile_button.setMenu(compile_menu)
        self.compile_button.setPopupMode(self.compile_button.ToolButtonPopupMode.MenuButtonPopup)
        self.compile_button.clicked.connect(lambda: self.compile())
        self.header.add(self.compile_button)
        self.logs_button = button('Logs', 'logs', 'Errors, warnings and the raw log', checkable=True)
        self.logs_button.toggled.connect(lambda on: self.log_pane.setVisible(on))
        self.header.add(self.logs_button)
        self.badge = QLabel('')
        self.badge.setObjectName('errorBadge')
        self.badge.hide()
        self.header.add(self.badge)
        root.addWidget(self.header)

        self.ribbon = Ribbon()
        self._fill_ribbon()
        root.addWidget(self.ribbon)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.splitter = splitter
        # left: files + outline
        left = QSplitter(Qt.Orientation.Vertical)
        files_panel = QWidget()
        fl = QVBoxLayout(files_panel)
        fl.setContentsMargins(8, 8, 4, 4)
        fl.setSpacing(4)
        head = QHBoxLayout()
        title = QLabel('FILES')
        title.setObjectName('panelTitle')
        head.addWidget(title, 1)
        for icon_name, tip, slot in (('file-plus', 'New file', self._new_file),
                                     ('folder-plus', 'New folder', self._new_folder),
                                     ('upload', 'Upload files into the project', self._upload_files)):
            b = button('', icon_name, tip, icon_only=True)
            b.clicked.connect(slot)
            head.addWidget(b)
        fl.addLayout(head)
        self.tree = FileTree()
        self.tree.fileActivated.connect(self.open_file)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        fl.addWidget(self.tree, 1)
        left.addWidget(files_panel)
        outline_panel = QWidget()
        ol = QVBoxLayout(outline_panel)
        ol.setContentsMargins(8, 4, 4, 8)
        ol.setSpacing(4)
        title = QLabel('OUTLINE')
        title.setObjectName('panelTitle')
        ol.addWidget(title)
        self.outline = QTreeWidget()
        self.outline.setHeaderHidden(True)
        self.outline.setIndentation(12)
        self.outline.itemClicked.connect(lambda item, _c: self.editor.go_to_line(item.data(0, Qt.ItemDataRole.UserRole)))
        ol.addWidget(self.outline, 1)
        left.addWidget(outline_panel)
        left.setSizes([480, 320])
        left.setMinimumWidth(190)
        splitter.addWidget(left)
        # centre: tabs + editor + find bar
        centre = QWidget()
        cl = QVBoxLayout(centre)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.tabs = QTabBar()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        cl.addWidget(self.tabs)
        self.editor = CodeEditor()
        self.editor.provider = self._completions
        self.editor.cursorMoved.connect(self._cursor_moved)
        self.editor.askAssistant.connect(self._ask_about)
        f = self.editor.font()
        f.setPointSize(int(self.conf.get('latex_font_size', 11)))
        self.editor.setFont(f)
        if not self.conf.get('latex_wrap', True):
            self.editor.setLineWrapMode(self.editor.LineWrapMode.NoWrap)
        cl.addWidget(self.editor, 1)
        self.find_bar = FindBar(lambda: self.editor)
        cl.addWidget(self.find_bar)
        splitter.addWidget(centre)
        # right: PDF + logs
        right = QSplitter(Qt.Orientation.Vertical)
        self.pdf = PdfPane()
        self.pdf.download.clicked.connect(self._download_pdf)
        self.pdf.external.clicked.connect(lambda: open_path(self.pdf.pdf_path) if self.pdf.pdf_path else None)
        right.addWidget(self.pdf)
        self.log_pane = LogPane()
        self.log_pane.jump.connect(self._jump_to)
        self.log_pane.askAssistant.connect(self._ask_fix)
        self.log_pane.hide()
        right.addWidget(self.log_pane)
        right.setSizes([620, 260])
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([230, 620, 620])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.position = QLabel('')
        self.compile_state = QLabel('')
        self.statusBar().addWidget(self.position)
        self.statusBar().addPermanentWidget(self.compile_state)
        self._fill_project_menu()
        for keys, slot in (('Ctrl+S', self.save_all), ('Ctrl+Return', self.compile), ('Ctrl+Enter', self.compile),
                           ('Ctrl+F', lambda: self.find_bar.open(False)), ('Ctrl+H', lambda: self.find_bar.open(True)),
                           ('Ctrl+B', lambda: self.editor.wrap_selection('\\textbf{', '}')),
                           ('Ctrl+I', lambda: self.editor.wrap_selection('\\textit{', '}')),
                           ('Ctrl+Shift+M', lambda: self.editor.wrap_selection('\\[ ', ' \\]'))):
            QShortcut(QKeySequence(keys), self, activated=slot)

    def _fill_ribbon(self):
        r = self.ribbon
        e = lambda: self.editor
        undo = button('', 'undo', 'Undo (Ctrl+Z)', icon_only=True)
        undo.clicked.connect(lambda: e().undo())
        redo = button('', 'redo', 'Redo (Ctrl+Shift+Z)', icon_only=True)
        redo.clicked.connect(lambda: e().redo())
        r.add(undo)
        r.add(redo)
        r.separator()
        section = button('Section', None, 'Insert a heading')
        section.setPopupMode(section.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        for name in ('part', 'chapter', 'section', 'subsection', 'subsubsection', 'paragraph'):
            menu.addAction(name.capitalize(), lambda n=name: e().insert_snippet(f'\\{n}{{§¤}}\n'))
        section.setMenu(menu)
        r.add(section)
        r.separator()
        for icon_name, tip, before, after in (('bold', 'Bold (Ctrl+B)', '\\textbf{', '}'),
                                              ('italic', 'Italic (Ctrl+I)', '\\textit{', '}'),
                                              ('underline', 'Underline', '\\underline{', '}')):
            b = button('', icon_name, tip, icon_only=True)
            b.clicked.connect(lambda _=False, x=before, y=after: e().wrap_selection(x, y))
            r.add(b)
        r.separator()
        inline = button('$x$', None, 'Inline math')
        inline.clicked.connect(lambda: e().wrap_selection('$', '$'))
        display = button('\\[x\\]', None, 'Display math (Ctrl+Shift+M)')
        display.clicked.connect(lambda: e().wrap_selection('\\[\n  ', '\n\\]'))
        equation = button('', 'formula', 'Numbered equation', icon_only=True)
        equation.clicked.connect(lambda: e().insert_snippet('\\begin{equation}\n  §¤\n  \\label{eq:}\n\\end{equation}\n'))
        symbols = button('', 'sigma', 'Symbols', icon_only=True)
        symbols.setPopupMode(symbols.ToolButtonPopupMode.InstantPopup)
        symbols.setMenu(symbol_menu(self, lambda c: e().insert_snippet(c.replace('{}', '{§}', 1) if '{}' in c else c + ' ')))
        for w in (inline, display, equation, symbols):
            r.add(w)
        r.separator()
        bullets = button('', 'list', 'Bulleted list', icon_only=True)
        bullets.clicked.connect(lambda: e().insert_snippet('\\begin{itemize}\n  \\item §¤\n\\end{itemize}\n'))
        numbers = button('', 'numbered', 'Numbered list', icon_only=True)
        numbers.clicked.connect(lambda: e().insert_snippet('\\begin{enumerate}\n  \\item §¤\n\\end{enumerate}\n'))
        r.add(bullets)
        r.add(numbers)
        r.separator()
        figure = button('Figure', 'image', 'Insert a figure (copied into figures/)')
        figure.clicked.connect(self._insert_figure_file)
        table = button('Table', 'table', 'Insert a table')
        table.clicked.connect(self._insert_table)
        r.add(figure)
        r.add(table)
        r.separator()
        for text, tip, snippet in (('ref', 'Cross-reference', '\\ref{§}'), ('cite', 'Citation', '\\cite{§}'),
                                   ('link', 'Hyperlink', '\\href{§}{¤}')):
            b = button(text, 'link' if text == 'link' else None, tip)
            b.clicked.connect(lambda _=False, s=snippet: e().insert_snippet(s))
            r.add(b)
        comment = button('', 'comment', 'Comment / uncomment lines (Ctrl+/)', icon_only=True)
        comment.clicked.connect(lambda: e().toggle_comment())
        r.add(comment)
        r.stretch()
        find = button('', 'search', 'Find and replace (Ctrl+F)', icon_only=True)
        find.clicked.connect(lambda: self.find_bar.open(False))
        r.add(find)

    def _fill_project_menu(self):
        m = self.project_menu
        m.clear()
        m.addAction('New project…', lambda: self.hub.launch('latex', self) if self.hub else None)
        m.addAction('Open project…', self._open_project)
        m.addAction('Import a .zip (Overleaf “Download source”)…', self._import_zip)
        m.addAction('Import from Overleaf…', lambda: self.hub.import_from_overleaf(self) if self.hub else None)
        m.addSeparator()
        m.addAction('Save\tCtrl+S', self.save_all)
        m.addAction('Save as… (copy the project elsewhere)', self._save_as)
        m.addAction('Save as template…', self._save_as_template)
        m.addSeparator()
        m.addAction('Download source (.zip)…', self._download_zip)
        m.addAction('Download PDF…', self._download_pdf)
        m.addSeparator()
        self.main_menu = m.addMenu('Main document')
        self.main_menu.aboutToShow.connect(self._fill_main_menu)
        m.addAction('Word count', self._word_count)
        m.addAction('Editor settings…', self._editor_settings)
        m.addSeparator()
        m.addAction('Open project folder', lambda: open_path(self.project))
        m.addAction('Close', self.close)

    def _timers(self):
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(1500)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autocompile_timer = QTimer(self)
        self.autocompile_timer.setSingleShot(True)
        self.autocompile_timer.setInterval(max(300, int(self.conf.get('latex_autocompile_delay_ms', 1200))))
        self.autocompile_timer.timeout.connect(self._autocompile)
        self.outline_timer = QTimer(self)
        self.outline_timer.setSingleShot(True)
        self.outline_timer.setInterval(500)
        self.outline_timer.timeout.connect(self._update_outline)

    # ================================================================== project
    def set_project(self, folder):
        if self.docs and not self._save_or_discard():
            return False
        self._blank = new_document('')
        self.editor.setDocument(self._blank)        # never show a document that is being deleted
        self.current = None
        for path in list(self.docs):
            self._forget(path)
        while self.tabs.count():
            self.tabs.removeTab(0)
        self.project = Path(folder)
        self.tree.set_root(self.project)
        self.header.title.setText(self.project.name)
        self.setWindowTitle(f'{self.project.name} — LaTeX · SPM Studio')
        doc_settings.add_recent('latex', self.project)
        main = self.main_file()
        if main is not None:
            self.open_file(str(main))
            self.tree.select_path(main)
        build_pdf = self.project / tex.BUILD_DIR / ((main.stem if main else 'main') + '.pdf')
        if build_pdf.is_file():
            self.pdf.load(str(build_pdf))
        self._update_overleaf_button()
        if self.auto_button.isChecked():
            self.autocompile_timer.start()        # child timer: cancelled if the window closes first
        return True

    def main_file(self) -> Path | None:
        return latex_project.main_file(self.project)

    def engine(self) -> str:
        meta = latex_project.project_meta(self.project) if hasattr(self, 'project') else {}
        return meta.get('engine') or self.conf.get('latex_engine', 'latexmk')

    def _set_engine(self, name):
        latex_project.save_project_meta(self.project, engine=name)
        self.compile()

    def _fill_main_menu(self):
        self.main_menu.clear()
        current = self.main_file()
        for path in sorted(self.project.rglob('*.tex')):
            rel = path.relative_to(self.project)
            if any(p in latex_project.IGNORED_NAMES for p in rel.parts):
                continue
            action = self.main_menu.addAction(rel.as_posix())
            action.setCheckable(True)
            action.setChecked(current is not None and path == current)
            action.triggered.connect(lambda _=False, r=rel.as_posix(): (
                latex_project.save_project_meta(self.project, main=r), self.compile()))

    def _safe_path(self, relative: str) -> Path:
        target = (self.project / str(relative).replace('\\', '/').lstrip('/')).resolve()
        if not target.is_relative_to(self.project.resolve()):
            raise ValueError('The path must stay inside the project')
        return target

    # ================================================================== files
    def open_file(self, path):
        path = str(Path(path))
        p = Path(path)
        if p.suffix.lower() in BINARY_PREVIEW:
            open_path(p)
            return
        if path not in self.docs:
            try:
                text = p.read_text(encoding='utf8')
            except UnicodeDecodeError:
                text = p.read_text(encoding='latin-1')
            except OSError as exc:
                MessageDialog.warning(self, 'Cannot open', str(exc))
                return
            doc = new_document(text)
            doc.setProperty('path', path)
            self._highlighters[path] = LatexHighlighter(doc) if p.suffix.lower() in ('.tex', '.sty', '.cls', '.bib', '.tikz') else None
            doc.contentsChanged.connect(self._contents_changed)
            doc.modificationChanged.connect(lambda _m, d=doc: self._mark_tab(d))
            self.docs[path] = doc
            self.watcher.addPath(path)
            index = self.tabs.addTab(p.name)
            self.tabs.setTabData(index, path)
            self.tabs.setTabToolTip(index, str(p.relative_to(self.project)) if p.is_relative_to(self.project) else path)
        for i in range(self.tabs.count()):
            if self.tabs.tabData(i) == path:
                self.tabs.setCurrentIndex(i)
                break
        self._show(path)

    def _show(self, path):
        if self.current and self.current in self.docs:
            self._cursors[self.current] = self.editor.textCursor().position()
        self.current = path
        doc = self.docs[path]
        self.editor.setDocument(doc)
        cursor = QTextCursor(doc)
        cursor.setPosition(min(self._cursors.get(path, 0), max(0, doc.characterCount() - 1)))
        self.editor.setTextCursor(cursor)
        self._apply_markers()
        self._update_outline()
        self.editor.setFocus()

    def _tab_changed(self, index):
        if index >= 0:
            path = self.tabs.tabData(index)
            if path and path in self.docs and path != self.current:
                self._show(path)

    def _close_tab(self, index):
        path = self.tabs.tabData(index)
        doc = self.docs.get(path)
        if doc is not None and doc.isModified():
            self._save(path)
        if self.tabs.count() == 1:
            return                                   # keep one file open
        self.tabs.removeTab(index)
        self._forget(path)
        new = self.tabs.tabData(self.tabs.currentIndex())
        if new:
            self._show(new)

    def _forget(self, path):
        doc = self.docs.pop(path, None)
        self._highlighters.pop(path, None)
        try:
            self.watcher.removePath(path)
        except RuntimeError:
            pass
        if self.current == path:
            self.current = None
        if doc is not None:
            doc.deleteLater()

    def _mark_tab(self, doc):
        path = doc.property('path')
        for i in range(self.tabs.count()):
            if self.tabs.tabData(i) == path:
                self.tabs.setTabText(i, Path(path).name + (' •' if doc.isModified() else ''))

    def _contents_changed(self):
        if self.conf.get('latex_autosave', True):
            self.autosave_timer.start()
        if self.auto_button.isChecked():
            self.autocompile_timer.start()
        self.outline_timer.start()

    def _save(self, path) -> bool:
        doc = self.docs.get(path)
        if doc is None:
            return True
        try:
            self.watcher.removePath(path)
        except RuntimeError:
            pass
        try:
            Path(path).write_text(doc.toPlainText(), encoding='utf8')
        except OSError as exc:
            MessageDialog.warning(self, 'Not saved', f'{Path(path).name}: {exc}')
            return False
        finally:
            if Path(path).exists():
                self.watcher.addPath(path)
        doc.setModified(False)
        return True

    def save_all(self) -> bool:
        ok = True
        for path, doc in list(self.docs.items()):
            if doc.isModified():
                ok = self._save(path) and ok
        if ok:
            self.statusBar().showMessage('Saved', 2000)
        return ok

    def _autosave(self):
        self.save_all()

    def _save_or_discard(self) -> bool:
        if not any(d.isModified() for d in self.docs.values()):
            return True
        if self.conf.get('latex_autosave', True):
            return self.save_all()
        answer = MessageDialog.question(self, 'Unsaved changes', 'Save the changes of this project?',
                                        MessageDialog.StandardButton.Save | MessageDialog.StandardButton.Discard |
                                        MessageDialog.StandardButton.Cancel)
        if answer == MessageDialog.StandardButton.Save:
            return self.save_all()
        return answer == MessageDialog.StandardButton.Discard

    def _file_changed_on_disk(self, path):
        doc = self.docs.get(path)
        if doc is None or not Path(path).exists():
            return
        try:
            text = Path(path).read_text(encoding='utf8')
        except (OSError, UnicodeDecodeError):
            return
        if text == doc.toPlainText():
            self.watcher.addPath(path)
            return
        if doc.isModified():
            answer = MessageDialog.question(self, 'Changed on disk',
                                            f'{Path(path).name} was changed by another program (for example the '
                                            f'assistant). Load that version and drop your unsaved edits?')
            if answer != MessageDialog.StandardButton.Yes:
                self.watcher.addPath(path)
                return
        self._replace_document_text(doc, text)
        doc.setModified(False)
        self.watcher.addPath(path)
        self.statusBar().showMessage(f'{Path(path).name} reloaded (changed on disk)', 4000)

    @staticmethod
    def _replace_document_text(doc, text):
        """Replace only the part that changed: cursors elsewhere stay where they are, Ctrl+Z undoes it."""
        old = doc.toPlainText()
        if old == text:
            return
        import os
        prefix = len(os.path.commonprefix([old, text]))
        limit = min(len(old), len(text)) - prefix
        suffix = 0
        while suffix < limit and old[len(old) - 1 - suffix] == text[len(text) - 1 - suffix]:
            suffix += 1
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        cursor.setPosition(to_qt(old, prefix))
        cursor.setPosition(to_qt(old, len(old) - suffix), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text[prefix:len(text) - suffix])
        cursor.endEditBlock()

    def _new_file(self):
        name, ok = TextInputDialog.getText(self, 'New file', 'File name (e.g. sections/results.tex):', text='new.tex')
        if not ok or not name.strip():
            return
        try:
            target = self._safe_path(name.strip())
        except ValueError as exc:
            MessageDialog.warning(self, 'New file', str(exc))
            return
        if target.exists():
            MessageDialog.warning(self, 'New file', f'{name} already exists')
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('% ' + target.name + '\n' if target.suffix == '.tex' else '', encoding='utf8')
        self.open_file(str(target))

    def _new_folder(self):
        name, ok = TextInputDialog.getText(self, 'New folder', 'Folder name:', text='sections')
        if ok and name.strip():
            try:
                self._safe_path(name.strip()).mkdir(parents=True, exist_ok=True)
            except (ValueError, OSError) as exc:
                MessageDialog.warning(self, 'New folder', str(exc))

    def _upload_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Add files to the project', str(Path.home()))
        target_dir = self.tree.selected_path()
        if target_dir is None or not target_dir.is_dir():
            target_dir = self.project
        import shutil
        for file in files:
            src = Path(file)
            folder = self.project / self.conf.get('latex_figures_folder', 'figures') \
                if src.suffix.lower() in BINARY_PREVIEW and target_dir == self.project else target_dir
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, folder / src.name)
        if files:
            self.statusBar().showMessage(f'{len(files)} file(s) added', 3000)

    def _tree_menu(self, pos):
        path = self.tree.path_of(self.tree.indexAt(pos))
        menu = QMenu(self)
        menu.addAction('New file…', self._new_file)
        menu.addAction('New folder…', self._new_folder)
        menu.addAction('Upload files…', self._upload_files)
        if path is not None:
            menu.addSeparator()
            if path.suffix == '.tex':
                menu.addAction('Set as main document', lambda: (
                    latex_project.save_project_meta(self.project, main=path.relative_to(self.project).as_posix()),
                    self.compile()))
            if path.suffix.lower() in BINARY_PREVIEW:
                menu.addAction('Insert as figure', lambda: self.insert_figure([path], copy=False))
                if self.hub is not None:
                    menu.addAction('Add to a presentation…', lambda: self.hub.send_files_dialog([path], self))
            menu.addAction('Rename…', lambda: self.tree.edit(self.tree.indexAt(pos)))
            menu.addAction('Delete', lambda: self._delete(path))
            menu.addAction('Show in folder', lambda: open_path(path.parent if path.is_file() else path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _delete(self, path: Path):
        if not MessageDialog.confirm(self, 'Delete', f'Move {path.name} to the trash?', 'Delete'):
            return
        from PySide6.QtCore import QFile
        if str(path) in self.docs:
            for i in range(self.tabs.count()):
                if self.tabs.tabData(i) == str(path) and self.tabs.count() > 1:
                    self.tabs.removeTab(i)
                    break
            self._forget(str(path))
        result = QFile.moveToTrash(str(path))
        if not (result[0] if isinstance(result, tuple) else result):
            import shutil
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    # ================================================================== editing aids
    def _completions(self, kind):
        texts = [d.toPlainText() for d in self.docs.values()]
        if kind == 'command':
            return sorted(set(latex_project.COMMANDS) | set(latex_project.user_commands(texts)))
        if kind == 'env':
            return latex_project.ENVIRONMENTS
        if kind == 'ref':
            extra = []
            for f in self.project.rglob('*.tex'):
                if str(f) not in self.docs and tex.BUILD_DIR not in f.parts:
                    try:
                        extra.append(f.read_text(encoding='utf8', errors='replace'))
                    except OSError:
                        pass
            return latex_project.labels(texts + extra)
        if kind == 'cite':
            return latex_project.bib_keys(self.project)
        if kind == 'package':
            return PACKAGES
        files = []
        for f in latex_project.project_files(self.project):
            rel = f.relative_to(self.project).as_posix()
            files.append(rel[:-4] if rel.endswith('.tex') else rel)
        return files

    def _cursor_moved(self, line, column):
        words = f' · {self._words} words' if getattr(self, '_words', None) is not None else ''
        self.position.setText(f'{Path(self.current).name if self.current else ""} · line {line}, column {column}{words}')

    def _update_outline(self):
        self.outline.clear()
        if not self.current:
            return
        self._words = tex.word_count(self.editor.toPlainText()) if self.current.endswith('.tex') else None
        stack = []
        for entry in latex_project.outline(self.editor.toPlainText()):
            item = QTreeWidgetItem([entry.title])
            item.setData(0, Qt.ItemDataRole.UserRole, entry.line)
            while stack and stack[-1][0] >= entry.level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.outline.addTopLevelItem(item)
            stack.append((entry.level, item))
        self.outline.expandAll()

    def _insert_table(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Insert table')
        form = QFormLayout(dialog)
        rows = QSpinBox()
        rows.setRange(1, 60)
        rows.setValue(3)
        cols = QSpinBox()
        cols.setRange(1, 20)
        cols.setValue(3)
        booktabs = QCheckBox('Publication style (booktabs)')
        booktabs.setChecked(True)
        form.addRow('Rows', rows)
        form.addRow('Columns', cols)
        form.addRow('', booktabs)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
        form.addRow(box)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if booktabs.isChecked():
            self._ensure_package('booktabs')
        self.editor.insert_snippet(latex_project.table_snippet(rows.value(), cols.value(), booktabs.isChecked()))

    def _ensure_package(self, package):
        main = self.main_file()
        if main is None:
            return
        doc = self.docs.get(str(main))
        text = doc.toPlainText() if doc is not None else main.read_text(encoding='utf8', errors='replace')
        new = latex_project.ensure_package(text, package)
        if new == text:
            return
        if doc is not None:
            self._replace_document_text(doc, new)
        else:
            main.write_text(new, encoding='utf8')

    # ================================================================== figures
    def _insert_figure_file(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Insert figure', str(Path.home()),
                                                'Figures (*.pdf *.png *.jpg *.jpeg *.svg *.eps);;All files (*)')
        if files:
            self.insert_figure([Path(f) for f in files[:1]])
            for extra in files[1:]:
                self.insert_figure([Path(extra)])

    def _export_from_scan(self):
        main = getattr(self.hub, 'main_window', None) if self.hub else None
        if main is None:
            return
        if getattr(main, 'scan', None) is None:
            MessageDialog.information(self, 'No scan', 'Open a scan in the SPM Studio window first.')
            return
        main.raise_()
        main.activateWindow()
        main.export_current(targets={'latex': self})

    def insert_figure(self, files, caption: str = '', copy: bool = True) -> str:
        """Copy the best format of ``files`` into figures/ and insert it at the cursor. Returns its path."""
        figure = figure_for_latex(files, self.project / tex.BUILD_DIR / 'converted')
        folder = self.conf.get('latex_figures_folder', 'figures') or 'figures'
        if copy or not Path(figure).is_relative_to(self.project):
            placed = latex_project.add_figure(self.project, figure, folder)
        else:
            placed = Path(figure)
        relative = placed.relative_to(self.project).as_posix()
        target = self.current if self.current and self.current.endswith('.tex') else None
        if target is None:
            main = self.main_file()
            if main is None:
                raise ValueError('The project has no .tex file')
            self.open_file(str(main))
            target = str(main)
        elif self.current != target:
            self.open_file(target)
        doc = self.docs[target]
        text = doc.toPlainText()
        cursor_pos = from_qt(text, self.editor.textCursor().position())
        new, start, end = latex_project.insert_figure_text(text, cursor_pos, relative, caption)
        self._replace_document_text(doc, new)
        cursor = self.editor.textCursor()
        cursor.setPosition(min(to_qt(new, end), doc.characterCount() - 1))
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self.statusBar().showMessage(f'Figure inserted: {relative}', 5000)
        if self.auto_button.isChecked():
            self.autocompile_timer.start()
        self.raise_()
        self.activateWindow()
        return relative

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        import shutil
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if not path.is_file():
                continue
            if path.suffix.lower() in BINARY_PREVIEW:
                self.insert_figure([path])
            else:
                shutil.copy2(path, self.project / path.name)

    # ================================================================== compiling
    def _auto_toggled(self, on):
        doc_settings.update(latex_autocompile=bool(on))
        if on:
            self.compile()

    def _autocompile(self):
        if self.auto_button.isChecked():
            self.compile()

    def compile(self, clean: bool = False):
        main = self.main_file()
        if main is None:
            self.pdf.show_message('No .tex file with \\documentclass in this project.')
            return False
        if self.compiler.running:
            self._pending_compile = True
            return True
        self.save_all()
        return self.compiler.start(self.project, main, self.engine(), clean=clean)

    def _compile_started(self):
        self.compile_button.setText('Compiling…')
        self.compile_state.setText('Compiling with ' + self.compiler.engine + '…')

    def _compile_finished(self, ok, log, pdf, seconds):
        self.compile_button.setText('Recompile')
        main = self.main_file()
        self.summary = tex.parse_log(log, main.relative_to(self.project).as_posix() if main else 'main.tex')
        self._last_ok = ok
        self._last_log = log
        self.log_pane.show_result(self.summary, log, seconds, ok)
        errors = len(self.summary.errors)
        if errors or (not ok and not pdf):
            self.badge.setText(str(errors or '!'))
            self.badge.setObjectName('errorBadge')
            self.badge.show()
        elif self.summary.warnings:
            self.badge.setText(str(len(self.summary.warnings)))
            self.badge.setObjectName('warnBadge')
            self.badge.show()
        else:
            self.badge.hide()
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        if pdf:
            self.pdf.load(pdf)
        elif not ok:
            self.pdf.show_message('No PDF yet — see Logs.\n\n' + (log[:400] if 'No LaTeX installation' in log else ''))
            self.logs_button.setChecked(True)
        self.compile_state.setText(('Compiled' if ok else 'Compiled with errors' if pdf else 'Failed') +
                                   f' · {seconds:.1f} s · {self.compiler.engine}')
        self._apply_markers()
        waiters, self._compile_waiters = self._compile_waiters, []
        for loop in waiters:
            loop.quit()
        if self._pending_compile:
            self._pending_compile = False
            self.autocompile_timer.start() if self.auto_button.isChecked() else self.compile()

    def _apply_markers(self):
        if not self.current:
            return
        rel = Path(self.current).relative_to(self.project).as_posix() if Path(self.current).is_relative_to(self.project) else ''
        def mine(entry):
            name = entry.file.replace('\\', '/').lstrip('./')
            return name == rel or (name and rel.endswith(name)) or (not name and entry.line and rel == (
                self.main_file().relative_to(self.project).as_posix() if self.main_file() else ''))
        errors = {e.line: e.message for e in self.summary.errors if e.line and mine(e)}
        warnings = {e.line: e.message for e in self.summary.warnings if e.line and mine(e)}
        self.editor.set_markers(errors, warnings)

    def _jump_to(self, file, line):
        target = None
        if file:
            candidate = self.project / file.replace('\\', '/').lstrip('./')
            if candidate.is_file():
                target = candidate
        if target is None:
            target = Path(self.current) if self.current else self.main_file()
        if target is not None:
            self.open_file(str(target))
            self.editor.go_to_line(line)

    def _clean_build(self):
        import shutil
        shutil.rmtree(self.project / tex.BUILD_DIR, ignore_errors=True)
        self.statusBar().showMessage('Build files deleted', 3000)

    def compile_and_wait(self, timeout_ms: int = 120000) -> bool:
        loop = QEventLoop(self)
        self._compile_waiters.append(loop)
        if not self.compile():
            self._compile_waiters.remove(loop)
            return False
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        return bool(self._last_ok)

    # ================================================================== project actions
    def _open_project(self):
        folder = QFileDialog.getExistingDirectory(self, 'Open LaTeX project folder', str(doc_settings.latex_root()))
        if folder:
            if not latex_project.is_project(folder):
                MessageDialog.warning(self, 'Open project', 'This folder has no .tex file with \\documentclass.')
                return
            if self.hub:
                self.hub.open_latex(folder)
            else:
                self.set_project(folder)

    def _import_zip(self):
        archive, _ = QFileDialog.getOpenFileName(self, 'Import LaTeX project', str(Path.home()), 'Zip archives (*.zip)')
        if not archive:
            return
        try:
            folder = latex_project.import_zip(archive, doc_settings.latex_root())
        except latex_project.ProjectError as exc:
            MessageDialog.warning(self, 'Import', str(exc))
            return
        self.hub.open_latex(folder) if self.hub else self.set_project(folder)

    def _save_as(self):
        self.save_all()
        parent = QFileDialog.getExistingDirectory(self, 'Save the project as… (choose where)', str(self.project.parent))
        if not parent:
            return
        name, ok = TextInputDialog.getText(self, 'Save as', 'Project name:', text=self.project.name + ' copy')
        if not ok or not name.strip():
            return
        target = latex_project.copy_project(self.project, parent, name.strip())
        self.set_project(target)
        self.statusBar().showMessage(f'Saved as {target}', 5000)

    def _save_as_template(self):
        self.save_all()
        name, ok = TextInputDialog.getText(self, 'Save as template', 'Template name:', text=self.project.name)
        if not ok or not name.strip():
            return
        figures = MessageDialog.question(self, 'Save as template', 'Include the figures of the project?') \
            == MessageDialog.StandardButton.Yes
        try:
            target = templates.save_latex_template(self.project, name.strip(), include_figures=figures)
        except templates.TemplateError as exc:
            MessageDialog.warning(self, 'Save as template', str(exc))
            return
        MessageDialog.information(self, 'Template saved', f'“{name}” is now in the template list.\n\n{target}')

    def _download_zip(self):
        self.save_all()
        destination, _ = QFileDialog.getSaveFileName(self, 'Download source', str(Path.home() / f'{self.project.name}.zip'),
                                                     'Zip archive (*.zip)')
        if destination:
            latex_project.export_zip(self.project, destination)
            self.statusBar().showMessage(f'Saved {destination}', 4000)

    def _download_pdf(self):
        if not self.pdf.pdf_path or not Path(self.pdf.pdf_path).is_file():
            MessageDialog.information(self, 'Download PDF', 'Compile the project first.')
            return
        import shutil
        destination, _ = QFileDialog.getSaveFileName(self, 'Save PDF', str(self.project / f'{self.project.name}.pdf'),
                                                     'PDF (*.pdf)')
        if destination:
            shutil.copy2(self.pdf.pdf_path, destination)
            self.statusBar().showMessage(f'Saved {destination}', 4000)

    def _word_count(self):
        main = self.main_file()
        total = 0
        files = []
        for f in self.project.rglob('*.tex'):
            if tex.BUILD_DIR in f.parts:
                continue
            text = self.docs[str(f)].toPlainText() if str(f) in self.docs else f.read_text(encoding='utf8', errors='replace')
            if f != main and '\\begin{document}' not in text:
                text = '\\begin{document}' + text + '\\end{document}'
            n = tex.word_count(text)
            total += n
            files.append(f'{f.relative_to(self.project).as_posix()}: {n}')
        MessageDialog.information(self, 'Word count', f'About {total} words in the text\n\n' + '\n'.join(files[:30]))

    def _editor_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Editor settings')
        form = QFormLayout(dialog)
        size = QSpinBox()
        size.setRange(7, 28)
        size.setValue(self.editor.font().pointSize())
        delay = QSpinBox()
        delay.setRange(300, 10000)
        delay.setSingleStep(100)
        delay.setSuffix(' ms')
        delay.setValue(self.autocompile_timer.interval())
        wrap = QCheckBox('Wrap long lines')
        wrap.setChecked(self.editor.lineWrapMode() != self.editor.LineWrapMode.NoWrap)
        autosave = QCheckBox('Save automatically while typing')
        autosave.setChecked(bool(self.conf.get('latex_autosave', True)))
        form.addRow('Font size', size)
        form.addRow('Auto-compile after', delay)
        form.addRow('', wrap)
        form.addRow('', autosave)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
        form.addRow(box)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        f = self.editor.font()
        f.setPointSize(size.value())
        self.editor.setFont(f)
        self.editor.setLineWrapMode(self.editor.LineWrapMode.WidgetWidth if wrap.isChecked()
                                    else self.editor.LineWrapMode.NoWrap)
        self.autocompile_timer.setInterval(delay.value())
        self.conf = doc_settings.update(latex_font_size=size.value(), latex_autocompile_delay_ms=delay.value(),
                                        latex_wrap=wrap.isChecked(), latex_autosave=autosave.isChecked())

    # ================================================================== Overleaf
    def _update_overleaf_button(self):
        linked = overleaf.OverleafClient.linked_project(self.project)
        self.overleaf_button.setText('Overleaf ✓' if linked else 'Overleaf')
        self.overleaf_button.setToolTip('Linked to Overleaf project ' + linked if linked else
                                        'Push this project to Overleaf, or pull its changes')

    def _fill_overleaf_menu(self):
        m = self.overleaf_menu
        m.clear()
        linked = overleaf.OverleafClient.linked_project(self.project)
        if linked:
            m.addAction('Push to Overleaf', lambda: self._overleaf_run('push'))
            m.addAction('Pull changes from Overleaf', lambda: self._overleaf_run('pull'))
            m.addAction('Open on Overleaf', lambda: self._open_url(overleaf.project_page(linked, doc_settings.load())))
            m.addSeparator()
        m.addAction('Link to an Overleaf project…' if not linked else 'Link to another Overleaf project…',
                    self._overleaf_link)
        m.addAction('Upload a file to Overleaf…', self._overleaf_upload_file)
        m.addSeparator()
        m.addAction('Overleaf settings…', lambda: self.hub.open_settings() if self.hub else None)

    @staticmethod
    def _open_url(url):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _overleaf_link(self):
        from .send_dialog import choose_overleaf_project
        project_id = choose_overleaf_project(self)
        if not project_id:
            return
        client = overleaf.OverleafClient()
        try:
            client.link_project(self.project, project_id)
        except overleaf.OverleafError as exc:
            MessageDialog.warning(self, 'Overleaf', str(exc))
            return
        self._update_overleaf_button()
        answer = MessageDialog.question(self, 'Overleaf', 'Linked. Pull the Overleaf files first (choose No to '
                                                          'push this project to Overleaf now)?')
        self._overleaf_run('pull' if answer == MessageDialog.StandardButton.Yes else 'push')

    def _overleaf_run(self, what):
        self.save_all()
        client = overleaf.OverleafClient()
        project = self.project
        self.statusBar().showMessage('Overleaf: working…')
        self.overleaf_button.setEnabled(False)

        def work():
            return client.push_project(project) if what == 'push' else client.pull_project(project)

        def done(result, error):
            self.overleaf_button.setEnabled(True)
            if error:
                MessageDialog.warning(self, 'Overleaf', error)
                self.statusBar().showMessage('Overleaf: failed', 5000)
                return
            self.statusBar().showMessage('Overleaf: ' + str(result), 6000)
            if what == 'pull':
                for path, doc in list(self.docs.items()):
                    if Path(path).exists() and not doc.isModified():
                        text = Path(path).read_text(encoding='utf8', errors='replace')
                        if text != doc.toPlainText():
                            self._replace_document_text(doc, text)
                            doc.setModified(False)
                self.compile()
        run_in_thread(work, done, self)

    def _overleaf_upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Upload to Overleaf', str(self.project))
        if path and self.hub:
            self.hub.send_files_dialog([Path(path)], self, only='overleaf')

    # ================================================================== assistant
    def _ask_about(self, text):
        if self.hub is None:
            return
        rel = Path(self.current).relative_to(self.project).as_posix() if self.current else ''
        line = self.editor.textCursor().blockNumber() + 1
        self.hub.ask_assistant(f'In my LaTeX project “{self.project.name}”, file {rel}, near line {line}:\n\n'
                               f'```latex\n{text[:4000]}\n```\n\n', send=False, source=self)

    def _ask_fix(self):
        if self.hub is None:
            return
        lines = []
        for entry in self.summary.errors[:8]:
            snippet = ''
            target = self.project / entry.file if entry.file else self.main_file()
            if target and Path(target).is_file() and entry.line:
                source = (self.docs[str(target)].toPlainText() if str(target) in self.docs
                          else Path(target).read_text(encoding='utf8', errors='replace')).split('\n')
                a, b = max(0, entry.line - 4), min(len(source), entry.line + 3)
                snippet = '\n'.join(f'{n + 1:>4}| {source[n]}' for n in range(a, b))
            lines.append(f'- {entry.location()}: {entry.message}' + (f'\n```\n{snippet}\n```' if snippet else ''))
        if not lines:
            lines.append('No parsed error; end of the log:\n```\n' + getattr(self, '_last_log', '')[-2500:] + '\n```')
        prompt = (f'My LaTeX project “{self.project.name}” does not compile ({self.compiler.engine}). Please fix it '
                  f'in the editor (read the file first if needed) and tell me what was wrong.\n\n' + '\n'.join(lines))
        self.hub.ask_assistant(prompt, send=True, source=self)

    # ---------------------------------------------------------- AI actions (hub)
    def ai_state(self) -> str:
        rel = Path(self.current).relative_to(self.project).as_posix() if self.current else '?'
        line = self.editor.textCursor().blockNumber() + 1
        state = 'not compiled yet' if self._last_ok is None else \
            f'{len(self.summary.errors)} error(s), {len(self.summary.warnings)} warning(s)'
        return f'LaTeX project “{self.project.name}” ({self.project}), file {rel}, cursor line {line}, last compile: {state}'

    def ai_read(self) -> str:
        files = [f.relative_to(self.project).as_posix() for f in latex_project.project_files(self.project)]
        text = self.editor.toPlainText()
        numbered = '\n'.join(f'{i + 1:>4}| {line}' for i, line in enumerate(text.split('\n')))
        if len(numbered) > 45000:
            numbered = numbered[:45000] + '\n[…truncated; use read_file for the rest]'
        errors = '\n'.join(f'- {e.level} {e.location()}: {e.message}' for e in self.summary.entries[:25]) or '- none'
        main = self.main_file()
        return (f'Project folder: {self.project}\nMain document: {main.relative_to(self.project).as_posix() if main else "?"}\n'
                f'Compiler: {self.engine()}\nFiles: {", ".join(files[:200])}\n'
                f'Open file: {Path(self.current).relative_to(self.project).as_posix() if self.current else "?"} '
                f'(cursor line {self.editor.textCursor().blockNumber() + 1})\n'
                f'Last compile: {"none" if self._last_ok is None else ("ok" if self._last_ok else "failed")}\n'
                f'Errors and warnings:\n{errors}\n\nContent of the open file (line numbers are not part of it):\n{numbered}')

    def ai_read_file(self, relative: str) -> str:
        path = self._safe_path(relative)
        if str(path) in self.docs:
            return self.docs[str(path)].toPlainText()
        if not path.is_file():
            raise ValueError(f'No file {relative} in the project')
        return path.read_text(encoding='utf8', errors='replace')[:60000]

    def ai_insert(self, text: str, at: str = 'cursor') -> str:
        if not self.current:
            raise ValueError('No open file')
        cursor = self.editor.textCursor()
        doc = self.docs[self.current]
        if at == 'end':
            text = doc.toPlainText()
            end = text.rfind('\\end{document}')
            cursor.setPosition(to_qt(text, end) if end >= 0 else doc.characterCount() - 1)
        elif at.startswith('line:'):
            block = doc.findBlockByNumber(max(0, int(float(at.split(':', 1)[1])) - 1))
            cursor = QTextCursor(block)
        cursor.beginEditBlock()
        cursor.insertText(text if text.endswith('\n') else text + '\n')
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        return f'Inserted {len(text)} characters in {Path(self.current).name} at line {cursor.blockNumber() + 1}'

    def ai_replace(self, find: str, replace: str, every: bool = False, relative: str = '') -> str:
        if not find:
            raise ValueError('"find" is empty')
        path = str(self._safe_path(relative)) if relative else self.current
        if path not in self.docs:
            self.open_file(path)
        doc = self.docs.get(path)
        if doc is None:
            raise ValueError(f'Cannot open {relative}')
        text = doc.toPlainText()
        count = text.count(find)
        if count == 0:
            raise ValueError('The exact text was not found (read the file again and copy it verbatim)')
        new = text.replace(find, replace) if every else text.replace(find, replace, 1)
        self._replace_document_text(doc, new)
        return f'Replaced {count if every else 1} occurrence(s) in {Path(path).name}'

    def ai_write_file(self, relative: str, text: str) -> str:
        path = self._safe_path(relative)
        if str(path) in self.docs:
            self._replace_document_text(self.docs[str(path)], text)
            self._save(str(path))
        else:
            # created on disk only: the file the user is editing stays open (it appears in the file tree)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf8')
        return f'Wrote {relative} ({len(text)} characters); the open file is unchanged'

    def ai_open_file(self, relative: str) -> str:
        path = self._safe_path(relative)
        if not path.is_file():
            raise ValueError(f'No file {relative}')
        self.open_file(str(path))
        return f'Opened {relative}'

    def ai_compile(self) -> str:
        self.compile_and_wait()
        errors = '\n'.join(f'- {e.level} {e.location()}: {e.message}' for e in self.summary.entries[:25]) or '- none'
        return f'Compilation {"succeeded" if self._last_ok else "failed"}.\n{errors}'

    # ================================================================== window
    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and self.hub is not None:
            self.hub.note_active(self)
        super().changeEvent(event)

    def closeEvent(self, event):
        if not self._save_or_discard():
            event.ignore()
            return
        self.compiler.stop() if self.compiler.running else None
        QSettings('SPM Studio', 'Documents').setValue('latex_geometry', self.saveGeometry())
        if self.hub is not None:
            self.hub.unregister(self)
        event.accept()
