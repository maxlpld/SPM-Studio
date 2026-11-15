"""Numerical and export acceptance tests for migrated CPD workflows."""
import json
from pathlib import Path
import numpy as np
from spm_studio.core.module_api import ModuleContext
from spm_studio.core.models import Geometry,ROI
from spm_studio.core.plot_settings import DEFAULT_PLOT
from spm_studio.core.analysis_utils import rectangle_slices,region_mask


def _ctx(tmp_path,plot_formats=('png',),populations=0):
    rng=np.random.default_rng(20261015)
    arr=np.r_[rng.normal(.18,.035,1024),rng.normal(.38,.04,1024)].reshape(32,64)
    params={'trace_mode':'selected','bins':64,'populations':populations,
            'raw_populations':0,'add_mask_fits_to_raw':True,
            'comparison_with_masked_image':True,'image_scale_bar':True,
            'scale_bar_color':'white','plot_title':'','x_axis_label':'','y_axis_label':'',
            'masks_json':json.dumps([{'name':'Substrate','low':.04,'high':.28,'populations':populations,'color':'#ff7744'},
                                     {'name':'Island','low':.29,'high':.55,'populations':populations,'color':'#4488ff'}])}
    return ModuleContext(tmp_path/'20260818_Ag_TClTAP_Pt_0008.sxm','Bias','forward',arr,'V',
                         Geometry(arr.shape,size_m=(8e-9,4e-9)),{},params,tmp_path,[],
                         {'Bias|forward':arr},ROI('rectangle',((8,2),(55,28))),[],{},[],
                         DEFAULT_PLOT.copy(),tuple(plot_formats))


def _run(ctx):
    import importlib.util
    entry=Path(__file__).resolve().parents[1]/'scripts/cpd_histogram/module.py'
    spec=importlib.util.spec_from_file_location('cpd_test_v042',entry)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files=[]
    ctx.result_file=lambda path,title='':files.append(Path(path))
    ctx.result_table=lambda *args,**kwargs:None
    ctx.progress=lambda *args,**kwargs:None
    ctx.log=lambda *args,**kwargs:None
    module.run(ctx)
    return files


def test_composite_mask_comparison_filename_and_contents(tmp_path):
    ctx=_ctx(tmp_path)
    files=_run(ctx)
    expected=tmp_path/'20260818_Ag_TClTAP_Pt_0008_with_masks_bias_histogram_forward_mask_comparison_with_masked_image.png'
    assert expected in files and expected.stat().st_size>10000
    import matplotlib.image as mpimg
    im=mpimg.imread(expected)
    assert im.ndim==3 and im.shape[1]>im.shape[0]
    meta=json.loads((tmp_path/'forward_masks.json').read_text())
    assert len(meta)==2
    area=region_mask(ctx.roi,ctx.data.shape)
    for n in (1,2):
        mask=np.load(tmp_path/f'forward_mask_{n:02d}.npy')
        assert np.all(~mask|area)
    assert (tmp_path/'histogram_fits.csv').is_file()


def test_comparison_respects_pdf_only(tmp_path):
    ctx=_ctx(tmp_path,('pdf',))
    files=_run(ctx)
    assert any(p.name.endswith('with_masked_image.pdf') for p in files)
    assert all(p.suffix!='.png' for p in files if p.suffix in ('.png','.pdf'))


def test_mask_derived_raw_fit_with_one_component(tmp_path):
    ctx=_ctx(tmp_path,populations=1)
    _run(ctx)
    import csv
    with (tmp_path/'histogram_fits.csv').open() as f:
        rows=list(csv.DictReader(f))
    assert len(rows)==2
    assert all(float(r['sigma_SI'])>0 for r in rows)


def test_rectangle_bounds_are_bounded_and_non_destructive():
    arr=np.arange(80).reshape(8,10)
    roi=ROI('rectangle',((-5.1,3.1),(3.5,14)))
    y,x=rectangle_slices(roi,arr.shape)
    assert (y.start,y.stop,x.start,x.stop)==(3,8,0,4)
    cropped=arr[y,x]
    assert cropped.shape==(5,4)
    assert arr[0,0]==0
