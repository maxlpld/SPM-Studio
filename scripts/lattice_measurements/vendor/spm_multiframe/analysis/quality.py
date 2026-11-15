from __future__ import annotations

import numpy as np


def robust_noise_sigma(image: np.ndarray) -> float:
    """Estimate high-frequency noise from first differences using a robust MAD scale."""
    arr = np.asarray(image, dtype=float)
    diffs: list[np.ndarray] = []
    if arr.shape[1] > 1:
        diffs.append(np.diff(arr, axis=1).ravel())
    if arr.shape[0] > 1:
        diffs.append(np.diff(arr, axis=0).ravel())
    if not diffs:
        return float("nan")
    values = np.concatenate(diffs)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan")
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    # Difference of independent samples increases sigma by sqrt(2).
    return float(1.4826 * mad / np.sqrt(2.0))


def invalid_fraction(image: np.ndarray) -> float:
    arr = np.asarray(image)
    return float(1.0 - np.count_nonzero(np.isfinite(arr)) / arr.size)


def quality_flags(
    *,
    correlation: float,
    residual_shift_nm: float,
    noise_sigma: float,
    median_noise_sigma: float,
    invalid_fraction_value: float,
    max_shift_nm: float,
) -> list[str]:
    flags: list[str] = []
    if correlation < 0.35:
        flags.append("low_registration_correlation")
    if residual_shift_nm > max_shift_nm:
        flags.append("large_residual_shift")
    if np.isfinite(noise_sigma) and np.isfinite(median_noise_sigma) and median_noise_sigma > 0:
        if noise_sigma > 2.5 * median_noise_sigma:
            flags.append("high_noise")
    if invalid_fraction_value > 0.10:
        flags.append("high_invalid_fraction")
    return flags
