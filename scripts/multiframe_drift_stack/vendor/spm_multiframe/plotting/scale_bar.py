from __future__ import annotations

import math

from matplotlib.axes import Axes


def nice_scale_length_nm(width_nm: float, fraction: float = 0.25) -> float:
    """Choose a round physical length near 20–30% of the displayed image width."""
    if width_nm <= 0:
        raise ValueError("width_nm must be > 0")
    target = width_nm * fraction
    exponent = math.floor(math.log10(target)) if target > 0 else 0
    candidates: list[float] = []
    for exp in range(exponent - 1, exponent + 2):
        candidates.extend(base * 10.0**exp for base in (1.0, 2.0, 3.0, 5.0))
    valid = [value for value in candidates if 0 < value < width_nm]
    return min(valid, key=lambda value: abs(value - target))


def add_scale_bar(
    ax: Axes,
    *,
    length_nm: float | None = None,
    color: str = "white",
    linewidth: float = 3.0,
    location: str = "lower right",
    margin_fraction: float = 0.05,
) -> float:
    """Draw a scale bar directly in the axis' physical nm data coordinates."""
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    width = abs(xmax - xmin)
    height = abs(ymax - ymin)
    length = nice_scale_length_nm(width) if length_nm is None else float(length_nm)
    mx, my = margin_fraction * width, margin_fraction * height
    if location == "lower left":
        x0, y0 = min(xmin, xmax) + mx, min(ymin, ymax) + my
    else:
        x0, y0 = max(xmin, xmax) - mx - length, min(ymin, ymax) + my
    ax.plot([x0, x0 + length], [y0, y0], color=color, lw=linewidth, solid_capstyle="butt")
    label = f"{length:g} nm" if length >= 0.1 else f"{length * 1000:g} pm"
    ax.text(x0 + 0.5 * length, y0 + 0.02 * height, label, color=color, ha="center", va="bottom")
    return length
