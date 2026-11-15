from __future__ import annotations

import numpy as np

from spm_multiframe.config import CalibrationOverride
from spm_multiframe.models import ScanMetadata


def rotation_matrix(angle_deg: float) -> np.ndarray:
    """Return the 2×2 counter-clockwise scan-angle rotation matrix."""
    theta = np.deg2rad(angle_deg)
    c, s = np.cos(theta), np.sin(theta)
    return np.asarray([[c, -s], [s, c]], dtype=float)


def _is_down(frame_direction: str) -> bool:
    text = frame_direction.strip().lower()
    return text in {"down", "downward", "bottom", "-y", "negative"}


def _is_backward(trace_direction: str) -> bool:
    return trace_direction.strip().lower() in {"backward", "bwd", "retrace", "1"}


def pixel_to_nominal_xy(
    metadata: ScanMetadata,
    trace_direction: str = "forward",
    calibration: CalibrationOverride | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Reconstruct physical sample coordinates for each stored SXM pixel.

    Nanonis stores image data in acquisition order.  Consequently a down scan starts at
    the upper edge and a backward trace starts at the right edge.  We keep the raw array
    untouched and encode those semantics only in the coordinate arrays.  This is a
    metadata-defined coordinate reconstruction, not a display-oriented image flip.

    ``factor_x`` / ``factor_y`` are independent physical-axis corrections and are
    applied exactly once to displacements from the recorded scan centre.
    """
    cal = calibration or CalibrationOverride()
    p_raw = np.arange(metadata.nx, dtype=float)
    q_raw = np.arange(metadata.ny, dtype=float)

    orientation = str(metadata.extra.get("array_orientation", "acquisition")).lower()
    if orientation == "display":
        # Gwyddion's Nanonis importer already flips backward traces horizontally and
        # up-scans vertically into a common display/physical orientation.  Applying the
        # SXM raw-storage flips a second time would mirror the GWY data.  Row zero is the
        # displayed top edge, hence the y-up physical index is reversed once here.
        p_phys = p_raw
        q_phys = metadata.ny - 1 - q_raw
    else:
        p_phys = metadata.nx - 1 - p_raw if _is_backward(trace_direction) else p_raw
        q_phys = metadata.ny - 1 - q_raw if _is_down(metadata.frame_direction) else q_raw

    u = (p_phys + 0.5) / metadata.nx - 0.5
    v = (q_phys + 0.5) / metadata.ny - 0.5
    uu, vv = np.meshgrid(u, v)

    local = np.stack((metadata.width_nm * uu, metadata.height_nm * vv), axis=0)
    rotated = rotation_matrix(metadata.scan_angle_deg) @ local.reshape(2, -1)
    dx = rotated[0].reshape(metadata.ny, metadata.nx) * cal.factor_x
    dy = rotated[1].reshape(metadata.ny, metadata.nx) * cal.factor_y
    return metadata.center_x_nm + dx, metadata.center_y_nm + dy


def nominal_pixel_size_nm(metadata: ScanMetadata) -> tuple[float, float]:
    return metadata.width_nm / metadata.nx, metadata.height_nm / metadata.ny
