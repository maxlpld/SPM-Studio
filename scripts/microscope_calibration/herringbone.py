"""X/Y calibration from the Au(111) herringbone reconstruction — NumPy / SciPy, no Qt, no files.

Why it works
------------
The 22×√3 reconstruction of Au(111) shows pairs of corrugation lines every d = 22 × 2.884 Å
= 63.4 Å along [1-10] (measured 63 Å), and in the herringbone pattern the lines bend by 120°
every ≈ 250 Å (J. V. Barth, H. Brune, G. Ertl and R. J. Behm, Phys. Rev. B 42, 9307 (1990)).
An image of the herringbones therefore contains two families of parallel lines whose normals
make 120° (60° modulo 180°), each with the known spacing d — a calibration standard that is
visible at 50–300 nm without atomic resolution.

From line spacings to the lattice fit
-------------------------------------
Each family gives a peak k_i in the 2-D FFT (|k_i| = 1/d in reality). A linear distortion of the
image (calibration error, constant drift: u_true = M · u_image) changes a line family's wave
vector as k_true = M⁻ᵀ · k_image. The dual basis of the two wave vectors (a_i · k_j = δ_ij)
then transforms exactly like real lattice vectors, a_true = M · a_image, and in reality it is a
hexagonal cell with a = b = 2d/√3 = 73.2 Å and γ = 120°. The measured dual basis is therefore
given to the same least-squares fit as an atomic lattice: previous calibration and scan angle of
every file, thermal drift (header compensation, fitted session drift, up/down pairs),
bootstrap and leave-one-out tests — nothing of that model is changed.
"""
from __future__ import annotations

import math

import numpy as np


class HerringboneNotFound(ValueError):
    """No herringbone pair of line families was found (the message says why)."""


def equivalent_cell_nm(period_nm):
    """Side of the equivalent hexagonal cell (dual basis of two line families at 120°)."""
    return 2 * float(period_nm) / math.sqrt(3)


def _flatten(data, dx, dy, period_nm, step_height_m=None):
    """Remove the plane, the terraces / steps and the large-scale background; mask step edges."""
    from scipy import ndimage
    import z_steps as zs
    z = np.asarray(data, float)
    z = np.where(np.isfinite(z), z, np.nanmedian(z))
    lev, _ = zs.robust_plane(z, dx, dy)
    keep = np.ones(z.shape, bool)
    if step_height_m:
        # topography: put every terrace at the same height so the steps do not dominate the FFT
        try:
            edges, *_ = zs.edge_map(lev, dx, dy, step_height_m)
            labels = zs.terraces(edges)
            if labels.max() >= 1:
                lev, _sl, offsets, _rows = zs.terrace_level(z, labels, dx, dy)
                for k, off in offsets.items():
                    lev = np.where(labels == k, lev - off, lev)
                keep = labels > 0
        except Exception:
            pass
    # any remaining sharp feature (step, adsorbate, tip change): mask it
    gx, gy = zs.gradient(lev, dx, dy, 1.0)
    g = np.hypot(gx, gy)
    med = np.median(g[keep]) if keep.any() else np.median(g)
    mad = np.median(np.abs(g[keep] - med)) * 1.4826 if keep.any() else 0
    keep &= g < med + 10 * mad + 1e-30
    sigma_px = (period_nm / dx, period_nm / dy)
    grow = max(1, int(round(.35 * period_nm / min(dx, dy))))
    keep = ndimage.binary_erosion(keep, iterations=grow) if keep.sum() > keep.size * .3 else keep
    background = ndimage.gaussian_filter(np.where(keep, lev, np.median(lev[keep]) if keep.any() else 0), sigma_px)
    weight = ndimage.gaussian_filter(keep.astype(float), sigma_px)
    hp = lev - np.where(weight > 1e-3, background / np.maximum(weight, 1e-3), 0)
    hp = ndimage.gaussian_filter(hp, (period_nm / 14 / dx, period_nm / 14 / dy))
    return np.where(keep, hp, 0.0), keep


