from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import numpy as np

from spm_multiframe.exceptions import MissingMetadataError
from spm_multiframe.io.sxm_reader import SXMFile
from spm_multiframe.models import ScanMetadata
from spm_multiframe.utils.hashing import sha256_file


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _first_float(value: Any) -> float | None:
    for item in _listify(value):
        try:
            return float(item)
        except (TypeError, ValueError):
            continue
    return None


def _pair_float(value: Any, key: str) -> tuple[float, float]:
    items = _listify(value)
    if len(items) < 2:
        raise MissingMetadataError(f"Missing or incomplete {key} metadata")
    try:
        return float(items[0]), float(items[1])
    except (TypeError, ValueError) as exc:
        raise MissingMetadataError(f"Invalid {key}: {items!r}") from exc


def _parse_datetime(header: dict[str, Any], path: Path) -> tuple[float, str | None, str]:
    raw_date = header.get("REC_DATE")
    raw_time = header.get("REC_TIME")
    date_text = " ".join(str(x) for x in _listify(raw_date)).strip()
    time_text = " ".join(str(x) for x in _listify(raw_time)).strip()
    combined = f"{date_text} {time_text}".strip()

    formats = (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%m/%d/%Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(combined, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return dt.timestamp(), dt.replace(tzinfo=None).isoformat(), "header_naive_time"

    # A missing acquisition timestamp should not make geometry unreadable. File mtime is
    # explicitly marked as a fallback so downstream reports do not present it as exact.
    stat_time = path.stat().st_mtime
    return stat_time, datetime.fromtimestamp(stat_time, tz=timezone.utc).isoformat(), "file_mtime_utc"


def _extract_piezo_calibration(raw_header_text: str, axis: str) -> float | None:
    patterns = (
        rf"Calib\.\s*{axis}\s*\(m/V\)\s*[:=]?\s*([-+0-9.eE]+)",
        rf"{axis}\s*Calib(?:ration)?\s*\(m/V\)\s*[:=]?\s*([-+0-9.eE]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw_header_text, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None


def _find_setpoint(header: dict[str, Any]) -> float | None:
    for key in ("CURRENT", "SETPOINT", "Z-CONTROLLER", "Z_CONTROLLER"):
        value = header.get(key)
        if key in {"CURRENT", "SETPOINT"}:
            result = _first_float(value)
            if result is not None:
                return result
    return None


def metadata_from_sxm(sxm: SXMFile, *, timing_tolerance_fraction: float = 0.01) -> ScanMetadata:
    header = sxm.header
    try:
        pixels = _listify(header["SCAN_PIXELS"])
        nx, ny = int(pixels[0]), int(pixels[1])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise MissingMetadataError(f"{sxm.path.name}: invalid SCAN_PIXELS") from exc

    range_x_m, range_y_m = _pair_float(header.get("SCAN_RANGE"), "SCAN_RANGE")
    offset_x_m, offset_y_m = _pair_float(header.get("SCAN_OFFSET", [0.0, 0.0]), "SCAN_OFFSET")
    angle = _first_float(header.get("SCAN_ANGLE")) or 0.0
    frame_direction = str(header.get("SCAN_DIR", "up")).strip().lower()

    start_s, acquisition_iso, time_source = _parse_datetime(header, sxm.path)
    scan_time = [float(x) for x in _listify(header.get("SCAN_TIME")) if _is_float_like(x)]
    line_forward = scan_time[0] if scan_time else None
    line_backward = scan_time[1] if len(scan_time) >= 2 else line_forward

    source_format = str(header.get("_SOURCE_FORMAT", "sxm")).lower()
    gwy_sidecar_geometry = bool(header.get("_GWY_SIDECAR_GEOMETRY_USED", False))
    timing_confidence = "reduced"
    if line_forward is not None and line_forward > 0:
        # Nanonis SCAN_TIME commonly stores forward/backward line times. Even when only
        # one image direction is saved, the retrace still consumes acquisition time.
        line_cycle = line_forward + (line_backward or 0.0)
        duration_s = ny * line_cycle
        timing_confidence = "high" if len(scan_time) >= 2 else "medium"
        if source_format == "gwy" and not gwy_sidecar_geometry:
            # Standard Gwyddion Nanonis imports preserve total acquisition time but not
            # exact per-line SCAN_TIME.  The GWY adapter may therefore reconstruct an
            # even trace/retrace split; do not report that estimate as high confidence.
            timing_confidence = "reduced"
    else:
        # Preserve a usable time ordering while loudly marking the missing raster timing.
        duration_s = max(1e-9, sxm.path.stat().st_mtime - start_s)
        timing_confidence = "low"
    end_s = start_s + duration_s

    descriptors = sxm.channel_descriptors
    channel_names = tuple(dict.fromkeys(desc.name for desc in descriptors))
    channel_units = {desc.name: desc.unit for desc in descriptors}
    bias = _first_float(header.get("BIAS"))
    setpoint = _find_setpoint(header)

    # Retain a compact subset of raw values used for audit/debugging without embedding
    # the entire textual header in every manifest scan entry.
    extra = {
        "time_source": time_source,
        "scan_time_raw": scan_time,
        "scan_type": header.get("SCANIT_TYPE", header.get("SCAN_TYPE")),
        "timing_tolerance_fraction": timing_tolerance_fraction,
        "source_format": source_format,
        "array_orientation": str(header.get("_ARRAY_ORIENTATION", "acquisition")).lower(),
        "gwy_sidecar_sxm": header.get("_GWY_SIDECAR_SXM"),
        "gwy_sidecar_geometry_used": gwy_sidecar_geometry,
    }

    return ScanMetadata(
        path=sxm.path.resolve(),
        sha256=sha256_file(sxm.path),
        nx=nx,
        ny=ny,
        width_nm=abs(range_x_m) * 1e9,
        height_nm=abs(range_y_m) * 1e9,
        center_x_nm=offset_x_m * 1e9,
        center_y_nm=offset_y_m * 1e9,
        scan_angle_deg=float(angle),
        frame_direction=frame_direction,
        start_time_s=float(start_s),
        end_time_s=float(end_s),
        line_time_forward_s=line_forward,
        line_time_backward_s=line_backward,
        piezo_cal_x_m_per_v=_extract_piezo_calibration(sxm.raw_header_text, "X"),
        piezo_cal_y_m_per_v=_extract_piezo_calibration(sxm.raw_header_text, "Y"),
        piezo_cal_z_m_per_v=_extract_piezo_calibration(sxm.raw_header_text, "Z"),
        channel_names=channel_names,
        acquisition_datetime=acquisition_iso,
        bias_v=bias,
        setpoint_a=setpoint,
        timing_confidence=timing_confidence,
        channel_units=channel_units,
        extra=extra,
    )



def metadata_for_channel(
    sxm: SXMFile,
    metadata: ScanMetadata,
    channel: str,
    direction: str = "forward",
) -> ScanMetadata:
    """Return metadata whose raster geometry matches one concrete data channel.

    SXM channels normally all share one raster geometry.  Gwyddion containers do not
    have to: a user can crop or resize one derived DataField while leaving the other
    channels untouched.  Geometry used for physical coordinates must therefore follow
    the selected channel rather than the first DataField in the container.

    When GWY per-channel geometry is unavailable, the actual data-array shape is still
    authoritative for ``nx``/``ny`` while the existing physical extent is retained.
    """
    data = np.asarray(sxm.get_channel(channel, direction))
    if data.ndim != 2:
        raise MissingMetadataError(
            f"{sxm.path.name}: channel {channel!r} is not a 2-D image"
        )
    ny, nx = map(int, data.shape)

    geometry_map = sxm.header.get("_GWY_CHANNEL_GEOMETRY", {})
    geometry = None
    if isinstance(geometry_map, dict):
        by_direction = geometry_map.get(channel)
        if isinstance(by_direction, dict):
            geometry = by_direction.get(direction)
            if geometry is None and len(by_direction) == 1:
                geometry = next(iter(by_direction.values()))

    width_nm = metadata.width_nm
    height_nm = metadata.height_nm
    center_x_nm = metadata.center_x_nm
    center_y_nm = metadata.center_y_nm
    extra = dict(metadata.extra)

    if isinstance(geometry, dict):
        try:
            width_nm = abs(float(geometry["width_m"])) * 1e9
            height_nm = abs(float(geometry["height_m"])) * 1e9
        except (KeyError, TypeError, ValueError):
            pass

        compatible = bool(int(geometry.get("sidecar_geometry_compatible", 0)))
        if not compatible:
            # For a cropped/resized GWY field, Gwyddion's DataField extent is the only
            # geometry guaranteed to describe the pixels now being analysed.  Translation
            # does not affect lattice lengths/angles, but using the field centre also keeps
            # overlays and local-coordinate exports internally self-consistent.
            try:
                xoff_m = float(geometry.get("xoff_m", 0.0))
                yoff_m = float(geometry.get("yoff_m", 0.0))
                center_x_nm = (xoff_m + 0.5 * width_nm * 1e-9) * 1e9
                center_y_nm = (yoff_m + 0.5 * height_nm * 1e-9) * 1e9
            except (TypeError, ValueError):
                pass
            extra["geometry_confidence"] = "resized_or_cropped_gwy"
            extra["timing_confidence_override"] = "reduced"
        else:
            extra["geometry_confidence"] = "matched_sidecar"

    if (ny, nx) != (metadata.ny, metadata.nx):
        extra["original_metadata_shape"] = [metadata.ny, metadata.nx]
        extra["channel_data_shape"] = [ny, nx]
        extra.setdefault("geometry_confidence", "channel_shape_override")

    timing_confidence = metadata.timing_confidence
    if extra.get("timing_confidence_override"):
        timing_confidence = str(extra["timing_confidence_override"])

    return replace(
        metadata,
        nx=nx,
        ny=ny,
        width_nm=float(width_nm),
        height_nm=float(height_nm),
        center_x_nm=float(center_x_nm),
        center_y_nm=float(center_y_nm),
        timing_confidence=timing_confidence,
        extra=extra,
    )

def _is_float_like(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
