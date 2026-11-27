"""Synthetic tests: known distortion in → known calibration out.

Run from the Scripts folder with the Python of SPM Studio:
    python -m pytest microscope_calibration/test_module.py -q
The end-to-end test needs the "Lattice measurements" tool next to this folder.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import calibration_core as cc  # noqa: E402

KBR = cc.Reference(0.4667, 0.4667, 90.0, None, 'KBr')
TRUE = (1.08e-8, 0.95e-8)     # real piezo constants (m/V)
OLD = (1.00e-8, 1.00e-8)      # constants used during acquisition


def lattice_scan(angle, rotation_deg, old=OLD, true=TRUE, ref=KBR, noise=0.0, seed=0, name='s'):
    """Lattice vectors as an image would show them with the *old* calibration."""
    t = math.radians(rotation_deg)
    g = math.radians(ref.gamma_deg or 90)
    a = ref.a_nm * np.array([math.cos(t), math.sin(t)])
    b = ref.b_nm * np.array([math.cos(t + g), math.sin(t + g)])
    apparent = np.diag([old[0] / true[0], old[1] / true[1]]) @ np.column_stack([a, b])
    image = cc.rotation(angle).T @ apparent
    image = image * (1 + np.random.default_rng(seed).normal(0, noise, (2, 2)))
    return cc.ScanLattice(name, image, angle, old[0], old[1], (20.0, 20.0), (256, 256))


def test_recovers_known_calibration_from_scans_at_0_and_90_degrees():
    scans = [lattice_scan(a, r, noise=.002, seed=i) for i, (a, r) in enumerate(((0, 10), (0, 37), (90, 12), (90, -25)))]
    fit, equations = cc.calibrate(scans, KBR)
    assert fit.cx == pytest.approx(TRUE[0], rel=5e-3)
    assert fit.cy == pytest.approx(TRUE[1], rel=5e-3)
    assert len(equations) == 16          # a, b and two diagonals per scan


def test_lattice_at_45_degrees_needs_the_diagonals():
    scan = lattice_scan(0, 45)
    no_angle = cc.Reference(0.4667, 0.4667, None)
    with pytest.raises(ValueError, match='constrain X and Y separately'):
        cc.calibrate([scan], no_angle)
    fit, _ = cc.calibrate([scan], KBR)    # γ = 90° adds |a ± b|, along X and Y
    assert fit.cx == pytest.approx(TRUE[0], rel=1e-6)
    assert fit.cy == pytest.approx(TRUE[1], rel=1e-6)


def test_different_previous_calibrations_are_handled_per_scan():
    s1 = lattice_scan(0, 10, old=(1.0e-8, 1.0e-8))
    s2 = lattice_scan(90, 20, old=(1.2e-8, 0.9e-8))
    fit, _ = cc.calibrate([s1, s2], KBR)
    assert fit.cx == pytest.approx(TRUE[0], rel=1e-6) and fit.cy == pytest.approx(TRUE[1], rel=1e-6)


def test_rectangular_and_hexagonal_references():
    rect = cc.Reference(0.40, 0.55, 90.0)
    scans = [lattice_scan(0, 15, ref=rect), lattice_scan(90, 15, ref=rect)]
    fit, _ = cc.calibrate(scans, rect)
    assert fit.cx == pytest.approx(TRUE[0], rel=1e-6) and fit.cy == pytest.approx(TRUE[1], rel=1e-6)
    hexa = cc.Reference(0.2461, 0.2461, 120.0)
    fit, _ = cc.calibrate([lattice_scan(0, 7, ref=hexa)], hexa)
    assert fit.cx == pytest.approx(TRUE[0], rel=1e-6) and fit.cy == pytest.approx(TRUE[1], rel=1e-6)


def test_corrected_basis_matches_the_reference():
    scans = [lattice_scan(0, 10), lattice_scan(90, 30)]
    fit, _ = cc.calibrate(scans, KBR)
    for s in scans:
        basis, _m = cc.corrected_basis_image(s, fit)
        a, b, gamma = cc.cell_parameters(basis)
        assert a == pytest.approx(.4667, rel=1e-6) and b == pytest.approx(.4667, rel=1e-6)
        assert gamma == pytest.approx(90, abs=1e-4)


def test_axis_skew_is_detected():
    skew = math.radians(1.5)
    def skewed(angle, rot):
        s = lattice_scan(angle, rot, true=(1e-8, 1e-8))
        # apparent ← true through a sheared metric: true = S · apparent
        S = np.array([[1, 0], [math.sin(skew), math.cos(skew)]])
        r = cc.rotation(angle)
        s.basis_image_nm = r.T @ np.linalg.inv(S) @ r @ s.basis_image_nm
        return s
    scans = [skewed(0, 10), skewed(0, 35), skewed(90, 20), skewed(90, 50)]
    fit, _ = cc.calibrate(scans, KBR, fit_skew=True)
    assert fit.skew_deg == pytest.approx(1.5, abs=.05)


def test_leave_one_out_and_bootstrap_statistics():
    scans = [lattice_scan(a, r, noise=.003, seed=i) for i, (a, r) in
             enumerate(((0, 5), (0, 25), (90, 15), (90, 40), (0, 60)))]
    rows = cc.leave_one_out(scans, KBR)
    before = np.array([r[3] / r[2] - 1 for r in rows])
    after = np.array([r[4] / r[2] - 1 for r in rows])
    assert np.sqrt(np.mean(after ** 2)) < np.sqrt(np.mean(before ** 2)) / 5
    boot = cc.bootstrap(scans, KBR, repeats=60)
    assert len(boot) > 50 and boot[:, 0].std() < 2e-10


def test_header_calibration_and_reference_parameters():
    h = {'PIEZO CONFIGURATION>CALIB. X (M/V)': '1.25E-8', 'PIEZO CONFIGURATION>CALIB. Y (M/V)': '1.30E-8',
         'PIEZO CONFIGURATION>HV GAIN X': '14', 'Z-CONTROLLER>SETPOINT': '1E-11'}
    found = cc.calibration_from_header(h)
    assert found['cx'] == 1.25e-8 and found['cy'] == 1.30e-8 and found['hv_gain'] == {'X': 14.0}
    assert cc.calibration_from_header({'X CALIBRATION (NM/V)': '12.5'})['cx'] == pytest.approx(1.25e-8)
    ref = cc.reference_from_parameters({'material': 'KBr(001) — Br–Br (or K–K) square cell'})   # old label
    assert ref.a_nm == pytest.approx(.665) and ref.gamma_deg == 90
    assert any('Hinaut' in n for n in ref.notes) and any('half diagonal' in n for n in ref.notes)
    chosen, why, _ = cc.choose_reference([(0.47, 0.468, 90.)], ref, .25)
    assert chosen.a_nm == pytest.approx(.665 / math.sqrt(2)) and 'a/√2' in why
    bad = cc.reference_from_parameters({'material': 'Custom', 'a_angstrom': 6.65, 'gamma_deg': 90,
                                        'diagonal_angstrom': 5.5})
    assert any('ignored' in n for n in bad.notes)
    ref = cc.reference_from_parameters({'material': 'Custom', 'a_angstrom': 4.0, 'b_angstrom': 5.0, 'gamma_deg': 90})
    assert (ref.a_nm, ref.b_nm) == (.4, .5)
    with pytest.raises(ValueError):
        cc.reference_from_parameters({'material': 'Custom'})


def test_conventional_constant_is_recognised():
    # The case of the first real run: a0 = 6.65 Å typed, image shows the a0/√2 surface cell.
    entered = cc.reference_from_parameters({'material': 'Custom', 'a_angstrom': 6.65, 'gamma_deg': 90})
    cells = [(0.4194, 0.4056, 87.4)]
    chosen, why, dev = cc.choose_reference(cells, entered, .25)
    assert chosen.a_nm == pytest.approx(.665 / math.sqrt(2)) and 'a/√2' in why and dev < .15
    assert chosen.diagonals()[0] == pytest.approx(.665)
    same, why, _ = cc.choose_reference(cells, entered, .25, automatic=False)
    assert same is entered
    # a correct entry is kept as it is
    kept, why, _ = cc.choose_reference([(0.46, 0.47, 90.)], KBR, .25)
    assert kept is KBR and why == 'as entered'
    # hexagonal: (√3×√3) description
    hexa = cc.Reference(0.2461, 0.2461, 120.0)
    chosen, why, _ = cc.choose_reference([(0.425, 0.427, 119.)], hexa, .25)
    assert chosen.a_nm == pytest.approx(.2461 * math.sqrt(3))
    # far from every description: nothing invented
    chosen, why, dev = cc.choose_reference([(0.30, 0.31, 90.)], entered, .25)
    assert chosen is entered and dev > .25


def test_no_scan_message_explains_numbers():
    import module
    entered = cc.Reference(.665, .665, 90.0)
    text = module._no_scan_message(entered, [('scan_1 · forward', (.25, .26, 88.))], .25)
    assert '2.500 × 2.600 Å' in text and '6.6500' in text and 'a0/√2' in text


# ------------------------------------------------------------------ drift
def drifted_scan(angle, rotation_deg, direction, v_nm_s, line_time=(1.0, 1.0), size=20.0, rows=256,
                 old=OLD, true=TRUE, ref=KBR, header=None, name='d'):
    """Lattice as measured with a constant drift v (piezo frame) and the old calibration."""
    t = math.radians(rotation_deg)
    g_ = math.radians(ref.gamma_deg or 90)
    u_true = np.column_stack([ref.a_nm * np.array([math.cos(t), math.sin(t)]),
                              ref.b_nm * np.array([math.cos(t + g_), math.sin(t + g_)])])
    g_img = cc.time_gradient('forward', direction, (size, size), (rows, rows), line_time)
    r = cc.rotation(angle)
    K = np.diag([true[0] / old[0], true[1] / old[1]])
    M = K - np.outer(np.asarray(v_nm_s, float), r @ g_img)      # u_true = M · u_piezo
    u_piezo = np.linalg.solve(M, u_true)
    s = cc.ScanLattice(name, r.T @ u_piezo, angle, old[0], old[1], (size, size), (rows, rows), direction,
                       'forward', False, {'line_time': line_time, 'header_drift': header and header[0],
                                          'drift_status': header and header[1]}, time_gradient=g_img)
    return s


V = np.array([0.0012, -0.002])      # nm/s ≈ 0.07 / −0.12 nm/min: 0.6 / 1 nm over a 512 s frame


def test_time_gradient_signs():
    down = cc.time_gradient('forward', 'down', (20, 20), (256, 256), (1.0, 1.0))
    up = cc.time_gradient('forward', 'up', (20, 20), (256, 256), (1.0, 1.0))
    back = cc.time_gradient('backward', 'down', (20, 20), (256, 256), (1.0, 1.0))
    assert down[0] == pytest.approx(.05) and down[1] == pytest.approx(-25.6) and up[1] == pytest.approx(25.6)
    assert back[0] == pytest.approx(-.05)
    assert cc.time_gradient('forward', '', (20, 20), (256, 256), (1, 1)) is None


def test_drift_biases_the_calibration_and_is_recovered():
    scans = [drifted_scan(a, r, d, V, name=f'{a}{d}') for a, r, d in
             ((0, 10, 'up'), (0, 10, 'down'), (90, 25, 'up'), (90, 25, 'down'))]
    plain = [cc.replace_drift(s, np.zeros(2)) for s in scans]
    biased, _ = cc.calibrate([s for s in plain if s.slow_direction == 'down'], KBR)
    assert abs(biased.cx / TRUE[0] - 1) > .002 or abs(biased.cy / TRUE[1] - 1) > .002
    fit, _ = cc.calibrate(scans, KBR, fit_drift=True)
    assert fit.cx == pytest.approx(TRUE[0], rel=1e-5) and fit.cy == pytest.approx(TRUE[1], rel=1e-5)
    assert fit.drift == pytest.approx(V, abs=1e-5) and fit.drift_mode == 'fitted'
    basis, _m = cc.corrected_basis_image(scans[0], fit)
    a, b, gamma = cc.cell_parameters(basis)
    assert a == pytest.approx(.4667, rel=1e-5) and gamma == pytest.approx(90, abs=1e-3)


def test_updown_pair_measures_drift_without_the_reference():
    up = drifted_scan(0, 10, 'up', V, name='u')
    down = drifted_scan(0, 10, 'down', V, name='d')
    r = cc.pair_drift(up, down, (TRUE[0] / OLD[0], TRUE[1] / OLD[1]))
    assert r['drift'] == pytest.approx(V, rel=1e-6) and r['relative_residual'] < 1e-8
    approx = cc.pair_drift(up, down, (1.0, 1.0))            # calibration unknown: still within ~10 %
    assert approx['drift'] == pytest.approx(V, rel=.12)
    assert cc.updown_pairs([up, down]) == [(0, 1)]


def test_header_compensation_is_used():
    # compensation ON with the right value → the image shows no drift; v_true = v_comp
    scans = [drifted_scan(a, r, d, np.zeros(2), header=(V, 'on'), name=f'{a}{d}') for a, r, d in
             ((0, 10, 'up'), (0, 10, 'down'), (90, 25, 'up'), (90, 25, 'down'))]
    scans = [cc.replace_drift(s, -V) for s in scans]           # what prepare_drift does (Header + fit)
    fit, _ = cc.calibrate(scans, KBR, fit_drift=True)
    assert fit.drift == pytest.approx(V, abs=1e-5)             # total sample drift
    assert fit.cx == pytest.approx(TRUE[0], rel=1e-5)
    # compensation OFF, header value known → "Header only" removes it without fitting
    off = [drifted_scan(0, 10, 'down', V, header=(V, 'off')), drifted_scan(90, 25, 'up', V, header=(V, 'off'))]
    off = [cc.replace_drift(s, V) for s in off]
    fit, _ = cc.calibrate(off, KBR)
    assert fit.cx == pytest.approx(TRUE[0], rel=1e-5) and fit.drift_mode == 'known'


def test_drift_header_parsing():
    h = {'SCAN_TIME': '1.250E+0 1.250E+0', 'PIEZO CONFIGURATION>DRIFT X (M/S)': '2.0E-11',
         'PIEZO CONFIGURATION>DRIFT Y (M/S)': '-1.0E-11', 'PIEZO CONFIGURATION>DRIFT CORRECTION STATUS (ON/OFF)': 'ON',
         'REC_DATE': '15.04.2026', 'REC_TIME': '10:22:33', 'SCAN_OFFSET': '1.0E-9 2.0E-9'}
    a = cc.acquisition_from_header(h)
    assert a['line_time'] == (1.25, 1.25) and a['drift'] == pytest.approx([.02, -.01])
    assert cc.compensation_on(a['drift_status']) is True and a['timestamp'] and a['offset_nm'] == pytest.approx((1, 2))


def test_single_scan_cannot_separate_drift():
    with pytest.raises(ValueError):
        cc.calibrate([drifted_scan(0, 10, 'down', V)], KBR, fit_drift=True)


# ------------------------------------------------------------------ end to end (real files)
def _write_sxm(path, image, size_nm, angle, cx, cy, direction='down', line_time=1.0):
    ny, nx = image.shape
    if direction == 'up':
        image = image[::-1]          # stored in acquisition order; the reader flips it back
    header = '\r\n'.join([
        ':SCAN_TIME:', f'{line_time:.3E} {line_time:.3E}',
        ':SCAN_PIXELS:', f'{nx} {ny}', ':SCAN_RANGE:', f'{size_nm * 1e-9:.6E} {size_nm * 1e-9:.6E}',
        ':SCAN_OFFSET:', '0 0', ':SCAN_ANGLE:', f'{angle}', ':SCAN_DIR:', direction,
        ':Piezo Configuration>Calib. X (m/V):', f'{cx:.6E}', ':Piezo Configuration>Calib. Y (m/V):', f'{cy:.6E}',
        ':SCANIT_TYPE:', 'FLOAT MSBFIRST', ':DATA_INFO:', 'Channel\tName\tUnit\tDirection\tCalibration\tOffset',
        '14\tZ\tm\tboth\t1\t0', ':SCANIT_END:']) + '\r\n'
    raw = (np.concatenate([image.ravel(), image[:, ::-1].ravel()]) * 1e-10).astype('>f4')
    path.write_bytes(header.encode('latin-1') + b'\x1a\x04' + raw.tobytes())


def _image(angle, rotation_deg, n=256, size=20.0, old=OLD, true=TRUE, direction='down', drift=(0, 0), line=1.0):
    x = (np.arange(n) + .5) * size / n - size / 2
    X, Y = np.meshgrid(x, x[::-1])                  # image frame, +y up (row 0 at the top)
    rows, cols = np.mgrid[0:n, 0:n]
    line_index = rows if direction == 'down' else (n - 1 - rows)
    t = line_index * 2 * line + (cols + .5) / n * line          # acquisition time of each pixel
    r = cc.rotation(angle)
    px = r[0, 0] * X + r[0, 1] * Y                  # apparent piezo coordinates
    py = r[1, 0] * X + r[1, 1] * Y
    tx = px * true[0] / old[0] - drift[0] * t       # where the sample really was
    ty = py * true[1] / old[1] - drift[1] * t
    t = math.radians(rotation_deg)
    k1 = np.array([math.cos(t), math.sin(t)]) / .4667
    k2 = np.array([-math.sin(t), math.cos(t)]) / .4667
    return np.cos(2 * np.pi * (k1[0] * tx + k1[1] * ty)) + np.cos(2 * np.pi * (k2[0] * tx + k2[1] * ty))


def test_end_to_end_with_open_files(tmp_path, monkeypatch):
    lattice_tool = HERE.parent / 'lattice_measurements'
    if not (lattice_tool / 'roi_pipeline.py').is_file():
        pytest.skip('Lattice measurements tool not installed next to this one')
    pytest.importorskip('skimage')
    pytest.importorskip('spm_studio')
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from spm_studio.core.io import read_scan
    from spm_studio.core.module_api import ModuleContext
    import module
    files = []
    drift = (0.0, 0.0006)            # nm/s along Y: 0.036 nm/min, ≈ 0.5 % distortion of the slow axis
    for i, (angle, rot, direction) in enumerate(((0, 10, 'down'), (0, 10, 'up'), (90, 20, 'up'), (90, 20, 'down'))):
        path = tmp_path / f'kbr_{i}.sxm'
        _write_sxm(path, _image(angle, rot, direction=direction, drift=drift), 20.0, angle, *OLD, direction)
        files.append(path)
    scan = read_scan(files[0])
    ch = scan.channels['Z']
    out = tmp_path / 'run'
    out.mkdir()
    params = {'material': 'Custom', 'a_angstrom': 6.60, 'gamma_deg': 90.0, 'diagonal_angstrom': 0,
              'traces': 'Active trace only',
              'bootstrap_repeats': 50, 'max_deviation_percent': 25.0}
    ctx = ModuleContext(files[0], 'Z', 'forward', ch.traces['forward'], 'm', ch.geometry, scan.metadata, params, out,
                        files, {f'Z|{t}': a for t, a in ch.traces.items()}, None, [], {}, [],
                        {'schema_version': 1}, ('svg',), {})
    events = []
    monkeypatch.setattr(ctx, 'log', lambda m, level='info': events.append(m))
    monkeypatch.setattr(ctx, 'progress', lambda *a, **k: None)
    monkeypatch.setattr(ctx, 'result_file', lambda *a, **k: None)
    monkeypatch.setattr(ctx, 'result_table', lambda *a, **k: None)
    result = module.run(ctx)
    print('\n'.join(map(str, events)))
    import json
    doc = json.loads(Path(result).read_text())
    assert len(doc['scans']) == 4, events
    assert 'a/√2' in doc['reference']['interpretation']      # 6.60 Å typed → 4.667 Å cell used
    new = doc['new_calibration_m_per_V']
    assert new['x'] == pytest.approx(TRUE[0], rel=.003)
    assert new['y'] == pytest.approx(TRUE[1], rel=.003)
    assert (out / 'calibration_statistics.svg').is_file()
    # Export-panel renderer (Qt) or, if it is unavailable, the Matplotlib fallback
    assert (out / 'calibration_lattice_overlay.svg').is_file(), events
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pass
    else:      # with Qt installed the Export-panel renderer itself must work
        assert not any('renderer failed' in str(m) for m in events), events
    assert doc['active_scan']['after'][0] == pytest.approx(.4667, rel=.01)
    assert doc['drift']['mode'] == 'fitted'
    assert doc['drift']['fitted_nm_per_s'][1] == pytest.approx(drift[1], abs=2e-4)
    assert len(doc['drift']['updown_pairs']) == 2


# ------------------------------------------------------------------ v1.4: Z from monatomic steps
AU_STEP = 0.23545e-9          # m
KZ = 1.07                     # real Z constant / previous one: the file shows steps 7 % too low


def _au_topography(n=320, size=80.0, angle=0.0, direction='down', true_xy=(1.0, 1.0), drift_xy=(0.0, 0.0),
                   vz=0.0, line=1.0, herringbone=True, steps=True, step_dir_deg=35.0, step_spacing=26.0,
                   rot=20.0, zigzag=25.0, seed=0, noise=4e-12):
    """Au(111) topography in m as recorded with the previous X/Y and Z calibrations.

    Terraces separated by monatomic steps (h = 2.355 Å, shown 1/KZ too low), the herringbone
    corrugation (period 6.34 nm, irregular 25 nm zigzag, 0.2 Å), line jumps, a tilt, X/Y drift and a
    constant Z drift v_z (m/s) during the frame.
    """
    rng = np.random.default_rng(seed)
    x = (np.arange(n) + .5) * size / n - size / 2
    X, Y = np.meshgrid(x, x[::-1])
    rows, cols = np.mgrid[0:n, 0:n]
    line_index = rows if direction == 'down' else (n - 1 - rows)
    t = line_index * 2 * line + (cols + .5) / n * line
    r = cc.rotation(angle)
    px = r[0, 0] * X + r[0, 1] * Y
    py = r[1, 0] * X + r[1, 1] * Y
    tx = px * true_xy[0] - drift_xy[0] * t
    ty = py * true_xy[1] - drift_xy[1] * t
    z = np.zeros_like(X)
    if steps:
        u = math.radians(step_dir_deg)
        coord = tx * math.cos(u) + ty * math.sin(u)
        z += AU_STEP * np.floor(coord / step_spacing + .37)
        z = z + .0 * X
    if herringbone:
        a, beta = math.radians(rot), math.radians(30)
        m = np.array([math.cos(a), math.sin(a)])
        p = np.array([-math.sin(a), math.cos(a)])
        w = tx * m[0] + ty * m[1]
        v = tx * p[0] + ty * p[1]
        seg = zigzag / 2 * (1 + .3 * (rng.random(400) * 2 - 1))
        L = size * 3
        bp = np.concatenate([[-L], -L + np.cumsum(seg)])
        k = np.clip(np.searchsorted(bp, w) - 1, 0, len(seg) - 1)
        sign = np.where(k % 2 == 0, 1., -1.)
        base = np.concatenate([[0], np.cumsum(np.where(np.arange(len(seg)) % 2 == 0, 1., -1.) * seg)])
        tri = base[k] + sign * (w - bp[k])
        z += .1e-10 * np.cos(2 * np.pi * (v + math.tan(beta) * tri) * math.cos(beta) / 6.3448)
    z = z / KZ + vz * t + 3e-12 * X - 2e-12 * Y
    z += rng.normal(0, noise, z.shape) + rng.normal(0, 2e-12, (n, 1))
    return z


def _write_au_sxm(path, image, size_nm, angle=0.0, cxy=(1e-8, 1e-8), cz=2.0e-9, direction='down', line_time=1.0,
                  drift_z=None):
    ny, nx = image.shape
    if direction == 'up':
        image = image[::-1]
    lines = [':SCAN_TIME:', f'{line_time:.3E} {line_time:.3E}', ':SCAN_PIXELS:', f'{nx} {ny}',
             ':SCAN_RANGE:', f'{size_nm * 1e-9:.6E} {size_nm * 1e-9:.6E}', ':SCAN_OFFSET:', '0 0',
             ':SCAN_ANGLE:', f'{angle}', ':SCAN_DIR:', direction,
             ':Piezo Configuration>Calib. X (m/V):', f'{cxy[0]:.6E}', ':Piezo Configuration>Calib. Y (m/V):',
             f'{cxy[1]:.6E}', ':Piezo Configuration>Calib. Z (m/V):', f'{cz:.6E}']
    if drift_z is not None:
        lines += [':Piezo Configuration>Drift Z (m/s):', f'{drift_z:.3E}',
                  ':Piezo Configuration>Drift correction status (on/off):', 'OFF']
    lines += [':SCANIT_TYPE:', 'FLOAT MSBFIRST', ':DATA_INFO:', 'Channel\tName\tUnit\tDirection\tCalibration\tOffset',
              '14\tZ\tm\tboth\t1\t0', ':SCANIT_END:']
    raw = np.concatenate([image.ravel(), image[:, ::-1].ravel()]).astype('>f4')
    path.write_bytes(('\r\n'.join(lines) + '\r\n').encode('latin-1') + b'\x1a\x04' + raw.tobytes())


def test_step_detection_and_height_on_synthetic_au111():
    import z_steps as zs
    for angle in (0, 35, 90):
        z = _au_topography(step_dir_deg=angle + 10, seed=angle)
        px = 80.0 / 320
        res = zs.find_steps(z, px, px, AU_STEP)
        zs.assign_layers(res['profiles'], AU_STEP, .25)
        used = [p for p in res['profiles'] if p.used]
        assert len(used) >= 4, [p.reason for p in res['profiles']]
        h = np.array([p.h_m for p in used])
        assert np.mean(h) == pytest.approx(AU_STEP / KZ, rel=.01)
        assert res['labels'].max() >= 3


def test_z_header_and_fit_statistics():
    h = {'PIEZO CONFIGURATION>CALIB. Z (M/V)': '2.5E-9', 'PIEZO CONFIGURATION>DRIFT Z (M/S)': '1.0E-12',
         'Z-CONTROLLER>SETPOINT': '1E-10', 'PIEZO CONFIGURATION>HV GAIN Z': '4'}
    z = cc.z_calibration_from_header(h)
    assert z['cz'] == 2.5e-9 and z['drift_z_nm_per_s'] == pytest.approx(1e-3) and z['hv_gain_z'] == 4
    assert cc.z_calibration_from_header({'Z CALIBRATION (NM/V)': '3.1'})['cz'] == pytest.approx(3.1e-9)
    assert cc.calibration_from_header(h)['cx'] is None          # X/Y parsing unchanged
    import z_steps as zs
    prof = zs.StepProfile(1, (0, 0), (0, 0), (1, 1), np.zeros(3), np.zeros(3), 0, AU_STEP / KZ, 1e-13, 0, 0, 1e-12,
                          (0, 0), 0, used=True, n_layers=1)
    scan = zs.ZScan('s', '', 'forward', 0, 2e-9, (1, 1), (2, 2), 'down', True, [prof], np.zeros((2, 2)),
                    np.zeros((2, 2)), np.ones((2, 2), int), (0, 0), {})
    fit = zs.combine(zs.step_estimates([scan], AU_STEP))
    assert fit.cz == pytest.approx(2e-9 * KZ, rel=1e-9)


def test_z_drift_from_updown_pair_is_measured_and_does_not_bias_heights():
    import z_steps as zs
    vz = 4e-13                                    # m/s → 0.2 nm over a 512 s frame
    px = 80.0 / 320
    out = []
    for direction in ('up', 'down'):
        z = _au_topography(direction=direction, vz=vz, herringbone=False, seed=3)
        res = zs.find_steps(z, px, px, AU_STEP)
        zs.assign_layers(res['profiles'], AU_STEP)
        g = cc.time_gradient('forward', direction, (80.0, 80.0), z.shape, (1.0, 1.0))
        out.append(zs.ZScan(direction, '', 'forward', 0.0, 2e-9, (80.0, 80.0), z.shape, direction, False,
                            res['profiles'], res['leveled'], res['leveled'], res['labels'], res['slopes'],
                            res['offsets'], g, {'timestamp': None, 'offset_nm': None}))
        h = np.mean([p.h_m for p in res['profiles'] if p.used])
        assert h == pytest.approx(AU_STEP / KZ, rel=.01)
    pairs = zs.z_drift_pairs(out)
    assert len(pairs) == 1 and pairs[0]['vz_nm_per_s'] == pytest.approx(vz * 1e9, rel=.15)


def test_herringbone_dual_cell_recovers_known_xy_distortion():
    import herringbone as hb
    period = 6.3448
    ref = cc.Reference(hb.equivalent_cell_nm(period), hb.equivalent_cell_nm(period), 120.0, None, 'hb')
    scans = []
    for i, (rot, angle) in enumerate(((20, 0), (-35, 90), (5, 0), (50, 90), (80, 0))):
        z = _au_topography(n=420, size=110.0, angle=angle, true_xy=(TRUE[0] / OLD[0], TRUE[1] / OLD[1]),
                           steps=False, rot=rot, seed=i)
        det = hb.detect(z, 110 / 420, 110 / 420, period)
        assert abs(det['separation_deg'] - 60) < 15
        scans.append(cc.ScanLattice(f'h{i}', det['dual_basis_nm'], angle, *OLD, (110., 110.), z.shape))
    fit, _ = cc.calibrate(scans, ref)
    # the herringbone is a weaker standard than an atomic lattice: ≈ 1–2 %
    assert fit.cx == pytest.approx(TRUE[0], rel=.025) and fit.cy == pytest.approx(TRUE[1], rel=.025)


def test_herringbone_region_mask_and_not_found_message():
    import herringbone as hb
    from types import SimpleNamespace as NS
    mask, polys = hb.region_mask((100, 100), [NS(kind='line', points_px=((10, 10), (60, 12), (55, 70))),
                                              NS(kind='rectangle', points_px=((70, 70), (90, 95)))])
    assert mask[30, 40] and mask[80, 80] and not mask[90, 10] and len(polys) == 2
    flat = np.random.default_rng(0).normal(0, 1e-12, (256, 256))
    with pytest.raises(hb.HerringboneNotFound):
        hb.detect(flat, .4, .4, 6.34)


def _au_context(tmp_path, files, params, monkeypatch):
    from spm_studio.core.io import read_scan
    from spm_studio.core.module_api import ModuleContext
    scan = read_scan(files[0])
    ch = scan.channels['Z']
    out = tmp_path / 'run'
    out.mkdir(exist_ok=True)
    ctx = ModuleContext(files[0], 'Z', 'forward', ch.traces['forward'], 'm', ch.geometry, scan.metadata, params, out,
                        files, {f'Z|{t}': a for t, a in ch.traces.items()}, None, [], {}, [],
                        {'schema_version': 1}, ('svg',), {'Z': 'm'})
    events = []
    monkeypatch.setattr(ctx, 'log', lambda m, level='info': events.append(m))
    monkeypatch.setattr(ctx, 'progress', lambda *a, **k: None)
    monkeypatch.setattr(ctx, 'result_file', lambda *a, **k: None)
    monkeypatch.setattr(ctx, 'result_table', lambda *a, **k: None)
    return ctx, out, events


def test_end_to_end_z_calibration_from_steps(tmp_path, monkeypatch):
    pytest.importorskip('skimage')
    pytest.importorskip('spm_studio')
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import module
    files = []
    for i, direction in enumerate(('down', 'up')):
        path = tmp_path / f'au_steps_{i}.sxm'
        _write_au_sxm(path, _au_topography(n=256, size=70.0, direction=direction, herringbone=False, vz=2e-13,
                                           seed=10 + i), 70.0, direction=direction, drift_z=0.0)
        files.append(path)
    params = {'material': 'Au(111) (1×1)', 'xy_method': 'Off (Z only)', 'z_calibration': 'Required (stop if no '
              'step is found)', 'z_channel': 'Z', 'bootstrap_repeats': 60, 'max_deviation_percent': 25.0,
              'traces': 'Active trace only'}
    ctx, out, events = _au_context(tmp_path, files, params, monkeypatch)
    result = module.run(ctx)
    import json
    doc = json.loads(Path(result).read_text())
    assert doc['kind'] == 'spm_studio_z_calibration', events
    assert doc['new_calibration_m_per_V']['z'] == pytest.approx(2.0e-9 * KZ, rel=.012), events
    assert doc['previous_calibration_m_per_V'] == pytest.approx(2.0e-9)
    assert len(doc['drift']['updown_pairs']) == 1
    for stem in ('z_steps_scan', 'z_step_profiles', 'z_calibration_overview', 'z_calibration_statistics'):
        assert (out / f'{stem}.svg').is_file(), (stem, events)
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pass
    else:
        assert not any('renderer failed' in str(m) for m in events), events


def test_end_to_end_herringbone_xy_and_steps_z(tmp_path, monkeypatch):
    """No atomic resolution: Automatic X/Y falls back to the herringbones, Z from the steps of the same scans."""
    pytest.importorskip('skimage')
    pytest.importorskip('spm_studio')
    lattice_tool = HERE.parent / 'lattice_measurements'
    if not (lattice_tool / 'roi_pipeline.py').is_file():
        pytest.skip('Lattice measurements tool not installed next to this one')
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import module
    files = []
    for i, (angle, rot, direction) in enumerate(((0, 20, 'down'), (90, -35, 'up'), (0, 50, 'up'), (90, 80, 'down'))):
        path = tmp_path / f'au_{i}.sxm'
        image = _au_topography(n=400, size=100.0, angle=angle, direction=direction,
                               true_xy=(TRUE[0] / OLD[0], TRUE[1] / OLD[1]), rot=rot, step_spacing=40.0,
                               step_dir_deg=15 + 30 * i, seed=20 + i)
        _write_au_sxm(path, image, 100.0, angle=angle, cxy=OLD, direction=direction)
        files.append(path)
    params = {'material': 'Au(111) (1×1)', 'z_channel': 'Z', 'bootstrap_repeats': 40, 'max_deviation_percent': 25.0,
              'traces': 'Active trace only', 'drift_mode': 'No drift correction'}
    ctx, out, events = _au_context(tmp_path, files, params, monkeypatch)
    result = module.run(ctx)
    import json
    doc = json.loads(Path(result).read_text())
    assert doc['method'] == 'herringbone', events
    assert any('herringbone reconstruction instead' in str(m) for m in events)
    new = doc['new_calibration_m_per_V']
    assert new['x'] == pytest.approx(TRUE[0], rel=.03) and new['y'] == pytest.approx(TRUE[1], rel=.03), events
    assert 'Barth' in doc['herringbone']['source']
    z = doc['z_calibration']
    assert z['new_z_calibration_m_per_V'] == pytest.approx(2.0e-9 * KZ, rel=.015), events
    assert (out / 'calibration_herringbone_overlay.svg').is_file(), events
    assert (out / 'calibration_statistics.svg').is_file()
    assert (out / 'z_calibration_overview.svg').is_file()
    zdoc = json.loads((out / 'z_calibration_result.json').read_text())
    assert any(s['lateral_correction_from_xy'] for s in zdoc['scans'])
