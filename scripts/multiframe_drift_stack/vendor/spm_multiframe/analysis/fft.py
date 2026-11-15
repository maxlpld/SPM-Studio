from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage.feature import peak_local_max

from spm_multiframe.analysis.registration import subtract_robust_plane
from spm_multiframe.models import FFTPeak, GridDefinition


@dataclass(frozen=True)
class FFTResult:
    magnitude: np.ndarray
    fx_cpnm: np.ndarray
    fy_cpnm: np.ndarray
    prepared_image: np.ndarray


def prepare_lattice_copy(image: np.ndarray) -> np.ndarray:
    """Plane-subtract, mean-center and Hann-window an FFT-only analysis copy."""
    arr = subtract_robust_plane(np.asarray(image, dtype=float))
    valid = np.isfinite(arr)
    if not np.any(valid):
        raise ValueError("FFT input contains no finite pixels")
    mean = float(np.nanmean(arr))
    arr = np.where(valid, arr - mean, 0.0)
    window = np.outer(np.hanning(arr.shape[0]), np.hanning(arr.shape[1]))
    return arr * window


def compute_fft(image: np.ndarray, grid: GridDefinition) -> FFTResult:
    prepared = prepare_lattice_copy(image)
    spectrum = np.fft.fftshift(np.fft.fft2(prepared))
    magnitude = np.abs(spectrum)
    fx = np.fft.fftshift(np.fft.fftfreq(prepared.shape[1], d=abs(grid.dx_nm)))
    fy = np.fft.fftshift(np.fft.fftfreq(prepared.shape[0], d=abs(grid.dy_nm)))
    return FFTResult(magnitude=magnitude, fx_cpnm=fx, fy_cpnm=fy, prepared_image=prepared)


def _quadratic_subpixel_peak(log_patch: np.ndarray) -> tuple[float, float] | None:
    """Fit a 2-D quadratic around a 3×3 peak and return local ``(dx,dy)``."""
    if log_patch.shape != (3, 3) or not np.all(np.isfinite(log_patch)):
        return None
    yy, xx = np.mgrid[-1:2, -1:2]
    design = np.column_stack(
        (
            xx.ravel() ** 2,
            yy.ravel() ** 2,
            (xx * yy).ravel(),
            xx.ravel(),
            yy.ravel(),
            np.ones(9),
        )
    )
    coeff, *_ = np.linalg.lstsq(design, log_patch.ravel(), rcond=None)
    a, b, c, d, e, _f = coeff
    hessian = np.asarray([[2 * a, c], [c, 2 * b]], dtype=float)
    gradient = np.asarray([d, e], dtype=float)
    try:
        offset = -np.linalg.solve(hessian, gradient)
    except np.linalg.LinAlgError:
        return None
    eig = np.linalg.eigvalsh(hessian)
    if not np.all(eig < 0) or np.any(np.abs(offset) > 1.5):
        return None
    return float(offset[0]), float(offset[1])


def detect_fft_peaks(
    fft: FFTResult,
    *,
    dc_radius_bins: int = 4,
    min_peak_distance_bins: int = 4,
    max_peaks: int = 32,
) -> list[FFTPeak]:
    magnitude = np.asarray(fft.magnitude, dtype=float).copy()
    ny, nx = magnitude.shape
    cy, cx = ny // 2, nx // 2
    yy, xx = np.ogrid[:ny, :nx]
    central = (yy - cy) ** 2 + (xx - cx) ** 2 <= dc_radius_bins**2
    magnitude[central] = 0.0
    finite = magnitude[np.isfinite(magnitude) & ~central]
    if finite.size == 0:
        return []
    background = float(np.median(finite))
    q90 = float(np.percentile(finite, 90))
    threshold = max(background * 3.0, q90 * 0.15)
    coordinates = peak_local_max(
        magnitude,
        min_distance=max(1, min_peak_distance_bins),
        threshold_abs=threshold,
        num_peaks=max_peaks,
        exclude_border=2,
    )
    if len(coordinates) == 0:
        return []

    dfx = float(np.median(np.diff(fft.fx_cpnm)))
    dfy = float(np.median(np.diff(fft.fy_cpnm)))
    peaks: list[FFTPeak] = []
    eps = np.finfo(float).tiny
    for row, col in coordinates:
        patch = magnitude[row - 1 : row + 2, col - 1 : col + 2]
        log_patch = np.log(np.maximum(patch, eps))
        refined = _quadratic_subpixel_peak(log_patch)
        dx, dy = refined if refined is not None else (0.0, 0.0)
        gx = float(fft.fx_cpnm[col] + dx * dfx)
        gy = float(fft.fy_cpnm[row] + dy * dfy)
        amp = float(magnitude[row, col])
        snr = amp / max(background, eps)
        # Frequency-bin width is a conservative localization scale; stronger peaks receive
        # a smaller uncertainty but never better than 0.05 bin without a full noise model.
        sigma = 0.5 * np.hypot(dfx, dfy) / max(np.sqrt(snr), 1.0)
        sigma = max(float(sigma), 0.05 * float(np.hypot(dfx, dfy)))
        peaks.append(FFTPeak(gx, gy, amp, float(snr), sigma))
    peaks.sort(key=lambda peak: peak.amplitude, reverse=True)
    return peaks
