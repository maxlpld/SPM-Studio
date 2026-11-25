"""Compare results (v0.0.20 redesign).

What it is for: every analysis run (Lattice, Molecule placement, Histogram, …) saves the numbers it measured.
This window puts the same quantity measured on different scans side by side — a lattice constant on ten scans, a
step height before and after annealing — as a table and a chart, with the mean and the spread.

1. Choose a quantity on the left (grouped by tool; the number of scans that have it is shown).
2. The table lists its value on each scan (latest run per scan by default); untick a row to leave it out.
3. The chart and the summary (n, mean, standard deviation, min–max) follow the ticked rows.
4. Export the table (CSV), save the chart (SVG / PDF / PNG), open the run folder or show the scan.

No interpolation and no unit conversion: values with different declared units are never mixed in one chart.
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QSplitter,
                               QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from spm_studio.shared import ResearchStore
from spm_studio.shared.dialogs import MessageDialog as QMessageBox
from spm_studio.shared.ui_strings import ui_label

INDEX_COLUMNS = {'index', 'idx', 'row', 'row_index', 'id', 'line', 'line_index', 'channel_index', 'number', 'n',
                 'i', 'j', 'k', 'frame', 'pass'}
LABEL_KEYS = ('type', 'polarity', 'name', 'label', 'feature', 'line', 'direction', 'channel', 'site')
COLUMNS = ('Use', 'Scan', 'Detail', 'Value', 'Unit', 'Tool', 'Date')


def unit_from_key(key: str) -> str:
    m = re.search(r'[\(\[]\s*([^\)\]]{1,12})\s*[\)\]]\s*$', key or '')
    return m.group(1).strip() if m else ''


def row_label(row: dict, key: str) -> str:
    row = row or {}
    for name in LABEL_KEYS:
        value = row.get(name)
        if value not in (None, '') and name != key:
            return f'{ui_label(name)} {value}' if isinstance(value, (int, float)) else str(value)
    for name, value in row.items():
        if isinstance(value, str) and name not in ('unit', key) and len(value) <= 40:
            return value
    return ''


def collect(runs, *, latest_only=True, paths=None):
    """Group the measurements of ``runs`` by (tool, table, quantity, unit).

    Returns ``{group_key: [entry, …]}`` where an entry is a dict with scan, path, detail, value, unit, tool,
    created, run_id, run_folder, uncertainty.
    """
    chosen = []
    seen = set()
    # preferred first, then newest first
    ordered = sorted(runs, key=lambda r: (0 if r.get('preferred') else 1, _neg(r.get('created_at', ''))))
    for run in ordered:
        if run.get('status') not in (None, 'completed', 'stale', 'synthetic'):
            continue
        source = str(run.get('source_path', ''))
        if paths is not None and source not in paths:
            continue
        ident = (run.get('scan_id') or source, run.get('module_id'))
        if latest_only:
            if ident in seen:
                continue
            seen.add(ident)
        chosen.append(run)
    groups: dict[tuple, list] = {}
    for run in chosen:
        for m in run.get('measurements', []) or []:
            key = str(m.get('key', ''))
            if not key or key.strip().lower() in INDEX_COLUMNS:
                continue
            value = m.get('value')
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                continue
            unit = str(m.get('unit') or unit_from_key(key) or '')
            group = (run.get('module_id', ''), str(m.get('table', '')), key, unit)
            groups.setdefault(group, []).append({
                'scan': Path(run.get('source_path', '')).stem, 'path': run.get('source_path', ''),
                'detail': row_label(m.get('row'), key), 'value': float(value), 'unit': unit,
                'tool': run.get('module_id', ''), 'created': str(run.get('created_at', ''))[:16].replace('T', ' '),
                'run_id': run.get('result_id', ''), 'run_folder': run.get('run_folder', ''),
                'uncertainty': m.get('uncertainty'), 'stale': run.get('status') == 'stale'})
    return groups


def _neg(text: str) -> str:
    """Sort key for 'newest first' on ISO dates."""
    return ''.join(chr(0x10FFFF - ord(c)) for c in text)


def stats(values):
    values = [float(v) for v in values]
    n = len(values)
    if not n:
        return {'n': 0}
    mean = sum(values) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    return {'n': n, 'mean': mean, 'std': std, 'min': min(values), 'max': max(values)}


def fmt(value: float) -> str:
    return f'{value:.4g}'


# ---------------------------------------------------------------------- chart
class ValueChart(QWidget):
    """Value per scan, with the mean (dashed) and ± one standard deviation (band)."""
    pointClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.points: list[tuple[str, float]] = []
        self.unit = ''
        self.title = ''
        self._hit = []
        self.setMouseTracking(True)

    def set_data(self, points, unit='', title=''):
        self.points = list(points)
        self.unit = unit
        self.title = title
        self.update()

    def sizeHint(self):
        return QSize(560, 280)

    def mousePressEvent(self, event):
        for index, rect in self._hit:
            if rect.contains(event.position()):
                self.pointClicked.emit(index)
                return

    def mouseMoveEvent(self, event):
        for index, rect in self._hit:
            if rect.contains(event.position()):
                name, value = self.points[index]
                self.setToolTip(f'{name}: {fmt(value)} {self.unit}'.strip())
                return
        self.setToolTip('')

    def paint_to(self, painter: QPainter, rect: QRectF, colors: dict, *, export=False):
        fg = QColor(colors.get('foreground', '#202020'))
        muted = QColor(colors.get('muted', '#707070'))
        border = QColor(colors.get('border', '#d0d0d0'))
        accent = QColor(colors.get('accent', '#ff6b2c'))
        bg = QColor(colors.get('surface', '#ffffff'))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not export:
            painter.fillRect(rect, bg)
        font = QFont(painter.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() * 0.92))
        painter.setFont(font)
        fm = painter.fontMetrics()
        self._hit = []
        if not self.points:
            painter.setPen(muted)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, 'Tick at least one row to see the chart')
            return
        values = [v for _, v in self.points]
        s = stats(values)
        lo, hi = min(values), max(values)
        if s['n'] > 1:
            lo, hi = min(lo, s['mean'] - s['std']), max(hi, s['mean'] + s['std'])
        if hi == lo:
            pad = abs(hi) * 0.05 or 1.0
            lo, hi = lo - pad, hi + pad
        pad = (hi - lo) * 0.08
        lo, hi = lo - pad, hi + pad
        ticks = _nice_ticks(lo, hi)
        left = rect.left() + max(fm.horizontalAdvance(fmt(t)) for t in ticks) + 18
        names = [n for n, _ in self.points]
        rotate = len(names) > 4
        label_h = (min(140, max(fm.horizontalAdvance(n[:24]) for n in names) * 0.75 + 12) if rotate
                   else fm.height() + 10)
        top = rect.top() + (fm.height() + 10 if self.title else 10)
        bottom = rect.bottom() - label_h - 6
        right = rect.right() - 14
        plot = QRectF(left, top, max(10, right - left), max(10, bottom - top))
        y = lambda v: plot.bottom() - (v - lo) / (hi - lo) * plot.height()
        if self.title:
            painter.setPen(fg)
            painter.drawText(QRectF(rect.left(), rect.top() + 2, rect.width(), fm.height() + 4),
                             Qt.AlignmentFlag.AlignHCenter, self.title)
        # grid + y labels
        for t in ticks:
            yy = y(t)
            painter.setPen(QPen(border, 1, Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(plot.left(), yy), QPointF(plot.right(), yy))
            painter.setPen(muted)
            painter.drawText(QRectF(rect.left(), yy - fm.height() / 2, left - rect.left() - 8, fm.height()),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, fmt(t))
        if self.unit:
            painter.save()
            painter.setPen(muted)
            painter.translate(rect.left() + 2, plot.center().y())
            painter.rotate(-90)
            painter.drawText(QRectF(-plot.height() / 2, -2, plot.height(), fm.height()),
                             Qt.AlignmentFlag.AlignCenter, self.unit)
            painter.restore()
        # mean ± std
        if s['n'] > 1:
            band = QRectF(plot.left(), y(s['mean'] + s['std']), plot.width(),
                          y(s['mean'] - s['std']) - y(s['mean'] + s['std']))
            soft = QColor(accent)
            soft.setAlpha(36)
            painter.fillRect(band, soft)
            painter.setPen(QPen(accent, 1.4, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(plot.left(), y(s['mean'])), QPointF(plot.right(), y(s['mean'])))
        # points
        n = len(self.points)
        step = plot.width() / n
        path = QPainterPath()
        for i, (name, value) in enumerate(self.points):
            xx = plot.left() + step * (i + 0.5)
            yy = y(value)
            path.moveTo(xx, yy) if i == 0 else path.lineTo(xx, yy)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 110), 1.2))
        painter.drawPath(path)
        painter.setPen(QPen(fg, 1.2))
        painter.setBrush(accent)
        for i, (name, value) in enumerate(self.points):
            xx = plot.left() + step * (i + 0.5)
            yy = y(value)
            painter.drawEllipse(QPointF(xx, yy), 4.2, 4.2)
            self._hit.append((i, QRectF(xx - 7, yy - 7, 14, 14)))
            painter.save()
            painter.setPen(muted)
            label = name if len(name) <= 24 else name[:11] + '…' + name[-11:]
            if rotate:
                painter.translate(xx, plot.bottom() + 6)
                painter.rotate(-40)
                painter.drawText(QRectF(-fm.horizontalAdvance(label) - 2, -fm.height() / 2,
                                        fm.horizontalAdvance(label) + 2, fm.height()),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            else:
                painter.drawText(QRectF(xx - step / 2, plot.bottom() + 4, step, fm.height() + 4),
                                 Qt.AlignmentFlag.AlignHCenter, label)
            painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(border, 1))
        painter.drawRect(plot)

    def paintEvent(self, _event):
        from spm_studio.shared.appearance import colors
        painter = QPainter(self)
        self.paint_to(painter, QRectF(self.rect()), colors(self))
        painter.end()


def _nice_ticks(lo, hi, count=5):
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / count
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=mag * 10)
    start = math.ceil(lo / step) * step
    ticks = []
    t = start
    while t <= hi + step * 1e-9 and len(ticks) < 12:
        ticks.append(round(t, 12))
        t += step
    return ticks or [lo, hi]


# ---------------------------------------------------------------------- window
class CompareDialog(QDialog):
    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.setObjectName('CompareResultsV0020')
        self.setWindowTitle('Compare results')
        self.resize(1180, 720)
        self.setMinimumSize(760, 480)
        self.store = store or ResearchStore()
        self.window_ = parent
        self.runs = self.store.runs()
        self.groups = {}
        self._entries = []
        root = QVBoxLayout(self)
        root.setSpacing(10)
        title = QLabel('Compare results')
        title.setObjectName('heading')
        root.addWidget(title)
        intro = QLabel('The numbers measured by the analysis tools, side by side across scans. Choose a quantity on '
                       'the left: its value on each scan is listed and drawn, with the mean and the spread.')
        intro.setObjectName('hint')
        intro.setWordWrap(True)
        root.addWidget(intro)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.tool = QComboBox()
        self.tool.setObjectName('CompareToolFilter')
        self.tool.addItem('All tools', '')
        for module in sorted({r.get('module_id', '') for r in self.runs if r.get('measurements')}):
            self.tool.addItem(ui_label(module), module)
        self.scope = QComboBox()
        self.scope.setObjectName('CompareScope')
        self.scope.addItem('Scans of this project', 'project')
        self.scope.addItem('All scans ever analysed', 'all')
        listed = set(getattr(parent, '_source_paths', []) or [])
        if not listed:
            self.scope.setCurrentIndex(1)
        self.latest = QCheckBox('Latest run per scan')
        self.latest.setToolTip('Use only the preferred (or newest) run of each tool on each scan. Untick to also '
                               'compare older runs of the same scan.')
        self.latest.setChecked(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search quantities')
        self.search.setClearButtonEnabled(True)
        for label, widget in (('Tool', self.tool), ('Scans', self.scope)):
            text = QLabel(label)
            text.setObjectName('muted')
            filters.addWidget(text)
            filters.addWidget(widget)
        filters.addWidget(self.latest)
        filters.addStretch(1)
        filters.addWidget(self.search)
        root.addLayout(filters)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        head = QLabel('Quantities')
        head.setObjectName('sectionTitle')
        lv.addWidget(head)
        self.quantities = QListWidget()
        self.quantities.setObjectName('CompareQuantities')
        self.quantities.setMinimumWidth(260)
        lv.addWidget(self.quantities, 1)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        self.caption = QLabel('')
        self.caption.setObjectName('sectionTitle')
        rv.addWidget(self.caption)
        inner = QSplitter(Qt.Orientation.Vertical)
        inner.setChildrenCollapsible(False)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName('CompareTable')
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        self.table.itemChanged.connect(self._row_toggled)
        self.table.itemDoubleClicked.connect(lambda _item: self.show_scan())
        inner.addWidget(self.table)
        chart_box = QFrame()
        chart_box.setObjectName('card')
        cv = QVBoxLayout(chart_box)
        cv.setContentsMargins(6, 6, 6, 6)
        self.chart = ValueChart()
        self.chart.setObjectName('CompareChart')
        self.chart.pointClicked.connect(self._select_point)
        cv.addWidget(self.chart, 1)
        self.summary = QLabel('')
        self.summary.setObjectName('CompareSummary')
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cv.addWidget(self.summary)
        inner.addWidget(chart_box)
        inner.setSizes([300, 320])
        rv.addWidget(inner, 1)
        split.addWidget(right)
        split.setSizes([300, 860])
        root.addWidget(split, 1)

        self.empty = QLabel('<b>No results to compare yet.</b><br><br>1. Open a scan and choose an analysis tool in '
                            '<i>Tools</i> (for example Lattice measurements).<br>2. Press <i>Run</i> in the '
                            'Analysis panel; repeat on a few scans.<br>3. Come back here: the numbers each run '
                            'measured appear on the left, ready to compare.')
        self.empty.setObjectName('CompareEmpty')
        self.empty.setTextFormat(Qt.TextFormat.RichText)
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty, 1)

        footer = QHBoxLayout()
        self.buttons = {}
        from spm_studio.shared.appearance import tool_button
        for key, text, icon_name, tip, slot in (
                ('csv', 'Export table', 'export', 'Save the ticked rows as CSV', self.export_csv),
                ('chart', 'Save chart', 'save', 'Save the chart as SVG, PDF or PNG', self.save_chart),
                ('folder', 'Open run folder', 'folder', 'Open the output folder of the selected run', self.open_run),
                ('scan', 'Show scan', 'scan', 'Show the selected scan in the main window', self.show_scan)):
            b = tool_button(text, icon_name, tip, flat=False)
            b.setObjectName('Compare' + key.capitalize() + 'Button')
            b.clicked.connect(slot)
            footer.addWidget(b)
            self.buttons[key] = b
        footer.addStretch(1)
        close = QToolButton()
        close.setText('Close')
        close.clicked.connect(self.close)
        footer.addWidget(close)
        root.addLayout(footer)

        self.tool.currentIndexChanged.connect(self.refresh)
        self.scope.currentIndexChanged.connect(self.refresh)
        self.latest.toggled.connect(self.refresh)
        self.search.textChanged.connect(self._filter_quantities)
        self.quantities.currentItemChanged.connect(lambda *_: self._show_group())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self._split = split
        self.refresh()
        if not self.groups and self.scope.currentData() == 'project' and self.runs:
            self.scope.setCurrentIndex(1)       # nothing for this project yet: show every analysed scan

    # ------------------------------------------------------------------ data
    def refresh(self, *_):
        tool = self.tool.currentData() or ''
        runs = [r for r in self.runs if not tool or r.get('module_id') == tool]
        paths = None
        if self.scope.currentData() == 'project':
            paths = set(getattr(self.window_, '_source_paths', []) or [])
        self.groups = collect(runs, latest_only=self.latest.isChecked(), paths=paths)
        previous = self.quantities.currentItem().data(Qt.ItemDataRole.UserRole) if self.quantities.currentItem() else None
        self.quantities.blockSignals(True)
        self.quantities.clear()
        ordered = sorted(self.groups.items(), key=lambda kv: (ui_label(kv[0][0]), -len({e['path'] for e in kv[1]}),
                                                               ui_label(kv[0][2])))
        current_tool = None
        for group, entries in ordered:
            module, table, key, unit = group
            if module != current_tool and not (self.tool.currentData()):
                head = QListWidgetItem(ui_label(module))
                head.setFlags(Qt.ItemFlag.NoItemFlags)
                font = head.font()
                font.setBold(True)
                head.setFont(font)
                self.quantities.addItem(head)
                current_tool = module
            scans = len({e['path'] for e in entries})
            text = f'{ui_label(key)}' + (f'  ({unit})' if unit and unit not in key else '') + \
                   f'   —   {scans} scan' + ('s' if scans != 1 else '')
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, group)
            item.setToolTip(f'Tool: {ui_label(module)}\nTable: {ui_label(table) or "—"}\nColumn: {key}\n'
                            f'{len(entries)} value(s) on {scans} scan(s)')
            self.quantities.addItem(item)
        self.quantities.blockSignals(False)
        has = bool(self.groups)
        self._split.setVisible(has)
        self.empty.setVisible(not has)
        if not has and self.runs and self.scope.currentData() == 'project':
            self.empty.setText('<b>No results for the scans of this project.</b><br><br>Choose <i>All scans ever '
                               'analysed</i> above, or run an analysis tool on the scans of this project.')
        target = None
        for i in range(self.quantities.count()):
            item = self.quantities.item(i)
            group = item.data(Qt.ItemDataRole.UserRole)
            if group is None:
                continue
            if target is None or group == previous:
                target = item
            if group == previous:
                break
        if target is not None:
            self.quantities.setCurrentItem(target)
        self._filter_quantities(self.search.text())
        self._show_group()

    def _filter_quantities(self, text):
        text = (text or '').lower().strip()
        for i in range(self.quantities.count()):
            item = self.quantities.item(i)
            if item.data(Qt.ItemDataRole.UserRole) is None:
                item.setHidden(bool(text))
            else:
                item.setHidden(bool(text) and text not in item.text().lower())

    def current_group(self):
        item = self.quantities.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _show_group(self):
        group = self.current_group()
        self._entries = list(self.groups.get(group, [])) if group else []
        self._entries.sort(key=lambda e: (e['scan'].lower(), e['detail'], e['created']))
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for entry in self._entries:
            n = self.table.rowCount()
            self.table.insertRow(n)
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            use.setCheckState(Qt.CheckState.Checked)
            use.setToolTip('Include this value in the chart, the summary and the export')
            self.table.setItem(n, 0, use)
            value = fmt(entry['value'])
            if entry.get('uncertainty') is not None:
                value += f' ± {fmt(float(entry["uncertainty"]))}'
            cells = (entry['scan'] + ('  (source changed)' if entry.get('stale') else ''), entry['detail'] or '—',
                     value, entry['unit'] or '—', ui_label(entry['tool']), entry['created'])
            for j, text in enumerate(cells, 1):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, n)
                if j == 1:
                    item.setToolTip(entry['path'])
                if j == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(n, j, item)
        self.table.blockSignals(False)
        if group:
            module, table, key, unit = group
            self.caption.setText(f'{ui_label(key)}' + (f' ({unit})' if unit else '') + f' · {ui_label(module)}'
                                 + (f' · {ui_label(table)}' if table else ''))
        else:
            self.caption.setText('')
        self._update_chart()
        self._update_buttons()

    def ticked(self) -> list[dict]:
        out = []
        for i, entry in enumerate(self._entries):
            item = self.table.item(i, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                out.append(entry)
        return out

    def _row_toggled(self, item):
        if item.column() == 0:
            self._update_chart()
            self._update_buttons()

    def _point_label(self, entry, entries):
        same = sum(1 for e in entries if e['scan'] == entry['scan']) > 1
        return entry['scan'] + (f' · {entry["detail"]}' if same and entry['detail'] else '')

    def _update_chart(self):
        rows = self.ticked()
        group = self.current_group()
        unit = group[3] if group else ''
        self.chart.set_data([(self._point_label(e, rows), e['value']) for e in rows], unit,
                            ui_label(group[2]) if group else '')
        s = stats([e['value'] for e in rows])
        if s['n']:
            u = f' {unit}' if unit else ''
            text = f'n = {s["n"]}   ·   mean {fmt(s["mean"])}{u}'
            if s['n'] > 1:
                rel = f' ({abs(s["std"] / s["mean"]) * 100:.1f} %)' if s['mean'] else ''
                text += f'   ·   std {fmt(s["std"])}{u}{rel}   ·   range {fmt(s["min"])} – {fmt(s["max"])}{u}'
            self.summary.setText(text)
        else:
            self.summary.setText('No row ticked.')

    def _update_buttons(self):
        rows = self.ticked()
        self.buttons['csv'].setEnabled(bool(rows))
        self.buttons['chart'].setEnabled(bool(rows))
        entry = self.selected_entry()
        self.buttons['folder'].setEnabled(bool(entry and entry.get('run_folder')))
        self.buttons['scan'].setEnabled(bool(entry and Path(entry.get('path', '')).is_file()
                                             and self.window_ is not None and hasattr(self.window_, '_load_file')))

    def selected_entry(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return self._entries[0] if len(self._entries) == 1 else None

    def _select_point(self, index):
        rows = self.ticked()
        if 0 <= index < len(rows):
            row = self._entries.index(rows[index])
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 1))

    # ------------------------------------------------------------------ actions
    def export_csv(self, path=None):
        rows = self.ticked()
        if not rows:
            return None
        group = self.current_group()
        if path is None:
            name = re.sub(r'[^\w.-]+', '_', ui_label(group[2]) if group else 'comparison').strip('_') or 'comparison'
            path, _ = QFileDialog.getSaveFileName(self, 'Export the comparison', f'{name}.csv', 'CSV (*.csv)')
            if not path:
                return None
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['scan', 'detail', 'quantity', 'value', 'unit', 'uncertainty', 'tool', 'table', 'date',
                            'run_id', 'scan_path'])
                for e in rows:
                    w.writerow([e['scan'], e['detail'], group[2] if group else '', repr(e['value']), e['unit'],
                                '' if e.get('uncertainty') is None else e['uncertainty'], e['tool'],
                                group[1] if group else '', e['created'], e['run_id'], e['path']])
        except OSError as exc:
            QMessageBox.warning(self, 'Export failed', str(exc))
            return None
        return path

    def save_chart(self, path=None):
        if not self.ticked():
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, 'Save the chart', 'comparison.svg',
                                                  'SVG (*.svg);;PDF (*.pdf);;PNG (*.png)')
            if not path:
                return None
        from spm_studio.shared.appearance import colors
        palette = dict(colors(self))
        transparent = bool(getattr(self.window_, 'export_transparent', lambda: False)())
        if not transparent:
            palette.update({'surface': '#ffffff', 'foreground': '#1a1a1a', 'muted': '#555555', 'border': '#d4d4d4'})
        size = QSize(900, 520)
        suffix = Path(path).suffix.lower()
        try:
            if suffix == '.svg':
                from PySide6.QtSvg import QSvgGenerator
                gen = QSvgGenerator()
                gen.setFileName(str(path))
                gen.setSize(size)
                gen.setViewBox(QRectF(0, 0, size.width(), size.height()))
                gen.setTitle('SPM Studio comparison')
                painter = QPainter(gen)
                if not transparent:
                    painter.fillRect(QRectF(0, 0, size.width(), size.height()), QColor('#ffffff'))
                self.chart.paint_to(painter, QRectF(0, 0, size.width(), size.height()), palette, export=True)
                painter.end()
            elif suffix == '.pdf':
                from PySide6.QtGui import QPdfWriter, QPageSize
                from PySide6.QtCore import QSizeF
                writer = QPdfWriter(str(path))
                writer.setPageSize(QPageSize(QSizeF(size.width() * 0.75, size.height() * 0.75),
                                             QPageSize.Unit.Point))
                writer.setResolution(96)
                painter = QPainter(writer)
                self.chart.paint_to(painter, QRectF(0, 0, size.width(), size.height()), palette, export=True)
                painter.end()
            else:
                from PySide6.QtGui import QImage
                scale = 3
                image = QImage(size * scale, QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent if transparent else QColor('#ffffff'))
                painter = QPainter(image)
                painter.scale(scale, scale)
                self.chart.paint_to(painter, QRectF(0, 0, size.width(), size.height()), palette, export=True)
                painter.end()
                image.setDotsPerMeterX(int(300 / 0.0254))
                image.setDotsPerMeterY(int(300 / 0.0254))
                image.save(str(path))
        except Exception as exc:
            QMessageBox.warning(self, 'Chart not saved', str(exc))
            return None
        self.update()
        return path

    def open_run(self):
        entry = self.selected_entry()
        if not entry or not entry.get('run_folder'):
            return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(entry['run_folder']))

    def show_scan(self):
        entry = self.selected_entry()
        w = self.window_
        if not entry or w is None or not Path(entry.get('path', '')).is_file():
            return
        path = str(Path(entry['path']).resolve())
        files = w.browser.files
        for i in range(files.count()):
            if files.item(i).data(Qt.ItemDataRole.UserRole) == path:
                files.setCurrentItem(files.item(i))
                break
        else:
            w._removed_paths.discard(path)
            w._add_file(path)
            for i in range(files.count()):
                if files.item(i).data(Qt.ItemDataRole.UserRole) == path:
                    files.setCurrentItem(files.item(i))
                    break
        w.raise_()
        w.activateWindow()
