"""End-to-end synthetic regression of calibrated ROI -> molecule workflow."""
from pathlib import Path
import sys, json, math, struct
from types import SimpleNamespace
import numpy as np
from PIL import Image, ImageDraw
import pytest
from spm_studio.core.models import Geometry, ROI

BASE=Path(__file__).resolve().parents[1]/'scripts'
LATTICE=BASE/'lattice_measurements'
MOLECULE=BASE/'molecule_placement'


def _import_at(folder,name):
    import importlib.util
    path=folder/(name+'.py')
    sys.path.insert(0,str(folder))
    try:
        spec=importlib.util.spec_from_file_location(name,path)
        mod=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:sys.path.remove(str(folder))


def _periodic(nx=256,ny=256,w=12,h=14):
    x,y=np.meshgrid((np.arange(nx)+.5)/nx*w-w/2,h/2-(np.arange(ny)+.5)[:,None]/ny*h)
    a=np.array([1.02,0.]);b=np.array([0.83*math.cos(math.radians(68)),0.83*math.sin(math.radians(68))])
    g=np.linalg.inv(np.column_stack((a,b))).T
    im=np.cos(2*np.pi*(g[0,0]*x+g[1,0]*y))+np.cos(2*np.pi*(g[0,1]*x+g[1,1]*y))
    return im,Geometry(im.shape,(w*1e-9,h*1e-9),(5e-9,6e-9),angle_deg=0)


def _make_ctx(tmp_path):
    arr,geo=_periodic()
    scan=tmp_path/'scan.sxm';scan.write_text('unchanged instrument file',encoding='utf8')
    run=tmp_path/'SPM_Studio_Results'/'scan'/'20261017_lattice_measurements_fixture';run.mkdir(parents=True)
    roi=ROI('rectangle',((12.,20.),(237.,225.)))
    def progress(*a,**k):pass
    files=[]
    ctx=SimpleNamespace(data=arr,geometry=geo,channel='Z',direction='forward',unit='m',
                        scan_path=scan,parameters={'analysis_method':'primitive_auto','estimate_drift':False},
                        roi=roi,rois=[],output_dir=run,source_paths=[scan],plot_formats=('png','pdf'),
                        progress=progress,log=lambda *a,**k:None,result_file=lambda *a,**k:files.append(a[0]),
                        result_table=lambda *a,**k:None)
    return ctx,files


def test_roi_crop_scales_and_original_unchanged(tmp_path):
    pytest.importorskip('PySide6')   # v0.8: figures use the Qt Export-panel renderer
    ctx,files=_make_ctx(tmp_path)
    ctx.parameters['export_gwy']=True
    text=ctx.scan_path.read_bytes()
    lattice=_import_at(LATTICE,'module')
    # The module's adjacent imports are resolved using the module folder.
    artifact=lattice.run(ctx)
    assert artifact.is_file() and ctx.scan_path.read_bytes()==text
    doc=json.loads(artifact.read_text())
    assert doc['roi_geometry']['shape_yx']==[206,226]
    assert doc['roi_geometry']['pixel_bounds_xyxy']==[12,20,238,226]
    assert doc['roi_geometry']['pixel_size_nm']==pytest.approx([12/256,14/256])
    assert doc['roi_geometry']['size_nm']==pytest.approx([226*12/256,206*14/256])
    assert doc['roi_geometry']['center_sample_nm'] is not None
    assert (doc['a_nm'],doc['b_nm'],doc['gamma_deg'])==pytest.approx((1.02,.83,68),rel=.035)
    assert doc['lattice_preview_png'] is None          # v0.8: no separate gray preview PNG
    assert not (ctx.output_dir/'lattice_preview.png').exists()
    assert Path(doc['cropped_scan_npy']).is_file()
    assert Path(doc['lattice_region_gwy']).read_bytes().startswith(b'GWYPGwyContainer\0')
    figures=[Path(f) for f in doc['publication_figures']]
    assert {f.suffix for f in figures}=={'.png','.pdf'} and all(f.is_file() for f in figures)
    assert all(f.stem=='07_reference_scan_lattice_overlay' for f in figures)
    assert all(artifact in files for artifact in figures+[Path(doc['lattice_region_gwy'])])


