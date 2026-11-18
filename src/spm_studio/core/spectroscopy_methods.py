"""Measurement types of the spectroscopy figure composer (v0.0.10, Qt-free).

One composer for every point-spectroscopy method: the method chosen at the top of the tool
decides the X axis (bias or Z), its label, the default Y channel, the units, which fits make
sense (CPD / kink only for Δf(V) KPFM) and the signal processing (numerical dI/dV, normalised
dI/dV, smoothing, averaging of forward/backward, waterfall offset).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from .bias_figure_analysis import Spectrum, canonical, get_views, is_bias, scalar


@dataclass(frozen=True)
class Method:
    key: str
    label: str
    sweep: str                       # 'bias' | 'z' | 'custom'
    x_label: str
    channels: tuple                  # preferred Y channels (fragments, in order)
    y_label: str = ''                # '' = channel name
    fits: tuple = ('None',)          # height analyses offered
    graph_title: str = 'Spectrum'
    hints: str = ''
    options: tuple = field(default=())


METHODS = {
    'bias_kpfm': Method('bias_kpfm', 'Δf(V) bias spectroscopy · KPFM / CPD', 'bias', 'Sample bias (V)',
                        ('OC M1 Freq. Shift', 'Freq. Shift', 'Frequency Shift', 'Excitation'),
                        fits=('None', 'Kink vs height', 'CPD vs height'), graph_title='Bias spectroscopy',
                        hints='Parabola vertex = local contact potential difference (CPD).',
                        options=('average',)),
    'didv': Method('didv', 'dI/dV · scanning tunnelling spectroscopy (STS)', 'bias', 'Sample bias (V)',
                   ('LI Demod 1 X', 'LI Demod 1 Y', 'Lock-in', 'LIX', 'dIdV', 'dI/dV', 'Current'),
                   y_label='dI/dV', graph_title='dI/dV spectrum',
                   hints='Lock-in channel, or a numerical derivative of the current (smoothed).',
                   options=('didv_source', 'normalize', 'smooth', 'average', 'offset')),
    'iv': Method('iv', 'I(V) · current–bias spectroscopy', 'bias', 'Sample bias (V)',
                 ('Current',), y_label='I', graph_title='I(V) spectrum',
                 options=('smooth', 'average', 'offset', 'log_y')),
    'iz': Method('iz', 'I(z) / Δf(z) · distance spectroscopy', 'z', 'Tip displacement Δz (nm)',
                 ('Current', 'OC M1 Freq. Shift', 'Freq. Shift'), graph_title='Distance spectroscopy',
                 hints='Z channel (Z rel / Z) of the file is used as X axis.',
                 options=('smooth', 'average', 'offset', 'log_y')),
    'generic': Method('generic', 'Generic X–Y spectroscopy (choose X channel)', 'custom', '',
                      (), graph_title='Spectrum', options=('x_channel', 'smooth', 'average', 'offset', 'log_y')),
}
DEFAULT_METHOD = 'bias_kpfm'


def method(key) -> Method:
    return METHODS.get(str(key or ''), METHODS[DEFAULT_METHOD])


def _key(name):
    s = canonical(name)[0].casefold()
    return re.sub('[^a-z0-9]', '', re.sub(r'\[[^]]*\]|\([^)]*\)', '', s))


def is_z(name) -> bool:
    return bool(re.match(r'(?i)^z(?:\s*rel)?(?:\s*\(|$)', canonical(name)[0]))


def x_channels(spec: Spectrum) -> list[str]:
    """Channels of a file that can be an X axis (bias, Z, anything numeric)."""
    return sorted({canonical(c)[0] for c in spec.names}, key=str.casefold)


def y_channels(spec: Spectrum, m: Method) -> list[str]:
    names = sorted({canonical(c)[0] for c in spec.names}, key=str.casefold)
    if m.sweep == 'bias':
        return [n for n in names if not is_bias(n)]
    if m.sweep == 'z':
        return [n for n in names if not is_z(n)]
    return names


def preferred_channel(spec: Spectrum, m: Method) -> str | None:
    names = y_channels(spec, m)
    for fragment in m.channels:
        k = _key(fragment)
        for n in names:
            if k and k in _key(n):
                return n
    return names[0] if names else None


def _column(spec: Spectrum, name: str, direction: str):
    k = _key(name)
    best = None
    for i, n in enumerate(spec.names):
        base, d = canonical(n)
        if _key(base) == k and d == direction:
            return spec.data[:, i]
        if _key(base) == k and best is None:
            best = spec.data[:, i]
    return best


def _x_name(spec: Spectrum, m: Method, x_channel: str = '') -> str | None:
    names = [canonical(c)[0] for c in spec.names]
    if m.sweep == 'z':
        for wanted in ('z rel', 'z'):
            for n in names:
                if re.match(rf'(?i)^{wanted}(?:\s*\(|$)', n):
                    return n
        return None
    if m.sweep == 'custom':
        k = _key(x_channel)
        return next((n for n in names if k and _key(n) == k), None)
    return None


def raw_views(spec: Spectrum, channel: str, m: Method, x_channel: str = '') -> dict:
    """{direction: (x, y)} in native units for the method's X axis."""
    if m.sweep == 'bias':
        return get_views(spec, channel)
    x_name = _x_name(spec, m, x_channel)
    if x_name is None:
        return {}
    out = {}
    k = _key(channel)
    directions = {canonical(n)[1] for n in spec.names if _key(canonical(n)[0]) == k}
    for direction in sorted(directions):
        y = _column(spec, channel, direction)
        x = _column(spec, x_name, direction)
        if x is None or y is None:
            continue
        out[direction] = (np.asarray(x, float), np.asarray(y, float))
    return out


