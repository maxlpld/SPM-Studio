"""Regression coverage for shared figure controls and restored module workflows."""
import json,sys,subprocess,os
from pathlib import Path
import numpy as np
import pytest
from spm_studio.core.plot_settings import validate_plot, DEFAULT_PLOT,available_styles,display_cmap
from spm_studio.core.models import Geometry

ROOT=Path(__file__).resolve().parents[1]


def test_style_validation_and_multiple_files(tmp_path):
    custom={**DEFAULT_PLOT,'name':'Conference','grid':True,'font_size':13,
            'channel_colormaps':{'Bias':'coolwarm'}}
    (tmp_path/'conference.json').write_text(json.dumps(custom))
    (tmp_path/'invalid.json').write_text(json.dumps({'schema_version':1,'font_size':-3}))
    styles,errors=available_styles(tmp_path)
    assert 'conference' in styles and len(errors)==1
    assert display_cmap('Bias',styles['conference'])=='coolwarm'
    with pytest.raises(ValueError,match='Unsupported'):
        validate_plot({**DEFAULT_PLOT,'unrecognized':1})


def _fixture(tmp_path,module,parameters,plot_formats=('png',)):
    rng=np.random.default_rng(8)
    data=rng.normal(.1,.03,(40,50))
    folder=tmp_path/'out';folder.mkdir()
    file=folder/'arrays.npz'
    np.savez(file,**{'Bias|forward':data,'Bias|backward':data*1.01})
    input=tmp_path/'example.sxm';input.write_bytes(b'synthetic')
    ctx={'scan_path':str(input),'channel':'Bias','direction':'forward',
        'selected_key':'Bias|forward','unit':'V','geometry':Geometry(data.shape,(4e-9,3e-9)).to_dict(),
        'output_dir':str(folder),'array_file':str(file),'source_paths':[],
        'plot_config':DEFAULT_PLOT,'plot_formats':list(plot_formats),'parameters':parameters}
    cp=folder/'context.json';cp.write_text(json.dumps(ctx))
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')+os.pathsep+env.get('PYTHONPATH','')
    command=[sys.executable,'-m','spm_studio.core.module_runner','--entry-file',
             str(ROOT/'src/spm_studio/builtin_modules'/module/'module.py'),'--context',str(cp)]
    run=subprocess.run(command,text=True,capture_output=True,env=env,timeout=50)
    assert run.returncode==0,run.stdout+'\n'+run.stderr
    return folder


def test_masked_histograms_respect_pdf_only_and_produce_reusable_masks(tmp_path):
    mask={'name':'Island','low':.07,'high':.13,'color':'#72aadd','populations':1}
    folder=_fixture(tmp_path,'cpd_histogram',{'trace_mode':'selected','bins':45,
        'populations':2,'masks_json':json.dumps([mask])},('pdf',))
    assert (folder/'forward_histograms_and_mask.pdf').is_file()
    assert (folder/'forward_mask_comparison.pdf').is_file()
    assert (folder/'forward_mask_01.pdf').is_file()
    assert not list(folder.glob('*.png'))
    assert (folder/'forward_mask_01.npy').is_file()
    recovered=json.loads((folder/'forward_masks.json').read_text())
    assert recovered[0]['name']=='Island'
    assert recovered[0]['populations']==1


def test_flake_edges_independently_measure_two_sides():
    import importlib.util
    path=ROOT/'src/spm_studio/builtin_modules/flake_height/module.py'
    spec=importlib.util.spec_from_file_location('flake_tests',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    profile=np.array([0,1,3,5,5,5,5,4,3,3,3,3,2,0],dtype=float)
    m=mod.measure_profile(profile,3)
    assert m['left_height']==5
    assert m['right_height']>=3


def test_cpd_invalid_mask_rejected():
    import importlib.util
    path=ROOT/'src/spm_studio/builtin_modules/cpd_histogram/module.py'
    spec=importlib.util.spec_from_file_location('cpd_mask_tests',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    with pytest.raises(ValueError):
        mod._masks({'masks_json':'[{"name":"bad","low":2,"high":1}]','populations':2})
