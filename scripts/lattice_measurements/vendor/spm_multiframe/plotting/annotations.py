from __future__ import annotations

import numpy as np
from matplotlib.axes import Axes
from matplotlib.patches import Arc
from spm_multiframe.config import AnnotationConfig
from spm_multiframe.models import GridDefinition

def _clutter_score(image: np.ndarray, grid: GridDefinition, anchor: np.ndarray, basis_nm: np.ndarray) -> float:
    x_end = np.asarray([anchor[0], *(anchor[0] + basis_nm[0, :])]); y_end = np.asarray([anchor[1], *(anchor[1] + basis_nm[1, :])])
    xmin, xmax = np.min(x_end), np.max(x_end); ymin, ymax = np.min(y_end), np.max(y_end)
    c0 = max(0, int(np.searchsorted(grid.x_nm, xmin) - 1)); c1 = min(len(grid.x_nm), int(np.searchsorted(grid.x_nm, xmax) + 2))
    r0 = max(0, int(np.searchsorted(grid.y_nm, ymin) - 1)); r1 = min(len(grid.y_nm), int(np.searchsorted(grid.y_nm, ymax) + 2))
    patch = image[r0:r1, c0:c1]
    if patch.size == 0 or not np.any(np.isfinite(patch)): return float("inf")
    gy, gx = np.gradient(np.nan_to_num(patch, nan=float(np.nanmedian(patch))))
    return float(np.nanvar(patch) + np.nanmean(np.hypot(gx, gy)))

def choose_lattice_anchor(image: np.ndarray, grid: GridDefinition, basis_nm: np.ndarray, margin_fraction: float = 0.08) -> np.ndarray:
    xmin, xmax, ymin, ymax = grid.extent; width, height = xmax - xmin, ymax - ymin; margins = np.asarray([margin_fraction * width, margin_fraction * height])
    corners=[np.asarray([xmin, ymin]) + margins,np.asarray([xmax, ymin]) + np.asarray([-margins[0], margins[1]]),np.asarray([xmin, ymax]) + np.asarray([margins[0], -margins[1]]),np.asarray([xmax, ymax]) - margins]
    candidates=[]
    for anchor in corners:
        endpoints = np.column_stack((anchor, anchor + basis_nm[:, 0], anchor + basis_nm[:, 1]))
        if (np.all(endpoints[0] >= xmin) and np.all(endpoints[0] <= xmax) and np.all(endpoints[1] >= ymin) and np.all(endpoints[1] <= ymax)): candidates.append((_clutter_score(image, grid, anchor, basis_nm), anchor))
    if candidates: return min(candidates, key=lambda item: item[0])[1]
    return np.asarray([xmin + 0.2 * width, ymin + 0.2 * height], dtype=float)

def add_lattice_overlay(ax: Axes, basis_nm: np.ndarray, gamma_deg: float, *, image: np.ndarray | None = None, grid: GridDefinition | None = None, config: AnnotationConfig | None = None, anchor_nm: tuple[float, float] | None = None) -> np.ndarray:
    cfg = config or AnnotationConfig(); basis = np.asarray(basis_nm, dtype=float).reshape(2, 2)
    if anchor_nm is not None: anchor = np.asarray(anchor_nm, dtype=float)
    elif image is not None and grid is not None and cfg.placement == "auto": anchor = choose_lattice_anchor(image, grid, basis)
    else:
        xmin, xmax = ax.get_xlim(); ymin, ymax = ax.get_ylim(); anchor = np.asarray([min(xmin, xmax) + 0.1 * abs(xmax - xmin), min(ymin, ymax) + 0.1 * abs(ymax - ymin)])
    vectors=[basis[:, 0], basis[:, 1]]; colors=[cfg.color_a, cfg.color_b]
    for vector, color in zip(vectors, colors, strict=True):
        ax.annotate("", xy=anchor + vector, xytext=anchor, arrowprops={"arrowstyle": "->", "color": color, "lw": 2.0})
    angle_a=float(np.degrees(np.arctan2(vectors[0][1], vectors[0][0]))); angle_b=float(np.degrees(np.arctan2(vectors[1][1], vectors[1][0])))
    delta=(angle_b - angle_a) % 360.0
    if delta > 180.0: angle_a, angle_b = angle_b, angle_a; delta = 360.0 - delta
    radius = 0.28 * min(np.linalg.norm(vectors[0]), np.linalg.norm(vectors[1]))
    arc = Arc(anchor, 2 * radius, 2 * radius, theta1=angle_a, theta2=angle_a + delta, color=cfg.color_gamma, lw=1.5)
    ax.add_patch(arc)
    legend=(f"a = {np.linalg.norm(vectors[0]) * 10:.2f} Å\n" f"b = {np.linalg.norm(vectors[1]) * 10:.2f} Å\n" f"γ = {gamma_deg:.1f}°")
    xmin, xmax = ax.get_xlim(); ymin, ymax = ax.get_ylim()
    ax.text(min(xmin, xmax) + 0.03 * abs(xmax - xmin), max(ymin, ymax) - 0.04 * abs(ymax - ymin), legend, color="white", ha="left", va="top")
    return anchor
