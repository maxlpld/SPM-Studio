"""Shared Qt pieces of the LaTeX and presentation editors: header bar, worker thread, conversions."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSize, QSizeF, QRectF, QUrl
from PySide6.QtGui import QImage, QPainter, QColor, QPixmap, QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget, QVBoxLayout


class Worker(QThread):
    """Runs ``fn()`` off the GUI thread; ``finished_with(result, error_text)`` comes back on the GUI thread."""
    finished_with = Signal(object, str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as exc:              # shown to the user as a plain message
            self.finished_with.emit(None, str(exc) or type(exc).__name__)
            return
        self.finished_with.emit(result, '')


_WORKERS = set()


def run_in_thread(fn, on_done, parent=None):
    """Start ``fn`` in a thread; ``on_done(result, error)`` runs on the GUI thread."""
    worker = Worker(fn, parent)
    _WORKERS.add(worker)

    def done(result, error):
        _WORKERS.discard(worker)
        on_done(result, error)
        worker.deleteLater()
    worker.finished_with.connect(done, Qt.ConnectionType.QueuedConnection)
    worker.start()
    return worker


def brand_mark() -> QLabel:
    label = QLabel()
    label.setObjectName('BrandMark')
    label.setFixedSize(22, 22)
    label.setScaledContents(True)
    try:
        from spm_studio.shared.appearance import colors, is_dark
        from spm_studio.core import paths
        name = 'spm-studio-mark-dark.png' if is_dark(colors()) else 'spm-studio-mark-light.png'
        for base in (Path(__file__).resolve().parents[2] / 'resources', paths.bundled_studio_root() / 'assets'):
            if (base / name).is_file():
                label.setPixmap(QPixmap(str(base / name)))
                break
            if (base / 'spm-studio.png').is_file():
                label.setPixmap(QPixmap(str(base / 'spm-studio.png')))
                break
    except Exception:
        pass
    return label


class HeaderBar(QFrame):
    """Top bar of an editor window, in the style of the main window's header."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.setObjectName('docHeader')
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(12, 6, 12, 6)
        self.row.setSpacing(6)
        self.row.addWidget(brand_mark())
        text = QVBoxLayout()
        text.setSpacing(0)
        self.kind = QLabel(kind.upper())
        self.kind.setObjectName('docKind')
        self.title = QLabel('')
        self.title.setObjectName('docTitle')
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.addWidget(self.kind)
        text.addWidget(self.title)
        holder = QWidget()
        holder.setLayout(text)
        self.row.addWidget(holder)
        self.row.addSpacing(10)

    def add(self, widget):
        self.row.addWidget(widget)
        return widget

    def stretch(self):
        self.row.addStretch(1)


