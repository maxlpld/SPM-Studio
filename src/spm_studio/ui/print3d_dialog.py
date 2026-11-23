"""Tools › 3D print: STL / STEP / 3MF plates of one or several scan channels with 3D colour bars, live preview.

v0.0.15: sharp bold labels, centred layout, several channels per plate (2 / 3 / triangle / 4 / custom grid),
channel titles on/off, main title, fridge-magnet pockets and a 3MF with one colour-gradient part per channel.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QFormLayout, QComboBox, QDoubleSpinBox, QSpinBox,
                               QCheckBox, QLineEdit, QPushButton, QLabel, QGroupBox, QFileDialog, QScrollArea,
                               QWidget, QSizePolicy, QMessageBox, QGridLayout, QColorDialog)
from PySide6.QtGui import QColor

from ..core import print3d as P
from ..core import print3d_plate as Q
from ..core import print3d_bambu as B

PREVIEW_MAX_CELLS = 80_000       # 3D preview grid (≈ 280 × 280)

GRADIENTS = (('#1D3F8F', '#F5C342'), ('#5B1A72', '#F28C28'), ('#0B6E4F', '#E8F1A0'), ('#7A1020', '#F7D9C4'),
             ('#202020', '#E0E0E0'), ('#0E4D64', '#F2A65A'))


class ColorButton(QPushButton):
    """Small button showing a colour; click to choose another one."""

    def __init__(self, color, on_change=None):
        super().__init__()
        self.setMaximumWidth(46)
        self._on_change = on_change
        self.set_color(color)
        self.clicked.connect(self._pick)

    def color(self):
        return self._color

    def set_color(self, color):
        self._color = QColor(color).name().upper()
        self.setToolTip(self._color)
        self.setStyleSheet(f'background:{self._color}; min-height:18px; border:1px solid #888; border-radius:3px;')

    def _pick(self):
        chosen = QColorDialog.getColor(QColor(self._color), self, 'Filament colour')
        if chosen.isValid():
            self.set_color(chosen.name())
            if self._on_change:
                self._on_change()

SOURCES = (('Scan channel', 'channel'), ('Lattice result (vectors + legend)', 'lattice'),
           ('Molecule placement (molecules + vectors)', 'molecules'))


def _find_result(scan_path, pattern, filename):
    scan = Path(scan_path).resolve()
    root = scan.parent / 'SPM_Studio_Results' / scan.stem
    found = sorted([*root.glob(f'Data/{pattern}_*/{filename}'), *root.glob(f'*{pattern}*/{filename}')],
                   key=lambda p: p.stat().st_mtime_ns, reverse=True) if root.exists() else []
    for path in found:
        try:
            doc = json.loads(path.read_text(encoding='utf8'))
            if Path(doc.get('source_scan', '')).resolve() == scan:
                return path, doc
        except (OSError, ValueError):
            continue
    return None, None


def _svg_alpha(path, long_side=400):
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtGui import QImage, QPainter
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        raise ValueError(f'Unreadable SVG: {path}')
    size = renderer.defaultSize()
    scale = long_side / max(1, size.width(), size.height())
    image = QImage(max(1, int(size.width() * scale)), max(1, int(size.height() * scale)),
                   QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    ptr = image.constBits()
    arr = np.frombuffer(ptr, np.uint8, image.sizeInBytes()).reshape(image.height(), image.bytesPerLine() // 4, 4)
    return arr[:, :image.width(), 3].astype(float) / 255


class Print3DDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle('3D print — STL / STEP / 3MF plate with 3D colour bars')
        self.setObjectName('Print3DDialogV0012')
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1250, 780)
        self.settings = QSettings()
        self.model = None
        self.plate = None
        self.panel_rows = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self.update_preview)
        root = QHBoxLayout(self)
        # ------------------------------------------------------------ controls
        panel = QWidget()
        form_layout = QVBoxLayout(panel)
        form_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(390)
        scroll.setMaximumWidth(460)
        root.addWidget(scroll)

        box = QGroupBox('What to print')
        f = QFormLayout(box)
        self.source = QComboBox()
        for label, key in SOURCES:
            self.source.addItem(label, key)
        self.channel = QComboBox()
        self.trace = QComboBox()
        self.trace.addItems(['forward', 'backward'])
        self.processed = QCheckBox('Use the processing shown on the scan')
        self.processed.setChecked(True)
        self.result_file = QLineEdit()
        self.result_file.setPlaceholderText('latest result of this scan')
        pick = QPushButton('…')
        pick.setMaximumWidth(34)
        pick.clicked.connect(self._pick_result)
        row = QHBoxLayout()
        row.addWidget(self.result_file, 1)
        row.addWidget(pick)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        f.addRow('Source', self.source)
        f.addRow('Channel', self.channel)
        f.addRow('Trace', self.trace)
        f.addRow('', self.processed)
        f.addRow('Result file', holder)
        self.source_hint = QLabel('')
        self.source_hint.setWordWrap(True)
        self.source_hint.setObjectName('hint')
        f.addRow(self.source_hint)
        form_layout.addWidget(box)

        box = QGroupBox('Layout and titles')
        f = QFormLayout(box)
        self.layout_combo = QComboBox()
        for key, (label, _slots) in Q.LAYOUTS.items():
            self.layout_combo.addItem(label, key)
        self.layout_rows = QSpinBox()
        self.layout_rows.setRange(1, 4)
        self.layout_cols = QSpinBox()
        self.layout_cols.setRange(1, 4)
        self.layout_cols.setValue(2)
        grid_row = QHBoxLayout()
        grid_row.setContentsMargins(0, 0, 0, 0)
        grid_row.addWidget(self.layout_rows)
        grid_row.addWidget(QLabel('×'))
        grid_row.addWidget(self.layout_cols)
        self.grid_holder = QWidget()
        self.grid_holder.setLayout(grid_row)
        self.channel_titles = QCheckBox('Channel titles above each scan')
        self.channel_titles.setChecked(True)
        self.main_title = QLineEdit()
        self.main_title.setPlaceholderText('optional, centred on top of the plate')
        f.addRow('Channels on the plate', self.layout_combo)
        f.addRow('Custom rows × columns', self.grid_holder)
        f.addRow('', self.channel_titles)
        f.addRow('Main title', self.main_title)
        self.panels_box = QWidget()
        self.panels_grid = QGridLayout(self.panels_box)
        self.panels_grid.setContentsMargins(0, 0, 0, 0)
        f.addRow(self.panels_box)
        hint = QLabel('Panel 1 is the source above; choose the channel of the other panels. The two colours are '
                      'the low → high colour gradient of the 3MF export.')
        hint.setWordWrap(True)
        hint.setObjectName('hint')
        f.addRow(hint)
        form_layout.addWidget(box)

        def dspin(lo, hi, value, step=.1, decimals=2, suffix=' mm'):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(decimals)
            s.setSingleStep(step)
            s.setValue(value)
            s.setSuffix(suffix)
            return s

        box = QGroupBox('Size and height')
        f = QFormLayout(box)
        self.width_mm = dspin(10, 400, 80, 5, 1)
        self.base_mm = dspin(.4, 30, 2, .2, 1)
        self.relief_mm = dspin(.2, 80, 6, .5, 1)
        self.quality = QComboBox()
        for key, label in (('draft', 'Draft (light file)'), ('standard', 'Standard'), ('fine', 'Fine (large file)'),
                           ('custom', 'Custom grid')):
            self.quality.addItem(label, key)
        self.quality.setCurrentIndex(1)
        self.resolution = dspin(.05, 2, Q.QUALITY['standard'], .05, 2)
        self.smooth = dspin(0, 10, 0, .5, 1, ' px')
        self.invert = QCheckBox('Invert (low values high)')
        self.magnets = QCheckBox('Fridge magnet: 4 round pockets under the corners')
        self.magnet_radius = dspin(1, 20, 5.1, .1, 2)
        self.magnet_depth = dspin(.4, 10, 2.0, .1, 2)
        self.base_color = ColorButton('#FFFFFF', self.schedule)       # plate / background colour
        self.text_color = ColorButton('#000000', self.schedule)       # every text, tick and scale bar
        f.addRow('Scan width', self.width_mm)
        f.addRow('Base plate', self.base_mm)
        f.addRow('Relief (low → high)', self.relief_mm)
        f.addRow('Quality', self.quality)
        f.addRow('Grid resolution', self.resolution)
        f.addRow('Smoothing', self.smooth)
        f.addRow('', self.invert)
        f.addRow('', self.magnets)
        f.addRow('Magnet pocket radius', self.magnet_radius)
        f.addRow('Magnet pocket depth', self.magnet_depth)
        form_layout.addWidget(box)

        box = QGroupBox('Colour-bar range (= printed heights)')
        f = QFormLayout(box)
        self.range_mode = QComboBox()
        self.range_mode.addItem('Same as the image (its contrast)', 'display')
        self.range_mode.addItem('Percentiles of the scan', 'percentile')
        self.range_mode.addItem('Values (display unit)', 'absolute')
        self.low = dspin(-1e9, 1e9, 1, 1, 3, '')
        self.high = dspin(-1e9, 1e9, 99, 1, 3, '')
        self.range_hint = QLabel('Values outside the range are printed flat (cuts a too high peak).')
        self.range_hint.setWordWrap(True)
        self.range_hint.setObjectName('hint')
        self.zero_mode = QComboBox()
        self.zero_mode.addItem('As the image (Fix Zero when it is on)', 'image')
        self.zero_mode.addItem('Measured values', 'values')
        self.zero_mode.addItem('From 0 (low end = 0)', 'zero')
        f.addRow('Mode', self.range_mode)
        f.addRow('Colour-bar labels', self.zero_mode)
        f.addRow('Low', self.low)
        f.addRow('High', self.high)
        f.addRow(self.range_hint)
        form_layout.addWidget(box)

        box = QGroupBox('Colour bar, labels, overlays')
        f = QFormLayout(box)
        self.colorbar = QComboBox()
        for name in P.POSITIONS:
            self.colorbar.addItem(name.capitalize() if name != 'none' else 'No colour bar', name)
        self.bar_width = dspin(3, 60, 10, 1, 1)
        self.bar_gap = dspin(1, 40, 5, 1, 1)
        self.ticks = QSpinBox()
        self.ticks.setRange(2, 11)
        self.ticks.setValue(5)
        self.font = dspin(1.5, 15, 5, .5, 1)
        self.label_mm = dspin(.2, 5, 1.0, .1, 1)
        self.overlay_mm = dspin(.2, 10, 1, .1, 1)
        self.title = self.main_title          # v0.0.12 name of the title field
        self.scale_bar = QCheckBox('Scale bar')
        self.scale_bar.setChecked(True)
        f.addRow('Colour bar', self.colorbar)
        f.addRow('Bar width', self.bar_width)
        f.addRow('Gap', self.bar_gap)
        f.addRow('Ticks', self.ticks)
        f.addRow('Text size', self.font)
        f.addRow('Text height', self.label_mm)
        f.addRow('Vectors / molecules height', self.overlay_mm)
        f.addRow('', self.scale_bar)
        f.addRow('Text colour', self.text_color)
        f.addRow('Background colour', self.base_color)
        form_layout.addWidget(box)

        box = QGroupBox('Bambu Lab 3MF')
        f = QFormLayout(box)
        self.printer = QComboBox()
        for name in B.printer_names():
            self.printer.addItem(name.replace('Bambu Lab ', ''), name)
        self.printer.setCurrentIndex(max(0, self.printer.findData(B.DEFAULT_PRINTER)))
        self.nozzle = QComboBox()
        for n in B.NOZZLES:
            self.nozzle.addItem(f'{n} mm', n)
        self.nozzle.setCurrentIndex(self.nozzle.findData('0.4'))
        self.bambu_project = QCheckBox('Bambu Studio project with the colour gradient already set')
        self.bambu_project.setChecked(True)
        self.bambu_project.setToolTip('Printer, nozzle, filaments and one gradient mixed filament per channel '
                                      '(scan + colour bar) are set in the 3MF; untick for a plain 3MF')
        f.addRow('Printer', self.printer)
        f.addRow('Nozzle', self.nozzle)
        f.addRow('', self.bambu_project)
        form_layout.addWidget(box)
        form_layout.addStretch(1)
        buttons = QHBoxLayout()
        self.save_stl = QPushButton('Save STL…')
        self.save_stl.setProperty('primary', True)
        self.save_step = QPushButton('Save STEP…')
        self.save_stl.clicked.connect(lambda: self.export('stl'))
        self.save_step.clicked.connect(lambda: self.export('step'))
        self.save_3mf = QPushButton('Save 3MF (colour gradient)…')
        self.save_3mf.setToolTip('Bambu Studio project: scan + colour bar printed as a low → high colour gradient')
        self.save_3mf.clicked.connect(lambda: self.export('3mf'))
        buttons.addWidget(self.save_stl)
        buttons.addWidget(self.save_step)
        form_layout.addLayout(buttons)
        form_layout.addWidget(self.save_3mf)
        # ------------------------------------------------------------ preview
        right = QVBoxLayout()
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        self.figure = Figure(figsize=(7, 6), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right.addWidget(self.canvas, 1)
        self.info = QLabel('')
        self.info.setWordWrap(True)
        self.info.setObjectName('hint')
        right.addWidget(self.info)
        root.addLayout(right, 1)
        self._restore()
        self._fill_channels()
        self._layout_changed()
        for w in (self.source, self.channel, self.trace, self.range_mode, self.colorbar, self.zero_mode,
                  self.printer, self.nozzle):
            w.currentIndexChanged.connect(self.schedule)
        for w in (self.width_mm, self.base_mm, self.relief_mm, self.resolution, self.smooth, self.low, self.high,
                  self.bar_width, self.bar_gap, self.font, self.label_mm, self.overlay_mm, self.magnet_radius,
                  self.magnet_depth):
            w.valueChanged.connect(self.schedule)
        self.ticks.valueChanged.connect(self.schedule)
        for w in (self.processed, self.invert, self.scale_bar, self.channel_titles, self.magnets):
            w.toggled.connect(self.schedule)
        self.magnets.toggled.connect(self._magnets_changed)
        self._magnets_changed()
        self.layout_combo.currentIndexChanged.connect(self._layout_changed)
        self.layout_rows.valueChanged.connect(self._layout_changed)
        self.layout_cols.valueChanged.connect(self._layout_changed)
        self.quality.currentIndexChanged.connect(self._quality_changed)
        self.resolution.valueChanged.connect(self._resolution_edited)
        self.title.textChanged.connect(self.schedule)
        self.result_file.editingFinished.connect(self.schedule)
        self.range_mode.currentIndexChanged.connect(self._range_mode_changed)
        self._range_mode_changed()
        self.source.currentIndexChanged.connect(self._source_changed)
        self._source_changed()
        self.schedule()

    # ------------------------------------------------------------------ settings
    _KEYS = ('width_mm', 'base_mm', 'relief_mm', 'resolution', 'smooth', 'bar_width', 'bar_gap', 'font',
             'label_mm', 'overlay_mm', 'magnet_radius', 'magnet_depth')
    _COMBOS = ('quality', 'layout_combo', 'printer', 'nozzle', 'zero_mode')

    def _restore(self):
        for key in self._KEYS:
            value = self.settings.value(f'print3d/{key}')
            if value is not None:
                try:
                    getattr(self, key).setValue(float(value))
                except (TypeError, ValueError):
                    pass
        position = self.settings.value('print3d/colorbar')
        if position:
            self.colorbar.setCurrentIndex(max(0, self.colorbar.findData(position)))
        for key in self._COMBOS:
            value = self.settings.value(f'print3d/{key}')
            if value:
                combo = getattr(self, key)
                combo.setCurrentIndex(max(0, combo.findData(value)))
        for key in ('layout_rows', 'layout_cols'):
            try:
                getattr(self, key).setValue(int(self.settings.value(f'print3d/{key}') or getattr(self, key).value()))
            except (TypeError, ValueError):
                pass
        for key, button in (('text_color', self.text_color), ('background_color', self.base_color)):
            value = self.settings.value(f'print3d/{key}')
            if value and QColor(str(value)).isValid():
                button.set_color(str(value))
        titles = self.settings.value('print3d/channel_titles')
        if titles is not None:
            self.channel_titles.setChecked(str(titles).lower() in ('true', '1'))

    def _store(self):
        for key in self._KEYS:
            self.settings.setValue(f'print3d/{key}', getattr(self, key).value())
        self.settings.setValue('print3d/colorbar', self.colorbar.currentData())
        for key in self._COMBOS:
            self.settings.setValue(f'print3d/{key}', getattr(self, key).currentData())
        for key in ('layout_rows', 'layout_cols'):
            self.settings.setValue(f'print3d/{key}', getattr(self, key).value())
        self.settings.setValue('print3d/channel_titles', self.channel_titles.isChecked())
        self.settings.setValue('print3d/text_color', self.text_color.color())
        self.settings.setValue('print3d/background_color', self.base_color.color())

    def closeEvent(self, event):
        self._store()
        super().closeEvent(event)

    # ------------------------------------------------------------------ sources
    def _fill_channels(self):
        scan = getattr(self.main_window, 'scan', None)
        self.channel.blockSignals(True)
        self.channel.clear()
        if scan is not None:
            self.channel.addItems(list(scan.channels))
            try:
                active = self.main_window.inspector.channel.currentText()
                if active:
                    self.channel.setCurrentText(active)
            except Exception:
                pass
        self.channel.blockSignals(False)

    def _source_changed(self, *_):
        key = self.source.currentData()
        channel = key == 'channel'
        for w in (self.channel, self.trace, self.processed):
            w.setEnabled(channel)
        self.result_file.setEnabled(not channel)
        self.overlay_mm.setEnabled(not channel)
        hints = {'channel': 'Any channel of the open scan (topography, current, dI/dV map, Δf …).',
                 'lattice': 'The scan region of the latest “Lattice measurements” result of this scan, with the '
                            'lattice vectors raised on the relief and a, b, γ embossed under it.',
                 'molecules': 'The latest “Molecule placement” result: molecule outlines raised on the relief, '
                              'lattice vectors and legend.'}
        self.source_hint.setText(hints[key])

    def _range_mode_changed(self, *_):
        display = self.range_mode.currentData() == 'display'
        for w in (self.low, self.high):
            w.setEnabled(not display)
        if display:
            self.range_hint.setText('The colour-bar range of each channel is the contrast range of its image in '
                                    'SPM Studio. Values outside are printed flat.')
            self.schedule()
            return
        self.range_hint.setText('Values outside the range are printed flat (cuts a too high peak).')
        if self.range_mode.currentData() == 'percentile':
            self.low.setSuffix(' %')
            self.high.setSuffix(' %')
            self.low.setValue(1)
            self.high.setValue(99)
        else:
            self.low.setSuffix('')
            self.high.setSuffix('')
            try:
                data, _size, unit, factor, _ov = self._data()
                lo, hi = np.nanpercentile(data, [1, 99]) * factor
                self.low.setValue(float(lo))
                self.high.setValue(float(hi))
            except Exception:
                pass

    def _quality_changed(self, *_):
        key = self.quality.currentData()
        if key in Q.QUALITY:
            self.resolution.blockSignals(True)
            self.resolution.setValue(Q.QUALITY[key])
            self.resolution.blockSignals(False)
            self.schedule()

    def _resolution_edited(self, *_):
        if self.quality.currentData() != 'custom' and \
                abs(self.resolution.value() - Q.QUALITY.get(self.quality.currentData(), -1)) > 1e-6:
            self.quality.blockSignals(True)
            self.quality.setCurrentIndex(self.quality.findData('custom'))
            self.quality.blockSignals(False)

    def _magnets_changed(self, *_):
        for w in (self.magnet_radius, self.magnet_depth):
            w.setEnabled(self.magnets.isChecked())

    def layout_params(self):
        return {'layout': self.layout_combo.currentData(), 'layout_rows': self.layout_rows.value(),
                'layout_cols': self.layout_cols.value()}

    def _layout_changed(self, *_):
        """One row per extra panel: channel, trace, low and high gradient colours."""
        self.grid_holder.setEnabled(self.layout_combo.currentData() == 'custom')
        n = Q.panel_count(self.layout_params())
        old = [(r['channel'].currentText(), r['trace'].currentText(), r['low'].color(), r['high'].color())
               for r in self.panel_rows]
        while self.panels_grid.count():
            item = self.panels_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.panel_rows = []
        scan = getattr(self.main_window, 'scan', None)
        names = list(scan.channels) if scan is not None else []
        for k in range(n):
            label = QLabel(f'Panel {k + 1}')
            if k == 0:
                channel = QLabel('source above')
                trace = QLabel('')
            else:
                channel = QComboBox()
                channel.addItems(names)
                if names:
                    channel.setCurrentIndex(k % len(names))
                trace = QComboBox()
                trace.addItems(['forward', 'backward'])
            low, high = GRADIENTS[k % len(GRADIENTS)]
            if k < len(old):
                if k and old[k][0]:
                    channel.setCurrentText(old[k][0])
                    trace.setCurrentText(old[k][1])
                low, high = old[k][2], old[k][3]
            row = {'channel': channel, 'trace': trace, 'low': ColorButton(low, self.schedule),
                   'high': ColorButton(high, self.schedule)}
            if k:
                channel.currentIndexChanged.connect(self.schedule)
                trace.currentIndexChanged.connect(self.schedule)
            else:          # keep the same API for panel 1
                channel.currentText = lambda: ''
                trace.currentText = lambda: ''
            for col, w in enumerate((label, channel, trace, row['low'], row['high'])):
                self.panels_grid.addWidget(w, k, col)
            self.panel_rows.append(row)
        self.schedule()

    def panels(self):
        """Q.Panel list of the plate (panel 1 = the chosen source)."""
        data, size_nm, unit, factor, overlay = self._data()
        rows = self.panel_rows or [{'low': ColorButton(GRADIENTS[0][0]), 'high': ColorButton(GRADIENTS[0][1])}]
        title = self.channel.currentText() if self.source.currentData() == 'channel' else \
            {'lattice': 'Lattice', 'molecules': 'Molecules'}.get(self.source.currentData(), '')
        if self.source.currentData() == 'channel' and self.trace.currentText() == 'backward':
            title += ' (backward)'
        source_channel = self.channel.currentText() if self.source.currentData() == 'channel' else None
        rng0, zero0 = self._panel_options(data, source_channel, self.trace.currentText())
        out = [Q.Panel(data, size_nm, unit, factor, title, overlay, (rows[0]['low'].color(), rows[0]['high'].color()),
                       rng0, zero0)]
        absolute = self.range_mode.currentData() == 'absolute'
        for row in rows[1:]:
            name = row['channel'].currentText()
            if not name:
                raise ValueError('Open a scan to choose the channels of the other panels')
            a, cd = self._channel_array(name, row['trace'].currentText(), self.processed.isChecked())
            size = cd.geometry.size_m
            f, u = P.display_unit(cd.unit or '', a)
            rng, zero = self._panel_options(a, name, row['trace'].currentText())
            if absolute:
                rng = {'range_mode': 'percentile', 'low': 1.0, 'high': 99.0}
            label = name + (' (backward)' if row['trace'].currentText() == 'backward' else '')
            out.append(Q.Panel(a, (size[0] * 1e9, size[1] * 1e9) if size else None, u, f, label, None,
                               (row['low'].color(), row['high'].color()), rng, zero))
        return out

    def _pick_result(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Lattice / molecule result', str(Path.home()), 'JSON (*.json)')
        if path:
            self.result_file.setText(path)
            self.schedule()

    def _is_current(self, channel, trace):
        try:
            insp = self.main_window.inspector
            return insp.channel.currentText() == channel and insp.selected_trace() == trace
        except Exception:
            return False

    def _steps(self, channel, trace):
        """Processing steps of a channel, as in the main window (the inspector for the shown channel)."""
        mw = self.main_window
        scan = mw.scan
        key = (str(scan.path), channel, trace)
        steps = list(getattr(mw, 'pipelines', {}).get(key, []))
        if self._is_current(channel, trace):
            try:
                steps = list(mw.inspector.steps())
            except Exception:
                pass
        return steps

    def _style(self, channel, trace):
        """ImageStyle of a channel (contrast mode / range) as shown in the main window, or None."""
        mw = self.main_window
        if self._is_current(channel, trace):
            try:
                return mw.inspector.get_style()
            except Exception:
                pass
        try:
            return getattr(mw, 'styles', {}).get((str(mw.scan.path), channel, trace))
        except Exception:
            return None

    def _channel_array(self, channel, trace, processed):
        mw = self.main_window
        scan = mw.scan
        cd = scan.channels[channel]
        if trace not in cd.traces:
            trace = next(iter(cd.traces))
        data = np.asarray(cd.get(trace), float)
        if processed:
            steps = self._steps(channel, trace)
            if steps:
                from ..core.processing import apply
                data = apply(data, steps)
        return data, cd

    def _panel_options(self, data, channel=None, trace=None):
        """(range override, zero_reference) of a panel from the range mode and the Fix Zero setting."""
        from ..core.processing import display_zero_enabled
        rng = {}
        if self.range_mode.currentData() == 'display':
            style = self._style(channel, trace) if channel else None
            if style is not None:
                from ..core.display import bounds
                lo, hi = bounds(data, style)
            else:
                lo, hi = P.value_range(data, {'range_mode': 'percentile', 'low': 1, 'high': 99})
            rng = {'range_mode': 'absolute', 'low': lo, 'high': hi}
        mode = self.zero_mode.currentData()
        if mode == 'zero':
            zero = True
        elif mode == 'values' or not channel or not self.processed.isChecked():
            zero = False
        else:
            zero = display_zero_enabled(self._steps(channel, trace))
        return rng, zero

    def _data(self):
        """(array, size_nm, unit, display factor, overlay)."""
        scan = getattr(self.main_window, 'scan', None)
        key = self.source.currentData()
        if key == 'channel':
            if scan is None:
                raise ValueError('Open a scan first')
            data, cd = self._channel_array(self.channel.currentText(), self.trace.currentText(),
                                           self.processed.isChecked())
            size = cd.geometry.size_m
            size_nm = (size[0] * 1e9, size[1] * 1e9) if size else None
            factor, unit = P.display_unit(cd.unit or '', data)
            return data, size_nm, unit, factor, None
        if scan is None and not self.result_file.text().strip():
            raise ValueError('Open the scan of the result, or choose the result file')
        explicit = self.result_file.text().strip()
        if key == 'lattice':
            path, doc = (Path(explicit), json.loads(Path(explicit).read_text(encoding='utf8'))) if explicit else \
                _find_result(scan.path, 'lattice_measurements', 'lattice_result.json')
            if doc is None:
                raise ValueError('No lattice result for this scan: run “Lattice measurements” first')
            lattice = doc
            overlay = P.overlay_from_lattice(doc)
        else:
            path, placement = (Path(explicit), json.loads(Path(explicit).read_text(encoding='utf8'))) if explicit \
                else _find_result(scan.path, 'molecule_placement', 'molecule_placement.json')
            if placement is None:
                raise ValueError('No molecule placement for this scan: run “Molecule placement” first')
            lattice = json.loads(Path(placement['lattice_result']).read_text(encoding='utf8'))
            art = Path(placement.get('molecule_png', ''))
            alpha = _svg_alpha(art) if art.suffix.lower() == '.svg' else P.artwork_alpha(art)
            overlay = P.overlay_from_molecules(lattice, placement, alpha)
        data = np.load(lattice['cropped_scan_npy'])
        size_nm = tuple(lattice['roi_geometry']['size_nm'])
        factor, unit = P.display_unit(lattice.get('source_unit', ''), data)
        return data, size_nm, unit, factor, overlay

    def params(self, factor=1.0, unit=''):
        absolute = self.range_mode.currentData() == 'absolute'
        mode = self.range_mode.currentData()
        return {'width_mm': self.width_mm.value(), 'base_mm': self.base_mm.value(),
                'relief_mm': self.relief_mm.value(), 'resolution_mm': self.resolution.value(),
                'range_mode': 'percentile' if mode == 'display' else mode, 'range_source': mode,
                'low': self.low.value() / factor if absolute else self.low.value(),
                'high': self.high.value() / factor if absolute else self.high.value(),
                'invert': self.invert.isChecked(), 'smooth_px': self.smooth.value(),
                'colorbar': self.colorbar.currentData(), 'colorbar_width_mm': self.bar_width.value(),
                'colorbar_gap_mm': self.bar_gap.value(), 'colorbar_ticks': self.ticks.value(),
                'font_mm': self.font.value(), 'label_mm': self.label_mm.value(),
                'overlay_mm': self.overlay_mm.value(), 'title': self.title.text(),
                'scale_bar': self.scale_bar.isChecked(), 'unit': unit, 'value_scale': factor,
                'quality': self.quality.currentData(), 'main_title': self.main_title.text(),
                'channel_titles': self.channel_titles.isChecked(), 'magnets': self.magnets.isChecked(),
                'magnet_radius_mm': self.magnet_radius.value(), 'magnet_depth_mm': self.magnet_depth.value(),
                'base_color': self.base_color.color(), 'background_color': self.base_color.color(),
                'text_color': self.text_color.color(), 'nozzle_mm': float(self.nozzle.currentData() or .4),
                'printer': self.printer.currentData(), **self.layout_params()}

    def bambu_options(self):
        if not self.bambu_project.isChecked():
            return None
        return {'printer': self.printer.currentData(), 'nozzle': float(self.nozzle.currentData() or .4),
                'gradient': True}

    # ------------------------------------------------------------------ preview
    def schedule(self, *_):
        self._timer.start()

    def _build(self, preview=False):
        panels = self.panels()
        p = self.params(panels[0].factor, panels[0].unit)
        p['title'] = ''                       # the title is the plate's main title
        if preview:
            # the preview samples the relief at its own grid (≈ 1/320 of the plate); the files use the quality
            p['resolution_mm'] = max(p['resolution_mm'], p['width_mm'] / 260)
            p['text_resolution_mm'] = .1
        return Q.build_plate(panels, p), p

    def update_preview(self):
        try:
            plate, p = self._build(preview=True)
        except Exception as exc:
            self.figure.clear()
            self.canvas.draw_idle()
            self.info.setText('⚠ ' + str(exc))
            for b in (self.save_stl, self.save_step, self.save_3mf):
                b.setEnabled(False)
            return
        self.plate = plate
        for b in (self.save_stl, self.save_step, self.save_3mf):
            b.setEnabled(True)
        z, cell = plate.preview
        rgb = plate.preview_rgb
        z2, cell2 = P.decimate(z, cell, PREVIEW_MAX_CELLS)
        if rgb is not None and z2.shape != z.shape:
            k = max(1, int(round(cell2 / cell)))
            rgb = rgb[::k, ::k][:z2.shape[0], :z2.shape[1]]
        z, cell = z2, cell2
        rows, cols = z.shape
        x = (np.arange(cols) + .5) * cell
        y = ((rows - 1 - np.arange(rows)) + .5) * cell
        X, Y = np.meshgrid(x, y)
        old = self.figure.axes[0] if self.figure.axes else None
        view = (old.elev, old.azim) if old is not None and hasattr(old, 'elev') else (48, -62)
        self.figure.clear()
        ax = self.figure.add_subplot(projection='3d')
        from matplotlib.colors import LightSource
        light = LightSource(azdeg=315, altdeg=45)
        if rgb is not None and rgb.shape[:2] == z.shape:
            shade = light.shade_rgb(rgb, z, vert_exag=1, blend_mode='soft', dx=cell, dy=cell)  # print colours, lit
        else:
            shade = light.shade(z, cmap=__import__('matplotlib').colormaps['Greys_r'], vert_exag=1, blend_mode='soft',
                                vmin=0, vmax=float(z.max()), dx=cell, dy=cell)
        ax.plot_surface(X, Y, z, facecolors=shade, rstride=1, cstride=1, linewidth=0, antialiased=False, shade=False)
        W, H = plate.size_mm
        top = float(z.max())
        ax.set_box_aspect((W, H, max(top, 1e-3) * 1.0))
        ax.set_xlabel('mm')
        ax.set_ylabel('mm')
        ax.set_zlabel('mm')
        ax.view_init(*view)
        self.figure.tight_layout()
        self.canvas.draw_idle()
        first = plate.panels[0]
        shift = first['low'] if first.get('zero_reference') else 0.0
        lo, hi = (first['low'] - shift) * first['factor'], (first['high'] - shift) * first['factor']
        base = plate.params['base_mm']
        bed = B.PRINTERS.get(self.printer.currentData(), {}).get('bed')
        text = (f'Plate {W:.0f} × {H:.0f} mm, highest point {base + p["relief_mm"]:.1f} mm · {len(plate.panels)} '
                f'channel(s) · range {lo:.4g} … {hi:.4g} {first["unit"]} → {base:.1f} … '
                f'{base + p["relief_mm"]:.1f} mm · relief grid {p_res(self):.2f} mm, labels 0.05 mm '
                f'(preview is coarser). Drag the view to rotate.')
        if bed:
            fits = W <= bed[0] and H <= bed[1]
            text += (f'\n{"✓ fits" if fits else "⚠ larger than"} the {self.printer.currentText()} bed '
                     f'({bed[0]} × {bed[1]} mm)')
        if plate.notes:
            text += '\n' + ' · '.join(plate.notes)
        self.info.setText(text)

    def export(self, fmt):
        suffix = {'stl': 'stl', '3mf': '3mf'}.get(fmt, 'step')
        scan = getattr(self.main_window, 'scan', None)
        folder = Path(getattr(self.main_window, 'last_export_dir', Path.home()) or Path.home())
        name = (scan.path.stem + '_' + self.channel.currentText().replace(' ', '_') if scan else 'relief')
        path, _ = QFileDialog.getSaveFileName(self, f'Save {suffix.upper()}', str(folder / f'{name}.{suffix}'),
                                              f'{suffix.upper()} (*.{suffix})')
        if not path:
            return
        try:
            plate, p = self._build(preview=False)
            bambu = self.bambu_options() if suffix == '3mf' else None
            written, triangles, notes = Q.export_plate(plate, path, suffix, bambu=bambu)
            sidecar = Path(path).with_suffix('.print3d.json')
            info = {'source': self.source.currentData(), 'scan': str(scan.path) if scan else None,
                    'channel': self.channel.currentText(), 'parameters': p,
                    'range': [plate.panels[0]['low'], plate.panels[0]['high']],
                    'panels': [{k: v for k, v in panel.items() if k != 'box'} for panel in plate.panels],
                    'plate_mm': list(plate.size_mm), 'triangles': triangles}
            if suffix == '3mf':
                info['colour_gradients'] = Q.gradient_recipe(plate)
                info['bambu'] = bambu
                Path(path).with_suffix('.colour_gradient.txt').write_text(
                    Q.recipe_text(info['colour_gradients']), encoding='utf8')
            sidecar.write_text(json.dumps(info, indent=2, ensure_ascii=False, default=float), encoding='utf8')
        except Exception as exc:
            QMessageBox.warning(self, '3D export failed', str(exc))
            return
        message = f'{written.name}: {triangles:,} triangles, {plate.size_mm[0]:.0f} × {plate.size_mm[1]:.0f} mm'
        if notes or plate.notes:
            message += '\n' + '\n'.join(list(plate.notes) + list(notes))
        try:
            self.main_window._log('3D print: ' + message + f' → {written}', important=True)
        except Exception:
            pass
        self.info.setText('✓ Saved ' + message)


def p_res(dialog):
    return dialog.resolution.value()


def create_tool(main_window):
    return Print3DDialog(main_window)
