"""Publication-style Matplotlib layout used identically for live preview and export."""
from __future__ import annotations

from pathlib import Path
from collections import defaultdict
import math
import re
import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, AutoMinorLocator
from matplotlib.patches import Rectangle
from matplotlib.colors import to_rgb

from .models import ImageStyle, ProcessingStep
from .processing import apply as apply_processing
from .display import bounds as display_bounds, lut as studio_lut
from matplotlib.colors import ListedColormap
from .bias_figure_analysis import (get_views, convert_signal, find_kink, fit_cpd, linear_trend,
                       map_to_scan_nm, in_scan, scan_position_m, scan_size_nm, matching_channel)

PALETTE = ['#C8102E', '#167BA3', '#D39818', '#367B52', '#7656A3', '#B55939',
           '#49747A', '#A44987', '#696969', '#2D66BF']


def backward_color(color: str) -> tuple:
    """Related but distinguishable: mix trace colour with paper white."""
    r, g, b = to_rgb(color)
    return tuple(0.64*v+0.36 for v in (r, g, b))


def _style(ax, font, *, inset=False):
    """Four-sided journal axes: inward major/minor ticks, no grid or offset quirks."""
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.85 if not inset else 0.70)
        spine.set_color('#222222')
    ax.tick_params(axis='both', which='major', direction='in', length=4 if not inset else 2.8,
                   width=.8 if not inset else .65, labelsize=font-1.0 if not inset else max(5,font-2),
                   top=True, right=True, pad=3)
    ax.tick_params(axis='both', which='minor', direction='in', length=2.1 if not inset else 1.4,
                   width=.6, top=True, right=True)
    ax.xaxis.set_major_locator(MaxNLocator(5 if not inset else 3))
    ax.yaxis.set_major_locator(MaxNLocator(5 if not inset else 3))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.grid(False)


def _finite_limits(values, *, pad=.04):
    """Never recenter on a fitted vertex; derive limits from actual data."""
    parts=[np.asarray(v,float).ravel() for v in values]
    parts=[v[np.isfinite(v)] for v in parts if v.size]
    parts=[v for v in parts if v.size]
    if not parts:
        return None
    low=min(float(v.min()) for v in parts)
    high=max(float(v.max()) for v in parts)
    span=high-low
    if not span:
        span=max(abs(low)*.05, 1e-3)
    return low-pad*span, high+pad*span


def _manual_bounds(options, warnings):
    """Validate limits without ever silently using an invalid inverted range."""
    overrides={}
    for kind in ('bias','signal'):
        v=[]
        for side in ('min','max'):
            entry=options.get(f'{kind}_{side}','')
            try:
                number=float(entry) if str(entry).strip() else None
                if number is not None and not np.isfinite(number):
                    raise ValueError('not finite')
            except (ValueError,TypeError):
                warnings.append(f'Invalid {kind} {side} limit {entry!r}; using automatic limit')
                number=None
            v.append(number)
        if v[0] is not None and v[1] is not None and v[0]>=v[1]:
            warnings.append(f'{kind} minimum must be lower than maximum; using auto limits')
            v=[None,None]
        overrides[kind]=tuple(v)
    return overrides


def _comparison_key(graph, unit):
    # Only compare like observables, avoiding e.g. frequency shift vs excitation.
    base=re.sub(r'\s*\([^)]*\)\s*$', '',graph.get('channel','')).strip().casefold()
    return base,unit


def _gather_views(graph, trace_specs, warnings):
    raw=[]
    for trace,spec in trace_specs:
        channel=matching_channel(spec,graph.get('channel',''))
        if channel is None:
            warnings.append(f"{Path(spec.path).name}: does not record {graph.get('channel')}")
            continue
        views=get_views(spec,channel)
        for direction,(x,y) in views.items():
            if trace.get('direction','Both') not in ('Both',direction):
                continue
            x=np.asarray(x,float);y=np.asarray(y,float)
            if x.shape!=y.shape or x.ndim!=1:
                warnings.append(f'{Path(spec.path).name}: bias/y shape mismatch')
                continue
            raw.append((trace,spec,direction,x,y,channel))
    return raw


