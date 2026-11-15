from pathlib import Path
import json
import numpy as np
import pytest

from spm_studio.core.presets import validate_profile
from spm_studio.core.display import PALETTES, lut
from spm_studio.core.gwyddion_palettes import parse_gwyddion_gradient, import_gwyddion_directory

ROOT=Path(__file__).resolve().parents[1]


def profile(name):
    return validate_profile(json.loads((ROOT/'customization/profiles'/name).read_text(encoding='utf-8')))


def test_molecular_resolution_profile_has_5_optional_channels_and_processed_topo():
    p=profile('AFM_Molecular_Resolution.json')
    assert p['visible_channels']==['Z','OC M1 Freq','OC M1 Excitation','OC M2 Freq','OC M2 Excitation']
    assert [s['operation'] for s in p['channel_processing']['Z']]==['plane','row_median','fix_zero']
    assert p['channel_styles']['OC M1 Freq']['colormap']=='cividis'
    assert p['channel_styles']['OC M1 Excitation']['colormap']=='viridis'
    assert p['channel_styles']['OC M2 Freq']['colormap']=='Gold'
    assert p['channel_styles']['OC M2 Excitation']['colormap']=='copper'
    assert 'Gold' in PALETTES
    assert lut('Gold').shape==(256,3)


def test_kpfm_has_z_leveling_and_bias_viridis():
    p=profile('KPFM.json')
    assert p['visible_channels']==['Z','Bias']
    assert [s['operation'] for s in p['channel_processing']['Z']]==['plane','row_median','fix_zero']
    assert p['channel_styles']['Bias']['colormap']=='viridis'


def test_actual_gwyddion_gradient_parser_and_import(tmp_path):
    source=tmp_path/'Gwyddion gradient files'
    source.mkdir()
    (source/'Real Gold').write_text('Gwyddion resource GwyGradient\n0 0 0 0 1\n0.5 1 0.7 0.1 1\n1 1 1 1 1\n',encoding='utf-8')
    (source/'wrong').write_text('Gwyddion resource SomethingElse\n0 0 0 0 1\n1 1 1 1 1\n',encoding='utf-8')
    actual=parse_gwyddion_gradient(source/'Real Gold')
    assert actual.shape==(256,3)
    assert np.allclose(actual[0],(0.,0.,0.))
    assert np.allclose(actual[-1],(1.,1.,1.))
    imported=import_gwyddion_directory(source,tmp_path/'custom')
    assert len(imported)==1
    assert imported[0].name=='Gwy - Real Gold.csv'
    assert np.loadtxt(imported[0],delimiter=',').shape==(256,3)
    # Cannot overwrite existing user palettes on next import.
    assert import_gwyddion_directory(source,tmp_path/'custom')==[]
    with pytest.raises(ValueError):parse_gwyddion_gradient(source/'wrong')


def test_bad_gradient_is_not_imported(tmp_path):
    source=tmp_path/'resources';source.mkdir()
    (source/'invalid').write_text('Gwyddion resource GwyGradient\n0 0 0 0 1\n0.6 0 1 1 1\n0.5 1 0 1 1\n1 1 1 1 1\n')
    assert import_gwyddion_directory(source,tmp_path/'out')==[]


def test_qt_source_exposes_tools_and_profile_save():
    source=(ROOT/'src/spm_studio/ui/main_window.py').read_text(encoding='utf-8')
    assert "addTab(interactive_scroll,'Image tools')" in source
    assert "self.right_tabs.addTab(interactive_scroll,'Image tools')" in source
    assert "setObjectName('SaveCurrentMultiChannelProfile')" in source
    assert "self.right_tabs.setCurrentWidget(self.module_tools_scroll)" in source
    assert "'channel_processing':channel_processing" in source
    assert "'channel_styles':channel_styles" in source


def test_extra_65_publication_palettes_are_shipped():
    examples=list((ROOT/'customization/colormaps').glob('MPL - *.csv'))
    assert len(examples)>=50
    for name in ('MPL - turbo.csv','MPL - twilight.csv','MPL - RdBu.csv'):
        path=ROOT/'customization/colormaps'/name
        assert path.is_file()
        rgb=np.loadtxt(path,delimiter=',')
        assert rgb.shape==(256,3)
        assert np.isfinite(rgb).all()
