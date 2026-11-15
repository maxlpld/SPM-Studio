import json,subprocess,sys,os
from pathlib import Path
import numpy as np
import pytest
from spm_studio.core.models import Geometry,Channel,Scan
from spm_studio.core.module_api import from_snapshot
from spm_studio.core.registry import discover_modules
from spm_studio.core.analysis_utils import profile_between

ROOT=Path(__file__).resolve().parents[1]
BUILTINS=ROOT/'src/spm_studio/builtin_modules'

def _context(tmp_path,arr,params=None):
    folder=tmp_path/'run';folder.mkdir(exist_ok=True)
    path=folder/'arrays.npz'
    np.savez(path,**{'Z|forward':arr,'Z|backward':-arr})
    source=tmp_path/'example.sxm';source.write_bytes(b'fixture')
    info={'scan_path':str(source),'channel':'Z','direction':'forward',
          'selected_key':'Z|forward','unit':'m','geometry':Geometry(arr.shape,(5e-9,5e-9)).to_dict(),
          'output_dir':str(folder),'array_file':str(path),'parameters':params or {},'source_paths':[]}
    p=folder/'context.json';p.write_text(json.dumps(info))
    return p

def test_all_packaged_modules_discoverable_and_hardware_not_installed():
    mods,warnings=discover_modules([BUILTINS])
    assert not warnings and len(mods)==5  # v15 retires redundant molecule/lattice overlay
    assert 'amp_calib' not in mods
    assert 'molecule_placement' not in mods  # the obsolete disabled duplicate was removed
    assert 'batch_scan_report' not in mods

def test_module_event_stream_and_output(tmp_path):
    arr=np.tile(np.linspace(-1e-9,2e-9,45),(25,1))
    context=_context(tmp_path,arr,{'edge_decrease_run':3,'find_stripes':False,'prominence_si':0.,'trace_mode':'selected'})
    payload=json.loads(context.read_text())
    payload['rois']=[{'kind':'line','points_px':[[0,12],[44,12]]},
                     {'kind':'line','points_px':[[0,16],[44,16]]}]
    context.write_text(json.dumps(payload))
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')+os.pathsep+env.get('PYTHONPATH','')
    cmd=[sys.executable,'-m','spm_studio.core.module_runner','--entry-file',str(BUILTINS/'flake_height/module.py'),
         '--context',str(context)]
    out=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=30)
    assert out.returncode==0,out.stdout+'\n'+out.stderr
    assert 'SPM_EVENT ' in out.stdout
    assert (context.parent/'flake_height.pdf').is_file()
    assert (context.parent/'heights.csv').is_file()

def test_line_profile_interpolation():
    arr=np.arange(10,dtype=float)[None,:].repeat(10,axis=0)
    x,y=profile_between(arr,(0,5),(8,5),samples=9)
    np.testing.assert_allclose(y,np.arange(9))

def test_missing_backward_no_fallback(tmp_path):
    context=_context(tmp_path,np.ones((6,6)))
    obj=from_snapshot(context)
    np.testing.assert_array_equal(obj.image('Z','backward'),-np.ones((6,6)))
    with pytest.raises(KeyError):obj.image('Bias','forward')

def test_histogram_fit_si_scaling_is_finite():
    import importlib.util
    file=BUILTINS/'cpd_histogram/module.py'
    spec=importlib.util.spec_from_file_location('cpd_test',file)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rng=np.random.default_rng(4)
    values=np.r_[rng.normal(-.1e-9,.01e-9,4000),rng.normal(.25e-9,.02e-9,4000)]
    xx,yy,params=mod._fit_populations(values,2,100)
    assert len(params)==2 and np.isfinite(xx).all() and np.isfinite(yy).all()
    assert np.allclose([p[0] for p in params],[-.1e-9,.25e-9],atol=.02e-9)

def test_cross_channel_mismatched_extent_rejected(tmp_path):
    context=_context(tmp_path,np.ones((6,6)))
    data=json.loads(context.read_text())
    data['channel_geometries']={'Z':Geometry((6,6),(5e-9,5e-9)).to_dict(),
                                'Bias':Geometry((6,6),(8e-9,5e-9)).to_dict()}
    np.savez(context.parent/'arrays.npz',**{'Z|forward':np.ones((6,6)),
                 'Bias|forward':np.ones((6,6))})
    context.write_text(json.dumps(data))
    ctx=from_snapshot(context)
    with pytest.raises(ValueError,match='different geometry'):
        ctx.image('Bias','forward')


def test_v36_real_runner_accepts_svg_formats_and_scan_display(tmp_path):
    """The exact context the app sends since v34: SVG figures + the scan display config."""
    from spm_studio.core.plot_settings import DEFAULT_PLOT
    arr=np.tile(np.linspace(-1e-9,2e-9,45),(25,1))
    context=_context(tmp_path,arr,{'edge_decrease_run':3,'find_stripes':False,'prominence_si':0.,'trace_mode':'selected'})
    payload=json.loads(context.read_text())
    payload['rois']=[{'kind':'line','points_px':[[0,12],[44,12]]},{'kind':'line','points_px':[[0,16],[44,16]]}]
    lut=[[i,i,i] for i in range(256)]
    payload['plot_formats']=['png','svg']
    payload['plot_config']={**DEFAULT_PLOT,'viewer_config':{'enabled':True,'channels':{'Z':{
        'colormap':'gray','lut':lut,'title':'$\\\\Delta f_{TR}$','range_mode':'percentile','low':1.,'high':99.,
        'gamma':1.,'scale_bar':True,'colorbar':True}}}}
    context.write_text(json.dumps(payload))
    assert from_snapshot(context).plot_formats==('png','svg')
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')+os.pathsep+env.get('PYTHONPATH','')
    cmd=[sys.executable,'-m','spm_studio.core.module_runner','--entry-file',str(BUILTINS/'flake_height/module.py'),
         '--context',str(context)]
    out=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=60)
    assert out.returncode==0,out.stdout+'\n'+out.stderr
    assert (context.parent/'flake_height.svg').is_file() and (context.parent/'flake_height.png').is_file()
