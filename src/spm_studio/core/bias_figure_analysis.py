"""Read-only spectroscopy import, scan-coordinate projection and conservative fits.

No hardware imports or commands.  The data exported by bias_z_spectroscopy_gui
remain unchanged; this module operates on copies.
"""
from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import savgol_filter


@dataclass
class Spectrum:
    path: Path
    names: list[str]
    data: np.ndarray
    z_nm: float = float('nan')
    x_m: float = float('nan')
    y_m: float = float('nan')
    settings: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    bias_source: str = ''

    def channels(self) -> list[str]:
        return sorted({canonical(c)[0] for c in self.names if not is_bias(c)}, key=str.casefold)


def scalar(v: Any, default=float('nan')) -> float:
    try:
        if isinstance(v, (list, tuple, np.ndarray)):
            return float(np.asarray(v).reshape(-1)[0])
        if isinstance(v, str):
            return float(v.split()[0])
        return float(v)
    except (ValueError, TypeError, IndexError):
        return float(default)


def canonical(name: str) -> tuple[str, str]:
    name = str(name).strip()
    bwd = bool(re.search(r'(?i)\[\s*(?:bwd|backward)\s*\]|\(\s*(?:bwd|backward)\s*\)|\b(?:bwd|backward)\b', name))
    name = re.sub(r'(?i)\[\s*(?:bwd|backward)\s*\]|\(\s*(?:bwd|backward)\s*\)|\b(?:bwd|backward)\b', '', name)
    name = re.sub(r'\s+', ' ', name).strip(' :-_')
    return name, 'Backward' if bwd else 'Forward'


def is_bias(name: str) -> bool:
    base = canonical(name)[0]
    return bool(re.match(r'(?i)^bias(?:\s+calc(?:ulated)?)?(?:\s*\(|$)', base))


def matching_channel(spec: Spectrum, name: str) -> str | None:
    def key(s):
        s = canonical(s)[0].casefold()
        return re.sub('[^a-z0-9]', '', re.sub(r'\[[^]]*\]|\([^)]*\)', '', s))
    for c in spec.channels():
        if key(c) == key(name):
            return c
    return None


def locate_session(path: Path) -> tuple[dict, Path | None]:
    path = Path(path)
    manifest = path / 'session.json' if path.is_dir() else path.parent / 'session.json'
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding='utf-8'))
            return data, manifest
        except Exception as exc:
            raise ValueError(f'Invalid session.json: {exc}') from exc
    return {}, None


def _metadata(spec: Spectrum, manifest: dict) -> None:
    state = manifest.get('initial_state') or {}
    spec.settings = dict(manifest.get('settings') or {})
    spec.x_m = scalar(state.get('follow_me_x_m'), spec.x_m)
    spec.y_m = scalar(state.get('follow_me_y_m'), spec.y_m)
    spec.metadata = {
        'session_mode': manifest.get('mode', 'unknown'),
        'created': manifest.get('created', ''),
        'initial_state': state,
    }


