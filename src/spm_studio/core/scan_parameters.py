"""Acquisition parameters of a scan, read from its header (Qt-free).

Used by the export (a box of parameters in a corner of each image) and by the Multipass
profile. Every value comes from the file's own metadata; nothing is guessed.

* general parameters: bias, feedback setpoint, Z-controller, scan time per line, size, pixels, date;
* **Nanonis Multipass**: the ``Multipass-Config`` table of the SXM header (one row per pass:
  record channel, playback, playback offset, BOL / EOL delays, Z offset, setpoint action,
  setpoint, bias override, bias, time-per-line override, time per line, speed ratio …),
  and the pass tags ``[P1]``, ``[P2]`` … of the channel names.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

PASS_TAG = re.compile(r'\[\s*P\s*(\d+)\s*\]|(?:^|[\s_(])P(\d+)(?=$|[\s_)\]])', re.I)


@dataclass(frozen=True)
class Parameter:
    key: str            # stable id, e.g. 'bias', 'p2.z_offset'
    label: str          # 'Bias', 'Δz'
    value: str          # formatted with unit, e.g. '−1.20 V'
    group: str = 'Scan'  # 'Scan' or 'P1', 'P2', …
    raw: object = None

    def line(self) -> str:
        return f'{self.label} = {self.value}'


# ------------------------------------------------------------------------ formatting
_PREFIX = [(1e-15, 'f'), (1e-12, 'p'), (1e-9, 'n'), (1e-6, 'µ'), (1e-3, 'm'), (1.0, ''), (1e3, 'k'), (1e6, 'M'),
           (1e9, 'G')]


def format_quantity(value, unit: str = '', digits: int = 3) -> str:
    """``-1.2, 'V'`` → ``−1.2 V``; ``5e-11, 'A'`` → ``50 pA``; ``-3e-10, 'm'`` → ``−300 pm``."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(v):
        return str(value)
    unit = (unit or '').strip()
    if unit in ('m', 'A', 'V', 's', 'Hz', 'N', 'S', 'F', 'W') and v != 0:
        magnitude = abs(v)
        factor, prefix = 1.0, ''
        for f, p in _PREFIX:
            if magnitude >= f * 0.9995:
                factor, prefix = f, p
        if unit == 'V' and factor < 1e-3:
            factor, prefix = 1e-3, 'm'
        if unit == 's' and factor > 1:
            factor, prefix = 1.0, ''
        text = f'{v / factor:.{digits}g}'
        unit = prefix + unit
    else:
        text = f'{v:.{digits}g}'
    text = text.replace('-', '−')
    return f'{text} {unit}'.strip()


def _number(text):
    if text is None:
        return None
    m = re.search(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', str(text))
    return float(m.group(0)) if m else None


def _unit_of(name: str) -> str:
    m = re.search(r'\(([^()]*)\)\s*$', name or '')
    return m.group(1).strip() if m else ''


def _bool(text) -> bool | None:
    t = str(text or '').strip().upper()
    if t in ('TRUE', 'ON', '1', 'YES'):
        return True
    if t in ('FALSE', 'OFF', '0', 'NO'):
        return False
    return None


# ------------------------------------------------------------------------ header access
def header(scan) -> dict:
    """The reader's header as ``{UPPER KEY: text}`` (native SXM and nanonispy dialects)."""
    meta = getattr(scan, 'metadata', {}) or {}
    h = meta.get('header') or {}
    out = {}
    if isinstance(h, dict):
        for k, v in h.items():
            if isinstance(v, (list, tuple)):
                v = '\n'.join(map(str, v))
            out[str(k).strip(':').upper()] = '' if v is None else str(v)
    raw = meta.get('raw_header')
    if isinstance(raw, str) and raw and not out:
        key = None
        for line in raw.replace('\r', '').split('\n'):
            s = line.strip()
            if re.fullmatch(r':[^:\n]+:', s):
                key = s[1:-1].upper()
                out.setdefault(key, '')
            elif key is not None and s:
                out[key] = (out[key] + '\n' + s).strip('\n')
    return out


def _find(h: dict, *names: str):
    for name in names:
        value = h.get(name.upper())
        if value not in (None, ''):
            return value
    return None


def _rows(text: str) -> list[list[str]]:
    rows = []
    for line in str(text or '').replace('\r', '').split('\n'):
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split('\t')] if '\t' in line else re.split(r'\s{2,}', line.strip())
        while cells and cells[0] == '':
            cells.pop(0)
        rows.append(cells)
    return rows


