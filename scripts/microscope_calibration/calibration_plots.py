"""Statistics figure that shows whether the new calibration is right (matplotlib)."""
from __future__ import annotations

import math

import numpy as np

import calibration_core as cc

OLD = '#9aa6b2'      # before calibration: pale
NEW = '#1f4e79'      # after calibration: dark
ACCENT = '#c8102e'


def _after_lengths(equations, fit, loo, scans):
    """After-calibration length of every equation: leave-one-out when available (honest)."""
    loo_map = {(i, lab): after for i, lab, _t, _b, after in loo}
    out = []
    for e in equations:
        out.append(loo_map.get((e.scan, e.label), fit.predict(e)))
    return np.asarray(out, float), bool(loo_map)


def statistics_figure(ctx, scans, equations, fit, ref, boot, loo, singles, relative, fallback, pairs=()):
    from spm_studio.core.plots import plot_style
    from spm_studio.core.analysis_utils import save_plot
    theory = np.array([e.theory_nm for e in equations])
    before = np.array([np.linalg.norm(e.vector_nm) for e in equations])
    after, honest = _after_lengths(equations, fit, loo, scans)
    phi = np.array([math.degrees(math.atan2(e.vector_nm[1], e.vector_nm[0])) % 180 for e in equations])
    multi = len(scans) > 1
    scale = 1 if relative else 1e9
    unit = '×' if relative else 'nm/V'
    with plot_style(getattr(ctx, 'plot_config', None)) as plt:
        ncols = 3
        drift_row = multi and (fit.drift_mode != 'none' or bool(pairs) or
                               any(s.extra.get('header_drift') is not None for s in scans))
        nrows = (3 if drift_row else 2) if multi else 1
        fig, axes = plt.subplots(nrows, ncols, figsize=(4.0 * ncols, 3.5 * nrows), squeeze=False)
        # (1) length ratio vs direction in the piezo frame -----------------------------
        ax = axes[0, 0]
        ax.axhline(1, color='#444444', lw=.8)
        ax.scatter(phi, before / theory, s=22, color=OLD, edgecolor='none', label='Before', zorder=3)
        ax.scatter(phi, after / theory, s=22, color=NEW, edgecolor='none', zorder=4,
                   label='After' + (' (leave-one-out)' if honest else ''))
        cx_old = np.median([s.cx_old for s in scans])
        cy_old = np.median([s.cy_old for s in scans])
        kx, ky = fit.cx / cx_old, fit.cy / cy_old
        t = np.radians(np.linspace(0, 180, 361))
        model = 1 / np.sqrt((kx * np.cos(t)) ** 2 + (ky * np.sin(t)) ** 2)
        ax.plot(np.degrees(t), model, color=OLD, lw=1.2, ls='--', label='Model of the previous error')
        ax.set_xlim(0, 180)
        ax.set_xticks([0, 45, 90, 135, 180])
        ax.set_xlabel('Vector direction in piezo frame (° from X)')
        ax.set_ylabel('Measured / theoretical length')
        ax.set_title('Length error vs direction', loc='left')
        ax.legend(fontsize='x-small', loc='best', frameon=True, framealpha=.9, edgecolor='none')
        # (2) per-scan error of the cell parameters ------------------------------------
        ax = axes[0, 1]
        labels = {'a': 'a', 'b': 'b', 'd_short': 'short diag.', 'd_long': 'long diag.'}
        kinds = [k for k in labels if any(e.label == k for e in equations)]
        x = np.arange(len(scans))
        width = .8 / max(1, len(kinds))
        for j, kind in enumerate(kinds):
            idx = [i for i, e in enumerate(equations) if e.label == kind]
            sc = np.array([equations[i].scan for i in idx]) + 1
            err_b = (before[idx] / theory[idx] - 1) * 100
            err_a = (after[idx] / theory[idx] - 1) * 100
            pos = sc + (j - (len(kinds) - 1) / 2) * width
            ax.scatter(pos, err_b, marker='o', s=16, color=OLD, zorder=3, label='Before' if j == 0 else None)
            ax.scatter(pos, err_a, marker='D', s=16, color=NEW, zorder=4, label='After' if j == 0 else None)
            for p0, b0, a0 in zip(pos, err_b, err_a):
                ax.plot([p0, p0], [b0, a0], color='#c9d1d9', lw=.7, zorder=2)
        resolution = np.median([e.sigma_nm / np.linalg.norm(e.vector_nm) for e in equations]) * 100
        ax.axhspan(-resolution, resolution, color='#e8eef5', zorder=0, label=f'±FFT resolution ({resolution:.2g} %)')
        ax.axhline(0, color='#444444', lw=.8)
        ax.set_xticks(x + 1)
        ax.set_xlim(.4, len(scans) + .6)
        ax.set_xlabel('Scan number (a, b, diagonals side by side)')
        ax.set_ylabel('Length error (%)')
        rms_b = float(np.sqrt(np.mean((before / theory - 1) ** 2)) * 100)
        rms_a = float(np.sqrt(np.mean((after / theory - 1) ** 2)) * 100)
        ax.set_title(f'RMS error {rms_b:.2f} % → {rms_a:.2f} %', loc='left')
        ax.legend(fontsize='x-small', loc='best', frameon=True, framealpha=.9, edgecolor='none')
        # (3) cell angle -----------------------------------------------------------------
        if True:
            target = axes[0, 2]
            g_before, g_after = [], []
            for s in scans:
                g_before.append(cc.cell_parameters(s.basis_image_nm)[2])
                basis, _m = cc.corrected_basis_image(s, fit, fallback)
                g_after.append(cc.cell_parameters(basis)[2])
            g_before = np.array(g_before)
            g_after = np.array(g_after)
            if ref.gamma_deg:
                fold = lambda g: np.where(abs(g - ref.gamma_deg) <= abs(180 - g - ref.gamma_deg), g, 180 - g)
                g_before, g_after = fold(g_before), fold(g_after)
                target.axhline(ref.gamma_deg, color='#444444', lw=.8)
            n = np.arange(len(scans)) + 1
            target.scatter(n, g_before, color=OLD, s=18, label='Before')
            target.scatter(n, g_after, color=NEW, s=18, marker='D', label='After')
            target.set_xticks(n)
            target.set_xlim(.4, len(scans) + .6)
            target.set_xlabel('Scan')
            target.set_ylabel('Cell angle γ (°)')
            target.set_title('Cell angle' + (f' (theory {ref.gamma_deg:g}°)' if ref.gamma_deg else ''), loc='left')
            target.legend(fontsize='x-small', loc='best', frameon=True, framealpha=.9, edgecolor='none')
        if multi:
            # (4) calibration of every scan alone vs the global fit ------------------------
            for col, (axis, value, sigma, k) in enumerate((('X', fit.cx, fit.sigma_cx, 0), ('Y', fit.cy, fit.sigma_cy, 1))):
                ax = axes[1, col]
                vals, idx = [], []
                for i, f in singles:
                    if f is not None:
                        vals.append((f.cx, f.sigma_cx) if k == 0 else (f.cy, f.sigma_cy))
                        idx.append(i)
                if vals:
                    v = np.array(vals)
                    ax.errorbar(np.array(idx) + 1, v[:, 0] * scale, yerr=v[:, 1] * scale, fmt='o', color=NEW,
                                ms=4, capsize=2, lw=.9, label='Each scan alone')
                ax.axhspan((value - sigma) * scale, (value + sigma) * scale, color='#cfe0f1', zorder=0,
                           label='All scans ±1σ')
                ax.axhline(value * scale, color=NEW, lw=1.4, label=f'New {value * scale:.4g} {unit}')
                if len(boot):
                    lo, hi = np.percentile(boot[:, k], [2.5, 97.5])
                    ax.axhline(lo * scale, color=NEW, lw=.7, ls=':')
                    ax.axhline(hi * scale, color=NEW, lw=.7, ls=':', label='Bootstrap 95 % CI')
                prev = np.array([s.cx_old if k == 0 else s.cy_old for s in scans])
                ax.scatter(np.arange(len(scans)) + 1, prev * scale, marker='_', s=120, color=OLD, lw=2,
                           label='Previous')
                ax.set_xlim(.4, len(scans) + .6)
                ax.set_xticks(np.arange(len(scans)) + 1)
                ax.set_xlabel('Scan')
                ax.set_ylabel(f'Calibration {axis} ({unit})')
                ax.set_title(f'{axis} calibration', loc='left')
                ax.legend(fontsize='x-small', loc='center', frameon=True, framealpha=.9, edgecolor='none')
            # (5) consistency between groups: fast axis X / Y, slow up / down ---------------
            ax = axes[1, 2]
            groups = {}
            for s in scans:
                groups.setdefault(f'fast {s.fast_axis}', []).append(s)
                if s.slow_direction:
                    groups.setdefault(f'slow {s.slow_direction}', []).append(s)
                groups.setdefault(s.trace, []).append(s)
            names, cxs, cys = [], [], []
            for name, members in groups.items():
                if len(members) == len(scans):
                    continue
                try:
                    f, _ = cc.calibrate(members, ref, False, fallback,
                                        extra_drift=fit.drift if fit.drift_mode == 'fitted' else None)
                except ValueError:
                    continue
                names.append(f'{name} ({len(members)})')
                cxs.append((f.cx / fit.cx - 1) * 100)
                cys.append((f.cy / fit.cy - 1) * 100)
            if names:
                pos = np.arange(len(names))
                ax.bar(pos - .18, cxs, .36, color='#5b8fc7', label='X')
                ax.bar(pos + .18, cys, .36, color='#e0a33a', label='Y')
                ax.axhline(0, color='#444444', lw=.8)
                ax.set_xticks([])
                top = max(max(map(abs, cxs)), max(map(abs, cys)), 1e-6)
                for p0, name in zip(pos, names):
                    ax.text(p0, -top * 1.25, name, ha='center', va='top', fontsize='x-small', rotation=0)
                ax.set_ylim(-top * 1.9, top * 1.5)
                ax.set_xlabel('Subset of scans (count)')
                ax.set_ylabel('Deviation from all-scan fit (%)')
                ax.set_title('Subsets agree?', loc='left')
                ax.legend(fontsize='x-small', loc='best', frameon=True, framealpha=.9, edgecolor='none')
            elif len(boot):
                ax.scatter(boot[:, 0] * scale, boot[:, 1] * scale, s=5, color=NEW, alpha=.35, edgecolor='none')
                ax.scatter([fit.cx * scale], [fit.cy * scale], color=ACCENT, s=30, zorder=5, label='All scans')
                ax.set_xlabel(f'X ({unit})')
                ax.set_ylabel(f'Y ({unit})')
                ax.set_title('Bootstrap over scans', loc='left')
                ax.legend(fontsize='x-small', loc='best', frameon=True, framealpha=.9, edgecolor='none')
            else:
                ax.set_axis_off()
                ax.text(.5, .5, 'Open scans with the fast axis along X and along Y\n(scan angle 0° and 90°)\n'
                        'to test the calibration on independent subsets.', ha='center', va='center',
                        transform=ax.transAxes, fontsize='small', color='#555555')
        if drift_row:
            _drift_panels(axes[2], scans, equations, fit, ref, fallback, pairs)
        save_plot(ctx, fig, 'calibration_statistics')
    for ext in getattr(ctx, 'plot_formats', ('svg',)):
        path = ctx.output_dir / f'calibration_statistics.{ext}'
        if path.is_file():
            ctx.result_file(path, 'Calibration statistics · ' + ext.upper())


