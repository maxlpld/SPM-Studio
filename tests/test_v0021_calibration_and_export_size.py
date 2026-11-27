"""v0.0.21: Z calibration from monatomic steps, X/Y from the Au(111) herringbones, export file-size preview."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'scripts' / 'microscope_calibration'


# ------------------------------------------------------------------ calibration tool 1.4
def test_calibration_manifest_offers_herringbones_and_z():
    from spm_studio.core.registry import load_manifest
    m = load_manifest(TOOL / 'module.json')
    assert m.version == '1.4.0'
    for key in ('xy_method', 'z_calibration', 'z_channel', 'step_height_angstrom', 'herringbone_period_angstrom',
                'previous_cz_nm_per_v', 'max_step_profiles', 'accept_multiple_steps'):
        assert key in m.parameters, key
    # every 1.3 setting is still there (no option removed)
    for key in ('material', 'a_angstrom', 'b_angstrom', 'gamma_deg', 'diagonal_angstrom', 'auto_match_cell',
                'previous_cx_nm_per_v', 'previous_cy_nm_per_v', 'override_metadata', 'traces', 'fit_axis_skew',
                'drift_mode', 'max_deviation_percent', 'bootstrap_repeats', 'scan_colormap', 'vector_a_color',
                'vector_b_color', 'calibration_color', 'lattice_legend_corner', 'calibration_legend_corner',
                'figure_title'):
        assert key in m.parameters, key
    assert m.selection['tools'] == ['rectangle', 'line'] and m.selection['multiple'] is True
    assert m.snapshot_parameter_channels == ('z_channel',)
    readme = (TOOL / 'README.md').read_text(encoding='utf8')
    assert 'Barth' in readme and 'herringbone' in readme.lower() and 'monatomic' in readme.lower()
    for name in ('z_steps.py', 'z_report.py', 'herringbone.py'):
        assert (TOOL / name).is_file()


def test_existing_unedited_calibration_tool_is_upgraded(tmp_path, monkeypatch):
    from spm_studio.core import paths
    scripts = tmp_path / 'scripts'
    old = scripts / 'microscope_calibration'
    old.mkdir(parents=True)
    # an installed 1.3.0 copy: files matching the shipped digests (simulated with known content)
    contents = {name: f'old {name}\n'.encode() for name in paths.CALIBRATION_V13_SHA256}
    for name, data in contents.items():
        (old / name).write_bytes(data)
    patched = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    patched['README.md'] = 'not-this-one'                 # the user edited the README
    monkeypatch.setattr(paths, 'CALIBRATION_V13_SHA256', patched)
    monkeypatch.setattr(paths, 'scripts_dir', lambda: scripts)
    notes = paths.upgrade_factory_calibration_v0021()
    assert (old / 'module.json').read_bytes() == (TOOL / 'module.json').read_bytes()
    assert (old / 'z_steps.py').is_file() and (old / 'herringbone.py').is_file()
    assert (old / 'README.md').read_bytes() == contents['README.md']          # edit kept
    assert any('edited copy was kept' in n for n in notes)
    assert (scripts / '.factory_backups_v0021' / 'microscope_calibration' / 'module.py').is_file()
    # a removed tool is not brought back
    shutil.rmtree(old)
    assert paths.upgrade_factory_calibration_v0021() == [] and not old.exists()


def test_calibration_tool_tests_include_steps_and_herringbones():
    text = (TOOL / 'test_module.py').read_text(encoding='utf8')
    for name in ('test_end_to_end_z_calibration_from_steps', 'test_end_to_end_herringbone_xy_and_steps_z',
                 'test_herringbone_dual_cell_recovers_known_xy_distortion'):
        assert name in text


# ------------------------------------------------------------------ export size preview
def test_human_size_and_descriptions():
    from spm_studio.core.export_estimate import human_size, describe_publication, describe_animation, page_pixels
    assert human_size(512) == '512 B' and human_size(2_345_678) == '2.3 MB' and human_size(150_000) == '150 kB'
    text = describe_publication({'sizes': {'png': 4_000_000, 'svg': 120_000}, 'size_px': [800, 600]})
    assert text.startswith('SVG 120 kB · PNG 4.0 MB') and 'total' in text and '800 × 600 px' in text
    assert 'GIF ≈ 1.5 MB' in describe_animation({'gif_bytes': 1_500_000, 'frames': 30, 'size_px': [720, 720]})
    assert page_pixels({'width_mm': 25.4, 'height_mm': 50.8, 'dpi': 300}) == (300, 600)


def _layers():
    rng = np.random.default_rng(0)
    y, x = np.mgrid[0:128, 0:128]
    return [NS(name='Z', data=np.sin(x / 7.) + rng.normal(0, .2, x.shape), palette='gray', gamma=1.0),
            NS(name='Bias', data=np.cos((x + y) / 11.) + rng.normal(0, .2, x.shape), palette='viridis', gamma=1.0)]


@pytest.mark.parametrize('opts', [dict(duration_s=2, fps=10, max_px=360),
                                  dict(duration_s=3, fps=20, max_px=480, labels=False, hold_fraction=.3)])
def test_gif_size_estimate_matches_the_written_file(tmp_path, opts):
    from spm_studio.core import channel_overlay as co
    geo = NS(size_m=(40e-9, 40e-9))
    est = co.estimate_overlay_animation_size(_layers(), geo, **opts)
    written = co.save_overlay_animation(_layers(), geo, tmp_path / 'a.gif', **opts)
    real = written[0].stat().st_size
    assert est['gif_bytes'] == pytest.approx(real, rel=.2), (est, real)
    meta = json.loads((tmp_path / 'a.gif.json').read_text())
    assert est['frames'] == meta['frames'] and est['size_px'] == meta['size_px']


@pytest.fixture(scope='module')
def app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def _scan():
    from spm_studio.core.models import Scan, Channel, Geometry
    rng = np.random.default_rng(1)
    geo = Geometry((96, 96), (30e-9, 30e-9))
    ch = Channel('Z', 'm', {'forward': rng.normal(0, 1e-10, (96, 96))}, geo)
    path = Path(__file__).resolve()
    return Scan(path, {'Z': ch}, {})


def test_publication_size_estimate_is_the_real_export_size(app, tmp_path):
    from spm_studio.core.export_estimate import estimate_publication_sizes
    from spm_studio.core.export_layout import export_publication_formats
    from spm_studio.core.models import ImageStyle
    scan = _scan()
    spec = {'kind': 'channel', 'channel': 'Z', 'trace': 'forward', 'title': 'Z', 'unit': '',
            'colorbar_position': 'below', 'show_colorbar': True, 'style': ImageStyle(), 'steps': []}
    from spm_studio.core.presets import validate_export, DEFAULT_EXPORT
    preset = validate_export({**DEFAULT_EXPORT, 'width_mm': 60, 'height_mm': 55, 'dpi': 300})
    est = estimate_publication_sizes(scan, [dict(spec)], preset, ['png', 'svg'])
    files = export_publication_formats(scan, [dict(spec)], tmp_path / 'fig', preset, ['png', 'svg'])
    real = {Path(f).suffix[1:]: Path(f).stat().st_size for f in files}
    assert est['sizes']['svg'] == pytest.approx(real['svg'], rel=.02)
    assert est['sizes']['png'] == pytest.approx(real['png'], rel=.02)
    assert est['size_px'] and est['size_px'][0] > 100


def test_export_dialog_shows_live_size(app):
    from spm_studio.ui.export_dialog import PublicationDialog
    calls = []

    def estimator(dialog, done):
        calls.append(dialog.page_dpi.value())
        done({'sizes': {'svg': 50_000, 'png': 3_000_000}, 'size_px': [1000, 900]}, '')
    dialog = PublicationDialog(_scan(), (), selected_channel='Z', formats=('svg', 'png'), size_estimator=estimator)
    dialog._run_size_estimate()
    assert 'SVG 50 kB' in dialog.size_label.text() and 'PNG 3.0 MB' in dialog.size_label.text()
    dialog.page_dpi.setValue(600)
    assert dialog._size_timer.isActive()            # a change schedules a new estimate
    dialog._run_size_estimate()
    assert calls[-1] == 600
    dialog.reject()
    dialog._run_size_estimate()                     # nothing happens once closed
    assert calls[-1] == 600 and len(calls) == 2
    # without an estimator the dialog is unchanged
    plain = PublicationDialog(_scan(), (), selected_channel='Z')
    assert plain.size_label.isHidden()
    plain.reject()


def test_gif_panel_has_size_preview(app):
    from spm_studio.ui.module_panel import ModulePanel
    panel = ModulePanel()
    requests = []
    panel.gifEstimateRequested.connect(requests.append)
    panel.module = NS(id='channel_overlay')
    panel.gif_fps.setValue(12)
    assert panel._gif_estimate_timer.isActive()
    panel._gif_estimate_timer.timeout.emit()
    assert requests and requests[-1]['fps'] == 12 and requests[-1]['max_px'] == int(panel.gif_size.currentData())
    panel.set_gif_estimate('GIF ≈ 1.0 MB')
    assert panel.gif_size_estimate.text() == 'GIF ≈ 1.0 MB'
