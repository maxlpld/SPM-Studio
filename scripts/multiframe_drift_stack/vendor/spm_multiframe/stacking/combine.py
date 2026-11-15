from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StackStatistics:
    value: np.ndarray
    uncertainty: np.ndarray
    contribution_count: np.ndarray


def _weighted_stats(data: np.ndarray, weights: np.ndarray) -> StackStatistics:
    valid = np.isfinite(data)
    w = weights[:, None, None] * valid
    sum_w = np.sum(w, axis=0)
    safe_sum_w = np.where(sum_w > 0, sum_w, np.nan)
    mean = np.nansum(w * np.where(valid, data, 0.0), axis=0) / safe_sum_w
    diff = np.where(valid, data - mean[None, :, :], 0.0)
    variance = np.nansum(w * diff**2, axis=0) / safe_sum_w
    sum_w2 = np.sum(w**2, axis=0)
    neff = np.full_like(sum_w, np.nan, dtype=float)
    np.divide(sum_w**2, sum_w2, out=neff, where=sum_w2 > 0)
    uncertainty = np.sqrt(variance) / np.sqrt(neff)
    count = np.sum(valid, axis=0).astype(np.uint16)
    mean[count == 0] = np.nan
    uncertainty[count <= 1] = np.nan
    return StackStatistics(mean, uncertainty, count)


def combine_frames(
    frames: list[np.ndarray],
    *,
    method: str = "sigma_clipped_mean",
    weights: np.ndarray | None = None,
    sigma_clip: float = 3.0,
) -> StackStatistics:
    """Combine aligned frames without spatial filtering and retain uncertainty/count maps."""
    if not frames:
        raise ValueError("At least one frame is required")
    data = np.asarray(frames, dtype=float)
    n = data.shape[0]
    if weights is None:
        weights_arr = np.ones(n, dtype=float)
    else:
        weights_arr = np.asarray(weights, dtype=float).reshape(n)
        weights_arr = np.where(np.isfinite(weights_arr) & (weights_arr > 0), weights_arr, 0.0)
        if not np.any(weights_arr > 0):
            weights_arr[:] = 1.0

    normalized_method = method.strip().lower()
    if normalized_method == "mean":
        weights_arr = np.ones(n, dtype=float)
        return _weighted_stats(data, weights_arr)
    if normalized_method == "weighted_mean":
        return _weighted_stats(data, weights_arr)
    if normalized_method == "median":
        count = np.sum(np.isfinite(data), axis=0).astype(np.uint16)
        value = np.nanmedian(data, axis=0)
        mad = np.nanmedian(np.abs(data - value[None, :, :]), axis=0)
        spread = 1.4826 * mad
        uncertainty = spread / np.sqrt(np.where(count > 0, count, np.nan))
        value[count == 0] = np.nan
        uncertainty[count <= 1] = np.nan
        return StackStatistics(value, uncertainty, count)
    if normalized_method == "sigma_clipped_mean":
        median = np.nanmedian(data, axis=0)
        mad = np.nanmedian(np.abs(data - median[None, :, :]), axis=0)
        sigma = 1.4826 * mad
        # A zero MAD means at least half the frames are exactly at the median. In that
        # special case, deviations are isolated outliers and the robust threshold should
        # be zero rather than infinity.
        threshold = sigma_clip * sigma
        keep = np.abs(data - median[None, :, :]) <= (threshold[None, :, :] + 1e-15)
        clipped = np.where(keep, data, np.nan)
        return _weighted_stats(clipped, weights_arr)
    raise ValueError(f"Unknown stacking method: {method!r}")
