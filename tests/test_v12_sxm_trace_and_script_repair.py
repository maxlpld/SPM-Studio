"""v12 regression: true Nanonis scan alignment and repairing stale local modules."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from spm_studio.core.io import read_scan
from spm_studio.core.sxm_native import orient_nanonis_trace
from spm_studio.core import paths


def _fixture(path: Path, direction: str, signal: np.ndarray):
    """Construct a genuinely direction-dependent acquisition-order SXM."""
    ny, nx = signal.shape
    # Each trace should represent the *same* physical image and same angle,
    # but the backwards acquisition runs right-to-left.
    stored_fwd = signal[::-1, :] if direction == 'up' else signal
    stored_back = stored_fwd[:, ::-1]
    header = ('\r\n'.join([
        ':SCAN_PIXELS:', f'{nx} {ny}', ':SCAN_RANGE:', '12e-9 8e-9',
        ':SCAN_OFFSET:', '0 0', ':SCAN_ANGLE:', '67',
        ':SCAN_DIR:', direction, ':SCANIT_TYPE:', 'FLOAT MSBFIRST',
        ':DATA_INFO:', 'Channel\tName\tUnit\tDirection\tCalibration\tOffset',
        '0\tZ\tm\tboth\t1\t0', ':SCANIT_END:'
    ]) + '\r\n').encode('latin-1')
    path.write_bytes(header + b'\x1a\x04' +
                     stored_fwd.astype('>f4').tobytes() +
                     stored_back.astype('>f4').tobytes())
    return path


@pytest.mark.parametrize('direction', ['up', 'down'])
def test_forward_backward_identical_spatial_pixels_no_rotation(tmp_path, direction):
    signal = (np.arange(6 * 8, dtype='f4').reshape(6, 8)**2 + 0.5)
    scan = read_scan(_fixture(tmp_path / 'scan.sxm', direction, signal))
    channel = scan.channels['Z']
    np.testing.assert_array_equal(channel.get('forward'), signal)
    np.testing.assert_array_equal(channel.get('backward'), signal)
    assert channel.geometry.angle_deg == 67
    assert channel.geometry.size_m == (12e-9, 8e-9)
    assert channel.get('forward').strides[0] != 0
    assert not channel.get('forward').flags.writeable
    assert not channel.get('backward').flags.writeable


def test_unchanged_gwyddion_stored_orientation(monkeypatch, tmp_path):
    import types
    raster=np.arange(5 * 6, dtype=float).reshape(5, 6)
    f=lambda array:types.SimpleNamespace(data=array, xreal=6e-9,yreal=5e-9,
         si_unit_z=types.SimpleNamespace(unitstr='m'))
    container={'/0/data': f(raster),'/0/data/title':'Z [FWD]',
               '/1/data': f(raster[:,::-1]),'/1/data/title':'Z [BWD]'}
    fake=types.SimpleNamespace(load=lambda _:container,
         util=types.SimpleNamespace(get_datafields=lambda _:{}))
    monkeypatch.setitem(sys.modules, 'gwyfile', fake)
    (tmp_path / 'test.gwy').write_bytes(b'test')
    scan=read_scan(tmp_path / 'test.gwy')
    np.testing.assert_array_equal(scan.channels['Z'].get('forward'), raster)
    np.testing.assert_array_equal(scan.channels['Z'].get('backward'), raster[:, ::-1])


def test_trace_view_is_zero_copy():
    data=np.arange(120, dtype=np.float32).reshape(10, 12)
    for name in ('up', 'down'):
        for trace in ('forward', 'backward'):
            oriented=orient_nanonis_trace(data,trace,name)
            assert np.shares_memory(oriented,data)
            assert oriented.shape == data.shape


def test_existing_install_repairs_missing_lattice_helpers_preserving_edits(monkeypatch,tmp_path):
    project = Path(__file__).resolve().parents[1]
    src = project / 'scripts'
    home=tmp_path/'user-data'
    target=home/'scripts'/'lattice_measurements'
    target.mkdir(parents=True)
    # Simulate the exact user situation: module.py installed, companions missing,
    # plus an old one-time marker that prevented reinstallation.
    (home/'scripts'/'.factory_modules_installed_v041').write_text('installed')
    (target/'module.json').write_bytes((src/'lattice_measurements'/'module.json').read_bytes())
    (target/'module.py').write_text('# MY CUSTOM USER EDITS\n')
    (target/'legacy_engine.py').write_text('# DO NOT REPLACE THIS\n')
    monkeypatch.setattr(paths,'bundled_studio_root',lambda:project)
    monkeypatch.setattr(paths,'scripts_dir',lambda:home/'scripts')
    messages=paths.repair_missing_factory_helpers()
    assert (target/'lattice_artifacts.py').is_file()
    assert (target/'roi_pipeline.py').is_file()
    assert (target/'legacy_engine.py').read_text()=='# DO NOT REPLACE THIS\n'
    assert (target/'module.py').read_text()=='# MY CUSTOM USER EDITS\n'
    assert any('lattice_artifacts.py' in message for message in messages)
    assert paths.repair_missing_factory_helpers()==[]
    # A tool deleted by the user is not reinstalled.
    assert not (home/'scripts'/'molecule_placement').exists()


def test_existing_install_runs_original_module_top_level_import(tmp_path, monkeypatch):
    project = Path(__file__).resolve().parents[1]
    src=project/'scripts'/'lattice_measurements'
    local=tmp_path/'scripts'/'lattice_measurements'
    local.mkdir(parents=True)
    (local/'module.py').write_bytes((src/'module.py').read_bytes())
    (local/'module.json').write_bytes((src/'module.json').read_bytes())
    monkeypatch.setattr(paths,'bundled_studio_root',lambda:project)
    monkeypatch.setattr(paths,'scripts_dir',lambda:tmp_path/'scripts')
    # Before repair the exact reported import fails (assuming scientific
    # dependencies are importable). After repair, a module can import its
    # helpers even from an isolated subprocess outside its working directory.
    paths.repair_missing_factory_helpers()
    command=[sys.executable,'-c',
      'import sys,importlib.util; from pathlib import Path; f=Path(sys.argv[1]); '
      'sys.path.insert(0,str(f.parent)); '
      's=importlib.util.spec_from_file_location("user_analysis",f); '
      'm=importlib.util.module_from_spec(s);s.loader.exec_module(m); '
      'assert hasattr(m,"run")',str(local/'module.py')]
    result=subprocess.run(command,capture_output=True,text=True,timeout=40)
    assert result.returncode == 0, result.stderr