def read_spectrum(path: Path) -> Spectrum:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    manifest, _ = locate_session(path)
    suffix = path.suffix.casefold()
    z_nm = float('nan')
    bias_source = ''
    if suffix == '.npz':
        with np.load(path, allow_pickle=False) as raw:
            if 'data' not in raw or 'channels' not in raw:
                raise ValueError(f'{path.name}: NPZ must have data + channels')
            data = np.asarray(raw['data'], dtype=float)
            names = [str(c) for c in raw['channels'].tolist()]
            if 'z_offset_nm' in raw:
                z_nm = scalar(raw['z_offset_nm'])
            if 'bias_source' in raw:
                bias_source = str(raw['bias_source'].item())
            x_m = scalar(raw['follow_me_x_m']) if 'follow_me_x_m' in raw else float('nan')
            y_m = scalar(raw['follow_me_y_m']) if 'follow_me_y_m' in raw else float('nan')
    elif suffix in ('.csv', '.dat', '.txt'):
        data, names, meta = _read_table(path)
        z_nm = meta.get('z_nm', z_nm)
        bias_source = meta.get('bias_source', '')
        x_m = meta.get('x_m', float('nan'))
        y_m = meta.get('y_m', float('nan'))
    else:
        raise ValueError(f'Unsupported spectroscopy format: {path.suffix}')
    if data.ndim != 2 or data.size < 4:
        raise ValueError(f'{path.name}: empty or non-2D spectroscopy data')
    if data.shape[1] != len(names) and data.shape[0] == len(names):
        data = data.T
    if data.shape[1] != len(names):
        raise ValueError(f'{path.name}: columns and channel names disagree')
    spec = Spectrum(path, names, data, z_nm, x_m, y_m, bias_source=bias_source)
    # The session metadata is authoritative for the Follow Me location.
    if manifest:
        _metadata(spec, manifest)
    return spec


def _read_table(path: Path):
    """CSV from acquisition GUI and common Nanonis DAT with [DATA] marker."""
    meta = {}
    raw_lines = path.read_text(encoding='utf-8-sig', errors='replace').splitlines()
    lines = []
    inside_data = False
    seen_nanonis_sections = any(ln.strip().upper() == '[DATA]' for ln in raw_lines)
    for line in raw_lines:
        s = line.strip()
        if s.startswith('#'):
            if 'Z offset above original imaging height' in s:
                meta['z_nm'] = scalar(s.split(':', 1)[-1])
            if 'Bias axis:' in s:
                meta['bias_source'] = s.split(':', 1)[-1].strip()
            continue
        if seen_nanonis_sections:
            if s.upper() == '[DATA]':
                inside_data = True
                continue
            if not inside_data:
                # In native DAT Nanonis header XY may be in [HEADER].
                mx = re.search(r'(?i)(?:follow\s*me\s*)?\bX\s*(?:pos(?:ition)?)?\s*\(m\)\s*[=:]\s*([+\-0-9.eE]+)', s)
                my = re.search(r'(?i)(?:follow\s*me\s*)?\bY\s*(?:pos(?:ition)?)?\s*\(m\)\s*[=:]\s*([+\-0-9.eE]+)', s)
                if mx: meta['x_m'] = scalar(mx.group(1))
                if my: meta['y_m'] = scalar(my.group(1))
                fields = re.split(r'\t+| {2,}',s)
                if len(fields) >= 2:
                    token=fields[0].casefold().strip(': ')
                    if token in ('x (m)','x pos (m)','x position (m)'):
                        meta['x_m']=scalar(fields[1])
                    if token in ('y (m)','y pos (m)','y position (m)'):
                        meta['y_m']=scalar(fields[1])
                continue
        if s:
            lines.append(line)
    if len(lines) < 2:
        raise ValueError(f'{path.name}: no data table found')
    delimiter = '\t' if ('\t' in lines[0] or path.suffix.lower() == '.dat') else (',' if ',' in lines[0] else ';')
    reader = csv.reader(lines, delimiter=delimiter)
    names = [c.strip().strip('"') for c in next(reader)]
    rows = []
    for row in reader:
        try:
            if len(row) >= len(names) and len(names) >= 2:
                rows.append([float(s) if s.strip() else float('nan') for s in row[:len(names)]])
        except ValueError:
            continue
    if not rows:
        raise ValueError(f'{path.name}: no numeric data in table')
    return np.asarray(rows, dtype=float), names, meta


def session_files(directory: Path) -> list[Path]:
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(directory)
    # NPZ is native and should take precedence over duplicate CSV exports.
    npz = sorted(directory.glob('height_*.npz'))
    if npz:
        return npz
    csvs = sorted(directory.glob('height_*.csv'))
    return csvs if csvs else sorted(directory.glob('*.dat'))


