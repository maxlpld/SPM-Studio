"""Parts of the LaTeX editor window: compiler, PDF preview, logs list, file tree, symbol palette."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from PySide6.QtCore import (Qt, QObject, Signal, QProcess, QProcessEnvironment, QTimer, QSortFilterProxyModel,
                            QPointF, QModelIndex)
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget, QTreeWidget,
                               QTreeWidgetItem, QPlainTextEdit, QTabWidget, QPushButton, QTreeView,
                               QFileSystemModel, QFrame, QGridLayout, QToolButton, QMenu, QWidgetAction)

from spm_studio.documents import tex
from spm_studio.documents.latex_project import IGNORED_NAMES, PROJECT_MARKER

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:                    # QtPdf is part of PySide6 ≥ 6.4 (Addons); keep the editor usable
    QPdfDocument = QPdfView = None


# ============================================================================ compiler
class Compiler(QObject):
    """Runs the engine (and BibTeX/Biber, extra passes) with QProcess, never blocking the window."""
    started = Signal()
    output = Signal(str)
    finished = Signal(bool, str, str, float)     # ok, log text, pdf path ('' if none), seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.queue = []
        self.project = None
        self.main = None
        self.engine = 'latexmk'
        self.passes = 0
        self.stdout = []
        self.t0 = 0.0
        self.running = False

    def _environment(self):
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PATH', tex.search_path())
        env.insert('max_print_line', '1000')         # long log lines: easier to parse
        env.insert('error_line', '254')
        env.insert('half_error_line', '238')
        return env

    def start(self, project: Path, main: Path, engine: str, *, clean: bool = False):
        if self.running:
            return False
        self.project, self.main = Path(project), Path(main)
        chosen = tex.best_engine(engine)
        if chosen is None:
            self.finished.emit(False, 'No LaTeX installation was found on this computer.\n\n' + tex.install_hint(),
                               '', 0.0)
            return False
        self.engine = chosen
        out = self.project / tex.BUILD_DIR
        if clean and out.is_dir():
            shutil.rmtree(out, ignore_errors=True)
        out.mkdir(exist_ok=True)
        # \include{chapters/x} needs the sub-folders in the output folder too
        for folder in {p.parent for p in self.project.rglob('*.tex')}:
            try:
                rel = folder.relative_to(self.project)
            except ValueError:
                continue
            if rel.parts and not any(part in IGNORED_NAMES for part in rel.parts):
                (out / rel).mkdir(parents=True, exist_ok=True)
        rel_main = self.main.relative_to(self.project) if self.main.is_relative_to(self.project) else Path(self.main.name)
        self.queue = tex.compile_steps(self.engine, rel_main)
        self.passes = 0
        self.stdout = []
        self.t0 = time.monotonic()
        self.running = True
        self.started.emit()
        self._next()
        return True

    def _next(self):
        command = self.queue.pop(0)
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(self.project))
        self.process.setProcessEnvironment(self._environment())
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._step_done)
        self.process.errorOccurred.connect(self._error)
        self.passes += 1
        self.process.start(command[0], command[1:])

    def _read(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode('utf8', errors='replace')
        self.stdout.append(text)
        self.output.emit(text)

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.running:
            self.running = False
            self.finished.emit(False, f'Could not start {self.engine}.\n\n{tex.install_hint()}', '', 0.0)

    def _log_text(self) -> str:
        log = self.project / tex.BUILD_DIR / (self.main.stem + '.log')
        try:
            return log.read_text(encoding='utf8', errors='replace')
        except OSError:
            return ''.join(self.stdout)

    def _step_done(self, code, _status):
        if not self.running:
            return
        self._read()
        log = self._log_text()
        if self.engine not in ('latexmk', 'tectonic') and not self.queue and self.passes < 5:
            if self.passes == 1:
                bib = tex.bibliography_step(self.main, tex.BUILD_DIR)
                if bib:
                    self.queue.append(bib)
                    self.queue += tex.compile_steps(self.engine, self.main.relative_to(self.project))
                    self.queue += tex.compile_steps(self.engine, self.main.relative_to(self.project))
            if not self.queue and tex.needs_rerun(log) and self.passes < 3:
                self.queue += tex.compile_steps(self.engine, self.main.relative_to(self.project))
        if self.queue:
            self._next()
            return
        self.running = False
        pdf = self.project / tex.BUILD_DIR / (self.main.stem + '.pdf')
        if self.engine == 'tectonic' and not log:
            log = ''.join(self.stdout)
        ok = code == 0 and pdf.is_file()
        full = log if log else ''.join(self.stdout)
        if self.engine == 'latexmk':
            full = full + '\n\n----- latexmk -----\n' + ''.join(self.stdout)[-6000:]
        self.finished.emit(ok, full, str(pdf) if pdf.is_file() else '', time.monotonic() - self.t0)

    def stop(self):
        self.queue = []
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.running = False
            self.process.kill()
            self.process.waitForFinished(2000)
            self.finished.emit(False, 'Compilation stopped.', '', time.monotonic() - self.t0)


# ========================================================================= PDF preview
class PdfPane(QFrame):
    """PDF of the last successful compilation; keeps the page and zoom when it is refreshed."""
    jumpToSource = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('pdfPane')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        bar.setSpacing(2)
        from spm_studio.shared.appearance import tool_button
        self.zoom_out = tool_button('', 'zoom-out', 'Zoom out', icon_only=True)
        self.zoom_in = tool_button('', 'zoom-in', 'Zoom in', icon_only=True)
        self.fit_width = tool_button('Width', 'fit', 'Fit the page width')
        self.fit_page = tool_button('Page', None, 'Show the whole page')
        self.page_label = QLabel('')
        self.page_label.setObjectName('hint')
        self.download = tool_button('', 'download', 'Save a copy of the PDF…', icon_only=True)
        self.external = tool_button('', 'float', 'Open the PDF in your PDF viewer', icon_only=True)
        for w in (self.zoom_out, self.zoom_in, self.fit_width, self.fit_page):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.page_label)
        bar.addWidget(self.external)
        bar.addWidget(self.download)
        layout.addLayout(bar)
        self.stack = QStackedWidget()
        self.message = QLabel('Press Recompile (Ctrl+Enter) to see the PDF.')
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setObjectName('hint')
        self.stack.addWidget(self.message)
        self.document = None
        self.view = None
        self._slot = 0
        self.pdf_path = ''
        if QPdfView is not None:
            self.document = QPdfDocument(self)
            self.view = QPdfView(self)
            self.view.setDocument(self.document)
            self.view.setPageMode(QPdfView.PageMode.MultiPage)
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.view.setPageSpacing(12)
            self.stack.addWidget(self.view)
            self.zoom_in.clicked.connect(lambda: self._zoom(1.2))
            self.zoom_out.clicked.connect(lambda: self._zoom(1 / 1.2))
            self.fit_width.clicked.connect(lambda: self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth))
            self.fit_page.clicked.connect(lambda: self.view.setZoomMode(QPdfView.ZoomMode.FitInView))
            self.view.verticalScrollBar().valueChanged.connect(lambda _v: self._update_page())
        else:
            self.message.setText('This Qt installation has no PDF viewer (QtPdf). Use “Open the PDF in your '
                                 'PDF viewer”.')
        layout.addWidget(self.stack, 1)

    def _zoom(self, factor):
        if self.view is None:
            return
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.2, min(6.0, self.view.zoomFactor() * factor)))

    def _update_page(self):
        if self.view is None or self.document is None or self.document.pageCount() == 0:
            self.page_label.setText('')
            return
        try:
            page = self.view.pageNavigator().currentPage() + 1
        except Exception:
            page = 1
        self.page_label.setText(f'{page} / {self.document.pageCount()}')

    def show_message(self, text: str):
        self.message.setText(text)
        if self.document is None or self.document.pageCount() == 0:
            self.stack.setCurrentWidget(self.message)

    def load(self, pdf: str):
        """Show ``pdf``. A copy is displayed so the next compilation can overwrite the original."""
        self.pdf_path = pdf
        if self.view is None:
            return
        source = Path(pdf)
        self._slot = 1 - self._slot
        copy = source.with_name(f'.preview_{self._slot}.pdf')
        try:
            shutil.copy2(source, copy)
        except OSError:
            copy = source
        bar = self.view.verticalScrollBar()
        hbar = self.view.horizontalScrollBar()
        keep = (bar.value(), hbar.value(), self.view.zoomMode(), self.view.zoomFactor())
        self.document.close()
        self.document.load(str(copy))
        self.stack.setCurrentWidget(self.view)

        def restore():
            mode = keep[2]
            self.view.setZoomMode(mode)
            if mode == QPdfView.ZoomMode.Custom:
                self.view.setZoomFactor(keep[3])
            bar.setValue(keep[0])
            hbar.setValue(keep[1])
            self._update_page()
        QTimer.singleShot(0, restore)
        QTimer.singleShot(60, restore)

    def page_count(self) -> int:
        return self.document.pageCount() if self.document is not None else 0


# =============================================================================== logs
class LogPane(QWidget):
    """Errors and warnings (click → line) and the raw log, like Overleaf's *Logs and output files*."""
    jump = Signal(str, int)
    askAssistant = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(6)
        head = QHBoxLayout()
        self.summary = QLabel('No compilation yet')
        self.summary.setObjectName('panelTitle')
        self.fix = QPushButton('Ask the assistant to fix')
        try:
            from spm_studio.shared.appearance import set_icon
            set_icon(self.fix, 'ai')
        except Exception:
            pass
        self.fix.clicked.connect(self.askAssistant)
        self.fix.setEnabled(False)
        head.addWidget(self.summary, 1)
        head.addWidget(self.fix)
        layout.addLayout(head)
        self.tabs = QTabWidget()
        self.list = QTreeWidget()
        self.list.setHeaderLabels(['', 'Message', 'Where'])
        self.list.setRootIsDecorated(False)
        self.list.setColumnWidth(0, 70)
        self.list.setColumnWidth(1, 380)
        self.list.itemActivated.connect(self._activate)
        self.list.itemClicked.connect(self._activate)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        from PySide6.QtGui import QFontDatabase
        self.raw.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.raw.setMaximumBlockCount(20000)
        self.tabs.addTab(self.list, 'Errors and warnings')
        self.tabs.addTab(self.raw, 'Raw log')
        layout.addWidget(self.tabs, 1)
        self.summary_data = None

    def show_result(self, summary, raw: str, seconds: float, ok: bool):
        from spm_studio.shared.appearance import colors
        t = colors()
        self.summary_data = summary
        self.list.clear()
        for entry in summary.entries:
            label = {'error': 'Error', 'warning': 'Warning', 'badbox': 'Box'}[entry.level]
            item = QTreeWidgetItem([label, entry.message + (f'   ⟶ {entry.context}' if entry.context else ''),
                                    entry.location()])
            item.setForeground(0, QBrush(QColor(t['danger'] if entry.level == 'error' else
                                                t['warning'] if entry.level == 'warning' else t['muted'])))
            item.setData(0, Qt.ItemDataRole.UserRole, (entry.file, entry.line))
            item.setToolTip(1, entry.message)
            self.list.addTopLevelItem(item)
        self.raw.setPlainText(raw)
        n_err, n_warn = len(summary.errors), len(summary.warnings)
        state = 'Compiled' if ok else 'Failed'
        self.summary.setText(f'{state} in {seconds:.1f} s · {n_err} error(s) · {n_warn} warning(s) · '
                             f'{len(summary.badboxes)} bad box(es)')
        self.fix.setEnabled(bool(n_err) or not ok)
        if n_err or not ok:
            self.tabs.setCurrentIndex(0 if summary.entries else 1)

    def _activate(self, item, _column=0):
        file, line = item.data(0, Qt.ItemDataRole.UserRole) or ('', 0)
        if line:
            self.jump.emit(file or '', int(line))


