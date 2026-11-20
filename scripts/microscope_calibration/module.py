"""Microscope X/Y calibration from lattice images of a known reference crystal.

Uses every scan open in SPM Studio (same channel as the active one), detects the primitive
lattice of each with the Lattice measurements tool's FFT engine, and fits the new X and Y
piezo calibration constants (see calibration_core.py for the model).
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
                if active and ctx.roi is not None and ctx.roi.kind == 'rectangle':
                    (c0, r0), (c1, r1) = ctx.roi.points_px
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


def select_reference(ctx, scans, skipped, ref, log):
    """Match the reference description to the detected cells, then drop the scans that are off."""
    tolerance = float(ctx.parameters.get('max_deviation_percent', 25.0)) / 100
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


def make_decorator(old_basis, new_basis, new_size_nm, rows_lattice, rows_calibration, colors, corners):
    """Painter callback: old (pale, dashed) and new (dark, solid) a/b arrows + two legends."""

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
                       figure_title='', colorbar_label='', colormap='', unit=''):
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


# --------------------------------------------------------------------------- run
def run(ctx):
    p = ctx.parameters
    log = ctx.log
    ref = cc.reference_from_parameters(p)
    short, long_ = ref.diagonals()
    log(f'Reference {ref.name}: a = {ref.a_nm * 10:.4f} Å, b = {ref.b_nm * 10:.4f} Å'
        + (f', γ = {ref.gamma_deg:g}°' if ref.gamma_deg else '')
        + (f', diagonals {", ".join(f"{d * 10:.4f} Å" for d in (short, long_) if d)}' if (short or long_) else ''))
    for note in ref.notes:
        log(note)
    fallback = _fallback(ctx)
    detected, skipped = collect(ctx, ref, log)
    cells = [(s.name, cc.cell_parameters(s.basis_image_nm)) for s in detected]
    entered = ref
    scans, ref, ref_why = select_reference(ctx, detected, skipped, ref, log)
    for name, why in skipped:
        log(f'{name}: {why}', 'warning')
    if not scans:
        raise ValueError(_no_scan_message(entered, cells, float(p.get('max_deviation_percent', 25.0)) / 100))
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
    rows = [['Previous calibration X', ref_cx * scale, unit], ['New calibration X', fit.cx * scale, unit],
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
        f'(×{ky:.4f})' + (f',  axis skew {fit.skew_deg:.2f}°' if fit_skew else ''))
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
                               for r in vector_rows], 'Lattice vectors before → after')

    # ---- figures
    ctx.progress(80, 'Statistics figure')
    try:
        from calibration_plots import statistics_figure
        statistics_figure(ctx, scans, equations, fit, ref, boot, loo, singles, relative, fb, pairs)
    except Exception as exc:
        log(f'Statistics figure could not be drawn: {exc}', 'warning')
    current = next((s for s in scans if s.is_current), None)
    before_after = None
    if current is None:
        current = scans[0]
        log(f'The active scan gave no usable lattice: the before → after figure is drawn on {current.name}.',
            'warning')
    ctx.progress(90, 'Lattice figure before → after')
    try:
        _w, before, after, new_size = publication_figure(ctx, current, fit, ref, fb, log)
        before_after = {'scan': current.name, 'before': before, 'after': after, 'new_size_nm': new_size}
        log(f'Before → after figure: {current.name}  a {before[0] * 10:.3f} → {after[0] * 10:.3f} Å, '
            f'b {before[1] * 10:.3f} → {after[1] * 10:.3f} Å, γ {before[2]:.2f} → {after[2]:.2f}°')
    except Exception:
        import traceback
        log('Before → after figure could not be drawn:\n' + traceback.format_exc(limit=8), 'warning')

    result = {
        'schema_version': 1, 'kind': 'spm_studio_xy_calibration',
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
    path = ctx.output_dir / 'calibration_result.json'
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=float), encoding='utf8')
    ctx.result_file(path, 'Calibration result (JSON)')
    ctx.progress(100, 'Calibration done')
    return path
