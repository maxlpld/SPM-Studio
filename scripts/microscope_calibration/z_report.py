"""Z calibration from monatomic steps: reading the scans, the fit, tables and figures (v1.4).

The engine (terrace leveling, step profiles, statistics) is in ``z_steps.py``. This file reads the
open scans, writes the results and draws the figures with the same renderers as the X/Y part:

* ``z_steps_scan``      — the scan, drawn exactly like the Export panel (recalibrated heights, colour
                          map and colourbar of the viewer), with the numbered step profiles used;
* ``z_step_profiles``   — the profiles (before and after), next to each other;
* ``z_calibration_overview`` — the scan and the profiles side by side (Export-panel renderer);
* ``z_calibration_statistics`` — the tests (per profile, per scan, subsets, direction, drift).
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

import calibration_core as cc
import z_steps as zs

OLD = '#9aa6b2'
NEW = '#1f4e79'
ACCENT = '#c8102e'


# --------------------------------------------------------------------------- helpers
def _mix(color, other, t):
    from matplotlib.colors import to_rgb
    c, o = np.array(to_rgb(color)), np.array(to_rgb(other))
    r, g, b = (1 - t) * c + t * o
    return '#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255))


def step_height_m(p):
    """Monatomic step height (m) of the reference crystal, or (None, '')."""
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


def _all_rois(ctx):
    rois = list(getattr(ctx, 'rois', None) or [])
    roi = getattr(ctx, 'roi', None)
    if roi is not None and not any(r.kind == roi.kind and tuple(map(tuple, r.points_px)) ==
                                   tuple(map(tuple, roi.points_px)) for r in rois):
        rois.append(roi)
    return rois


def _scan_entries(ctx):
    paths = [Path(ctx.scan_path)]
    for p in ctx.source_paths or []:
        p = Path(p)
        if p.suffix.lower() in ('.sxm', '.gwy') and p.resolve() not in {q.resolve() for q in paths}:
            paths.append(p)
    return paths


def _traces(ctx, available):
    mode = str(ctx.parameters.get('traces', 'Active trace only'))
    if mode.startswith('Forward and backward'):
        return [t for t in ('forward', 'backward') if t in available] or list(available)[:1]
    return [ctx.direction] if ctx.direction in available else list(available)[:1]


def _crop_rows(data):
    a = np.asarray(data, float)
    good = np.isfinite(a).mean(axis=1) > .98
    if good.all() or good.sum() < 32:
        return a, 0
    idx = np.flatnonzero(good)
    return a[idx[0]:idx[-1] + 1], int(idx[0])


def _fmt_v(v_nm_s):
    return f'{v_nm_s * 60:+.3g} nm/min'


# --------------------------------------------------------------------------- reading + measuring
def collect_steps(ctx, z_channel, h0, log):
    """Step profiles on every open scan / trace of the topography channel. Returns (zscans, skipped)."""
    p = ctx.parameters
    tolerance = float(p.get('max_deviation_percent', 25.0)) / 100
    allow_multi = bool(p.get('accept_multiple_steps', False))
    max_profiles = max(1, int(p.get('max_step_profiles', 12) or 12))
    length = float(p.get('step_profile_length_nm', 0) or 0)
    fallback = float(p.get('previous_cz_nm_per_v', 0) or 0) * 1e-9 or None
    override = bool(p.get('override_metadata', False))
    entries = _scan_entries(ctx)
    lines = [r for r in _all_rois(ctx) if r.kind == 'line' and len(r.points_px) == 2]
    from spm_studio.core.io import read_scan
    from spm_studio.core.models import Geometry
    zscans, skipped = [], []
    for n, path in enumerate(entries):
        ctx.progress(5 + 55 * n / max(1, len(entries)), f'Steps of {path.name}')
        current = n == 0
        try:
            arrays = {}
            if current:
                metadata = ctx.metadata or {}
                geo = (getattr(ctx, 'channel_geometries', None) or {}).get(z_channel)
                geometry = Geometry.from_dict(geo) if geo else ctx.geometry
                arrays = {t: ctx.arrays[f'{z_channel}|{t}'] for t in ('forward', 'backward')
                          if f'{z_channel}|{t}' in (ctx.arrays or {})}
                unit = (getattr(ctx, 'channel_units', None) or {}).get(z_channel) or \
                    (ctx.unit if z_channel == ctx.channel else '')
                if z_channel == ctx.channel:
                    arrays.setdefault(ctx.direction, ctx.data)
                if not arrays:
                    scan = read_scan(path)
                    if z_channel not in scan.channels:
                        skipped.append((path.name, f'no channel {z_channel}'))
                        continue
                    arrays = dict(scan.channels[z_channel].traces)
                    unit = scan.channels[z_channel].unit
                    geometry = scan.channels[z_channel].geometry
            else:
                scan = read_scan(path)
                if z_channel not in scan.channels:
                    skipped.append((path.name, f'no channel {z_channel}'))
                    continue
                ch = scan.channels[z_channel]
                metadata, geometry, arrays, unit = scan.metadata or {}, ch.geometry, dict(ch.traces), ch.unit
        except Exception as exc:
            skipped.append((path.name, f'could not be read: {exc}'))
            continue
        if str(unit or '').strip() != 'm':
            skipped.append((path.name, f'channel {z_channel} is in “{unit}”, not a height in m — choose the '
                                       'topography channel for Z'))
            continue
        if not geometry.size_m:
            skipped.append((path.name, 'no physical scan size in the file'))
            continue
        header = cc.header_dict(metadata)
        zinfo = cc.z_calibration_from_header(header)
        acq = cc.acquisition_from_header(header)
        cz = zinfo['cz']
        if (override or cz is None) and fallback:
            cz = fallback
        slow = str(geometry.scan_direction or '').strip().lower()
        angle = float(geometry.angle_deg or 0.0)
        for trace in _traces(ctx, arrays):
            label = f'{path.stem} · {trace}'
            active = current and trace == ctx.direction
            try:
                raw = np.asarray(arrays[trace], float)
                ny, nx = raw.shape
                cropped, row0 = _crop_rows(raw)
                width_nm = geometry.size_m[0] * 1e9
                height_nm = geometry.size_m[1] * 1e9 * cropped.shape[0] / ny
                dx, dy = width_nm / cropped.shape[1], height_nm / cropped.shape[0]
                manual = []
                if active and lines:
                    manual = [((float(a[0]), float(a[1]) - row0), (float(b[0]), float(b[1]) - row0))
                              for a, b in (r.points_px for r in lines)]
                    log(f'{label}: {len(manual)} drawn line(s) used as step profiles')
                res = zs.find_steps(cropped, dx, dy, h0, max_profiles=max_profiles, length_nm=length,
                                    manual_lines=manual)
                zs.assign_layers(res['profiles'], h0, tolerance, allow_multi)
            except zs.NoStepsFound as exc:
                skipped.append((label, str(exc)))
                continue
            except Exception as exc:
                skipped.append((label, f'step analysis failed ({exc})'))
                continue
            display = res['leveled']
            if active and z_channel == ctx.channel:
                shown, _r0 = _crop_rows(np.asarray(ctx.data, float))
                if shown.shape == display.shape:
                    display = shown          # exactly as shown in the viewer
            gradient = cc.time_gradient(trace, slow, (width_nm, height_nm), cropped.shape, acq['line_time'])
            zscan = zs.ZScan(label, str(path), trace, angle, cz, (width_nm, height_nm), cropped.shape, slow, active,
                             res['profiles'], res['leveled'], np.asarray(display, float), res['labels'],
                             res['slopes'], res['offsets'], gradient,
                             {'timestamp': acq['timestamp'], 'offset_nm': acq['offset_nm'],
                              'line_time': acq['line_time'], 'drift_status': acq['drift_status'],
                              'header_drift_z_nm_per_s': zinfo['drift_z_nm_per_s'], 'cz_key': zinfo['source_key'],
                              'hv_gain_z': zinfo['hv_gain_z'], 'edge_threshold': res['threshold'],
                              'profile_length_nm': res['profile_length_nm'],
                              'patch_radius_nm': res['patch_radius_nm'], 'pixel_nm': (dx, dy)},
                             relative=cz is None)
            zscans.append(zscan)
            used = zscan.used
            heights = ', '.join(f'{q.h_m * 1e10:.3f}' for q in used[:8]) + (' …' if len(used) > 8 else '')
            log(f'{label}: {len(res["profiles"])} step profile(s), {len(used)} monatomic'
                + (f' (h = {heights} Å)' if used else '')
                + f'; {int(res["labels"].max())} terraces; previous Z calibration '
                + (f'{cz * 1e9:.4g} nm/V' if cz else 'unknown (relative factor)')
                + (f'; header Z drift {_fmt_v(zinfo["drift_z_nm_per_s"])}, compensation '
                   f'{acq["drift_status"] or "?"}' if zinfo['drift_z_nm_per_s'] is not None else ''))
    return zscans, skipped


def _no_step_message(zscans, skipped, h0, tolerance):
    lines = [f'no monatomic step ({h0 * 1e10:.3f} Å ± {tolerance * 100:.0f} %) was found.']
    for z in zscans:
        seen = ', '.join(f'{q.h_m * 1e10:.2f} Å' for q in z.profiles[:6])
        lines.append(f'  {z.name}: ' + (f'steps of {seen}' if seen else 'no step edge (flat terrace?)'))
        reasons = {q.reason for q in z.profiles if q.reason}
        if reasons:
            lines.append('    ' + '; '.join(sorted(reasons))[:300])
    for name, why in skipped[:6]:
        lines.append(f'  {name}: {why}')
    lines.append('  Check the crystal (step height), the Z channel, or raise “Reject lattices off by more than (%)” '
                 'if the Z calibration is far off. You can also draw lines across the steps.')
    return '\n'.join(lines)


# --------------------------------------------------------------------------- run
def run_z(ctx, xy_out=None):
    p = ctx.parameters
    log = ctx.log
    h0, why = step_height_m(p)
    if not h0:
        raise zs.NoStepsFound('no monatomic step height is known for this crystal — choose a crystal or enter '
                              '“Monatomic step height (Å)”')
    z_channel = str(p.get('z_channel') or 'Z')
    tolerance = float(p.get('max_deviation_percent', 25.0)) / 100
    log(f'Z reference: monatomic step h₀ = {why}; topography channel {z_channel}')
    zscans, skipped = collect_steps(ctx, z_channel, h0, log)
    for name, reason in skipped:
        log(f'{name}: {reason}', 'warning')
    used_scans = [z for z in zscans if z.used]
    if not used_scans:
        raise zs.NoStepsFound(_no_step_message(zscans, skipped, h0, tolerance))
    zscans = used_scans
    relative = any(z.relative for z in zscans)
    if relative and not all(z.relative for z in zscans):
        raise ValueError('Some scans have a previous Z calibration in their header and others not. Enter the '
                         'previous Z calibration (nm/V) in Tool settings so every scan uses known constants.')
    ctx.progress(65, 'Fitting the Z calibration')
    estimates = zs.step_estimates(zscans, h0)
    fit = zs.combine(estimates)
    repeats = int(p.get('bootstrap_repeats', 400) or 0)
    boot = zs.bootstrap(estimates, repeats)
    loo = zs.leave_one_out(estimates, len(zscans))
    singles = zs.per_scan(estimates)
    subsets = zs.subsets(zscans, estimates, fit)
    pairs = zs.z_drift_pairs(zscans)
    # lateral (X/Y) correction of the profile distances, when the X/Y calibration was fitted in this run
    if xy_out:
        for z in zscans:
            match = next((s for s in xy_out['scans'] if Path(s.extra.get('path', '')).resolve() == Path(z.path).resolve()
                          and s.trace == z.trace), None)
            if match is None:
                match = next((s for s in xy_out['scans'] if Path(s.extra.get('path', '')).resolve() ==
                              Path(z.path).resolve()), None)
            if match is not None:
                _b, m = cc.corrected_basis_image(match, xy_out['fit'], xy_out['fallback'])
                z.extra['lateral_matrix'] = m
    cz_ref = float(np.median([z.cz_old or 1.0 for z in zscans]))
    factor = fit.cz / cz_ref
    unit = '×' if relative else 'nm/V'
    scale = 1 if relative else 1e9
    rows = [['Z reference (monatomic step)', h0 * 1e10, 'Å'],
            ['Previous Z calibration', cz_ref * scale, unit], ['New Z calibration', fit.cz * scale, unit],
            ['σ Z (fit, scaled by the scatter)', fit.sigma * scale, unit]]
    if len(boot):
        lo, hi = np.percentile(boot, [2.5, 97.5]) * scale
        rows.append(['Z 95 % CI (bootstrap over step edges)', f'{lo:.5g} – {hi:.5g}', unit])
    rows += [['Correction Z (new / previous)', factor, ''],
             ['Scans · step profiles used', f'{fit.n_scans} · {fit.n_steps}', ''],
             ['Reduced χ²', fit.chi2_red, ''],
             ['Mean step before', float(np.mean([abs(e[1].h_m) / e[1].n_layers for e in estimates])) * 1e10, 'Å'],
             ['Mean step after', float(np.mean([abs(e[1].h_m) / e[1].n_layers * fit.cz / (zscans[e[0]].cz_old or 1.0)
                                                for e in estimates])) * 1e10, 'Å'],
             ['Z drift treatment', 'linear Z drift / creep along each profile removed by the terrace slope', '']]
    for k, pr in enumerate(pairs, 1):
        rows.append([f'Z drift from up/down pair {k}', f'{pr["vz_nm_per_s"] * 60:.4g}', 'nm/min'])
    ctx.result_table(['quantity', 'value', 'unit'], rows, 'Z calibration (monatomic steps)')
    log(f'NEW Z CALIBRATION  Z = {fit.cz * scale:.5g} {unit} (×{factor:.4f}) ± {fit.sigma * scale:.2g} from '
        f'{fit.n_steps} step profile(s) on {fit.n_scans} scan(s)')
    if relative:
        log('The previous Z calibration was not found in the files: the value is a correction factor. New Z '
            'calibration = factor × the Z calibration used for these scans.', 'warning')
    for pr in pairs:
        log(f'Z drift, up/down pair {pr["up"]} ↔ {pr["down"]}: {_fmt_v(pr["vz_nm_per_s"])} (sample tilt '
            f'{pr["tilt_y_mrad"]:.2f} mrad); it does not bias the step heights (terrace slope fitted per profile).')

    # ---- per-profile table + CSV
    columns = ['scan', 'profile', 'drawn', 'edge direction (°)', 'layers', 'h before (Å)', 'σ (Å)',
               'h after (Å)', 'h after, leave-one-out (Å)', 'fit', 'used', 'note']
    table = []
    for i, z in enumerate(zscans):
        c_old = z.cz_old or 1.0
        for q in z.profiles:
            after = abs(q.h_m) * fit.cz / c_old
            after_loo = abs(q.h_m) * loo[i] / c_old if i in loo else ''
            table.append([z.name, q.index, 'yes' if q.manual else '', round(q.direction_deg % 180, 1),
                          q.n_layers or '', abs(q.h_m) * 1e10, q.sigma_m * 1e10, after * 1e10,
                          (after_loo * 1e10) if after_loo != '' else '', q.method, 'yes' if q.used else 'no',
                          q.reason])
    csv_path = ctx.output_dir / 'z_step_profiles.csv'
    with csv_path.open('w', newline='', encoding='utf8') as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(table)
    ctx.result_file(csv_path, 'Every step profile before / after')
    ctx.result_table(columns, [[r[0], r[1], r[2], r[3], r[4]] + [round(v, 4) if isinstance(v, float) else v
                                                                  for v in r[5:]] for r in table],
                     'Step profiles before → after')

    # ---- figures
    shown = next((z for z in zscans if z.is_current), zscans[0])
    if not shown.is_current:
        log(f'The active scan gave no usable step: the Z figures are drawn on {shown.name}.', 'warning')
    ctx.progress(75, 'Z figures')
    profile_files = []
    try:
        profile_files = profiles_figure(ctx, shown, fit, h0)
    except Exception:
        import traceback
        log('Step-profile figure could not be drawn:\n' + traceback.format_exc(limit=6), 'warning')
    scan_info = None
    try:
        scan_info = scan_figure(ctx, shown, fit, h0, log)
    except Exception:
        import traceback
        log('Z scan figure could not be drawn:\n' + traceback.format_exc(limit=8), 'warning')
    try:
        overview_figure(ctx, shown, fit, h0, profile_files, scan_info, log)
    except Exception:
        import traceback
        log('Z overview figure could not be drawn:\n' + traceback.format_exc(limit=6), 'warning')
    ctx.progress(88, 'Z statistics figure')
    try:
        statistics_figure(ctx, zscans, estimates, fit, h0, boot, loo, singles, subsets, pairs, relative, shown)
    except Exception as exc:
        log(f'Z statistics figure could not be drawn: {exc}', 'warning')

    summary = {'new_z_calibration_m_per_V': None if relative else fit.cz,
               'sigma_m_per_V': None if relative else fit.sigma,
               'previous_z_calibration_m_per_V': None if relative else cz_ref,
               'correction_factor': factor, 'step_height_reference_m': h0, 'profiles_used': fit.n_steps,
               'scans_used': fit.n_scans, 'file': 'z_calibration_result.json'}
    result = {
        'schema_version': 1, 'kind': 'spm_studio_z_calibration', 'method': 'monatomic steps',
        'reference': {'step_height_m': h0, 'description': why, 'material': str(p.get('material', ''))},
        'channel': z_channel, 'relative_factor_only': relative,
        'previous_calibration_m_per_V': None if relative else cz_ref,
        'new_calibration_m_per_V': None if relative else {'z': fit.cz, 'sigma_z': fit.sigma},
        'correction_factor': factor, 'reduced_chi2': fit.chi2_red,
        'bootstrap_95ci_m_per_V': None if not len(boot) else {'z': list(np.percentile(boot, [2.5, 97.5])),
                                                               'repeats_ok': int(len(boot))},
        'leave_one_scan_out_m_per_V': {zscans[i].name: v for i, v in loo.items()},
        'per_scan_m_per_V': {zscans[i].name: {'z': f.cz, 'sigma': f.sigma, 'n': f.n_steps} for i, f in singles.items()},
        'subsets_deviation_percent': [{'subset': n, 'deviation': d, 'sigma': s} for n, d, s in subsets],
        'drift': {'model': 'a constant Z drift or creep adds a plane v_z·t(x, y) inside a frame (t linear in x, y): '
                           'removed by the common terrace plane and by the slope fitted on every profile; '
                           'up/down pairs give v_z = Δslope / Δ(time gradient) along the slow axis',
                  'updown_pairs': pairs,
                  'per_scan': [{'scan': z.name, 'terrace_plane_slopes_m_per_nm': list(z.slopes_m_per_nm),
                                'header_drift_z_nm_per_s': z.extra.get('header_drift_z_nm_per_s'),
                                'compensation': z.extra.get('drift_status'),
                                'time_gradient_s_per_nm': None if z.time_gradient is None else list(z.time_gradient)}
                               for z in zscans]},
        'scans': [{'name': z.name, 'path': z.path, 'trace': z.trace, 'scan_angle_deg': z.angle_deg,
                   'fast_axis': z.fast_axis, 'slow_direction': z.slow_direction, 'previous_cz_m_per_V': z.cz_old,
                   'calibration_header_key': z.extra.get('cz_key'), 'size_nm': list(z.size_nm),
                   'terraces': int(z.terrace_labels.max()), 'edge_threshold_m_per_nm': z.extra.get('edge_threshold'),
                   'patch_radius_nm': z.extra.get('patch_radius_nm'),
                   'lateral_correction_from_xy': 'lateral_matrix' in z.extra,
                   'profiles': [{'index': q.index, 'drawn': q.manual, 'p0_px': list(q.p0_px), 'p1_px': list(q.p1_px),
                                 'edge_direction_deg': q.direction_deg, 'h_m': q.h_m, 'sigma_m': q.sigma_m,
                                 'h_profile_fit_m': q.h_profile_m, 'fit': q.method, 'layers': q.n_layers,
                                 'used': q.used, 'note': q.reason} for q in z.profiles]} for z in zscans],
        'skipped': [{'scan': n, 'reason': r} for n, r in skipped],
        'model': 'cz_new = cz_old · n · h₀ / h_measured for every profile; weighted mean (profile errors, 0.5 % '
                 'floor, Birge-scaled), bootstrap over step edges, leave-one-scan-out.',
    }
    path = ctx.output_dir / 'z_calibration_result.json'
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=float), encoding='utf8')
    ctx.result_file(path, 'Z calibration result (JSON)')
    return {'path': path, 'fit': fit, 'zscans': zscans, 'summary': summary}


# --------------------------------------------------------------------------- figures
def _new_size(z):
    w, h = z.size_nm
    m = z.extra.get('lateral_matrix')
    if m is None:
        return (w, h)
    return (w * float(np.linalg.norm(m[:, 0])), h * float(np.linalg.norm(m[:, 1])))


def _lateral_scale(z, q):
    m = z.extra.get('lateral_matrix')
    if m is None:
        return 1.0
    u = np.array([math.cos(math.radians(q.direction_deg)), math.sin(math.radians(q.direction_deg))])
    return float(np.linalg.norm(m @ u))


def _legend(painter, rect, rows, corner, font, bold):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFontMetricsF, QBrush
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
        y -= rect.height() * .10
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


def make_profile_decorator(profiles, shape, rows_left, rows_right, corners):
    """Painter callback: the numbered step profiles (coloured lines) and the two value boxes."""

    def decorate(painter, rect):
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QPen, QColor, QFont, QPainter
        ny, nx = shape

        def pt(c, r):
            return QPointF(rect.left() + (c + .5) / nx * rect.width(), rect.top() + (r + .5) / ny * rect.height())
        width = max(1.2, rect.width() * .0042)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont('DejaVu Sans')
        font.setPixelSize(max(9, int(rect.width() * .027)))
        bold = QFont(font)
        bold.setBold(True)
        for k, q in enumerate(profiles):
            color = zs.PALETTE[k % len(zs.PALETTE)]
            a, b = pt(*q.p0_px), pt(*q.p1_px)
            for pen in (QPen(QColor(0, 0, 0, 160), width + 1.8), QPen(QColor(color), width)):
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(a, b)
            dx, dy = b.x() - a.x(), b.y() - a.y()
            norm = max(1e-6, math.hypot(dx, dy))
            tag = QPointF(b.x() + dx / norm * font.pixelSize() * .75, b.y() + dy / norm * font.pixelSize() * .75)
            box = QRectF(tag.x() - font.pixelSize() * .7, tag.y() - font.pixelSize() * .62, font.pixelSize() * 1.4,
                         font.pixelSize() * 1.24)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawRoundedRect(box, 3, 3)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setFont(bold)
            painter.setPen(QColor(color))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), str(q.index))
        _legend(painter, rect, rows_left, corners[0], font, bold)
        _legend(painter, rect, rows_right, corners[1], font, bold)
        painter.restore()

    return decorate


def _rows(ctx, z, fit, h0):
    p = ctx.parameters
    ccal = str(p.get('calibration_color', '#7ee081'))
    pale = _mix(ccal, '#ffffff', .55)
    c_old = z.cz_old or 1.0
    used = z.used
    before = float(np.mean([abs(q.h_m) / q.n_layers for q in used]))
    after = before * fit.cz / c_old
    step_color = str(p.get('vector_a_color', '#16d8f5'))
    left = [('step', f'{before * 1e10:.3f} Å', f'{after * 1e10:.3f} Å', _mix(step_color, '#ffffff', .55), step_color),
            ('theory', '', f'{h0 * 1e10:.3f} Å', '#d8d8d8', '#ffffff'),
            ('profiles', '', f'{len(used)} used', '#d8d8d8', '#f2f2f2')]
    if z.relative:
        right = [('Z', '×1', f'×{fit.cz / c_old:.4f}', pale, ccal)]
    else:
        right = [('Z', f'{c_old * 1e9:.4g}', f'{fit.cz * 1e9:.4g} nm/V', pale, ccal)]
    if z.extra.get('lateral_matrix') is not None:
        right.append(('X/Y', '', 'recalibrated', pale, '#f2f2f2'))
    corners = (str(p.get('lattice_legend_corner', 'top_left')), str(p.get('calibration_legend_corner', 'top_right')))
    if corners[0] == corners[1]:
        corners = (corners[0], 'top_right' if corners[0] != 'top_right' else 'top_left')
    return left, right, corners


def scan_figure(ctx, z, fit, h0, log):
    """The topography (recalibrated heights) with the numbered profiles, drawn like the Export panel."""
    from spm_studio.core import script_figures as figures
    p = ctx.parameters
    channel = str(p.get('z_channel') or 'Z')
    data = np.asarray(z.display, float) * (fit.cz / (z.cz_old or 1.0))
    size = _new_size(z)
    left, right, corners = _rows(ctx, z, fit, h0)
    decorate = make_profile_decorator(z.used, data.shape, left, right, corners)
    cfg = getattr(ctx, 'plot_config', None) or {'schema_version': 1}
    style = figures.scan_display_style(cfg, channel, colormap_override=p.get('scan_colormap', ''))
    title = figures.colorbar_title(cfg, channel, '')
    formats = tuple(getattr(ctx, 'plot_formats', None) or ('svg',))
    base = ctx.output_dir / 'z_steps_scan'
    info = {'data': data, 'size_nm': size, 'style': style, 'title': title, 'decorate': decorate, 'channel': channel,
            'left': left, 'right': right, 'corners': corners}
    try:
        written = figures.export_scan_figure(base, scan_path=z.path, data=data, size_nm=size, channel=channel,
                                             unit='m', plot_config=cfg, formats=formats, style=style, decorate=decorate,
                                             title=title, figure_title=str(p.get('figure_title', '') or ''))
        written = [Path(w) for w in written if w and Path(w).is_file()]
        if not written:
            raise RuntimeError('the Export-panel renderer wrote no file')
        info['renderer'] = 'export panel'
    except Exception:
        import traceback
        log('Export-panel renderer failed, the Z scan figure is drawn with Matplotlib instead:\n'
            + traceback.format_exc(limit=6), 'warning')
        written = matplotlib_scan(base, z, data, size, left, right, corners, formats, title,
                                  p.get('scan_colormap', ''), str(p.get('figure_title', '') or ''))
        info['renderer'] = 'matplotlib'
    for path in written:
        ctx.result_file(path, 'Z calibration: scan with the step profiles · ' + path.suffix[1:].upper())
    info['files'] = written
    return info


def _draw_scan_matplotlib(ax, z, data, size, left, right, corners, colormap='', title='', with_colorbar=None):
    import matplotlib
    from matplotlib import patheffects
    from matplotlib.offsetbox import AnchoredOffsetbox, HPacker, VPacker, TextArea
    cmap = colormap if colormap and colormap in matplotlib.colormaps else 'afmhot'
    shown = data * 1e9
    unit = 'nm'
    finite = shown[np.isfinite(shown)]
    if finite.size and np.ptp(finite) < 1:
        shown, unit = shown * 10, 'Å'
    finite = shown[np.isfinite(shown)]
    lo, hi = np.percentile(finite, [1, 99]) if finite.size else (0, 1)
    w, h = size
    im = ax.imshow(shown, extent=[0, w, 0, h], origin='upper', cmap=cmap, vmin=lo, vmax=hi, interpolation='nearest')
    ax.set_xticks([])
    ax.set_yticks([])
    ny, nx = data.shape
    stroke = [patheffects.Stroke(linewidth=3, foreground='black', alpha=.65), patheffects.Normal()]
    for k, q in enumerate(z.used):
        color = zs.PALETTE[k % len(zs.PALETTE)]
        xs = [(c + .5) / nx * w for c in (q.p0_px[0], q.p1_px[0])]
        ys = [h - (r + .5) / ny * h for r in (q.p0_px[1], q.p1_px[1])]
        line, = ax.plot(xs, ys, color=color, lw=1.6, solid_capstyle='round')
        line.set_path_effects(stroke)
        ax.text(xs[1], ys[1], f' {q.index}', color=color, fontsize=7, weight='bold', va='center',
                path_effects=[patheffects.withStroke(linewidth=2, foreground='black')])
    loc = {'top_left': 'upper left', 'top_right': 'upper right', 'bottom_left': 'lower left',
           'bottom_right': 'lower right'}
    for items, corner in ((left, corners[0]), (right, corners[1])):
        lines = [HPacker(children=[TextArea(f'{lab}  ', textprops=dict(color='#f2f2f2', size=6.5)),
                                   TextArea(f'{o} → ' if o else '', textprops=dict(color=co, size=6.5)),
                                   TextArea(n, textprops=dict(color=cn, size=6.5, weight='bold'))],
                         align='baseline', pad=0, sep=0) for lab, o, n, co, cn in items]
        box = AnchoredOffsetbox(loc=loc.get(corner, 'upper left'), child=VPacker(children=lines, align='left', pad=0,
                                                                                  sep=2),
                                pad=.35, borderpad=.4, frameon=True)
        box.patch.set_facecolor('black')
        box.patch.set_alpha(.6)
        box.patch.set_edgecolor('none')
        ax.add_artist(box)
    bar = 10 ** math.floor(math.log10(max(w / 4, 1e-9)))
    bar = next((m * bar for m in (5, 2, 1) if m * bar <= w / 3), bar)
    ax.plot([w * .95 - bar, w * .95], [h * .06, h * .06], color='black', lw=3, solid_capstyle='butt')
    ax.text(w * .95 - bar / 2, h * .08, f'{bar:g} nm', color='black', ha='center', va='bottom', fontsize=7)
    return im, unit


def matplotlib_scan(base, z, data, size, left, right, corners, formats, title, colormap='', figure_title=''):
    import matplotlib
    matplotlib.use('Agg', force=False)
    from matplotlib.figure import Figure
    w, h = size
    fig = Figure(figsize=(4.2, 4.2 * h / w + .7), dpi=200, layout='constrained')
    ax = fig.add_subplot()
    im, unit = _draw_scan_matplotlib(ax, z, data, size, left, right, corners, colormap)
    cb = fig.colorbar(im, ax=ax, location='bottom', fraction=.05, pad=.02, aspect=30)
    cb.set_label(f'{title or "Z"} ({unit})', fontsize=7)
    cb.ax.tick_params(labelsize=6)
    if figure_title:
        fig.suptitle(figure_title, fontsize=9)
    written = []
    for fmt in formats:
        path = Path(f'{base}.{fmt}')
        fig.savefig(path, dpi=300 if fmt in ('png', 'jpg') else None)
        written.append(path)
    return written


def _profile_curves(z, q, factor, lateral):
    """Distance from the edge (nm, laterally recalibrated) and height above the lower terrace (Å)."""
    d = q.distance_nm
    s = (d - q.s0_nm) * lateral
    base = q.offset_m + q.slope_m_per_nm * (d - q.s0_nm)          # lower terrace (1-D fit) incl. its slope
    rel = (q.height_m - base) * factor
    low = d < q.s0_nm + q.exclusion_nm[0]
    if low.any():
        rel = rel - float(np.median(rel[low]))
    model = None
    if q.model_m is not None:
        model = (np.asarray(q.model_m, float) - base) * factor
        if low.any():
            model = model - float(np.median(model[low]))
    return s, rel * 1e10, (model * 1e10 if model is not None else None)


def profiles_figure(ctx, z, fit, h0):
    """The step profiles of the figure scan: previous calibration (left) and new calibration (right)."""
    from spm_studio.core.plots import plot_style
    from spm_studio.core.analysis_utils import save_plot
    c_old = z.cz_old or 1.0
    used = z.used
    with plot_style(getattr(ctx, 'plot_config', None)) as plt:
        fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.3), sharey=True, squeeze=False)
        for col, (factor, name) in enumerate(((1.0, 'Before (previous Z calibration)'),
                                              (fit.cz / c_old, 'After (new Z calibration)'))):
            ax = axes[0, col]
            ax.axhline(0, color='#bbbbbb', lw=.7)
            ax.axhline(h0 * 1e10, color='#444444', lw=.9, ls='--', label=f'h₀ = {h0 * 1e10:.3f} Å')
            for k, q in enumerate(used):
                color = zs.PALETTE[k % len(zs.PALETTE)]
                s, rel, model = _profile_curves(z, q, factor, _lateral_scale(z, q))
                ax.plot(s, rel, color=color, lw=1.0, alpha=.9,
                        label=f'{q.index}: {abs(q.h_m) / q.n_layers * factor * 1e10:.3f} Å'
                              + (f' (/{q.n_layers})' if q.n_layers > 1 else ''))
                if model is not None:
                    ax.plot(s, model, color=color, lw=.7, ls=':', alpha=.9)
            mean = np.mean([abs(q.h_m) / q.n_layers for q in used]) * factor * 1e10
            ax.set_title(f'{name}\nmean step {mean:.3f} Å', loc='left', fontsize='small')
            ax.set_xlabel('Distance from the step edge (nm)')
            if col == 0:
                ax.set_ylabel('Height above the lower terrace (Å)')
            ax.legend(fontsize='xx-small', loc='lower right', frameon=True, framealpha=.85, edgecolor='none',
                      ncol=2 if len(used) > 6 else 1,
                      title='X/Y recalibrated' if z.extra.get('lateral_matrix') is not None else None,
                      title_fontsize='xx-small')
        save_plot(ctx, fig, 'z_step_profiles')
    files = [ctx.output_dir / f'z_step_profiles.{ext}' for ext in getattr(ctx, 'plot_formats', ('svg',))]
    return [f for f in files if f.is_file()]


def overview_figure(ctx, z, fit, h0, profile_files, scan_info, log):
    """The scan and its step profiles side by side (Export-panel renderer, Matplotlib fallback)."""
    formats = tuple(getattr(ctx, 'plot_formats', None) or ('svg',))
    base = ctx.output_dir / 'z_calibration_overview'
    report = next((f for ext in ('.svg', '.pdf', '.png') for f in profile_files if f.suffix == ext), None)
    written = []
    if scan_info is not None and scan_info.get('renderer') == 'export panel' and report is not None:
        try:
            from spm_studio.core import script_figures as figures
            from spm_studio.core.export_layout import export_publication
            from spm_studio.core.plot_settings import default_scale_bar_color
            from types import SimpleNamespace
            figures.ensure_qt_gui()
            cfg = getattr(ctx, 'plot_config', None) or {'schema_version': 1}
            scan_spec = {'kind': 'array', 'data': scan_info['data'], 'size_nm': list(map(float, scan_info['size_nm'])),
                         'style': scan_info['style'], 'title': scan_info['title'], 'unit': '', 'base_unit': 'm',
                         'colorbar_position': 'below', 'show_colorbar': True,
                         'scale_bar_color': default_scale_bar_color(scan_info['channel']),
                         'scale_bar_position': 'bottom_right', 'show_scale_bar': True, 'display_zero': False,
                         'lattice': None, 'decorate': scan_info['decorate'], 'figure_title': ''}
            plot_spec = {'kind': 'report', 'path': str(report), 'title': '', 'unit': '', 'colorbar_position': 'none',
                         'show_colorbar': False, 'scale_bar_color': '#111111', 'scale_bar_position': 'bottom_right',
                         'show_scale_bar': False}
            preset = dict(figures.export_preset(cfg))
            preset['width_mm'] = 178.0
            preset['height_mm'] = 82.0
            scan = SimpleNamespace(path=Path(z.path), channels={})
            transparent = bool(cfg.get('transparent_background', False))
            for fmt in figures.figure_formats(formats):
                out = export_publication(scan, [scan_spec, plot_spec], Path(f'{base}.{fmt}'), preset,
                                         plot_config=cfg, transparent=transparent, arrangement='row',
                                         panel_letters=False)
                if out and Path(out).is_file():
                    written.append(Path(out))
        except Exception:
            import traceback
            log('Export-panel renderer failed for the Z overview, drawn with Matplotlib instead:\n'
                + traceback.format_exc(limit=6), 'warning')
            written = []
    if not written:
        written = matplotlib_overview(base, ctx, z, fit, h0, scan_info, formats)
    for path in written:
        ctx.result_file(path, 'Z calibration: scan and step profiles · ' + path.suffix[1:].upper())
    return written


def matplotlib_overview(base, ctx, z, fit, h0, scan_info, formats):
    import matplotlib
    matplotlib.use('Agg', force=False)
    from matplotlib.figure import Figure
    p = ctx.parameters
    data = np.asarray(z.display, float) * (fit.cz / (z.cz_old or 1.0))
    size = _new_size(z)
    left, right, corners = _rows(ctx, z, fit, h0)
    fig = Figure(figsize=(8.6, 3.9), dpi=200, layout='constrained')
    ax_img, ax_prof = fig.subplots(1, 2, gridspec_kw={'width_ratios': [1, 1.15]})
    im, unit = _draw_scan_matplotlib(ax_img, z, data, size, left, right, corners, p.get('scan_colormap', ''))
    cb = fig.colorbar(im, ax=ax_img, location='bottom', fraction=.05, pad=.02, aspect=30)
    cb.set_label(f'Z ({unit})', fontsize=7)
    cb.ax.tick_params(labelsize=6)
    factor = fit.cz / (z.cz_old or 1.0)
    ax_prof.axhline(0, color='#bbbbbb', lw=.7)
    ax_prof.axhline(h0 * 1e10, color='#444444', lw=.9, ls='--', label=f'h₀ = {h0 * 1e10:.3f} Å')
    for k, q in enumerate(z.used):
        color = zs.PALETTE[k % len(zs.PALETTE)]
        s, rel, model = _profile_curves(z, q, factor, _lateral_scale(z, q))
        ax_prof.plot(s, rel, color=color, lw=1.0, label=f'{q.index}: {abs(q.h_m) / q.n_layers * factor * 1e10:.3f} Å')
    ax_prof.set_xlabel('Distance from the step edge (nm)', fontsize=7)
    ax_prof.set_ylabel('Height above the lower terrace (Å)', fontsize=7)
    ax_prof.tick_params(labelsize=6)
    ax_prof.legend(fontsize=5.5, loc='lower right', frameon=False, ncol=2 if len(z.used) > 6 else 1)
    ax_prof.set_title('Step profiles (new Z calibration)', fontsize=8, loc='left')
    written = []
    for fmt in formats:
        path = Path(f'{base}.{fmt}')
        fig.savefig(path, dpi=300 if fmt in ('png', 'jpg') else None)
        written.append(path)
    return written


def statistics_figure(ctx, zscans, estimates, fit, h0, boot, loo, singles, subsets, pairs, relative, shown):
    """Does the new Z calibration explain every step? (same logic as the X/Y statistics)."""
    from spm_studio.core.plots import plot_style
    from spm_studio.core.analysis_utils import save_plot
    scale = 1 if relative else 1e9
    unit = '×' if relative else 'nm/V'
    with plot_style(getattr(ctx, 'plot_config', None)) as plt:
        fig, axes = plt.subplots(2, 3, figsize=(12.0, 7.0), squeeze=False)
        # (a) every profile before → after ------------------------------------------------
        ax = axes[0, 0]
        before = np.array([abs(e[1].h_m) / e[1].n_layers for e in estimates]) * 1e10
        sig = np.array([e[1].sigma_m / e[1].n_layers for e in estimates]) * 1e10
        olds = np.array([zscans[e[0]].cz_old or 1.0 for e in estimates])
        after_all = before * fit.cz / olds
        after = np.array([b * (loo.get(e[0], fit.cz)) / o for b, e, o in zip(before, estimates, olds)])
        x = np.arange(len(estimates)) + 1
        ax.axhline(h0 * 1e10, color='#444444', lw=.8, label=f'h₀ = {h0 * 1e10:.3f} Å')
        ax.errorbar(x, before, yerr=sig, fmt='o', ms=3.5, color=OLD, capsize=1.5, lw=.7, label='Before')
        ax.errorbar(x, after, yerr=sig * fit.cz / olds, fmt='D', ms=3.5, color=NEW, capsize=1.5, lw=.7,
                    label='After' + (' (leave-one-scan-out)' if loo else ''))
        rms_b = float(np.sqrt(np.mean((before / (h0 * 1e10) - 1) ** 2)) * 100)
        rms_a = float(np.sqrt(np.mean((after_all / (h0 * 1e10) - 1) ** 2)) * 100)
        ax.set_xlabel('Step profile (all scans)')
        ax.set_ylabel('Step height per layer (Å)')
        ax.set_title(f'RMS error {rms_b:.2f} % → {rms_a:.2f} %', loc='left')
        ax.legend(fontsize='x-small', loc='best', frameon=True, framealpha=.9, edgecolor='none')
        # (b) terrace levels of the figure scan (after) ---------------------------------------
        ax = axes[0, 1]
        factor = fit.cz / (shown.cz_old or 1.0)
        lev = shown.leveled[shown.terrace_labels > 0] * factor * 1e10
        if lev.size:
            lo = np.percentile(lev, .5)
            hist, edges = np.histogram(lev - lo, bins=200)
            centres = (edges[:-1] + edges[1:]) / 2
            ax.fill_between(centres, hist, step='mid', color='#cfe0f1')
            ax.plot(centres, hist, color=NEW, lw=.8, drawstyle='steps-mid')
            ref_level = centres[int(np.argmax(hist))]
            top = centres.max()
            for m in range(-int(ref_level // (h0 * 1e10)) - 1, int((top - ref_level) // (h0 * 1e10)) + 2):
                ax.axvline(ref_level + m * h0 * 1e10, color='#444444', lw=.6, ls='--')
        ax.set_xlabel('Height on the terraces, new calibration (Å)')
        ax.set_ylabel('Pixels')
        ax.set_title('Terrace levels (dashed: n × h₀)', loc='left')
        # (c) every scan alone vs all scans --------------------------------------------------
        ax = axes[0, 2]
        idx = sorted(singles)
        if idx:
            ax.errorbar(np.array(idx) + 1, [singles[i].cz * scale for i in idx],
                        yerr=[singles[i].sigma * scale for i in idx], fmt='o', color=NEW, ms=4, capsize=2, lw=.9,
                        label='Each scan alone')
        ax.axhspan((fit.cz - fit.sigma) * scale, (fit.cz + fit.sigma) * scale, color='#cfe0f1', zorder=0,
                   label='All scans ±1σ')
        ax.axhline(fit.cz * scale, color=NEW, lw=1.4, label=f'New {fit.cz * scale:.4g} {unit}')
        if len(boot):
            lo, hi = np.percentile(boot, [2.5, 97.5])
            ax.axhline(lo * scale, color=NEW, lw=.7, ls=':')
            ax.axhline(hi * scale, color=NEW, lw=.7, ls=':', label='Bootstrap 95 % CI')
        prev = np.array([(z.cz_old or 1.0) for z in zscans])
        ax.scatter(np.arange(len(zscans)) + 1, prev * scale, marker='_', s=120, color=OLD, lw=2, label='Previous')
        ax.set_xlim(.4, len(zscans) + .6)
        ax.set_xticks(np.arange(len(zscans)) + 1)
        ax.set_xlabel('Scan')
        ax.set_ylabel(f'Z calibration ({unit})')
        ax.set_title('Z calibration', loc='left')
        ax.legend(fontsize='x-small', loc='best', frameon=True, framealpha=.9, edgecolor='none')
        # (d) subsets ----------------------------------------------------------------------
        ax = axes[1, 0]
        if subsets:
            pos = np.arange(len(subsets))
            ax.bar(pos, [d for _n, d, _s in subsets], .55, yerr=[s for _n, _d, s in subsets], color='#5b8fc7',
                   capsize=2)
            ax.axhline(0, color='#444444', lw=.8)
            ax.set_xticks([])
            top = max(max(abs(d) + s_ for _n, d, s_ in subsets), 1e-6)
            for x0, (n_, _d, _s) in zip(pos, subsets):
                ax.text(x0, -top * 1.25, n_, ha='center', va='top', fontsize='x-small')
            ax.set_ylim(-top * 1.9, top * 1.5)
            ax.set_xlabel('Subset of scans (count)')
            ax.set_ylabel('Deviation from all-scan fit (%)')
            ax.set_title('Subsets agree?', loc='left')
        elif len(boot):
            ax.hist(boot * scale, bins=30, color='#cfe0f1', edgecolor=NEW, lw=.4)
            ax.axvline(fit.cz * scale, color=ACCENT, lw=1.2)
            ax.set_xlabel(f'Z calibration ({unit})')
            ax.set_ylabel('Bootstrap samples')
            ax.set_title('Bootstrap over step edges', loc='left')
        else:
            ax.set_axis_off()
            ax.text(.5, .5, 'Open more scans with steps (up and down,\nfast axis X and Y) to test the\n'
                    'calibration on independent subsets.', ha='center', va='center', transform=ax.transAxes,
                    fontsize='small', color='#555555')
        # (e) direction of the step edge ------------------------------------------------------
        ax = axes[1, 1]
        phi = np.array([(e[1].direction_deg + zscans[e[0]].angle_deg) % 180 for e in estimates])
        ax.axhline(0, color='#444444', lw=.8)
        ax.scatter(phi, (before / (h0 * 1e10) - 1) * 100, color=OLD, s=18, label='Before')
        ax.scatter(phi, (after_all / (h0 * 1e10) - 1) * 100, color=NEW, s=18, marker='D', label='After')
        ax.set_xlim(0, 180)
        ax.set_xticks([0, 45, 90, 135, 180])
        ax.set_xlabel('Step-edge normal in piezo frame (° from X)')
        ax.set_ylabel('Height error (%)')
        ax.set_title('Height vs step direction', loc='left')
        ax.legend(fontsize='x-small', loc='best', frameon=True, framealpha=.9, edgecolor='none')
        # (f) drift and summary --------------------------------------------------------------
        ax = axes[1, 2]
        ax.set_axis_off()
        lines = [f'{fit.n_steps} profiles on {fit.n_scans} scan(s); reduced χ² {fit.chi2_red:.2f}',
                 f'new Z = {fit.cz * scale:.5g} ± {fit.sigma * scale:.2g} {unit}']
        if len(boot):
            lo, hi = np.percentile(boot, [2.5, 97.5]) * scale
            lines.append(f'bootstrap 95 % CI {lo:.5g} – {hi:.5g}')
        for z in zscans:
            hz = z.extra.get('header_drift_z_nm_per_s')
            if hz is not None:
                lines.append(f'{z.name[:26]}: header Z drift {hz * 60:+.3g} nm/min ({z.extra.get("drift_status") or "?"})')
        for pr in pairs:
            lines.append(f'up/down pair: Z drift {pr["vz_nm_per_s"] * 60:+.3g} nm/min')
        lines += ['', 'Model: cz_new = cz_old · n·h₀ / h_measured',
                  'Terraces: one plane + one offset per terrace,',
                  'line offsets removed on the terraces only.',
                  'Linear Z drift / creep (∝ time ∝ position)',
                  'is absorbed by the fitted terrace slope.']
        ax.text(0, 1, '\n'.join(lines), va='top', ha='left', fontsize='small', transform=ax.transAxes)
        save_plot(ctx, fig, 'z_calibration_statistics')
