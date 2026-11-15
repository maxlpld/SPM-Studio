"""Conservative Nanonis SXM decoder, independent of obsolete NumPy aliases.

Nanonis acquisition order is normalized to the same spatial raster for trace
and retrace. The original binary remains untouched; zero-copy views are used.
No rotation of the scan pixels is performed. Never used for hardware I/O.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import numpy as np

HEADER_END = b':SCANIT_END:'
BINARY_START = b'\x1a\x04'
MAX_HEADER = 2 * 1024 * 1024
MAX_PIXELS = 200_000_000


class SXMDecodeError(ValueError):
    """File is not an SXM scan with a safely identifiable raster layout."""


@dataclass
class SXMDecoded:
    channels: dict[str, dict[str, np.ndarray]]
    units: dict[str, str]
    header: dict[str, object]
    raw_header: str
    warnings: list[str]


def header_blocks(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    key: str | None = None
    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        stripped = line.strip().strip('\x00')
        if re.fullmatch(r':[^:\n]+:', stripped):
            key = stripped[1:-1].upper()
            blocks.setdefault(key, [])
        elif key is not None and stripped:
            blocks[key].append(line.strip())
    return blocks


def _row_values(line: str) -> list[str]:
    if '\t' in line:
        return [x.strip() for x in line.split('\t') if x.strip()]
    if ';' in line:
        return [x.strip() for x in line.split(';') if x.strip()]
    return [x.strip() for x in re.split(r'\s{2,}', line.strip()) if x.strip()]


def channel_table(rows: list[str]) -> list[tuple[str, str, str]]:
    """(name, unit, direction), strictly from DATA_INFO, not fabricated names."""
    if len(rows) < 2:
        raise SXMDecodeError('Missing/empty DATA_INFO channel table')
    columns = _row_values(rows[0])
    if len(columns) < 3:
        columns = re.split(r'\s+', rows[0].strip())
    lower = [x.casefold() for x in columns]
    if 'name' not in lower or 'direction' not in lower:
        raise SXMDecodeError('DATA_INFO must identify Name and Direction columns')
    ni = lower.index('name')
    di = lower.index('direction')
    ui = lower.index('unit') if 'unit' in lower else -1
    result = []
    for line in rows[1:]:
        cells = _row_values(line)
        if len(cells) != len(columns):
            cells = line.split()
        if len(cells) <= max(ni, di):
            raise SXMDecodeError(f'Cannot parse DATA_INFO row: {line!r}')
        name = cells[ni].strip()
        if not name:
            raise SXMDecodeError('Unnamed DATA_INFO channel')
        unit = cells[ui] if 0 <= ui < len(cells) else ''
        raw = cells[di].strip().lower()
        directions = {'both':'both','b':'both','f':'forward','forward':'forward',
                      'fwd':'forward','trace':'forward','backward':'backward',
                      'bwd':'backward','retrace':'backward'}
        if raw not in directions:
            raise SXMDecodeError(f'Unknown direction {raw!r} for channel {name!r}')
        result.append((name, unit, directions[raw]))
    if not result:
        raise SXMDecodeError('No channels in DATA_INFO')
    return result


def orient_nanonis_trace(array: np.ndarray, trace: str, scan_dir: str | None) -> np.ndarray:
    """Return an aligned top-left-origin view of Nanonis acquisition data.

    Nanonis stores backward lines in *acquisition* order, so the first point
    is on the opposite side of the physical frame. Likewise SCAN_DIR=up
    starts at the bottom. Negating neither the scan angle nor coordinate axes,
    these reversals simply map both traces to the same XY raster.

    Views are non-copying even for large float32 memmaps, and preserve NaNs.
    SXM contains no promise that a GWY file uses this layout; do NOT call on
    already processed Gwyddion fields.
    """
    aligned = array if isinstance(array, np.ndarray) else np.asarray(array)
    if aligned.ndim != 2:
        raise ValueError('Nanonis SXM trace must be 2-D')
    if str(scan_dir or '').strip().casefold() == 'up':
        aligned = aligned[::-1, :]
    if trace == 'backward':
        aligned = aligned[:, ::-1]
    return aligned


def read_sxm_native(path: str | Path) -> SXMDecoded:
    p = Path(path)
    with p.open('rb') as f:
        prefix = f.read(MAX_HEADER)
        end = prefix.find(HEADER_END)
        if end < 0:
            raise SXMDecodeError('Missing :SCANIT_END: within 2 MiB header limit')
        header_text = prefix[:end + len(HEADER_END)].decode('latin-1')
        blocks = header_blocks(header_text)
        px = ' '.join(blocks.get('SCAN_PIXELS', [])).split()
        if len(px) < 2:
            raise SXMDecodeError('Missing SCAN_PIXELS X Y')
        try:
            nx, ny = int(px[0]), int(px[1])
        except ValueError as exc:
            raise SXMDecodeError('Non-numeric SCAN_PIXELS') from exc
        if nx < 1 or ny < 1 or nx * ny > MAX_PIXELS:
            raise SXMDecodeError(f'Invalid or excessive image dimensions {nx} x {ny}')
        layout = []
        units: dict[str, str] = {}
        for name, unit, direction in channel_table(blocks.get('DATA_INFO', [])):
            if name in units and units[name] != unit:
                raise SXMDecodeError(f'Inconsistent units for channel {name!r}')
            units[name] = unit
            for trace in ('forward', 'backward') if direction == 'both' else (direction,):
                if (name, trace) in layout:
                    raise SXMDecodeError(f'Duplicate image {name!r}/{trace}')
                layout.append((name, trace))
        data_type = ' '.join(blocks.get('SCANIT_TYPE', ['FLOAT MSBFIRST'])).upper()
        if 'FLOAT' not in data_type:
            raise SXMDecodeError(f'Unsupported SXM pixel type: {data_type!r}')
        dtype = '<f4' if 'LSBFIRST' in data_type or 'LITTLE' in data_type else '>f4'
        # The standard Nanonis binary marker follows the header (often CRLF); 
        # refuse to locate a marker arbitrarily deep inside the image payload.
        f.seek(end + len(HEADER_END))
        separator = f.read(12)
        marker_pos = separator.find(BINARY_START)
        if marker_pos < 0 or any(ch not in b'\r\n\x00 ' for ch in separator[:marker_pos]):
            raise SXMDecodeError('Missing 0x1A04 binary separator immediately after header')
        start = end + len(HEADER_END) + marker_pos + 2
        f.seek(start)
        # If a separator newline follows the marker, it is not image data.
        peek = f.read(2)
        if peek == b'\r\n':
            start += 2
        elif peek[:1] == b'\n':
            start += 1
        f.seek(0, 2)
        available = f.tell() - start
        expected = len(layout) * nx * ny * 4
        warnings = []
        if available < expected:
            # Incomplete images are represented with NaN pixels, never fictitious zeros.
            warnings.append(f'Incomplete SXM payload: {available} of {expected} bytes; missing pixels masked as NaN')
        elif available > expected:
            # Avoid silently shifting a raster to consume an unknown tail.
            warnings.append(f'{available - expected} trailing bytes beyond expected SXM raster were ignored')
        # Do not decode and upcast *every* channel during Open. A typical Nanonis
        # scan contains many large 32-bit rasters. Mapping the original file is
        # almost instant and only faults in the chosen preview channel on demand.
        # The file stays unchanged; arrays are strictly read-only.
        pixels_per_trace = nx * ny
        channels: dict[str, dict[str, np.ndarray]] = {}
        scan_dir = ' '.join(blocks.get('SCAN_DIR', [])).strip().casefold()
        if scan_dir and scan_dir not in ('up', 'down'):
            warnings.append(f'Unrecognized SCAN_DIR {scan_dir!r}; vertical image order left unchanged')
        if available < 4:
            raise SXMDecodeError('SXM contains no complete float32 values')
        for index, (name, trace) in enumerate(layout):
            trace_start = index * pixels_per_trace * 4
            n_values = min(pixels_per_trace, max(0, available - trace_start) // 4)
            if n_values == pixels_per_trace:
                image = np.memmap(p, dtype=dtype, mode='r',
                                  offset=start + trace_start, shape=(ny, nx))
            else:
                # Only a physically incomplete trace requires allocating an array.
                image = np.full((ny, nx), np.nan, dtype=np.float32)
                if n_values:
                    partial = np.memmap(p, dtype=dtype, mode='r',
                                        offset=start + trace_start, shape=(n_values,))
                    image.flat[:n_values] = partial
                image.setflags(write=False)
            channels.setdefault(name, {})[trace] = orient_nanonis_trace(image, trace, scan_dir)
    info: dict[str, object] = {key: '\n'.join(lines) for key, lines in blocks.items()}
    info['scan_pixels'] = [nx, ny]
    return SXMDecoded(channels, units, info, header_text, warnings)
