"""v13 regression: scan-scoped profiles; opt-in multiframe; user-controlled lattice artwork."""
from __future__ import annotations
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
LATTICE=ROOT/'scripts/lattice_measurements'
MOLECULE=ROOT/'scripts/molecule_placement'


def load(name,folder):
    import sys
    sys.path.insert(0,str(folder))
    try:
        spec=importlib.util.spec_from_file_location(name,folder/(name+'.py'))
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(folder))


def test_lattice_default_only_current_scan_even_if_all_open(tmp_path):
    bridge=load('legacy_engine',LATTICE)
    focus=tmp_path/'focus.sxm';other=tmp_path/'other.sxm';unopened=tmp_path/'unopened.sxm'
    for path in (focus,other,unopened):path.write_bytes(b'data')
    ctx=SimpleNamespace(scan_path=focus,source_paths=[other,unopened,focus])
    _,files,kind=bridge.selected_sources(ctx)
    assert files==[focus.resolve()]
    assert kind=='sxm'
    _,files,_=bridge.selected_sources(ctx,include_dataset=True)
    assert files==[focus.resolve(),*sorted([other.resolve(),unopened.resolve()])]
    _,files,_=bridge.selected_sources(ctx,excludes='other.sxm',include_dataset=True)
    assert files==[focus.resolve(),unopened.resolve()]


def test_lattice_gui_declares_checkbox_and_color_legend_settings():
    manifest=json.loads((LATTICE/'module.json').read_text())
    p=manifest['parameters']
    assert p['use_all_scans']=={**p['use_all_scans'],'default':False}
    assert p['use_all_scans']['type']=='bool'
    assert p['vector_legend_corner']['default']=='top_left'
    assert set(p['vector_legend_corner']['choices'])=={'top_left','top_right','bottom_left','bottom_right'}
    assert p['vector_a_color']['type']==p['vector_b_color']['type']=='color'
    assert p['vector_a_color']['default']!=p['vector_b_color']['default']


def test_corner_legend_changes_pixels_and_keeps_arrows_and_angle():
    art=load('lattice_artifacts',LATTICE)
    geom={'shape_yx':[160,180],'pixel_size_nm':[.1,.1],'size_nm':[18.,16.]}
    basis=np.array([[1.02,.33],[.05,.8]])
    img=Image.new('RGB',(180,160),(110,110,110))
    top=art.lattice_draw(img,basis,geom,colors=('#ff0000','#00ff00'),legend_corner='top_left')
    bottom=art.lattice_draw(img,basis,geom,colors=('#ff0000','#00ff00'),legend_corner='bottom_right')
    # Arrows originate in the center and are identical at both legend settings.
    assert np.array_equal(np.asarray(top)[75:95,85:105],np.asarray(bottom)[75:95,85:105])
    assert not np.array_equal(np.asarray(top)[:35,:95],np.asarray(bottom)[:35,:95])
    assert not np.array_equal(np.asarray(top)[-35:,-95:],np.asarray(bottom)[-35:,-95:])
    assert np.any(np.all(np.asarray(top)==(255,0,0),axis=-1))
    assert np.any(np.all(np.asarray(top)==(0,255,0),axis=-1))


def test_new_results_folder_layout_auto_recognized(tmp_path):
    place=load('placement_engine',MOLECULE)
    scan=tmp_path/'my_scan.sxm';scan.write_bytes(b'sxm')
    folder=tmp_path/'SPM_Studio_Results'/'my_scan'/'Data'/'lattice_measurements_20261109_A'
    folder.mkdir(parents=True)
    np.save(folder/'cropped_scan.npy',np.ones((64,64)))
    Image.new('RGB',(64,64)).save(folder/'lattice_preview.png')
    manifest={'schema_version':1,'kind':'spm_studio_lattice_roi','source_scan':str(scan),
      'source_channel':'Z','roi_geometry':{'shape_yx':[64,64],'size_nm':[6.4,6.4],
      'pixel_size_nm':[.1,.1]},'basis_local_nm':[[1.,.3],[0.,.8]],
      'cropped_scan_npy':str(folder/'cropped_scan.npy'),
      'lattice_preview_png':str(folder/'lattice_preview.png')}
    (folder/'lattice_result.json').write_text(json.dumps(manifest))
    source,doc=place.find_lattice_result(scan)
    assert source==folder/'lattice_result.json'
    assert doc['source_scan']==str(scan)
    return doc


