from __future__ import annotations

import numpy as np


_TOPOGRAPHY_NAMES = {
    "z",
    "height",
    "topography",
    "z_control_signal",
    "z-control signal",
    "z control signal",
}


def is_topography_channel(name: str | None) -> bool:
    """Return True for channels that should be displayed as topography.

    This affects presentation only.  It never changes the quantitative arrays saved by
    the analysis/stacking pipelines.
    """
    if not name:
        return False
    text = name.strip().lower().replace(".", "_")
    return text in _TOPOGRAPHY_NAMES or text.startswith("z (")


def _least_squares_plane(image: np.ndarray) -> np.ndarray:
    """Remove a best-fit plane from a *display copy* of a 2-D image."""
    arr = np.asarray(image, dtype=float)
    valid = np.isfinite(arr)
    if np.count_nonzero(valid) < 3:
        return arr.copy()
    ny, nx = arr.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    x = (xx - 0.5 * (nx - 1)) / max(nx - 1, 1)
    y = (yy - 0.5 * (ny - 1)) / max(ny - 1, 1)
    design = np.column_stack((x[valid], y[valid], np.ones(np.count_nonzero(valid))))
    values = arr[valid]

    # Two deterministic reweighted passes suppress isolated spikes without importing the
    # scientific registration preprocessing into the plotting layer.
    keep = np.ones(values.size, dtype=bool)
    coeff = np.zeros(3, dtype=float)
    for _ in range(2):
        coeff, *_ = np.linalg.lstsq(design[keep], values[keep], rcond=None)
        residual = values - design @ coeff
        med = float(np.median(residual[keep]))
        mad = float(np.median(np.abs(residual[keep] - med)))
        if not np.isfinite(mad) or mad <= np.finfo(float).eps:
            break
        sigma = 1.4826 * mad
        keep = np.abs(residual - med) <= 4.5 * sigma
        if np.count_nonzero(keep) < 3:
            keep[:] = True
            break
    plane = coeff[0] * x + coeff[1] * y + coeff[2]
    return arr - plane


def robust_display_limits(
    image: np.ndarray,
    *,
    low_percentile: float = 1.0,
    high_percentile: float = 99.0,
) -> tuple[float | None, float | None]:
    """Return outlier-resistant display limits without altering the image data."""
    finite = np.asarray(image, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return None, None
    if finite.size < 16:
        lo = float(np.min(finite))
        hi = float(np.max(finite))
    else:
        lo, hi = np.percentile(finite, [low_percentile, high_percentile]).astype(float)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        centre = float(np.median(finite))
        spread = float(np.std(finite))
        if not np.isfinite(spread) or spread <= np.finfo(float).eps:
            spread = max(abs(centre) * 1e-12, 1e-15)
        lo, hi = centre - spread, centre + spread
    return float(lo), float(hi)


def prepare_display_image(
    image: np.ndarray,
    channel: str | None,
    *,
    level_topography: bool = True,
) -> tuple[np.ndarray, str | None, float | None, float | None, bool]:
    """Prepare presentation parameters for an SPM image.

    Returns ``(display_image, cmap, vmin, vmax, was_levelled)``.  For topography the
    function works on a plane-levelled copy and uses grayscale.  The caller's array is
    never modified and the numerical stack remains untouched.
    """
    arr = np.asarray(image, dtype=float)
    topo = is_topography_channel(channel)
    display = _least_squares_plane(arr) if (topo and level_topography) else arr
    vmin, vmax = robust_display_limits(display)
    return display, ("gray" if topo else None), vmin, vmax, bool(topo and level_topography)
