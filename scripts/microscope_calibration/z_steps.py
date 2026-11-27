"""Z (height) piezo calibration from monatomic steps — NumPy / SciPy / scikit-image, no Qt, no files.

Model
-----
A topography image recorded with the previous Z constant ``cz_old`` (m/V) shows a height
``z = cz_old · V_z``; the real height is ``cz_true · V_z``. A monatomic step of known height h₀
(Au(111): a/√3 = 2.355 Å) that appears as h_meas therefore gives

    cz_true = cz_old · n · h₀ / h_meas            (n = 1 for a monatomic step)

Every step profile of every scan gives one estimate; they are combined by a weighted mean
(errors from each profile fit, scaled by the observed scatter), with a bootstrap over step
edges and a leave-one-scan-out test, exactly like the X/Y calibration.

Measurement of one step
-----------------------
1. **Terraces.** Step edges are the pixels with a large height gradient (threshold from the
   expected step height and from the noise). The terraces are the regions between them.
2. **Terrace leveling.** One plane (common slope) plus one offset per terrace is fitted to the
   terrace pixels, then the offset of every scan line is removed from the terrace pixels only
   (line jumps), and the fit is repeated. Unlike a plain plane or a row alignment, this does not
   bend or erase steps (a row alignment removes steps that run along the fast axis).
3. **Profiles** are taken perpendicular to the step edge (averaged over a few parallel lines),
   long enough to see both terraces but never crossing another step.
4. **Fit** of each profile: ``z(s) = a + b·(s − s₀) + h·H(s − s₀)`` on the two terraces, the
   transition region being left out. ``h`` is the step height and ``b`` the terrace slope.

Drift and creep
---------------
Inside a frame, time grows linearly with the position (fast and slow axes), so a constant Z
drift (thermal drift, creep of the Z piezo) adds a plane ``v_z · t(x, y)``. It is absorbed by the
terrace slope ``b`` of every profile and by the plane of the terrace leveling, so it does not bias
the step heights. Up/down pairs measure it: the tilt of the sample is the same in both frames
while the drift term changes sign with the slow-scan direction, so
``v_z = (slope_up − slope_down) / (g_up − g_down)`` along the slow axis (g = time gradient).
Lateral (X/Y) drift and calibration do not change heights; when the X/Y calibration was fitted
in the same run, the distance axis of the profiles is corrected with it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

PALETTE = ('#ff3b6b', '#36d27a', '#4f8dff', '#ffa630', '#c065ff', '#2fd8e6', '#ff5fd2', '#c6f04a',
           '#ffb3c6', '#3fb5a6', '#b9a3ff', '#c98a3c')


class NoStepsFound(ValueError):
    """No usable monatomic step in the scans (the message says what was found)."""


# --------------------------------------------------------------------------- data classes
@dataclass
class StepProfile:
    index: int                    # number drawn on the figure (1-based within its scan)
    center_px: tuple              # (col, row) of the edge point in the analysed image
    p0_px: tuple                  # profile start (col, row)
    p1_px: tuple                  # profile end (col, row)
    distance_nm: np.ndarray       # along the profile, previous lateral calibration
    height_m: np.ndarray          # terrace-leveled heights sampled on the profile
    s0_nm: float
    h_m: float                    # step height (upper − lower terrace), previous Z calibration
    sigma_m: float
    slope_m_per_nm: float
    offset_m: float
    rms_m: float
    exclusion_nm: tuple           # (left, right) of the transition region left out of the fit
    direction_deg: float          # uphill normal of the edge, image frame (+x fast axis, +y up), 0–360°
    segment: int = 0              # step edge it belongs to (bootstrap unit)
    manual: bool = False
    method: str = 'profile'       # 'terrace patch' (2-D, default) or 'profile' (1-D fit only)
    model_m: np.ndarray | None = None   # fitted model along the profile (for the plot)
    h_profile_m: float = 0.0      # 1-D profile fit, for comparison
    n_layers: int = 0             # 1 = monatomic; 0 = not used
    used: bool = False
    reason: str = ''


@dataclass
class ZScan:
    """Steps measured on one scan / trace, with its acquisition context (duck-types ScanLattice)."""
    name: str
    path: str
    trace: str
    angle_deg: float
    cz_old: float | None
    size_nm: tuple
    shape: tuple
    slow_direction: str
    is_current: bool
    profiles: list
    leveled: np.ndarray
    display: np.ndarray
    terrace_labels: np.ndarray
    slopes_m_per_nm: tuple        # plane of the terrace leveling (x, y up)
    terrace_offsets_m: dict
    time_gradient: np.ndarray | None = None
    extra: dict = field(default_factory=dict)
    relative: bool = False

    @property
    def fast_axis(self) -> str:
        a = (self.angle_deg % 180 + 180) % 180
        if min(a, 180 - a) < 1:
            return 'X'
        if abs(a - 90) < 1:
            return 'Y'
        return f'{self.angle_deg:g}°'

    @property
    def used(self):
        return [p for p in self.profiles if p.used]


# --------------------------------------------------------------------------- image helpers
def _coords(shape, dx, dy):
    ny, nx = shape
    x = np.arange(nx) * dx
    y = (ny - 1 - np.arange(ny)) * dy              # image frame, +y up (row 0 at the top)
    return np.meshgrid(x, y)


def robust_plane(z, dx, dy, mask=None):
    """Plane fitted with two passes of outlier rejection. Returns (leveled, (a, bx, by))."""
    z = np.asarray(z, float)
    X, Y = _coords(z.shape, dx, dy)
    ok = np.isfinite(z) if mask is None else (np.isfinite(z) & mask)
    coef = np.array([np.nanmedian(z), 0., 0.])
    for _ in range(3):
        A = np.column_stack([np.ones(ok.sum()), X[ok], Y[ok]])
        coef, *_ = np.linalg.lstsq(A, z[ok], rcond=None)
        r = z - (coef[0] + coef[1] * X + coef[2] * Y)
        mad = np.nanmedian(np.abs(r[ok] - np.nanmedian(r[ok]))) * 1.4826 + 1e-30
        ok = ok & (np.abs(r) < 3 * mad + np.nanmedian(r[ok]))
        if ok.sum() < 16:
            break
    return z - (coef[0] + coef[1] * X + coef[2] * Y), tuple(float(c) for c in coef)


def gradient(z, dx, dy, sigma_px=1.0):
    """Smoothed gradient (m per nm) in the image frame (+x right, +y up)."""
    from scipy import ndimage
    z = np.asarray(z, float)
    filled = np.where(np.isfinite(z), z, np.nanmedian(z))
    gx = ndimage.gaussian_filter(filled, sigma_px, order=(0, 1)) / dx
    gy = -ndimage.gaussian_filter(filled, sigma_px, order=(1, 0)) / dy
    return gx, gy


def edge_map(z, dx, dy, h_expected_m, sigma_px=1.0):
    """Boolean map of step edges, gradient (gx, gy) and the threshold used.

    A step of height h smoothed by the Gaussian derivative (σ) and by the tip (≈ 0.5 nm) has a
    maximum slope ≈ h / (√(2π)·√(σ² + 0.5²)). The threshold is 35 % of that, and at least 8
    robust standard deviations of the terrace gradient (noise, atomic or herringbone
    corrugation), so a corrugation never makes a "step".
    """
    from skimage.filters import apply_hysteresis_threshold
    gx, gy = gradient(z, dx, dy, sigma_px)
    g = np.hypot(gx, gy)
    med = float(np.median(g))
    mad = float(np.median(np.abs(g - med))) * 1.4826
    sigma_nm = sigma_px * min(dx, dy)
    step_slope = abs(h_expected_m) / (math.sqrt(2 * math.pi) * math.sqrt(sigma_nm ** 2 + .5 ** 2))
    high = max(med + 8 * mad, .35 * step_slope)
    edges = apply_hysteresis_threshold(g, .55 * high, high)
    return edges, gx, gy, high


def terraces(edges, min_area_px=None):
    """Labels of the terraces between the edges (0 = edge or too small)."""
    from scipy import ndimage
    ny, nx = edges.shape
    grown = ndimage.binary_dilation(edges, iterations=2)
    labels, n = ndimage.label(~grown)
    if n == 0:
        return labels
    min_area = min_area_px or max(64, int(.004 * nx * ny))
    areas = ndimage.sum(np.ones_like(labels), labels, index=np.arange(1, n + 1))
    keep = np.zeros(n + 1, bool)
    keep[1:] = areas >= min_area
    labels = np.where(keep[labels], labels, 0)
    # renumber 1..k
    uniq = np.unique(labels[labels > 0])
    remap = np.zeros(n + 1, int)
    remap[uniq] = np.arange(1, len(uniq) + 1)
    return remap[labels]


def terrace_level(z, labels, dx, dy, align_rows=True, iterations=3):
    """One common plane + one offset per terrace (+ line offsets), fitted on the terrace pixels.

    Returns (leveled image, slopes (bx, by) in m/nm, {terrace: offset m}, row offsets m).
    The terrace offsets are kept in the leveled image (that is the topography); only the plane
    and the line offsets are removed.
    """
    z = np.asarray(z, float)
    X, Y = _coords(z.shape, dx, dy)
    ok = (labels > 0) & np.isfinite(z)
    ny = z.shape[0]
    row_off = np.zeros(ny)
    work = z.copy()
    bx = by = 0.0
    offsets = {}
    if ok.sum() < 16:
        lev, (c0, bx, by) = robust_plane(z, dx, dy)
        return lev, (bx, by), {}, row_off
    for _ in range(max(1, iterations)):
        zz = work - row_off[:, None]
        lab = labels[ok]
        # within-terrace (pooled) regression: centred coordinates per terrace
        n_lab = int(labels.max()) + 1
        counts = np.bincount(lab, minlength=n_lab).astype(float)
        counts[counts == 0] = 1
        mx = np.bincount(lab, X[ok], n_lab) / counts
        my = np.bincount(lab, Y[ok], n_lab) / counts
        mz = np.bincount(lab, zz[ok], n_lab) / counts
        xc, yc, zc = X[ok] - mx[lab], Y[ok] - my[lab], zz[ok] - mz[lab]
        A = np.column_stack([xc, yc])
        # robust: drop the worst residuals (adsorbates, defects) once
        coef, *_ = np.linalg.lstsq(A, zc, rcond=None)
        r = zc - A @ coef
        mad = np.median(np.abs(r)) * 1.4826 + 1e-30
        good = np.abs(r) < 4 * mad
        if good.sum() > 16:
            coef, *_ = np.linalg.lstsq(A[good], zc[good], rcond=None)
        bx, by = float(coef[0]), float(coef[1])
        plane = bx * X + by * Y
        model_off = mz - bx * mx - by * my                    # offset of every terrace
        if align_rows:
            resid = np.where(ok, zz - plane - model_off[labels], np.nan)
            with np.errstate(all='ignore'):
                delta = np.nanmedian(resid, axis=1)
            delta = np.where(np.isfinite(delta), delta, 0.0)
            row_off = row_off + delta - np.median(delta)
        offsets = {int(k): float(model_off[k]) for k in range(1, n_lab) if np.any(lab == k)}
    leveled = z - row_off[:, None] - bx * X - by * Y
    return leveled, (bx, by), offsets, row_off


# --------------------------------------------------------------------------- profiles
def _to_px(x_nm, y_nm, shape, dx, dy):
    ny = shape[0]
    return x_nm / dx, (ny - 1) - y_nm / dy


def _to_nm(col, row, shape, dx, dy):
    ny = shape[0]
    return col * dx, ((ny - 1) - row) * dy


def sample_profile(z, p0_nm, p1_nm, dx, dy, band_px=2, step_nm=None):
    """Heights along p0 → p1 (nm, image frame), averaged over 2·band+1 parallel lines."""
    from scipy import ndimage
    p0, p1 = np.asarray(p0_nm, float), np.asarray(p1_nm, float)
    length = float(np.linalg.norm(p1 - p0))
    step = step_nm or min(dx, dy)
    n = max(4, int(length / step) + 1)
    t = np.linspace(0, 1, n)
    u = (p1 - p0) / max(length, 1e-12)
    perp = np.array([-u[1], u[0]])
    filled = np.where(np.isfinite(z), z, np.nanmedian(z))
    lines = []
    for k in range(-band_px, band_px + 1):
        pts = p0[None, :] + t[:, None] * (p1 - p0)[None, :] + k * min(dx, dy) * perp[None, :]
        col, row = _to_px(pts[:, 0], pts[:, 1], z.shape, dx, dy)
        lines.append(ndimage.map_coordinates(filled, [row, col], order=1, mode='nearest'))
    return t * length, np.mean(lines, axis=0)


def fit_step(s, z, s0=None, min_side=4):
    """Two terraces with a common slope and a height jump; the transition is left out.

    Returns a dict (h, sigma, slope, offset, rms, s0, exclusion) or None.
    """
    from scipy import ndimage
    s = np.asarray(s, float)
    z = np.asarray(z, float)
    if len(s) < 2 * min_side + 3:
        return None
    ds = float(np.median(np.diff(s)))
    dz = np.gradient(ndimage.gaussian_filter1d(z, 1.0), s)
    n = len(s)
    if s0 is None:
        lo, hi = int(n * .2), int(math.ceil(n * .8))
        k0 = lo + int(np.argmax(np.abs(dz[lo:hi])))
    else:
        k0 = int(np.argmin(np.abs(s - s0)))
    peak = abs(dz[k0])
    if peak <= 0:
        return None
    left = k0
    while left > 0 and abs(dz[left - 1]) > .25 * peak:
        left -= 1
    right = k0
    while right < n - 1 and abs(dz[right + 1]) > .25 * peak:
        right += 1
    margin = max(1, int(math.ceil(.15 / max(ds, 1e-9))))
    left, right = max(0, left - margin), min(n - 1, right + margin)
    s0v = float(s[k0])
    keep = np.ones(n, bool)
    keep[left:right + 1] = False
    lower, upper = keep & (s < s0v), keep & (s > s0v)
    if lower.sum() < min_side or upper.sum() < min_side:
        return None
    A = np.column_stack([np.ones(keep.sum()), s[keep] - s0v, (s[keep] > s0v).astype(float)])
    coef, *_ = np.linalg.lstsq(A, z[keep], rcond=None)
    resid = z[keep] - A @ coef
    dof = max(1, keep.sum() - 3)
    rms = float(math.sqrt(resid @ resid / dof))
    try:
        cov = np.linalg.inv(A.T @ A) * rms ** 2
        sigma = float(math.sqrt(max(cov[2, 2], 0)))
    except np.linalg.LinAlgError:
        return None
    return {'h': float(coef[2]), 'sigma': sigma, 'slope': float(coef[1]), 'offset': float(coef[0]),
            'rms': rms, 's0': s0v, 'exclusion': (float(s[left] - s0v), float(s[right] - s0v))}


def _segments(edges, min_px):
    from scipy import ndimage
    from skimage.morphology import skeletonize
    skel = skeletonize(edges)
    labels, n = ndimage.label(skel, structure=np.ones((3, 3)))
    out = []
    for k in range(1, n + 1):
        rr, cc = np.nonzero(labels == k)
        if len(rr) >= min_px:
            out.append((rr, cc))
    out.sort(key=lambda t: -len(t[0]))
    return out


def _candidate_points(rr, cc, spacing_px, max_points):
    """Points spread along a skeleton segment (its ends left out)."""
    pts = np.column_stack([cc, rr]).astype(float)
    centre = pts.mean(axis=0)
    u, s_, vt = np.linalg.svd(pts - centre, full_matrices=False)
    proj = (pts - centre) @ vt[0]
    order = np.argsort(proj)
    proj = proj[order]
    pts = pts[order]
    span = proj[-1] - proj[0]
    if span < 1:
        return [tuple(pts[len(pts) // 2])]
    count = int(max(1, min(max_points, math.floor(span * .8 / max(spacing_px, 1)) + 1)))
    targets = (np.linspace(proj[0] + .1 * span, proj[-1] - .1 * span, count) if count > 1
               else [proj[0] + .5 * span])
    return [tuple(pts[int(np.argmin(np.abs(proj - t)))]) for t in targets]


def measure_profile(leveled, edges, centre_px, normal, dx, dy, length_nm, band_px=2, manual=False,
                    endpoints_px=None):
    """One step profile centred on an edge point (or along a drawn line). Returns StepProfile or None."""
    shape = leveled.shape
    ny, nx = shape
    if endpoints_px is not None:
        (c0, r0), (c1, r1) = endpoints_px
        p0 = np.array(_to_nm(c0, r0, shape, dx, dy))
        p1 = np.array(_to_nm(c1, r1, shape, dx, dy))
        s, z = sample_profile(leveled, p0, p1, dx, dy, band_px)
        fit = fit_step(s, z)
        if fit is None:
            return None
        if fit['h'] < 0:          # drawn downhill: measure it uphill (upper − lower terrace)
            p0, p1 = p1, p0
            s, z = sample_profile(leveled, p0, p1, dx, dy, band_px)
            fit = fit_step(s, z)
            if fit is None:
                return None
        u = (p1 - p0) / max(np.linalg.norm(p1 - p0), 1e-12)
        c = p0 + u * fit['s0']
        centre = _to_px(c[0], c[1], shape, dx, dy)
    else:
        c = np.array(_to_nm(centre_px[0], centre_px[1], shape, dx, dy))
        u = np.asarray(normal, float) / max(np.linalg.norm(normal), 1e-12)
        half = length_nm / 2
        # stay inside the image
        for sign in (-1, 1):
            for _ in range(60):
                end = c + sign * half * u
                col, row = _to_px(end[0], end[1], shape, dx, dy)
                if 0 <= col <= nx - 1 and 0 <= row <= ny - 1:
                    break
                half *= .9
        left = right = half
        # never cross another step: shorten each side before the next edge
        step = min(dx, dy)
        n = int(2 * half / step) + 1
        t = np.linspace(-half, half, n)
        pts = c[None, :] + t[:, None] * u[None, :]
        col, row = _to_px(pts[:, 0], pts[:, 1], shape, dx, dy)
        ci = np.clip(np.rint(col).astype(int), 0, nx - 1)
        ri = np.clip(np.rint(row).astype(int), 0, ny - 1)
        on_edge = edges[ri, ci]
        core = .9 + 2 * step                    # the edge being measured (tip-broadened)
        k_centre = int(np.argmin(np.abs(t)))
        # the central edge run around the centre
        k = k_centre
        while k > 0 and on_edge[k - 1]:
            k -= 1
        lo_run = t[k]
        k = k_centre
        while k < n - 1 and on_edge[k + 1]:
            k += 1
        hi_run = t[k]
        margin = max(2 * step, .4)
        others_left = t[(t < min(lo_run, -core)) & on_edge]
        others_right = t[(t > max(hi_run, core)) & on_edge]
        if len(others_left):
            left = min(left, -others_left.max() - margin)
        if len(others_right):
            right = min(right, others_right.min() - margin)
        if min(left, right) < max(5 * step, 1.0):
            return None
        p0, p1 = c - left * u, c + right * u
        s, z = sample_profile(leveled, p0, p1, dx, dy, band_px)
        fit = fit_step(s, z, s0=left)
        if fit is None or fit['h'] <= 0:
            return None
        centre = tuple(centre_px)
    c0, r0 = _to_px(p0[0], p0[1], shape, dx, dy)
    c1, r1 = _to_px(p1[0], p1[1], shape, dx, dy)
    direction = math.degrees(math.atan2(u[1], u[0])) % 360
    return StepProfile(0, (float(centre[0]), float(centre[1])), (float(c0), float(r0)), (float(c1), float(r1)),
                       np.asarray(s, float), np.asarray(z, float), fit['s0'], fit['h'], fit['sigma'], fit['slope'],
                       fit['offset'], fit['rms'], fit['exclusion'], direction, manual=manual)


def patch_height(leveled, labels, prof, dx, dy, radius_nm):
    """Step height from the two terraces around a profile, fitted in 2-D (v1.4).

    Pixels of the lower and upper terrace within ``radius_nm`` of the edge point:
    ``z = a + bx·x + by·y + h·[upper terrace]``. A 2-D patch averages the surface corrugation
    (Au(111) herringbone ≈ 0.2 Å, atomic rows) that a single line would pick up. Returns
    (h, σ, rms, model along the profile, (lower, upper)) or None.
    """
    shape = leveled.shape
    ny, nx = shape
    s = prof.distance_nm
    p0 = np.array(_to_nm(*prof.p0_px, shape, dx, dy))
    p1 = np.array(_to_nm(*prof.p1_px, shape, dx, dy))
    u = (p1 - p0) / max(np.linalg.norm(p1 - p0), 1e-12)
    pts = p0[None, :] + s[:, None] * u[None, :]
    col, row = _to_px(pts[:, 0], pts[:, 1], shape, dx, dy)
    lab = labels[np.clip(np.rint(row).astype(int), 0, ny - 1), np.clip(np.rint(col).astype(int), 0, nx - 1)]
    lo_side = lab[(s < prof.s0_nm + prof.exclusion_nm[0]) & (lab > 0)]
    hi_side = lab[(s > prof.s0_nm + prof.exclusion_nm[1]) & (lab > 0)]
    if not len(lo_side) or not len(hi_side):
        return None
    lower = int(np.bincount(lo_side).argmax())
    upper = int(np.bincount(hi_side).argmax())
    if lower == upper:
        return None
    X, Y = _coords(shape, dx, dy)
    c = p0 + u * prof.s0_nm
    near = (X - c[0]) ** 2 + (Y - c[1]) ** 2 <= radius_nm ** 2
    sel = near & ((labels == lower) | (labels == upper)) & np.isfinite(leveled)
    if (sel & (labels == lower)).sum() < 30 or (sel & (labels == upper)).sum() < 30:
        return None
    xs, ys, zs_ = X[sel] - c[0], Y[sel] - c[1], leveled[sel]
    hstep = (labels[sel] == upper).astype(float)
    A = np.column_stack([np.ones(len(zs_)), xs, ys, hstep])
    coef, *_ = np.linalg.lstsq(A, zs_, rcond=None)
    r = zs_ - A @ coef
    mad = np.median(np.abs(r)) * 1.4826 + 1e-30
    good = np.abs(r) < 4 * mad                    # adsorbates, defects, the rounded edge
    if good.sum() > 60:
        coef, *_ = np.linalg.lstsq(A[good], zs_[good], rcond=None)
        r = zs_[good] - A[good] @ coef
        A = A[good]
    dof = max(1, len(r) - 4)
    rms = float(math.sqrt(r @ r / dof))
    # neighbouring pixels are correlated (corrugation, tip): count independent samples per
    # (corrugation-size) area so σ is not over-optimistic
    n_eff = max(8.0, len(r) * (min(dx, dy) / 1.0) ** 2)
    try:
        cov = np.linalg.inv(A.T @ A) * rms ** 2 * (len(r) / n_eff)
    except np.linalg.LinAlgError:
        return None
    sigma = float(math.sqrt(max(cov[3, 3], 0)))
    rel = pts - c[None, :]
    model = coef[0] + coef[1] * rel[:, 0] + coef[2] * rel[:, 1] + coef[3] * (s > prof.s0_nm)
    return float(coef[3]), sigma, rms, model, (lower, upper)


def find_steps(z, dx, dy, h_expected_m, *, max_profiles=12, length_nm=0.0, band_px=2, manual_lines=(),
               align_rows=True):
    """Level the topography and measure step profiles.

    ``z`` in metres (previous calibration); ``dx``, ``dy`` pixel size in nm; ``manual_lines`` =
    [((c0, r0), (c1, r1))] drawn by the user (replace the automatic profiles).
    Returns dict(leveled, edges, labels, slopes, offsets, profiles, threshold).
    """
    z = np.asarray(z, float)
    if not np.isfinite(z).any():
        raise NoStepsFound('the image is empty')
    if not np.isfinite(z).all():
        z = np.where(np.isfinite(z), z, np.nanmedian(z))
    pre, _plane = robust_plane(z, dx, dy)
    edges, gx, gy, threshold = edge_map(pre, dx, dy, h_expected_m)
    labels = terraces(edges)
    leveled, slopes, offsets, row_off = terrace_level(z, labels, dx, dy, align_rows=align_rows)
    # the edges again on the leveled image (line jumps and tilt removed)
    edges, gx, gy, threshold = edge_map(leveled, dx, dy, h_expected_m)
    labels = terraces(edges)
    ny, nx = z.shape
    width_nm, height_nm = nx * dx, ny * dy
    auto_length = length_nm if length_nm and length_nm > 0 else \
        float(np.clip(max(40 * min(dx, dy), 8.0), 3.0, .45 * min(width_nm, height_nm)))
    profiles = []
    if manual_lines:
        for line in manual_lines:
            prof = measure_profile(leveled, edges, None, None, dx, dy, auto_length, band_px, manual=True,
                                   endpoints_px=line)
            if prof is not None:
                prof.segment = len(profiles)
                profiles.append(prof)
    else:
        min_seg_px = max(6, int(math.ceil(1.5 / min(dx, dy))))
        segments = _segments(edges, min_seg_px)
        spacing_px = max(8.0, .6 * auto_length / min(dx, dy))
        per_segment = []
        for k, (rr, cc) in enumerate(segments[:40]):
            per_segment.append([(k, p) for p in _candidate_points(rr, cc, spacing_px, max_profiles)])
        # round robin over the edges (longest first) so several steps are represented
        queue = []
        while any(per_segment):
            for lst in per_segment:
                if lst:
                    queue.append(lst.pop(0))
        for seg, (col, row) in queue:
            if len(profiles) >= max_profiles:
                break
            ci, ri = int(round(col)), int(round(row))
            normal = np.array([gx[ri, ci], gy[ri, ci]])
            if not np.any(normal):
                continue
            prof = measure_profile(leveled, edges, (col, row), normal, dx, dy, auto_length, band_px)
            if prof is None:
                continue
            prof.segment = seg
            profiles.append(prof)
    # ≈ 2 periods of the Au(111) herringbone corrugation (6.3 nm) or more; bounded by the image
    radius = float(min(max(1.2 * auto_length, 12.0, 25 * min(dx, dy)), .4 * min(width_nm, height_nm)))
    for prof in profiles:
        prof.h_profile_m = prof.h_m
        patch = patch_height(leveled, labels, prof, dx, dy, radius)
        if patch is not None and patch[0] > 0:
            prof.h_m, prof.sigma_m, prof.rms_m, prof.model_m, _pair = patch
            prof.method = 'terrace patch'
        else:
            prof.model_m = (prof.offset_m + prof.slope_m_per_nm * (prof.distance_nm - prof.s0_nm)
                            + prof.h_m * (prof.distance_nm > prof.s0_nm))
    for i, prof in enumerate(profiles, 1):
        prof.index = i
    return {'patch_radius_nm': radius, 'leveled': leveled, 'edges': edges, 'labels': labels, 'slopes': slopes, 'offsets': offsets,
            'row_offsets': row_off, 'profiles': profiles, 'threshold': threshold, 'profile_length_nm': auto_length}


def assign_layers(profiles, h0_m, tolerance=.25, allow_multiple=False):
    """Mark which profiles are monatomic (or n-atomic) steps; the others get a reason."""
    for p in profiles:
        h = abs(p.h_m)
        if h <= 3 * p.sigma_m:
            p.used, p.n_layers, p.reason = False, 0, 'height not significant (noise)'
            continue
        n = max(1, int(round(h / h0_m)))
        dev = abs(h / (n * h0_m) - 1)
        if n > 1 and not allow_multiple:
            p.used, p.n_layers = False, 0
            p.reason = f'{h * 1e10:.3f} Å ≈ {n} × step (multi-atomic step; enable “Also use double / triple steps”)'
            continue
        if n > 3 or dev > tolerance:
            p.used, p.n_layers = False, 0
            p.reason = (f'{h * 1e10:.3f} Å is not a monatomic step ({h0_m * 1e10:.3f} Å) within '
                        f'{tolerance * 100:.0f} %')
            continue
        if p.rms_m > .35 * h:
            p.used, p.n_layers, p.reason = False, 0, 'terraces too rough on this profile'
            continue
        p.used, p.n_layers, p.reason = True, n, ''
    return profiles


# --------------------------------------------------------------------------- calibration
@dataclass
class ZFit:
    cz: float                 # new Z calibration (m/V, or factor when relative)
    sigma: float              # formal error scaled by the Birge ratio
    chi2_red: float
    n_steps: int
    n_scans: int
    estimates: np.ndarray     # per-step estimates of cz
    sigmas: np.ndarray
    weights: np.ndarray


def step_estimates(zscans, h0_m, fallback_cz=None):
    """[(scan index, profile, estimate cz, σ)] for every used profile."""
    out = []
    for i, zs in enumerate(zscans):
        c_old = zs.cz_old or fallback_cz or 1.0
        for p in zs.used:
            k = p.n_layers * h0_m / abs(p.h_m)
            est = c_old * k
            sigma = est * max(p.sigma_m / abs(p.h_m), 1e-5)
            out.append((i, p, est, sigma))
    return out


def combine(estimates, scans_count=None):
    if not estimates:
        raise NoStepsFound('no usable step')
    est = np.array([e[2] for e in estimates], float)
    sig = np.array([e[3] for e in estimates], float)
    # each profile is not fully independent (several on one edge; tip shape): an extra 0.5 % floor
    sig = np.sqrt(sig ** 2 + (.005 * est) ** 2)
    w = 1 / sig ** 2
    mean = float(np.sum(w * est) / np.sum(w))
    dof = max(1, len(est) - 1)
    chi2 = float(np.sum(w * (est - mean) ** 2) / dof) if len(est) > 1 else 1.0
    sigma = float(math.sqrt(1 / np.sum(w)) * max(1.0, math.sqrt(chi2)))
    n_scans = len({e[0] for e in estimates}) if scans_count is None else scans_count
    return ZFit(mean, sigma, chi2, len(est), n_scans, est, sig, w)


def bootstrap(estimates, repeats=400, seed=11):
    """Resample whole step edges (all profiles of one edge together) with replacement."""
    if repeats <= 0:
        return np.empty(0)
    groups = {}
    for e in estimates:
        groups.setdefault((e[0], e[1].segment), []).append(e)
    keys = list(groups)
    if len(keys) < 3:
        return np.empty(0)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(int(repeats)):
        pick = rng.integers(0, len(keys), len(keys))
        sample = [e for j in pick for e in groups[keys[j]]]
        try:
            out.append(combine(sample).cz)
        except NoStepsFound:
            continue
    return np.asarray(out, float)


def leave_one_out(estimates, n_scans):
    """{scan index: cz fitted on the other scans} (≥ 2 scans with steps)."""
    out = {}
    scans = sorted({e[0] for e in estimates})
    if len(scans) < 2:
        return out
    for i in scans:
        others = [e for e in estimates if e[0] != i]
        if others:
            out[i] = combine(others).cz
    return out


def per_scan(estimates):
    out = {}
    for i in sorted({e[0] for e in estimates}):
        try:
            out[i] = combine([e for e in estimates if e[0] == i])
        except NoStepsFound:
            continue
    return out


def subsets(zscans, estimates, fit):
    """Calibration of subsets (fast axis, slow direction, trace) as % deviation from the global fit."""
    groups = {}
    for i, zs in enumerate(zscans):
        groups.setdefault(f'fast {zs.fast_axis}', set()).add(i)
        if zs.slow_direction:
            groups.setdefault(f'slow {zs.slow_direction}', set()).add(i)
        groups.setdefault(zs.trace, set()).add(i)
    used_scans = {e[0] for e in estimates}
    rows = []
    for name, members in groups.items():
        members = members & used_scans
        if not members or members == used_scans:
            continue
        sub = [e for e in estimates if e[0] in members]
        try:
            f = combine(sub)
        except NoStepsFound:
            continue
        rows.append((f'{name} ({len(members)})', (f.cz / fit.cz - 1) * 100, f.sigma / fit.cz * 100))
    return rows


def z_drift_pairs(zscans):
    """Z drift from up/down pairs (nm/s): the tilt is common, the drift term changes sign."""
    import calibration_core as cc
    out = []
    for i, j in cc.updown_pairs(zscans):
        up, down = (zscans[i], zscans[j]) if zscans[i].slow_direction == 'up' else (zscans[j], zscans[i])
        gu, gd = np.asarray(up.time_gradient, float), np.asarray(down.time_gradient, float)
        if abs(gu[1] - gd[1]) <= 0:
            continue
        # slopes in m/nm along +y (up) of the image; time gradient in s/nm
        vz = (up.slopes_m_per_nm[1] - down.slopes_m_per_nm[1]) / (gu[1] - gd[1])      # m/s
        tilt = (up.slopes_m_per_nm[1] + down.slopes_m_per_nm[1]) / 2 - vz * (gu[1] + gd[1]) / 2
        out.append({'up': up.name, 'down': down.name, 'vz_nm_per_s': float(vz * 1e9),
                    'tilt_y_mrad': float(math.atan(tilt * 1e9) * 1e3)})
    return out
