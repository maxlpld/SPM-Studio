import numpy as np
import pytest
from spm_studio.core.io import sxm_header,_numbers,_geometry,discover,read_scan

def test_header_only_decoding(tmp_path):
    src=tmp_path/'valid.sxm'
    src.write_bytes(b':SCAN_RANGE:\n1.2e-8 9e-9\r\n:SCAN_OFFSET:\r\n1e-9\t2e-9\r\n:SCAN_ANGLE:\r\n90\r\n:SCANIT_END:\r\n\x1a\x04'+b'\0'*1024)
    header=sxm_header(src)
    assert _numbers(header['SCAN_RANGE'],2)==(1.2e-8,9e-9)
    g=_geometry((8,6),header)
    assert g.angle_deg==90 and g.size_m==(1.2e-8,9e-9)
    assert g.center_m==(1e-9,2e-9)
    assert not g.verified_orientation

def test_missing_header_raises(tmp_path):
    src=tmp_path/'bad.sxm'
    src.write_bytes(b'not nanonis')
    with pytest.raises(ValueError):sxm_header(src)

def test_discovery_no_data_decode(tmp_path):
    (tmp_path/'a.sxm').write_bytes(b'bad')
    (tmp_path/'b.gwy').write_bytes(b'bad')
    (tmp_path/'unrelated.txt').write_text('hi')
    (tmp_path/'selection').mkdir()
    (tmp_path/'selection'/'result.gwy').touch()
    assert sorted(x.name for x in discover(tmp_path))==['a.sxm','b.gwy']
    with pytest.raises(ValueError):read_scan(tmp_path/'unrelated.txt')

def test_gwyddion_direction_and_geometry_mocked(tmp_path,monkeypatch):
    import types,sys
    a=np.arange(30.,dtype=float).reshape(5,6)
    field=lambda data:types.SimpleNamespace(data=data,xreal=6e-9,yreal=5e-9,
                                      si_unit_z=types.SimpleNamespace(unitstr='m'))
    fake=types.SimpleNamespace(load=lambda f:object(),util=types.SimpleNamespace(
         get_datafields=lambda obj:{'Z [FWD]':field(a),'Z [BWD]':field(-a)}))
    monkeypatch.setitem(sys.modules,'gwyfile',fake)
    p=tmp_path/'sample.gwy';p.write_bytes(b'fixture')
    scan=read_scan(p)
    assert 'Z' in scan.channels
    ch=scan.channels['Z']
    assert set(ch.traces)=={'forward','backward'}
    assert ch.geometry.size_m==(6e-9,5e-9)
    np.testing.assert_array_equal(ch.get('forward'),a)
    np.testing.assert_array_equal(ch.get('backward'),-a)


def test_sxm_reader_no_implicit_fwd_bwd_substitution(tmp_path,monkeypatch):
    import types,sys
    p=tmp_path/'sample.sxm'
    p.write_bytes(b':SCAN_RANGE:\n5e-9 6e-9\n:SCAN_OFFSET:\n2e-9 3e-9\n:SCAN_ANGLE:\n90\n:SCANIT_END:\n\x1a\x04')
    a=np.arange(24.).reshape(4,6)
    obj=types.SimpleNamespace(header={'data_info':{'Name':['Z'],'Unit':['m']}},
             signals={'Z':{'forward':a,'backward':-a}})
    monkeypatch.setitem(sys.modules,'nanonispy',types.SimpleNamespace(read=types.SimpleNamespace(Scan=lambda _:obj)))
    scan=read_scan(p)
    assert scan.channels['Z'].geometry.angle_deg==90
    assert not scan.channels['Z'].geometry.verified_orientation
    np.testing.assert_array_equal(scan.channels['Z'].get('backward'),-a[:, ::-1])
