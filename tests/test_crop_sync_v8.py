"""Regression tests for the non-destructive, physically matching crop model."""
import numpy as np
import pytest

from spm_studio.core.cropping import CropRegion, CropAlignmentError, crop_channel
from spm_studio.core.models import Channel, Geometry, ProcessingStep, ROI
from spm_studio.core.processing import apply


def build_channel(name='Z', shape=(100,200), *, size=(20e-9,10e-9), center=(0.,0.), angle=0.):
    geo=Geometry(shape, size_m=size,center_m=center,angle_deg=angle)
    array=np.arange(np.prod(shape),dtype=np.float64).reshape(shape)
    return Channel(name,'m',{'forward':array,'backward':-array},geo)


def test_matching_crop_preserves_raw_and_both_traces_and_geometry():
    source=build_channel(); other=build_channel('OC M1 Excitation')
    roi=ROI('rectangle',((20,10),(119,59)))
    region=CropRegion.from_roi(roi,source.geometry)
    z=crop_channel(source,region); exc=crop_channel(other,region)
    assert z.geometry.shape==(50,100)
    assert exc.geometry.shape==z.geometry.shape
    assert exc.geometry.size_m==z.geometry.size_m
    assert exc.geometry.center_m==z.geometry.center_m
    np.testing.assert_array_equal(z.get('forward'),source.get('forward')[10:60,20:120])
    np.testing.assert_array_equal(z.get('backward'),source.get('backward')[10:60,20:120])
    assert not z.get('forward').flags.writeable
    assert source.get('forward').shape==(100,200)
    # Cutting out a region must NOT apply leveling or other profile steps.
    pipeline=[ProcessingStep('plane'),ProcessingStep('row_median')]
    assert not np.array_equal(z.get('forward'),apply(z.get('forward'),pipeline))


def test_nested_crop_uses_original_physical_region_and_no_reset():
    source=build_channel()
    first=CropRegion.from_roi(ROI('rectangle',((20,10),(119,59))),source.geometry)
    cropped=crop_channel(source,first)
    second=CropRegion.from_roi(ROI('rectangle',((10,5),(59,34))),cropped.geometry,first)
    final=crop_channel(source,second)
    np.testing.assert_array_equal(final.get('forward'),source.get('forward')[15:45,30:80])
    assert final.geometry.shape==(30,50)
    assert final.geometry.size_m==(5e-9,3e-9)


def test_registered_channels_with_different_pixel_density_use_same_physical_region():
    source=build_channel(shape=(100,200))
    fine=build_channel(name='Bias',shape=(200,400))
    region=CropRegion.from_roi(ROI('rectangle',((20,10),(119,59))),source.geometry)
    left=crop_channel(source,region); right=crop_channel(fine,region)
    assert left.geometry.size_m==right.geometry.size_m
    assert left.geometry.center_m==right.geometry.center_m
    assert left.geometry.shape==(50,100) and right.geometry.shape==(100,200)


def test_misaligned_channels_rejected_not_silently_cropped():
    source=build_channel()
    region=CropRegion.from_roi(ROI('rectangle',((20,10),(119,59))),source.geometry)
    for kw in ({'center':(1e-9,0.)},{'angle':15.},{'size':(20e-9,11e-9)}):
        params=dict(kw)
        incompatible=build_channel('Other',**params)
        with pytest.raises(CropAlignmentError):crop_channel(incompatible,region)


def test_processing_pipeline_on_cropped_data_is_user_controlled():
    source=build_channel()
    region=CropRegion.from_roi(ROI('rectangle',((20,10),(119,59))),source.geometry)
    z=crop_channel(source,region)
    p=[ProcessingStep('fix_zero')]
    # Display zero leaves scan data unmodified; profiles remain separate from ROI.
    np.testing.assert_array_equal(z.get('forward'),source.get('forward')[10:60,20:120])
    assert all(s.operation=='fix_zero' for s in p)
