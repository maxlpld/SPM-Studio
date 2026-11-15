"""v15 regressions: native image results, physical bars, script/manifest safety."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import numpy as np
from PIL import Image
import pytest
ROOT=Path(__file__).resolve().parents[1]
LATTICE=ROOT/'scripts/lattice_measurements'
MOLECULE=ROOT/'scripts/molecule_placement'
SRC=ROOT/'src/spm_studio'


def _load(path,alias):
    spec=importlib.util.spec_from_file_location(alias,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_obsolete_overlay_removed_from_both_discovery_roots():
    assert not (ROOT/'scripts/molecule_lattice_overlay').exists()
    assert not (SRC/'builtin_modules/molecule_lattice_overlay').exists()
    from spm_studio.core.registry import discover_modules
    mods,_=discover_modules([ROOT/'scripts',SRC/'builtin_modules'])
    assert 'molecule_lattice_overlay' not in mods
    assert 'molecule_placement' in mods


def test_lattice_annotations_native_resolution_and_export_scale():
    from spm_studio.core.painting import nice_length
    mod=_load(LATTICE/'lattice_artifacts.py','lattice_artifacts_v15_test')
    arr=np.arange(80*100,dtype=float).reshape(80,100)
    base=mod.normalize_gray(arr)
    large=base.resize((400,320),Image.Resampling.NEAREST)
    geometry={'shape_yx':[80,100],'size_nm':[10.,8.],'pixel_size_nm':[.1,.1]}
    basis=[[.94,.32],[0.,.73]]
    result=mod.lattice_draw(large,basis,geometry,colors=('#33ee55','#aa44ff'),legend_corner='top_left')
    assert result.size==(400,320)
    assert mod._nice_length_nm(10.)==pytest.approx(nice_length(10.))
    assert not np.array_equal(np.asarray(result),np.asarray(large))
    assert 'stroke_width' not in mod.lattice_draw.__code__.co_varnames


def test_native_png_precedes_pdf_report_and_keeps_source_pixels(tmp_path):
    from spm_studio.core.result_library import preview_files
    folder=tmp_path/'Data'/'molecule_placement_20261109_210000_abc123';folder.mkdir(parents=True)
    original=np.random.default_rng(6).integers(0,255,(580,490,3),dtype='uint8')
    Image.fromarray(original).save(folder/'lattice_plus_molecules.png')
    public=tmp_path/'Images';public.mkdir()
    pdf=public/'scan_overlay.pdf';pdf.write_bytes(b'%PDF-1.4\n')
    selected=preview_files(folder,[pdf])
    assert selected==[folder/'lattice_plus_molecules.png',pdf]
    np.testing.assert_array_equal(np.asarray(Image.open(selected[0])),original)


def test_molecule_placement_uses_original_float_pixels_and_oversampled_artwork(tmp_path):
    # Keep imports confined to script dir: it has a private helper module.
    # Test against a real raw .npy lattice snapshot, not just the old 8-bit png.
    area=tmp_path/'ROI';area.mkdir()
    raw=np.random.default_rng(12).normal(size=(96,112))
    np.save(area/'cropped_scan.npy',raw)
    Image.fromarray(np.full((96,112,3),25,dtype='uint8')).save(area/'lattice_preview.png')
    doc={'cropped_scan_npy':str(area/'cropped_scan.npy'),
         'lattice_preview_png':str(area/'lattice_preview.png'),
         'roi_geometry':{'size_nm':[11.2,9.6],'shape_yx':[96,112],
                         'pixel_size_nm':[.1,.1]},
         'basis_local_nm':[[1.,.3],[0.,.8]],'vector_colors':['#33ee55','#aa44ff']}
    art=Image.new('RGBA',(180,180),(200,0,0,180))
    p={'molecule_width_nm':.75,'molecule_height_nm':.89,'orientation_mode':'manual',
       'rotation_offset_deg':30.,'origin_x_nm':0.,'origin_y_nm':0.,
       'opacity':.95,'max_molecules':1200,'molecule_count':3}
    saved=sys.modules.pop('lattice_artifacts',None)
    sys.path.insert(0,str(MOLECULE))
    try:
        place=_load(MOLECULE/'placement_engine.py','placement_engine_v15_test')
        output,count,angle,sites=place.render_molecules(doc,art,p)
    finally:
        sys.path.remove(str(MOLECULE))
        sys.modules.pop('lattice_artifacts',None)
        if saved is not None:sys.modules['lattice_artifacts']=saved
    assert output.size==(112*3,96*3)
    assert count==len(sites)==3 and angle==30.


def test_installed_v14_unchanged_scripts_upgrade_but_custom_edits_preserved(tmp_path,monkeypatch):
    from spm_studio.core import paths
    user=tmp_path/'user';user.mkdir()
    source=tmp_path/'app/scripts';source.mkdir(parents=True)
    (source/'molecule_placement').mkdir()
    (source/'lattice_measurements').mkdir()
    old=source/'molecule_placement'/'module.py';old.write_bytes(b'# new factory v15\n')
    factory=source/'molecule_placement'/'module.json';factory.write_text('{}')
    installed=user/'molecule_placement';installed.mkdir()
    (installed/'module.json').write_text('{}')
    (installed/'module.py').write_bytes(b'# v14 original\n')
    custom=user/'lattice_measurements';custom.mkdir()
    (custom/'module.json').write_text('{}')
    (custom/'module.py').write_text('# local edits\n')
    (source/'lattice_measurements'/'module.json').write_text('{}')
    (source/'lattice_measurements'/'module.py').write_text('# new lattice\n')
    monkeypatch.setattr(paths,'scripts_dir',lambda:user)
    monkeypatch.setattr(paths,'bundled_studio_root',lambda:tmp_path/'app')
    monkeypatch.setattr(paths,'V15_FACTORY_PREVIOUS_SHA256',{
        'molecule_placement':{'module.py':hashlib.sha256(b'# v14 original\n').hexdigest()},
        'lattice_measurements':{'module.py':hashlib.sha256(b'# v14 original\n').hexdigest()}})
    notes=paths.upgrade_factory_overlays_v15()
    assert (installed/'module.py').read_text()=='# new factory v15\n'
    assert (custom/'module.py').read_text()=='# local edits\n'
    assert (user/'.factory_backups_v15/molecule_placement/module.py').read_text()=='# v14 original\n'
    assert any('custom' in note for note in notes)


def test_qt_result_panel_has_full_width_and_live_svg_slot():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage
    from spm_studio.ui.result_view import ResultPreview
    app=QApplication.instance() or QApplication([])
    panel=ResultPreview()
    assert panel.minimumWidth()==460
    image=QImage(890,650,QImage.Format.Format_RGB888)
    image.fill(0xff33aa88)
    panel.set_live_image(image,'15 SVG molecule positions')
    assert panel.live and panel.raster.pixmap_item.pixmap().size().width()==890
    assert panel.stack.currentWidget() is panel.raster
    panel.deleteLater()
