"""SXM/GWY adapters. Nanonis trace/retrace acquisition order is spatially aligned."""
from __future__ import annotations
from pathlib import Path
import re
import threading
import numpy as np
from .models import Scan, Channel, Geometry

SUPPORTED = {'.sxm', '.gwy'}
_NANONIS_COMPAT_LOCK = threading.RLock()


def discover(folder: Path):
    """Yield file paths immediately; never decode full scans during indexing."""
    import os
    for root, dirs, files in os.walk(folder):
        dirs[:] = [x for x in dirs if not x.startswith('.') and x != 'selection']
        for name in sorted(files):
            if Path(name).suffix.lower() in SUPPORTED:
                yield Path(root) / name


def sxm_header(path: Path) -> dict[str, str]:
    """Header-only, bounded SXM metadata probe; no image arrays read."""
    with open(path, 'rb') as f:
        data = f.read(2 * 1024 * 1024)
    marker = b':SCANIT_END:'
    idx = data.find(marker)
    if idx < 0:
        raise ValueError('SXM header terminator missing in first 2 MiB')
    lines = data[:idx].decode('utf-8', errors='replace').replace('\r', '').split('\n')
    result = {}
    key, values = None, []
    for line in lines + [':SCANIT_END:']:
        if line.startswith(':') and line.endswith(':'):
            if key is not None:
                result[key] = '\n'.join(values).strip()
            key, values = line.strip(':'), []
        elif key is not None:
            values.append(line)
    return result


def _numbers(raw, count: int):
    if raw is None:
        return None
    try:
        vals = tuple(float(v) for v in re.split(r'[\s;,]+', str(raw).strip()) if v)
    except (ValueError, TypeError):
        return None
    return vals[:count] if len(vals) >= count else None


def _geometry(shape, meta, source='sxm'):
    if source == 'sxm':
        size = _numbers(meta.get('SCAN_RANGE') or meta.get('scan_range'), 2)
        center = _numbers(meta.get('SCAN_OFFSET') or meta.get('scan_offset'), 2)
        angle = _numbers(meta.get('SCAN_ANGLE') or meta.get('scan_angle'), 1)
        direction = meta.get('SCAN_DIR') or meta.get('scan_dir')
    else:
        size, center, angle, direction = meta.get('size_m'), meta.get('center_m'), meta.get('angle_deg'), None
    return Geometry(tuple(shape), tuple(size) if size else None, tuple(center) if center else None,
                    angle[0] if isinstance(angle, (tuple, list)) else angle, direction,
                    source_orientation=('Nanonis SXM aligned scan coordinates' if source == 'sxm' else 'GWY stored raster'),
                    verified_orientation=False)