# ========================================================================== file tree
class _HideBuild(QSortFilterProxyModel):
    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        index = model.index(row, 0, parent)
        name = model.fileName(index)
        if name in IGNORED_NAMES or name == PROJECT_MARKER or name.startswith('.preview_') or name == '.keep':
            return False
        return True


class FileTree(QTreeView):
    """Files of the project (build folder and Git data hidden)."""
    fileActivated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = QFileSystemModel(self)
        self.model_.setReadOnly(False)
        self.proxy = _HideBuild(self)
        self.proxy.setSourceModel(self.model_)
        self.setModel(self.proxy)
        self.setHeaderHidden(True)
        for column in (1, 2, 3):
            self.hideColumn(column)
        self.setAnimated(True)
        self.setIndentation(14)
        self.setEditTriggers(QTreeView.EditTrigger.EditKeyPressed)
        self.activated.connect(self._activated)
        self.doubleClicked.connect(self._activated)
        self.root = None

    def set_root(self, folder: Path):
        self.root = Path(folder)
        source_root = self.model_.setRootPath(str(folder))
        self.setRootIndex(self.proxy.mapFromSource(source_root))
        for column in (1, 2, 3):
            self.hideColumn(column)

    def path_of(self, index) -> Path | None:
        if not index.isValid():
            return None
        return Path(self.model_.filePath(self.proxy.mapToSource(index)))

    def selected_path(self) -> Path | None:
        return self.path_of(self.currentIndex())

    def _activated(self, index):
        path = self.path_of(index)
        if path is not None and path.is_file():
            self.fileActivated.emit(str(path))

    def select_path(self, path):
        index = self.model_.index(str(path))
        if index.isValid():
            self.setCurrentIndex(self.proxy.mapFromSource(index))