def test_molecule_is_placed_on_duplicate_with_physical_scale(tmp_path):
    pytest.importorskip('PySide6')
    ctx,_=_make_ctx(tmp_path)
    lattice=_import_at(LATTICE,'module')
    artifact=lattice.run(ctx)
    art=tmp_path/'molecule.png'
    im=Image.new('RGBA',(120,180),(0,0,0,0));ImageDraw.Draw(im).ellipse((2,2,118,178),fill=(255,45,30,225));im.save(art)
    doc=json.loads(artifact.read_text())
    original=Path(doc['cropped_scan_npy']).read_bytes()
    out=tmp_path/'SPM_Studio_Results'/'scan'/'20261017_molecule_placement_fixture';out.mkdir()
    params={'molecule_image':str(art),'lattice_result_json':'',
            'molecule_width_nm':.783,'molecule_height_nm':.887,
            'orientation_mode':'align_height_a','rotation_offset_deg':0.,
            'origin_x_nm':0.,'origin_y_nm':0.,'opacity':.9,'max_molecules':1200,
            'remove_white_background':False,'export_gwy':True}
    placement=_import_at(MOLECULE,'module')
    ctx2=SimpleNamespace(scan_path=ctx.scan_path,parameters=params,output_dir=out,plot_formats=('png','pdf'),
                         progress=lambda *a,**k:None,log=lambda *a,**k:None,
                         result_file=lambda *a,**k:None,result_table=lambda *a,**k:None)
    placement.run(ctx2)
    assert Path(doc['cropped_scan_npy']).read_bytes()==original
    assert (out/'lattice_plus_molecules.png').is_file()
    assert (out/'lattice_plus_molecules.pdf').is_file()
    assert (out/'lattice_plus_molecules.gwy').read_bytes().startswith(b'GWYP')
    m=json.loads((out/'molecule_placement.json').read_text())
    assert m['count']>50
    assert m['pixel_size_nm']==doc['roi_geometry']['pixel_size_nm']
    # Transparent margins are trimmed by default; metadata stores visible artwork dimensions.
    assert m['artwork_scale']['artwork_canvas_px'] == [120, 180]
    assert m['molecule_png_pixels'] == m['artwork_scale']['visible_molecule_px']
    assert 0 < m['molecule_png_pixels'][0] <= 120
    assert 0 < m['molecule_png_pixels'][1] <= 180
    assert m['rotation_deg']==pytest.approx(math.degrees(math.atan2(doc['basis_local_nm'][1][0],doc['basis_local_nm'][0][0]))-90)
    assert np.any(np.asarray(Image.open(out/'lattice_plus_molecules.png'))[:,:,0]>200)
    assert ctx.scan_path.read_text()=='unchanged instrument file'


def test_invalid_region_and_mismatched_manifest(tmp_path):
    ctx,_=_make_ctx(tmp_path)
    from spm_studio.core.models import ROI
    ctx.roi=ROI('rectangle',((2,2),(3,3)))
    lattice=_import_at(LATTICE,'module')
    with pytest.raises(ValueError,match='32'):lattice.run(ctx)
    pytest.importorskip('PySide6')
    # A source from another scan is not silently used for the wrong instrument image.
    ctx.roi=ROI('rectangle',((12,20),(237,225)))
    artifact=lattice.run(ctx)
    engine=_import_at(MOLECULE,'placement_engine')
    other=tmp_path/'another.sxm';other.write_bytes(b'')
    with pytest.raises(ValueError,match='DIFFERENT'):
        engine.find_lattice_result(other,str(artifact))


def test_warp_preserves_units_for_anisotropic_pixels(tmp_path):
    engine=_import_at(MOLECULE,'placement_engine')
    # One opaque tiny molecule, placed at origin, must have physical width
    # W and height H despite different x/y pixels per nm.
    source=Image.new('RGBA',(80,80),(255,0,0,255))
    base=Image.new('RGBA',(200,200),(0,0,0,0))
    geo={'size_nm':[20.,40.],'pixel_size_nm':[.1,.2]}
    engine._place_artwork(base,source,geo,(0.,0.),0.,2.,4.,1.)
    mask=np.asarray(base)[:,:,3]>150
    ys,xs=np.where(mask)
    assert (xs.max()-xs.min()+1)==pytest.approx(20,abs=2)
    assert (ys.max()-ys.min()+1)==pytest.approx(20,abs=2)
    base2=Image.new('RGBA',(200,200),(0,0,0,0))
    engine._place_artwork(base2,source,geo,(0.,0.),90.,2.,4.,1.)
    ys,xs=np.where(np.asarray(base2)[:,:,3]>150)
    assert xs.max()-xs.min()+1==pytest.approx(40,abs=2)
    assert ys.max()-ys.min()+1==pytest.approx(10,abs=2)


