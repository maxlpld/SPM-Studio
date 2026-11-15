from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable

import numpy as np

from spm_multiframe.exceptions import SXMFormatError

_HEADER_END = b":SCANIT_END:"
_DATA_MARKER = b"\x1a\x04"


@dataclass(frozen=True)
class ChannelDescriptor:
    index: int
    name: str
    unit: str
    direction: str
    calibration: float | None = None
    offset: float | None = None


@dataclass
class SXMFile:
    path: Path
    header: dict[str, Any]
    raw_header_text: str
    channels: dict[str, dict[str, np.ndarray]]
    channel_descriptors: list[ChannelDescriptor]

    def channel_directions(self, name: str) -> tuple[str, ...]:
        if name not in self.channels:
            raise KeyError(name)
        return tuple(self.channels[name])

    def get_channel(self, name: str, direction: str = "forward") -> np.ndarray:
        directions = self.channels.get(name)
        if directions is None:
            raise KeyError(f"Channel {name!r} is not present in {self.path.name}")
        normalized = normalize_direction(direction)
        if normalized in directions:
            return directions[normalized]
        if len(directions) == 1:
            return next(iter(directions.values()))
        raise KeyError(
            f"Channel {name!r} does not contain direction {direction!r}; "
            f"available={tuple(directions)}"
        )


def normalize_direction(value: str) -> str:
    text = value.strip().lower()
    if text in {"forward", "fwd", "trace", "0"}:
        return "forward"
    if text in {"backward", "bwd", "retrace", "1"}:
        return "backward"
    if text in {"both", "forward/backward", "fwd/bwd"}:
        return "both"
    return text or "forward"