def _prepare_comparison(graphs, specs, options, warnings):
    """Precompute one X range and per-physical-channel Y ranges for all graphs."""
    raw_groups=[_gather_views(g,pairs,warnings) for g,pairs in zip(graphs,specs)]
    # All Auto units for the same native observable use a single pooled unit.
    pools=defaultdict(list)
    names={}
    for graph,raw in zip(graphs,raw_groups):
        base=re.sub(r'\s*\([^)]*\)\s*$', '',graph.get('channel','')).strip().casefold()
        pools[base].extend([entry[4] for entry in raw])
        names[base]=graph.get('channel','')
    auto_units={}
    for base,ys in pools.items():
        auto_units[base]=_group_unit({'channel':names[base],'unit':'Auto'},ys)
    prepared=[];xvalues=[];ypools=defaultdict(list)
    for graph,raw in zip(graphs,raw_groups):
        base=re.sub(r'\s*\([^)]*\)\s*$', '',graph.get('channel','')).strip().casefold()
        requested=graph.get('unit','Auto')
        desired=auto_units.get(base,'Raw') if requested=='Auto' else requested
        converted=[];effective_units=set()
        for trace,spec,direction,x,y,channel in raw:
            yy,unit=convert_signal(y,channel,desired)
            converted.append((trace,spec,direction,x,yy,channel,unit))
            effective_units.add(unit)
            xvalues.append(x)
            ypools[_comparison_key(graph,unit)].append(yy)
        if len(effective_units)>1:
            warnings.append(f"{graph.get('title','Graph')}: mixed Y units; only like-unit graphs share a Y scale")
        prepared.append(converted)
    overrides=_manual_bounds(options,warnings)
    shared_x=_finite_limits(xvalues)
    shared_y={k:_finite_limits(values) for k,values in ypools.items()}
    return prepared,{'x':shared_x,'y':shared_y,'overrides':overrides,
                     'share_x':bool(options.get('share_bias',True)),
                     'share_y':bool(options.get('share_signal',True))}


def _bounds_with_manual(automatic, overrides):
    lo,hi=overrides
    if automatic is None:
        if lo is None or hi is None:return None
        return (lo,hi) if lo<hi else None
    low=automatic[0] if lo is None else lo
    high=automatic[1] if hi is None else hi
    return (low,high) if high>low else automatic


def _inset_region(graph, prepared, main_ax):
    config=graph.get('inset') or {}
    bounds=config.get('bounds')
    if isinstance(bounds,(list,tuple)) and len(bounds)==4:
        try:
            x0,x1,y0,y1=map(float,bounds)
            if np.isfinite([x0,x1,y0,y1]).all() and x0<x1 and y0<y1:
                return (x0,x1,y0,y1)
        except (ValueError,TypeError):pass
    global_x=main_ax.get_xlim()
    span=global_x[1]-global_x[0]
    if span<=0:return None
    # A useful first inset automatically contains detected CPD vertices, if any.
    vertices=[]
    for _trace,_spec,_direction,x,y,_ch,_unit in prepared:
        try:
            result=fit_cpd(x,y)
            if result.success and np.isfinite(result.voltage):vertices.append(float(result.voltage))
        except (ValueError,TypeError,np.linalg.LinAlgError):pass
    if vertices:
        center=(min(vertices)+max(vertices))/2
        half=max(span*.13,(max(vertices)-min(vertices))*.8)
    else:
        center=sum(global_x)/2;half=span*.17
    x0=max(global_x[0],center-half)
    x1=min(global_x[1],center+half)
    if x1<=x0:return None
    crop=[y[np.isfinite(x)&np.isfinite(y)&(x>=x0)&(x<=x1)] for _t,_s,_d,x,y,_c,_u in prepared]
    ylim=_finite_limits(crop,pad=.08) or main_ax.get_ylim()
    return x0,x1,*ylim