def x_scale(spec: Spectrum, m: Method, x_channel: str = '') -> tuple[float, str]:
    """Factor and unit of the X axis (Z in nm; a custom channel keeps its own unit)."""
    if m.sweep == 'z':
        return 1e9, 'nm'
    if m.sweep == 'custom':
        found = re.findall(r'\(([^()]*)\)', x_channel or '')
        unit = found[-1] if found else ''
        return {'m': (1e9, 'nm'), 'A': (1e12, 'pA')}.get(unit, (1.0, unit))
    return 1.0, 'V'


def x_label(m: Method, x_channel: str = '') -> str:
    if m.sweep != 'custom':
        return m.x_label
    base = re.sub(r'\s*\([^)]*\)\s*$', '', x_channel or 'X').strip() or 'X'
    _f, unit = x_scale(None, m, x_channel)
    return f'{base} ({unit})' if unit else base


def smooth(y, points: int):
    """Savitzky–Golay smoothing (order 2); ``points`` ≤ 2 leaves the data untouched."""
    y = np.asarray(y, float)
    points = int(points or 0)
    if points <= 2 or y.size < 5:
        return y
    from scipy.signal import savgol_filter
    largest = y.size if y.size % 2 else y.size - 1
    w = min(points | 1, largest)
    if w < 5:
        return y
    good = np.isfinite(y)
    if not good.all():
        idx = np.arange(y.size)
        y = np.interp(idx, idx[good], y[good]) if good.sum() >= 2 else y
    return savgol_filter(y, w, 2)


def numerical_derivative(x, y, points: int = 7):
    """dy/dx on a (smoothed) sweep; robust to a decreasing bias ramp."""
    x = np.asarray(x, float)
    y = smooth(y, max(5, int(points or 0)))
    if x.size < 3:
        return np.full_like(y, np.nan)
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.gradient(y, x)


def normalized_didv(x, didv, current, epsilon=0.02):
    """(dI/dV)/(I/V) with a broadened I/V (Feenstra) so the ratio stays finite near 0 V."""
    x = np.asarray(x, float)
    i = np.asarray(current, float)
    d = np.asarray(didv, float)
    with np.errstate(divide='ignore', invalid='ignore'):
        conductance = i / x
        good = np.isfinite(conductance)
        conductance = np.where(good, conductance, 0.0)      # V = 0: only the broadening remains
        scale = np.nanmax(np.abs(conductance[good])) if good.any() else 1.0
        floor = max(float(epsilon) * float(scale), 1e-30)
        broadened = np.sqrt(conductance ** 2 + floor ** 2)
        return d / broadened


