import numpy as np
import pytest
from spm_studio.core.models import Geometry,Channel,Scan

def test_asymmetric_fiducial_inverse_0_90_and_arbitrary():
    for angle in (0,90,180,71):
        g=Geometry((47,79),(12e-9,8e-9),(33e-9,-21e-9),angle,'up')
        rows=np.array([2,11,30,42]);cols=np.array([7,28,53,75])
        sx,sy=g.pixel_to_sample(rows,cols)
        r,c=g.sample_to_pixel(sx,sy)
        np.testing.assert_allclose(r,rows,atol=1e-10)
        np.testing.assert_allclose(c,cols,atol=1e-10)
        assert not g.verified_orientation

def test_local_rectangular_pixel_scaling():
    g=Geometry((100,200),(20e-9,4e-9))
    x1,y1=g.pixel_to_local(0,0)
    x2,y2=g.pixel_to_local(99,199)
    assert x1<x2 and y1>y2
    assert np.isclose(x2-x1,19.9e-9)
    assert np.isclose(y1-y2,3.96e-9)

def test_absent_geometry_explicitly_unknown():
    g=Geometry((10,10))
    with pytest.raises(ValueError):g.pixel_to_sample(0,0)
    np.testing.assert_allclose(g.local_to_pixel(*g.pixel_to_local(3,4)),(3,4))

def test_missing_trace_never_substituted(tmp_path):
    geo=Geometry((3,3))
    ch=Channel('Z','m',{'forward':np.arange(9.).reshape(3,3)},geo)
    with pytest.raises(KeyError):ch.get('backward')
    with pytest.raises(ValueError):Channel('Bad','V',{'forward':np.zeros((3,4))},geo)
    scan=Scan(tmp_path/'x.sxm',{'Z':ch})
    assert scan.preferred_channel()=='Z'
    assert not ch.get('forward').flags.writeable