def _read_sxm(path: Path) -> Scan:
    """Prefer the self-contained SXM decoder; legacy nanonispy is optional."""
    from .sxm_native import read_sxm_native, orient_nanonis_trace, SXMDecodeError
    try:
        decoded = read_sxm_native(path)
        geometry_meta = decoded.header
        channels = {}
        for name, traces in decoded.channels.items():
            shape = next(iter(traces.values())).shape
            channels[name] = Channel(name, decoded.units.get(name, ''), traces,
                                     _geometry(shape, geometry_meta))
        return Scan(path, channels, {'format':'SXM', 'reader':'native',
                    'header':_json_safe_header(decoded.header),
                    'raw_header':decoded.raw_header},
                    list(decoded.warnings) + [
                        'Nanonis SXM forward/backward traces aligned in scan XY coordinates (backward X acquisition reversed; up-scan Y acquisition reversed); no scan-angle rotation applied.'])
    except SXMDecodeError as primary_exc:
        # nanonispy remains an optional compatibility path for uncommon SXM variants.
        # Its original parser uses removed NumPy aliases. Proxy its *module-local*
        # np reference during decoding without modifying the real NumPy module.
        try:
            from nanonispy import read
        except ImportError:
            raise ValueError(f'Could not parse SXM {path.name}: {primary_exc}. '
                             'For an uncommon SXM dialect, install nanonispy or supply a sample to improve the reader.') from primary_exc

        class _LegacyNumPy:
            aliases = {'float':float, 'int':int, 'bool':bool, 'object':object}

            def __getattr__(self, name):
                if name in self.aliases:
                    return self.aliases[name]
                return getattr(np, name)

        with _NANONIS_COMPAT_LOCK:
            original_np = getattr(read, 'np', None)
            read.np = _LegacyNumPy()
            try:
                raw_scan = read.Scan(str(path))
            except Exception as exc:
                raise ValueError(f'Unable to read SXM {path.name}: native: {primary_exc}; '
                                 f'nanonispy: {type(exc).__name__}: {exc}') from exc
            finally:
                if original_np is None:
                    delattr(read, 'np')
                else:
                    read.np = original_np
        header = raw_scan.header
        manual = sxm_header(path)
        meta = dict(manual)
        for k in ('scan_range','scan_offset','scan_angle','scan_dir'):
            if header.get(k) is not None:
                meta[k] = header[k]
        info = header.get('data_info', {})
        names = list(info.get('Name', [])) if hasattr(info, 'get') else []
        units = list(info.get('Unit', [])) if hasattr(info, 'get') else []
        units_map = dict(zip(names, units))
        channels = {}
        for name, raw in raw_scan.signals.items():
            if not isinstance(raw, dict):
                continue
            scan_dir = meta.get('scan_dir') or meta.get('SCAN_DIR')
            traces = {direction: orient_nanonis_trace(a, direction, scan_dir)
                      for direction,a in raw.items()
                      if direction in ('forward', 'backward') and np.asarray(a).ndim == 2}
            if not traces:
                continue
            unit = units_map.get(name, '')
            if not unit:
                unit_match = re.search(r'\(([^()]+)\)\s*$', name)
                unit = unit_match.group(1) if unit_match else ''
            channels[name] = Channel(name, unit, traces,
                                     _geometry(next(iter(traces.values())).shape, meta))
        if not channels:
            raise ValueError(f'nanonispy found no 2-D channels in {path.name}')
        return Scan(path, channels, {'format':'SXM','reader':'nanonispy-compat',
                     'header':_json_safe_header(header),'raw_header':manual},
                    [f'Native SXM adapter could not decode this dialect ({primary_exc}); used nanonispy compatibility reader.',
                     'Nanonis SXM forward/backward acquisition order normalized to one XY orientation; no scan-angle rotation applied.'])


# GwyDataField's lateral coordinates are expressed in its declared XY units.
_LENGTH_SCALE_M = {'m':1.,'mm':1e-3,'um':1e-6,'µm':1e-6,'μm':1e-6,
                   'nm':1e-9,'pm':1e-12,'Å':1e-10,'angstrom':1e-10}
_TRACE_SUFFIX = re.compile(
    r'(?i)\s*(?:[\[(]\s*(forward|fwd|trace|backward|bwd|retrace)\s*[\])]|'
    r'[-_: ]+(forward|fwd|trace|backward|bwd|retrace))\s*$')


def _gwy_unit(unit_obj) -> str:
    if unit_obj is None:
        return ''
    raw = getattr(unit_obj,'unitstr',unit_obj)
    if isinstance(raw, bytes):
        return raw.decode('utf-8',errors='replace')
    return str(raw)


def _gwy_name_trace(name: str) -> tuple[str,str]:
    m = _TRACE_SUFFIX.search(name)
    if m:
        word = (m.group(1) or m.group(2)).lower()
        return name[:m.start()].strip() or name, ('backward' if word in ('backward','bwd','retrace') else 'forward')
    return name.strip(), 'forward'