def _draw_inset(ax,graph,prepared,font,warnings):
    config=graph.get('inset') or {}
    if not config.get('enabled',False) or not prepared:
        return
    raw_pos=config.get('position',[.57,.53,.40,.40])
    try:
        x,y,w,h=map(float,raw_pos)
    except (ValueError,TypeError):x,y,w,h=.57,.53,.40,.40
    w=np.clip(w,.16,.85);h=np.clip(h,.16,.85)
    x=np.clip(x,0,1-w);y=np.clip(y,0,1-h)
    bounds=_inset_region(graph,prepared,ax)
    if bounds is None:
        warnings.append(f"{graph.get('title','Graph')}: inset has no valid data region")
        return
    ix=ax.inset_axes([x,y,w,h],zorder=12)
    ix.set_facecolor('white');ix._spm_keep_background=True
    ix.patch.set_alpha(.97)
    for trace,_spec,direction,xdata,ydata,_channel,_unit in prepared:
        color=trace.get('color','#C8102E')
        ix.plot(xdata,ydata,color=color if direction=='Forward' else backward_color(color),
                ls='-' if direction=='Forward' else '--',lw=.95,alpha=.95)
    ix.set_xlim(bounds[0],bounds[1]);ix.set_ylim(bounds[2],bounds[3])
    _style(ix,font,inset=True)
    ix._spm_inset=True
    # The GUI uses these indices to offer direct drag-to-move interaction.
    ix._spm_graph_index=getattr(ax,'_spm_graph_index',None)
    ix._spm_inset_parent=ax
    ix._spm_inset_coords=(float(x),float(y),float(w),float(h))
    ax.add_patch(Rectangle((bounds[0],bounds[2]),bounds[1]-bounds[0],bounds[3]-bounds[2],
                           facecolor='none',edgecolor='#444444',linestyle=(0,(3,2)),
                           linewidth=.8,alpha=.8,zorder=4))
    # Keep the inset within its parent graph; never rasterize vector axes/text.


def _round_scale(v):
    if v<=0: return 0.
    magnitude=10**math.floor(math.log10(v))
    for x in (5, 2, 1):
        if x*magnitude<=v: return x*magnitude
    return magnitude