def flatten_terraces(data, dx, dy, step_height_m):
    """Topography with every terrace brought to the same height (plane, line offsets and terrace
    offsets removed), so that the 0.2 Å herringbone corrugation is visible next to 2.4 Å steps.
    Returns the image unchanged when no terrace is found."""
    import z_steps as zs
    z = np.asarray(data, float)
    z = np.where(np.isfinite(z), z, np.nanmedian(z))
    try:
        lev, _ = zs.robust_plane(z, dx, dy)
        edges, *_ = zs.edge_map(lev, dx, dy, step_height_m)
        labels = zs.terraces(edges)
        if labels.max() < 1:
            return lev
        lev, _sl, offsets, _rows = zs.terrace_level(z, labels, dx, dy)
        for k, off in offsets.items():
            lev = np.where(labels == k, lev - off, lev)
        edge = labels == 0
        if edge.any() and (~edge).any():
            lev = np.where(edge, np.median(lev[~edge]), lev)
        return lev
    except Exception:
        return z


def region_mask(shape, rois):
    """Mask of the drawn region(s): rectangles and closed lines (≥ 3 points, closed automatically)."""
    from matplotlib.path import Path as MplPath
    ny, nx = shape
    mask = np.zeros(shape, bool)
    cols, rows = np.meshgrid(np.arange(nx) + .0, np.arange(ny) + .0)
    pts = np.column_stack([cols.ravel(), rows.ravel()])
    used = []
    for roi in rois or ():
        kind = getattr(roi, 'kind', None)
        points = [tuple(map(float, p)) for p in getattr(roi, 'points_px', ())]
        if kind == 'rectangle' and len(points) == 2:
            (c0, r0), (c1, r1) = points
            c0, c1 = sorted((c0, c1))
            r0, r1 = sorted((r0, r1))
            mask |= (cols >= c0) & (cols <= c1) & (rows >= r0) & (rows <= r1)
            used.append([(c0, r0), (c1, r0), (c1, r1), (c0, r1)])
        elif kind == 'line' and len(points) >= 3:
            inside = MplPath(points + [points[0]]).contains_points(pts).reshape(shape)
            mask |= inside
            used.append(points)
    return mask, used


def _hann(n):
    return np.hanning(n) if n > 1 else np.ones(n)


