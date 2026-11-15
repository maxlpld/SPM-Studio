"""Regression checks for the display-only Fix Zero and scale bar layout (no Qt needed)."""
import json
from pathlib import Path

import numpy as np
import pytest

from spm_studio.core.models import ProcessingStep
from spm_studio.core.processing import apply, display_bounds, display_zero_enabled
from spm_studio.core.painting import nice_length, _scale_bar_geometry
from spm_studio.core.export_layout import panel_defaults


class FakeRect:
    def left(self): return 10
    def right(self): return 410
    def top(self): return 20
    def bottom(self): return 420
    def width(self): return 400
    def height(self): return 400


def test_scale_bar_is_sensible_at_many_nanoscale_scan_widths():
    for width_nm in (0.5, 1, 3, 5, 10, 20, 30, 50, 100, 500, 2000):
        bar_nm = nice_length(width_nm * 1e-9) * 1e9
        assert 0 < bar_nm <= width_nm * .35000001
    assert nice_length(20e-9) == pytest.approx(5e-9)
    assert nice_length(10e-9) == pytest.approx(2e-9)


def test_top_bottom_scale_bar_geometry_and_corner_handling():
    rect=FakeRect()
    for position in ('top_left','top_right','bottom_left','bottom_right'):
        real_length, pixels, x, top=_scale_bar_geometry(rect,20e-9,position)
        assert real_length == pytest.approx(5e-9)
        assert pixels == pytest.approx(100)
        assert top == position.startswith('top')
        assert x > rect.left() if position.endswith('left') else x+pixels < rect.right()
    with pytest.raises(ValueError):
        _scale_bar_geometry(rect,20e-9,'middle')


def test_fix_zero_changes_only_legend_and_does_not_touch_values_or_colors():
    data=np.array([[-2e-10,-1e-10],[1e-10,5e-10]])
    original=data.copy()
    step=ProcessingStep('fix_zero')
    assert np.array_equal(apply(data,[step]),original)
    assert np.array_equal(data,original)
    assert display_bounds(float(data.min()),float(data.max()),[step]) == pytest.approx((0,7e-10))
    assert display_bounds(float(data.min()),float(data.max()),[ProcessingStep('fix_zero',enabled=False)]) == pytest.approx((-2e-10,5e-10))
    assert display_zero_enabled([step])
    assert not display_zero_enabled([ProcessingStep('fix_zero',enabled=False)])


def test_zero_after_plane_row_median_preserves_processed_data():
    yy,xx=np.indices((20,30))
    raw=1e-9+2e-11*xx+3e-12*yy+2e-10*np.sin(xx/4.)
    corrected=apply(raw,[ProcessingStep('plane'),ProcessingStep('row_median')])
    with_zero=apply(raw,[ProcessingStep('plane'),ProcessingStep('row_median'),ProcessingStep('fix_zero')])
    np.testing.assert_allclose(with_zero,corrected)
    lo,hi=float(corrected.min()),float(corrected.max())
    assert display_bounds(lo,hi,[ProcessingStep('fix_zero')])==pytest.approx((0,hi-lo))


def test_afm_profile_has_visual_zero_for_z_only():
    f=Path(__file__).resolve().parents[1]/'customization/profiles/AFM_Dissipation_Excitation.json'
    p=json.loads(f.read_text())
    assert [s['operation'] for s in p['channel_processing']['Z']] == ['plane','row_median','fix_zero']
    assert p['channel_styles']['Z']['range_mode']=='full'
    assert not p['channel_processing']['OC M1 Excitation']


def test_lattice_manifest_passes_zero_reference_to_export(tmp_path):
    from spm_studio.core.models import Scan,Channel,Geometry
    base=tmp_path/'SPM_Studio_Results'/'test'
    (base/'Images').mkdir(parents=True)
    folder=base/'Data'/'lattice_2026';folder.mkdir(parents=True)
    arr=folder/'cropped_scan.npy';np.save(arr,np.zeros((10,10)))
    (folder/'lattice_result.json').write_text(json.dumps({
        'cropped_scan_npy':str(arr), 'source_channel':'Z','source_unit':'m',
        'colorbar_zero_reference':True}))
    source=tmp_path/'scan.sxm';source.touch()
    geo=Geometry((10,10),(20e-9,20e-9))
    scan=Scan(source,{'Z':Channel('Z','m',{'forward':np.zeros((10,10))},geo)})
    artifact=base/'Images'/'lattice_2026__07_reference_scan_lattice_overlay.pdf';artifact.touch()
    defaults=panel_defaults(scan,{'kind':'report','path':str(artifact)})
    assert defaults['kind']=='lattice'
    assert defaults['display_zero'] is True
    assert defaults['scale_bar_position']=='bottom_right'
