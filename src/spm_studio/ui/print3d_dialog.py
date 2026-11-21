"""Tools › 3D print: STL / STEP relief of a scan channel with a 3D colour bar, live 3D preview."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, QSettings
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QFormLayout, QComboBox, QDoubleSpinBox, QSpinBox,
                               QCheckBox, QLineEdit, QPushButton, QLabel, QGroupBox, QFileDialog, QScrollArea,
                               QWidget, QSizePolicy, QMessageBox)

from ..core import print3d as P

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
        self.setWindowTitle('3D print — STL / STEP relief with 3D colour bar')
        self.setObjectName('Print3DDialogV0012')
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1250, 780)
        self.settings = QSettings()
        self.model = None
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
        self.resolution = dspin(.05, 2, .25, .05, 2)
        self.smooth = dspin(0, 10, 0, .5, 1, ' px')
        self.invert = QCheckBox('Invert (low values high)')
        f.addRow('Scan width', self.width_mm)
        f.addRow('Base plate', self.base_mm)
        f.addRow('Relief (low → high)', self.relief_mm)
        f.addRow('Grid resolution', self.resolution)
        f.addRow('Smoothing', self.smooth)
        f.addRow('', self.invert)
        form_layout.addWidget(box)

        box = QGroupBox('Colour-bar range (= printed heights)')
        f = QFormLayout(box)
        self.range_mode = QComboBox()
        self.range_mode.addItem('Percentiles of the scan', 'percentile')
        self.range_mode.addItem('Values (display unit)', 'absolute')
        self.low = dspin(-1e9, 1e9, 1, 1, 3, '')
        self.high = dspin(-1e9, 1e9, 99, 1, 3, '')
        self.range_hint = QLabel('Values outside the range are printed flat (cuts a too high peak).')
        self.range_hint.setWordWrap(True)
        self.range_hint.setObjectName('hint')
        f.addRow('Mode', self.range_mode)
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
        self.font = dspin(1.5, 15, 4, .5, 1)
        self.label_mm = dspin(.2, 5, .8, .1, 1)
        self.overlay_mm = dspin(.2, 10, 1, .1, 1)
        self.title = QLineEdit()
        self.title.setPlaceholderText('optional, embossed above the scan')
        self.scale_bar = QCheckBox('Scale bar')
        self.scale_bar.setChecked(True)
        f.addRow('Colour bar', self.colorbar)
        f.addRow('Bar width', self.bar_width)
        f.addRow('Gap', self.bar_gap)
        f.addRow('Ticks', self.ticks)
        f.addRow('Text size', self.font)
        f.addRow('Text height', self.label_mm)
        f.addRow('Vectors / molecules height', self.overlay_mm)
        f.addRow('Title', self.title)
        f.addRow('', self.scale_bar)
        form_layout.addWidget(box)
        form_layout.addStretch(1)
        buttons = QHBoxLayout()
        self.save_stl = QPushButton('Save STL…')
        self.save_stl.setProperty('primary', True)
        self.save_step = QPushButton('Save STEP…')
        self.save_stl.clicked.connect(lambda: self.export('stl'))
        self.save_step.clicked.connect(lambda: self.export('step'))
        buttons.addWidget(self.save_stl)
        buttons.addWidget(self.save_step)
        form_layout.addLayout(buttons)
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
        for w in (self.source, self.channel, self.trace, self.range_mode, self.colorbar):
            w.currentIndexChanged.connect(self.schedule)
        for w in (self.width_mm, self.base_mm, self.relief_mm, self.resolution, self.smooth, self.low, self.high,
                  self.bar_width, self.bar_gap, self.font, self.label_mm, self.overlay_mm):
            w.valueChanged.connect(self.schedule)
        self.ticks.valueChanged.connect(self.schedule)
        for w in (self.processed, self.invert, self.scale_bar):
            w.toggled.connect(self.schedule)
        self.title.textChanged.connect(self.schedule)
        self.result_file.editingFinished.connect(self.schedule)
        self.range_mode.currentIndexChanged.connect(self._range_mode_changed)
        self.source.currentIndexChanged.connect(self._source_changed)
        self._source_changed()
        self.schedule()

    # ------------------------------------------------------------------ settings
    _KEYS = ('width_mm', 'base_mm', 'relief_mm', 'resolution', 'smooth', 'bar_width', 'bar_gap', 'font',
             'label_mm', 'overlay_mm')

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

    def _store(self):
        for key in self._KEYS:
            self.settings.setValue(f'print3d/{key}', getattr(self, key).value())
        self.settings.setValue('print3d/colorbar', self.colorbar.currentData())

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

    def _pick_result(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Lattice / molecule result', str(Path.home()), 'JSON (*.json)')
        if path:
            self.result_file.setText(path)
            self.schedule()

    def _channel_array(self, channel, trace, processed):
        mw = self.main_window
        scan = mw.scan
        cd = scan.channels[channel]
        if trace not in cd.traces:
            trace = next(iter(cd.traces))
        data = np.asarray(cd.get(trace), float)
        if processed:
            key = (str(scan.path), channel, trace)
            steps = list(getattr(mw, 'pipelines', {}).get(key, []))
            try:
                if mw.inspector.channel.currentText() == channel and mw.inspector.selected_trace() == trace:
                    steps = list(mw.inspector.steps())
            except Exception:
                pass
            if steps:
                from ..core.processing import apply
                data = apply(data, steps)
        return data, cd

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
        return {'width_mm': self.width_mm.value(), 'base_mm': self.base_mm.value(),
                'relief_mm': self.relief_mm.value(), 'resolution_mm': self.resolution.value(),
                'range_mode': self.range_mode.currentData(),
                'low': self.low.value() / factor if absolute else self.low.value(),
                'high': self.high.value() / factor if absolute else self.high.value(),
                'invert': self.invert.isChecked(), 'smooth_px': self.smooth.value(),
                'colorbar': self.colorbar.currentData(), 'colorbar_width_mm': self.bar_width.value(),
                'colorbar_gap_mm': self.bar_gap.value(), 'colorbar_ticks': self.ticks.value(),
                'font_mm': self.font.value(), 'label_mm': self.label_mm.value(),
                'overlay_mm': self.overlay_mm.value(), 'title': self.title.text(),
                'scale_bar': self.scale_bar.isChecked(), 'unit': unit, 'value_scale': factor}

    # ------------------------------------------------------------------ preview
    def schedule(self, *_):
        self._timer.start()

    def _build(self, preview=False):
        data, size_nm, unit, factor, overlay = self._data()
        p = self.params(factor, unit)
        if preview:
            # a coarser grid keeps the live preview fast; the files use the chosen resolution
            plate = p['width_mm'] * 1.6
            p['resolution_mm'] = max(p['resolution_mm'], plate / 260)
        return P.build_model(data, size_nm, p, overlay), p

    def update_preview(self):
        try:
            model, p = self._build(preview=True)
        except Exception as exc:
            self.figure.clear()
            self.canvas.draw_idle()
            self.info.setText('⚠ ' + str(exc))
            self.save_stl.setEnabled(False)
            self.save_step.setEnabled(False)
            return
        self.save_stl.setEnabled(True)
        self.save_step.setEnabled(True)
        z, cell = P.decimate(model.z, model.cell_mm, 22000)
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
        shade = light.shade(z, cmap=__import__('matplotlib').colormaps['Greys_r'], vert_exag=1, blend_mode='soft',
                            vmin=0, vmax=float(z.max()))
        ax.plot_surface(X, Y, z, facecolors=shade, rstride=1, cstride=1, linewidth=0, antialiased=False, shade=False)
        W, H = model.size_mm
        top = float(z.max())
        ax.set_box_aspect((W, H, max(top, 1e-3) * 1.0))
        ax.set_xlabel('mm')
        ax.set_ylabel('mm')
        ax.set_zlabel('mm')
        ax.view_init(*view)
        self.figure.tight_layout()
        self.canvas.draw_idle()
        cells = int(np.ceil(W / p_res(self)) * np.ceil(H / p_res(self)))
        lo, hi = model.low * p['value_scale'], model.high * p['value_scale']
        text = (f'Plate {W:.0f} × {H:.0f} mm, highest point {top:.1f} mm · range {lo:.4g} … {hi:.4g} {p["unit"]} '
                f'→ {p["base_mm"]:.1f} … {p["base_mm"] + p["relief_mm"]:.1f} mm · STL ≈ {2 * cells / 1e6:.2f} M '
                f'triangles at {p_res(self):.2f} mm (preview is coarser). Drag the view to rotate.')
        if model.notes:
            text += '\n' + ' · '.join(model.notes)
        self.info.setText(text)

    def export(self, fmt):
        suffix = 'stl' if fmt == 'stl' else 'step'
        scan = getattr(self.main_window, 'scan', None)
        folder = Path(getattr(self.main_window, 'last_export_dir', Path.home()) or Path.home())
        name = (scan.path.stem + '_' + self.channel.currentText().replace(' ', '_') if scan else 'relief')
        path, _ = QFileDialog.getSaveFileName(self, f'Save {suffix.upper()}', str(folder / f'{name}.{suffix}'),
                                              f'{suffix.upper()} (*.{suffix})')
        if not path:
            return
        try:
            model, p = self._build(preview=False)
            written, triangles, notes = P.export(model, path, suffix)
            sidecar = Path(path).with_suffix('.print3d.json')
            sidecar.write_text(json.dumps({'source': self.source.currentData(),
                                           'scan': str(scan.path) if scan else None,
                                           'channel': self.channel.currentText(), 'parameters': p,
                                           'range': [model.low, model.high], 'plate_mm': list(model.size_mm),
                                           'triangles': triangles}, indent=2, ensure_ascii=False, default=float),
                               encoding='utf8')
        except Exception as exc:
            QMessageBox.warning(self, '3D export failed', str(exc))
            return
        message = f'{written.name}: {triangles:,} triangles, {model.size_mm[0]:.0f} × {model.size_mm[1]:.0f} mm'
        if notes:
            message += '\n' + '\n'.join(notes)
        try:
            self.main_window._log('3D print: ' + message + f' → {written}', important=True)
        except Exception:
            pass
        self.info.setText('✓ Saved ' + message)


def p_res(dialog):
    return dialog.resolution.value()


def create_tool(main_window):
    return Print3DDialog(main_window)