def test_exact_molecule_count_and_rotation(tmp_path):
    import importlib.util
    if importlib.util.find_spec('cairosvg') is None and importlib.util.find_spec('PySide6') is None:
        __import__('pytest').skip('SVG molecule artwork needs PySide6 (QtSvg) or CairoSVG')
    place=load('placement_engine',MOLECULE)
    scan=tmp_path/'one.sxm'
    img=tmp_path/'basis.png';Image.new('RGB',(128,128),(100,100,100)).save(img)
    doc={'roi_geometry':{'shape_yx':[128,128],'size_nm':[12.8,12.8],'pixel_size_nm':[.1,.1]},
         'lattice_preview_png':str(img),'basis_local_nm':[[1.,.3],[0.,.8]]}
    svg=tmp_path/'mol.svg'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80"><circle cx="50" cy="40" r="35" fill="blue"/></svg>')
    molecule=place.load_artwork(str(svg))
    assert molecule.size==(100,80)
    params={'molecule_width_nm':.78,'molecule_height_nm':.89,'orientation_mode':'manual',
            'rotation_offset_deg':73.,'origin_x_nm':0.,'origin_y_nm':0.,
            'opacity':.9,'max_molecules':1200,'molecule_count':7}
    output,count,angle,sites=place.render_molecules(doc,molecule,params)
    assert count==len(sites)==7
    assert angle==73.
    assert output.size==(128,128)
    assert all(len(p)==4 for p in sites)
    _,full_count,_,_=place.render_molecules(doc,molecule,{**params,'molecule_count':0})
    assert full_count>7
    _,one_count,_,_=place.render_molecules(doc,molecule,{**params,'molecule_count':1})
    assert one_count==1


def test_factory_migration_restores_missing_and_preserves_custom_scripts(monkeypatch,tmp_path):
    from spm_studio.core import paths
    local=tmp_path/'local'
    local.mkdir()
    monkeypatch.setattr(paths,'scripts_dir',lambda:local)
    monkeypatch.setattr(paths,'bundled_studio_root',lambda:ROOT)
    # Existing customized lattice file must remain untouched.
    custom=local/'lattice_measurements';custom.mkdir()
    (custom/'module.py').write_text('# user customized analysis script\n')
    (custom/'module.json').write_text('{}')
    notes=paths.upgrade_factory_analysis_v13()
    assert (custom/'module.py').read_text()=='# user customized analysis script\n'
    assert (local/'molecule_placement'/'module.json').is_file()
    assert (local/'molecule_placement'/'preview_worker.py').is_file()
    assert any('Restored molecule_placement' in note for note in notes)
    assert any('Preserved user edits' in note for note in notes)
    second=paths.upgrade_factory_analysis_v13()
    assert all('Preserved user edits' in note for note in second)


def test_per_scan_profile_isolation_wired_in_qt_source():
    main=(ROOT/'src/spm_studio/ui/main_window.py').read_text()
    ast.parse(main)
    assert 'self._scan_view_states[path]=view' in main
    assert 'self._remember_scan_view()' in main
    assert 'if path in self._scan_view_states else {}' in main
    assert 'self._scan_profile_keys[str(self.scan.path.resolve())]=selected_key' in main
    assert 'request.get(\'crop_region\')' in main
    assert "self._channel_titles=dict(request.get('channel_titles',{}))" in main
    assert "self.scan_profile_label.setObjectName('ActiveScanProfileV13')" in main


