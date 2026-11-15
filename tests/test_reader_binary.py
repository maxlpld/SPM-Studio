"""Binary SXM fixtures, direction labels and no-fabrication checks.

These tests use generated binary data with real SXM framing, rather than
mocking nanonispy. Instrument-exported golden fixtures remain necessary.
"""
from __future__ import annotations
import numpy as np
import pytest
from spm_studio.core.io import read_scan


def create_sxm(path, *, short_by=0, little_endian=False):
    header = ('\r\n'.join([
        ':SCAN_PIXELS:', '5 4', ':SCAN_RANGE:', '10e-9 8e-9',
        ':SCAN_OFFSET:', '2e-9 -3e-9', ':SCAN_ANGLE:', '90',
        ':SCAN_DIR:', 'up', ':SCANIT_TYPE:',
        'FLOAT LSBFIRST' if little_endian else 'FLOAT MSBFIRST',
        ':DATA_INFO:',
        'Channel\tName\tUnit\tDirection\tCalibration\tOffset',
        '0\tZ\tm\tboth\t1\t0',
        '1\tBias\tV\tforward\t1\t0',
        ':SCANIT_END:'
    ]) + '\r\n').encode('latin-1')
    raw = np.arange(60, dtype='<f4' if little_endian else '>f4')
    path.write_bytes(header + b'\x1a\x04' + raw.tobytes()[:raw.nbytes-short_by])
    return path


@pytest.mark.parametrize('little_endian', [False, True])
def test_real_framed_sxm_multiple_channels(tmp_path, little_endian):
    p = create_sxm(tmp_path/'test.sxm', little_endian=little_endian)
    scan = read_scan(p)
    assert scan.metadata['reader'] == 'native'
    assert set(scan.channels) == {'Z', 'Bias'}
    assert set(scan.channels['Z'].traces) == {'forward', 'backward'}
    assert set(scan.channels['Bias'].traces) == {'forward'}
    assert scan.channels['Bias'].unit == 'V'
    assert scan.channels['Z'].geometry.size_m == (10e-9, 8e-9)
    assert scan.channels['Z'].geometry.center_m == (2e-9, -3e-9)
    assert scan.channels['Z'].geometry.scan_direction == 'up'
    assert scan.channels['Z'].geometry.angle_deg == 90
    np.testing.assert_array_equal(scan.channels['Z'].get('forward'), np.arange(20).reshape(4,5)[::-1, :])
    np.testing.assert_array_equal(scan.channels['Z'].get('backward'), np.arange(20,40).reshape(4,5)[::-1, ::-1])
    with pytest.raises(KeyError):
        scan.channels['Bias'].get('backward')
    assert not scan.channels['Z'].get('forward').flags.writeable


def test_incomplete_sxm_preserves_nans(tmp_path):
    scan = read_scan(create_sxm(tmp_path/'incomplete.sxm',short_by=16))
    b = scan.channels['Bias'].get('forward')
    assert np.isnan(b[0,-4:]).all()
    assert np.isfinite(b[-1,0])
    assert any('Incomplete SXM' in w for w in scan.warnings)


def test_bad_sxm_does_not_fake_channel(tmp_path):
    p=tmp_path/'broken.sxm'
    p.write_bytes(b':SCAN_PIXELS:\n4 4\n:SCANIT_END:\n\x1a\x04' + b'\x00'*64)
    with pytest.raises(ValueError,match='DATA_INFO'):
        read_scan(p)


def test_gwy_container_preserves_untitled_fields_and_duplicate_titles(tmp_path,monkeypatch):
    import sys,types
    a=np.arange(20.,dtype=float).reshape(4,5)
    def field(x):
        return types.SimpleNamespace(data=x,xreal=5e-9,yreal=4e-9,
            si_unit_xy=types.SimpleNamespace(unitstr='m'),
            si_unit_z=types.SimpleNamespace(unitstr='V'))
    container={'/0/data':field(a),'/0/data/title':'Bias [FWD]',
               '/1/data':field(-a),'/1/data/title':'Bias [BWD]',
               '/2/data':field(a+2),'/2/data/title':'Bias [FWD]',
               '/3/data':field(a+3)}
    fake=types.SimpleNamespace(load=lambda _:container,
         util=types.SimpleNamespace(get_datafields=lambda _:{}))
    monkeypatch.setitem(sys.modules,'gwyfile',fake)
    p=tmp_path/'some.gwy';p.write_bytes(b'placeholder')
    scan=read_scan(p)
    assert {'Bias','Bias [FWD]','Channel 3'} == set(scan.channels)
    np.testing.assert_array_equal(scan.channels['Bias'].get('backward'),-a)
    assert len(scan.metadata['fields'])==4  # even repeated titles retain metadata
    assert any('separate channel' in w for w in scan.warnings)
