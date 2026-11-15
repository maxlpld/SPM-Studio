from __future__ import annotations

import warnings

import numpy as np

from spm_multiframe.models import ScanMetadata


def pixel_to_acquisition_time(
    metadata: ScanMetadata,
    trace_direction: str = "forward",
    *,
    timing_tolerance_fraction: float = 0.01,
) -> np.ndarray:
    """Return an absolute acquisition-time map in seconds for every stored pixel.

    The raw SXM row/column order is chronological within each stored trace.  Spatial
    orientation is deliberately not inferred here; that is handled by
    :func:`pixel_to_nominal_xy`.  Forward and backward traces are offset within each
    line cycle using Nanonis line-time metadata when available.
    """
    fwd = metadata.line_time_forward_s
    bwd = metadata.line_time_backward_s
    if fwd is None or fwd <= 0:
        line_cycle = metadata.duration_s / max(metadata.ny, 1)
        fwd = line_cycle / 2.0
        bwd = line_cycle / 2.0
    elif bwd is None or bwd <= 0:
        bwd = fwd

    line_cycle = fwd + bwd
    trace = trace_direction.strip().lower()
    if trace in {"backward", "bwd", "retrace", "1"}:
        trace_offset = fwd
        trace_time = bwd
    else:
        trace_offset = 0.0
        trace_time = fwd

    q = np.arange(metadata.ny, dtype=float)[:, None]
    p = np.arange(metadata.nx, dtype=float)[None, :]
    orientation = str(metadata.extra.get("array_orientation", "acquisition")).lower()
    if orientation == "display":
        # GWY data imported from Nanonis are stored in a common display orientation.
        # Reconstruct chronological acquisition indices from that physical orientation:
        # an up scan starts at the bottom, while a backward trace starts at the right.
        if metadata.frame_direction.strip().lower() in {"down", "downward", "bottom", "-y", "negative"}:
            line_index = q
        else:
            line_index = metadata.ny - 1 - q
        if trace in {"backward", "bwd", "retrace", "1"}:
            pixel_index = metadata.nx - 1 - p
        else:
            pixel_index = p
    else:
        # Raw SXM arrays are chronological in storage order.
        line_index = q
        pixel_index = p
    dt_pixel = trace_time / max(metadata.nx, 1)
    times = metadata.start_time_s + line_index * line_cycle + trace_offset + pixel_index * dt_pixel
    times = np.broadcast_to(times, (metadata.ny, metadata.nx)).copy()

    reconstructed_end = metadata.start_time_s + metadata.ny * line_cycle
    recorded_duration = metadata.duration_s
    if recorded_duration > 0:
        mismatch = abs((reconstructed_end - metadata.start_time_s) - recorded_duration)
        if mismatch / recorded_duration > timing_tolerance_fraction:
            warnings.warn(
                "Raster timing reconstructed from line times disagrees with recorded frame "
                f"duration by {100*mismatch/recorded_duration:.2f}%.",
                RuntimeWarning,
                stacklevel=2,
            )
    return times


def relative_time_map(t_s: np.ndarray, reference_time_s: float) -> np.ndarray:
    return np.asarray(t_s, dtype=float) - float(reference_time_s)