# ------------------------------------------------------------------------ Multipass
MULTIPASS_COLUMNS = (
    # (pattern in the Nanonis column name, key, label)
    (r'^record', 'record_channel', 'Record channel'),
    (r'^playback$', 'playback', 'Playback'),
    (r'^playback.?offset', 'playback_offset', 'Playback offset'),
    (r'^bol', 'bol_delay', 'BOL delay'),
    (r'^eol', 'eol_delay', 'EOL delay'),
    (r'^z.?offset', 'z_offset', 'Δz'),
    (r'^setpoint action', 'setpoint_action', 'Setpoint change'),
    (r'^setpoint(?!\s*action)', 'setpoint', 'Setpoint'),
    (r'^bias override', 'bias_override', 'Bias override'),
    (r'^bias', 'bias', 'Bias'),
    (r'^time.?per.?line override', 'time_override', 'Time-per-line override'),
    (r'^time.?per.?line', 'time_per_line', 'Time per line'),
    (r'^speed', 'speed_ratio', 'Speed ratio'),
    (r'^lock.?in', 'lockin', 'Lock-in'),
)


def _column_key(name: str):
    clean = re.sub(r'[\s_\-]+', ' ', re.sub(r'[\[(][^\])]*[\])]', '', name)).strip().lower()
    for pattern, key, label in MULTIPASS_COLUMNS:
        if re.search(pattern, clean):
            return key, label
    return re.sub(r'[^a-z0-9]+', '_', clean).strip('_') or 'value', name.strip()


def multipass_table(scan) -> list[dict]:
    """One dict per pass ``{'pass': 1, 'bias': (-1.0, 'V'), 'z_offset': (-3e-10, 'm'), …}``.

    Values are ``(raw, unit)``; booleans stay booleans. Empty list when the scan has no
    Multipass configuration in its header.
    """
    h = header(scan)
    key = next((k for k in h if 'MULTIPASS' in k and ('CONFIG' in k or k == 'MULTIPASS')), None)
    passes = []
    if key:
        rows = _rows(h[key])
        if len(rows) >= 2:
            columns = rows[0]
            for n, row in enumerate(rows[1:], 1):
                if len(row) < 2:
                    continue
                item = {'pass': n}
                for name, cell in zip(columns, row):
                    k, _label = _column_key(name)
                    flag = _bool(cell)
                    if flag is not None and not re.search(r'-?\d', cell.replace('1', '').replace('0', '')) \
                            and k not in ('record_channel',):
                        item[k] = flag
                        continue
                    number = _number(cell)
                    unit = _unit_of(name)
                    if k in ('z_offset', 'playback_offset') and not unit:
                        unit = 'm'
                    if k == 'bias' and not unit:
                        unit = 'V'
                    if k == 'time_per_line' and not unit:
                        unit = 's'
                    item[k] = (number, unit) if number is not None and k != 'record_channel' else cell
                passes.append(item)
    # key/value dialect: ":Multipass>P2>Bias (V):"
    if not passes:
        by_pass = {}
        for k, v in h.items():
            m = re.match(r'MULTI-?PASS\S*>\s*(?:PASS\s*|P)(\d+)\s*>\s*(.+)$', k)
            if m:
                n = int(m.group(1))
                name = m.group(2)
                ck, _label = _column_key(name.title())
                flag = _bool(v)
                number = _number(v)
                by_pass.setdefault(n, {'pass': n})[ck] = flag if flag is not None and number is None else \
                    ((number, _unit_of(name)) if number is not None else v)
        passes = [by_pass[n] for n in sorted(by_pass)]
    return passes


def pass_of_channel(name: str) -> int | None:
    """``'Z [P2]'`` → 2 (also ``'[P2]_Z'``, ``'Z_P2'``); ``None`` for an ordinary channel."""
    m = PASS_TAG.search(str(name or ''))
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def channel_base(name: str) -> str:
    """Channel name without its pass tag: ``'OC M1 Freq. Shift [P2]'`` → ``'OC M1 Freq. Shift'``."""
    return re.sub(r'\s{2,}', ' ', PASS_TAG.sub(' ', str(name or ''))).strip(' _-')


def is_multipass(scan) -> bool:
    if multipass_table(scan):
        return True
    return any(pass_of_channel(name) for name in getattr(scan, 'channels', {}) or {})


def passes_in_scan(scan) -> list[int]:
    found = {pass_of_channel(n) for n in getattr(scan, 'channels', {}) or {}}
    found.discard(None)
    found |= {p['pass'] for p in multipass_table(scan)}
    return sorted(found)


