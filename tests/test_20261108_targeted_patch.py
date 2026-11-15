"""Targeted regression checks for the November Studio patch (headless-safe)."""
import json
from pathlib import Path
import numpy as np
from spm_studio.core.models import ProcessingStep, ImageStyle, Geometry, Channel, Scan
from spm_studio.core.processing import PROCESS_GROUPS, DEFAULT_PARAMETERS, apply, display_bounds
from spm_studio.core.presets import read_json, validate_profile
from spm_studio.core.export_layout import find_lattice_manifest, panel_defaults


def test_all_visible_native_operations_execute_without_mutating_source():
    rng=np.random.default_rng(19)
    data=rng.normal(0.2,0.03,(27,35))
    data[0,0]=np.nan
    original=data.copy()
    for group in PROCESS_GROUPS.values():
        for name,operation in group:
            result=apply(data,[ProcessingStep(operation,dict(DEFAULT_PARAMETERS.get(operation,{})))])
            assert result.shape==data.shape, name
            assert np.isnan(result[0,0]), name
            assert np.isfinite(result[1:,1:]).all(), name
            assert np.array_equal(data,original,equal_nan=True), name


def test_fix_zero_after_plane_and_raw_median():
    row,col=np.indices((20,30))
    data=(row*0.1+col*.2+np.sin(col/3)).astype(float)
    data[0,0]=np.nan
    steps=[ProcessingStep('plane'),ProcessingStep('row_median'),ProcessingStep('fix_zero')]
    result=apply(data,steps)
    reference=apply(data,steps[:-1])
    np.testing.assert_allclose(result,reference,equal_nan=True)
    lo,hi=np.nanmin(reference),np.nanmax(reference)
    assert display_bounds(lo,hi,steps)==(0.0,hi-lo)
    assert np.isnan(result[0,0])


def test_afm_profile_includes_per_channel_styles_and_nondestructive_pipeline():
    profile=Path(__file__).resolve().parents[1]/'customization/profiles/AFM_Dissipation_Excitation.json'
    rules=read_json(profile,validate_profile)
    assert rules['channel_styles']['Z']['colormap']=='gray'
    assert rules['channel_styles']['OC M1 Excitation']['colormap']=='viridis'
    assert [item['operation'] for item in rules['channel_processing']['Z']]==[
        'plane','row_median','fix_zero']
    assert rules['channel_titles']['OC M1 Excitation']=='$V_{exc}$'   # v34 default
    assert rules['visible_channels']==['Z','OC M1 Excitation']


def test_lattice_result_manifest_is_resolved_to_same_run_only(tmp_path):
    folder=tmp_path/'SPM_Studio_Results'/'my_scan'
    (folder/'Images').mkdir(parents=True)
    run='lattice_measurements_20261108_195035_309f73'
    data=folder/'Data'/run
    data.mkdir(parents=True)
    manifest=data/'lattice_result.json'
    raster=data/'cropped_scan.npy'
    np.save(raster,np.arange(100,dtype=float).reshape(10,10))
    manifest.write_text(json.dumps({'cropped_scan_npy':str(raster),
        'source_channel':'Z','source_unit':'m'}))
    pdf=folder/'Images'/(run+'__07_reference_scan_lattice_overlay.pdf')
    pdf.write_bytes(b'%PDF-1.4\n')
    assert find_lattice_manifest(pdf)==manifest
    scan_file=tmp_path/'my_scan.sxm';scan_file.write_bytes(b'test')
    g=Geometry((10,10),size_m=(1e-8,1e-8))
    scan=Scan(scan_file,{'Z':Channel('Z','m',{'forward':np.zeros((10,10))},g)})
    spec=panel_defaults(scan,{'kind':'report','path':str(pdf)})
    assert spec['kind']=='lattice'
    assert spec['unit']=='m'
    assert spec['title']=='Z'


def test_removed_pan_shortcut_and_backward_compatible_profiles():
    from spm_studio.core.shortcuts import ACTION_BY_ID, DEFAULT_BINDINGS, validate_profile
    assert 'view.pan' not in ACTION_BY_ID
    assert 'view.pan' not in DEFAULT_BINDINGS
    previous=DEFAULT_BINDINGS.copy()
    previous['view.pan']='P'
    previous['view.fit']='F'
    fixed=validate_profile({'schema_version':1,'name':'previous','bindings':previous})
    assert 'view.pan' not in fixed['bindings']
    assert fixed['bindings']['view.fit']=='F'


def test_declared_shortcuts_are_all_connected_at_startup():
    import ast
    from spm_studio.core.shortcuts import ACTION_BY_ID
    source=Path(__file__).resolve().parents[1]/'src/spm_studio/ui/main_window.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    menus={node.args[2].value for node in ast.walk(tree)
           if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
           and node.func.attr=='_action' and len(node.args)>=3
           and isinstance(node.args[2],ast.Constant) and isinstance(node.args[2].value,str)}
    # The four navigation keys are handled directly in the window event filter;
    # the tool slots are registered in a dynamic for-loop.
    registered=menus|{f'tool.slot{i}' for i in range(1,9)}
    registered|={'nav.scan_previous','nav.scan_next','nav.channel_left','nav.channel_right'}
    assert set(ACTION_BY_ID)==registered
