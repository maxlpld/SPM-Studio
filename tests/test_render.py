import numpy as np
import pytest
from spm_studio.core.models import ImageStyle
from spm_studio.core.display import render_rgb,bounds,lut

def test_palette_bounds_and_repeated_render_are_deterministic():
    a=np.linspace(-2,10,256*256).reshape(256,256)
    style=ImageStyle(colormap='gray',range_mode='manual',low=0,high=8)
    full=render_rgb(a,style)
    small=render_rgb(a,style,max_dimension=128)
    np.testing.assert_array_equal(full[::2,::2],small)
    assert bounds(a,style)==(0,8)
    assert full[0,0,0]==0 and full[-1,-1,0]==255
    assert full.shape==(256,256,3)

def test_nan_mask_and_colormap_is_not_sign_inversion():
    a=np.array([[0.,1.],[np.nan,2.]])
    rgb=render_rgb(a,ImageStyle(range_mode='manual',low=0,high=2))
    np.testing.assert_array_equal(rgb[1,0],[130,20,130])
    assert rgb[0,0,0]<rgb[1,1,0]
    assert lut('gray').shape==(256,3)

def test_invalid_style_inputs():
    with pytest.raises(ValueError):bounds(np.ones((3,3)),ImageStyle(range_mode='broken'))
    with pytest.raises(ValueError):lut('fake.csv')
    with pytest.raises(ValueError):lut('custom',np.array([[300,0,0],[1,1,1]]))