def _gwy_extra_metadata(container) -> dict:
    """Preserve Gwyddion metadata/parameters, not embedded raster pixel payloads.

    GWY containers can include nested ``/N/meta`` dictionaries, field titles,
    palettes, and acquisition settings.  Keep those values by their original
    keys.  Pixel arrays and graphical objects are described, not copied.
    """
    from collections.abc import Mapping

    def text_value(value, depth=0):
        if depth > 32:
            return '<deep metadata object>'
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='replace')
        if isinstance(value, Mapping) or (hasattr(value, 'items') and callable(value.items)):
            return {str(k): text_value(v, depth + 1) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [text_value(v, depth + 1) for v in value]
        if isinstance(value, np.ndarray):
            return f'<data array, shape={tuple(value.shape)}, dtype={value.dtype}>'
        if hasattr(value, 'unitstr'):
            return text_value(value.unitstr, depth + 1)
        return f'<{type(value).__name__}>'

    if not hasattr(container, 'items'):
        return {}
    result = {}
    for key, value in container.items():
        name = str(key)
        # This is an image/volume payload, not a metadata parameter.
        if re.fullmatch(r'/\d+/data', name) or hasattr(value, 'data'):
            continue
        result[name] = text_value(value)
    return result


def _read_gwy(path: Path) -> Scan:
    try:
        import gwyfile
    except ImportError as exc:
        raise RuntimeError('GWY reader dependency is missing. From the project directory run '
                           'python -m pip install -e ".[all]"; then restart the program.') from exc
    try:
        container = gwyfile.load(str(path))
        # get_datafields() drops untitled fields and silently merges duplicate
        # titles in several gwyfile releases. Read numbered DataFields first.
        fields = []
        if hasattr(container, 'items'):
            for key, field in container.items():
                match = re.fullmatch(r'/(\d+)/data', str(key))
                if match and hasattr(field, 'data'):
                    index = match.group(1)
                    title = container.get(f'/{index}/data/title', f'Channel {index}')
                    fields.append((str(title), field))
        if not fields:
            fields = list(gwyfile.util.get_datafields(container).items())
    except Exception as exc:
        raise ValueError(f'Could not decode Gwyddion file {path.name}: {exc}') from exc
    channels = {}
    warnings = ['GWY stored rasters are not automatically flipped. Acquisition orientation '
                'and scan timing may be absent in an edited Gwyddion file.']
    field_meta = {}
    for original_name, field in fields:
        array = np.asarray(field.data)
        if array.ndim != 2 or array.size == 0:
            continue
        title = str(original_name).strip()
        name, trace = _gwy_name_trace(title)
        xy_unit = _gwy_unit(getattr(field,'si_unit_xy',None)) or 'm'
        xy_scale = _LENGTH_SCALE_M.get(xy_unit)
        if xy_scale is None:
            warnings.append(f'{title}: unrecognized XY unit {xy_unit!r}; physical dimensions disabled')
            size = None
        else:
            xr = getattr(field,'xreal',None)
            yr = getattr(field,'yreal',None)
            size = (float(xr)*xy_scale, float(yr)*xy_scale) if xr and yr else None
        xoff, yoff = getattr(field,'xoff',None), getattr(field,'yoff',None)
        unit = _gwy_unit(getattr(field,'si_unit_z',None))
        metadata_key = title if title not in field_meta else f'{title} (field {len(field_meta)})'
        field_meta[metadata_key] = {'shape':list(array.shape),'xreal':getattr(field,'xreal',None),
                             'yreal':getattr(field,'yreal',None), 'xoff':xoff,'yoff':yoff,
                             'xy_unit':xy_unit, 'unit':unit}
        geo = Geometry(array.shape, size_m=size, source_orientation='GWY stored array',
                       verified_orientation=False)
        if name in channels:
            old = channels[name]
            if (old.geometry.shape != geo.shape or old.geometry.size_m != geo.size_m
                or old.unit != unit or trace in old.traces):
                # Keep every field accessible rather than silently merging unlike grids.
                name = title
                if name in channels:
                    name = f'{title} [{len(channels)}]'
                warnings.append(f'{title}: kept as a separate channel (duplicate trace or mismatched geometry/units)')
            else:
                old.traces[trace] = np.asarray(array)
                old.traces[trace].setflags(write=False)
                continue
        channels[name] = Channel(name, unit, {trace:array}, geo)
    if not channels:
        raise ValueError(f'{path.name} contains no supported 2-D Gwyddion DataFields')
    return Scan(path,channels,{'format':'GWY','reader':'gwyfile','fields':field_meta,
                               'gwy_metadata':_gwy_extra_metadata(container)},warnings)


def read_scan(path: str | Path) -> Scan:
    """Read SXM/GWY in worker threads. Unsupported/invalid input fails explicitly."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    ext = path.suffix.lower()
    if ext == '.sxm':
        return _read_sxm(path)
    if ext == '.gwy':
        return _read_gwy(path)
    raise ValueError('Supported scan formats: .sxm and .gwy only')


def _json_safe_header(header):
    result = {}
    for k, v in header.items():
        if isinstance(v, np.ndarray):
            result[str(k)] = v.tolist()
        elif isinstance(v, (str, int, float, bool, type(None))):
            result[str(k)] = v
        elif isinstance(v, (tuple, list)):
            result[str(k)] = [str(x) for x in v]
        else:
            result[str(k)] = str(v)
    return result