def _plot_image(fig, rectangle, panel, scan, marker_specs, font, warnings):
    left, bottom, width, height = rectangle
    # Keep physical image undistorted, reserve separate narrow colourbar.
    right_cbar=panel.get('colorbar','Bottom')=='Right'
    ax = fig.add_axes([left, bottom+(.02 if right_cbar else .095)*height,
                       width*(.84 if right_cbar else 1.),
                       (.96 if right_cbar else .875)*height])
    if right_cbar:
        cax = fig.add_axes([left+.87*width,bottom+.17*height,.028*width,.68*height])
    else:
        cax = fig.add_axes([left+.04*width, bottom+.025*height, .92*width, .033*height])
    source_name = panel.get('channel','')
    if source_name not in scan.channels:
        warnings.append(f"{Path(scan.path).name}: channel {source_name!r} is missing")
        ax.text(.5,.5,'Channel unavailable',ha='center',va='center',transform=ax.transAxes, fontsize=font)
        ax.set_axis_off();cax.set_axis_off();return
    cd = scan.channels[source_name]
    direction = panel.get('direction','forward')
    if direction not in cd.traces:
        warnings.append(f"{Path(scan.path).name}: {source_name} {direction} unavailable")
        direction=next(iter(cd.traces))
    data = cd.get(direction)
    style = None
    if panel.get('processed',True) and isinstance(panel.get('style'),dict):
        try:
            snapshot=panel['style']
            style=ImageStyle(**{k:v for k,v in snapshot.items() if k in ImageStyle.__dataclass_fields__})
            steps=[ProcessingStep(**v) for v in snapshot.get('processing_steps',[])]
            data=apply_processing(data,steps) if steps else np.asarray(data,dtype=float).copy()
        except Exception as exc:
            warnings.append(f"Image processing unavailable for {source_name}: {exc}")
    # Native SPM raster row 0 is the TOP, unlike the old image-selection GUI.
    # Keep all pixels intact; plotting with origin='upper' aligns scan/sample axes.
    data = np.array(data, dtype=float, copy=True)
    finite=data[np.isfinite(data)]
    if not finite.size:
        ax.text(.5,.5,'No finite image pixels',ha='center',va='center',transform=ax.transAxes)
        ax.set_axis_off();cax.set_axis_off();return
    low, high=np.percentile(finite,[2,98])
    if style is not None:
        try:low,high=display_bounds(data,style)
        except Exception as exc:warnings.append(f'Could not apply SPM Studio range: {exc}')
    if low==high: low-=.5;high+=.5
    for field, default in (('vmin',low),('vmax',high)):
        try:
            value = float(panel.get(field, ''))
            if field=='vmin':low=value
            else: high=value
        except (TypeError,ValueError): pass
    if low>=high:
        warnings.append(f'Invalid color limits for {source_name}; using 2–98%')
        low,high=np.percentile(finite,[2,98]); high=max(high,low+1e-12)
    unit = cd.unit or ''
    multiplier = 1.
    selected_unit=panel.get('unit','Auto')
    if selected_unit=='Auto':
        if unit=='m': selected_unit='pm' if np.nanpercentile(np.abs(finite),90)<.5e-9 else 'nm'
        elif unit=='V':selected_unit='mV' if np.nanpercentile(np.abs(finite),90)<.2 else 'V'
        else:selected_unit=unit
    scale = {('m','pm'):1e12,('m','nm'):1e9,('V','mV'):1e3,('A','pA'):1e12}
    multiplier = scale.get((unit,selected_unit),1.)
    shown_unit=selected_unit if multiplier!=1. else unit
    data*=multiplier;low*=multiplier;high*=multiplier
    dims=scan_size_nm(scan)
    if dims:
        w,h = dims
    else:
        h,w=data.shape
        warnings.append(f'{Path(scan.path).name}: physical scan size missing; markers suppressed')
    extent=[0,w,0,h]
    im=ax.imshow(data,origin='upper',extent=extent,cmap=ListedColormap(studio_lut(panel.get('cmap','gray'))/255.),
                 vmin=low,vmax=high,interpolation='nearest',aspect='equal',rasterized=True)
    title=panel.get('title','') or source_name
    ax.set_title(title,fontsize=font+0.5,loc='left',pad=4,fontweight='medium')
    ax.set_xticks([]);ax.set_yticks([])
    for spine in ax.spines.values():spine.set_visible(False)
    if panel.get('scalebar',True) and dims:
        dist=_round_scale(w*.24)
        if dist>0:
            x0=w*.70;y0=h*.075
            # contrasting stroke for light and dark microscopy palettes.
            from matplotlib import patheffects
            line=ax.plot([x0,x0+dist],[y0,y0],color='white',lw=2.1,solid_capstyle='butt',zorder=12)[0]
            line.set_path_effects([patheffects.Stroke(linewidth=3.3,foreground='black'),patheffects.Normal()])
            label=ax.text(x0+dist/2,y0+h*.055,f'{dist:g} nm',ha='center',va='bottom',
                          color='white',fontsize=font-1.3,weight='medium',zorder=12)
            label.set_path_effects([patheffects.withStroke(linewidth=2,foreground='black')])
    if panel.get('markers', True) and dims:
        by_xy=defaultdict(list)
        for t,spec in marker_specs:
            point=map_to_scan_nm(scan,spec.x_m,spec.y_m,
                                 bool(panel.get('flip_x',False)),bool(panel.get('flip_y',False)),
                                 float(panel.get('drift_x',0)),float(panel.get('drift_y',0)))
            # User-approved manual position is already expressed in local nm.
            if isinstance(t.get('manual_nm'),(list,tuple)) and len(t['manual_nm'])==2:
                point=tuple(map(float,t['manual_nm']))
            if point is None:
                warnings.append(f"No trustworthy XY conversion: {Path(scan.path).name} / {Path(spec.path).name}")
                continue
            if not in_scan(scan,point):
                warnings.append(f"Out of scan: {Path(spec.path).name} ({point[0]:.2f}, {point[1]:.2f} nm)")
                continue
            key=(round(point[0],3),round(point[1],3))
            by_xy[key].append(t)
        for (x,y), traces in by_xy.items():
            # Same XY, different Z offsets: concentric outlines retain all colours.
            for j,tr in enumerate(traces):
                ax.plot([x],[y],marker='o',markersize=6.2+j*2.8,markerfacecolor='none',
                        markeredgecolor=tr.get('color','#C8102E'),markeredgewidth=1.35,
                        linestyle='None',zorder=20+j)
            ax.plot([x],[y],marker='+',color='white',markersize=3.,markeredgewidth=1.,zorder=31)
    # Studio convention: physical scan footprint, close colorbar with title
    # inside its gradient and the two extrema just outside the gradient.
    ax.apply_aspect()
    actual=ax.get_position()
    label=f'{source_name} [{shown_unit}]' if shown_unit else source_name
    middle=np.asarray(studio_lut(panel.get('cmap','gray'))[128],dtype=float)/255.
    fg='black' if (.2126*middle[0]+.7152*middle[1]+.0722*middle[2])>.58 else 'white'
    if right_cbar:
        bar_width=min(.023, actual.width*.065)
        bar_gap=min(.012,actual.width*.035)
        cax.set_position([actual.x1+bar_gap,actual.y0+.052*actual.height,
                          bar_width,.896*actual.height])
    else:
        bar_gap=min(.014,actual.height*.055)
        bar_height=min(.027,actual.height*.065)
        cax.set_position([actual.x0,actual.y0-bar_gap-bar_height,actual.width,bar_height])
    cb=fig.colorbar(im,cax=cax,orientation='vertical' if right_cbar else 'horizontal')
    cb.set_ticks([])
    cb.outline.set_visible(False)
    cb.ax.text(.5,.5,label,ha='center',va='center',color=fg,
               fontsize=max(5,font-1.3),rotation=-90 if right_cbar else 0,
               transform=cb.ax.transAxes)
    if right_cbar:
        cax.text(.5,1.005,f'{high:.3g}',ha='center',va='bottom',fontsize=max(5,font-2),transform=cax.transAxes)
        cax.text(.5,-.005,f'{low:.3g}',ha='center',va='top',fontsize=max(5,font-2),transform=cax.transAxes)
    else:
        cax.text(-.008,.5,f'{low:.3g}',ha='right',va='center',fontsize=max(5,font-2),transform=cax.transAxes)
        cax.text(1.008,.5,f'{high:.3g}',ha='left',va='center',fontsize=max(5,font-2),transform=cax.transAxes)



