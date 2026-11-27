"""Lateral (X/Y) piezo calibration from lattice images of a known crystal — pure NumPy.

Model
-----
A scan was recorded with the *old* calibration constants ``cx_old``, ``cy_old`` (m/V).
The apparent displacement along a piezo axis is ``p = c_old · V`` while the real one is
``c_true · V``. For a lattice vector measured in the image (scan frame, +x fast axis,
+y up) we rotate it into the piezo frame with the recorded scan angle θ,

    v_piezo = R(θ) · v_image,      V = (v_piezo,x / cx_old,  v_piezo,y / cy_old)   (volts)

and the real length of the vector is

    |L|² = Vx² · X + Vy² · Y + 2 Vx Vy · Z,      X = cx², Y = cy², Z = cxy (axis skew).

The theoretical length L of every measured vector (a, b and, when the cell angle or the
diagonal is known, the two diagonals |a ± b|) is known, so the equation is **linear** in the
unknowns (X, Y[, Z]). All vectors of all scans are solved together by weighted linear least
squares; scans recorded with different old calibrations, scan angles (fast axis along X or
Y) and slow-scan directions are handled exactly because each equation uses its own scan's
old constants and angle. The new constants are cx = √X, cy = √Y.

Nothing here touches files or Qt: it is tested on synthetic lattices with known distortion.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

# Surface lattices (room temperature, nm). γ = angle between a and b.
# v1.4: ``step`` = monatomic step height (nm) for the Z calibration, from the bulk lattice constant
# (fcc(111): a/√3; rock salt (001): a/2; layered crystals: interlayer distance c/2), and, for Au(111),
# ``herringbone`` = period of the 22×√3 reconstruction (nm) for the X/Y calibration without atomic resolution.
BARTH_1990 = ('J. V. Barth, H. Brune, G. Ertl and R. J. Behm, “Scanning tunneling microscopy observations on the '
              'reconstructed Au(111) surface: Atomic structure, long-range superstructure, rotational domains, and '
              'surface defects,” Phys. Rev. B 42, 9307 (1990), doi:10.1103/PhysRevB.42.9307')
MATERIALS = {
    'Custom': None,
    'KBr(001) — a = 6.65 Å, γ = 90°, diagonal 4.7 Å (Hinaut 2012)': {
        'a': 0.665, 'b': 0.665, 'gamma': 90.0, 'diagonal': 0.47,
        'note': 'conventional rock-salt cell a = 6.65 Å; 4.7 Å = half diagonal = distance between neighbouring '
                'ions of the same species (the square cell seen in NC-AFM images, rotated by 45°)',
        'source': 'A. Hinaut, “Non-contact Atomic Force Microscopy and Kelvin Probe Force Microscopy Studies of '
                  'Triphenylene Derivatives on KBr(001) in Ultra High Vacuum,” Ph.D. thesis, Université '
                  'Toulouse III – Paul Sabatier (2012).',
        'step': 0.3325, 'step_note': 'monatomic step of rock salt (001) = a/2 = 3.325 Å (a = 6.65 Å, Hinaut 2012)'},
    'NaCl(001) — Cl–Cl square cell': {'a': 0.3988, 'b': 0.3988, 'gamma': 90.0, 'diagonal': 0.5640,
                                      'note': 'rock salt a0 = 5.640 Å',
                                      'step': 0.2820, 'step_note': 'monatomic step = a0/2 = 2.820 Å'},
    'KCl(001) — Cl–Cl square cell': {'a': 0.4449, 'b': 0.4449, 'gamma': 90.0, 'diagonal': 0.6293,
                                     'note': 'rock salt a0 = 6.293 Å',
                                     'step': 0.31465, 'step_note': 'monatomic step = a0/2 = 3.147 Å'},
    'HOPG / graphene (hexagonal)': {'a': 0.2461, 'b': 0.2461, 'gamma': 120.0, 'diagonal': None,
                                    'note': 'in-plane a = 2.461 Å',
                                    'step': 0.3354, 'step_note': 'single graphene-layer step = c/2 = 3.354 Å'},
    'Au(111) (1×1)': {'a': 0.2884, 'b': 0.2884, 'gamma': 120.0, 'diagonal': None, 'note': 'a_fcc/√2, a = 4.078 Å',
                      'step': 0.23545,
                      'step_note': 'monatomic step = a_fcc/√3 = 2.355 Å (a_fcc = 4.078 Å); Barth et al. (1990) '
                                   'observe monatomic steps of ≈ 2.4 Å',
                      'herringbone': 22 * 0.2884,
                      'herringbone_note': '22×√3 reconstruction: pairs of corrugation lines every 22 × 2.884 Å = '
                                          '63.4 Å along [1-10] (measured 63 Å), bent by 120° in the herringbone '
                                          '(zigzag) pattern (≈ 250 Å between bends)',
                      'herringbone_source': BARTH_1990, 'step_source': BARTH_1990},
    'Ag(111) (1×1)': {'a': 0.2889, 'b': 0.2889, 'gamma': 120.0, 'diagonal': None, 'note': 'a_fcc/√2, a = 4.086 Å',
                      'step': 0.2359, 'step_note': 'monatomic step = a_fcc/√3 = 2.359 Å'},
    'Cu(111) (1×1)': {'a': 0.2556, 'b': 0.2556, 'gamma': 120.0, 'diagonal': None, 'note': 'a_fcc/√2, a = 3.615 Å',
                      'step': 0.2087, 'step_note': 'monatomic step = a_fcc/√3 = 2.087 Å'},
    'Si(111)-(7×7)': {'a': 2.688, 'b': 2.688, 'gamma': 120.0, 'diagonal': None, 'note': '7 × 3.840 Å',
                      'step': 0.3136, 'step_note': 'bilayer step = a/√3 = 3.136 Å (a = 5.431 Å)'},
    'h-BN (hexagonal)': {'a': 0.2504, 'b': 0.2504, 'gamma': 120.0, 'diagonal': None, 'note': 'a = 2.504 Å',
                         'step': 0.333, 'step_note': 'single-layer step = c/2 = 3.33 Å'},
}


# --------------------------------------------------------------------------- reference lattice
@dataclass(frozen=True)
class Reference:
    a_nm: float
    b_nm: float
    gamma_deg: float | None = None
    diagonal_nm: float | None = None
    name: str = 'Custom'
    notes: tuple = ()

    @property
    def square_like(self) -> bool:
        return abs(self.a_nm - self.b_nm) <= 1e-6 * max(self.a_nm, self.b_nm)

    def diagonals(self):
        """(short, long) theoretical diagonals |a ± b| when known, else (None, None)."""
        if self.gamma_deg is not None:
            g = math.radians(self.gamma_deg)
            plus = math.sqrt(self.a_nm ** 2 + self.b_nm ** 2 + 2 * self.a_nm * self.b_nm * math.cos(g))
            minus = math.sqrt(self.a_nm ** 2 + self.b_nm ** 2 - 2 * self.a_nm * self.b_nm * math.cos(g))
            return tuple(sorted((plus, minus)))
        if self.diagonal_nm:
            # Without γ we cannot tell which of |a + b| / |a − b| was given: a value close to
            # √(a² + b²) (rectangular/square) is both; otherwise the longer one is assumed.
            d = float(self.diagonal_nm)
            if abs(d / math.hypot(self.a_nm, self.b_nm) - 1) < .02:
                return d, d
            return (d, None) if d < math.hypot(self.a_nm, self.b_nm) else (None, d)
        return None, None


def cell_deviation(a_nm, b_nm, ref: Reference) -> float:
    """Largest relative difference between a detected cell (a, b) and a reference cell."""
    lengths = sorted((a_nm, b_nm))
    expected = sorted((ref.a_nm, ref.b_nm))
    return max(abs(lengths[0] / expected[0] - 1), abs(lengths[1] / expected[1] - 1))


def equivalent_references(ref: Reference):
    """Other standard descriptions of the same crystal surface: [(Reference, explanation)].

    The value typed is often the *conventional* constant, while the image shows the primitive
    surface cell (or the reverse):
    * square cell (γ = 90°, a = b): a/√2 rotated by 45° (rock-salt a0 → one-ion-species cell
      a0/√2, e.g. KBr 6.60 Å → 4.67 Å) and a·√2;
    * hexagonal cell (γ = 60°/120°, a = b): a·√3 and a/√3 ((√3×√3)R30° descriptions).
    Only these exact geometric relations are offered; nothing is fitted.
    """
    out = [(ref, 'as entered')]
    if not ref.square_like:
        return out
    g = ref.gamma_deg
    if g is not None and abs(g - 90) < 1e-6:
        r2 = math.sqrt(2)
        out.append((Reference(ref.a_nm / r2, ref.b_nm / r2, 90.0, ref.a_nm, ref.name + ' · a/√2 cell', ref.notes),
                    f'a/√2 = {ref.a_nm / r2 * 10:.4f} Å: the entered value is the conventional (rock-salt) constant, '
                    'the image shows the primitive surface cell rotated by 45°'))
        out.append((Reference(ref.a_nm * r2, ref.b_nm * r2, 90.0, ref.a_nm * 2, ref.name + ' · a·√2 cell', ref.notes),
                    f'a·√2 = {ref.a_nm * r2 * 10:.4f} Å: the entered value is the primitive cell, the image shows the '
                    'conventional cell'))
    elif g is not None and (abs(g - 120) < 1e-6 or abs(g - 60) < 1e-6):
        r3 = math.sqrt(3)
        out.append((Reference(ref.a_nm * r3, ref.b_nm * r3, g, None, ref.name + ' · √3 cell'),
                    f'a·√3 = {ref.a_nm * r3 * 10:.4f} Å: (√3×√3)R30° cell'))
        out.append((Reference(ref.a_nm / r3, ref.b_nm / r3, g, None, ref.name + ' · a/√3 cell'),
                    f'a/√3 = {ref.a_nm / r3 * 10:.4f} Å: the entered value is the (√3×√3) cell'))
    return out


def choose_reference(cells, ref: Reference, tolerance: float, automatic=True):
    """Pick the description of the reference that the detected cells [(a, b, γ)] match.

    Returns (reference, explanation, median deviation). The choice is made on the median over
    all scans, so one bad scan cannot change it; it is only accepted within the tolerance.
    """
    candidates = equivalent_references(ref) if automatic else [(ref, 'as entered')]
    if not cells:
        return ref, 'as entered', float('nan')
    scored = []
    for candidate, why in candidates:
        dev = float(np.median([cell_deviation(a, b, candidate) for a, b, _g in cells]))
        scored.append((dev, candidate, why))
    scored.sort(key=lambda t: t[0])
    dev, best, why = scored[0]
    if best is not ref and dev > tolerance:
        entered = next(d for d, c, _w in scored if c is ref)
        return ref, 'as entered', entered
    return best, why, dev


def find_material(name):
    """Preset by its label; a label from an older version matches by its first word (``KBr(001)``)."""
    name = str(name or 'Custom')
    if name in MATERIALS:
        return name, MATERIALS[name]
    head = name.split(' ')[0]
    for key, value in MATERIALS.items():
        if value is not None and key.split(' ')[0] == head:
            return key, value
    return 'Custom', None


def full_diagonals(a, b, gamma_deg):
    g = math.radians(gamma_deg)
    return (math.sqrt(a * a + b * b + 2 * a * b * math.cos(g)), math.sqrt(a * a + b * b - 2 * a * b * math.cos(g)))


def reference_from_parameters(p: dict) -> Reference:
    """Reference lattice from the Tool settings.

    A crystal preset gives a, b, γ and the diagonal; the four fields are used with *Custom*.
    The diagonal may be the full diagonal |a ± b| or the half diagonal (KBr: 4.7 Å = the
    distance between neighbouring ions of the same species in the 6.65 Å cubic cell).
    """
    material, preset = find_material(p.get('material', 'Custom'))
    notes = []
    if preset:
        a, b, gamma, diag = preset['a'], preset['b'], preset['gamma'] or 0, preset['diagonal'] or 0
        if preset.get('source'):
            notes.append('Source: ' + preset['source'])
    else:
        a = float(p.get('a_angstrom', 0) or 0) / 10
        b = float(p.get('b_angstrom', 0) or 0) / 10
        gamma = float(p.get('gamma_deg', 0) or 0)
        diag = float(p.get('diagonal_angstrom', 0) or 0) / 10
    if a <= 0:
        raise ValueError('Enter the theoretical lattice constant a (Å) or choose a crystal.')
    b = b if b > 0 else a
    if gamma and not 0 < gamma < 180:
        raise ValueError('γ must be between 0 and 180°.')
    full = None
    if diag > 0:
        if gamma:
            d1, d2 = full_diagonals(a, b, gamma)
            options = [(abs(diag / d - 1), d, 'full diagonal') for d in (d1, d2)] + \
                      [(abs(diag / (d / 2) - 1), d, 'half diagonal') for d in (d1, d2)]
            err, d, kind = min(options)
            if err <= .02:
                full = d
                notes.append(f'Diagonal {diag * 10:.3f} Å = {kind} of the cell ({d * 10 / (2 if kind == "half diagonal" else 1):.3f} Å '
                             f'from a, b, γ): consistent' + (' — the same-species sublattice a/√2 is the cell seen in '
                                                             'the image' if kind == 'half diagonal' else '') + '.')
            else:
                notes.append(f'Diagonal {diag * 10:.3f} Å does not agree with a, b, γ (full diagonals '
                             f'{d1 * 10:.3f} / {d2 * 10:.3f} Å): γ is used, the diagonal is ignored.')
        else:
            # Without γ: a value shorter than the cell sides can only be a half diagonal.
            full = 2 * diag if diag < max(a, b) else diag
            if full != diag:
                notes.append(f'Diagonal {diag * 10:.3f} Å is shorter than a: taken as the half diagonal '
                             f'(full diagonal {full * 10:.3f} Å).')
    return Reference(a, b, gamma or None, full, material, tuple(notes))


# --------------------------------------------------------------------------- header metadata
def header_dict(metadata) -> dict:
    """``{UPPER KEY: text}`` from the reader's metadata (native SXM header or raw header)."""
    meta = metadata or {}
    out = {}
    h = meta.get('header') or {}
    if isinstance(h, dict):
        for k, v in h.items():
            if isinstance(v, (list, tuple)):
                v = '\n'.join(map(str, v))
            out[str(k).strip(':').upper()] = '' if v is None else str(v)
    raw = meta.get('raw_header')
    if isinstance(raw, str) and raw:
        key = None
        for line in raw.replace('\r', '').split('\n'):
            s = line.strip()
            if re.fullmatch(r':[^:\n]+:', s):
                key = s[1:-1].upper()
                out.setdefault(key, '')
            elif key is not None and s and not out.get(key):
                out[key] = s
    for k, v in meta.items():          # GWY metadata / flat dictionaries
        if isinstance(v, (str, int, float)) and str(k).upper() not in out:
            out[str(k).upper()] = str(v)
    return out


