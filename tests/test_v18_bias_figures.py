"""Offline v18 regression tests using synthetic data, no instrument connection."""
import json
from pathlib import Path
import numpy as np
import pytest
from spm_studio.core.models import Geometry, Channel, Scan
from spm_studio.core.bias_figure_analysis import (read_spectrum,session_files,get_views,
      find_kink,fit_cpd,linear_trend,map_to_scan_nm,in_scan, Spectrum)
from spm_studio.core.bias_figure_render import create_figure


def synthetic(tmp_path):
    session=tmp_path/'run';session.mkdir()
    manifest={'settings':{'points':256,'backward':True,'bias_start_v':-1.5,'bias_end_v':1.5},
            'initial_state':{'follow_me_x_m':1.1e-9,'follow_me_y_m':-.5e-9},'mode':'SIMULATION'}
    (session/'session.json').write_text(json.dumps(manifest))
    xx=np.linspace(-1.5,1.5,256)
    names=['Bias calc (V)','OC M1 Freq. Shift (Hz)','OC M1 Freq. Shift (Hz) [bwd]',
           'OC M1 Excitation (V)','OC M1 Excitation (V) [bwd]']
    for i,z in enumerate([0.,.4,.8,1.2]):
        rng=np.random.default_rng(i+3)
        vk=.1+.1*z
        y=7*(xx+.2)**2+2.5*(xx>=vk)+1.7*np.maximum(0,xx-vk)
        y+=rng.normal(0,.03,len(xx))
        data=np.column_stack([xx,y,y+rng.normal(0,.03,len(xx)),.02+xx*.002,.021+xx*.002])
        np.savez_compressed(session/f'height_{i:03d}.npz',data=data,channels=np.array(names),z_offset_nm=z)
    geom=Geometry((72,96),(12e-9,8e-9),(0.,0.),0.)
    scan=Scan(tmp_path/'image.sxm',{'Z':Channel('Z','m',{'forward':np.random.default_rng(1).normal(0,1e-11,(72,96))},geom),
                'OC M1 Excitation':Channel('OC M1 Excitation','V',{'forward':np.random.default_rng(2).normal(.02,.002,(72,96))},geom)})
    return scan,session


def test_native_coordinate_and_spectroscopy(tmp_path):
    scan,folder=synthetic(tmp_path)
    spec=read_spectrum(session_files(folder)[0])
    assert (spec.x_m,spec.y_m)==(1.1e-9,-.5e-9)
    assert np.allclose(map_to_scan_nm(scan,spec.x_m,spec.y_m),(7.1,3.5))
    assert len(spec.channels())==2
    assert sorted(get_views(spec,'OC M1 Freq. Shift (Hz)'))==['Backward','Forward']
    g=scan.channels['Z'].geometry
    row,col=g.sample_to_pixel(spec.x_m,spec.y_m)
    x=(col+.5)*12/96
    y=(72-row-.5)*8/72
    assert np.allclose([x,y],[7.1,3.5])
    assert in_scan(scan,(x,y))


def test_native_rotation_and_missing_coordinates(tmp_path):
    geom=Geometry((20,40),(10e-9,20e-9),(0,0),90.)
    scan=Scan(tmp_path/'image.sxm',{'Z':Channel('Z','m',{'forward':np.zeros((20,40))},geom)})
    assert np.allclose(map_to_scan_nm(scan,1e-9,0),(5.,9.))
    scan.path=tmp_path/'converted.gwy'
    assert map_to_scan_nm(scan,1e-9,0) is None


def test_conservative_kinks_and_cpd():
    rng=np.random.default_rng(33)
    x=np.linspace(-1.5,1.5,256)
    parabola=7*(x+.2)**2+rng.normal(0,.04,len(x))
    assert not find_kink(x,parabola).success
    transition=.2
    y=7*(x+.2)**2+3*(x>=transition)+1.6*np.maximum(0,x-transition)+rng.normal(0,.04,len(x))
    result=find_kink(x,y)
    assert result.success, result
    assert abs(result.voltage-transition)<.07
    assert abs(fit_cpd(x,(x-.4)**2).voltage-.4)<.01
    trend=linear_trend([(0,.1,.005),(.4,.14,.005),(.8,.18,.005),(1.2,.22,.005)])
    assert abs(trend['slope']-.1)<1e-6