def _group_unit(graph, trace_data):
    name=graph.get('channel','')
    mode=graph.get('unit','Auto')
    if mode!='Auto':return mode
    try:
        vals=np.concatenate([np.asarray(v,float) for v in trace_data if len(v)])
        _, unit=convert_signal(vals,name,'Auto')
        return unit or 'Raw'
    except ValueError:return 'Raw'


def _plot_graph(fig, rectangle, graph, trace_specs, prepared, comparison, font, diagnostics, warnings, graph_index):
    left,bottom,width,height=rectangle
    trend_mode=graph.get('trend','None')
    trend_on=trend_mode!='None'
    ax=fig.add_axes([left,bottom+(0.36 if trend_on else 0.17)*height,width,(.58 if trend_on else .75)*height])
    ax.set_title(graph.get('title','Bias spectroscopy'),loc='left',pad=5,fontsize=font+0.7,fontweight='medium')
    _style(ax,font)
    ax._spm_graph_index=graph_index
    ax._spm_plot_main=True
    desired_unit=prepared[0][6] if prepared else graph.get('unit','Auto')
    all_y=[entry[4] for entry in prepared]
    lines=0
    trend_points=[]
    for trace,spec,direction,x,yy,channel,unit in prepared:
        color=trace.get('color','#C8102E')
        c=color if direction=='Forward' else backward_color(color)
        ax.plot(x,yy,color=c,ls='-' if direction=='Forward' else '--',lw=1.25,
                solid_capstyle='round',alpha=.96,zorder=3 if direction=='Forward' else 2)
        lines+=1
        key=trace.get('path','')
        kind='kink' if trend_mode=='Kink vs height' else 'cpd'
        if not (trend_on or graph.get('annotate',False)) or not trace.get('fit_enabled',True):
            continue
        fit = find_kink(x,yy,
                        min_bic=float(graph.get('min_bic',14.0)),
                        min_sigma=float(graph.get('min_sigma',4.0))) if kind=='kink' else fit_cpd(x,yy)
        diagnostics.append({'graph':graph.get('title',''), 'source':str(spec.path),
             'trace':trace.get('label',spec.path.stem), 'channel':channel,
             'direction':direction,'z_offset_nm':spec.z_nm,
             'kind':kind,'accepted':fit.success,'voltage_V':fit.voltage,
             'voltage_uncertainty_V':fit.uncertainty,'BIC_gain':fit.bic_gain,
             'reason':fit.evidence})
        if fit.success and (graph.get('annotate',False) or trend_on):
            yi=float(np.interp(fit.voltage,np.sort(x),yy[np.argsort(x)]))
            ax.scatter([fit.voltage],[yi],color=c,s=20,marker='|',zorder=6)
            if kind=='cpd' and graph.get('annotate',False):
                ax.axvline(fit.voltage,color=c,ls=(0,(2,2)),lw=.72,alpha=.65,zorder=1)
            if trend_on:
                trend_points.append((spec.z_nm,fit.voltage,fit.uncertainty,direction,c))
    # Shared absolute bias scale avoids individually centering every curve at its CPD.
    # The shared signal scale is only applied to graphs with the same observable/unit.
    limits=comparison['overrides']
    if comparison['share_x']:
        chosen=_bounds_with_manual(comparison['x'],limits['bias'])
    else:
        local=_finite_limits([entry[3] for entry in prepared])
        chosen=_bounds_with_manual(local,limits['bias'])
    if chosen is not None:ax.set_xlim(*chosen)
    if comparison['share_y']:
        y_auto=comparison['y'].get(_comparison_key(graph,desired_unit))
    else:
        y_auto=_finite_limits([entry[4] for entry in prepared])
    y_limits=_bounds_with_manual(y_auto,limits['signal'])
    if y_limits is not None:ax.set_ylim(*y_limits)
    ax.set_xlabel('Sample bias (V)',fontsize=font,labelpad=3)
    clean=re.sub(r'\s*\([^)]*\)\s*$','',graph.get('channel','Signal'))
    ax.set_ylabel(f'{clean} ({unit})' if all_y and unit else clean, fontsize=font,labelpad=3)
    if not lines:
        ax.text(.5,.5,'No matching spectroscopy data',transform=ax.transAxes,ha='center',va='center',fontsize=font)
    _draw_inset(ax,graph,prepared,font,warnings)
    if trend_on:
        trend_ax=fig.add_axes([left,bottom+.045*height,width,.22*height])
        _style(trend_ax,font)
        branch=graph.get('trend_direction','Forward')
        chosen=[p for p in trend_points if p[3]==branch and np.isfinite(p[0])]
        # Never combine a molecular site and a metal reference into one
        # height-dependent fit merely because their curves share a graph.
        sites=[(s.x_m*1e9,s.y_m*1e9) for tr,s in trace_specs
               if np.isfinite(s.x_m) and np.isfinite(s.y_m) and tr.get('fit_enabled',True)]
        if len(sites)>1 and (np.ptp([p[0] for p in sites])>.75 or
                             np.ptp([p[1] for p in sites])>.75):
            warnings.append(f"{graph.get('title','Graph')}: mixed measurement sites; height trend disabled")
            chosen=[]
        for z,v,e,direc,c in chosen:
            trend_ax.errorbar(z,v,yerr=e if np.isfinite(e) and e>0 else None,
                              fmt='o',markersize=3,capsize=1,color=c,lw=.7)
        regression=linear_trend([(p[0],p[1],p[2]) for p in chosen])
        if regression:
            zvals=[p[0] for p in chosen]
            xx=np.linspace(min(zvals),max(zvals),100)
            trend_ax.plot(xx,regression['intercept']+regression['slope']*xx,color='#202A33',lw=1.15)
            trend_ax.text(.02,.96,f"dV/dz = {regression['slope']:+.3g} ± {regression['slope_err']:.2g} V/nm",
                ha='left',va='top',transform=trend_ax.transAxes,fontsize=font-1.4)
        else:
            trend_ax.text(.99,.95,'≥3 accepted heights needed for linear fit',ha='right',va='top',
                          transform=trend_ax.transAxes,fontsize=font-1.6,color='#8A4030')
        trend_ax.set_xlabel('Z offset (nm)',fontsize=font-1.3,labelpad=1)
        trend_ax.set_ylabel('Kink bias (V)' if kind=='kink' else 'CPD vertex (V)',fontsize=font-1.3,labelpad=1)
        diagnostics.append({'graph':graph.get('title',''), 'kind':f'{kind} trend',
                            'direction':branch,'regression':regression or {}})


