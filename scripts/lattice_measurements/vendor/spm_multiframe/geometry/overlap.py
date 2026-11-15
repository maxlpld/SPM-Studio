from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import griddata
from scipy.spatial import ConvexHull
from matplotlib.path import Path as MplPath

from spm_multiframe.models import CropRegion, GridDefinition


@dataclass(frozen=True)
class MaskGridResult:
    grid: GridDefinition
    masks: list[np.ndarray]


def union_bounds(coordinates: list[tuple[np.ndarray, np.ndarray]]) -> tuple[float, float, float, float]:
    xmin = min(float(np.nanmin(x)) for x, _ in coordinates)
    xmax = max(float(np.nanmax(x)) for x, _ in coordinates)
    ymin = min(float(np.nanmin(y)) for _, y in coordinates)
    ymax = max(float(np.nanmax(y)) for _, y in coordinates)
    return xmin, xmax, ymin, ymax


def intersection_bounds(coordinates: list[tuple[np.ndarray, np.ndarray]]) -> tuple[float, float, float, float]:
    xmin = max(float(np.nanmin(x)) for x, _ in coordinates)
    xmax = min(float(np.nanmax(x)) for x, _ in coordinates)
    ymin = max(float(np.nanmin(y)) for _, y in coordinates)
    ymax = min(float(np.nanmax(y)) for _, y in coordinates)
    if xmin >= xmax or ymin >= ymax:
        raise ValueError("Corrected scans have no axis-aligned bounding-box overlap")
    return xmin, xmax, ymin, ymax


def make_grid_for_bounds(
    bounds: tuple[float, float, float, float],
    pixel_size_nm: float,
    *,
    max_pixels: int | None = None,
) -> GridDefinition:
    xmin, xmax, ymin, ymax = bounds
    if pixel_size_nm <= 0:
        raise ValueError("pixel_size_nm must be > 0")
    nx = max(2, int(np.floor((xmax - xmin) / pixel_size_nm)) + 1)
    ny = max(2, int(np.floor((ymax - ymin) / pixel_size_nm)) + 1)
    if max_pixels is not None and max(nx, ny) > max_pixels:
        scale = max(nx, ny) / max_pixels
        pixel_size_nm *= scale
        nx = max(2, int(np.floor((xmax - xmin) / pixel_size_nm)) + 1)
        ny = max(2, int(np.floor((ymax - ymin) / pixel_size_nm)) + 1)
    return GridDefinition(
        x_nm=np.linspace(xmin, xmax, nx, dtype=float),
        y_nm=np.linspace(ymin, ymax, ny, dtype=float),
    )


def coordinate_validity_mask(
    x_nm: np.ndarray,
    y_nm: np.ndarray,
    valid_source: np.ndarray,
    grid: GridDefinition,
) -> np.ndarray:
    """Rasterize a scan's physically valid support onto a regular physical grid."""
    source_valid = np.isfinite(x_nm) & np.isfinite(y_nm) & np.asarray(valid_source, dtype=bool)
    points = np.column_stack((x_nm[source_valid], y_nm[source_valid]))
    if len(points) < 3:
        return np.zeros(grid.shape, dtype=bool)

    # A convex-hull support is reliable for the small affine/shear distortions permitted by
    # the quantitative drift model. Internal invalid pixels are then removed by a sampled
    # nearest-validity field rather than silently treated as data.
    hull = ConvexHull(points)
    polygon = points[hull.vertices]
    xx, yy = np.meshgrid(grid.x_nm, grid.y_nm)
    target = np.column_stack((xx.ravel(), yy.ravel()))
    in_hull = MplPath(polygon).contains_points(target, radius=1e-12).reshape(grid.shape)

    all_finite_xy = np.isfinite(x_nm) & np.isfinite(y_nm)
    source_points = np.column_stack((x_nm[all_finite_xy], y_nm[all_finite_xy]))
    source_values = np.asarray(valid_source, dtype=float)[all_finite_xy]
    if len(source_points) >= 3:
        sampled = griddata(source_points, source_values, (xx, yy), method="nearest")
        in_hull &= np.asarray(sampled >= 0.5)
    return in_hull


def build_common_masks(
    coordinate_sets: list[tuple[np.ndarray, np.ndarray]],
    valid_sources: list[np.ndarray],
    pixel_size_nm: float,
    *,
    max_pixels: int = 512,
) -> MaskGridResult:
    if len(coordinate_sets) != len(valid_sources):
        raise ValueError("coordinate_sets and valid_sources must have the same length")
    bounds = union_bounds(coordinate_sets)
    grid = make_grid_for_bounds(bounds, pixel_size_nm, max_pixels=max_pixels)
    masks = [
        coordinate_validity_mask(x, y, valid, grid)
        for (x, y), valid in zip(coordinate_sets, valid_sources, strict=True)
    ]
    return MaskGridResult(grid=grid, masks=masks)


