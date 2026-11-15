"""Regression tests: calibration-safe alpha layers and publication layout wiring."""
from pathlib import Path
import importlib.util
import json
import os
import numpy as np
import pytest
from spm_studio.core.channel_overlay import Layer,make_layers,composite
from spm_studio.core.registry import load_manifest
from spm_studio.core.models import Geometry,Channel,Scan

ROOT=Path(__file__).resolve().parents[1]


def test_manifest_is_discoverable_and_declarative():
    mod=load_manifest(ROOT/'scripts/channel_overlay/module.json')
    assert mod.id=='channel_overlay' and mod.snapshot_channels=='all'
    assert mod.parameters['opacity_2']['max']==1
    assert len(mod.parameters)>=5


def test_layer_opaque_transparent_and_partial():
    a=np.arange(100,dtype=float).reshape(10,10)
    b=np.rot90(a)
    base=Layer('Z',a,'m','gray',1.)
    top=Layer('Excitation',b,'V','inferno',0.)
    transparent,_=composite([base,top])
    expected,_=composite([base,Layer('Excitation',b,'V','inferno',1.)])
    assert transparent.shape==(10,10,3)
    assert not np.array_equal(transparent,expected)
    mid,_=composite([base,Layer('Excitation',b,'V','inferno',.5)])
    assert np.max(np.abs(mid.astype(float)-.5*(transparent.astype(float)+expected.astype(float))))<=1


def test_masked_pixels_keep_lower_layer_and_misalignment_rejected():
    base=np.arange(36,dtype=float).reshape(6,6)
    top=np.rot90(base)
    top[2,2]=np.nan
    b,_=composite([Layer('Z',base,'m'),Layer('CPD',top,'V','viridis',0.)])
    over,_=composite([Layer('Z',base,'m'),Layer('CPD',top,'V','viridis',1.)])
    assert np.array_equal(b[2,2],over[2,2])
    with pytest.raises(ValueError,match='Registration required'):
        composite([Layer('Z',base),Layer('CPD',top[:5])])
    with pytest.raises(ValueError,match='Opacity'):
        composite([Layer('Z',base),Layer('CPD',top,'V','inferno',2.)])


def test_any_number_of_named_overlay_channels_and_duplicate_check():
    image=np.ones((8,8))
    available={'Z':image,'Bias':image*2,'Excitation':image*3,'CPD':image*4}
    p={'channel_2':'Bias','channel_3':'Excitation','channel_4':'',
       'additional_channels':'CPD','opacity_2':.3,'opacity_3':.8}
    layers=make_layers('Z',image,'m',[],available.__getitem__,{k:'V' for k in available},p)
    assert [l.name for l in layers]==['Z','Bias','Excitation','CPD']
    assert [l.opacity for l in layers]==[1,.3,.8,.4]
    with pytest.raises(ValueError,match='more than once'):
        make_layers('Z',image,'m',[],available.__getitem__,{},dict(p,additional_channels='Bias'))


def test_publication_sources_use_vector_annotations_and_600_dpi():
    placement=(ROOT/'scripts/molecule_placement/vector_publication.py').read_text()
    module=(ROOT/'scripts/molecule_placement/module.py').read_text()
    lattice=(ROOT/'scripts/lattice_measurements/module.py').read_text()
    assert 'svg_art.render(painter,QRectF(' in placement and 'setClipRect(artwork_rect)' in placement
    # v0.8: lattice vectors, scale bar and colourbar come from the Export-panel renderer.
    assert 'export_scan_figure' in placement and 'molecule_decorator' in placement
    assert 'export_placement' in module
    assert 'image.convert(\'RGB\').save(pdf' not in module
    assert 'export_scan_figure' in lattice


@pytest.mark.skipif(importlib.util.find_spec('PySide6') is None,reason='Qt not installed in test environment')
def test_publication_dialog_custom_and_square(tmp_path):
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    from spm_studio.ui.export_dialog import PublicationDialog
    QApplication.instance() or QApplication([])
    data=np.arange(100.,dtype=float).reshape(10,10)
    geom=Geometry((10,10),(1e-8,1e-8))
    p=tmp_path/'dummy.sxm';p.write_bytes(b'probe')
    scan=Scan(p,{'Z':Channel('Z','m',{'forward':data},geom),'Bias':Channel('Bias','V',{'forward':data},geom)})
    dialog=PublicationDialog(scan,selected_channel='Z',preset={'schema_version':1,'name':'square',
                             'width_mm':100,'height_mm':100,'dpi':600,'font_family':'DejaVu Sans',
                             'font_size_pt':9,'margin_mm':4},layout_name='square')
    assert len(dialog.selection())==1
    assert not dialog.controls[1]['group'].isVisible()
    assert dialog.resolved_preset()['width_mm']==dialog.resolved_preset()['height_mm']
    dialog.layout_mode.setCurrentIndex(dialog.layout_mode.findData('custom'))
    dialog.page_width.setValue(121);dialog.page_height.setValue(77)
    dialog.panel_count.setCurrentIndex(1)
    assert len(dialog.selection())==2 and dialog.resolved_preset()['height_mm']==77