def _drift_panels(axes, scans, equations, fit, ref, fallback, pairs):
    """(g) drift estimates, (h) length error with / without drift correction, (i) summary."""
    import matplotlib.patches as mpatches
    ax = axes[0]
    ax.axhline(0, color='#bbbbbb', lw=.6)
    ax.axvline(0, color='#bbbbbb', lw=.6)
    pts = []
    for s in scans:
        h = s.extra.get('header_drift')
        if h is not None:
            on = cc.compensation_on(s.extra.get('drift_status'))
            ax.scatter([h[0] * 60], [h[1] * 60], marker='x', color='#7f7f7f', s=28,
                       label='Header compensation (on)' if on else 'Header value (off)')
            pts.append(h)
    for k, pr in enumerate(pairs):
        ax.scatter([pr['drift'][0] * 60], [pr['drift'][1] * 60], marker='D', color='#e0a33a', s=26,
                   label='Up/down pair (no reference used)' if k == 0 else None, zorder=4)
        pts.append(pr['drift'])
    if fit.drift_mode == 'fitted':
        v = fit.drift * 60
        cov = fit.drift_cov * 3600
        ax.scatter([v[0]], [v[1]], color=ACCENT, s=36, zorder=5, label='Fitted with the calibration')
        w, vec = np.linalg.eigh(cov)
        w = np.sqrt(np.clip(w, 0, None))
        angle = math.degrees(math.atan2(vec[1, 1], vec[0, 1]))
        ax.add_patch(mpatches.Ellipse(v, 2 * 2.4477 * w[1], 2 * 2.4477 * w[0], angle=angle, fill=False,
                                      color=ACCENT, lw=1, ls='--', label='95 % region (fit errors)'))
        pts.append(fit.drift)
        extent = float(np.max(np.abs(v)) + 2.4477 * w.max())
    else:
        extent = 0.0
    if pts:
        r = max(1e-6, float(np.max(np.abs(np.asarray(pts))) * 60 * 1.35), extent * 1.1)
        ax.set_xlim(-r, r)
        ax.set_ylim(-r, r)
    ax.set_aspect('equal', adjustable='box')
    ax.set_xlabel('Drift X (nm/min, piezo frame)')
    ax.set_ylabel('Drift Y (nm/min)')
    ax.set_title('Drift estimates', loc='left')
    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    if unique:
        ax.legend(unique.values(), unique.keys(), fontsize='x-small', loc='best', frameon=True, framealpha=.9,
                  edgecolor='none')
    # (h) per-scan RMS error: calibration only vs calibration + drift (in-sample, same equations)
    ax = axes[1]
    try:
        plain = [cc.replace_drift(s, np.zeros(2)) for s in scans]
        f0, eq0 = cc.calibrate(plain, ref, False, fallback)
        err0 = {}
        for e in eq0:
            err0.setdefault(e.scan, []).append(f0.predict(e) / e.theory_nm - 1)
        err1 = {}
        for e in equations:
            err1.setdefault(e.scan, []).append(fit.predict(e) / e.theory_nm - 1)
        n = np.arange(len(scans)) + 1
        r0 = [np.sqrt(np.mean(np.square(err0.get(i, [np.nan])))) * 100 for i in range(len(scans))]
        r1 = [np.sqrt(np.mean(np.square(err1.get(i, [np.nan])))) * 100 for i in range(len(scans))]
        ax.bar(n - .18, r0, .36, color=OLD, label=f'Calibration only (RMS {np.nanmean(r0):.3f} %)')
        ax.bar(n + .18, r1, .36, color=NEW, label=f'With drift (RMS {np.nanmean(r1):.3f} %)')
        top = np.nanmax(r0 + r1) if len(r0) else 1
        for k, s in enumerate(scans):
            ax.text(n[k], np.nanmax([r0[k], r1[k]]) + top * .02, s.slow_direction[:1].upper() or '?', ha='center',
                    va='bottom', fontsize='x-small', color='#333333')
        ax.set_ylim(0, top * 1.25)
        ax.set_xticks(n)
        ax.set_xlabel('Scan (U = up, D = down)')
        ax.set_ylabel('RMS length error (%)')
        ax.set_title('Residual error per scan', loc='left')
        ax.legend(fontsize='x-small', loc='best', frameon=True, framealpha=.9, edgecolor='none')
    except Exception as exc:
        ax.set_axis_off()
        ax.text(.5, .5, f'Comparison unavailable: {exc}', ha='center', va='center', transform=ax.transAxes,
                fontsize='x-small')
    # (i) summary
    ax = axes[2]
    ax.set_axis_off()
    lines = ['Drift treatment: ' + {'fitted': 'fitted (constant over the session)',
                                    'known': 'header values', 'none': 'none'}[fit.drift_mode]]
    if fit.drift_mode == 'fitted':
        sx, sy = np.sqrt(np.clip(np.diag(fit.drift_cov), 0, None)) * 60
        lines.append(f'v = ({fit.drift[0] * 60:+.3g} ± {sx:.2g}, {fit.drift[1] * 60:+.3g} ± {sy:.2g}) nm/min')
    if pairs:
        mean = np.mean([p['drift'] for p in pairs], axis=0) * 60
        lines.append(f'{len(pairs)} up/down pair(s): ({mean[0]:+.3g}, {mean[1]:+.3g}) nm/min')
        worst = max(p['relative_residual'] for p in pairs) * 100
        lines.append(f'unexplained by a constant drift: ≤ {worst:.2f} % of the cell')
    times = [s.extra.get('line_time') for s in scans if s.extra.get('line_time')]
    if times:
        frame = [lt[0] + lt[1] for lt in times]
        lines.append(f'line time {min(frame):.3g}–{max(frame):.3g} s (fwd + bwd)')
    lines.append('')
    lines.append('Model: u_true = C·V − v·(g·u)')
    lines.append('g = time gradient of the image (s/nm),')
    lines.append('v = drift velocity relative to the scanner.')
    ax.text(0, 1, '\n'.join(lines), va='top', ha='left', fontsize='small', transform=ax.transAxes)