def test_new_module_manifest_is_valid_and_uses_svg_and_exact_count():
    from spm_studio.core.registry import load_manifest
    assert load_manifest(LATTICE/'module.json').version=='0.9.0'
    assert load_manifest(MOLECULE/'module.json').version=='0.10.0'
    manifest=json.loads((MOLECULE/'module.json').read_text())
    assert manifest['parameters']['molecule_image']['type']=='file'
    assert manifest['parameters']['molecule_count']['default']==0
    assert manifest['parameters']['rotation_offset_deg']['type']=='float'


def test_qt_scan_a_and_b_keep_different_profiles_when_switching(monkeypatch,tmp_path):
    """Real GUI-level regression (skipped if the test host lacks PySide6)."""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings
    from spm_studio.ui.main_window import MainWindow
    from spm_studio.core.models import Scan,Channel,Geometry
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    monkeypatch.setenv('XDG_CACHE_HOME',str(tmp_path/'cache'))
    monkeypatch.delenv('RS_APP_ROOT',raising=False)
    monkeypatch.delenv('RESEARCH_STUDIO_DATA',raising=False)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path/'config'))
    app=QApplication.instance() or QApplication([])
    data=np.zeros((64,64),dtype=np.float32)
    geo=Geometry((64,64),(12e-9,12e-9),(0.,0.),0.)
    def scan(name):
        p=tmp_path/name;p.write_bytes(b'placeholder used for cache lookup')
        return Scan(p,{n:Channel(n,'m',{'forward':data},geo)
                       for n in ('Z','OC M1 Freq','OC M1 Excitation','Bias')})
    a,b=scan('a.sxm'),scan('b.sxm')
    def cache_scan(win,s):
        st=s.path.stat();win.cache.put(('scan',(str(s.path),st.st_size,st.st_mtime_ns)),s)
    win=MainWindow()
    try:
        cache_scan(win,a);cache_scan(win,b)
        win._load_file(str(a.path))
        assert win.scan.path==a.path
        assert win.inspector.visible_channel_names()==['Z']
        from spm_studio.shared.ui_strings import set_combo_key
        set_combo_key(win.profile_combo,'Multipass')
        win.apply_profile()
        a_visible=win.inspector.visible_channel_names()
        assert 'OC M1 Freq' in a_visible or 'OC M1 Excitation' in a_visible
        assert win._scan_profile_keys[str(a.path)]=='Multipass'
        win._load_file(str(b.path))
        assert win.scan.path==b.path
        assert win.inspector.visible_channel_names()==['Z']
        assert 'none' in win.scan_profile_label.text()
        set_combo_key(win.profile_combo,'KPFM')
        win.apply_profile()
        assert 'Bias' in win.inspector.visible_channel_names()
        win._load_file(str(a.path))
        assert win.inspector.visible_channel_names()==a_visible
        assert win._scan_profile_keys[str(a.path)]=='Multipass'
        assert 'Multipass' in win.scan_profile_label.text()
        win._load_file(str(b.path))
        assert 'Bias' in win.inspector.visible_channel_names()
        assert win._scan_profile_keys[str(b.path)]=='KPFM'
        assert 'KPFM' in win.scan_profile_label.text()
    finally:
        win.close()
        app.processEvents()