def get_views(spec: Spectrum, channel: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Decode native forward/backward channels, including 2N-row packed traces."""
    data = spec.data
    nrows = data.shape[0]
    selected = matching_channel(spec, channel)
    if selected is None:
        return {}
    axes = {}
    for idx, name in enumerate(spec.names):
        if is_bias(name):
            base, direction = canonical(name)
            priority = 2 if 'calc' in base.casefold() else 1
            if direction not in axes or priority > axes[direction][0]:
                axes[direction] = (priority, data[:, idx])
    pts = int(scalar(spec.settings.get('points'), 0))
    backward_enabled = bool(spec.settings.get('backward', False))
    x_fwd = axes.get('Forward', (None, None))[1]
    if x_fwd is None:
        a, b = scalar(spec.settings.get('bias_start_v')), scalar(spec.settings.get('bias_end_v'))
        if np.isfinite(a) and np.isfinite(b):
            if pts == nrows:
                x_fwd = np.linspace(a, b, nrows)
            elif backward_enabled and pts * 2 == nrows:
                x_fwd = np.r_[np.linspace(a, b, pts), np.linspace(b, a, pts)]
        if x_fwd is None:
            return {}  # never invent an axis without source limits
    x_bwd = axes.get('Backward', (None, x_fwd))[1]
    found = {}
    explicit_bwd = any(canonical(name)[1] == 'Backward' and canonical(name)[0] == selected
                       for name in spec.names)
    for i, name in enumerate(spec.names):
        base, direction = canonical(name)
        if base != selected:
            continue
        y = np.asarray(data[:, i], dtype=float)
        if backward_enabled and not explicit_bwd and pts > 0 and nrows == 2 * pts:
            found['Forward'] = (np.asarray(x_fwd[:pts]), y[:pts])
            found['Backward'] = (np.asarray(x_fwd[pts:]), y[pts:])
        else:
            x = x_bwd if direction == 'Backward' else x_fwd
            found[direction] = (np.asarray(x), y)
    return found


def convert_signal(values: np.ndarray, channel: str, unit: str = 'Auto') -> tuple[np.ndarray, str]:
    """Use readable physical units; raw values are preserved in the source files."""
    found = re.findall(r'\(([^()]*)\)', channel)
    native = found[-1] if found else ''
    val = np.asarray(values, dtype=float)
    if unit == 'Raw' or native not in ('m', 'V', 'A'):
        return val, native
    good = np.abs(val[np.isfinite(val)])
    magnitude = float(np.percentile(good, 90)) if good.size else 0.0
    if unit == 'Auto':
        if native == 'm':
            unit = 'pm' if magnitude < 0.5e-9 else 'nm'
        elif native == 'V':
            unit = 'mV' if magnitude < 0.2 else 'V'
        elif native == 'A':
            unit = 'pA' if magnitude < 1e-9 else 'nA'
    conversions = {'pm':('m', 1e12),'nm':('m',1e9),'mV':('V',1e3),
                   'pA':('A',1e12),'nA':('A',1e9)}
    if unit in conversions and conversions[unit][0] == native:
        return val * conversions[unit][1], unit
    return val, native


def scan_header(scan) -> dict:
    return dict(getattr(scan, 'metadata', {}) or {})


def _get_header(header: dict, *names: str) -> Any:
    lowered = {re.sub('[^a-z0-9]', '', str(k).lower()): v for k, v in header.items()}
    for name in names:
        k = re.sub('[^a-z0-9]', '', name.lower())
        if k in lowered:
            return lowered[k]
    return None


def _pair(v) -> tuple[float, float] | None:
    try:
        if isinstance(v, str):
            values = [float(x) for x in re.split(r'[,\s]+', v.strip()) if x]
        else:
            values = np.asarray(v, dtype=float).ravel().tolist()
        if len(values) >= 2 and np.all(np.isfinite(values[:2])):
            return float(values[0]), float(values[1])
    except (TypeError, ValueError):
        return None
    return None


def _scan_geometry(scan):
    """Use native SPM Studio geometry, never re-parse an approximated header."""
    channels=getattr(scan,'channels',{})
    if not channels:
        return None
    primary=getattr(scan,'preferred_channel',lambda:next(iter(channels)))()
    return channels[primary].geometry


def scan_size_nm(scan) -> tuple[float,float] | None:
    g=_scan_geometry(scan)
    if g is None or g.size_m is None:
        return None
    return g.size_m[0]*1e9, g.size_m[1]*1e9


def scan_position_m(scan) -> tuple[float, float, float] | None:
    """Auto-coordinate placement is allowed for original SXM geometry only.

    GWY or cropped/altered raster orientations may have insufficient provenance.
    The GUI permits an explicit local X/Y marker instead of guessing.
    """
    if Path(scan.path).suffix.lower() != '.sxm':
        return None
    g=_scan_geometry(scan)
    if g is None or g.center_m is None or g.angle_deg is None or g.size_m is None:
        return None
    return g.center_m[0],g.center_m[1],g.angle_deg


def map_to_scan_nm(scan, x_m: float, y_m: float,
                   flip_x: bool=False, flip_y: bool=False,
                   drift_x_nm: float=0., drift_y_nm: float=0.) -> tuple[float,float] | None:
    """Nanonis global Follow Me XY to native scan-local chart coordinates.

    SPM Studio stores top image row as high local Y, and reads SXM scans into
    a spatially aligned raster. The plot uses origin='upper', no array rotations.
    """
    frame=scan_position_m(scan)
    dims=scan_size_nm(scan)
    if frame is None or dims is None or not np.isfinite((x_m,y_m)).all():
        return None
    cx,cy,angle=frame
    theta=np.deg2rad(angle)
    dx=(x_m-cx)*1e9;dy=(y_m-cy)*1e9
    local_x=dx*np.cos(theta)+dy*np.sin(theta)
    local_y=-dx*np.sin(theta)+dy*np.cos(theta)
    if flip_x:local_x=-local_x
    if flip_y:local_y=-local_y
    return dims[0]*.5+local_x+drift_x_nm,dims[1]*.5+local_y+drift_y_nm


def in_scan(scan, point_nm: tuple[float, float]) -> bool:
    size = scan_size_nm(scan)
    if size is None: return False
    width, height = size
    return 0 <= point_nm[0] <= width and 0 <= point_nm[1] <= height


def _mad(x):
    x = np.asarray(x, dtype=float)
    if not len(x): return 0.0
    return 1.4826 * float(np.median(np.abs(x - np.median(x))))


@dataclass
class Fit:
    success: bool
    voltage: float = float('nan')
    uncertainty: float = float('nan')
    bic_gain: float = float('nan')
    evidence: str = ''
    parameters: dict = field(default_factory=dict)


def find_kink(bias: np.ndarray, signal: np.ndarray, min_bic: float = 14.0,
              min_sigma: float = 4.0) -> Fit:
    """Quadratic-null vs quadratic + (step, slope change) hypothesis test.

    Scores BIC after looking across possible transition positions and adds a
    search penalty. Requires local significance, a stable position under
    decimation, and >= 12% samples on each side. A statistical candidate is
    *not* proof of molecular charging. Used with explicit fit diagnostics.
    """
    x = np.asarray(bias, float).ravel()
    y = np.asarray(signal, float).ravel()
    good = np.isfinite(x) & np.isfinite(y)
    x, y = x[good], y[good]
    if len(x) < 40: return Fit(False, evidence='Too few data points (<40)')
    order = np.argsort(x)
    x, y = x[order], y[order]
    # Average repeated bias values to avoid singular fits.
    unique, inv = np.unique(x, return_inverse=True)
    if len(unique) < .8 * len(x):
        sums = np.bincount(inv, weights=y)
        y = sums / np.bincount(inv)
        x = unique
    n = len(x)
    if n < 40 or (x[-1]-x[0]) <= 0: return Fit(False, evidence='Insufficient bias span')
    # Normalized x for numerical stability; y scaled by robust amplitude.
    xm, xr = float(np.mean(x)), float(np.ptp(x))
    xx = (x - xm) / xr
    yy = y - np.median(y)
    ys = float(np.percentile(yy, 95)-np.percentile(yy, 5))
    if ys <= 0: return Fit(False, evidence='Flat signal')
    yy = yy / ys
    X0 = np.column_stack([np.ones(n), xx, xx**2])
    p0 = np.linalg.lstsq(X0, yy, rcond=None)[0]
    r0 = yy-X0 @ p0
    rss0 = max(float(r0@r0), 1e-24)
    # Noise from high frequency residual, after smoothed quadratic baseline.
    window = min(31, max(7, (n//18) | 1))
    if window % 2 == 0: window += 1
    smooth = savgol_filter(yy, window, 2)
    noise = max(_mad(yy-smooth), 1e-8)
    best = None
    lo, hi = int(n*.16), int(n*.84)
    for idx in range(lo, hi, max(1, (hi-lo)//90)):
        threshold = xx[idx]
        H = (xx >= threshold).astype(float)
        X = np.column_stack([X0, H, np.maximum(xx-threshold, 0)])
        params = np.linalg.lstsq(X, yy, rcond=None)[0]
        residual = yy-X@params
        rss = float(residual@residual)
        if best is None or rss < best[0]:
            best = (rss, idx, params, residual, X)
    if best is None: return Fit(False, evidence='No candidates')
    rss, idx, params, resid, X = best
    # Account for scanning 90 thresholds in addition to the two extra params.
    # Strong guard against false positives: compare with flexible *smooth* curves.
    # Without this, a quartic, sinusoidal response or broad S-shape can be
    # mistaken for a sharp charge transition by a quadratic-only null.
    alt_bic = n*np.log(max(rss/n,1e-24)) + 5*np.log(n) + 2*np.log(max(2,(hi-lo)//max(1,(hi-lo)//90)))
    smooth_bics = []
    for degree in range(2, 7):
        poly = np.polynomial.polynomial.polyvander(xx, degree)
        beta = np.linalg.lstsq(poly, yy, rcond=None)[0]
        rr = yy-poly @ beta
        smooth_bics.append(n*np.log(max(float(rr@rr)/n,1e-24)) + (degree+1)*np.log(n))
    gain = min(smooth_bics) - alt_bic
    # Step at threshold and slope variation across a 5% window.
    discontinuity = abs(float(params[3]))
    slope_effect = abs(float(params[4])) * .05
    impact = math.hypot(discontinuity, slope_effect)
    local_significance = impact / max(noise, math.sqrt(max(rss/n,0))*0.25,1e-8)
    if gain < min_bic or local_significance < min_sigma:
        return Fit(False, bic_gain=float(gain), evidence=f'Candidate below thresholds (BIC {gain:.1f}, SNR {local_significance:.1f})')
    # Reject smooth polynomial distortions which mimic a hinge across whole curve:
    # a genuine local feature is much more sharply concentrated near threshold.
    # Robust check by fitting even and odd points independently.
    estimates = []
    for subset in (slice(None,None,2), slice(1,None,2)):
        xs, ys_ = xx[subset], yy[subset]
        ns = len(xs)
        if ns < 20: continue
        q = np.column_stack([np.ones(ns), xs, xs**2])
        b = None
        for j in range(max(5,int(ns*.16)), min(ns-5,int(ns*.84)), max(1, ns//60)):
            h = (xs >= xs[j]).astype(float)
            mat = np.column_stack([q,h,np.maximum(xs-xs[j],0)])
            p = np.linalg.lstsq(mat,ys_,rcond=None)[0]
            e = ys_-mat@p
            sse = float(e@e)
            if b is None or sse < b[0]: b = (sse, float(xs[j]))
        if b: estimates.append(b[1])
    if len(estimates)==2 and max(abs(v-xx[idx]) for v in estimates) > .08:
        return Fit(False, bic_gain=float(gain), evidence='Unstable kink under odd/even sampling')
    # Candidate positional uncertainty from bias discretization & cross-validation.
    resolution = abs(float(np.median(np.diff(x))))
    err = max(resolution, float(np.std(estimates)) * xr if len(estimates)==2 else resolution)
    return Fit(True, float(x[idx]), err, float(gain),
               f'Candidate kink; BIC gain {gain:.1f}, local SNR {local_significance:.1f}; verify manually',
               {'step_fraction': float(params[3]), 'slope_fraction':float(params[4]), 'noise_fraction':noise})


def fit_cpd(bias: np.ndarray, signal: np.ndarray) -> Fit:
    """Parabolic vertex; reports fit only for positive/negative strong curvature."""
    x=np.asarray(bias,float).ravel(); y=np.asarray(signal,float).ravel()
    good=np.isfinite(x)&np.isfinite(y); x,y=x[good],y[good]
    if len(x)<12 or np.ptp(x)==0: return Fit(False,evidence='Too few points')
    mid=float(np.mean(x)); scale=float(np.ptp(x)); t=(x-mid)/scale
    X=np.column_stack([t*t,t,np.ones(len(t))])
    p=np.linalg.lstsq(X,y,rcond=None)[0]
    rss=float(np.sum((y-X@p)**2))
    if abs(p[0]) < 1e-10 * max(1.0, float(np.max(np.abs(y)))):
        return Fit(False, evidence='Curvature too small')
    vertex=-p[1]/(2*p[0])*scale+mid
    # CPD extrapolation beyond scan is not reliable.
    if vertex < np.min(x) or vertex > np.max(x):
        return Fit(False, evidence='Vertex outside recorded bias range')
    try:
        cov=np.linalg.inv(X.T@X)*rss/max(1,len(x)-3)
        grad=np.array([p[1]/(2*p[0]**2),-1/(2*p[0]),0])*scale
        err=math.sqrt(max(0,float(grad@cov@grad)))
    except np.linalg.LinAlgError:
        err=float('nan')
    ss=float(np.sum((y-np.mean(y))**2))
    r2=1-rss/max(ss,1e-30)
    return Fit(r2>=0.85,float(vertex),err,evidence=f'Parabola R² = {r2:.3f}',parameters={'r2':r2})


def linear_trend(points: list[tuple[float,float,float]]) -> dict | None:
    """Fit V_kink = intercept + slope * z_nm with propagated uncertainties."""
    values=np.asarray(points,float)
    if values.ndim!=2 or values.shape[0]<3: return None
    values=values[np.isfinite(values[:,:2]).all(axis=1)]
    if len(values)<3 or len(np.unique(values[:,0]))<3: return None
    x,y,err=values.T
    valid=np.isfinite(err)&(err>0)
    fallback=max(_mad(np.diff(y)) if len(y)>2 else 0.,1e-3)
    err=np.where(valid,err,fallback)
    A=np.column_stack([np.ones(len(x)),x])
    w=1/np.maximum(err,1e-5)**2
    cov=np.linalg.pinv(A.T@(w[:,None]*A))
    beta=cov@(A.T@(w*y))
    resid=y-A@beta
    chi2=float(np.sum(w*resid**2))
    cov*=max(1.,chi2/max(1,len(x)-2))
    return {'intercept':float(beta[0]),'slope':float(beta[1]),
            'intercept_err':float(np.sqrt(max(cov[0,0],0))),
            'slope_err':float(np.sqrt(max(cov[1,1],0))),
            'n':len(x),'chi2_reduced':chi2/max(1,len(x)-2)}
