from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import map_coordinates

from spm_multiframe.models import CropRegion, GridDefinition


@dataclass(frozen=True)
class AffineCoordinateModel:
    matrix: np.ndarray  # shape (2, 3): [x,y] = matrix @ [col,row,1]
    rms_residual_nm: float


def fit_pixel_to_physical_affine(x_nm: np.ndarray, y_nm: np.ndarray) -> AffineCoordinateModel:
    """Fit the structured pixel-index -> physical-coordinate affine map.

    Linear drift plus raster timing yields an affine map for each trace in the MVP. The
    residual is checked so a future nonlinear timing/drift model falls back to scattered
    interpolation instead of being silently approximated as affine.
    """
    if x_nm.shape != y_nm.shape or x_nm.ndim != 2:
        raise ValueError("x_nm and y_nm must be matching 2-D arrays")
    ny, nx = x_nm.shape
    # The map is affine, so a sparse deterministic sample is sufficient and much faster.
    rows = np.unique(np.linspace(0, ny - 1, min(ny, 12), dtype=int))
    cols = np.unique(np.linspace(0, nx - 1, min(nx, 12), dtype=int))
    cc, rr = np.meshgrid(cols, rows)
    x = x_nm[rr, cc].ravel()
    y = y_nm[rr, cc].ravel()
    design = np.column_stack((cc.ravel(), rr.ravel(), np.ones(cc.size)))
    valid = np.isfinite(x) & np.isfinite(y)
    if np.count_nonzero(valid) < 3:
        raise ValueError("Not enough finite coordinate samples for affine fit")
    coef_x, *_ = np.linalg.lstsq(design[valid], x[valid], rcond=None)
    coef_y, *_ = np.linalg.lstsq(design[valid], y[valid], rcond=None)
    matrix = np.vstack((coef_x, coef_y))
    pred = design[valid] @ matrix.T
    residual = np.column_stack((x[valid], y[valid])) - pred
    rms = float(np.sqrt(np.mean(np.sum(residual**2, axis=1))))
    return AffineCoordinateModel(matrix=matrix, rms_residual_nm=rms)


def resample_to_grid(
    data: np.ndarray,
    x_nm: np.ndarray,
    y_nm: np.ndarray,
    grid: GridDefinition,
    *,
    order: int = 1,
    affine_tolerance_nm: float = 1e-5,
) -> np.ndarray:
    """Interpolate a physical scan onto a regular ``x-y`` grid.

    Uses an exact/near-exact affine inverse when valid, otherwise falls back to linear
    scattered interpolation.  No filtering is applied beyond the requested interpolation.
    """
    data = np.asarray(data, dtype=float)
    if data.shape != x_nm.shape or data.shape != y_nm.shape:
        raise ValueError("data and coordinate arrays must have identical shapes")
    xx, yy = np.meshgrid(grid.x_nm, grid.y_nm)
    try:
        model = fit_pixel_to_physical_affine(x_nm, y_nm)
    except (ValueError, np.linalg.LinAlgError):
        model = None

    if model is not None and model.rms_residual_nm <= affine_tolerance_nm:
        linear = model.matrix[:, :2]
        offset = model.matrix[:, 2]
        inv = np.linalg.inv(linear)
        target = np.stack((xx - offset[0], yy - offset[1]), axis=0).reshape(2, -1)
        col_row = inv @ target
        cols = col_row[0].reshape(grid.shape)
        rows = col_row[1].reshape(grid.shape)
        valid_data = np.isfinite(data)
        filled = np.where(valid_data, data, 0.0)
        sampled = map_coordinates(
            filled,
            [rows, cols],
            order=order,
            mode="constant",
            cval=np.nan,
            prefilter=(order > 1),
        )
        sampled_valid = map_coordinates(
            valid_data.astype(float),
            [rows, cols],
            order=0,
            mode="constant",
            cval=0.0,
            prefilter=False,
        )
        sampled[sampled_valid < 0.5] = np.nan
        return sampled

    valid = np.isfinite(data) & np.isfinite(x_nm) & np.isfinite(y_nm)
    points = np.column_stack((x_nm[valid], y_nm[valid]))
    if len(points) < 3:
        return np.full(grid.shape, np.nan, dtype=float)
    method = "nearest" if order == 0 else "linear"
    return griddata(points, data[valid], (xx, yy), method=method, fill_value=np.nan)


def grid_for_crop(crop: CropRegion, pixel_size_nm: float) -> GridDefinition:
    if pixel_size_nm <= 0:
        raise ValueError("pixel_size_nm must be > 0")
    nx = max(2, int(np.floor(crop.width_nm / pixel_size_nm)) + 1)
    ny = max(2, int(np.floor(crop.height_nm / pixel_size_nm)) + 1)
    return GridDefinition(
        x_nm=np.linspace(crop.xmin_nm, crop.xmax_nm, nx, dtype=float),
        y_nm=np.linspace(crop.ymin_nm, crop.ymax_nm, ny, dtype=float),
    )
