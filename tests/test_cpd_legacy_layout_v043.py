"""Check three independent scan panels and comparison histogram against legacy layout."""
import importlib.util
import json
from pathlib import Path
import numpy as np
from spm_studio.core.models import Channel, Geometry, Scan, ROI
from spm_studio.core.module_api import ModuleContext, select_snapshot_arrays,from_snapshot
from spm_studio.core.plot_settings import DEFAULT_PLOT
from spm_studio.core.registry import load_manifest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/'scripts/cpd_histogram/module.py'

def load():
    spec=importlib.util.spec_from_file_location('cpd_legacy_layout_test',MODULE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def context(tmp_path):
    rng=np.random.default_rng(2026)
    bias=rng.normal(.27,.08,(33,45))
    z=rng.normal(0,1.1e-10,(32,45))
    other=rng.normal(0,1,(33,45))
    geo=Geometry(bias.shape,size_m=(9e-9,6.5e-9))
    z_geo=Geometry(z.shape,size_m=(9e-9,6.5e-9))
    channels={'Bias':Channel('Bias','V',{'forward':bias},geo),
              'Z':Channel('Z','m',{'forward':z},z_geo),
              'Other':Channel('Other','V',{'forward':other},geo)}
    scan=Scan(tmp_path/'scan.sxm',channels)
    params={'trace_mode':'selected','bins':36,'populations':0,'raw_populations':0,
            'add_mask_fits_to_raw':False,'comparison_with_masked_image':True,
            'image_scale_bar':True,'scale_bar_color':'white',
            'masks_json':json.dumps([{'name':'Low','low':0.1,'high':0.25,'color':'#ff4411','populations':0},
                                      {'name':'High','low':0.28,'high':0.48,'color':'#1188ff','populations':0}]),
            'topography_channel':'Z','bias_panel_channel':'Bias','rotate_export_180':True}
    module=load_manifest(ROOT/'scripts/cpd_histogram/module.json')
    assert module.snapshot_parameter_channels==('topography_channel','bias_panel_channel')
    arrays=select_snapshot_arrays(scan,'Bias',module.snapshot_channels,('Z','Bias'))
    assert set(arrays)=={'Bias|forward','Z|forward'}
    return ModuleContext(scan.path,'Bias','forward',bias,'V',geo,{},params,tmp_path,[],arrays,
                         ROI('rectangle',((2,4),(41,29))),[],
                         {name:ch.geometry.to_dict() for name,ch in channels.items()},[],
                         DEFAULT_PLOT.copy(),('png',),{name:ch.unit for name,ch in channels.items()})


def test_three_scan_panels_and_histogram_span(tmp_path):
    ctx=context(tmp_path)
    module=load()
    from matplotlib import pyplot as plt
    spatial=np.ones(ctx.data.shape,dtype=bool)
    masks=module._masks(ctx.parameters)
    edges=np.histogram_bin_edges(ctx.data,bins=36)
    raw=np.histogram(ctx.data,bins=edges)[0]/ctx.data.size/np.diff(edges)
    figure=module._composite_mask_figure(ctx,plt,'forward',ctx.data,spatial,masks,edges,raw,ctx.data.size,(15,10.5))
    assert figure._spm_cpd_panel_names==['Z / Topography','Bias raw','Selected mask regions']
    assert len(figure._spm_cpd_panel_axes)==3
    assert len(figure._spm_cpd_panel_axes[0].images)==1
    assert len(figure._spm_cpd_panel_axes[1].images)==1
    assert len(figure._spm_cpd_panel_axes[2].images)==2
    assert np.allclose(figure._spm_cpd_panel_axes[0].images[0].get_array(),np.rot90(ctx.arrays['Z|forward']*1e12,2))
    assert figure._spm_cpd_histogram_ax.get_subplotspec().rowspan.stop==3
    figure.savefig(tmp_path/'layout.png',dpi=95)
    assert (tmp_path/'layout.png').stat().st_size>10000
    plt.close(figure)


def test_comparison_png_and_selected_trace(tmp_path):
    ctx=context(tmp_path)
    ctx.log=lambda *args,**kwargs:None
    ctx.progress=lambda *args,**kwargs:None
    ctx.result_file=lambda *args,**kwargs:None
    ctx.result_table=lambda *args,**kwargs:None
    load().run(ctx)
    expected=tmp_path/'scan_with_masks_bias_histogram_forward_mask_comparison_with_masked_image.png'
    assert expected.is_file() and expected.stat().st_size>12000
    metadata=json.loads((tmp_path/'scan_with_masks_bias_histogram_forward_mask_comparison_with_masked_image_figure_settings.json').read_text())
    assert metadata['rendered_panels']==['Z / Topography','Bias raw','Selected mask regions']
    assert metadata['available_channels']==['Bias','Z']
    assert metadata['legacy_rotation_180'] is True
    mask=np.load(tmp_path/'forward_mask_01.npy')
    assert mask.shape==ctx.data.shape and np.sum(mask)>0
    assert not (tmp_path/'scan_with_masks_bias_histogram_forward_mask_comparison_with_masked_image.pdf').exists()


def test_undeclared_channel_not_copied(tmp_path):
    ctx=context(tmp_path)
    from spm_studio.core.models import Scan,Channel
    geo=ctx.geometry
    scan=Scan(tmp_path/'other.sxm',{
        'Bias':Channel('Bias','V',{'forward':ctx.data},geo),
        'Current':Channel('Current','A',{'forward':ctx.data},geo)})
    assert set(select_snapshot_arrays(scan,'Bias',extra_channels=('Missing','Current')))=={
        'Bias|forward','Current|forward'}
