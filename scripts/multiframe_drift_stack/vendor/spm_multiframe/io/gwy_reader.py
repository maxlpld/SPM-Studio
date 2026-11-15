from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np

from spm_multiframe.exceptions import SPMError
from spm_multiframe.io.sxm_reader import ChannelDescriptor, SXMFile, read_sxm


_DIRECTION_SUFFIX = re.compile(
    r"(?ix)"
    r"(?:\s*[\(\[\{]\s*(forward|backward|fwd|bwd|trace|retrace)\s*[\)\]\}]\s*$)"
    r"|(?:\s*[-_:]\s*(forward|backward|fwd|bwd|trace|retrace)\s*$)"
)

_LENGTH_TO_M = {
    "m": 1.0,
    "meter": 1.0,
    "metre": 1.0,
    "mm": 1e-3,
    "um": 1e-6,
    "µm": 1e-6,
    "μm": 1e-6,
    "nm": 1e-9,
    "pm": 1e-12,
    "a": 1e-10,
    "å": 1e-10,
    "angstrom": 1e-10,
    "angstroms": 1e-10,
}


def _unit_string(unit_obj: Any) -> str:
    if unit_obj is None:
        return ""
    value = getattr(unit_obj, "unitstr", None)
    if value is None and isinstance(unit_obj, Mapping):
        value = unit_obj.get("unitstr", "")
    return str(value or "").strip()


def _length_scale_to_m(unit: str) -> float:
    text = unit.strip().lower().replace("ångström", "angstrom")
    if text in _LENGTH_TO_M:
        return _LENGTH_TO_M[text]
    # Gwyddion normally stores Nanonis lateral data in metres.  Reject unknown lateral
    # units instead of silently treating pixels or arbitrary units as physical length.
    raise SPMError(
        f"Unsupported GWY lateral unit {unit!r}. Expected a physical length unit such as m, nm or µm."
    )


def _normalize_direction(value: str) -> str:
    text = value.strip().lower()
    if text in {"forward", "fwd", "trace"}:
        return "forward"
    if text in {"backward", "bwd", "retrace"}:
        return "backward"
    return "forward"


def _split_title_direction(title: str) -> tuple[str, str]:
    text = title.strip()
    match = _DIRECTION_SUFFIX.search(text)
    if match is None:
        return text or "channel", "forward"
    token = next((group for group in match.groups() if group), "forward")
    base = text[: match.start()].strip(" -_:()[]{}") or "channel"
    return base, _normalize_direction(token)


def _flatten_meta(meta_obj: Any) -> dict[str, str]:
    if meta_obj is None or not hasattr(meta_obj, "items"):
        return {}
    result: dict[str, str] = {}
    for key, value in meta_obj.items():
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        result[str(key)] = str(value)
    return result


def _normalized_meta(meta: Mapping[str, str]) -> dict[str, str]:
    return {re.sub(r"[^a-z0-9]+", "", key.lower()): value for key, value in meta.items()}


def _meta_value(meta: Mapping[str, str], *aliases: str) -> str | None:
    normalized = _normalized_meta(meta)
    for alias in aliases:
        key = re.sub(r"[^a-z0-9]+", "", alias.lower())
        if key in normalized:
            return normalized[key]
    return None


def _numbers(value: str | None) -> list[float]:
    if not value:
        return []
    return [
        float(token)
        for token in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value)
    ]


def _first_number(value: str | None) -> float | None:
    values = _numbers(value)
    return values[0] if values else None


def _find_sidecar_sxm(path: Path) -> Path | None:
    direct = path.with_suffix(".sxm")
    if direct.exists():
        return direct
    upper = path.with_suffix(".SXM")
    if upper.exists():
        return upper
    return None


def _channel_ids(container: Any) -> list[int]:
    ids: set[int] = set()
    for key in container.keys():
        match = re.fullmatch(r"/(\d+)/data", str(key))
        if match:
            ids.add(int(match.group(1)))
    return sorted(ids)


