"""Renders the LaTeX text boxes of slides: LaTeX → PDF → image, cached; Matplotlib as fallback.

A box is rendered at 10 pt with ``standalone`` + ``varwidth`` (so text wraps at the box width) in a
background ``QProcess``; the PDF is rasterised by QtPdf at high resolution and kept in
``<cache>/formulas/<hash>.png`` so a presentation opens instantly the next time. Without TeX the
box falls back to Matplotlib's mathtext (formulas only, no packages).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QProcess, QProcessEnvironment, QSize, Qt
from PySide6.QtGui import QImage

from spm_studio.documents import tex

RENDER_SCALE = 6.0          # pixels per point of the 10 pt rendering (sharp up to ~3× zoom at 60 pt)
BASE_SIZE = 10.0
DEFAULT_PREAMBLE = '\\usepackage{amsmath,amssymb,bm}'


def _cache_dir() -> Path:
    from spm_studio.core import paths
    d = paths.cache_dir() / 'formulas'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _color(value: str) -> str:
    value = (value or '#000000').lstrip('#')
    if len(value) == 8:              # #AARRGGBB (Qt) → RRGGBB
        value = value[2:]
    return value.upper() if re.fullmatch(r'[0-9A-Fa-f]{6}', value) else '000000'


def tex_source(source: str, color: str, width_pt: float, align: str, preamble: str) -> str:
    alignment = {'center': '\\centering', 'right': '\\raggedleft'}.get(align, '\\raggedright')
    width = max(20.0, min(2000.0, width_pt))
    return ('\\documentclass[10pt,border=1pt,varwidth=%.1fpt]{standalone}\n' % width +
            '\\usepackage[T1]{fontenc}\n\\usepackage{xcolor}\n' + (preamble or DEFAULT_PREAMBLE) + '\n'
            '\\begin{document}\n\\color[HTML]{' + _color(color) + '}' + alignment + '\n' +
            source.strip() + '\n\\end{document}\n')


def make_key(source, color, width_pt, align, preamble) -> str:
    blob = json.dumps([source, _color(color), round(width_pt, 1), align, preamble or DEFAULT_PREAMBLE, 2])
    return hashlib.sha1(blob.encode('utf8')).hexdigest()[:20]


class FormulaRenderer(QObject):
    rendered = Signal(str)          # key (image or error now available)
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = FormulaRenderer()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.images = {}            # key -> (QImage, width_pt, height_pt)
        self.errors = {}            # key -> message
        self.queue = []
        self.jobs = {}
        self.process = None
        self.current = None

    def get(self, key):
        return self.images.get(key)

    def error(self, key):
        return self.errors.get(key)

    def forget_errors(self):
        self.errors.clear()

    def request(self, source, color='#000000', width_pt=400.0, align='center', preamble='') -> str:
        key = make_key(source, color, width_pt, align, preamble)
        if key in self.images or key in self.errors or key in self.jobs:
            return key
        png = _cache_dir() / f'{key}.png'
        meta = _cache_dir() / f'{key}.json'
        if png.is_file() and meta.is_file():
            image = QImage(str(png))
            try:
                w, h = json.loads(meta.read_text(encoding='utf8'))
            except (OSError, ValueError):
                w = h = 0
            if not image.isNull() and w and h:
                self.images[key] = (image, float(w), float(h))
                return key
        self.jobs[key] = (source, color, width_pt, align, preamble)
        self.queue.append(key)
        if self.process is None:
            self._next()
        return key

    def render_blocking(self, source, color='#000000', width_pt=400.0, align='center', preamble='', timeout=30000):
        """For exports: wait until the box is rendered (returns (QImage, w_pt, h_pt) or None)."""
        key = self.request(source, color, width_pt, align, preamble)
        from PySide6.QtCore import QEventLoop, QTimer
        if key not in self.images and key not in self.errors:
            loop = QEventLoop()
            self.rendered.connect(lambda k: loop.quit() if k == key else None)
            QTimer.singleShot(timeout, loop.quit)
            loop.exec()
        return self.images.get(key)

    # ------------------------------------------------------------------ engine
    def _next(self):
        if not self.queue:
            self.process = None
            self.current = None
            return
        key = self.queue.pop(0)
        self.current = key
        source, color, width_pt, align, preamble = self.jobs[key]
        engine = tex.which('pdflatex') or tex.which('lualatex') or tex.which('xelatex')
        folder = _cache_dir() / f'build_{key}'
        folder.mkdir(exist_ok=True)
        (folder / 'f.tex').write_text(tex_source(source, color, width_pt, align, preamble), encoding='utf8')
        if engine is None:
            self._fallback(key, 'No LaTeX installation found')
            return
        self.process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PATH', tex.search_path())
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(folder))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.finished.connect(lambda code, _s, k=key, f=folder: self._done(k, f, code))
        self.process.errorOccurred.connect(lambda err, k=key: self._failed_start(k, err))
        self.process.start(engine, ['-interaction=nonstopmode', '-halt-on-error', 'f.tex'])

    def _failed_start(self, key, error):
        if error == QProcess.ProcessError.FailedToStart and self.current == key:
            self._fallback(key, 'LaTeX could not be started')

    def _done(self, key, folder: Path, code):
        if self.current != key:
            return
        pdf = folder / 'f.pdf'
        if code == 0 and pdf.is_file():
            try:
                self._store(key, *self._rasterise(pdf))
            except Exception as exc:
                self._fail(key, f'Could not read the rendered formula: {exc}')
        else:
            message = 'LaTeX error'
            try:
                log = (folder / 'f.log').read_text(encoding='utf8', errors='replace')
                m = re.search(r'^! (.+)$', log, re.M)
                ctx = re.search(r'^l\.\d+ (.*)$', log, re.M)
                if m:
                    message = m.group(1).strip() + (f' — {ctx.group(1).strip()}' if ctx else '')
            except OSError:
                pass
            self._fail(key, message)
        self._cleanup(folder)
        self._next()

    @staticmethod
    def _cleanup(folder):
        import shutil
        shutil.rmtree(folder, ignore_errors=True)

    @staticmethod
    def _rasterise(pdf: Path):
        from PySide6.QtPdf import QPdfDocument
        document = QPdfDocument()
        document.load(str(pdf))
        if document.pageCount() < 1:
            raise ValueError('empty PDF')
        size = document.pagePointSize(0)
        image = document.render(0, QSize(max(1, int(size.width() * RENDER_SCALE)),
                                         max(1, int(size.height() * RENDER_SCALE))))
        document.close()
        return image, size.width(), size.height()

    def _store(self, key, image: QImage, w_pt: float, h_pt: float):
        self.images[key] = (image, float(w_pt), float(h_pt))
        self.jobs.pop(key, None)
        try:
            image.save(str(_cache_dir() / f'{key}.png'))
            (_cache_dir() / f'{key}.json').write_text(json.dumps([w_pt, h_pt]), encoding='utf8')
        except OSError:
            pass
        self.rendered.emit(key)

    def _fail(self, key, message):
        self.errors[key] = message
        self.jobs.pop(key, None)
        self.rendered.emit(key)

    def _fallback(self, key, reason):
        """Matplotlib mathtext: formulas without TeX (no packages, no environments)."""
        source, color, width_pt, align, _preamble = self.jobs[key]
        try:
            image, w, h = mathtext_image(source, color)
            self._store(key, image, w, h)
        except Exception as exc:
            self._fail(key, f'{reason}; Matplotlib fallback failed ({exc}). Install a TeX distribution '
                            f'(Settings › Documents shows how).')
        self._next()


def mathtext_image(source: str, color: str):
    import io
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    text = source.strip()
    text = re.sub(r'\\\[(.*?)\\\]', lambda m: '$' + m.group(1).strip() + '$', text, flags=re.S)
    text = re.sub(r'\$\$(.*?)\$\$', lambda m: '$' + m.group(1).strip() + '$', text, flags=re.S)
    text = re.sub(r'\\begin\{(equation|align|gather)\*?\}(.*?)\\end\{\1\*?\}',
                  lambda m: '$' + m.group(2).replace('&', '').replace('\\\\', ' ').strip() + '$', text, flags=re.S)
    text = text.replace('\\,', '\\ ')
    figure = Figure(figsize=(0.01, 0.01), dpi=72 * RENDER_SCALE)
    FigureCanvasAgg(figure)
    figure.text(0, 0, text, fontsize=BASE_SIZE, color='#' + _color(color))
    buffer = io.BytesIO()
    figure.savefig(buffer, format='png', dpi=72 * RENDER_SCALE, transparent=True, bbox_inches='tight',
                   pad_inches=0.02)
    image = QImage.fromData(buffer.getvalue(), 'PNG')
    if image.isNull():
        raise ValueError('empty image')
    return image, image.width() / RENDER_SCALE, image.height() / RENDER_SCALE