def test_native_figure_and_pdf(tmp_path):
    scan,folder=synthetic(tmp_path)
    paths=session_files(folder)
    spectra={str(p):read_spectrum(p) for p in paths}
    traces=[{'path':str(p),'scan':str(scan.path),'label':f'Height {i}',
        'direction':'Both','enabled':True,'color':col, 'fit_enabled':True}
        for i,(p,col) in enumerate(zip(paths,['#C8102E','#167BA3','#D39818','#367B52']))]
    project={'options':{'title':'SYNTHETIC — for test only','font':8.,'width':11},
          'images':[{'scan':str(scan.path),'channel':ch,'title':title,'direction':'forward',
                 'cmap':cmap,'processed':True,'style':{'range_mode':'percentile','low':2,'high':98,
                        'processing_steps':[{'operation':'plane','params':{},'enabled':True}]},
                  'unit':'Auto','markers':True,'scalebar':True}
             for ch,title,cmap in [('Z','Topography','gray'),('OC M1 Excitation','Excitation','inferno')]],
          'graphs':[{'title':'Kink vs height','channel':'OC M1 Freq. Shift (Hz)',
                 'unit':'Auto','trend':'Kink vs height','min_bic':14,'min_sigma':4,
                 'trend_direction':'Forward','traces':traces,'annotate':True}]}
    fig,diagnostics,warnings=create_figure(project,{str(scan.path):scan},spectra)
    assert not warnings,warnings
    pdf=tmp_path/'demo.pdf'
    fig.savefig(pdf)
    assert pdf.stat().st_size>10000
    assert len([d for d in diagnostics if d.get('accepted') and d.get('direction')=='Forward'])>=3
    # Explicit image mapping physical width and height, no double-rotation
    images=[img for ax in fig.axes for img in ax.images]
    assert len(images)==2
    assert list(images[0].get_extent())==[0.,12.,0.,8.]
    fig.clear()


def test_missing_metadata_warns_no_fabricated_marker(tmp_path):
    scan,folder=synthetic(tmp_path)
    scan.path=tmp_path/'changed.gwy'
    spec=read_spectrum(session_files(folder)[0]); assert np.isfinite(spec.x_m)
    assert map_to_scan_nm(scan,spec.x_m,spec.y_m) is None


def test_batch_profile_source_contract():
    # Qt-specific app startup is verified separately by verify_spm_v18.sh.
    source=(Path(__file__).resolve().parents[1]/'src/spm_studio/ui/main_window.py').read_text()
    assert 'self.apply_all_profiles_button.clicked.connect(self.apply_profile_to_all_files)' in source
    assert 'self._scan_profile_keys[path]=selected' in source
    assert 'if str(self.scan.path.resolve()) in self._pending_bulk_profiles:' in source
    assert 'self.apply_profile()' in source
    assert 'self.bias_figure_button.clicked.connect(self.open_bias_figure_composer)' in source


def test_bulk_apply_executable_without_qt(tmp_path):
    """Exercise the exact application method's logic with minimal GUI stubs."""
    import ast
    import types
    src=(Path(__file__).resolve().parents[1]/'src/spm_studio/ui/main_window.py').read_text()
    tree=ast.parse(src)
    cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='MainWindow')
    fn=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='apply_profile_to_all_files')
    mod=ast.Module(body=[fn],type_ignores=[])
    ast.fix_missing_locations(mod)
    class FakeBox:
        class StandardButton:
            Yes=1
            No=2
        @classmethod
        def question(cls,*args):return cls.StandardButton.Yes
        @classmethod
        def information(cls,*args):raise AssertionError('Should have files')
        @classmethod
        def warning(cls,*args):raise AssertionError('Should have profile')
    class FakeStatus:
        def showMessage(self,*args): pass
    class FakeScan:
        path=tmp_path/'scan1.sxm'
    class FakeWindow:
        profiles={'STM':{'name':'STM'}}
        profile_combo=object()
        _source_paths=[str(tmp_path/'scan1.sxm'),str(tmp_path/'scan2.sxm'),str(tmp_path/'scan3.sxm')]
        scan=FakeScan()
        _scan_profile_keys={}
        _scan_view_states={str(tmp_path/'scan2.sxm'):{'crop_region':'PRESERVE THIS','profile_key':'KPFM'}}
        _pending_bulk_profiles=set()
        applied=[]
        def apply_profile(self):self.applied.append(self.scan.path)
        def statusBar(self):return FakeStatus()
        def _log(self,*_):pass
    namespace={'combo_key':lambda _:'STM','QMessageBox':FakeBox}
    exec(compile(mod,'<production bulk method>','exec'),namespace)
    FakeWindow.apply_profile_to_all_files=namespace['apply_profile_to_all_files']
    fake=FakeWindow()
    fake.apply_profile_to_all_files()
    assert len(fake._scan_profile_keys)==3
    assert fake.applied==[fake.scan.path]
    assert fake._pending_bulk_profiles==set(fake._source_paths[1:])
    assert fake._scan_view_states[fake._source_paths[1]]['crop_region']=='PRESERVE THIS'