def read_gwy(path: str | Path, *, load_data: bool = True) -> SXMFile:
    """Read regular 2-D image channels from a Gwyddion ``.gwy`` file.

    The returned object intentionally uses the same lightweight internal representation
    as the SXM reader so the scientific pipeline can remain format-independent.

    Important: Gwyddion's Nanonis importer re-orients Forward/Backward and Up/Down data
    into display/physical orientation.  ``_ARRAY_ORIENTATION='display'`` records this so
    coordinate and timing reconstruction do not apply the SXM raw-storage flips again.

    If ``same_name.sxm`` exists beside the GWY file, its Nanonis acquisition metadata is
    used automatically for scan centre, angle and exact line timing.  This is preferred
    because a standard GWY saved by Gwyddion does not retain every Nanonis geometry field.
    """
    gwy_path = Path(path).expanduser().resolve()
    try:
        import gwyfile  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SPMError(
            "Reading .gwy files requires the 'gwyfile' package. Replace pyproject.toml "
            "with the patched version and run 'pip install -e .' in the virtual environment."
        ) from exc

    try:
        container = gwyfile.load(str(gwy_path))
    except Exception as exc:  # gwyfile exposes several low-level parser exceptions
        raise SPMError(f"Could not read GWY file {gwy_path.name}: {exc}") from exc

    ids = _channel_ids(container)
    if not ids:
        raise SPMError(f"{gwy_path.name}: no regular 2-D GwyDataField channels found")

    channels: dict[str, dict[str, np.ndarray]] = {}
    descriptors: list[ChannelDescriptor] = []
    representative = None
    representative_meta: dict[str, str] = {}
    channel_geometry: dict[str, dict[str, dict[str, float | int | str]]] = {}
    descriptor_index = 0

    for channel_id in ids:
        data_key = f"/{channel_id}/data"
        field = container[data_key]
        if representative is None:
            representative = field
            representative_meta = _flatten_meta(container.get(f"/{channel_id}/meta"))
        title = str(container.get(f"/{channel_id}/data/title", f"channel_{channel_id}"))
        base_name, direction = _split_title_direction(title)
        z_unit = _unit_string(getattr(field, "si_unit_z", None))
        data = np.asarray(field.data, dtype=float) if load_data else np.empty((0, 0), dtype=float)

        # Each GwyDataField owns its own resolution and physical extent.  This matters
        # after cropping/resizing in Gwyddion: one derived channel can legitimately be
        # 512x240 while other channels in the same container remain 512x512.
        field_xy_unit = _unit_string(getattr(field, "si_unit_xy", None)) or "m"
        field_scale_m = _length_scale_to_m(field_xy_unit)
        field_xres = int(field["xres"])
        field_yres = int(field["yres"])
        field_xreal_m = abs(float(getattr(field, "xreal", field.get("xreal", 1.0)))) * field_scale_m
        field_yreal_m = abs(float(getattr(field, "yreal", field.get("yreal", 1.0)))) * field_scale_m
        field_xoff_m = float(getattr(field, "xoff", field.get("xoff", 0.0))) * field_scale_m
        field_yoff_m = float(getattr(field, "yoff", field.get("yoff", 0.0))) * field_scale_m

        # Keep the stored GwyDataField values unchanged.  GWY masks are application
        # selections and their semantics are not guaranteed to mean invalid numerical data.

        final_name = base_name
        if direction in channels.get(final_name, {}):
            final_name = f"{base_name} [{channel_id}]"
        channels.setdefault(final_name, {})[direction] = data
        channel_geometry.setdefault(final_name, {})[direction] = {
            "nx": field_xres,
            "ny": field_yres,
            "width_m": field_xreal_m,
            "height_m": field_yreal_m,
            "xoff_m": field_xoff_m,
            "yoff_m": field_yoff_m,
            "xy_unit": field_xy_unit,
        }
        descriptors.append(
            ChannelDescriptor(
                index=descriptor_index,
                name=final_name,
                unit=z_unit,
                direction=direction,
            )
        )
        descriptor_index += 1

    assert representative is not None
    xres = int(representative["xres"])
    yres = int(representative["yres"])
    xy_unit = _unit_string(getattr(representative, "si_unit_xy", None)) or "m"
    scale_m = _length_scale_to_m(xy_unit)
    xreal_m = abs(float(getattr(representative, "xreal", representative.get("xreal", 1.0)))) * scale_m
    yreal_m = abs(float(getattr(representative, "yreal", representative.get("yreal", 1.0)))) * scale_m
    xoff_m = float(getattr(representative, "xoff", representative.get("xoff", 0.0))) * scale_m
    yoff_m = float(getattr(representative, "yoff", representative.get("yoff", 0.0))) * scale_m

    sidecar_path = _find_sidecar_sxm(gwy_path)
    sidecar = None
    if sidecar_path is not None:
        try:
            sidecar = read_sxm(sidecar_path, load_data=False)
        except Exception:
            sidecar = None

    header: dict[str, Any] = {}
    raw_header_text = ""
    sidecar_geometry_used = False
    if sidecar is not None:
        header.update(sidecar.header)
        raw_header_text = sidecar.raw_header_text
        raw_range = sidecar.header.get("SCAN_RANGE")
        if isinstance(raw_range, list) and len(raw_range) >= 2:
            try:
                sxm_x = abs(float(raw_range[0]))
                sxm_y = abs(float(raw_range[1]))
                size_match = (
                    abs(sxm_x - xreal_m) <= max(1e-15, 0.01 * sxm_x)
                    and abs(sxm_y - yreal_m) <= max(1e-15, 0.01 * sxm_y)
                )
            except (TypeError, ValueError):
                size_match = False
        else:
            size_match = False
        sidecar_geometry_used = bool(size_match)

    # Record geometry compatibility per individual channel.  A resized/cropped derived
    # channel may no longer match the sidecar even when another channel does.
    sidecar_range: tuple[float, float] | None = None
    if sidecar is not None:
        raw_range = sidecar.header.get("SCAN_RANGE")
        if isinstance(raw_range, list) and len(raw_range) >= 2:
            try:
                sidecar_range = (abs(float(raw_range[0])), abs(float(raw_range[1])))
            except (TypeError, ValueError):
                sidecar_range = None
    for direction_map in channel_geometry.values():
        for geometry in direction_map.values():
            compatible = False
            if sidecar_range is not None:
                sx, sy = sidecar_range
                gx = float(geometry["width_m"])
                gy = float(geometry["height_m"])
                compatible = (
                    abs(sx - gx) <= max(1e-15, 0.01 * sx)
                    and abs(sy - gy) <= max(1e-15, 0.01 * sy)
                )
            geometry["sidecar_geometry_compatible"] = int(compatible)

    # DataField dimensions are authoritative for the representative data field.
    header["SCAN_PIXELS"] = [xres, yres]
    header["SCAN_RANGE"] = [xreal_m, yreal_m]

    meta = representative_meta
    if not sidecar_geometry_used:
        # A standard Gwyddion file commonly stores xoff/yoff relative to its own image,
        # not the original Nanonis scanner offset.  Use them when available; otherwise the
        # scan is placed in a local 0..range coordinate system and marked reduced geometry.
        offset_value = _meta_value(meta, "SCAN_OFFSET", "Scan offset", "Offset")
        offsets = _numbers(offset_value)
        if len(offsets) >= 2:
            # Nanonis-style metadata are normally metres unless an explicit nm/µm suffix
            # is present.  Detect common suffixes conservatively.
            lower = (offset_value or "").lower()
            if "nm" in lower:
                factor = 1e-9
            elif "µm" in lower or "μm" in lower or "um" in lower:
                factor = 1e-6
            else:
                factor = 1.0
            header["SCAN_OFFSET"] = [offsets[0] * factor, offsets[1] * factor]
        else:
            header["SCAN_OFFSET"] = [xoff_m + 0.5 * xreal_m, yoff_m + 0.5 * yreal_m]

        angle = _first_number(_meta_value(meta, "SCAN_ANGLE", "Scan angle", "Rotation", "Angle"))
        header["SCAN_ANGLE"] = 0.0 if angle is None else angle

    if "SCAN_DIR" not in header:
        header["SCAN_DIR"] = (_meta_value(meta, "Direction", "SCAN_DIR", "Scan direction") or "up").strip().lower()

    if "REC_DATE" not in header:
        date = _meta_value(meta, "Date", "REC_DATE", "Recording date")
        if date:
            header["REC_DATE"] = date
    if "REC_TIME" not in header:
        time = _meta_value(meta, "Time", "REC_TIME", "Recording time")
        if time:
            header["REC_TIME"] = time
    if "BIAS" not in header:
        bias = _first_number(_meta_value(meta, "Bias", "BIAS"))
        if bias is not None:
            header["BIAS"] = bias

    # Gwyddion's Nanonis importer stores total acquisition time but not SCAN_TIME.  When
    # no sidecar provides exact line times, split a line cycle evenly between trace/retrace.
    if "SCAN_TIME" not in header:
        acquisition_s = _first_number(
            _meta_value(meta, "Acquistion time", "Acquisition time", "ACQ_TIME", "Duration")
        )
        if acquisition_s is not None and acquisition_s > 0:
            half_line = acquisition_s / max(2 * yres, 1)
            header["SCAN_TIME"] = [half_line, half_line]
            header["_GWY_TOTAL_ACQUISITION_S"] = acquisition_s

    header["_SOURCE_FORMAT"] = "gwy"
    header["_ARRAY_ORIENTATION"] = "display"
    header["_GWY_METADATA"] = dict(meta)
    header["_GWY_CHANNEL_GEOMETRY"] = channel_geometry
    header["_GWY_SIDECAR_SXM"] = str(sidecar_path) if sidecar_path else None
    header["_GWY_SIDECAR_GEOMETRY_USED"] = sidecar_geometry_used

    if not raw_header_text:
        raw_header_text = "\n".join(f"{key}: {value}" for key, value in meta.items())

    return SXMFile(
        path=gwy_path,
        header=header,
        raw_header_text=raw_header_text,
        channels=channels,
        channel_descriptors=descriptors,
    )


def discover_gwy_files(folder: str | Path, recursive: bool = True) -> list[Path]:
    base = Path(folder)
    patterns = ("**/*.gwy", "**/*.GWY") if recursive else ("*.gwy", "*.GWY")
    found: set[Path] = set()
    for pattern in patterns:
        found.update(path for path in base.glob(pattern) if path.is_file())
    return sorted(found)
