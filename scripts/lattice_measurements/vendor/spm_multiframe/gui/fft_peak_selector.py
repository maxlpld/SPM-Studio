from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np

from spm_multiframe.analysis.fft import FFTResult


def select_two_reciprocal_peaks(fft: FFTResult, *, title: str) -> np.ndarray | None:
    """Open an interactive FFT diagnostic and return two clicked reciprocal vectors.

    Coordinates are read directly from axes expressed in cycles/nm. The user can close the
    window to reject manual selection. This path is opt-in and is recorded in the manifest.
    """
    fig, ax = plt.subplots(figsize=(6, 5.5))
    extent = [fft.fx_cpnm[0], fft.fx_cpnm[-1], fft.fy_cpnm[0], fft.fy_cpnm[-1]]
    ax.imshow(np.log1p(fft.magnitude), origin="lower", extent=extent, aspect="equal")
    ax.axhline(0.0, lw=0.5, alpha=0.5)
    ax.axvline(0.0, lw=0.5, alpha=0.5)
    ax.set_xlabel("kx (cycles/nm)")
    ax.set_ylabel("ky (cycles/nm)")
    ax.set_title(title + "\nClick two non-collinear primitive reciprocal peaks")
    points = plt.ginput(2, timeout=-1, show_clicks=True)
    plt.close(fig)
    if len(points) != 2:
        return None
    g = np.column_stack((np.asarray(points[0], dtype=float), np.asarray(points[1], dtype=float)))
    if abs(np.linalg.det(g)) < 1e-12:
        return None
    return g