def process_views(spec: Spectrum, channel: str, options: dict) -> tuple[dict, str, str, list]:
    """Views ready to plot: ``({direction: (x, y)}, y_label, y_native_unit, warnings)``.

    ``y_native_unit`` is the unit of the returned y in SI (so the composer's unit chooser can
    still pick nA / pA / mV …); the X values are already scaled (Z in nm).
    """
    m = method(options.get('method'))
    warnings = []
    x_channel = str(options.get('x_channel', '') or '')
    views = raw_views(spec, channel, m, x_channel)
    if not views:
        return {}, channel, '', warnings
    found = re.findall(r'\(([^()]*)\)', channel)
    unit = found[-1] if found else ''
    base = re.sub(r'\s*\([^)]*\)\s*$', '', channel).strip()
    label = m.y_label or base
    if m.key != 'didv' and m.y_label:
        label = f'{m.y_label}' if 'current' in base.casefold() else base
    points = int(scalar(options.get('smooth', 0), 0))
    factor, _xunit = x_scale(spec, m, x_channel)
    out = {}
    for direction, (x, y) in views.items():
        x = np.asarray(x, float) * factor
        y = np.asarray(y, float)
        if m.key == 'didv':
            source = str(options.get('didv_source', 'Lock-in channel'))
            numeric = source.startswith('Numerical') or 'current' in base.casefold()
            if numeric:
                y = numerical_derivative(x, y, max(points, 7))
                unit = 'S' if unit == 'A' else (f'{unit}/V' if unit else '')
                label = 'dI/dV'
            else:
                y = smooth(y, points)
                label = 'dI/dV' if not base.casefold().startswith('di') else base
            if options.get('normalize'):
                name = next((canonical(n)[0] for n in spec.names
                             if 'current' in canonical(n)[0].casefold()), '')
                current = _column(spec, name, direction) if name else None
                if current is None:
                    warnings.append(f'{spec.path.name}: no Current channel, dI/dV not normalised')
                else:
                    # Lock-in output (V) or numerical dI/dV (S): the ratio is dimensionless
                    # up to the lock-in gain, so it is shown in arbitrary units.
                    y = normalized_didv(x, y, current)
                    unit = ''
                    label = '(dI/dV)/(I/V)'
        else:
            y = smooth(y, points)
        out[direction] = (x, y)
    if options.get('average') and len(out) > 1 and 'Forward' in out and 'Backward' in out:
        xf, yf = out['Forward']
        xb, yb = out['Backward']
        order = np.argsort(xb)
        yb_on_f = np.interp(xf, xb[order], yb[order], left=np.nan, right=np.nan)
        out = {'Forward': (xf, np.nanmean(np.vstack([yf, yb_on_f]), axis=0))}
    if unit in ('S',):
        y_unit = 'S'
    else:
        y_unit = unit
    return out, label, y_unit, warnings


def convert_y(values, native: str, wanted: str = 'Auto'):
    """Readable unit for the Y axis (pm/nm, mV, pA/nA, nS/pS …)."""
    v = np.asarray(values, float)
    if wanted == 'Raw' or native not in ('m', 'V', 'A', 'S', 'Hz'):
        return v, native
    good = np.abs(v[np.isfinite(v)])
    magnitude = float(np.percentile(good, 90)) if good.size else 0.0
    table = {'m': [('pm', 1e12, 0.5e-9), ('nm', 1e9, np.inf)],
             'V': [('µV', 1e6, 1e-4), ('mV', 1e3, 0.2), ('V', 1, np.inf)],
             'A': [('fA', 1e15, 1e-12), ('pA', 1e12, 1e-9), ('nA', 1e9, 1e-6), ('µA', 1e6, np.inf)],
             'S': [('pS', 1e12, 1e-9), ('nS', 1e9, 1e-6), ('µS', 1e6, np.inf)],
             'Hz': [('Hz', 1, 1e3), ('kHz', 1e-3, np.inf)]}
    if wanted == 'Auto':
        for name, factor, limit in table[native]:
            if magnitude < limit:
                return v * factor, name
        return v, native
    for name, factor, _limit in table[native]:
        if name == wanted:
            return v * factor, name
    return v, native
