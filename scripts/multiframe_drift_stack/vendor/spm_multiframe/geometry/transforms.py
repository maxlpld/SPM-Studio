from __future__ import annotations

import numpy as np


def corrected_coordinates(
    x_nom_nm: np.ndarray,
    y_nom_nm: np.ndarray,
    t_s: np.ndarray,
    correction_velocity_nm_s: np.ndarray,
    reference_time_s: float,
    residual_translation_nm: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply the package's explicit linear drift-correction sign convention.

    ``r_corr = r_nom + v_c * (t - t_ref) + delta_i``.
    """
    velocity = np.asarray(correction_velocity_nm_s, dtype=float).reshape(2)
    delta = np.zeros(2, dtype=float) if residual_translation_nm is None else np.asarray(
        residual_translation_nm, dtype=float
    ).reshape(2)
    dt = np.asarray(t_s, dtype=float) - float(reference_time_s)
    return (
        np.asarray(x_nom_nm, dtype=float) + velocity[0] * dt + delta[0],
        np.asarray(y_nom_nm, dtype=float) + velocity[1] * dt + delta[1],
    )


def perimeter_points(x_nm: np.ndarray, y_nm: np.ndarray) -> np.ndarray:
    """Return an ordered Nx2 boundary polyline from structured coordinate arrays."""
    if x_nm.shape != y_nm.shape or x_nm.ndim != 2:
        raise ValueError("x_nm and y_nm must be matching 2-D arrays")
    if min(x_nm.shape) < 2:
        return np.column_stack((x_nm.ravel(), y_nm.ravel()))
    top = np.column_stack((x_nm[0, :], y_nm[0, :]))
    right = np.column_stack((x_nm[1:, -1], y_nm[1:, -1]))
    bottom = np.column_stack((x_nm[-1, -2::-1], y_nm[-1, -2::-1]))
    left = np.column_stack((x_nm[-2:0:-1, 0], y_nm[-2:0:-1, 0]))
    return np.vstack((top, right, bottom, left))


def bounds_from_coordinates(x_nm: np.ndarray, y_nm: np.ndarray) -> tuple[float, float, float, float]:
    valid = np.isfinite(x_nm) & np.isfinite(y_nm)
    if not np.any(valid):
        raise ValueError("No finite coordinates")
    return (
        float(np.nanmin(x_nm[valid])),
        float(np.nanmax(x_nm[valid])),
        float(np.nanmin(y_nm[valid])),
        float(np.nanmax(y_nm[valid])),
    )