def test_end_to_end_one_scan_fft_then_svg_placement_in_current_results_layout(tmp_path):
    """Run the actual vendor lattice engine, then locate/place SVG molecules."""
    import shutil
    from spm_studio.core.io import read_scan
    project=ROOT.parents[1]
    fixtures=project/'demo-projects'/'Synthetic_TClTAP_Ag111'/'scans'
    if not (fixtures/'Synthetic_lattice_0001.sxm').is_file():
        __import__('pytest').skip('developer-only demo dataset demo-projects/Synthetic_TClTAP_Ag111 is not shipped')
    one=tmp_path/'Synthetic_lattice_0001.sxm'
    two=tmp_path/'Synthetic_lattice_0002.sxm'
    shutil.copy2(fixtures/one.name,one)
    shutil.copy2(fixtures/two.name,two)
    raw=read_scan(one)
    channel=raw.channels['Z']
    run=tmp_path/'SPM_Studio_Results'/one.stem/'Data'/'lattice_measurements_v13_test'
    run.mkdir(parents=True)
    progress=lambda *a,**k:None
    ctx=SimpleNamespace(scan_path=one,source_paths=[one,two],channel='Z',direction='forward',
                        unit=channel.unit,data=channel.get('forward'),geometry=channel.geometry,
                        roi=None,rois=[],output_dir=run,plot_formats=('png','pdf'),
                        parameters={'analysis_method':'primitive_auto','estimate_drift':False,
                                    'use_all_scans':False,'lattice_bootstrap':8,'drift_bootstrap':2,
                                    'trace_direction':'forward','colorbar_position':'right',
                                    'vector_legend_corner':'top_right',
                                    'vector_a_color':'#33ee55','vector_b_color':'#aa44ff'},
                        progress=progress,log=lambda *a,**k:None,
                        result_file=lambda *a,**k:None,result_table=lambda *a,**k:None)
    import sys
    # Each real tool uses an isolated subprocess; prevent in-process test
    # cache collisions with molecule_placement/lattice_artifacts.py.
    module_names=('lattice_artifacts','legacy_engine','roi_pipeline')
    previous={key:sys.modules.pop(key,None) for key in module_names}
    try:
        lattice=load('module',LATTICE)
        sys.path.insert(0,str(LATTICE))
        try:lattice_json=lattice.run(ctx)
        finally:sys.path.remove(str(LATTICE))
    finally:
        for key in module_names:
            sys.modules.pop(key,None)
            if previous[key] is not None:sys.modules[key]=previous[key]
    doc=json.loads(lattice_json.read_text())
    assert doc['vector_legend_corner']=='top_right'
    assert doc['vector_colors']==['#33ee55','#aa44ff']
    assert Path(doc['lattice_region_gwy']).is_file()
    assert (run/'07_reference_scan_lattice_overlay.pdf').is_file()
    assert (run/'07_reference_scan_lattice_overlay.svg').is_file()
    recovered=load('placement_engine',MOLECULE)
    detected,_=recovered.find_lattice_result(one)
    assert detected==lattice_json
    svg=tmp_path/'molecule.svg'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="90" height="110">'
                   '<path d="M15 5 L75 5 L85 55 L75 105 L15 105 L5 55 Z" fill="red"/></svg>')
    molecule_out=tmp_path/'SPM_Studio_Results'/one.stem/'Data'/'molecule_placement_v13_test'
    molecule_out.mkdir()
    previous_engine=sys.modules.pop('placement_engine',None)
    molecule=load('module',MOLECULE)
    ctx2=SimpleNamespace(scan_path=one,parameters={'lattice_result_json':'','molecule_image':str(svg),
                       'molecule_width_nm':.783,'molecule_height_nm':.887,'orientation_mode':'manual',
                       'rotation_offset_deg':40.,'origin_x_nm':0.,'origin_y_nm':0.,'opacity':.9,
                       'max_molecules':1200,'molecule_count':5,'remove_white_background':False},
                       output_dir=molecule_out,plot_formats=('png','pdf'),progress=progress,
                       log=lambda *a,**k:None,result_file=lambda *a,**k:None,
                       result_table=lambda *a,**k:None)
    sys.path.insert(0,str(MOLECULE))
    try:molecule.run(ctx2)
    finally:
        sys.path.remove(str(MOLECULE))
        sys.modules.pop('placement_engine',None)
        if previous_engine is not None:sys.modules['placement_engine']=previous_engine
    manifest=json.loads((molecule_out/'molecule_placement.json').read_text())
    assert manifest['count']==5
    assert manifest['rotation_deg']==40.
    assert manifest['molecule_png_pixels'][1]>=110  # v15 renders SVG at publication sampling
    assert (molecule_out/'lattice_plus_molecules.png').is_file()