# ===================================================================== symbol palette
SYMBOLS = {
    'Greek': r'\alpha \beta \gamma \delta \epsilon \varepsilon \zeta \eta \theta \kappa \lambda \mu \nu \xi \pi '
             r'\rho \sigma \tau \phi \varphi \chi \psi \omega \Gamma \Delta \Theta \Lambda \Xi \Pi \Sigma \Phi \Psi '
             r'\Omega',
    'Operators': r'\pm \mp \times \div \cdot \circ \otimes \oplus \nabla \partial \sum \prod \int \oint \iint '
                 r'\sqrt{} \frac{}{} \infty \propto \hbar \ell \Re \Im',
    'Relations': r'\leq \geq \neq \approx \sim \simeq \equiv \ll \gg \in \notin \subset \subseteq \cup \cap '
                 r'\forall \exists',
    'Arrows': r'\to \leftarrow \rightarrow \Rightarrow \Leftarrow \leftrightarrow \Leftrightarrow \mapsto '
              r'\uparrow \downarrow \longrightarrow',
    'Accents': r'\hat{} \bar{} \vec{} \tilde{} \dot{} \ddot{} \overline{} \mathbf{} \mathrm{} \mathcal{} \mathbb{}',
    'Units': r'\SI{}{} \si{} \num{} \angstrom \nano\metre \micro\metre \kelvin \volt \milli\volt \electronvolt '
             r'\pico\ampere \nano\ampere \hertz \tesla \degree',
}
GLYPHS = {'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'epsilon': 'ϵ', 'varepsilon': 'ε', 'zeta': 'ζ',
          'eta': 'η', 'theta': 'θ', 'kappa': 'κ', 'lambda': 'λ', 'mu': 'μ', 'nu': 'ν', 'xi': 'ξ', 'pi': 'π',
          'rho': 'ρ', 'sigma': 'σ', 'tau': 'τ', 'phi': 'ϕ', 'varphi': 'φ', 'chi': 'χ', 'psi': 'ψ', 'omega': 'ω',
          'Gamma': 'Γ', 'Delta': 'Δ', 'Theta': 'Θ', 'Lambda': 'Λ', 'Xi': 'Ξ', 'Pi': 'Π', 'Sigma': 'Σ', 'Phi': 'Φ',
          'Psi': 'Ψ', 'Omega': 'Ω', 'pm': '±', 'mp': '∓', 'times': '×', 'div': '÷', 'cdot': '·', 'circ': '∘',
          'otimes': '⊗', 'oplus': '⊕', 'nabla': '∇', 'partial': '∂', 'sum': '∑', 'prod': '∏', 'int': '∫',
          'oint': '∮', 'iint': '∬', 'sqrt': '√', 'frac': '⁄', 'infty': '∞', 'propto': '∝', 'hbar': 'ℏ', 'ell': 'ℓ',
          'Re': 'ℜ', 'Im': 'ℑ', 'leq': '≤', 'geq': '≥', 'neq': '≠', 'approx': '≈', 'sim': '∼', 'simeq': '≃',
          'equiv': '≡', 'll': '≪', 'gg': '≫', 'in': '∈', 'notin': '∉', 'subset': '⊂', 'subseteq': '⊆', 'cup': '∪',
          'cap': '∩', 'forall': '∀', 'exists': '∃', 'to': '→', 'leftarrow': '←', 'rightarrow': '→',
          'Rightarrow': '⇒', 'Leftarrow': '⇐', 'leftrightarrow': '↔', 'Leftrightarrow': '⇔', 'mapsto': '↦',
          'uparrow': '↑', 'downarrow': '↓', 'longrightarrow': '⟶', 'hat': 'â', 'bar': 'ā', 'vec': 'v⃗',
          'tilde': 'ã', 'dot': 'ȧ', 'ddot': 'ä', 'overline': 'x̅', 'mathbf': 'B', 'mathrm': 'R', 'mathcal': '𝒞',
          'mathbb': 'ℝ', 'SI': 'SI', 'si': 'si', 'num': '1.0', 'angstrom': 'Å', 'kelvin': 'K', 'volt': 'V',
          'electronvolt': 'eV', 'hertz': 'Hz', 'tesla': 'T', 'degree': '°'}


def symbol_menu(parent, insert) -> QMenu:
    """Menu with one grid of symbol buttons per group; ``insert(latex)`` is called on click."""
    menu = QMenu(parent)
    for group, symbols in SYMBOLS.items():
        sub = menu.addMenu(group)
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(2)
        for index, command in enumerate(symbols.split()):
            name = command.lstrip('\\').split('{')[0].split('\\')[0]
            b = QToolButton()
            b.setText(GLYPHS.get(name, name[:4]))
            b.setToolTip(command)
            b.setFixedSize(34, 30)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, c=command, m=menu: (insert(c), m.close()))
            grid.addWidget(b, index // 8, index % 8)
        action = QWidgetAction(sub)
        action.setDefaultWidget(grid_widget)
        sub.addAction(action)
    return menu
