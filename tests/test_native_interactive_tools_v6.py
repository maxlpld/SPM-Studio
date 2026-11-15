"""Scientific regression checks for native interactive Gwyddion-inspired tools."""
import numpy as np
import pytest
from spm_studio.core.models import Geometry, ROI, ProcessingStep
from spm_studio.core.interactive_tools import (TOOLS,roi_slice,line_profile,measure,
    radial_profile,three_point_plane_coefficients,fft_radial)
from spm_studio.core.processing import apply


def image():
    ny,nx=30,40
    yy,xx=np.indices((ny,nx))
    # Nominally 20 nm wide × 15 nm tall
    g=Geometry((ny,nx),size_m=(20e-9,15e-9))
    return xx*.3+yy*.5+7.,g


def test_catalogue_is_interactive_not_just_icon_display():
    ids=[v.identifier for v in TOOLS]
    assert len(ids)>20 and len(ids)==len(set(ids))
    assert {'read_value','distance','profile','roughness','three_point','mask','crop','filter','fft'}<=set(ids)
    assert all(t.instructions and t.selection in ('pan','point','line','rectangle') for t in TOOLS)


def test_rectangle_selection_is_bounded():
    a,g=image()
    roi=ROI('rectangle',((-4,-3),(5,6)))
    ys,xs=roi_slice(a.shape,roi)
    assert (ys.start,ys.stop,xs.start,xs.stop)==(0,7,0,6)


def test_distance_and_profile_physical_values():
    a,g=image()
    roi=ROI('line',((0,0),(20,0)))
    out=measure('distance',a,g,roi)
    assert any('10' in x and 'nm' in x for x in out['lines'])
    x,z=line_profile(a,g,roi)
    assert x[-1]==pytest.approx(10e-9)
    assert z[0]==pytest.approx(a[0,0])
    assert z[-1]==pytest.approx(a[0,20])


def test_point_crosshair_readout():
    a,g=image()
    roi=ROI('point',((10,12),))
    assert any('Signal' in x for x in measure('read_value',a,g,roi)['lines'])
    out=measure('axes_profile',a,g,roi)
    assert len(out['series'])==2
    assert len(out['series'][0][1])==40


def test_live_histogram_stats_mask():
    a,g=image()
    roi=ROI('rectangle',((3,4),(12,16)))
    mask=np.zeros_like(a,dtype=bool)
    mask[5:8,6:9]=True
    out=measure('statistics',a,g,roi)
    assert any('Mean' in s for s in out['lines'])
    assert measure('grain_measure',a,g,roi,mask=mask)['lines'][0]=='Pixels = 9'
    assert len(measure('distribution',a,g,roi)['series'])==1
    assert len(measure('row_stats',a,g,roi)['series'])==2


def test_radial_and_fft_outputs():
    a,g=image()
    roi=ROI('line',((12,12),(23,12)))
    x,y=radial_profile(a,g,roi)
    assert x.size==160 and y.size==160
    f,p=fft_radial(a,g)
    assert len(f)==len(p)==180
    assert np.all(p>=0)


def test_three_point_plane_and_reversible_step():
    a,g=image()
    points=[(2.,3.),(11.,5.),(4.,22.)]
    coeff=three_point_plane_coefficients(a,points)
    assert coeff==pytest.approx([.3,.5,7.])
    params={f'{axis}{i}':float(point[j]) for i,point in enumerate(points,1)
            for j,axis in enumerate(('x','y'))}
    result=apply(a,[ProcessingStep('three_point_plane',params)])
    assert np.max(np.abs(result))<1e-11
    assert np.array_equal(a,np.indices(a.shape)[1]*.3+np.indices(a.shape)[0]*.5+7)


def test_path_level_removes_trend_along_reference_line():
    a,g=image()
    p={'x0':1,'y0':5,'x1':35,'y1':5}
    processed=apply(a,[ProcessingStep('path_plane',p)])
    assert np.ptp(processed[5,:])<1e-10
    assert np.ptp(a[5,:])>10


def test_spot_repair_one_pixel_only():
    a,g=image()
    corrupted=a.copy();corrupted[11,13]+=200
    result=apply(corrupted,[ProcessingStep('spot_replace',{'x':13,'y':11,'radius':2})])
    assert result[11,13]==pytest.approx(a[11,13],abs=.001)
    result[11,13]=corrupted[11,13]
    assert np.array_equal(result,corrupted)


def test_roughness_and_fft_statistics_do_not_modify_source():
    a,g=image()
    original=a.copy()
    line=ROI('line',((5,5),(28,19)))
    rect=ROI('rectangle',((5,5),(28,19)))
    for tool,roi in [('roughness',line),('correlation',rect),('fft',rect),('radial',line)]:
        out=measure(tool,a,g,roi)
        assert out['lines']
    assert np.array_equal(a,original)


def test_legend_zero_remains_display_only():
    a,g=image()
    result=apply(a,[ProcessingStep('fix_zero',{})])
    assert np.array_equal(a,result)


def test_dark_and_light_colorbar_value_contrast():
    from spm_studio.core.painting import foreground_on_background
    assert foreground_on_background('#15191e')=='#ffffff'
    assert foreground_on_background('#222831')=='#ffffff'
    assert foreground_on_background('#f7f9fc')=='#20252a'
    assert foreground_on_background('#fff')=='#20252a'
