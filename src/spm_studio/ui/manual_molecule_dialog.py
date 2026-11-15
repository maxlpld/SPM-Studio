"""v32 manual molecule placement window.

Tick **Click on the scan to place**, click positions on the scan, then fine-tune
each molecule (X/Y in nm, rotation).  After two or more molecules, **Continue
chain** repeats the established spacing and rotation N more times.  The molecule
drawing is shown at true scale on the scan and exported at full quality.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QPushButton, QLabel,
                               QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QTableWidget, QTableWidgetItem,
                               QFileDialog, QHeaderView, QSlider, QGridLayout)
from spm_studio.shared.dialogs import MessageDialog as QMessageBox

from ..core.manual_molecules import (Molecule, continue_chain, nm_to_px, px_to_nm, content_box,
                                     save_positions, load_positions)


def _qimage_rgba(img):
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    return np.frombuffer(img.constBits(), dtype=np.uint8, count=img.sizeInBytes()).reshape(h, img.bytesPerLine() // 4, 4)[:, :w]


class ManualMoleculeDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.setObjectName('ManualMoleculePlacementV32')
        self.setWindowTitle('Manual molecule placement')
        self.resize(560, 820)
        self.mw = main_window
        self.molecules: list[Molecule] = []
        self.art = None            # trimmed QImage (visible molecule only)
        self.svg = None            # QSvgRenderer for vector export
        self.box_frac = (0., 0., 1., 1.)
        self.art_path = ''
        self._sync = False
        root = QVBoxLayout(self)
        help_ = QLabel('Choose a drawing and its size, then click on the scan to place. '
                       'Continue chain repeats spacing and rotation.')
        help_.setObjectName('hint')
        help_.setWordWrap(True)
        root.addWidget(help_)
        g = QGroupBox('Molecule'); f = QFormLayout(g)
        row = QHBoxLayout(); self.art_label = QLabel('no drawing'); b = QPushButton('Choose…'); b.clicked.connect(self.choose_art)
        row.addWidget(self.art_label, 1); row.addWidget(b); f.addRow('Drawing', row)
        self.width_nm = QDoubleSpinBox(); self.width_nm.setRange(0, 1000); self.width_nm.setDecimals(3); self.width_nm.setValue(1.5)
        self.height_nm = QDoubleSpinBox(); self.height_nm.setRange(0, 1000); self.height_nm.setDecimals(3); self.height_nm.setValue(0)
        self.height_nm.setSpecialValueText('auto (keep aspect)')
        for w in (self.width_nm, self.height_nm):
            w.setSuffix(' nm'); w.valueChanged.connect(self.update_overlay)
        f.addRow('Width (visible molecule)', self.width_nm); f.addRow('Height', self.height_nm)
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(10, 100); self.opacity.setValue(100)
        self.opacity.valueChanged.connect(self.update_overlay); f.addRow('Opacity', self.opacity)
        self.place = QCheckBox('Click on the scan to place a molecule'); self.place.toggled.connect(self._toggle_place)
        f.addRow(self.place)
        self.default_angle = QDoubleSpinBox(); self.default_angle.setRange(-360, 360); self.default_angle.setSuffix(' °')
        f.addRow('Rotation of new molecules', self.default_angle)
        root.addWidget(g)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['#', 'X (nm)', 'Y (nm)', 'Rotation (°)'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemSelectionChanged.connect(self._selected)
        root.addWidget(self.table, 1)
        g = QGroupBox('Selected molecule'); grid = QGridLayout(g)
        self.sx = QDoubleSpinBox(); self.sy = QDoubleSpinBox(); self.sa = QDoubleSpinBox()
        for w, suf in ((self.sx, ' nm'), (self.sy, ' nm'), (self.sa, ' °')):
            w.setRange(-1e5, 1e5); w.setDecimals(3); w.setSuffix(suf); w.valueChanged.connect(self._edit_selected)
        grid.addWidget(QLabel('X'), 0, 0); grid.addWidget(self.sx, 0, 1)
        grid.addWidget(QLabel('Y'), 0, 2); grid.addWidget(self.sy, 0, 3)
        grid.addWidget(QLabel('Rotation'), 1, 0); grid.addWidget(self.sa, 1, 1)
        self.step = QDoubleSpinBox(); self.step.setRange(.001, 100); self.step.setValue(.05); self.step.setDecimals(3); self.step.setSuffix(' nm')
        grid.addWidget(QLabel('Nudge step'), 1, 2); grid.addWidget(self.step, 1, 3)
        nud = QHBoxLayout()
        for text, d in (('←', (-1, 0, 0)), ('→', (1, 0, 0)), ('↑', (0, -1, 0)), ('↓', (0, 1, 0)), ('⟲ 5°', (0, 0, 5)), ('⟳ 5°', (0, 0, -5))):
            b = QPushButton(text); b.clicked.connect(lambda _=False, d=d: self.nudge(*d)); nud.addWidget(b)
        grid.addLayout(nud, 2, 0, 1, 4)
        act = QHBoxLayout()
        for text, slot in (('Duplicate', self.duplicate), ('Delete', self.delete), ('Clear all', self.clear)):
            b = QPushButton(text); b.clicked.connect(slot); act.addWidget(b)
        grid.addLayout(act, 3, 0, 1, 4)
        root.addWidget(g)
        g = QGroupBox('Continue chain'); h = QHBoxLayout(g)
        self.chain_n = QSpinBox(); self.chain_n.setRange(1, 500); self.chain_n.setValue(5); self.chain_n.setPrefix('+ ')
        self.chain_mode = QComboBox(); self.chain_mode.addItem('step of the last two', 'last'); self.chain_mode.addItem('average step of the chain', 'average')
        self.chain_clip = QCheckBox('stop at scan edge'); self.chain_clip.setChecked(True)
        b = QPushButton('Continue chain'); b.setObjectName('ContinueChainV32'); b.clicked.connect(self.extend_chain)
        for w in (self.chain_n, self.chain_mode, self.chain_clip, b):
            h.addWidget(w)
        root.addWidget(g)
        exp = QHBoxLayout()
        for text, slot in (('Export scan with molecules…', self.export), ('Save positions…', self.save), ('Load positions…', self.load)):
            b = QPushButton(text); b.clicked.connect(slot); exp.addWidget(b)
        root.addLayout(exp)
        self.status = QLabel(''); self.status.setWordWrap(True); root.addWidget(self.status)

    # ------------------------------------------------------------ geometry
    def _geo(self):
        g = self.mw.viewer.geometry
        if g is None:
            return None, None
        ny, nx = g.shape
        size = (g.size_m[0] * 1e9, g.size_m[1] * 1e9) if g.size_m else (float(nx), float(ny))
        return (ny, nx), size

    def _size_nm(self):
        w = self.width_nm.value(); h = self.height_nm.value()
        if self.art is not None and self.art.width() > 0:
            aspect = self.art.width() / self.art.height()
            if h <= 0 and w > 0:
                h = w / aspect
            if w <= 0 and h > 0:
                w = h * aspect
        return max(w, 1e-6), max(h if h > 0 else w, 1e-6)

    # ------------------------------------------------------------ artwork
    def choose_art(self):
        fn, _ = QFileDialog.getOpenFileName(self, 'Molecule drawing', str(Path(self.art_path).parent if self.art_path else Path.home()),
                                            'Drawings (*.svg *.png *.jpg *.jpeg *.tif *.tiff)')
        if fn:
            self.load_art(fn)

    def load_art(self, fn):
        self.svg = None
        if fn.lower().endswith('.svg'):
            from PySide6.QtSvg import QSvgRenderer
            r = QSvgRenderer(fn)
            if not r.isValid():
                QMessageBox.warning(self, 'Drawing', 'Cannot read this SVG.'); return
            vb = r.viewBoxF(); aspect = vb.width() / vb.height() if vb.height() > 0 else 1.
            W = 1600; img = QImage(W, max(1, int(W / aspect)), QImage.Format.Format_ARGB32); img.fill(QColor(0, 0, 0, 0))
            p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing, True); r.render(p); p.end()
            self.svg = r
        else:
            img = QImage(fn)
            if img.isNull():
                QMessageBox.warning(self, 'Drawing', 'Cannot read this image.'); return
            img = img.convertToFormat(QImage.Format.Format_ARGB32)
        x0, y0, x1, y1 = content_box(_qimage_rgba(img))
        self.box_frac = (x0 / img.width(), y0 / img.height(), x1 / img.width(), y1 / img.height())
        self.art = img.copy(x0, y0, x1 - x0, y1 - y0)
        self.art_path = fn
        trimmed = (x0, y0, x1, y1) != (0, 0, img.width(), img.height())
        self.art_label.setText(f'{Path(fn).name} · {self.art.width()}×{self.art.height()} px' + (' (margins trimmed)' if trimmed else ''))
        self.update_overlay()

    # ------------------------------------------------------------ placement
    def _toggle_place(self, on):
        self.mw.viewer.set_roi_tool('point' if on else 'pan')
        self.status.setText('Click on the scan to add molecules.' if on else '')

    def add_at_px(self, col, row):
        shape, size = self._geo()
        if shape is None:
            return
        x, y = px_to_nm(col, row, shape, size)
        self.molecules.append(Molecule(x, y, self.default_angle.value()))
        self._refresh_table(select=len(self.molecules) - 1)

    def _refresh_table(self, select=None):
        self._sync = True
        self.table.setRowCount(len(self.molecules))
        for i, m in enumerate(self.molecules):
            for c, v in enumerate((str(i + 1), f'{m.x_nm:.3f}', f'{m.y_nm:.3f}', f'{m.angle_deg:.2f}')):
                it = QTableWidgetItem(v); it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, c, it)
        if select is not None and 0 <= select < len(self.molecules):
            self.table.selectRow(select)
        self._sync = False
        self._selected()
        self.update_overlay()

    def _current(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return rows[0] if rows else None

    def _selected(self):
        i = self._current()
        if i is None or i >= len(self.molecules):
            return
        self._sync = True
        m = self.molecules[i]
        self.sx.setValue(m.x_nm); self.sy.setValue(m.y_nm); self.sa.setValue(m.angle_deg)
        self._sync = False
        self.update_overlay()

    def _edit_selected(self):
        if self._sync:
            return
        i = self._current()
        if i is None:
            return
        self.molecules[i] = Molecule(self.sx.value(), self.sy.value(), self.sa.value())
        self._refresh_table(select=i)

    def nudge(self, dx, dy, da):
        i = self._current()
        if i is None:
            return
        s = self.step.value()
        self.molecules[i] = self.molecules[i].moved(dx * s, dy * s, da)
        self._refresh_table(select=i)

    def duplicate(self):
        i = self._current()
        if i is None:
            return
        self.molecules.append(self.molecules[i].moved(self.step.value() * 10, 0, 0))
        self._refresh_table(select=len(self.molecules) - 1)

    def delete(self):
        i = self._current()
        if i is None:
            return
        self.molecules.pop(i)
        self._refresh_table(select=min(i, len(self.molecules) - 1))

    def clear(self):
        self.molecules.clear(); self._refresh_table()

    def extend_chain(self):
        _, size = self._geo()
        try:
            new, added = continue_chain(self.molecules, self.chain_n.value(), self.chain_mode.currentData(),
                                        bounds_nm=size if self.chain_clip.isChecked() else None)
        except ValueError as exc:
            QMessageBox.information(self, 'Continue chain', str(exc)); return
        self.molecules = new
        self._refresh_table(select=len(new) - 1)
        self.status.setText(f'Added {added} molecule(s)' + ('' if added == self.chain_n.value() else ' (stopped at the scan edge)'))

    # ------------------------------------------------------------ drawing
    def overlay_items(self):
        shape, size = self._geo()
        if shape is None or self.art is None:
            return []
        w_nm, h_nm = self._size_nm()
        ny, nx = shape
        out = []
        for m in self.molecules:
            c, r = nm_to_px(m.x_nm, m.y_nm, shape, size)
            out.append((c, r, m.angle_deg, w_nm / size[0] * nx, h_nm / size[1] * ny))
        return out

    def update_overlay(self, *_):
        v = self.mw.viewer
        v.molecule_overlay = {'art': self.art, 'items': self.overlay_items(), 'selected': self._current(),
                              'opacity': self.opacity.value() / 100.} if self.art is not None else None
        v.update()

    def closeEvent(self, event):
        self.place.setChecked(False)
        super().closeEvent(event)

    # ------------------------------------------------------------ export / io
    def export(self):
        v = self.mw.viewer
        if v.image is None or v.geometry is None or not self.molecules or self.art is None:
            QMessageBox.information(self, 'Export', 'Open a scan, choose a drawing and place molecules first.'); return
        scan = self.mw.scan
        fn, _ = QFileDialog.getSaveFileName(self, 'Export scan with molecules',
                                            str(scan.path.with_name(scan.path.stem + '_molecules.svg')),
                                            'SVG (*.svg);;PDF (*.pdf);;PNG (*.png)')
        if not fn:
            return
        from ..core.export import render_tight
        from ..core.painting import paint_frame
        style = self.mw._plot_profile_for_run()
        dpi = max(600, int(style.get('dpi', 600)))
        transparent = bool(style.get('transparent_background', False))
        ny, nx = v.geometry.shape
        sx, sy = v.geometry.size_m if v.geometry.size_m else (nx, ny)
        W = int(140 / 25.4 * dpi); H = int(W / (sx / sy) * 1.18) + int(dpi * .5)
        items = self.overlay_items(); opacity = self.opacity.value() / 100.
        fx0, fy0, fx1, fy1 = self.box_frac
        svg, art = self.svg, self.art

        def draw(painter):
            rect = paint_frame(painter, v.image, v.bounds, v.channel, v.unit, v.geometry, v.style, QRectF(0, 0, W, H), [],
                               background='transparent' if transparent else '#ffffff',
                               font_pt=float(style.get('label_size', 9)), display_zero=v.display_zero)
            k = rect.width() / nx
            painter.setOpacity(opacity)
            for c, r, ang, wpx, hpx in items:
                painter.save()
                painter.translate(rect.left() + (c + .5) * k, rect.top() + (r + .5) * rect.height() / ny)
                painter.rotate(-ang)
                w, h = wpx * k, hpx * rect.height() / ny
                target = QRectF(-w / 2, -h / 2, w, h)
                if svg is not None:      # vector molecule; trimmed box mapped exactly on target
                    fw, fh = w / max(1e-9, fx1 - fx0), h / max(1e-9, fy1 - fy0)
                    painter.setClipRect(target)
                    svg.render(painter, QRectF(-w / 2 - fx0 * fw, -h / 2 - fy0 * fh, fw, fh))
                else:
                    painter.drawImage(target, art)
                painter.restore()
            painter.setOpacity(1.)

        info = render_tight(fn, draw, W, H, dpi, transparent=transparent)
        save_positions(self.molecules, fn + '.molecules.json', meta=self._meta())
        self.status.setText(f"Saved {fn} ({info['size_px'][0]}×{info['size_px'][1]} px) + positions")

    def _meta(self):
        w, h = self._size_nm()
        return {'scan': str(self.mw.scan.path) if self.mw.scan else '', 'drawing': self.art_path,
                'molecule_size_nm': [w, h], 'coordinates': 'nm from the scan top-left corner, x right, y down; '
                'rotation counter-clockwise in degrees'}

    def save(self):
        if not self.molecules:
            return
        scan = self.mw.scan
        fn, _ = QFileDialog.getSaveFileName(self, 'Save positions', str(scan.path.with_name(scan.path.stem + '_molecules.json')),
                                            'JSON (*.json);;CSV (*.csv)')
        if fn:
            save_positions(self.molecules, fn, meta=self._meta()); self.status.setText(f'Saved {fn}')

    def load(self):
        scan = self.mw.scan
        fn, _ = QFileDialog.getOpenFileName(self, 'Load positions', str(scan.path.parent if scan else Path.home()), 'JSON (*.json)')
        if not fn:
            return
        try:
            mols, meta = load_positions(fn)
        except Exception as exc:
            QMessageBox.warning(self, 'Load positions', str(exc)); return
        self.molecules = mols
        if meta.get('drawing') and Path(meta['drawing']).is_file() and self.art is None:
            self.load_art(meta['drawing'])
        if meta.get('molecule_size_nm'):
            self.width_nm.setValue(float(meta['molecule_size_nm'][0])); self.height_nm.setValue(float(meta['molecule_size_nm'][1]))
        self._refresh_table(select=0)
