"""v16 regression: physical molecule footprint, later crops, colorbar export."""
from pathlib import Path
import importlib.util
import json
import sys
import numpy as np
from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[1]
LATTICE=ROOT/'scripts/lattice_measurements'
MOLECULE=ROOT/'scripts/molecule_placement'


def load_engine():
    sys.path.insert(0,str(MOLECULE))
    try:
        spec=importlib.util.spec_from_file_location('_v16_placement_engine',MOLECULE/'placement_engine.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def source_artifact(tmp_path):
    array=np.arange(200*300,dtype=float).reshape(200,300)
    np.save(tmp_path/'crop.npy',array)
    return {
        'cropped_scan_npy':str(tmp_path/'crop.npy'),
        'source_scan':str(tmp_path/'source.sxm'),
        'roi_geometry':{'shape_yx':[200,300],'size_nm':[30.,20.],
                        'pixel_size_nm':[.1,.1],
                        'pixel_bounds_xyxy':[0,0,300,200],
                        'center_local_nm':[0.,0.],
                        'center_sample_nm':[100.,200.],
                        'scan_angle_deg':0.},
        'source_raster_geometry':{'shape':[200,300],'size_m':[30e-9,20e-9]},
        'basis_local_nm':[[1.3,.4],[.2,1.1]],
        'vector_colors':['#16d8f5','#fbb748'],
    }


def crop(a,b,c,d):
    return {'left':a,'top':b,'right':c,'bottom':d,
            'reference_geometry':{'shape':[200,300],'size_m':[30e-9,20e-9]}}


def test_cropped_molecule_scale_and_lattice_phase(tmp_path):
    engine=load_engine()
    original=source_artifact(tmp_path)
    doc=engine.view_for_session_crop(original,crop(.5,.25,1.,1.))
    g=doc['roi_geometry']
    assert g['shape_yx']==[150,150]
    assert g['size_nm']==pytest.approx([15.,15.])
    assert g['pixel_size_nm']==pytest.approx([.1,.1])
    assert doc['_origin_shift_nm']==pytest.approx([-7.5,2.5])
    assert g['center_sample_nm']==pytest.approx([107.5,197.5])
    np.testing.assert_array_equal(doc['_raw_view'],np.load(original['cropped_scan_npy'])[50:200,150:300])
    # A 0.8 x 0.6 nm molecule must have identical pixel footprint before/after
    # cropping (8 by 6 pixels at 0.1 nm/pixel).
    artwork=Image.new('RGBA',(100,100),(255,255,255,255))
    a=Image.new('RGBA',(300,200),(0,0,0,0))
    b=Image.new('RGBA',(150,150),(0,0,0,0))
    engine._place_artwork(a,artwork,original['roi_geometry'],(0.,0.),0.,.8,.6,1.)
    engine._place_artwork(b,artwork,g,(0.,0.),0.,.8,.6,1.)
    assert a.getbbox() is not None and b.getbbox() is not None
    assert (a.getbbox()[2]-a.getbbox()[0],a.getbbox()[3]-a.getbbox()[1]) == (
           b.getbbox()[2]-b.getbbox()[0],b.getbbox()[3]-b.getbbox()[1])


def test_symmetric_crop_preserves_origin_and_view_resolution(tmp_path):
    engine=load_engine()
    original=source_artifact(tmp_path)
    doc=engine.view_for_session_crop(original,crop(.25,.2,.75,.8))
    assert doc['roi_geometry']['size_nm']==pytest.approx([15.,12.])
    assert doc['roi_geometry']['pixel_size_nm']==pytest.approx(original['roi_geometry']['pixel_size_nm'])
    assert doc['_origin_shift_nm']==pytest.approx([0.,0.])
    art=Image.new('RGBA',(100,100),(240,0,0,255))
    params={'molecule_width_nm':.8,'molecule_height_nm':.6,'orientation_mode':'manual',
            'rotation_offset_deg':0.,'max_molecules':2000,'molecule_count':5,
            'origin_x_nm':0.,'origin_y_nm':0.,'opacity':1.}
    image,n,angle,sites=engine.render_molecules(doc,art,params,max_preview_side=1200)
    assert image.size==(450,360)
    assert n==len(sites)==5
    assert angle==0.
    assert doc['roi_geometry']['size_nm'] == pytest.approx([15.,12.])


def test_nonoverlapping_crop_refuses_incorrect_registration(tmp_path):
    engine=load_engine()
    doc=source_artifact(tmp_path)
    doc['roi_geometry']['pixel_bounds_xyxy']=[0,0,100,80]
    doc['roi_geometry']['shape_yx']=[80,100]
    doc['roi_geometry']['size_nm']=[10.,8.]
    doc['roi_geometry']['pixel_size_nm']=[.1,.1]
    np.save(tmp_path/'crop.npy',np.zeros((80,100)))
    with pytest.raises(ValueError,match='does not overlap'):
        engine.view_for_session_crop(doc,crop(.60,.60,.90,.90))


def test_previous_session_crop_maps_back_to_original_raster(tmp_path):
    engine=load_engine()
    doc=source_artifact(tmp_path)
    # Lattice measured on a 0.2..0.8 cropped source: middle region of that crop.
    doc['analysis_session_crop']=crop(.2,.2,.8,.8)
    doc['source_raster_geometry']={'shape':[120,180]}
    doc['roi_geometry']['pixel_bounds_xyxy']=[30,20,150,100]
    doc['roi_geometry']['shape_yx']=[80,120]
    doc['roi_geometry']['size_nm']=[12.,8.]
    doc['roi_geometry']['pixel_size_nm']=[.1,.1]
    np.save(tmp_path/'crop.npy',np.zeros((80,120)))
    sub=engine.view_for_session_crop(doc,crop(.4,.4,.6,.6))
    assert sub['roi_geometry']['shape_yx']==[40,60]
    assert sub['roi_geometry']['size_nm']==pytest.approx([6.,4.])
    assert sub['_origin_shift_nm']==pytest.approx([0.,0.])


def test_gamma_label_only_in_corner_and_arc_in_both_image_engines():
    text=(LATTICE/'lattice_artifacts.py').read_text()
    molecule=(MOLECULE/'lattice_artifacts.py').read_text()
    for source in (text,molecule):
        assert 'arc_points=' in source
        assert 'draw.line(arc_points' in source
        assert "draw.text(point,f'γ =" not in source
        assert "(f'γ = {gamma:.1f}°','white')" in source
    # v0.8: the publication figure is drawn by the Export-panel renderer.
    pdf=(LATTICE/'module.py').read_text()
    renderer=(ROOT/'src/spm_studio/core/export_layout.py').read_text()
    assert "f'γ = {gamma:.1f}°',color='white'" not in pdf
    assert 'export_scan_figure' in pdf
    assert "(f'γ = {gamma:.1f}°','#ffffff')" in renderer


def test_double_column_allows_png_and_each_colorbar():
    dialog=(ROOT/'src/spm_studio/ui/export_dialog.py').read_text()
    layout=(ROOT/'src/spm_studio/core/export_layout.py').read_text()
    ui=(ROOT/'src/spm_studio/ui/main_window.py').read_text()
    assert 'Show quantitative colourbar' in dialog
    assert "'.png','.jpg','.jpeg','.pdf'" in dialog
    assert "'colorbar_source'" in dialog
    assert "report.suffix.lower() in ('.png','.jpg','.jpeg')" in layout
    assert "spec.get('show_colorbar',True)" in layout
    assert "'colorbar_style'" in ui


def test_installed_v15_factory_migrates_without_touching_user_edits(tmp_path,monkeypatch):
    from spm_studio.core import paths
    base=tmp_path/'bundle';source=base/'scripts';source.mkdir(parents=True)
    installed=tmp_path/'installed';installed.mkdir()
    folder='molecule_placement'
    (source/folder).mkdir();(installed/folder).mkdir()
    (source/folder/'module.json').write_text('{"version":"0.9.0"}')
    (installed/folder/'module.json').write_text('{"version":"0.8.0"}')
    (source/folder/'module.py').write_text('new factory v16\n')
    (installed/folder/'module.py').write_text('old factory v15\n')
    (source/folder/'placement_engine.py').write_text('new upstream\n')
    (installed/folder/'placement_engine.py').write_text('local customization\n')
    monkeypatch.setattr(paths,'scripts_dir',lambda:installed)
    monkeypatch.setattr(paths,'bundled_studio_root',lambda:base)
    monkeypatch.setattr(paths,'V16_FACTORY_PREVIOUS_SHA256',{folder:{
        'module.json':__import__('hashlib').sha256(b'{"version":"0.8.0"}').hexdigest(),
        'module.py':__import__('hashlib').sha256(b'old factory v15\n').hexdigest(),
        'placement_engine.py':__import__('hashlib').sha256(b'factory original').hexdigest()}})
    report=paths.upgrade_factory_overlays_v16()
    assert (installed/folder/'module.py').read_text()=='new factory v16\n'
    assert (installed/folder/'placement_engine.py').read_text()=='local customization\n'
    assert (installed/'.factory_backups_v16'/folder/'module.py').read_text()=='old factory v15\n'
    assert any('customized' in s for s in report)
