from __future__ import annotations

import numpy as np


def percentile_intervals(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return central empirical 68% and 95% intervals along axis 0."""
    arr = np.asarray(samples, dtype=float)
    if arr.size == 0:
        shape = arr.shape[1:] if arr.ndim > 1 else (1,)
        nan = np.full((2, *shape), np.nan)
        return nan, nan.copy()
    interval68 = np.nanpercentile(arr, [16.0, 84.0], axis=0)
    interval95 = np.nanpercentile(arr, [2.5, 97.5], axis=0)
    return interval68, interval95


def huber_location(values: np.ndarray, weights: np.ndarray | None = None, c: float = 1.345) -> np.ndarray:
    """Robust component-wise location estimate using iteratively reweighted Huber weights."""
    x = np.asarray(values, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    base_weights = np.ones(x.shape[0]) if weights is None else np.asarray(weights, dtype=float)
    location = np.average(x, axis=0, weights=base_weights)
    for _ in range(30):
        residual = x - location
        scale = 1.4826 * np.nanmedian(np.abs(residual), axis=0)
        scale = np.where(scale > np.finfo(float).eps, scale, 1.0)
        u = np.abs(residual / scale)
        huber = np.where(u <= c, 1.0, c / np.maximum(u, np.finfo(float).eps))
        combined = huber * base_weights[:, None]
        new = np.sum(combined * x, axis=0) / np.maximum(np.sum(combined, axis=0), 1e-12)
        if np.allclose(new, location, rtol=0, atol=1e-10):
            location = new
            break
        location = new
    return location.squeeze()