def create_figure(project: dict, scan_files: dict, spectra: dict) -> tuple[Figure, list[dict], list[str]]:
    """No GUI dependencies: generate a reproducible figure using configured scans."""
    images=project.get('images',[])
    graphs=project.get('graphs',[])
    if not images and not graphs:
        raise ValueError('Add at least one image or spectroscopy graph')
    options=project.get('options',{})
    font=float(options.get('font',8.0))
    width=float(options.get('width',11.0))
    unique_labels=[]
    marker_specs=defaultdict(list)
    for g in graphs:
        for t in g.get('traces',[]):
            spec=spectra.get(t.get('path'))
            if not spec or not t.get('enabled',True):continue
            scan_path=t.get('scan','')
            if scan_path:
                marker_specs[scan_path].append((t,spec))
            label=t.get('label',spec.path.stem)
            if not any(l==label and c==t.get('color') for l,c in unique_labels):
                unique_labels.append((label,t.get('color','#C8102E')))
    # A single figure-wide legend, including sweep line convention.
    legend_entries=min(len(unique_labels),50)+2 if graphs else 0
    legend_rows=max(1,math.ceil(legend_entries/4)) if graphs else 0
    legend_inches=.22*legend_rows+.18 if graphs else 0.
    content_height=max(2.45*max(1,len(images)),2.15*max(1,len(graphs)))
    height=.65+content_height+legend_inches
    fig=Figure(figsize=(width,height),dpi=110,facecolor='white')
    diagnostics=[];warnings=[]
    legend_frac=legend_inches/height
    content_bottom=(legend_inches+.32)/height
    content_top=1-.40/height
    content_size=content_top-content_bottom
    def panel_rect(i,n,left,w):
        item_h=content_size/max(1,n)
        return (left,content_bottom+(n-i-1)*item_h+.025*item_h,w,item_h*.92)
    # No empty half-page when composing graphs-only or images-only papers.
    if images and graphs:
        image_left,image_width=.055,.37
        graph_left,graph_width=.56,.395
    elif graphs:
        image_left,image_width=.055,.90
        graph_left,graph_width=.105,.80
    else:
        image_left,image_width=.17,.65
        graph_left,graph_width=.105,.80
    for i,panel in enumerate(images):
        path=panel.get('scan','')
        scan=scan_files.get(path)
        if scan is None:
            warnings.append(f'Image {i+1}: scan not loaded: {path}');continue
        _plot_image(fig,panel_rect(i,len(images),image_left,image_width),panel,scan,
                    marker_specs.get(path,[]),font,warnings)
    plot_specs=[]
    for i,graph in enumerate(graphs):
        pairs=[]
        for trace in graph.get('traces',[]):
            if trace.get('enabled',True):
                spec=spectra.get(trace.get('path'))
                if spec: pairs.append((trace,spec))
                else: warnings.append(f"Missing spectrum: {trace.get('path')}")
        plot_specs.append(pairs)
    prepared,comparison=_prepare_comparison(graphs,plot_specs,options,warnings)
    for i,graph in enumerate(graphs):
        _plot_graph(fig,panel_rect(i,len(graphs),graph_left,graph_width),graph,plot_specs[i],
                    prepared[i],comparison,font,diagnostics,warnings,i)
    title=options.get('title','')
    if title:
        fig.suptitle(title,x=.055,y=1-.09/height,ha='left',fontsize=font+3,weight='medium')
    if graphs:
        handles=[]
        for lab,col in unique_labels[:50]:
            handles.append(Line2D([0],[0],color=col,linewidth=1.8,label=lab))
        handles.extend([Line2D([0],[0],color='#333333',ls='-',lw=1.5,label='Forward — solid'),
                        Line2D([0],[0],color='#777777',ls='--',lw=1.5,label='Backward — dashed')])
        fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.525,0.01),
                   frameon=False,ncol=4,fontsize=max(5.2,font-1.5),
                   columnspacing=1.4,handlelength=2.5,borderaxespad=0.)
        if len(unique_labels)>50:warnings.append('Legend displays the first 50 traces; all data still plotted')
    # v29: bold a, b, c … letters (images column first, then the graph column).
    if options.get('panel_labels',True):
        try:
            from .plots import add_panel_labels
            add_panel_labels(fig,order='columns',fontsize=font+3.5)
        except Exception as exc:  # labels are cosmetic; never block a figure
            warnings.append(f'Panel letters skipped: {exc}')
    return fig, diagnostics, sorted(set(warnings))