def detect(data, dx, dy, period_nm, tolerance=.25, region=None, step_height_m=None, snr_min=50.0):
    """Find the two herringbone line families. Returns a dict with the wave vectors (nm⁻¹, image
    frame +x fast axis, +y up), their periods, powers, signal/noise and the dual basis.

    ``region`` = boolean mask of the area to use (drawn by the user); None = whole image.
    """
    from scipy import ndimage
    z = np.asarray(data, float)
    ny, nx = z.shape
    width, height = nx * dx, ny * dy
    if min(width, height) < 2.2 * period_nm:
        raise HerringboneNotFound(f'the image ({width:.0f} × {height:.0f} nm) is too small: it must show at least '
                                  f'≈ 3 herringbone periods ({3 * period_nm:.0f} nm)')
    if 3 * min(dx, dy) > period_nm:
        raise HerringboneNotFound(f'the pixels ({dx:.2f} nm) are too large to resolve the {period_nm:.1f} nm '
                                  'herringbone period (need ≥ 3 pixels per period)')
    flat, keep = _flatten(z, dx, dy, period_nm, step_height_m)
    window_mask = keep.copy()
    if region is not None:
        region = np.asarray(region, bool)
        if region.sum() < (2.5 * period_nm / dx) * (2.5 * period_nm / dy):
            raise HerringboneNotFound('the drawn region is too small (it must contain several herringbone periods)')
        window_mask &= region
        rr, cc = np.nonzero(region)
        r0, r1, c0, c1 = rr.min(), rr.max() + 1, cc.min(), cc.max() + 1
    else:
        r0, r1, c0, c1 = 0, ny, 0, nx
    crop = flat[r0:r1, c0:c1]
    m = window_mask[r0:r1, c0:c1].astype(float)
    m = ndimage.gaussian_filter(m, max(1.0, .25 * period_nm / min(dx, dy)))
    win = np.outer(_hann(crop.shape[0]), _hann(crop.shape[1])) * m
    if win.sum() <= 0:
        raise HerringboneNotFound('no flat terrace left to analyse')
    sig = (crop - np.sum(crop * win) / win.sum()) * win
    # zero padding ×2 for a finer frequency grid (the peak position is interpolated as well)
    py, px_ = 2 * crop.shape[0], 2 * crop.shape[1]
    F = np.fft.fftshift(np.fft.fft2(sig, s=(py, px_)))
    power = np.abs(F) ** 2
    kx = np.fft.fftshift(np.fft.fftfreq(px_, d=dx))
    ky = -np.fft.fftshift(np.fft.fftfreq(py, d=dy))          # rows run downwards → +y up
    KX, KY = np.meshgrid(kx, ky)
    radius = np.hypot(KX, KY)
    k0 = 1 / period_nm
    ring = (radius >= k0 * (1 - tolerance)) & (radius <= k0 * (1 + tolerance))
    half = ring & ((KY > 0) | ((KY == 0) & (KX > 0)))
    if half.sum() < 20:
        raise HerringboneNotFound('the image does not resolve the herringbone frequency')
    theta = np.degrees(np.arctan2(KY, KX)) % 180
    bins = np.arange(181)
    idx = np.clip(np.digitize(theta[half], bins) - 1, 0, 179)
    prof = np.zeros(180)
    np.maximum.at(prof, idx, power[half])
    # background: a broad ring just outside / inside the search band (noise floor)
    outer = ((radius > k0 * (1 + tolerance)) & (radius < k0 * (1 + 2 * tolerance))) | \
            ((radius < k0 * (1 - tolerance)) & (radius > k0 * (1 - 2 * tolerance)))
    # Noise floor: the median power of the search ring itself. For noise alone the power of a
    # pixel is exponentially distributed, so the highest of ~10⁴ ring pixels is ≈ 10–15 × the
    # median; a herringbone peak is thousands of times above it. S/N ≥ 50 is required.
    floor = max(float(np.median(power[half])), float(np.median(power[outer])) if outer.any() else 0.0, 1e-300)
    smooth = ndimage.gaussian_filter1d(prof, 1.2, mode='wrap')
    peaks = []
    for a in range(180):
        v = smooth[a]
        if v >= smooth[(a - 1) % 180] and v >= smooth[(a + 1) % 180] and v > 0:
            peaks.append((v, a))
    peaks.sort(reverse=True)
    chosen = []
    for v, a in peaks:
        if all(min(abs(a - b), 180 - abs(a - b)) >= 15 for _v, b in chosen):
            chosen.append((v, a))
        if len(chosen) >= 6:
            break
    found = []
    for v, a in chosen:
        sector = half & (np.minimum(np.abs(theta - a), 180 - np.abs(theta - a)) <= 4)
        if not sector.any():
            continue
        flat_idx = np.argmax(np.where(sector, power, -1))
        r, c = np.unravel_index(flat_idx, power.shape)
        if not (0 < r < py - 1 and 0 < c < px_ - 1):
            continue
        # Gaussian (log-parabola) interpolation of the highest pixel (coarse value; refined below)
        def interp(m1, m0, p1):
            l1, l0, l2 = (math.log(max(x, 1e-300)) for x in (m1, m0, p1))
            den = l1 - 2 * l0 + l2
            return 0.0 if den >= 0 else .5 * (l1 - l2) / den
        kxv = kx[c] + interp(power[r, c - 1], power[r, c], power[r, c + 1]) * (kx[1] - kx[0])
        kyv = ky[r] + interp(power[r - 1, c], power[r, c], power[r + 1, c]) * (ky[1] - ky[0])
        snr = float(power[r, c] / max(floor, 1e-300))
        found.append({'k': np.array([kxv, kyv]), 'angle_deg': math.degrees(math.atan2(kyv, kxv)) % 180,
                      'period_nm': 1 / math.hypot(kxv, kyv), 'power': float(power[r, c]), 'snr': snr})
    strong = [f for f in found if f['snr'] >= snr_min]
    best = None
    for i in range(len(strong)):
        for j in range(i + 1, len(strong)):
            sep = abs(strong[i]['angle_deg'] - strong[j]['angle_deg']) % 180
            sep = min(sep, 180 - sep)
            if abs(sep - 60) <= 22:
                score = min(strong[i]['power'], strong[j]['power'])
                if best is None or score > best[0]:
                    best = (score, strong[i], strong[j], sep)
    if best is None:
        listed = ', '.join(f"{f['period_nm']:.2f} nm at {f['angle_deg']:.0f}° (S/N {f['snr']:.0f})" for f in found[:4])
        raise HerringboneNotFound('no pair of herringbone line families (two periods ≈ '
                                  f'{period_nm:.2f} nm at 60°/120°) was found'
                                  + (f'; strongest peaks: {listed}' if listed else ''))
    _s, f1, f2, sep = best
    refined = refine_local(flat, keep if region is None else (keep & region), dx, dy, period_nm,
                           [f1['k'], f2['k']])
    method = 'FFT peak'
    if refined is not None:
        for f, k in zip((f1, f2), refined['k']):
            f['k_fft'] = f['k']
            f['k'] = k
            f['period_nm'] = 1 / math.hypot(*k)
            f['angle_deg'] = math.degrees(math.atan2(k[1], k[0])) % 180
        method = 'local wave vector inside each arm (median), FFT for the directions'
        sep = abs(f1['angle_deg'] - f2['angle_deg']) % 180
        sep = min(sep, 180 - sep)
    k1, k2 = f1['k'].copy(), f2['k'].copy()
    if k1 @ k2 > 0:          # choose the pair at 120° (the dual cell is then at 120° as well)
        k2 = -k2
    K = np.column_stack([k1, k2])
    dual = np.linalg.inv(K).T                     # a_i · k_j = δ_ij
    third = [f for f in strong if f is not f1 and f is not f2 and
             all(min(abs(f['angle_deg'] - g['angle_deg']) % 180, 180 - abs(f['angle_deg'] - g['angle_deg']) % 180) > 40
                 for g in (f1, f2))]
    return {'k_nm_inv': [k1, k2], 'periods_nm': [f1['period_nm'], f2['period_nm']],
            'angles_deg': [f1['angle_deg'], f2['angle_deg']], 'separation_deg': float(sep),
            'snr': [f1['snr'], f2['snr']], 'dual_basis_nm': dual, 'third_family': third[0] if third else None,
            'peaks': found, 'analysed_fraction': float(window_mask[r0:r1, c0:c1].mean()),
            'region_box_px': (int(c0), int(r0), int(c1), int(r1)), 'method': method,
            'arm_pixels': None if refined is None else refined['pixels']}