# ------------------------------------------------------------------------ parameters
def _general(scan, h) -> list[Parameter]:
    out = []
    bias = _number(_find(h, 'BIAS>BIAS (V)', 'BIAS'))
    if bias is not None:
        out.append(Parameter('bias', 'Bias', format_quantity(bias, 'V'), 'Scan', bias))
    # Z-controller: key/value dialect first, then the table dialect.
    setpoint = _number(_find(h, 'Z-CONTROLLER>SETPOINT'))
    setpoint_unit = (_find(h, 'Z-CONTROLLER>SETPOINT UNIT') or '').strip()
    controller = (_find(h, 'Z-CONTROLLER>CONTROLLER NAME') or '').strip()
    feedback = _find(h, 'Z-CONTROLLER>CONTROLLER STATUS')
    table = _find(h, 'Z-CONTROLLER')
    if table and setpoint is None:
        rows = _rows(table)
        if len(rows) >= 2:
            cols = [c.lower() for c in rows[0]]
            row = rows[1]
            def cell(name):
                return row[cols.index(name)] if name in cols and cols.index(name) < len(row) else None
            controller = controller or (cell('name') or '')
            raw = cell('setpoint')
            setpoint = _number(raw)
            if raw and not setpoint_unit:
                m = re.search(r'[-+0-9.eE]+\s*([A-Za-zµ]+)\s*$', raw)
                setpoint_unit = m.group(1) if m else ''
            if feedback is None:
                feedback = cell('on')
    if setpoint is not None:
        unit = setpoint_unit or ('A' if 'current' in controller.lower() else 'Hz' if 'freq' in controller.lower() else '')
        label = 'I' if unit == 'A' else 'Δf' if unit == 'Hz' else 'Setpoint'
        out.append(Parameter('setpoint', label, format_quantity(setpoint, unit), 'Scan', setpoint))
    if controller:
        out.append(Parameter('controller', 'Feedback on', controller, 'Scan', controller))
    if feedback is not None:
        state = _bool(feedback)
        if state is not None:
            out.append(Parameter('feedback', 'Feedback', 'on' if state else 'off (constant height)', 'Scan', state))
    current = _number(_find(h, 'CURRENT>CURRENT (A)'))
    if current is not None:
        out.append(Parameter('current', 'Current', format_quantity(current, 'A'), 'Scan', current))
    scan_time = _find(h, 'SCAN_TIME')
    if scan_time:
        values = [float(x) for x in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', scan_time)]
        if values:
            out.append(Parameter('time_per_line', 'Time per line', format_quantity(values[0], 's'), 'Scan', values[0]))
    size = _find(h, 'SCAN_RANGE')
    if size:
        values = [float(x) for x in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', size)][:2]
        if len(values) == 2:
            out.append(Parameter('size', 'Size', f'{format_quantity(values[0], "m")} × {format_quantity(values[1], "m")}',
                                 'Scan', tuple(values)))
    pixels = _find(h, 'SCAN_PIXELS')
    if pixels:
        values = re.findall(r'\d+', pixels)[:2]
        if len(values) == 2:
            out.append(Parameter('pixels', 'Pixels', f'{values[0]} × {values[1]}', 'Scan', tuple(map(int, values))))
    angle = _number(_find(h, 'SCAN_ANGLE'))
    if angle:
        out.append(Parameter('angle', 'Angle', f'{angle:g}°', 'Scan', angle))
    date = (_find(h, 'REC_DATE') or '').strip()
    clock = (_find(h, 'REC_TIME') or '').strip()
    if date:
        out.append(Parameter('date', 'Date', f'{date} {clock}'.strip(), 'Scan', date))
    temperature = _number(_find(h, 'TEMPERATURE', 'TEMPERATURE 1>TEMPERATURE 1 (K)'))
    if temperature is not None:
        out.append(Parameter('temperature', 'T', f'{temperature:.3g} K', 'Scan', temperature))
    amplitude = _number(_find(h, 'OSCILLATION CONTROL>AMPLITUDE SETPOINT (M)'))
    if amplitude is not None:
        out.append(Parameter('amplitude', 'A', format_quantity(amplitude, 'm'), 'Scan', amplitude))
    return out


def _multipass(scan, general) -> list[Parameter]:
    out = []
    bias = next((p.raw for p in general if p.key == 'bias'), None)
    setpoint = next((p for p in general if p.key == 'setpoint'), None)
    for item in multipass_table(scan):
        n = item['pass']
        group = f'P{n}'

        def add(key, label, value):
            out.append(Parameter(f'p{n}.{key}', label, value, group, item.get(key)))
        value = item.get('bias')
        if isinstance(value, tuple) and value[0] is not None:
            overridden = item.get('bias_override')
            if overridden is False and bias is not None:
                add('bias', 'Bias', format_quantity(bias, 'V'))
            else:
                add('bias', 'Bias', format_quantity(value[0], value[1] or 'V'))
        elif bias is not None:
            add('bias', 'Bias', format_quantity(bias, 'V'))
        value = item.get('setpoint')
        if isinstance(value, tuple) and value[0] is not None:
            if item.get('setpoint_action') is False and setpoint is not None:
                add('setpoint', setpoint.label, setpoint.value)
            else:
                unit = value[1] or {'I': 'A', 'Δf': 'Hz'}.get(setpoint.label if setpoint else '', '')
                add('setpoint', setpoint.label if setpoint else 'Setpoint', format_quantity(value[0], unit))
        elif setpoint is not None:
            add('setpoint', setpoint.label, setpoint.value)
        value = item.get('z_offset')
        if isinstance(value, tuple) and value[0] is not None:
            add('z_offset', 'Δz', format_quantity(value[0], value[1] or 'm'))
        if 'playback' in item:
            add('playback', 'Playback', 'on' if item['playback'] is True else 'off' if item['playback'] is False
                else str(item['playback']))
        value = item.get('playback_offset')
        if isinstance(value, tuple) and value[0] is not None:
            add('playback_offset', 'Playback offset', format_quantity(value[0], value[1] or 'm'))
        value = item.get('time_per_line')
        if isinstance(value, tuple) and value[0] is not None and item.get('time_override') is not False:
            add('time_per_line', 'Time per line', format_quantity(value[0], value[1] or 's'))
        value = item.get('speed_ratio')
        if isinstance(value, tuple) and value[0] is not None:
            add('speed_ratio', 'Speed ratio', f'{value[0]:g}')
        for key, label in (('bol_delay', 'BOL delay'), ('eol_delay', 'EOL delay')):
            value = item.get(key)
            if isinstance(value, tuple) and value[0] is not None:
                add(key, label, f'{value[0]:g} cycles')
        if 'record_channel' in item:
            add('record_channel', 'Record channel', str(item['record_channel']))
        if 'lockin' in item:
            add('lockin', 'Lock-in', 'on' if item['lockin'] is True else 'off' if item['lockin'] is False
                else str(item['lockin']))
        for k, v in item.items():
            if k in ('pass',) or any(p.key == f'p{n}.{k}' for p in out) or k in (
                    'bias_override', 'setpoint_action', 'time_override'):
                continue
            if isinstance(v, tuple) and v[0] is not None:
                add(k, k.replace('_', ' ').capitalize(), format_quantity(v[0], v[1]))
    return out


def parameters(scan) -> list[Parameter]:
    """Every parameter that can be shown on the exported image (general, then per pass)."""
    h = header(scan)
    general = _general(scan, h)
    return general + _multipass(scan, general)


DEFAULT_KEYS = ('bias', 'setpoint')
DEFAULT_PASS_KEYS = ('bias', 'setpoint', 'z_offset')


def default_selection(scan, channel: str = '') -> list[str]:
    """What the parameter box shows unless the user chooses: bias + setpoint, and for a pass
    channel that pass's bias, setpoint and Δz."""
    available = {p.key for p in parameters(scan)}
    n = pass_of_channel(channel)
    if n is not None and any(k.startswith(f'p{n}.') for k in available):
        return [f'p{n}.{k}' for k in DEFAULT_PASS_KEYS if f'p{n}.{k}' in available]
    return [k for k in DEFAULT_KEYS if k in available]


def resolve_keys(keys, channel: str = '') -> list[str]:
    """``'pass.bias'`` means "the bias of the pass this channel was recorded in"."""
    n = pass_of_channel(channel)
    out = []
    for key in keys:
        if key.startswith('pass.'):
            if n is None:
                key = key[5:]
            else:
                key = f'p{n}.{key[5:]}'
        if key not in out:
            out.append(key)
    return out


def lines_for(scan, keys, channel: str = '', *, with_pass_prefix: bool | None = None) -> list[str]:
    """Text lines of the box, in the chosen order (``Bias = −1.2 V``; ``P2 · Δz = −300 pm``)."""
    by_key = {p.key: p for p in parameters(scan)}
    chosen = [by_key[k] for k in resolve_keys(keys, channel) if k in by_key]
    groups = {p.group for p in chosen}
    prefix = (len(groups - {'Scan'}) > 1) if with_pass_prefix is None else with_pass_prefix
    return [(f'{p.group} · ' if prefix and p.group != 'Scan' else '') + p.line() for p in chosen]
