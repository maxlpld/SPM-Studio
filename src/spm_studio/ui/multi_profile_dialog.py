"""v32 Multi-line profiles: many coloured lines, many channels, many graphs.

Draw lines on the scan with *Line ROI* (tick *Keep lines* to add several), then open
**Line profiles…**.  Each line gets its own colour, a graph number and an optional
inset; the same lines are re-used on every ticked channel at identical physical
coordinates.  Exports: publication graphs (PNG/PDF/SVG), CSV (long + wide) and the
scan with all lines drawn on it.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPen, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
                               QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QLineEdit, QLabel, QListWidget,
                               QListWidgetItem, QColorDialog, QFileDialog, QSplitter, QWidget, QGroupBox,
                               QFormLayout, QHeaderView)
from spm_studio.shared.dialogs import MessageDialog as QMessageBox

from ..core.multi_profiles import LineSpec, compute_profiles, build_figure, write_csv, write_wide_csv, line_color


class MultiProfileDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.setObjectName('MultiLineProfilesV32')
        self.setWindowTitle('Multi-line profiles')
        self.resize(1320, 820)
        self.mw = main_window
        self.lines: list[LineSpec] = []
        self._building = False
        self.figure = None
        root = QVBoxLayout(self)
        intro = QLabel('Draw lines on the scan (Keep lines adds several), then import them and assign each to a graph.')
        intro.setObjectName('hint')
        intro.setWordWrap(True)
        root.addWidget(intro)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Show', 'Name', 'Colour', 'Scan thickness', 'Graph', 'Inset', 'From → to (px)'])
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._table_changed)
        lv.addWidget(self.table, 2)
        row = QHBoxLayout()
        for text, slot in (('Import lines from scan', self.import_from_scan), ('Remove selected', self.remove_selected),
                           ('Send colours to scan', self.send_to_scan)):
            b = QPushButton(text); b.clicked.connect(slot); row.addWidget(b)
        lv.addLayout(row)
        row = QHBoxLayout()
        for text, slot in (('Save line set…', self.save_lines), ('Load line set…', self.load_lines)):
            b = QPushButton(text); b.clicked.connect(slot); row.addWidget(b)
        row.addStretch(1)
        lv.addLayout(row)
        opts = QGroupBox('Channels and graphs'); of = QFormLayout(opts)
        self.channels = QListWidget(); self.channels.setMaximumHeight(150)
        self.channels.itemChanged.connect(lambda *_: self.refresh())
        of.addRow('Channels (same lines on each)', self.channels)
        self.n_graphs = QSpinBox(); self.n_graphs.setRange(1, 12); self.n_graphs.setValue(1)
        self.n_graphs.valueChanged.connect(self._graphs_changed)
        of.addRow('Number of graphs', self.n_graphs)
        self.titles = QLineEdit(); self.titles.setPlaceholderText('Graph titles, comma-separated (optional, LaTeX ok)')
        self.titles.editingFinished.connect(self.refresh)
        of.addRow('Graph titles', self.titles)
        self.normalize = QCheckBox('Normalize 0–1')
        self.normalize.setToolTip('Normalize each curve to 0–1 to compare channels on one axis')
        self.normalize.toggled.connect(self.refresh)
        of.addRow(self.normalize)
        self.inset_pos = QComboBox(); self.inset_pos.addItems(['upper right', 'upper left', 'lower right', 'lower left'])
        self.inset_pos.currentIndexChanged.connect(self.refresh)
        of.addRow('Inset position', self.inset_pos)
        lv.addWidget(opts)
        exp = QHBoxLayout()
        for text, slot in (('Export graphs…', self.export_graphs), ('Export CSV…', self.export_csv),
                           ('Export scan with lines…', self.export_scan)):
            b = QPushButton(text); b.clicked.connect(slot); exp.addWidget(b)
        lv.addLayout(exp)
        split.addWidget(left)
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        self.canvas = FigureCanvasQTAgg(Figure(figsize=(6, 4)))
        rv.addWidget(self.canvas, 1)
        self._plot_layout = rv
        self.status = QLabel(''); self.status.setWordWrap(True)
        rv.addWidget(self.status)
        split.addWidget(right)
        split.setSizes([560, 760])
        self._fill_channels()
        self.import_from_scan()

    # ---------------------------------------------------------------- data
    def _trace(self):
        try:
            return self.mw.inspector.selected_trace()
        except Exception:
            return 'forward'

    def _fill_channels(self):
        scan = self.mw.scan
        self.channels.blockSignals(True)
        self.channels.clear()
        current = self.mw.inspector.channel.currentText()
        for name in (scan.channels if scan else {}):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name == current else Qt.CheckState.Unchecked)
            self.channels.addItem(item)
        self.channels.blockSignals(False)

    def _checked_channels(self):
        return [self.channels.item(i).text() for i in range(self.channels.count())
                if self.channels.item(i).checkState() == Qt.CheckState.Checked]

    def _channel_payload(self, name):
        from ..core.processing import apply
        scan = self.mw.scan
        obj = scan.channels[name]
        trace = self._trace()
        if trace not in obj.traces:
            trace = 'forward' if 'forward' in obj.traces else next(iter(obj.traces))
        data = np.asarray(obj.get(trace), dtype=float)
        steps = self.mw.pipelines.get((str(scan.path), name, trace), [])
        try:
            data = apply(data, steps) if steps else data
        except Exception:
            pass
        title = self.mw.channel_title(name)
        return {'name': title, 'data': data, 'unit': obj.unit, 'size_m': obj.geometry.size_m}

    def import_from_scan(self):
        v = self.mw.viewer
        if v.geometry is None:
            self.status.setText('Open a scan and draw lines first.')
            return
        rois = [r for r in list(v.extra_rois) + ([v.roi] if v.roi is not None else []) if r.kind == 'line']
        known = {tuple(map(tuple, l.points_px)) for l in self.lines}
        shape = tuple(v.geometry.shape)
        current = {tuple(tuple(map(float, p)) for p in r.points_px) for r in rois}
        # A line that was extended (Shift+click) or whose vertex was dragged keeps its
        # name, colour and graph: the stale entry is updated instead of adding a new line.
        stale = [l for l in self.lines if tuple(map(tuple, l.points_px)) not in current
                 and tuple(l.reference_shape) == shape]
        for roi in rois:
            pts = tuple(tuple(map(float, p)) for p in roi.points_px)
            if pts in known:
                continue
            if stale:
                line = stale.pop(0)
                old = tuple(map(tuple, line.points_px))
                style = v.line_styles.pop(old, None)
                line.points_px = pts
                if style is not None:
                    v.line_styles[pts] = style
                continue
            i = len(self.lines)
            self.lines.append(LineSpec(pts, shape, f'L{i + 1}', line_color(i), graph=1))
        self._rebuild_table()
        self.refresh()
        if not rois:
            self.status.setText('No line on the scan yet: use Line ROI (tick Keep lines to draw several).')

    def _rebuild_table(self):
        self._building = True
        self.table.setRowCount(len(self.lines))
        for r, line in enumerate(self.lines):
            show = QTableWidgetItem(); show.setFlags(show.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            show.setCheckState(Qt.CheckState.Checked if line.visible else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, show)
            self.table.setItem(r, 1, QTableWidgetItem(line.name))
            btn = QPushButton(''); btn.setStyleSheet(f'background:{line.color};border:1px solid #444;')
            btn.clicked.connect(lambda _=False, i=r: self._pick_color(i))
            self.table.setCellWidget(r, 2, btn)
            scan_width = QDoubleSpinBox(); scan_width.setRange(0.5, 12.0); scan_width.setSingleStep(0.5)
            scan_width.setDecimals(1); scan_width.setSuffix(' ×'); scan_width.setValue(line.scan_width)
            scan_width.setToolTip('Thickness multiplier for this line on the exported scan (1.0 = standard)')
            scan_width.valueChanged.connect(lambda v, i=r: self._set(i, 'scan_width', v))
            self.table.setCellWidget(r, 3, scan_width)
            spin = QSpinBox(); spin.setRange(1, self.n_graphs.value()); spin.setValue(min(line.graph, self.n_graphs.value()))
            spin.valueChanged.connect(lambda v, i=r: self._set(i, 'graph', v))
            self.table.setCellWidget(r, 4, spin)
            ins = QCheckBox(); ins.setChecked(line.inset)
            ins.toggled.connect(lambda v, i=r: self._set(i, 'inset', v))
            self.table.setCellWidget(r, 5, ins)
            coord = QTableWidgetItem(' → '.join(f'({c:.0f}, {r:.0f})' for c, r in line.points_px))
            coord.setFlags(coord.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 6, coord)
        self._building = False

    def _set(self, i, key, value):
        setattr(self.lines[i], key, value)
        self.refresh()

    def _pick_color(self, i):
        c = QColorDialog.getColor(QColor(self.lines[i].color), self, f'Colour of {self.lines[i].name}')
        if c.isValid():
            self.lines[i].color = c.name()
            self._rebuild_table(); self.refresh()

    def _table_changed(self, item):
        if self._building:
            return
        r, c = item.row(), item.column()
        if r >= len(self.lines):
            return
        if c == 0:
            self.lines[r].visible = item.checkState() == Qt.CheckState.Checked
        elif c == 1:
            self.lines[r].name = item.text().strip() or f'L{r + 1}'
        self.refresh()

    def _graphs_changed(self, n):
        for line in self.lines:
            line.graph = min(line.graph, n)
        self._rebuild_table(); self.refresh()

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.lines.pop(r)
        self._rebuild_table(); self.refresh()

    def send_to_scan(self):
        """Push names/colours to the viewer so the scan shows the same colours."""
        self.mw.viewer.line_styles = {
            tuple(map(tuple, l.points_px)): (l.color, l.name, float(l.scan_width))
            for l in self.lines
        }
        self.mw.viewer.update()

    # ---------------------------------------------------------------- figure
    def _profiles(self):
        names = self._checked_channels()
        if not names or not self.lines:
            return [], []
        payload = [self._channel_payload(n) for n in names]
        return compute_profiles(self.lines, payload), [p['name'] for p in payload]

    def _style(self):
        try:
            return self.mw._plot_profile_for_run()
        except Exception:
            return None

    def _build(self, **kw):
        profiles, chans = self._profiles()
        if not profiles:
            return None, profiles
        titles = [t.strip() for t in self.titles.text().split(',')] if self.titles.text().strip() else None
        fig = build_figure(profiles, n_graphs=self.n_graphs.value(), channels=chans,
                           normalize=self.normalize.isChecked(), plot_style=self._style(),
                           graph_titles=titles, inset_position=self.inset_pos.currentText(), **kw)
        return fig, profiles

    def refresh(self):
        self.send_to_scan()
        try:
            fig, profiles = self._build()
        except Exception as exc:
            self.status.setText(f'Cannot draw profiles: {exc}')
            return
        if fig is None:
            try:
                self.canvas.figure.clf(); self.canvas.draw_idle()
            except Exception:
                pass
            self.status.setText('Tick at least one channel and import at least one line.')
            return
        self.figure = fig
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        new = FigureCanvasQTAgg(fig)
        self._plot_layout.replaceWidget(self.canvas, new)
        self.canvas.setParent(None); self.canvas.deleteLater()
        self.canvas = new
        new.draw_idle()
        self.status.setText(f'{len(self.lines)} line(s) · {len(self._checked_channels())} channel(s) · '
                            f'{self.n_graphs.value()} graph(s) · {len(profiles)} curve(s)')

    # ---------------------------------------------------------------- export
    def _default_dir(self):
        scan = self.mw.scan
        return Path(getattr(self.mw, 'last_export_dir', None) or (scan.path.parent if scan else Path.home()))

    def _stem(self):
        scan = self.mw.scan
        return (scan.path.stem if scan else 'scan') + '_line_profiles'

    def export_graphs(self):
        fn, _ = QFileDialog.getSaveFileName(self, 'Export profile graphs', str(self._default_dir() / (self._stem() + '.svg')),
                                            'SVG (*.svg);;PDF (*.pdf);;PNG 600+ DPI (*.png)')
        if not fn:
            return
        fig, profiles = self._build()
        if fig is None:
            return
        from ..core.plots import savefig_maybe_transparent, publication_dpi
        style = self._style() or {}
        savefig_maybe_transparent(fig, fn, transparent=bool(style.get('transparent_background', False)),
                                  dpi=publication_dpi(style.get('dpi', 600)), bbox_inches='tight', pad_inches=.01)
        Path(fn + '.lines.json').write_text(json.dumps({'kind': 'spm_studio_multi_line_profiles', 'schema_version': 1,
            'scan': str(self.mw.scan.path), 'channels': self._checked_channels(), 'n_graphs': self.n_graphs.value(),
            'normalize': self.normalize.isChecked(), 'lines': [l.to_dict() for l in self.lines]}, indent=2), encoding='utf-8')
        self.status.setText(f'Saved {fn}')

    def export_csv(self):
        fn, _ = QFileDialog.getSaveFileName(self, 'Export profile data (CSV)', str(self._default_dir() / (self._stem() + '.csv')),
                                            'CSV (*.csv)')
        if not fn:
            return
        profiles, _ = self._profiles()
        if not profiles:
            return
        write_csv(profiles, fn)
        wide = str(Path(fn).with_name(Path(fn).stem + '_wide.csv'))
        write_wide_csv(profiles, wide)
        self.status.setText(f'Saved {fn} (one row per sample) and {wide} (columns per line)')

    def export_scan(self):
        """Open Studio's standard scan-export dialog, including its usual options."""
        if self.mw.viewer.image is None or self.mw.viewer.geometry is None:
            return
        # Use the normal publication exporter so preset/layout, formats, DPI,
        # transparency, and channel/trace choices remain available. The main
        # exporter includes all current line ROIs as scan overlays.
        self.mw.export_current()

    # ---------------------------------------------------------------- reuse
    def save_lines(self):
        fn, _ = QFileDialog.getSaveFileName(self, 'Save line set', str(self._default_dir() / (self._stem() + '.lines.json')),
                                            'Line set (*.json)')
        if fn:
            Path(fn).write_text(json.dumps({'kind': 'spm_studio_line_set', 'schema_version': 1,
                                            'lines': [l.to_dict() for l in self.lines]}, indent=2), encoding='utf-8')

    def load_lines(self):
        fn, _ = QFileDialog.getOpenFileName(self, 'Load line set', str(self._default_dir()), 'Line set (*.json)')
        if not fn:
            return
        try:
            d = json.loads(Path(fn).read_text(encoding='utf-8'))
            self.lines = [LineSpec.from_dict(x) for x in d['lines']]
        except Exception as exc:
            QMessageBox.warning(self, 'Load line set', f'Cannot read line set: {exc}')
            return
        # put them on the scan too, so they can be edited with the Line ROI tool
        from ..core.models import ROI
        from ..core.multi_profiles import map_points
        v = self.mw.viewer
        if v.geometry is not None:
            for l in self.lines:
                pts = map_points(l.points_px, l.reference_shape, tuple(v.geometry.shape))
                v.extra_rois.append(ROI('line', pts))
            v.update()
        self.n_graphs.setValue(max([1] + [l.graph for l in self.lines]))
        self._rebuild_table(); self.refresh()