def _number(text):
    m = re.search(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', str(text or ''))
    return float(m.group(0)) if m else None


def calibration_from_header(h: dict) -> dict:
    """Old X/Y piezo calibration (m/V) and related settings found in the header.

    Nanonis writes the active piezo configuration as ``Piezo Configuration>Calib. X (m/V)``;
    other spellings (``Calibration X``, ``X calib``, nm/V) are accepted. Missing → ``None``.
    """
    found = {'cx': None, 'cy': None, 'source_keys': [], 'hv_gain': {}, 'drift_correction': None,
             'second_order': {}, 'active_calibration': None}
    for key, value in h.items():
        k = key.upper()
        if 'CALIB' in k and re.search(r'\b(X|Y)\b', k) and 'CURRENT' not in k and 'BIAS' not in k:
            axis = re.search(r'\b(X|Y)\b', k).group(1)
            number = _number(value)
            if number is None or number <= 0:
                continue
            if 'NM/V' in k:
                number *= 1e-9
            elif 'M/V' not in k and number > 1e-3:
                continue                      # not a length-per-volt constant
            name = 'cx' if axis == 'X' else 'cy'
            if found[name] is None:
                found[name] = number
                found['source_keys'].append(key)
        if 'HV GAIN' in k:
            axis = re.search(r'\b(X|Y|Z)\b', k)
            if axis:
                found['hv_gain'][axis.group(1)] = _number(value)
        if 'DRIFT CORRECTION' in k and 'STATUS' in k:
            found['drift_correction'] = str(value).strip()
        if '2ND ORDER' in k or 'CURVATURE' in k:
            n = _number(value)
            if n:
                found['second_order'][key] = n
        if 'ACTIVE CALIB' in k:
            found['active_calibration'] = str(value).strip()
    return found


def acquisition_from_header(h: dict) -> dict:
    """Timing and drift information of a scan (all optional).

    * ``line_time``: (forward, backward) time per line in s — Nanonis ``SCAN_TIME``;
    * ``drift``: drift velocity written in the header (piezo frame, nm/s) — Nanonis
      ``Piezo Configuration>Drift X/Y (m/s)``; ``drift_status``: compensation on/off;
    * ``timestamp``: acquisition start (s since epoch) from ``REC_DATE`` / ``REC_TIME``;
    * ``offset_nm``: scan centre (``SCAN_OFFSET``).
    """
    import datetime as _dt
    out = {'line_time': None, 'drift': None, 'drift_status': None, 'timestamp': None, 'offset_nm': None}
    st = h.get('SCAN_TIME')
    if st:
        values = [float(x) for x in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', st)]
        if values:
            out['line_time'] = (values[0], values[1] if len(values) > 1 else values[0])
    drift = {}
    for key, value in h.items():
        k = key.upper()
        if 'DRIFT' in k and ('STATUS' in k or 'ON/OFF' in k or 'CORRECTION' in k) and not re.search(r'\bDRIFT [XYZ]\b', k):
            out['drift_status'] = str(value).strip()
            continue
        m = re.search(r'DRIFT\s*([XY])\b', k)
        if m:
            n = _number(value)
            if n is None:
                continue
            factor = 1e9                                  # m/s → nm/s
            if 'NM/S' in k:
                factor = 1.0
            elif 'M/MIN' in k:
                factor = 1e9 / 60
            elif 'M/S' not in k and abs(n) > 1e-3:
                continue
            drift[m.group(1)] = n * factor
    if drift:
        out['drift'] = np.array([drift.get('X', 0.0), drift.get('Y', 0.0)])
    date, clock = (h.get('REC_DATE') or '').strip(), (h.get('REC_TIME') or '').strip()
    if date:
        for fmt in ('%d.%m.%Y %H:%M:%S', '%d.%m.%Y %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%d.%m.%Y'):
            try:
                out['timestamp'] = _dt.datetime.strptime(f'{date} {clock}'.strip(), fmt).timestamp()
                break
            except ValueError:
                continue
    off = h.get('SCAN_OFFSET')
    if off:
        values = [float(x) for x in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', off)][:2]
        if len(values) == 2:
            out['offset_nm'] = (values[0] * 1e9, values[1] * 1e9)
    return out


def z_calibration_from_header(h: dict) -> dict:
    """Previous Z piezo calibration (m/V) and Z drift compensation written in the header (v1.4).

    Nanonis: ``Piezo Configuration>Calib. Z (m/V)``, ``Piezo Configuration>Drift Z (m/s)`` and
    ``HV Gain Z``. Other spellings (``Z calibration (nm/V)``) are accepted. Missing → ``None``.
    """
    out = {'cz': None, 'source_key': None, 'drift_z_nm_per_s': None, 'hv_gain_z': None}
    for key, value in h.items():
        k = key.upper()
        if (out['cz'] is None and re.search(r'CALIB\w*\.?\s*Z\b|\bZ\s+CALIB', k)
                and 'CURRENT' not in k and 'BIAS' not in k):
            n = _number(value)
            if n is not None and n > 0:
                if 'NM/V' in k:
                    n *= 1e-9
                elif 'M/V' not in k and n > 1e-3:
                    n = None                          # not a length-per-volt constant
                if n:
                    out['cz'] = n
                    out['source_key'] = key
        if re.search(r'DRIFT\s*Z\b', k) and not ('STATUS' in k or 'ON/OFF' in k):
            n = _number(value)
            if n is None:
                continue
            if 'NM/S' in k:
                factor = 1.0
            elif 'M/MIN' in k:
                factor = 1e9 / 60
            elif 'M/S' in k or abs(n) <= 1e-3:
                factor = 1e9
            else:
                continue
            out['drift_z_nm_per_s'] = n * factor
        if 'HV GAIN' in k and re.search(r'\bZ\b', k):
            out['hv_gain_z'] = _number(value)
    return out


def compensation_on(status) -> bool | None:
    t = str(status or '').strip().lower()
    if t in ('on', 'true', '1', 'yes', 'enabled'):
        return True
    if t in ('off', 'false', '0', 'no', 'disabled'):
        return False
    return None


def time_gradient(trace, slow_direction, size_nm, shape, line_time):
    """∂t/∂x and ∂t/∂y of an image (s per nm, image frame, +y up).

    Fast axis: the forward trace runs towards +x during t_fwd, the backward trace towards −x.
    Slow axis: one line (forward + backward) per row; a *down* scan starts at the top, so time
    grows towards −y; an *up* scan towards +y.
    """
    if not line_time:
        return None
    t_fwd, t_bwd = line_time
    width, height = size_nm
    rows = shape[0]
    fast = (t_fwd if trace != 'backward' else -t_bwd) / max(width, 1e-12)
    slow = (t_fwd + t_bwd) * rows / max(height, 1e-12)
    d = str(slow_direction or '').lower()
    if d not in ('up', 'down'):
        return None
    return np.array([fast, slow if d == 'up' else -slow])


def _match_basis(target, basis):
    """``basis`` expressed with the same choice of vectors as ``target`` (±a, ±b, a↔b)."""
    b = np.asarray(basis, float)
    variants = []
    for cols in ((0, 1), (1, 0)):
        for sa in (1, -1):
            for sb in (1, -1):
                variants.append(np.column_stack([sa * b[:, cols[0]], sb * b[:, cols[1]]]))
    return min(variants, key=lambda v: float(np.linalg.norm(v - target)))


def updown_pairs(scans, max_offset_fraction=.15):
    """Consecutive scans of the same area with opposite slow-scan direction.

    Same scan angle, size and trace; centres within 15 % of the scan size (when known);
    taken in order of acquisition time (or file order).
    """
    order = sorted(range(len(scans)), key=lambda i: (scans[i].extra.get('timestamp') or 0, i))
    used, pairs = set(), []
    for pos, i in enumerate(order):
        if i in used:
            continue
        a = scans[i]
        for j in order[pos + 1:]:
            b = scans[j]
            if j in used or {a.slow_direction, b.slow_direction} != {'up', 'down'} or a.trace != b.trace:
                continue
            if abs(a.angle_deg - b.angle_deg) > .5 or abs(a.size_nm[0] / b.size_nm[0] - 1) > .01:
                continue
            oa, ob = a.extra.get('offset_nm'), b.extra.get('offset_nm')
            if oa and ob and math.hypot(oa[0] - ob[0], oa[1] - ob[1]) > max_offset_fraction * a.size_nm[0]:
                continue
            if a.time_gradient is None or b.time_gradient is None:
                continue
            pairs.append((i, j))
            used |= {i, j}
            break
    return pairs


def pair_drift(up: ScanLattice, down: ScanLattice, calibration=(1.0, 1.0)):
    """Drift velocity (piezo frame, nm/s) from an up/down pair — independent of the reference.

    Both frames show the same lattice; a constant drift v distorts them with opposite slow-axis
    time gradients:  (K − v g_upᵀ) B_up = (K − v g_downᵀ) B_down   (image frame, K ≈ correction).
    → v · (g_upᵀ B_up − g_downᵀ B_down) = K (B_up − B_down): 4 equations, 2 unknowns.
    The lattice constants of the reference are not used; the residual tells whether a
    constant drift explains the difference between the two frames.
    """
    r = rotation(up.angle_deg)
    k = r.T @ np.diag(calibration) @ r
    bu = np.asarray(up.basis_image_nm, float)
    bd = _match_basis(bu, down.basis_image_nm)
    w = up.time_gradient @ bu - down.time_gradient @ bd          # (2,) row: time along a, b
    rhs = k @ (bu - bd) - np.outer(r.T @ (up.drift_known), up.time_gradient) @ bu \
        + np.outer(r.T @ (down.drift_known), down.time_gradient) @ bd
    # v (image frame) solves  v ⊗ w = rhs  in the least-squares sense
    if float(w @ w) <= 0:
        return None
    v_img = rhs @ w / float(w @ w)
    residual = rhs - np.outer(v_img, w)
    scale = float(np.linalg.norm(bu))
    return {'drift': r @ v_img, 'residual_nm': float(np.linalg.norm(residual)), 'relative_residual':
            float(np.linalg.norm(residual) / max(scale, 1e-12)), 'up': up.name, 'down': down.name}


# --------------------------------------------------------------------------- measured data
@dataclass
class ScanLattice:
    """Lattice measured on one scan (image frame, nm, +y up), with its acquisition context."""
    name: str
    basis_image_nm: np.ndarray            # 2×2, columns a, b (Gauss reduced)
    angle_deg: float                      # scan angle (fast axis vs piezo X, CCW)
    cx_old: float | None                  # m/V
    cy_old: float | None
    size_nm: tuple                        # (width, height) as recorded
    shape: tuple                          # (rows, cols)
    slow_direction: str = ''              # 'up' / 'down'
    trace: str = 'forward'
    is_current: bool = False
    extra: dict = field(default_factory=dict)
    # Drift (v0.1.3): time gradient of the image (s per nm, image frame) and the drift that is
    # known for this scan (piezo frame, nm/s) — header drift when compensation was OFF.
    time_gradient: np.ndarray | None = None
    drift_known: np.ndarray = field(default_factory=lambda: np.zeros(2))

    @property
    def fast_axis(self) -> str:
        a = (self.angle_deg % 180 + 180) % 180
        if min(a, 180 - a) < 1:
            return 'X'
        if abs(a - 90) < 1:
            return 'Y'
        return f'{self.angle_deg:g}°'


def rotation(deg):
    t = math.radians(deg)
    return np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])


def piezo_vectors(scan: ScanLattice) -> dict:
    """Measured vectors in the piezo frame (nm, *old* calibration): a, b, a+b, a−b."""
    basis = rotation(scan.angle_deg) @ np.asarray(scan.basis_image_nm, float)
    a, b = basis[:, 0], basis[:, 1]
    return {'a': a, 'b': b, 'a+b': a + b, 'a-b': a - b}


@dataclass
class Equation:
    scan: int
    label: str          # 'a', 'b', 'd_short', 'd_long'
    theory_nm: float
    vector_nm: np.ndarray   # measured in piezo frame with the old calibration
    volts: np.ndarray       # vector / old calibration (in V; needs cx_old, cy_old)
    sigma_nm: float
    g_dot_u: float = 0.0    # time elapsed along the vector during the scan (s)
    drift_known: np.ndarray = field(default_factory=lambda: np.zeros(2))


def _assign(scan: ScanLattice, ref: Reference, guess=(1.0, 1.0)):
    """Which measured vector is a, b and which diagonal is short/long.

    With a ≠ b the assignment is chosen after correcting by the current calibration guess,
    so it stays right even with a large initial error. Returns {label: (vector, theory)}.
    """
    v = piezo_vectors(scan)
    k = np.asarray(guess, float)

    def corrected(x):
        return float(np.linalg.norm(x * k))
    la, lb = corrected(v['a']), corrected(v['b'])
    out = {}
    if ref.square_like or abs(la / ref.a_nm - lb / ref.b_nm) <= abs(la / ref.b_nm - lb / ref.a_nm):
        out['a'] = (v['a'], ref.a_nm)
        out['b'] = (v['b'], ref.b_nm)
    else:
        out['a'] = (v['b'], ref.a_nm)
        out['b'] = (v['a'], ref.b_nm)
    short, long_ = ref.diagonals()
    d1, d2 = v['a+b'], v['a-b']
    ds, dl = (d1, d2) if corrected(d1) <= corrected(d2) else (d2, d1)
    if short is not None:
        out['d_short'] = (ds, short)
    if long_ is not None:
        out['d_long'] = (dl, long_)
    return out


def build_equations(scans, ref: Reference, guess=(1.0, 1.0), fallback=(None, None)):
    """One equation per measured vector. ``guess`` = (kx, ky) only to choose labels."""
    equations = []
    for i, s in enumerate(scans):
        cx = s.cx_old or fallback[0]
        cy = s.cy_old or fallback[1]
        if not cx or not cy:
            raise ValueError(f'{s.name}: the previous X/Y calibration is unknown. Enter it in Tool settings '
                             '(Previous calibration X / Y), or leave both empty to compute relative factors.')
        # FFT resolution: one frequency bin is 1/(image extent); the half-bin error on a
        # vector of length L observed over an image of size W is ≈ L²/(2W).
        w = min(s.size_nm)
        for label, (vec, theory) in _assign(s, ref, guess).items():
            L = float(np.linalg.norm(vec))
            sigma = max(L * L / (2 * max(w, 1e-9)), 1e-4 * L)
            g = s.time_gradient
            # time gradient is in the image frame; the vector is in the piezo frame
            g_dot_u = float(np.asarray(g) @ (rotation(s.angle_deg).T @ vec)) if g is not None else 0.0
            equations.append(Equation(i, label, float(theory), np.asarray(vec, float),
                                      np.array([vec[0] * 1e-9 / cx, vec[1] * 1e-9 / cy]), sigma,
                                      g_dot_u, np.asarray(s.drift_known, float)))
    return equations


# --------------------------------------------------------------------------- the fit
@dataclass
class Fit:
    cx: float                 # new calibration, m/V
    cy: float
    skew_deg: float           # deviation of the piezo axes from 90° (0 when not fitted)
    cov: np.ndarray           # covariance of (cx, cy[, skew]) — formal
    chi2_red: float
    n_equations: int
    n_scans: int
    condition: float
    metric: np.ndarray        # [[X, Z], [Z, Y]] (m²/V²)
    drift: np.ndarray = field(default_factory=lambda: np.zeros(2))       # fitted residual drift (nm/s, piezo)
    drift_cov: np.ndarray = field(default_factory=lambda: np.zeros((2, 2)))
    drift_mode: str = 'none'

    def matrix(self):
        """C (m/V): true displacement = C · volts; C = [[cx, cy·sinδ], [0, cy·cosδ]]."""
        sk = math.radians(self.skew_deg)
        return np.array([[self.cx, self.cy * math.sin(sk)], [0.0, self.cy * math.cos(sk)]])

    def true_vector(self, e):
        """Real vector (nm, piezo frame) of an equation: calibration, then drift removed."""
        v = np.asarray(e.drift_known, float) + np.asarray(self.drift, float)
        return self.matrix() @ np.asarray(e.volts, float) * 1e9 - v * e.g_dot_u

    def predict(self, e):
        return float(np.linalg.norm(self.true_vector(e)))

    def length_nm(self, volts):
        v = np.asarray(volts, float)
        g = self.metric
        q = v[0] ** 2 * g[0, 0] + v[1] ** 2 * g[1, 1] + 2 * v[0] * v[1] * g[0, 1]
        return math.sqrt(max(q, 0.0)) * 1e9

    @property
    def sigma_cx(self):
        return float(math.sqrt(max(self.cov[0, 0], 0)))

    @property
    def sigma_cy(self):
        return float(math.sqrt(max(self.cov[1, 1], 0)))


def solve(equations, fit_skew=False, scans=None) -> Fit:
    if not equations:
        raise ValueError('No lattice vectors to fit.')
    rows, rhs, weights = [], [], []
    for e in equations:
        vx, vy = e.volts
        row = [vx * vx, vy * vy] + ([2 * vx * vy] if fit_skew else [])
        rows.append(row)
        rhs.append((e.theory_nm * 1e-9) ** 2)
        # σ on L² = 2 L σ_L (relative, scale-free weighting)
        weights.append(1.0 / (2 * e.theory_nm * 1e-9 * e.sigma_nm * 1e-9 * e.theory_nm / max(
            np.linalg.norm(e.vector_nm), 1e-12)))
    A = np.asarray(rows, float)
    y = np.asarray(rhs, float)
    w = np.asarray(weights, float)
    Aw = A * w[:, None]
    yw = y * w
    scale = np.abs(Aw).max(axis=0)
    scale[scale == 0] = 1
    An = Aw / scale
    rank = np.linalg.matrix_rank(An, tol=1e-9)
    cond = float(np.linalg.cond(An)) if An.shape[0] >= An.shape[1] else float('inf')
    if rank < A.shape[1] or cond > 1e7:
        raise ValueError('The measured vectors do not constrain X and Y separately (all vectors along the same '
                         'piezo direction). Add the cell angle γ or the diagonal, scans at another scan angle '
                         '(e.g. 0° and 90°), or a lattice not aligned with the scan axes.'
                         + (' Fitting the axis skew needs ≥ 3 independent vector directions.' if fit_skew else ''))
    sol, *_ = np.linalg.lstsq(An, yw, rcond=None)
    sol = sol / scale
    X, Y = sol[0], sol[1]
    Z = sol[2] if fit_skew else 0.0
    if X <= 0 or Y <= 0 or X * Y - Z * Z <= 0:
        raise ValueError('The fit gave a non-physical calibration (negative metric). Check the reference '
                         'lattice (a, b, γ) and that the detected lattice is the expected one.')
    residual = yw - Aw @ sol
    dof = max(1, len(y) - A.shape[1])
    chi2_red = float(residual @ residual / dof)
    # Formal errors scaled by the observed scatter (Birge ratio) when there are redundant
    # equations; never scaled below the a-priori FFT-resolution errors.
    cov_sol = np.linalg.pinv(Aw.T @ Aw) * (max(chi2_red, 1.0) if len(y) > A.shape[1] else 1.0)
    cx, cy = math.sqrt(X), math.sqrt(Y)
    # propagate to (cx, cy, skew)
    J = np.zeros((3 if fit_skew else 2, len(sol)))
    J[0, 0] = 1 / (2 * cx)
    J[1, 1] = 1 / (2 * cy)
    skew = 0.0
    if fit_skew:
        s = Z / (cx * cy)
        skew = math.degrees(math.asin(max(-1, min(1, s))))
        dsk = 1 / math.sqrt(max(1e-15, 1 - s * s)) * 180 / math.pi
        J[2, 2] = dsk / (cx * cy)
        J[2, 0] = dsk * (-Z / (2 * X * cy * cx))
        J[2, 1] = dsk * (-Z / (2 * Y * cx * cy))
    cov = J @ cov_sol @ J.T
    n_scans = len({e.scan for e in equations})
    return Fit(cx, cy, skew, cov, chi2_red, len(y), n_scans, cond, np.array([[X, Z], [Z, Y]]))


class DriftNotSeparable(ValueError):
    pass


def refine(equations, start: Fit, fit_skew=False, fit_drift=False) -> Fit:
    """Non-linear least squares on the lengths, with the known drift of each scan removed and
    (optionally) one residual drift velocity fitted for the whole session.

    Model of a vector:  u_true = C · V  −  v · (g · u)      (piezo frame)
    C = calibration matrix, V = vector / previous calibration, v = drift velocity, g · u =
    time elapsed while the tip travelled along the vector in the image.
    """
    from scipy.optimize import least_squares
    p0 = [start.cx * 1e9, start.cy * 1e9] + ([start.skew_deg] if fit_skew else []) + \
         ([0.0, 0.0] if fit_drift else [])
    n_cal = 3 if fit_skew else 2

    def unpack(p):
        f = Fit(p[0] * 1e-9, p[1] * 1e-9, p[2] if fit_skew else 0.0, np.zeros((2, 2)), 0, len(equations), 0, 0,
                np.zeros((2, 2)))
        if fit_drift:
            f.drift = np.array(p[n_cal:n_cal + 2], float)
        return f

    def residuals(p):
        f = unpack(p)
        return np.array([(f.predict(e) - e.theory_nm) / (e.sigma_nm * e.theory_nm / max(
            np.linalg.norm(e.vector_nm), 1e-12)) for e in equations])
    result = least_squares(residuals, p0, method='lm' if len(equations) > len(p0) else 'trf', x_scale='jac')
    J = result.jac
    dof = len(equations) - len(p0)
    if dof < 0:
        raise DriftNotSeparable('more unknowns than measured vectors')
    sv = np.linalg.svd(J, compute_uv=False)
    cond = float(sv[0] / max(sv[-1], 1e-300))
    chi2 = float(result.fun @ result.fun / max(dof, 1))
    cov = np.linalg.pinv(J.T @ J) * (max(chi2, 1.0) if dof > 0 else 1.0)
    if fit_drift and (cond > 1e8 or not np.all(np.isfinite(cov))):
        raise DriftNotSeparable('the drift cannot be separated from the calibration with these scans')
    f = unpack(result.x)
    g = np.zeros((3 if fit_skew else 2, 3 if fit_skew else 2))
    g[:n_cal, :n_cal] = cov[:n_cal, :n_cal]
    g[0, :] *= 1e-9
    g[:, 0] *= 1e-9
    g[1, :] *= 1e-9
    g[:, 1] *= 1e-9
    f.cov = g
    f.chi2_red = chi2
    f.n_scans = len({e.scan for e in equations})
    f.condition = cond
    m = f.matrix()
    f.metric = m.T @ m
    if fit_drift:
        f.drift_cov = cov[n_cal:n_cal + 2, n_cal:n_cal + 2]
        f.drift_mode = 'fitted'
    else:
        f.drift_mode = 'known' if any(np.any(e.drift_known) for e in equations) else 'none'
    return f


def calibrate(scans, ref: Reference, fit_skew=False, fallback=(None, None), iterations=3,
              fit_drift=False, extra_drift=None) -> tuple[Fit, list]:
    """Fit, re-assign a/b with the fitted correction, fit again (a ≠ b references).

    ``extra_drift`` (nm/s, piezo) is added to every scan's known drift (used to apply a
    session drift fitted on all scans to subsets / single scans).
    """
    if extra_drift is not None and np.any(extra_drift):
        scans = [replace_drift(s, np.asarray(s.drift_known) + np.asarray(extra_drift)) for s in scans]
    use_drift = fit_drift or any(np.any(s.drift_known) for s in scans)
    guess = (1.0, 1.0)
    fit = equations = None
    for _ in range(max(1, iterations)):
        equations = build_equations(scans, ref, guess, fallback)
        drift_ok = use_drift and all(s.time_gradient is not None for s in scans)
        try:
            fit = solve(equations, fit_skew)
        except ValueError:
            if not drift_ok:
                raise
            # strongly drifted data: start the non-linear fit from the previous calibration
            c0 = (np.median([s.cx_old or fallback[0] for s in scans]), np.median([s.cy_old or fallback[1] for s in scans]))
            fit = Fit(c0[0], c0[1], 0.0, np.zeros((2, 2)), 0, 0, 0, 0, np.diag([c0[0] ** 2, c0[1] ** 2]))
        if drift_ok:
            fit = refine(equations, fit, fit_skew, fit_drift)
        cx_ref = np.median([s.cx_old or fallback[0] for s in scans])
        cy_ref = np.median([s.cy_old or fallback[1] for s in scans])
        new_guess = (fit.cx / cx_ref, fit.cy / cy_ref)
        if np.allclose(new_guess, guess, rtol=1e-6):
            break
        guess = new_guess
        if ref.square_like:
            break
    return fit, equations


def replace_drift(scan, drift):
    import dataclasses
    return dataclasses.replace(scan, drift_known=np.asarray(drift, float))


# --------------------------------------------------------------------------- statistics
def per_scan_fits(scans, ref, fallback=(None, None), extra_drift=None):
    """Independent X/Y fit of every scan that constrains both axes on its own (session drift fixed)."""
    out = []
    for i, s in enumerate(scans):
        try:
            f, _ = calibrate([s], ref, False, fallback, extra_drift=extra_drift)
            out.append((i, f))
        except ValueError:
            out.append((i, None))
    return out


def bootstrap(scans, ref, fit_skew=False, fallback=(None, None), repeats=400, seed=7, fit_drift=False):
    """Resample whole scans with replacement (keeps the a, b, diagonal correlation of a scan)."""
    if len(scans) < 3 or repeats <= 0:
        return np.empty((0, 2))
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(int(repeats)):
        pick = rng.integers(0, len(scans), len(scans))
        try:
            f, _ = calibrate([scans[j] for j in pick], ref, fit_skew, fallback, fit_drift=fit_drift)
            out.append((f.cx, f.cy))
        except ValueError:
            continue
    return np.asarray(out, float).reshape(-1, 2)


def leave_one_out(scans, ref, fit_skew=False, fallback=(None, None), fit_drift=False):
    """Predict every scan's lattice with the calibration fitted on the *other* scans.

    Returns rows (scan index, label, theory nm, before nm, after nm) — an honest test,
    the scan being evaluated never takes part in its own calibration.
    """
    rows = []
    if len(scans) < 2:
        return rows
    for i in range(len(scans)):
        others = [s for j, s in enumerate(scans) if j != i]
        try:
            f, _ = calibrate(others, ref, fit_skew, fallback, fit_drift=fit_drift)
        except ValueError:
            try:     # the remaining scans may not separate the drift: keep the calibration-only fit
                f, _ = calibrate(others, ref, fit_skew, fallback)
            except ValueError:
                continue
        guess = (f.cx / (scans[i].cx_old or fallback[0]), f.cy / (scans[i].cy_old or fallback[1]))
        for e in build_equations([scans[i]], ref, guess, fallback):
            rows.append((i, e.label, e.theory_nm, float(np.linalg.norm(e.vector_nm)), f.predict(e)))
    return rows


def corrected_basis_image(scan: ScanLattice, fit: Fit, fallback=(None, None)):
    """Lattice basis of ``scan`` after recalibration (and drift removal), image frame (nm).

    Returns (basis, M) with basis = M · measured basis, M the image-frame correction matrix.
    """
    cx = scan.cx_old or fallback[0]
    cy = scan.cy_old or fallback[1]
    r = rotation(scan.angle_deg)
    k = fit.matrix() @ np.diag([1 / cx, 1 / cy])            # piezo frame, old nm → true nm
    m = r.T @ k @ r
    v = np.asarray(scan.drift_known, float) + np.asarray(fit.drift, float)
    if scan.time_gradient is not None and np.any(v):
        m = m - np.outer(r.T @ v, np.asarray(scan.time_gradient, float))
    return m @ np.asarray(scan.basis_image_nm, float), m


def cell_parameters(basis):
    b = np.asarray(basis, float)
    a_vec, b_vec = b[:, 0], b[:, 1]
    a, bl = float(np.linalg.norm(a_vec)), float(np.linalg.norm(b_vec))
    gamma = math.degrees(math.acos(max(-1, min(1, float(a_vec @ b_vec) / max(a * bl, 1e-15)))))
    return a, bl, gamma


def gamma_error(gamma_meas, gamma_ref):
    """Angle error modulo the a/b sign ambiguity (γ ≡ 180° − γ)."""
    if gamma_ref is None:
        return None
    return min(abs(gamma_meas - gamma_ref), abs((180 - gamma_meas) - gamma_ref))