def common_mask(masks: list[np.ndarray], included: list[bool] | None = None) -> np.ndarray:
    if not masks:
        raise ValueError("At least one validity mask is required")
    if included is None:
        selected = masks
    else:
        selected = [mask for mask, keep in zip(masks, included, strict=True) if keep]
    if not selected:
        return np.zeros_like(masks[0], dtype=bool)
    result = np.ones_like(selected[0], dtype=bool)
    for mask in selected:
        result &= mask
    return result


def largest_rectangle(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Return ``(row0,row1,col0,col1)`` for the largest all-True rectangle."""
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2:
        raise ValueError("mask must be 2-D")
    rows, cols = binary.shape
    heights = np.zeros(cols, dtype=int)
    best_area = 0
    best: tuple[int, int, int, int] | None = None

    for row in range(rows):
        heights = np.where(binary[row], heights + 1, 0)
        stack: list[int] = []
        for col in range(cols + 1):
            current = heights[col] if col < cols else 0
            while stack and heights[stack[-1]] > current:
                height = heights[stack.pop()]
                left = stack[-1] + 1 if stack else 0
                width = col - left
                area = int(height * width)
                if area > best_area:
                    best_area = area
                    best = (row - height + 1, row + 1, left, col)
            stack.append(col)
    return best


def largest_square(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2:
        raise ValueError("mask must be 2-D")
    rows, cols = binary.shape
    dp = np.zeros((rows + 1, cols + 1), dtype=int)
    best_size = 0
    best_end = (0, 0)
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            if binary[i - 1, j - 1]:
                dp[i, j] = 1 + min(dp[i - 1, j], dp[i, j - 1], dp[i - 1, j - 1])
                if dp[i, j] > best_size:
                    best_size = int(dp[i, j])
                    best_end = (i, j)
    if best_size == 0:
        return None
    i, j = best_end
    return (i - best_size, i, j - best_size, j)


def indices_to_crop(region: tuple[int, int, int, int], grid: GridDefinition) -> CropRegion:
    row0, row1, col0, col1 = region
    dx = grid.dx_nm
    dy = grid.dy_nm
    # Cell boundaries rather than centres make crop sizes independent of preview raster DPI.
    xmin = float(grid.x_nm[col0] - 0.5 * dx)
    xmax = float(grid.x_nm[col1 - 1] + 0.5 * dx)
    ymin = float(grid.y_nm[row0] - 0.5 * dy)
    ymax = float(grid.y_nm[row1 - 1] + 0.5 * dy)
    return CropRegion(xmin, xmax, ymin, ymax)


def find_common_crop(
    masks: list[np.ndarray],
    grid: GridDefinition,
    *,
    included: list[bool] | None = None,
    mode: str = "largest_rectangle",
) -> CropRegion | None:
    combined = common_mask(masks, included)
    region = largest_square(combined) if mode == "largest_square" else largest_rectangle(combined)
    if region is None:
        return None
    return indices_to_crop(region, grid)


def crop_mask_on_grid(crop: CropRegion, grid: GridDefinition) -> np.ndarray:
    """Return grid cells whose centres fall inside ``crop`` in physical coordinates."""
    xx, yy = np.meshgrid(grid.x_nm, grid.y_nm)
    return (
        (xx >= crop.xmin_nm)
        & (xx <= crop.xmax_nm)
        & (yy >= crop.ymin_nm)
        & (yy <= crop.ymax_nm)
    )


def crop_coverage_fraction(mask: np.ndarray, grid: GridDefinition, crop: CropRegion) -> float:
    """Fraction of a physical crop covered by one scan support mask."""
    region = crop_mask_on_grid(crop, grid)
    count = int(np.count_nonzero(region))
    if count == 0:
        return 0.0
    return float(np.count_nonzero(np.asarray(mask, dtype=bool) & region) / count)


def recommend_initial_inclusion(
    masks: list[np.ndarray],
    grid: GridDefinition,
    *,
    mode: str = "largest_rectangle",
) -> tuple[list[bool], CropRegion | None]:
    """Recommend a scan subset that restores a valid common physical area.

    All scans are retained whenever they have any common all-valid rectangle/square.  Only
    when the full set has no common physical area does the routine greedily remove the
    single scan whose removal yields the largest recoverable common area.  This is repeated
    until a valid region exists.  The GUI still shows every scan and lets the user override
    the recommendation before stacking.
    """
    if not masks:
        return [], None
    included = [True] * len(masks)
    crop = find_common_crop(masks, grid, included=included, mode=mode)
    if crop is not None:
        return included, crop

    while sum(included) > 1:
        best_index: int | None = None
        best_crop: CropRegion | None = None
        best_area = -1.0
        for index, keep in enumerate(included):
            if not keep:
                continue
            candidate = included.copy()
            candidate[index] = False
            candidate_crop = find_common_crop(masks, grid, included=candidate, mode=mode)
            area = (
                candidate_crop.width_nm * candidate_crop.height_nm
                if candidate_crop is not None
                else 0.0
            )
            if area > best_area:
                best_area = area
                best_index = index
                best_crop = candidate_crop
        if best_index is None:
            break
        included[best_index] = False
        if best_crop is not None:
            return included, best_crop
    return included, find_common_crop(masks, grid, included=included, mode=mode)