def refine_local(flat, usable, dx, dy, period_nm, k_coarse, ang_sigma=25.0, rad_sigma=.35):
    """Line spacing of each herringbone arm from its local wave vector, measured inside the arms.

    The FFT peak of a herringbone arm is not exactly at 1/d: an arm is only ≈ 12 nm wide between
    two elbows, and the two arms leak into each other's peak (on synthetic herringbones with a
    25 nm zigzag, the FFT peak gives periods ≈ 3 % too long). Here each arm is isolated by an
    analytic (one-sided) band-pass around its FFT direction; its local wave vector
    k(r) = ∇phase / 2π is computed with exact spectral derivatives, and the median is taken over
    the pixels well inside the domains of that arm (its amplitude ≥ 3 × the other arm's, eroded
    by half a period). On the same synthetic herringbones the bias is ≈ 0.7 % (25 nm zigzag) and
    ≈ 0.2 % (60 nm). Returns {'k': [k1, k2], 'pixels': [n1, n2]} or None.
    """
    from scipy import ndimage
    flat = np.asarray(flat, float)
    usable = np.asarray(usable, bool)
    ny, nx = flat.shape
    if usable.sum() < 400:
        return None
    soft = ndimage.gaussian_filter(usable.astype(float), max(1.0, .25 * period_nm / min(dx, dy)))
    F = np.fft.fft2(np.where(usable, flat - flat[usable].mean(), 0.0) * soft)
    kx = np.fft.fftfreq(nx, d=dx)
    ky = -np.fft.fftfreq(ny, d=dy)
    KX, KY = np.meshgrid(kx, ky)
    R = np.hypot(KX, KY)
    k0 = 1 / period_nm
    th = np.degrees(np.arctan2(KY, KX))
    fields = []
    for k in k_coarse:
        a = math.degrees(math.atan2(k[1], k[0]))
        dth = (th - a + 180) % 360 - 180
        H = np.exp(-.5 * (dth / ang_sigma) ** 2) * np.exp(-.5 * (np.log(np.maximum(R, 1e-12) / k0) / rad_sigma) ** 2)
        G = F * H
        fields.append((np.fft.ifft2(G), np.fft.ifft2(G * 2j * np.pi * KX), np.fft.ifft2(G * 2j * np.pi * KY), a))
    border = np.zeros((ny, nx), bool)
    b = max(2, int(.06 * min(nx, ny)))
    border[b:-b, b:-b] = True
    out, counts = [], []
    for i, (q, qx, qy, a) in enumerate(fields):
        other = np.abs(fields[1 - i][0])
        amp = np.abs(q)
        for ratio, erode in ((4.0, 0.6), (3.0, 0.5), (2.0, 0.25)):
            dom = usable & border & (amp > ratio * other)
            dom = ndimage.binary_erosion(dom, iterations=max(1, int(erode * period_nm / min(dx, dy))))
            if not dom.any():
                continue
            sel = dom & (amp > np.percentile(amp[usable], 40))
            if sel.sum() >= 50:
                break
        else:
            return None
        den = amp ** 2 + 1e-300
        kxl = np.imag(np.conj(q) * qx)[sel] / den[sel] / (2 * np.pi)
        kyl = np.imag(np.conj(q) * qy)[sel] / den[sel] / (2 * np.pi)
        u = np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
        v = np.array([-u[1], u[0]])
        kr = np.median(kxl * u[0] + kyl * u[1])
        kt = np.median(kxl * v[0] + kyl * v[1])
        vec = kr * u + kt * v
        if not np.all(np.isfinite(vec)) or abs(np.hypot(*vec) / k0 - 1) > .6:
            return None
        if vec @ np.asarray(k_coarse[i], float) < 0:
            vec = -vec
        out.append(vec)
        counts.append(int(sel.sum()))
    return {'k': out, 'pixels': counts}


def period_vectors(k_list):
    """Real-space spacing vector of each line family: k / |k|² (nm, normal to the lines)."""
    return np.column_stack([np.asarray(k, float) / float(np.asarray(k) @ np.asarray(k)) for k in k_list])


def corrected_wavevectors(k_list, matrix):
    """k_true = M⁻ᵀ k_image for an image-frame correction matrix M (u_true = M u_image)."""
    inv_t = np.linalg.inv(np.asarray(matrix, float)).T
    return [inv_t @ np.asarray(k, float) for k in k_list]
