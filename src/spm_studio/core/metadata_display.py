"""Read-only formatting of complete scan metadata for the browser sidebar.

The source SXM header is kept unmodified and accessible in its own view.  The
formatted view does not calculate from or read the image arrays; channel shapes
come from Geometry.  No arbitrary line/field limit is applied to metadata.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
import json


def _value_text(value) -> str:
    if value is None:
        return 'None'
    if isinstance(value, (bool, int, float)):
        return str(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, (list, tuple)):
        return ', '.join(_value_text(v) for v in value)
    return str(value)


def _append_metadata(lines: list[str], key: str, value, indent: int = 0):
    prefix = '  ' * indent
    if isinstance(value, Mapping):
        lines.append(f'{prefix}{key}:')
        if not value:
            lines.append(f'{prefix}  (empty)')
        for name, child in value.items():
            _append_metadata(lines, str(name), child, indent + 1)
        return
    content = _value_text(value).replace('\r\n', '\n').replace('\r', '\n')
    if '\n' in content:
        lines.append(f'{prefix}{key}:')
        lines.extend(f'{prefix}  {line}' for line in content.split('\n'))
    else:
        lines.append(f'{prefix}{key}: {content}')


def original_header(scan) -> str:
    """Exactly the SXM source header when available, without interpretation."""
    raw = scan.metadata.get('raw_header')
    if isinstance(raw, str) and raw:
        return raw
    return 'No original plain-text instrument header is available for this file.\n\n' \
           'Use Parameters or JSON to inspect all metadata exposed by the file reader.'


def metadata_json(scan) -> str:
    """All reader metadata as human-readable JSON; non-JSON scalar values stringify."""
    return json.dumps(scan.metadata, ensure_ascii=False, indent=2, default=str)


def metadata_text(scan) -> str:
    """Show every recorded parameter plus a helpful channel and geometry index."""
    meta = scan.metadata
    sections = ['SCAN FILE', '---------', f'Name: {scan.path.name}',
                f'Path: {scan.path}', f'Format: {meta.get("format", scan.path.suffix.upper().lstrip("."))}',
                f'Reader: {meta.get("reader", "unknown")}', f'Number of channels: {len(scan.channels)}']
    try:
        sections.append(f'File size: {Path(scan.path).stat().st_size:,} bytes')
    except OSError:
        pass
    sections.extend(['', 'CHANNELS AND GEOMETRY', '---------------------'])
    for index, (name, channel) in enumerate(scan.channels.items(), 1):
        geometry = channel.geometry
        sections.extend([f'{index}. {name}', f'   Unit: {channel.unit or "(unspecified)"}',
                         f'   Traces: {", ".join(channel.traces)}',
                         f'   Resolution (rows × columns): {geometry.shape[0]} × {geometry.shape[1]}'])
        if geometry.size_m:
            sections.append(f'   Physical width × height: {geometry.size_m[0]:.12g} × {geometry.size_m[1]:.12g} m')
            sections.append(f'   Physical width × height: {geometry.size_m[0]*1e9:.12g} × {geometry.size_m[1]*1e9:.12g} nm')
        if geometry.center_m:
            sections.append(f'   Scan center (m): {geometry.center_m[0]:.12g}, {geometry.center_m[1]:.12g}')
        if geometry.angle_deg is not None:
            sections.append(f'   Scan angle: {geometry.angle_deg:.12g}°')
        if geometry.scan_direction:
            sections.append(f'   Scan direction: {geometry.scan_direction}')
        sections.append(f'   Stored orientation: {geometry.source_orientation}')
    header = meta.get('header')
    if isinstance(header, Mapping) and header:
        sections.extend(['', 'INSTRUMENT ACQUISITION PARAMETERS', '---------------------------------'])
        for key, value in header.items():
            _append_metadata(sections, str(key), value)
    for key, value in meta.items():
        if key in ('header', 'raw_header', 'format', 'reader'):
            continue
        sections.extend(['', f'{str(key).upper()}', '-' * min(len(str(key)), 48)])
        if isinstance(value, Mapping):
            for name, child in value.items():
                _append_metadata(sections, str(name), child)
        else:
            _append_metadata(sections, str(key), value)
    if scan.warnings:
        sections.extend(['', 'READER WARNINGS', '---------------'])
        sections.extend(f'• {message}' for message in scan.warnings)
    if isinstance(meta.get('raw_header'), str) and meta['raw_header']:
        sections.extend(['', 'Original SXM header is available in the “Original header” view.'])
    return '\n'.join(sections) + '\n'
