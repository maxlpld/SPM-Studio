"""Microscope X/Y calibration from lattice images of a known reference crystal.

Uses every scan open in SPM Studio (same channel as the active one), detects the primitive
lattice of each with the Lattice measurements tool's FFT engine, and fits the new X and Y
piezo calibration constants (see calibration_core.py for the model).

1.4: X/Y can also come from the Au(111) herringbone reconstruction (herringbone.py), and Z from
monatomic steps on the topography channel (z_steps.py, z_report.py).
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import calibration_core as cc  # noqa: E402


# --------------------------------------------------------------------------- lattice engine
def _lattice_solver():
    """``solve_roi`` of the installed Lattice measurements tool (same scripts folder)."""
    candidates = [HERE.parent / 'lattice_measurements', HERE / 'lattice_measurements']
    for folder in candidates:
        path = folder / 'roi_pipeline.py'
        if path.is_file():
            spec = importlib.util.spec_from_file_location('_calib_roi_pipeline', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.solve_roi
    raise RuntimeError('The "Lattice measurements" tool was not found next to this tool in the Scripts folder. '
                       'It provides the lattice detection; install / restore it and run again.')


def _processing_steps(ctx):
    from spm_studio.core.models import ProcessingStep
    steps = []
    for item in getattr(ctx, 'processing', None) or []:
        try:
            steps.append(ProcessingStep(**{k: v for k, v in item.items() if k in ('operation', 'params', 'enabled')}))
        except TypeError:
            continue
    return steps


def _detection_image(data, steps):
    """Same processing as the active scan; a plane is removed if none is set (detection only)."""
    from spm_studio.core.processing import apply
    from spm_studio.core.models import ProcessingStep
    a = np.asarray(data, float)
    if steps:
        a = apply(a, steps)
    else:
        a = apply(a, [ProcessingStep('plane', {}, True)])
    if not np.isfinite(a).all():
        finite = np.isfinite(a)
        if finite.mean() < .6:
            raise ValueError('more than 40 % of the image is missing (aborted scan?)')
        a = np.where(finite, a, np.nanmedian(a))
    return a


def _crop_rows_of_aborted_scan(data):
    """Keep only complete rows (an aborted scan stores NaN rows)."""
    a = np.asarray(data, float)
    good = np.isfinite(a).mean(axis=1) > .98
    if good.all() or good.sum() < 32:
        return a, slice(None)
    idx = np.flatnonzero(good)
    sl = slice(idx[0], idx[-1] + 1)
    return a[sl], sl


# --------------------------------------------------------------------------- inputs
def _all_rois(ctx):
    """Every selection drawn on the active scan (v1.4 keeps several: lines, rectangles)."""
    rois = list(getattr(ctx, 'rois', None) or [])
    roi = getattr(ctx, 'roi', None)
    if roi is not None and not any(r.kind == roi.kind and tuple(map(tuple, r.points_px)) ==
                                   tuple(map(tuple, roi.points_px)) for r in rois):
        rois.append(roi)
    return rois


def _lattice_rectangle(ctx):
    """The rectangle that limits the lattice measurement: the current selection if it is a rectangle,
    else the last rectangle drawn."""
    roi = getattr(ctx, 'roi', None)
    if roi is not None and roi.kind == 'rectangle' and len(roi.points_px) == 2:
        return roi
    rects = [r for r in _all_rois(ctx) if r.kind == 'rectangle' and len(r.points_px) == 2]
    return rects[-1] if rects else None


def _scan_entries(ctx):
    """[(path, is_current)] for every open file (the active scan first)."""
    paths = [Path(ctx.scan_path)]
    for p in ctx.source_paths or []:
        p = Path(p)
        if p.suffix.lower() in ('.sxm', '.gwy') and p.resolve() not in {q.resolve() for q in paths}:
            paths.append(p)
    return paths


def _traces(ctx, available):
    mode = str(ctx.parameters.get('traces', 'Active trace only'))
    if mode.startswith('Forward and backward'):
        return [t for t in ('forward', 'backward') if t in available] or [ctx.direction]
    return [ctx.direction] if ctx.direction in available else list(available)[:1]


def _fallback(ctx):
    x = float(ctx.parameters.get('previous_cx_nm_per_v', 0) or 0)
    y = float(ctx.parameters.get('previous_cy_nm_per_v', 0) or 0)
    return (x * 1e-9 if x > 0 else None), (y * 1e-9 if y > 0 else None)


def collect(ctx, ref, log):
    """Measure the lattice on every usable scan / trace. Returns (scans, skipped)."""
    solve_roi = _lattice_solver()
    steps = _processing_steps(ctx)
    override = bool(ctx.parameters.get('override_metadata', False))
    fallback = _fallback(ctx)
    scans, skipped = [], []
    entries = _scan_entries(ctx)
    from spm_studio.core.io import read_scan
    for n, path in enumerate(entries):
        ctx.progress(5 + 55 * n / max(1, len(entries)), f'Lattice of {path.name}')
        current = n == 0
        try:
            if current:
                metadata = ctx.metadata or {}
                geometry = ctx.geometry
                arrays = {t: ctx.image(ctx.channel, t) for t in ('forward', 'backward')
                          if f'{ctx.channel}|{t}' in ctx.arrays}
                arrays[ctx.direction] = ctx.data
            else:
                scan = read_scan(path)
                if ctx.channel not in scan.channels:
                    skipped.append((path.name, f'no channel {ctx.channel}'))
                    continue
                channel = scan.channels[ctx.channel]
                metadata = scan.metadata or {}
                geometry = channel.geometry
                arrays = dict(channel.traces)
        except Exception as exc:
            skipped.append((path.name, f'could not be read: {exc}'))
            continue
        if not geometry.size_m:
            skipped.append((path.name, 'no physical scan size in the file'))
            continue
        header = cc.header_dict(metadata)
        found = cc.calibration_from_header(header)
        acquisition = cc.acquisition_from_header(header)
        cx, cy = found['cx'], found['cy']
        if override or cx is None or cy is None:
            cx = fallback[0] if (override or cx is None) and fallback[0] else cx
            cy = fallback[1] if (override or cy is None) and fallback[1] else cy
        relative = cx is None or cy is None
        if relative:
            # Unknown previous calibration: work with 1 m/V so the result is a pure
            # correction factor (new = factor × previous).
            cx, cy = 1.0, 1.0
        slow = str(geometry.scan_direction or '').strip().lower()
        angle = float(geometry.angle_deg or 0.0)
        for trace in _traces(ctx, arrays):
            label = f'{path.stem} · {trace}'
            try:
                raw = np.asarray(arrays[trace], float)
                ny, nx = raw.shape
                active = current and trace == ctx.direction
                source = np.asarray(ctx.data, float) if active else raw
                region = ''
                rect = _lattice_rectangle(ctx) if active else None
                if rect is not None:
                    (c0, r0), (c1, r1) = rect.points_px
                    x0, x1 = sorted((max(0, int(round(c0))), min(nx, int(round(c1)))))
                    y0, y1 = sorted((max(0, int(round(r0))), min(ny, int(round(r1)))))
                    if min(x1 - x0, y1 - y0) >= 32:
                        source = source[y0:y1, x0:x1]
                        region = ' (selected rectangle)'
                cropped, _rows = _crop_rows_of_aborted_scan(source)
                # The active trace is already processed as shown; other traces / scans get
                # the same processing steps (or a plane when none is set).
                data = (_detection_image(cropped, []) if not steps else
                        np.where(np.isfinite(cropped), cropped, np.nanmedian(cropped))) if active \
                    else _detection_image(cropped, steps)
                width_nm = geometry.size_m[0] * 1e9 * data.shape[1] / nx
                height_nm = geometry.size_m[1] * 1e9 * data.shape[0] / ny
                if region:
                    log(f'{label}: lattice measured in the selected rectangle only')
                result = solve_roi(data, {'pixel_size_nm': [width_nm / data.shape[1], height_nm / data.shape[0]]})
            except Exception as exc:
                skipped.append((label, f'no lattice found ({exc})'))
                continue
            basis = np.asarray(result['basis_local_nm'], float)
            a, b, gamma = cc.cell_parameters(basis)
            gradient = cc.time_gradient(trace, slow, (width_nm, height_nm), data.shape, acquisition['line_time'])
            scans.append(cc.ScanLattice(label, basis, angle, cx, cy, (width_nm, height_nm), data.shape,
                                        slow, trace, current and trace == ctx.direction,
                                        {'path': str(path), 'relative': relative,
                                         'line_time': acquisition['line_time'],
                                         'header_drift': acquisition['drift'],
                                         'drift_status': acquisition['drift_status'],
                                         'timestamp': acquisition['timestamp'],
                                         'offset_nm': acquisition['offset_nm'],
                                         'calibration_keys': found['source_keys'],
                                         'drift_correction': found['drift_correction'],
                                         'second_order': found['second_order'],
                                         'fft_score': result.get('score'), 'n_peaks': result.get('peak_count'),
                                         # exactly the region that was measured, for the overlay figure
                                         'display': (np.asarray(cropped, float) if active else data)},
                                        time_gradient=gradient))
            log(f'{label}: detected a = {a * 10:.3f} Å, b = {b * 10:.3f} Å, γ = {gamma:.2f}°, fast axis '
                f'{scans[-1].fast_axis}, slow {slow or "?"}, previous calibration '
                + ('unknown (relative factors)' if relative else f'X {cx * 1e9:.4g} nm/V, Y {cy * 1e9:.4g} nm/V'))
    return scans, skipped


def select_reference(ctx, scans, skipped, ref, log, automatic=None):
    """Match the reference description to the detected cells, then drop the scans that are off."""
    tolerance = float(ctx.parameters.get('max_deviation_percent', 25.0)) / 100
    if automatic is None:
        automatic = bool(ctx.parameters.get('auto_match_cell', True))
    cells = [cc.cell_parameters(s.basis_image_nm) for s in scans]
    chosen, why, median_dev = cc.choose_reference(cells, ref, tolerance, automatic)
    if chosen is not ref:
        log(f'Reference cell used: {why}. (Typed / preset cell {ref.a_nm * 10:.4f} Å matched the detected lattice '
            f'only within {np.median([cc.cell_deviation(a, b, ref) for a, b, _g in cells]) * 100:.0f} %; '
            f'this description matches within '
            f'{median_dev * 100:.1f} %.)', 'warning')
    kept = []
    for s, (a, b, gamma) in zip(scans, cells):
        dev = cc.cell_deviation(a, b, chosen)
        if dev > tolerance:
            skipped.append((s.name, f'detected cell {a * 10:.3f} × {b * 10:.3f} Å, γ {gamma:.1f}° differs by '
                                    f'{dev * 100:.0f} % from the reference {chosen.a_nm * 10:.3f} × '
                                    f'{chosen.b_nm * 10:.3f} Å (> {tolerance * 100:.0f} %) — not used'))
        else:
            kept.append(s)
    return kept, chosen, why


def _no_scan_message(ref, cells, tolerance):
    lines = ['No scan could be used for the calibration.']
    for name, (a, b, g) in cells:
        lines.append(f'  {name}: detected {a * 10:.3f} × {b * 10:.3f} Å, γ {g:.1f}°')
    lines.append(f'  Reference: {ref.a_nm * 10:.4f} × {ref.b_nm * 10:.4f} Å'
                 + (f', γ {ref.gamma_deg:g}°' if ref.gamma_deg else '') + f'; tolerance {tolerance * 100:.0f} %.')
    if cells:
        a, b, _g = cells[0][1]
        ratio = (a + b) / (ref.a_nm + ref.b_nm)
        lines.append(f'  Detected / reference = {ratio:.3f}. Check that a is the SURFACE cell seen in the image '
                     '(KBr(001): 4.67 Å = a0/√2, not a0 = 6.60 Å), or raise “Reject lattices off by more than (%)” '
                     'if the microscope is very far from calibrated.')
    return '\n'.join(lines)


# --------------------------------------------------------------------------- figure of the active scan
def _mix(color, other, t):
    from matplotlib.colors import to_rgb
    c, o = np.array(to_rgb(color)), np.array(to_rgb(other))
    r, g, b = (1 - t) * c + t * o
    return '#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255))


def make_decorator(old_basis, new_basis, new_size_nm, rows_lattice, rows_calibration, colors, corners,
                   outlines=None, outline_shape=None, outline_color='#7ee081'):
    """Painter callback: old (pale, dashed) and new (dark, solid) a/b arrows + two legends.

    ``outlines`` (v1.4): polygons [(col, row), …] in the pixels of the drawn image (shape
    ``outline_shape``), e.g. the region where the herringbones were measured.
    """

    def decorate(painter, rect):
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QPen, QColor, QPolygonF, QFont, QFontMetricsF, QBrush, QPainter
        sx = rect.width() / new_size_nm[0]
        sy = rect.height() / new_size_nm[1]
        anchor = QPointF(rect.center())
        width = max(1.2, rect.width() * .0045)

        def arrow(vec, color, dashed, w):
            dx, dy = float(vec[0]) * sx, -float(vec[1]) * sy
            end = QPointF(anchor.x() + dx, anchor.y() + dy)
            outline = QPen(QColor(0, 0, 0, 150), w + 1.6)
            pen = QPen(QColor(color), w)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
                outline.setStyle(Qt.PenStyle.DashLine)
            for p in (outline, pen):
                painter.setPen(p)
                painter.drawLine(anchor, end)
            angle = math.atan2(dy, dx)
            head = max(6., rect.width() * .018)
            poly = QPolygonF([end, QPointF(end.x() - head * math.cos(angle - .45), end.y() - head * math.sin(angle - .45)),
                              QPointF(end.x() - head * math.cos(angle + .45), end.y() - head * math.sin(angle + .45))])
            painter.setPen(QPen(QColor(0, 0, 0, 150), 1))
            painter.setBrush(QColor(color))
            painter.drawPolygon(poly)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if outlines and outline_shape:
            ny_o, nx_o = outline_shape
            for poly in outlines:
                pts = QPolygonF([QPointF(rect.left() + (c + .5) / nx_o * rect.width(),
                                         rect.top() + (r + .5) / ny_o * rect.height()) for c, r in poly])
                for pen in (QPen(QColor(0, 0, 0, 150), width * 1.9), QPen(QColor(outline_color), width * .9)):
                    pen.setStyle(Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPolygon(pts)
        # new (solid, full colour) first, old (pale, dashed) on top so both stay visible
        for i in range(2):
            arrow(np.asarray(new_basis)[:, i], colors['new'][i], False, width * 1.25)
        for i in range(2):
            arrow(np.asarray(old_basis)[:, i], colors['old'][i], True, width * .8)

        font = QFont('DejaVu Sans')
        font.setPixelSize(max(9, int(rect.width() * .027)))
        bold = QFont(font)
        bold.setBold(True)

        def legend(rows, corner):
            # rows: [(label, old_text, new_text, old_color, new_color)]
            metrics, bmetrics = QFontMetricsF(font), QFontMetricsF(bold)
            line_h = metrics.height() * 1.22
            widths = [metrics.horizontalAdvance(f'{r[0]}  ' + (f'{r[1]} → ' if r[1] else '')) +
                      bmetrics.horizontalAdvance(r[2]) for r in rows]
            box_w = max(widths) + 14
            box_h = line_h * len(rows) + 8
            margin = 6
            x = rect.left() + margin if corner.endswith('left') else rect.right() - margin - box_w
            y = rect.top() + margin if corner.startswith('top') else rect.bottom() - margin - box_h
            if corner == 'bottom_right':
                y -= rect.height() * .10          # keep clear of the scale bar
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 140)))
            painter.drawRoundedRect(QRectF(x, y, box_w, box_h), 4, 4)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for k, (label, old, new, c_old, c_new) in enumerate(rows):
                yy = y + 4 + k * line_h
                cursor = x + 7
                painter.setFont(font)
                painter.setPen(QColor('#f2f2f2'))
                text = f'{label}  '
                painter.drawText(QRectF(cursor, yy, 400, line_h), int(Qt.AlignmentFlag.AlignLeft), text)
                cursor += metrics.horizontalAdvance(text)
                painter.setPen(QColor(c_old))
                text = f'{old} → ' if old else ''
                painter.drawText(QRectF(cursor, yy, 400, line_h), int(Qt.AlignmentFlag.AlignLeft), text)
                cursor += metrics.horizontalAdvance(text)
                painter.setFont(bold)
                painter.setPen(QColor(c_new))
                painter.drawText(QRectF(cursor, yy, 400, line_h), int(Qt.AlignmentFlag.AlignLeft), new)

        legend(rows_lattice, corners[0])
        legend(rows_calibration, corners[1])
        painter.restore()

    return decorate


def matplotlib_overlay(base, data, size_nm, old_basis, new_basis, rows, cal_rows, colors, corners, formats,
                       figure_title='', colorbar_label='', colormap='', unit='', outlines=None,
                       outline_color='#7ee081'):
    """Same content as the Export-panel overlay, drawn with Matplotlib (always available)."""
    import matplotlib
    matplotlib.use('Agg', force=False)
    from matplotlib.figure import Figure
    from matplotlib.offsetbox import AnchoredOffsetbox, HPacker, VPacker, TextArea
    from matplotlib import patheffects
    cmap = colormap if colormap and colormap in matplotlib.colormaps else 'gray'
    data = np.asarray(data, float)
    shown_unit = unit or ''
    finite_abs = np.abs(data[np.isfinite(data)])
    if unit == 'm' and finite_abs.size:
        data, shown_unit = (data * 1e12, 'pm') if np.percentile(finite_abs, 95) < 1e-9 else (data * 1e9, 'nm')
    elif unit == 'A' and finite_abs.size:
        data, shown_unit = (data * 1e12, 'pA') if np.percentile(finite_abs, 95) < 1e-9 else (data * 1e9, 'nA')
    elif unit == 'Hz':
        shown_unit = 'Hz'
    w, h = size_nm
    fig = Figure(figsize=(4.2, 4.2 * h / w + .7), dpi=200, layout='constrained')
    ax = fig.add_subplot()
    finite = data[np.isfinite(data)]
    lo, hi = (np.percentile(finite, [1, 99]) if finite.size else (0, 1))
    im = ax.imshow(data, extent=[0, w, 0, h], origin='upper', cmap=cmap, vmin=lo, vmax=hi, interpolation='nearest')
    ax.set_xticks([])
    ax.set_yticks([])
    cx, cy = w / 2, h / 2
    stroke = [patheffects.Stroke(linewidth=3, foreground='black', alpha=.6), patheffects.Normal()]
    ny_d, nx_d = data.shape
    for poly in outlines or ():
        xs = [(c + .5) / nx_d * w for c, _r in poly] + [(poly[0][0] + .5) / nx_d * w]
        ys = [h - (r + .5) / ny_d * h for _c, r in poly] + [h - (poly[0][1] + .5) / ny_d * h]
        line, = ax.plot(xs, ys, color=outline_color, lw=1.2, ls='--')
        line.set_path_effects(stroke)
    for basis, palette, dashed, lw in ((new_basis, colors['new'], False, 2.0), (old_basis, colors['old'], True, 1.1)):
        for i in range(2):
            vx, vy = np.asarray(basis)[:, i]
            arrow = ax.annotate('', (cx + vx, cy + vy), (cx, cy), arrowprops=dict(
                arrowstyle='-|>', color=palette[i], lw=lw, ls='--' if dashed else '-', shrinkA=0, shrinkB=0,
                mutation_scale=11))
            arrow.arrow_patch.set_path_effects(stroke)
    loc = {'top_left': 'upper left', 'top_right': 'upper right', 'bottom_left': 'lower left',
           'bottom_right': 'lower right'}

    def box(items, corner):
        lines = []
        for label, old_text, new_text, c_old, c_new in items:
            lines.append(HPacker(children=[
                TextArea(f'{label}  ', textprops=dict(color='#f2f2f2', size=7)),
                TextArea(f'{old_text} → ' if old_text else '', textprops=dict(color=c_old, size=7)),
                TextArea(new_text, textprops=dict(color=c_new, size=7, weight='bold'))], align='baseline', pad=0, sep=0))
        packed = VPacker(children=lines, align='left', pad=0, sep=2)
        anchored = AnchoredOffsetbox(loc=loc.get(corner, 'upper left'), child=packed, pad=.35, borderpad=.4,
                                     frameon=True)
        anchored.patch.set_facecolor('black')
        anchored.patch.set_alpha(.6)
        anchored.patch.set_edgecolor('none')
        anchored.patch.set_boxstyle('round,pad=0.2')
        ax.add_artist(anchored)
    box(rows, corners[0])
    box(cal_rows, corners[1])
    bar = 10 ** math.floor(math.log10(w / 4))
    bar = next(m * bar for m in (5, 2, 1) if m * bar <= w / 3)
    ax.plot([w * .95 - bar, w * .95], [h * .06, h * .06], color='white', lw=3, solid_capstyle='butt')
    ax.text(w * .95 - bar / 2, h * .08, f'{bar:g} nm', color='white', ha='center', va='bottom', fontsize=7,
            path_effects=[patheffects.withStroke(linewidth=2, foreground='black')])
    cb = fig.colorbar(im, ax=ax, location='bottom', fraction=.05, pad=.02, aspect=30)
    label = colorbar_label or 'Signal'
    cb.set_label(f'{label} ({shown_unit})' if shown_unit and shown_unit not in label else label, fontsize=7)
    cb.ax.tick_params(labelsize=6)
    if figure_title:
        fig.suptitle(figure_title, fontsize=9)
    written = []
    for fmt in formats:
        path = Path(f'{base}.{fmt}')
        fig.savefig(path, dpi=300 if fmt in ('png', 'jpg') else None)
        written.append(path)
    return written


def publication_figure(ctx, scan, fit, ref, fallback, log):
    from spm_studio.core import script_figures as figures
    p = ctx.parameters
    new_basis, matrix = cc.corrected_basis_image(scan, fit, fallback)
    shear = abs(matrix[0, 1]) + abs(matrix[1, 0])
    if shear > .005:
        log('The scan angle is not 0°/90° (or an axis skew was fitted): the image is drawn as a rectangle with '
            'corrected side lengths; the arrows are the exact corrected vectors.', 'warning')
    w, h = scan.size_nm
    new_size = (w * float(np.linalg.norm(matrix[:, 0])), h * float(np.linalg.norm(matrix[:, 1])))
    a0, b0, g0 = cc.cell_parameters(scan.basis_image_nm)
    a1, b1, g1 = cc.cell_parameters(new_basis)
    # One lattice vector is a few pixels on a large scan: draw N × a and N × b (stated in the legend).
    n_cells = max(1, int(round(.2 * min(new_size) / max(a1, b1, 1e-9))))
    ca = str(p.get('vector_a_color', '#16d8f5'))
    cb = str(p.get('vector_b_color', '#fbb748'))
    ccal = str(p.get('calibration_color', '#7ee081'))
    # Same hue: before = pale (mixed with white), after = the full, darker colour in bold.
    old = (_mix(ca, '#ffffff', .55), _mix(cb, '#ffffff', .55))
    new = (ca, cb)
    rows = [('a', f'{a0 * 10:.3f} Å', f'{a1 * 10:.3f} Å', old[0], new[0]),
            ('b', f'{b0 * 10:.3f} Å', f'{b1 * 10:.3f} Å', old[1], new[1]),
            ('γ', f'{g0:.1f}°', f'{g1:.1f}°', '#d8d8d8', '#ffffff')]
    if n_cells > 1:
        rows.append(('arrows', '', f'{n_cells} × a,  {n_cells} × b', '#d8d8d8', '#f2f2f2'))
    relative = scan.extra.get('relative')
    cx_old = scan.cx_old or fallback[0]
    cy_old = scan.cy_old or fallback[1]
    if relative:
        cal_rows = [('X', '×1', f'×{fit.cx / cx_old:.4f}', _mix(ccal, '#ffffff', .55), ccal),
                    ('Y', '×1', f'×{fit.cy / cy_old:.4f}', _mix(ccal, '#ffffff', .55), ccal)]
    else:
        cal_rows = [('X', f'{cx_old * 1e9:.4g}', f'{fit.cx * 1e9:.4g} nm/V', _mix(ccal, '#ffffff', .55),
                     ccal),
                    ('Y', f'{cy_old * 1e9:.4g}', f'{fit.cy * 1e9:.4g} nm/V', _mix(ccal, '#ffffff', .55),
                     ccal)]
    v_total = np.asarray(scan.drift_known, float) + np.asarray(fit.drift, float)
    if np.any(v_total):
        cal_rows.append(('drift', '', _fmt_drift(v_total), _mix(ccal, '#ffffff', .55), '#f2f2f2'))
    corners = (str(p.get('lattice_legend_corner', 'top_left')), str(p.get('calibration_legend_corner', 'top_right')))
    if corners[0] == corners[1]:
        corners = (corners[0], 'top_right' if corners[0] != 'top_right' else 'top_left')
    decorate = make_decorator(np.asarray(scan.basis_image_nm) * n_cells, new_basis * n_cells, new_size, rows, cal_rows,
                              {'old': old, 'new': new}, corners)
    cfg = getattr(ctx, 'plot_config', None) or {'schema_version': 1}
    style = figures.scan_display_style(cfg, ctx.channel, colormap_override=p.get('scan_colormap', ''))
    title = figures.colorbar_title(cfg, ctx.channel, '')
    data = np.asarray(scan.extra.get('display', ctx.data), float)
    formats = tuple(getattr(ctx, 'plot_formats', None) or ('svg',))
    base = ctx.output_dir / 'calibration_lattice_overlay'
    try:
        written = figures.export_scan_figure(base, scan_path=scan.extra.get('path') or ctx.scan_path,
                                             data=data, size_nm=new_size, channel=ctx.channel, unit=ctx.unit,
                                             plot_config=cfg, formats=formats, style=style, decorate=decorate,
                                             title=title, figure_title=str(p.get('figure_title', '') or ''))
        written = [Path(w) for w in written if w and Path(w).is_file()]
        if not written:
            raise RuntimeError('the Export-panel renderer wrote no file')
    except Exception:
        import traceback
        log('Export-panel renderer failed, the overlay is drawn with Matplotlib instead:\n'
            + traceback.format_exc(limit=6), 'warning')
        written = matplotlib_overlay(base, data, new_size, np.asarray(scan.basis_image_nm) * n_cells,
                                     new_basis * n_cells, rows, cal_rows, {'old': old, 'new': new}, corners, formats,
                                     str(p.get('figure_title', '') or ''), title, p.get('scan_colormap', ''), ctx.unit)
    for path in written:
        ctx.result_file(path, 'Lattice before → after calibration · ' + path.suffix[1:].upper())
    return written, (a0, b0, g0), (a1, b1, g1), new_size


# --------------------------------------------------------------------------- drift
DRIFT_MODES = ('Header + fit drift (recommended)', 'Header only', 'Fit drift only (ignore header)',
               'No drift correction')


def _fmt_drift(v):
    v = np.asarray(v, float) * 60          # nm/min
    return f'({v[0]:+.3g}, {v[1]:+.3g}) nm/min'


def prepare_drift(ctx, scans, log):
    """Known drift of every scan from its header, according to the chosen treatment.

    Physics: a sample drifting with velocity v_true relative to the scanner, while the
    controller moves the tip with a compensation v_comp, appears to drift with
    v_eff = v_true − v_comp. The compensation written in the header is therefore already in
    the image; only the remaining drift distorts the lattice.
    * Header + fit: v_true is fitted for the whole session; each scan uses −v_comp (on) or 0.
    * Header only:  compensation on → v_eff = 0 (assumed perfect); off → v_eff = the header value.
    * Fit only:     one effective drift for all scans, header ignored.
    """
    mode = str(ctx.parameters.get('drift_mode', DRIFT_MODES[0]))
    if mode not in DRIFT_MODES:
        mode = DRIFT_MODES[0]
    out = []
    for s in scans:
        header = s.extra.get('header_drift')
        state = cc.compensation_on(s.extra.get('drift_status'))
        known = np.zeros(2)
        if header is not None:
            log(f'{s.name}: drift in header {_fmt_drift(header)}, compensation '
                + ({True: 'ON during the scan', False: 'OFF', None: 'state unknown'}[state]))
        if mode == DRIFT_MODES[0] and header is not None and state:
            known = -np.asarray(header, float)
        elif mode == DRIFT_MODES[1] and header is not None and state is False:
            known = np.asarray(header, float)
        if s.time_gradient is None and mode != DRIFT_MODES[3]:
            log(f'{s.name}: no scan time per line or slow-scan direction in the file — drift cannot be '
                'modelled for this scan.', 'warning')
            known = np.zeros(2)
        out.append(cc.replace_drift(s, known) if mode != DRIFT_MODES[3] else cc.replace_drift(s, np.zeros(2)))
    wants_fit = mode in (DRIFT_MODES[0], DRIFT_MODES[2]) and all(s.time_gradient is not None for s in out)
    return out, wants_fit


def fit_with_drift(scans, ref, fit_skew, fb, wants_fit, log):
    """Calibration with the drift fitted when the scans can separate it, else header drift only."""
    if wants_fit:
        try:
            fit, eq = cc.calibrate(scans, ref, fit_skew, fb, fit_drift=True)
            sx, sy = np.sqrt(np.clip(np.diag(fit.drift_cov), 0, None)) * 60
            log(f'Drift fitted with the calibration (session constant, piezo frame): '
                f'{_fmt_drift(fit.drift)} ± ({sx:.2g}, {sy:.2g}) nm/min')
            return fit, eq, 'fitted together with the calibration (constant drift over the session)'
        except (cc.DriftNotSeparable, ValueError) as exc:
            log(f'Drift could not be fitted ({exc}). It needs frames with different time gradients: up and down '
                'scans of the same area, scans at 0° and 90°, or different scan speeds. Header drift only.',
                'warning')
    fit, eq = cc.calibrate(scans, ref, fit_skew, fb)
    note = 'header drift values (compensation) only' if fit.drift_mode == 'known' else 'not corrected'
    return fit, eq, note


def drift_pairs(scans, fit, fb, log):
    """Independent check: drift from every up/down pair, without using the reference lattice."""
    out = []
    for i, j in cc.updown_pairs(scans):
        up, down = (scans[i], scans[j]) if scans[i].slow_direction == 'up' else (scans[j], scans[i])
        k = (fit.cx / (up.cx_old or fb[0]), fit.cy / (up.cy_old or fb[1]))
        result = cc.pair_drift(up, down, k)
        if result is None:
            continue
        out.append(result)
        log(f'Up/down pair {up.name} ↔ {down.name}: drift {_fmt_drift(result["drift"])} '
            f'(unexplained difference {result["relative_residual"] * 100:.2f} % of the cell)')
    if out and fit.drift_mode == 'fitted':
        mean = np.mean([r['drift'] for r in out], axis=0)
        log(f'Drift check: up/down pairs {_fmt_drift(mean)} vs fitted {_fmt_drift(fit.drift)}')
    return out


# --------------------------------------------------------------------------- v1.4: method choice
XY_METHODS = ('Automatic (atomic lattice, else Au(111) herringbones)', 'Atomic lattice (FFT)',
              'Au(111) herringbone reconstruction', 'Off (Z only)')
Z_MODES = ('Automatic (when monatomic steps are found)', 'Off', 'Required (stop if no step is found)')


class NoUsableScan(ValueError):
    """No scan gave the reference lattice (the message lists what was detected)."""


def _xy_method(p):
    text = str(p.get('xy_method', XY_METHODS[0]) or XY_METHODS[0]).lower()
    if text.startswith('off'):
        return 'off'
    if text.startswith('atomic'):
        return 'lattice'
    if 'herringbone' in text and not text.startswith('auto'):
        return 'herringbone'
    return 'auto'


def _z_mode(p):
    text = str(p.get('z_calibration', Z_MODES[0]) or Z_MODES[0]).lower()
    if text.startswith('off'):
        return 'off'
    if text.startswith('required'):
        return 'required'
    return 'auto'


class _Stage:
    """``ctx`` with its progress mapped onto a part of the bar (X/Y first, then Z)."""

    def __init__(self, ctx, lo, hi):
        self._ctx, self._lo, self._hi = ctx, float(lo), float(hi)

    def __getattr__(self, name):
        return getattr(self._ctx, name)

    def progress(self, value, message=''):
        self._ctx.progress(self._lo + (self._hi - self._lo) * max(0., min(100., float(value))) / 100, message)


# --------------------------------------------------------------------------- v1.4: Au(111) herringbones
def herringbone_period_nm(p):
    """Period of the herringbone line pairs (nm) and where it comes from."""
    typed = float(p.get('herringbone_period_angstrom', 0) or 0)
    if typed > 0:
        return typed / 10, f'{typed:.2f} Å (entered in Tool settings)'
    _name, preset = cc.find_material(p.get('material', 'Custom'))
    if preset and preset.get('herringbone'):
        return float(preset['herringbone']), (f'{preset["herringbone"] * 10:.1f} Å — {preset["herringbone_note"]}. '
                                              f'Source: {preset["herringbone_source"]}')
    return None, ''


def herringbone_reference(p):
    import herringbone as hb
    period, why = herringbone_period_nm(p)
    if not period:
        raise NoUsableScan('The herringbone method needs Au(111): choose “Au(111) (1×1)” as reference crystal, '
                           'or enter the herringbone period (Å) in Tool settings.')
    a = hb.equivalent_cell_nm(period)
    notes = (f'Herringbone period d = {why}',
             f'The two line families (normals at 120°) are fitted as their dual cell: hexagonal a = 2d/√3 = '
             f'{a * 10:.1f} Å, γ = 120° (it transforms exactly like a lattice under calibration and drift).')
    return cc.Reference(a, a, 120.0, None, f'Au(111) herringbone, d = {period * 10:.1f} Å', notes), period


def _region_rois(ctx):
    """Rectangles and closed lines (≥ 3 points) drawn around the herringbones."""
    return [r for r in _all_rois(ctx) if (r.kind == 'rectangle' and len(r.points_px) == 2)
            or (r.kind == 'line' and len(r.points_px) >= 3)]


def _step_height_m(p):
    """Monatomic step height (m) of the crystal, or None."""
    typed = float(p.get('step_height_angstrom', 0) or 0)
    if typed > 0:
        return typed * 1e-10, f'{typed:.3f} Å (entered in Tool settings)'
    _name, preset = cc.find_material(p.get('material', 'Custom'))
    if preset and preset.get('step'):
        note = preset.get('step_note', '')
        if preset.get('step_source'):
            note += '. Source: ' + preset['step_source']
        return float(preset['step']) * 1e-9, f'{preset["step"] * 10:.3f} Å — {note}'
    return None, ''


def collect_herringbone(ctx, period_nm, log):
    """Herringbone line families on every usable scan / trace → equivalent dual cells (ScanLattice)."""
    import herringbone as hb
    p = ctx.parameters
    tolerance = float(p.get('max_deviation_percent', 25.0)) / 100
    override = bool(p.get('override_metadata', False))
    fallback = _fallback(ctx)
    step_h, _why = _step_height_m(p)
    scans, skipped = [], []
    entries = _scan_entries(ctx)
    regions = _region_rois(ctx)
    from spm_studio.core.io import read_scan
    for n, path in enumerate(entries):
        ctx.progress(5 + 55 * n / max(1, len(entries)), f'Herringbones of {path.name}')
        current = n == 0
        try:
            if current:
                metadata = ctx.metadata or {}
                geometry = ctx.geometry
                arrays = {t: ctx.image(ctx.channel, t) for t in ('forward', 'backward')
                          if f'{ctx.channel}|{t}' in ctx.arrays}
                arrays[ctx.direction] = ctx.data
            else:
                scan = read_scan(path)
                if ctx.channel not in scan.channels:
                    skipped.append((path.name, f'no channel {ctx.channel}'))
                    continue
                channel = scan.channels[ctx.channel]
                metadata = scan.metadata or {}
                geometry = channel.geometry
                arrays = dict(channel.traces)
        except Exception as exc:
            skipped.append((path.name, f'could not be read: {exc}'))
            continue
        if not geometry.size_m:
            skipped.append((path.name, 'no physical scan size in the file'))
            continue
        header = cc.header_dict(metadata)
        found = cc.calibration_from_header(header)
        acquisition = cc.acquisition_from_header(header)
        cx, cy = found['cx'], found['cy']
        if override or cx is None or cy is None:
            cx = fallback[0] if (override or cx is None) and fallback[0] else cx
            cy = fallback[1] if (override or cy is None) and fallback[1] else cy
        relative = cx is None or cy is None
        if relative:
            cx, cy = 1.0, 1.0
        slow = str(geometry.scan_direction or '').strip().lower()
        angle = float(geometry.angle_deg or 0.0)
        for trace in _traces(ctx, arrays):
            label = f'{path.stem} · {trace}'
            active = current and trace == ctx.direction
            try:
                raw = np.asarray(arrays[trace], float)
                ny, nx = raw.shape
                cropped, rows = _crop_rows_of_aborted_scan(raw if not active else np.asarray(ctx.data, float))
                width_nm = geometry.size_m[0] * 1e9
                height_nm = geometry.size_m[1] * 1e9 * cropped.shape[0] / ny
                dx, dy = width_nm / cropped.shape[1], height_nm / cropped.shape[0]
                mask, polygons = (None, [])
                if active and regions:
                    off = rows.start or 0
                    shifted = [type(r)(r.kind, tuple((c, rr - off) for c, rr in r.points_px)) for r in regions]
                    mask, polygons = hb.region_mask(cropped.shape, shifted)
                    if not mask.any():
                        mask, polygons = None, []
                    else:
                        log(f'{label}: herringbones measured inside the drawn region only')
                unit = (getattr(ctx, 'channel_units', None) or {}).get(ctx.channel, ctx.unit)
                det = hb.detect(cropped, dx, dy, period_nm, tolerance, region=mask,
                                step_height_m=step_h if str(unit).strip() == 'm' else None)
            except hb.HerringboneNotFound as exc:
                hint = ('' if (active and regions) else
                        ' — if you see herringbones on this scan, draw around them (rectangle, or a closed line '
                        'with Shift+click) and run again')
                skipped.append((label, f'herringbones not found automatically ({exc}){hint if current else ""}'))
                continue
            except Exception as exc:
                skipped.append((label, f'herringbone analysis failed ({exc})'))
                continue
            basis = np.asarray(det['dual_basis_nm'], float)
            gradient = cc.time_gradient(trace, slow, (width_nm, height_nm), cropped.shape, acquisition['line_time'])
            scans.append(cc.ScanLattice(label, basis, angle, cx, cy, (width_nm, height_nm), cropped.shape,
                                        slow, trace, active,
                                        {'path': str(path), 'relative': relative,
                                         'line_time': acquisition['line_time'],
                                         'header_drift': acquisition['drift'],
                                         'drift_status': acquisition['drift_status'],
                                         'timestamp': acquisition['timestamp'],
                                         'offset_nm': acquisition['offset_nm'],
                                         'calibration_keys': found['source_keys'],
                                         'drift_correction': found['drift_correction'],
                                         'second_order': found['second_order'],
                                         'herringbone': det, 'region_polygons': polygons,
                                         # terraces flattened so that the herringbones are visible
                                         'display': (hb.flatten_terraces(cropped, dx, dy, step_h)
                                                     if step_h and str(unit).strip() == 'm'
                                                     else np.asarray(cropped, float))},
                                        time_gradient=gradient))
            log(f'{label}: herringbone periods {det["periods_nm"][0] * 10:.2f} Å and {det["periods_nm"][1] * 10:.2f} Å '
                f'(line families at {det["angles_deg"][0]:.1f}° and {det["angles_deg"][1]:.1f}°, '
                f'{det["separation_deg"]:.1f}° apart; S/N {min(det["snr"]):.0f}; {det["method"]}), fast axis '
                f'{scans[-1].fast_axis}, slow {slow or "?"}, previous calibration '
                + ('unknown (relative factors)' if relative else f'X {cx * 1e9:.4g} nm/V, Y {cy * 1e9:.4g} nm/V'))
    return scans, skipped


def _calibration_rows(scan, fit, fallback, ccal):
    relative = scan.extra.get('relative')
    cx_old = scan.cx_old or fallback[0]
    cy_old = scan.cy_old or fallback[1]
    pale = _mix(ccal, '#ffffff', .55)
    if relative:
        rows = [('X', '×1', f'×{fit.cx / cx_old:.4f}', pale, ccal), ('Y', '×1', f'×{fit.cy / cy_old:.4f}', pale, ccal)]
    else:
        rows = [('X', f'{cx_old * 1e9:.4g}', f'{fit.cx * 1e9:.4g} nm/V', pale, ccal),
                ('Y', f'{cy_old * 1e9:.4g}', f'{fit.cy * 1e9:.4g} nm/V', pale, ccal)]
    v_total = np.asarray(scan.drift_known, float) + np.asarray(fit.drift, float)
    if np.any(v_total):
        rows.append(('drift', '', _fmt_drift(v_total), pale, '#f2f2f2'))
    return rows


def herringbone_figure(ctx, scan, fit, ref, fallback, log):
    """The scan with the herringbones used: period vectors before (pale, dashed) → after, region outline."""
    import herringbone as hb
    from spm_studio.core import script_figures as figures
    p = ctx.parameters
    det = scan.extra['herringbone']
    _basis, matrix = cc.corrected_basis_image(scan, fit, fallback)
    w, h = scan.size_nm
    new_size = (w * float(np.linalg.norm(matrix[:, 0])), h * float(np.linalg.norm(matrix[:, 1])))
    k_before = [np.asarray(k, float) for k in det['k_nm_inv']]
    k_after = hb.corrected_wavevectors(k_before, matrix)
    old_vec, new_vec = hb.period_vectors(k_before), hb.period_vectors(k_after)
    d0 = [1 / float(np.linalg.norm(k)) for k in k_before]
    d1 = [1 / float(np.linalg.norm(k)) for k in k_after]

    def line_angle(k1, k2):
        c = abs(float(k1 @ k2)) / (np.linalg.norm(k1) * np.linalg.norm(k2))
        return 180 - math.degrees(math.acos(max(-1., min(1., c))))       # angle between the lines (120°)
    g0, g1 = line_angle(*k_before), line_angle(*k_after)
    n_cells = max(1, int(round(.2 * min(new_size) / max(max(d1), 1e-9))))
    ca = str(p.get('vector_a_color', '#16d8f5'))
    cb = str(p.get('vector_b_color', '#fbb748'))
    ccal = str(p.get('calibration_color', '#7ee081'))
    old = (_mix(ca, '#ffffff', .55), _mix(cb, '#ffffff', .55))
    new = (ca, cb)
    rows = [('d₁', f'{d0[0] * 10:.2f} Å', f'{d1[0] * 10:.2f} Å', old[0], new[0]),
            ('d₂', f'{d0[1] * 10:.2f} Å', f'{d1[1] * 10:.2f} Å', old[1], new[1]),
            ('lines', f'{g0:.1f}°', f'{g1:.1f}°', '#d8d8d8', '#ffffff'),
            ('theory', '', f'{ref.a_nm * math.sqrt(3) / 2 * 10:.1f} Å, 120°', '#d8d8d8', '#f2f2f2')]
    if n_cells > 1:
        rows.append(('arrows', '', f'{n_cells} × d₁,  {n_cells} × d₂', '#d8d8d8', '#f2f2f2'))
    cal_rows = _calibration_rows(scan, fit, fallback, ccal)
    corners = (str(p.get('lattice_legend_corner', 'top_left')), str(p.get('calibration_legend_corner', 'top_right')))
    if corners[0] == corners[1]:
        corners = (corners[0], 'top_right' if corners[0] != 'top_right' else 'top_left')
    data = np.asarray(scan.extra.get('display', ctx.data), float)
    outlines = scan.extra.get('region_polygons') or []
    decorate = make_decorator(old_vec * n_cells, new_vec * n_cells, new_size, rows, cal_rows,
                              {'old': old, 'new': new}, corners, outlines=outlines, outline_shape=data.shape,
                              outline_color=ccal)
    cfg = getattr(ctx, 'plot_config', None) or {'schema_version': 1}
    style = figures.scan_display_style(cfg, ctx.channel, colormap_override=p.get('scan_colormap', ''))
    title = figures.colorbar_title(cfg, ctx.channel, '')
    formats = tuple(getattr(ctx, 'plot_formats', None) or ('svg',))
    base = ctx.output_dir / 'calibration_herringbone_overlay'
    try:
        written = figures.export_scan_figure(base, scan_path=scan.extra.get('path') or ctx.scan_path,
                                             data=data, size_nm=new_size, channel=ctx.channel, unit=ctx.unit,
                                             plot_config=cfg, formats=formats, style=style, decorate=decorate,
                                             title=title, figure_title=str(p.get('figure_title', '') or ''))
        written = [Path(x) for x in written if x and Path(x).is_file()]
        if not written:
            raise RuntimeError('the Export-panel renderer wrote no file')
    except Exception:
        import traceback
        log('Export-panel renderer failed, the herringbone figure is drawn with Matplotlib instead:\n'
            + traceback.format_exc(limit=6), 'warning')
        written = matplotlib_overlay(base, data, new_size, old_vec * n_cells, new_vec * n_cells, rows, cal_rows,
                                     {'old': old, 'new': new}, corners, formats, str(p.get('figure_title', '') or ''),
                                     title, p.get('scan_colormap', ''), ctx.unit, outlines=outlines,
                                     outline_color=ccal)
    for path in written:
        ctx.result_file(path, 'Herringbones before → after calibration · ' + path.suffix[1:].upper())
    return written, (d0[0], d0[1], g0), (d1[0], d1[1], g1), new_size


# --------------------------------------------------------------------------- X/Y run
def run_xy(ctx, method):
    """X/Y calibration with the atomic lattice or the Au(111) herringbones; returns a dict for the Z part."""
    p = ctx.parameters
    log = ctx.log
    fallback = _fallback(ctx)
    if method == 'herringbone':
        ref, period = herringbone_reference(p)
        log(f'X/Y reference: {ref.name} (equivalent cell a = b = {ref.a_nm * 10:.1f} Å, γ = 120°)')
        for note in ref.notes:
            log(note)
        log('Accuracy: the herringbone period is a weaker standard than an atomic lattice (≈ 1–2 %: 22 or 23 '
            'atoms per cell, strain near steps and elbows); use atomic resolution when you can.')
        detected, skipped = collect_herringbone(ctx, period, log)
        automatic = False
    else:
        ref = cc.reference_from_parameters(p)
        short, long_ = ref.diagonals()
        log(f'Reference {ref.name}: a = {ref.a_nm * 10:.4f} Å, b = {ref.b_nm * 10:.4f} Å'
            + (f', γ = {ref.gamma_deg:g}°' if ref.gamma_deg else '')
            + (f', diagonals {", ".join(f"{d * 10:.4f} Å" for d in (short, long_) if d)}' if (short or long_) else ''))
        for note in ref.notes:
            log(note)
        detected, skipped = collect(ctx, ref, log)
        automatic = None
    cells = [(s.name, cc.cell_parameters(s.basis_image_nm)) for s in detected]
    entered = ref
    scans, ref, ref_why = select_reference(ctx, detected, skipped, ref, log, automatic)
    for name, why in skipped:
        log(f'{name}: {why}', 'warning')
    if not scans:
        if method == 'herringbone':
            raise NoUsableScan('No scan could be used for the herringbone calibration.\n'
                               + '\n'.join(f'  {n}: {w}' for n, w in skipped[:8])
                               + '\nIf you see the herringbones, draw around them on the active scan (rectangle, or '
                                 'a closed line with Shift+click) and run again.')
        raise NoUsableScan(_no_scan_message(entered, cells, float(p.get('max_deviation_percent', 25.0)) / 100))
    relative = any(s.extra.get('relative') for s in scans)
    if relative and not all(s.extra.get('relative') for s in scans):
        raise ValueError('Some scans have a previous calibration in their header and others not. Enter the previous '
                         'calibration X / Y in Tool settings so every scan uses known constants.')
    fb = (1.0, 1.0) if relative else fallback
    ctx.progress(65, 'Fitting X / Y calibration')
    fit_skew = bool(p.get('fit_axis_skew', False))
    scans, drift_fit_wanted = prepare_drift(ctx, scans, log)
    fit, equations, drift_note = fit_with_drift(scans, ref, fit_skew, fb, drift_fit_wanted, log)
    pairs = drift_pairs(scans, fit, fb, log)
    for s in scans:
        if s.extra.get('second_order'):
            log(f'{s.name}: non-linear (2nd order / curvature) piezo corrections are set in the header; this '
                'tool fits the linear constants only.', 'warning')
    repeats = int(p.get('bootstrap_repeats', 400) or 0)
    fitted = fit.drift_mode == 'fitted'
    boot = cc.bootstrap(scans, ref, fit_skew, fb, repeats, fit_drift=fitted)
    loo = cc.leave_one_out(scans, ref, fit_skew, fb, fit_drift=fitted)
    singles = cc.per_scan_fits(scans, ref, fb, extra_drift=fit.drift if fitted else None)

    ref_cx = float(np.median([s.cx_old for s in scans]))
    ref_cy = float(np.median([s.cy_old for s in scans]))
    kx, ky = fit.cx / ref_cx, fit.cy / ref_cy
    unit = '×' if relative else 'nm/V'
    scale = 1 if relative else 1e9
    rows = [['Method', 'Au(111) herringbones (22×√3)' if method == 'herringbone' else 'atomic lattice (FFT)', ''],
            ['Previous calibration X', ref_cx * scale, unit], ['New calibration X', fit.cx * scale, unit],
            ['σ X (fit)', fit.sigma_cx * scale, unit]]
    if len(boot):
        lo, hi = np.percentile(boot[:, 0], [2.5, 97.5]) * scale
        rows.append(['X 95 % CI (bootstrap over scans)', f'{lo:.5g} – {hi:.5g}', unit])
    rows += [['Previous calibration Y', ref_cy * scale, unit], ['New calibration Y', fit.cy * scale, unit],
             ['σ Y (fit)', fit.sigma_cy * scale, unit]]
    if len(boot):
        lo, hi = np.percentile(boot[:, 1], [2.5, 97.5]) * scale
        rows.append(['Y 95 % CI (bootstrap over scans)', f'{lo:.5g} – {hi:.5g}', unit])
    rows += [['Correction X (new / previous)', kx, ''], ['Correction Y (new / previous)', ky, ''],
             ['Scans · vectors used', f'{fit.n_scans} · {fit.n_equations}', ''],
             ['Reduced χ² (FFT-resolution errors)', fit.chi2_red, '']]
    if fit_skew:
        rows.append(['Axis non-orthogonality', fit.skew_deg, '°'])
    rows.append(['Drift treatment', drift_note, ''])
    if fitted:
        sx, sy = np.sqrt(np.clip(np.diag(fit.drift_cov), 0, None))
        rows.append(['Drift X (fitted, piezo frame)', f'{fit.drift[0] * 60:.4g} ± {sx * 60:.2g}', 'nm/min'])
        rows.append(['Drift Y (fitted, piezo frame)', f'{fit.drift[1] * 60:.4g} ± {sy * 60:.2g}', 'nm/min'])
    for k, pr in enumerate(pairs, 1):
        rows.append([f'Drift from up/down pair {k} (X, Y)', f'{pr["drift"][0] * 60:.4g}, {pr["drift"][1] * 60:.4g}',
                     'nm/min'])
    ctx.result_table(['quantity', 'value', 'unit'], rows, 'Microscope calibration')
    log(f'NEW CALIBRATION  X = {fit.cx * scale:.5g} {unit} (×{kx:.4f}),  Y = {fit.cy * scale:.5g} {unit} '
        f'(×{ky:.4f})' + (f',  axis skew {fit.skew_deg:.2f}°' if fit_skew else '')
        + ('  [Au(111) herringbones]' if method == 'herringbone' else ''))
    if relative:
        log('The previous calibration was not found in the files: the values are correction factors. '
            'New calibration = factor × the calibration used for these scans.', 'warning')

    # ---- per-vector table (before / after; after = leave-one-out when possible)
    loo_map = {(i, lab): after for i, lab, _t, _b, after in loo}
    vector_rows = []
    for e in equations:
        before = float(np.linalg.norm(e.vector_nm))
        after_in = fit.predict(e)
        after_loo = loo_map.get((e.scan, e.label))
        vector_rows.append([scans[e.scan].name, e.label, e.theory_nm * 10, before * 10, after_in * 10,
                            (after_loo * 10) if after_loo is not None else '',
                            math.degrees(math.atan2(e.vector_nm[1], e.vector_nm[0])) % 180])
    columns = ['scan', 'vector', 'theory (Å)', 'before (Å)', 'after, all scans (Å)',
               'after, leave-one-out (Å)', 'piezo direction (°)']
    with (ctx.output_dir / 'calibration_vectors.csv').open('w', newline='', encoding='utf8') as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(vector_rows)
    ctx.result_file(ctx.output_dir / 'calibration_vectors.csv', 'Every lattice vector before / after')
    ctx.result_table(columns, [[r[0], r[1]] + [round(v, 4) if isinstance(v, float) else v for v in r[2:]]
                               for r in vector_rows],
                     'Herringbone dual-cell vectors before → after' if method == 'herringbone'
                     else 'Lattice vectors before → after')

    # ---- figures
    ctx.progress(80, 'Statistics figure')
    try:
        from calibration_plots import statistics_figure
        statistics_figure(ctx, scans, equations, fit, ref, boot, loo, singles, relative, fb, pairs,
                          label='Herringbone dual cell · ' if method == 'herringbone' else '')
    except Exception as exc:
        log(f'Statistics figure could not be drawn: {exc}', 'warning')
    current = next((s for s in scans if s.is_current), None)
    before_after = None
    if current is None:
        current = scans[0]
        log(f'The active scan gave no usable {"herringbones" if method == "herringbone" else "lattice"}: the '
            f'before → after figure is drawn on {current.name}.', 'warning')
    ctx.progress(90, 'Figure before → after')
    try:
        if method == 'herringbone':
            _w, before, after, new_size = herringbone_figure(ctx, current, fit, ref, fb, log)
            before_after = {'scan': current.name, 'periods_before_nm': before[:2], 'lines_angle_before_deg': before[2],
                            'periods_after_nm': after[:2], 'lines_angle_after_deg': after[2], 'new_size_nm': new_size}
            log(f'Before → after figure: {current.name}  d₁ {before[0] * 10:.2f} → {after[0] * 10:.2f} Å, '
                f'd₂ {before[1] * 10:.2f} → {after[1] * 10:.2f} Å, lines {before[2]:.1f} → {after[2]:.1f}°')
        else:
            _w, before, after, new_size = publication_figure(ctx, current, fit, ref, fb, log)
            before_after = {'scan': current.name, 'before': before, 'after': after, 'new_size_nm': new_size}
            log(f'Before → after figure: {current.name}  a {before[0] * 10:.3f} → {after[0] * 10:.3f} Å, '
                f'b {before[1] * 10:.3f} → {after[1] * 10:.3f} Å, γ {before[2]:.2f} → {after[2]:.2f}°')
    except Exception:
        import traceback
        log('Before → after figure could not be drawn:\n' + traceback.format_exc(limit=8), 'warning')

    result = {
        'schema_version': 1, 'kind': 'spm_studio_xy_calibration',
        'method': 'herringbone' if method == 'herringbone' else 'lattice',
        'reference': {'name': ref.name, 'a_nm': ref.a_nm, 'b_nm': ref.b_nm, 'gamma_deg': ref.gamma_deg,
                      'diagonal_nm': ref.diagonal_nm, 'interpretation': ref_why,
                      'entered_a_nm': entered.a_nm, 'entered_b_nm': entered.b_nm, 'notes': list(entered.notes)},
        'relative_factors_only': relative,
        'previous_calibration_m_per_V': None if relative else {'x': ref_cx, 'y': ref_cy},
        'new_calibration_m_per_V': None if relative else {'x': fit.cx, 'y': fit.cy,
                                                          'sigma_x': fit.sigma_cx, 'sigma_y': fit.sigma_cy},
        'correction_factor': {'x': kx, 'y': ky},
        'axis_skew_deg': fit.skew_deg if fit_skew else None,
        'drift': {'treatment': drift_note, 'mode': fit.drift_mode,
                  'fitted_nm_per_s': fit.drift.tolist() if fitted else None,
                  'fitted_cov_nm2_per_s2': fit.drift_cov.tolist() if fitted else None,
                  'per_scan': [{'scan': s.name, 'header_drift_nm_per_s': (None if s.extra.get('header_drift') is None
                                                                          else list(s.extra['header_drift'])),
                                'compensation': s.extra.get('drift_status'),
                                'known_drift_used_nm_per_s': list(np.asarray(s.drift_known, float)),
                                'time_gradient_s_per_nm': (None if s.time_gradient is None
                                                           else list(s.time_gradient)),
                                'line_time_s': s.extra.get('line_time')} for s in scans],
                  'updown_pairs': [{k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in pr.items()}
                                   for pr in pairs]},
        'bootstrap_95ci_m_per_V': None if not len(boot) else
        {'x': list(np.percentile(boot[:, 0], [2.5, 97.5])), 'y': list(np.percentile(boot[:, 1], [2.5, 97.5])),
         'repeats_ok': int(len(boot))},
        'reduced_chi2': fit.chi2_red, 'condition_number': fit.condition,
        'scans': [{'name': s.name, 'path': s.extra.get('path'), 'trace': s.trace, 'scan_angle_deg': s.angle_deg,
                   'fast_axis': s.fast_axis, 'slow_direction': s.slow_direction,
                   'previous_cx_m_per_V': s.cx_old, 'previous_cy_m_per_V': s.cy_old,
                   'size_nm': list(s.size_nm), 'basis_image_nm': np.asarray(s.basis_image_nm).tolist(),
                   'calibration_header_keys': s.extra.get('calibration_keys')} for s in scans],
        'skipped': [{'scan': n, 'reason': r} for n, r in skipped],
        'active_scan': before_after,
        'model': 'L² = Vx²·cx² + Vy²·cy² (+ 2VxVy·cxy); V = piezo-frame vector / previous calibration; weighted '
                 'linear least squares over every a, b and diagonal of every scan.',
    }
    if method == 'herringbone':
        result['herringbone'] = {
            'period_nm': ref.a_nm * math.sqrt(3) / 2, 'source': cc.BARTH_1990,
            'equivalent_cell': 'dual basis of the two line families (a_i·k_j = δ_ij), hexagonal a = 2d/√3, γ = 120°',
            'per_scan': [{'scan': s.name,
                          'periods_nm': [float(x) for x in s.extra['herringbone']['periods_nm']],
                          'line_family_angles_deg': [float(x) for x in s.extra['herringbone']['angles_deg']],
                          'signal_to_noise': [float(x) for x in s.extra['herringbone']['snr']],
                          'wave_vectors_nm_inv': [list(map(float, k)) for k in s.extra['herringbone']['k_nm_inv']],
                          'estimator': s.extra['herringbone'].get('method'),
                          'drawn_region': bool(s.extra.get('region_polygons'))} for s in scans]}
    path = ctx.output_dir / 'calibration_result.json'
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=float), encoding='utf8')
    ctx.result_file(path, 'Calibration result (JSON)')
    return {'path': path, 'fit': fit, 'scans': scans, 'fallback': fb, 'relative': relative, 'result': result,
            'method': method}


def _run_xy_with_fallback(ctx, method):
    """``auto``: atomic lattice; when no scan shows it and the crystal is Au(111), the herringbones."""
    if method != 'auto':
        return run_xy(ctx, method)
    try:
        return run_xy(ctx, 'lattice')
    except NoUsableScan as exc:
        period, _why = herringbone_period_nm(ctx.parameters)
        if not period:
            raise
        message = str(exc)
    # outside the except block, so that later tracebacks are not chained to this one
    ctx.log('No atomic lattice could be used; trying the Au(111) herringbone reconstruction instead.\n' + message,
            'warning')
    return run_xy(ctx, 'herringbone')


# --------------------------------------------------------------------------- run
def run(ctx):
    p = ctx.parameters
    log = ctx.log
    xy_method = _xy_method(p)
    z_mode = _z_mode(p)
    xy_out = xy_error = None
    split = 70 if (xy_method != 'off' and z_mode != 'off') else 100
    if xy_method != 'off':
        try:
            xy_out = _run_xy_with_fallback(_Stage(ctx, 0, split), xy_method)
        except Exception as exc:
            if z_mode == 'off':
                raise
            xy_error = exc
            log(f'X/Y calibration not done: {exc}', 'warning')
    z_out = None
    if z_mode != 'off':
        import z_steps as zs
        from z_report import run_z
        try:
            z_out = run_z(_Stage(ctx, split if xy_method != 'off' else 0, 100), xy_out)
        except zs.NoStepsFound as exc:
            if z_mode == 'required' or (xy_out is None and xy_error is None):
                raise ValueError(f'Z calibration: {exc}') from exc
            if xy_out is None:
                log(f'Z calibration not done either: {exc}', 'warning')
                raise xy_error
            log(f'No monatomic step for the Z calibration ({exc}); Z is not calibrated. Set “Z calibration” to Off '
                'to skip this check.')
    ctx.progress(100, 'Calibration done')
    if xy_out is not None and z_out is not None:
        try:     # one summary in the X/Y result, the full Z result next to it
            result = xy_out['result']
            result['z_calibration'] = z_out['summary']
            xy_out['path'].write_text(json.dumps(result, indent=2, ensure_ascii=False, default=float), encoding='utf8')
        except Exception:
            pass
    if xy_out is not None:
        return xy_out['path']
    return z_out['path']
