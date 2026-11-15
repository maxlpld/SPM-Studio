"""Offline regression tests for v28 publication axes, global comparisons and zoom insets."""
from pathlib import Path
import numpy as np
from spm_studio.core.bias_figure_analysis import Spectrum
from spm_studio.core.bias_figure_render import create_figure


def _scenario(*, x1=(-1,1),x2=(-1.5,1.5), unit='Hz', signal='Freq. Shift', inset=False):
    c=f'OC M1 {signal} ({unit})'
    spectra={}
    graphs=[]
    for i,(limits,vertex) in enumerate(((x1,-.29),(x2,.31))):
        x=np.linspace(limits[0],limits[1],257)
        y=(x-vertex)**2 * (1+i*.8)+i*.36
        spec=Spectrum(Path(f'/tmp/synthetic_bias_{i}.npz'), ['Bias calc (V)',c],
                      np.column_stack((x,y)))
        spectra[str(spec.path)]=spec
        graphs.append({'title':f'Site {i+1}','channel':c,'unit':'Auto',
                       'traces':[{'path':str(spec.path),'label':f'site {i+1}',
                                  'direction':'Forward','enabled':True,'color':'#AA2233'}],
                       'inset':{'enabled':inset,'bounds':[-.48,-.12,0.,.45],
                                'position':[.57,.53,.40,.40]}})
    return graphs,spectra


def _axes(fig):
    return [ax for ax in fig.axes if getattr(ax,'_spm_plot_main',False)]


def test_common_axes_for_different_bias_windows_and_cpd_sites():
    graphs,specs=_scenario()
    fig,_,warnings=create_figure({'options':{'share_bias':True,'share_signal':True},
                                  'images':[],'graphs':graphs},{},specs)
    assert not warnings
    ax0,ax1=_axes(fig)
    assert ax0.get_xlim()==ax1.get_xlim()
    assert ax0.get_ylim()==ax1.get_ylim()
    assert ax0.get_xlim()[0]<-1.5 and ax0.get_xlim()[1]>1.5
    for ax in (ax0,ax1):
        assert all(spine.get_visible() for spine in ax.spines.values())
        assert ax.xaxis.get_minor_locator() is not None
        assert ax.yaxis.get_minor_locator() is not None
    fig.clear()


def test_manual_bias_limits_and_independent_y_scaling():
    graphs,specs=_scenario()
    fig,_,warnings=create_figure({'options':{'share_bias':True,'share_signal':False,
                                 'bias_min':'-0.75','bias_max':'0.8'},
                                 'images':[],'graphs':graphs},{},specs)
    assert not warnings
    ax0,ax1=_axes(fig)
    assert ax0.get_xlim()==ax1.get_xlim()==(-.75,.8)
    assert ax0.get_ylim()!=ax1.get_ylim()
    fig.clear()


def test_independent_bias_axes_when_disabled():
    graphs,specs=_scenario()
    fig,_,warnings=create_figure({'options':{'share_bias':False,'share_signal':True},
                                  'images':[],'graphs':graphs},{},specs)
    assert not warnings
    ax0,ax1=_axes(fig)
    assert ax0.get_xlim()!=ax1.get_xlim()
    assert ax0.get_ylim()==ax1.get_ylim()
    fig.clear()


def test_inset_bounds_position_and_export_vector(tmp_path):
    graphs,specs=_scenario(inset=True)
    fig,_,warnings=create_figure({'options':{'share_bias':True,'share_signal':True},
                                  'images':[],'graphs':graphs},{},specs)
    assert not warnings
    main=_axes(fig)[0]
    assert len(main.child_axes)==1
    inset=main.child_axes[0]
    assert inset.get_xlim()==(-.48,-.12)
    assert inset.get_ylim()==(0.,.45)
    assert inset._spm_graph_index==0
    pdf=tmp_path/'inset.pdf';svg=tmp_path/'inset.svg'
    fig.savefig(pdf);fig.savefig(svg)
    assert pdf.stat().st_size>8000
    text=svg.read_text()
    assert '<svg' in text and '<path' in text
    fig.clear()


def test_auto_unit_shared_across_small_and_large_signal_magnitudes():
    graphs,specs=_scenario(unit='V',signal='Excitation')
    # Make second site ~100x stronger so individual Auto unit selection would differ.
    second=specs['/tmp/synthetic_bias_1.npz']
    second.data[:,1]*=.001
    first=specs['/tmp/synthetic_bias_0.npz']
    first.data[:,1]*=.1
    fig,_,warnings=create_figure({'options':{'share_bias':True,'share_signal':True},
                                  'images':[],'graphs':graphs},{},specs)
    assert not warnings
    ax0,ax1=_axes(fig)
    assert ax0.get_ylim()==ax1.get_ylim()
    assert ax0.get_ylabel()==ax1.get_ylabel()
    fig.clear()


def test_invalid_manual_limits_fall_back_with_warning():
    graphs,specs=_scenario()
    fig,_,warnings=create_figure({'options':{'bias_min':'3','bias_max':'-3'},
                                  'images':[],'graphs':graphs},{},specs)
    assert any('minimum must be lower' in w for w in warnings)
    assert _axes(fig)[0].get_xlim()[0]<0
    fig.clear()


def test_graph_only_fills_publication_page_without_empty_image_column():
    graphs,specs=_scenario()
    fig,_,warnings=create_figure({'options':{},'images':[],'graphs':graphs},{},specs)
    assert not warnings
    for ax in _axes(fig):
        assert ax.get_position().width>=.79
        assert ax.get_position().x0<.15
    fig.clear()


def test_optional_cpd_guide_is_vertical_and_uses_measured_absolute_bias():
    graphs,specs=_scenario()
    graphs[0]['annotate']=True
    fig,diag,warnings=create_figure({'options':{},'images':[],'graphs':graphs},{},specs)
    assert not warnings
    ax=_axes(fig)[0]
    guides=[line for line in ax.lines if np.ptp(line.get_xdata())==0]
    assert guides
    assert any(abs(line.get_xdata()[0]-(-.29))<.02 for line in guides)
    assert any(row.get('kind')=='cpd' and row.get('accepted') for row in diag)
    fig.clear()
