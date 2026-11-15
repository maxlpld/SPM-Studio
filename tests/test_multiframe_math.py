import numpy as np
from spm_studio.core.models import Geometry

def test_shared_physical_reference_across_rotations():
    reference=Geometry((40,40),(8e-9,8e-9),(5e-9,2e-9),0,'up')
    other=Geometry((60,60),(10e-9,10e-9),(5e-9,2e-9),90,'down')
    row,col=np.meshgrid(np.arange(40),np.arange(40),indexing='ij')
    sx,sy=reference.pixel_to_sample(row,col)
    rr,cc=other.sample_to_pixel(sx,sy)
    valid=(rr>=0)&(rr<59)&(cc>=0)&(cc<59)
    assert valid.mean()>0.6
    xx,yy=other.pixel_to_sample(rr[valid],cc[valid])
    np.testing.assert_allclose(xx,sx[valid],atol=1e-20)
    np.testing.assert_allclose(yy,sy[valid],atol=1e-20)
