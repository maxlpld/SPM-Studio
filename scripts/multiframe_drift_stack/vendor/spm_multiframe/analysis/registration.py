from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import shift as ndi_shift
from scipy.optimize import least_squares
from skimage.registration import phase_cross_correlation

from spm_multiframe.geometry.overlap import intersection_bounds, make_grid_for_bounds
from spm_multiframe.models import GridDefinition
from spm_multiframe.stacking.resample import resample_to_grid


@dataclass(frozen=True)
class RegistrationResult:
    shift_nm: np.ndarray
    shift_pixels_rc: np.ndarray
    score: float
    mse: float
    grid: GridDefinition


def subtract_robust_plane(image: np.ndarray) -> np.ndarray:
    """Subtract a robust best-fit plane from a temporary analysis copy."""
    arr = np.asarray(image, dtype=float)
    ny, nx = arr.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    x = (xx - 0.5 * (nx - 1)) / max(nx, 1)
    y = (yy - 0.5 * (ny - 1)) / max(ny, 1)
    valid = np.isfinite(arr)
    if np.count_nonzero(valid) < 3:
        return arr.copy()
    design = np.column_stack((x[valid], y[valid], np.ones(np.count_nonzero(valid))))
    z = arr[valid]
    initial, *_ = np.linalg.lstsq(design, z, rcond=None)

    def residual(coeff: np.ndarray) -> np.ndarray:
        return design @ coeff - z

    fit = least_squares(residual, initial, loss="soft_l1", max_nfev=30)
    plane = fit.x[0] * x + fit.x[1] * y + fit.x[2]
    return arr - plane


def robust_normalize(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image, dtype=float).copy()
    valid = np.isfinite(arr)
    if not np.any(valid):
        return arr
    median = float(np.nanmedian(arr[valid]))
    mad = float(np.nanmedian(np.abs(arr[valid] - median)))
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale <= np.finfo(float).eps:
        scale = float(np.nanstd(arr[valid]))
    if not np.isfinite(scale) or scale <= np.finfo(float).eps:
        scale = 1.0
    arr[valid] = (arr[valid] - median) / scale
    return arr


def preprocess_registration_copy(image: np.ndarray, *, window: bool = False) -> np.ndarray:
    processed = robust_normalize(subtract_robust_plane(image))
    if window:
        ny, nx = processed.shape
        win = np.outer(np.hanning(ny), np.hanning(nx))
        processed = processed * win
    return processed


def _crop_finite_overlap(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    valid = np.isfinite(a) & np.isfinite(b)
    if np.count_nonzero(valid) < 64:
        return None
    rows, cols = np.where(valid)
    r0, r1 = rows.min(), rows.max() + 1
    c0, c1 = cols.min(), cols.max() + 1
    a_crop = a[r0:r1, c0:c1].copy()
    b_crop = b[r0:r1, c0:c1].copy()
    common = np.isfinite(a_crop) & np.isfinite(b_crop)
    # Zero is the robust-normalized median. Filling only registration copies avoids
    # introducing any synthetic values into quantitative output channels.
    a_crop[~common] = 0.0
    b_crop[~common] = 0.0
    return a_crop, b_crop


def normalized_correlation(a: np.ndarray, b: np.ndarray) -> float:
    valid = np.isfinite(a) & np.isfinite(b)
    if np.count_nonzero(valid) < 3:
        return float("nan")
    av = a[valid] - np.mean(a[valid])
    bv = b[valid] - np.mean(b[valid])
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom <= np.finfo(float).eps:
        return 0.0
    return float(np.dot(av, bv) / denom)


def register_physical_images(
    data_ref: np.ndarray,
    x_ref_nm: np.ndarray,
    y_ref_nm: np.ndarray,
    data_mov: np.ndarray,
    x_mov_nm: np.ndarray,
    y_mov_nm: np.ndarray,
    *,
    pixel_size_nm: float,
    max_pixels: int = 192,
    upsample_factor: int = 20,
    max_shift_nm: float | None = None,
) -> RegistrationResult | None:
    """Estimate the small rigid translation that moves ``moving`` onto ``reference``."""
    try:
        bounds = intersection_bounds([(x_ref_nm, y_ref_nm), (x_mov_nm, y_mov_nm)])
    except ValueError:
        return None
    grid = make_grid_for_bounds(bounds, pixel_size_nm, max_pixels=max_pixels)
    ref = resample_to_grid(data_ref, x_ref_nm, y_ref_nm, grid)
    mov = resample_to_grid(data_mov, x_mov_nm, y_mov_nm, grid)
    cropped = _crop_finite_overlap(ref, mov)
    if cropped is None:
        return None
    ref_crop, mov_crop = cropped
    shift_rc, error, _phase = phase_cross_correlation(
        ref_crop,
        mov_crop,
        upsample_factor=upsample_factor,
        normalization="phase",
        disambiguate=True,
    )
    shift_rc = np.asarray(shift_rc, dtype=float)
    shift_nm = np.asarray([shift_rc[1] * grid.dx_nm, shift_rc[0] * grid.dy_nm], dtype=float)
    if max_shift_nm is not None and np.linalg.norm(shift_nm) > max_shift_nm:
        return RegistrationResult(
            shift_nm=shift_nm,
            shift_pixels_rc=shift_rc,
            score=0.0,
            mse=float("inf"),
            grid=grid,
        )
    aligned = ndi_shift(mov_crop, shift_rc, order=1, mode="constant", cval=np.nan, prefilter=False)
    score = normalized_correlation(ref_crop, aligned)
    valid = np.isfinite(ref_crop) & np.isfinite(aligned)
    mse = float(np.mean((ref_crop[valid] - aligned[valid]) ** 2)) if np.any(valid) else float("inf")
    if not np.isfinite(score):
        score = 0.0
    return RegistrationResult(shift_nm, shift_rc, score, mse, grid)