def test_gwy_binary_layout_primitive_vectors_and_nan_mask(tmp_path):
    """Independent byte decoder for the documented GWYP format, not just magic bytes."""
    artifact=_import_at(LATTICE,'lattice_artifacts')
    shape=[31,41]
    geom={'shape_yx':shape,'size_nm':[4.1,6.2], 'pixel_size_nm':[.1,.2],
          'scan_angle_deg':0.,'center_sample_nm':[20.,30.],
          'orientation':'stored-array'}
    data=np.arange(31*41,dtype=float).reshape(shape)
    data[3,5]=np.nan
    path=tmp_path/'crop.gwy'
    artifact.write_gwy(path,[('Z',data,'m')],geom,
                       basis_local_nm=np.array([[1.,.3],[0.,.8]]),
                       extra_metadata={'gamma':'69.44 degrees'})
    raw=path.read_bytes()
    assert raw[:4]==b'GWYP'
    def decode_object(start):
        end=raw.index(b'\0',start);name=raw[start:end].decode();start=end+1
        n=struct.unpack_from('<I',raw,start)[0];start+=4;stop=start+n
        parts={}
        while start<stop:
            end=raw.index(b'\0',start);key=raw[start:end].decode();start=end+1
            kind=chr(raw[start]);start+=1
            if kind=='o': value,start=decode_object(start)
            elif kind=='s':
                end=raw.index(b'\0',start);value=raw[start:end].decode();start=end+1
            elif kind=='i':value=struct.unpack_from('<i',raw,start)[0];start+=4
            elif kind=='d':value=struct.unpack_from('<d',raw,start)[0];start+=8
            elif kind=='D':
                count=struct.unpack_from('<I',raw,start)[0];start+=4
                value=np.frombuffer(raw,dtype='<f8',count=count,offset=start).copy();start+=count*8
            else:raise AssertionError(kind)
            parts[key]=value
        assert start==stop
        return {'type':name,'parts':parts},start
    container,end=decode_object(4)
    assert end==len(raw)
    fields=container['parts'];assert container['type']=='GwyContainer'
    z=fields['/0/data']['parts'];assert fields['/0/data']['type']=='GwyDataField'
    assert z['xres']==41 and z['yres']==31
    assert z['xreal']==pytest.approx(4.1e-9)
    assert z['yreal']==pytest.approx(6.2e-9)
    assert z['si_unit_xy']['parts']['unitstr']=='m'
    assert z['si_unit_z']['parts']['unitstr']=='m'
    assert z['data'].size==31*41 and np.all(np.isfinite(z['data']))
    assert fields['/0/mask']['parts']['data'].reshape(shape)[3,5]==1
    assert fields['/0/select/line']['type']=='GwySelectionLine'
    assert fields['/0/select/line']['parts']['max']==2
    assert len(fields['/0/select/line']['parts']['data'])==8
    assert fields['/0/meta']['parts']['gamma']=='69.44 degrees'


def test_interactive_preview_subprocess_roundtrip(tmp_path):
    """The interactive thumbnail runs outside Qt/main process and uses live parameters."""
    import subprocess,base64,io
    pytest.importorskip('PySide6')
    ctx,_=_make_ctx(tmp_path)
    lattice=_import_at(LATTICE,'module')
    lattice.run(ctx)
    art=tmp_path/'art.png'
    Image.new('RGBA',(16,24),(90,120,255,180)).save(art)
    params={'lattice_result_json':'','molecule_image':str(art),
            'molecule_width_nm':.783,'molecule_height_nm':.887,
            'orientation_mode':'manual','rotation_offset_deg':45,
            'origin_x_nm':0,'origin_y_nm':0,'opacity':.8,
            'max_molecules':1200,'remove_white_background':False}
    commands=[{'sequence':idx,'scan_path':str(ctx.scan_path),
               'parameters':{**params,'rotation_offset_deg':angle}}
              for idx,angle in [(5,10),(6,45)]]
    cmd='\n'.join(json.dumps(c) for c in commands)+'\n'
    output=subprocess.run([sys.executable,str(MOLECULE/'preview_worker.py')],
                          input=cmd,capture_output=True,text=True,timeout=20)
    assert output.returncode==0,output.stderr
    results=[json.loads(s) for s in output.stdout.splitlines()]
    assert len(results)==2
    assert [r['sequence'] for r in results]==[5,6]
    assert all(r['ok'] for r in results),results
    assert results[0]['rotation_deg']==10
    assert results[1]['rotation_deg']==45
    assert results[0]['count']>0
    first=Image.open(io.BytesIO(base64.b64decode(results[0]['image_png_base64'])))
    assert max(first.size)<=1050  # v15 renders at full-channel preview resolution


def test_svg_artwork_optional_support(tmp_path):
    engine=_import_at(MOLECULE,'placement_engine')
    cairosvg=pytest.importorskip('cairosvg')
    art=tmp_path/'ring.svg'
    art.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80"><circle cx="50" cy="40" r="25" fill="red"/></svg>',encoding='utf8')
    pic=engine.load_artwork(str(art))
    assert pic.size==(100,80)
    assert np.asarray(pic)[:,:,3].max()==255