def _split_header_blocks(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    key: str | None = None
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip("\x00")
        stripped = line.strip()
        if stripped.startswith(":") and stripped.endswith(":") and len(stripped) >= 3:
            key = stripped.strip(":")
            blocks.setdefault(key, [])
            continue
        if key is not None and stripped:
            blocks[key].append(stripped)
    return blocks


def _tokens(lines: Iterable[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        result.extend(line.replace(";", " ").replace("\t", " ").split())
    return result


def _to_number(token: str) -> int | float | str:
    try:
        number = float(token)
    except ValueError:
        return token
    if number.is_integer() and not any(c in token.lower() for c in (".", "e")):
        return int(number)
    return number


def _parse_data_info(lines: list[str]) -> list[dict[str, Any]]:
    if not lines:
        return []

    def split_row(line: str) -> list[str]:
        if "\t" in line:
            return [part.strip() for part in line.split("\t") if part.strip()]
        if ";" in line:
            return [part.strip() for part in line.split(";") if part.strip()]
        return re.split(r"\s{2,}", line.strip())

    header = split_row(lines[0])
    if len(header) < 3:
        # Some exports collapse tabs to single spaces. These field names are stable enough
        # to recover the common six-column layout without touching the binary payload.
        header = ["Channel", "Name", "Unit", "Direction", "Calibration", "Offset"]

    rows: list[dict[str, Any]] = []
    for line in lines[1:]:
        values = split_row(line)
        if len(values) != len(header):
            # Fallback for simple whitespace separated rows. Channel names in Nanonis are
            # normally single tokens; if not, retaining the raw header still makes failure auditable.
            values = line.split()
        if len(values) < 4:
            continue
        if len(values) > len(header):
            values = values[: len(header)]
        row: dict[str, Any] = {}
        for key, value in zip(header, values, strict=False):
            row[key] = _to_number(value)
        rows.append(row)
    return rows


def _parse_header(text: str) -> dict[str, Any]:
    blocks = _split_header_blocks(text)
    parsed: dict[str, Any] = {}
    for key, lines in blocks.items():
        upper = key.upper()
        if upper == "DATA_INFO":
            parsed[upper] = _parse_data_info(lines)
            continue
        tokens = _tokens(lines)
        if not tokens:
            parsed[upper] = ""
        elif len(tokens) == 1:
            parsed[upper] = _to_number(tokens[0])
        else:
            converted = [_to_number(token) for token in tokens]
            parsed[upper] = converted
    parsed["_RAW_BLOCKS"] = blocks
    return parsed


def _get_case_insensitive(row: dict[str, Any], name: str, default: Any = None) -> Any:
    for key, value in row.items():
        if key.lower() == name.lower():
            return value
    return default


def _descriptors(header: dict[str, Any]) -> list[ChannelDescriptor]:
    rows = header.get("DATA_INFO", [])
    descriptors: list[ChannelDescriptor] = []
    for fallback_index, row in enumerate(rows):
        name = str(_get_case_insensitive(row, "Name", f"channel_{fallback_index}"))
        unit = str(_get_case_insensitive(row, "Unit", ""))
        direction = normalize_direction(str(_get_case_insensitive(row, "Direction", "forward")))
        index_raw = _get_case_insensitive(row, "Channel", fallback_index)
        try:
            index = int(index_raw)
        except (TypeError, ValueError):
            index = fallback_index
        cal_raw = _get_case_insensitive(row, "Calibration")
        off_raw = _get_case_insensitive(row, "Offset")
        try:
            calibration = None if cal_raw is None else float(cal_raw)
        except (TypeError, ValueError):
            calibration = None
        try:
            offset = None if off_raw is None else float(off_raw)
        except (TypeError, ValueError):
            offset = None
        descriptors.append(ChannelDescriptor(index, name, unit, direction, calibration, offset))
    return descriptors


def _scan_pixels(header: dict[str, Any]) -> tuple[int, int]:
    raw = header.get("SCAN_PIXELS")
    if raw is None:
        raise SXMFormatError("Missing :SCAN_PIXELS: in SXM header")
    if not isinstance(raw, list):
        raw = [raw]
    if len(raw) < 2:
        raise SXMFormatError(f"Invalid SCAN_PIXELS value: {raw!r}")
    try:
        nx, ny = int(raw[0]), int(raw[1])
    except (TypeError, ValueError) as exc:
        raise SXMFormatError(f"Invalid SCAN_PIXELS value: {raw!r}") from exc
    if nx <= 0 or ny <= 0:
        raise SXMFormatError(f"Non-positive scan dimensions: {nx} × {ny}")
    return nx, ny


def _array_layout(descriptors: list[ChannelDescriptor]) -> list[tuple[str, str]]:
    layout: list[tuple[str, str]] = []
    for descriptor in descriptors:
        if descriptor.direction == "both":
            layout.append((descriptor.name, "forward"))
            layout.append((descriptor.name, "backward"))
        elif descriptor.direction in {"forward", "backward"}:
            layout.append((descriptor.name, descriptor.direction))
        else:
            # Nanonis variants occasionally use an unrecognized direction label. Treat it
            # as one stored image but keep a deterministic internal direction.
            layout.append((descriptor.name, descriptor.direction or "forward"))
    return layout


def _locate_binary_offset(blob: bytes, header_end: int, expected_bytes: int) -> int:
    marker = blob.find(_DATA_MARKER, header_end)
    if marker < 0:
        raise SXMFormatError("Could not locate Nanonis binary data marker 0x1A04")

    base = marker + len(_DATA_MARKER)
    candidates = [base]
    if blob[base : base + 2] == b"\r\n":
        candidates.insert(0, base + 2)
    elif blob[base : base + 1] == b"\n":
        candidates.insert(0, base + 1)
    # Some third-party readers describe a four-byte separator. Keep this fallback, but
    # only select it when the expected payload size proves it is correct.
    candidates.extend([base + 2, base + 4])

    unique_candidates: list[int] = []
    for candidate in candidates:
        if candidate not in unique_candidates and candidate <= len(blob):
            unique_candidates.append(candidate)

    exact = [offset for offset in unique_candidates if len(blob) - offset == expected_bytes]
    if exact:
        return exact[0]

    viable = [offset for offset in unique_candidates if len(blob) - offset >= expected_bytes]
    if viable:
        return min(viable, key=lambda offset: (len(blob) - offset) - expected_bytes)
    raise SXMFormatError(
        "Binary payload is smaller than expected from DATA_INFO and SCAN_PIXELS "
        f"(expected {expected_bytes} bytes)"
    )


def read_sxm(path: str | Path, *, load_data: bool = True) -> SXMFile:
    """Read a Nanonis ``.sxm`` file into a stable package-level representation.

    The reader intentionally preserves the binary arrays in acquisition/storage order.
    Physical orientation is reconstructed later from scan direction, trace direction and
    scan angle; the reader never rotates or flips an image for display convenience.
    """
    sxm_path = Path(path)
    blob = sxm_path.read_bytes()
    end_pos = blob.find(_HEADER_END)
    if end_pos < 0:
        raise SXMFormatError(f"{sxm_path.name}: missing :SCANIT_END: marker")
    header_end = end_pos + len(_HEADER_END)
    raw_header = blob[:header_end].decode("utf-8", errors="replace")
    header = _parse_header(raw_header)
    descriptors = _descriptors(header)
    if not descriptors:
        raise SXMFormatError(f"{sxm_path.name}: DATA_INFO contains no readable channels")

    nx, ny = _scan_pixels(header)
    layout = _array_layout(descriptors)
    channels: dict[str, dict[str, np.ndarray]] = {}
    if load_data:
        expected_values = len(layout) * nx * ny
        offset = _locate_binary_offset(blob, header_end, expected_values * 4)
        payload = np.frombuffer(blob, dtype=">f4", count=expected_values, offset=offset)
        if payload.size != expected_values:
            raise SXMFormatError(
                f"{sxm_path.name}: expected {expected_values} float32 values, found {payload.size}"
            )
        images = payload.reshape(len(layout), ny, nx)
        for image, (name, direction) in zip(images, layout, strict=True):
            channels.setdefault(name, {})[direction] = np.asarray(image, dtype=np.float64)
    else:
        for name, direction in layout:
            channels.setdefault(name, {})[direction] = np.empty((0, 0), dtype=float)

    return SXMFile(
        path=sxm_path,
        header=header,
        raw_header_text=raw_header,
        channels=channels,
        channel_descriptors=descriptors,
    )


def discover_sxm_files(folder: str | Path, recursive: bool = True) -> list[Path]:
    base = Path(folder)
    pattern = "**/*.sxm" if recursive else "*.sxm"
    return sorted(path for path in base.glob(pattern) if path.is_file())