class Ribbon(QFrame):
    """Formatting / insert toolbar under the header (one row, scrolls when the window is narrow)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('docRibbon')
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(44)
        inner = QWidget()
        self.row = QHBoxLayout(inner)
        self.row.setContentsMargins(10, 4, 10, 4)
        self.row.setSpacing(2)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def add(self, widget):
        self.row.addWidget(widget)
        return widget

    def separator(self):
        from spm_studio.shared.appearance import separator
        self.row.addWidget(separator())

    def stretch(self):
        self.row.addStretch(1)


def button(text, icon_name=None, tooltip='', **kw):
    from spm_studio.shared.appearance import tool_button
    return tool_button(text, icon_name, tooltip, **kw)


def open_path(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# ------------------------------------------------------------------------ conversions
def svg_to_pdf(svg, pdf) -> Path:
    """Vector conversion (pdfLaTeX cannot include SVG): QSvgRenderer → QPdfWriter."""
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtGui import QPdfWriter, QPageSize, QPageLayout
    from PySide6.QtCore import QMarginsF
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise ValueError(f'Unreadable SVG: {Path(svg).name}')
    box = renderer.viewBoxF()
    w, h = (box.width(), box.height()) if box.width() > 0 and box.height() > 0 else \
        (float(renderer.defaultSize().width()), float(renderer.defaultSize().height()))
    # SVG user units are CSS px (1/96 in); PDF pages are in points (1/72 in).
    wpt, hpt = max(1.0, w * 0.75), max(1.0, h * 0.75)
    writer = QPdfWriter(str(pdf))
    writer.setResolution(1200)
    writer.setPageSize(QPageSize(QSizeF(wpt, hpt), QPageSize.Unit.Point, 'figure', QPageSize.SizeMatchPolicy.ExactMatch))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
    writer.setCreator('SPM Studio')
    painter = QPainter(writer)
    try:
        renderer.render(painter, QRectF(0, 0, writer.width(), writer.height()))
    finally:
        painter.end()
    return Path(pdf)


def svg_to_image(svg, long_side=2400) -> QImage:
    from PySide6.QtSvg import QSvgRenderer
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise ValueError(f'Unreadable SVG: {Path(svg).name}')
    box = renderer.viewBoxF()
    w, h = (box.width(), box.height()) if box.width() > 0 else (1000.0, 1000.0)
    scale = long_side / max(w, h)
    image = QImage(max(1, int(w * scale)), max(1, int(h * scale)), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return image


def pdf_to_image(pdf, long_side=2400, page=0) -> QImage:
    from PySide6.QtPdf import QPdfDocument
    document = QPdfDocument()
    error = document.load(str(pdf))
    if document.pageCount() < 1:
        raise ValueError(f'Unreadable PDF: {Path(pdf).name} ({error})')
    size = document.pagePointSize(page)
    scale = long_side / max(size.width(), size.height(), 1.0)
    image = document.render(page, QSize(max(1, int(size.width() * scale)), max(1, int(size.height() * scale))))
    document.close()
    return image


def figure_for_latex(files, workdir: Path) -> Path:
    """The file to ``\\includegraphics``: PDF, PNG or JPG; an SVG is converted to PDF (vector)."""
    from spm_studio.documents import latex_project
    files = [Path(f) for f in files if Path(f).is_file() and not str(f).endswith('.json')]
    for suffix in ('.pdf', '.png', '.jpg', '.jpeg'):
        for f in files:
            if f.suffix.lower() == suffix:
                return f
    for f in files:
        if f.suffix.lower() == '.svg':
            workdir.mkdir(parents=True, exist_ok=True)
            return svg_to_pdf(f, workdir / (f.stem + '.pdf'))
    chosen = latex_project.choose_figure(files)
    if chosen is None:
        raise ValueError('No figure file to insert')
    return chosen


def figure_for_slides(files, workdir: Path) -> Path:
    """The file shown on a slide: SVG (sharp at any zoom), else PNG/JPG; a PDF becomes a PNG."""
    files = [Path(f) for f in files if Path(f).is_file() and not str(f).endswith('.json')]
    for suffix in ('.svg', '.png', '.jpg', '.jpeg', '.gif'):
        for f in files:
            if f.suffix.lower() == suffix:
                return f
    for f in files:
        if f.suffix.lower() == '.pdf':
            workdir.mkdir(parents=True, exist_ok=True)
            out = workdir / (f.stem + '.png')
            pdf_to_image(f, 2400).save(str(out))
            return out
    if not files:
        raise ValueError('No figure file to add')
    return files[0]


def color_button(color: str, tooltip: str, on_pick, allow_none: bool = False):
    """A swatch button that opens the colour selector (no typed colour codes needed)."""
    from PySide6.QtWidgets import QToolButton, QColorDialog
    b = QToolButton()
    b.setToolTip(tooltip)
    b.setFixedSize(QSize(30, 26))
    b.setProperty('swatch', True)

    def paint(value):
        c = QColor(value) if value else QColor(0, 0, 0, 0)
        b.setProperty('color', value or '')
        if not value:
            b.setStyleSheet('QToolButton { border: 1px dashed #888; border-radius: 5px; }')
            b.setText('∅')
        else:
            b.setText('')
            b.setStyleSheet(f'QToolButton {{ background: {c.name()}; border: 1px solid #777; border-radius: 5px; }}')

    def pick():
        start = QColor(b.property('color') or '#000000')
        chosen = QColorDialog.getColor(start, b.window(), tooltip, QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if chosen.isValid():
            value = chosen.name(QColor.NameFormat.HexArgb) if chosen.alpha() < 255 else chosen.name()
            paint(value)
            on_pick(value)
    b.clicked.connect(pick)
    if allow_none:
        b.setToolTip(tooltip + ' — right-click: no colour')
        b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def clear(_pos):
            paint('')
            on_pick('')
        b.customContextMenuRequested.connect(clear)
    b.set_color = paint
    paint(color)
    return b
