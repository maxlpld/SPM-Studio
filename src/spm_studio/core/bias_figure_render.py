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
from . import spectroscopy_methods as sm

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


def _gather_views(graph, trace_specs, warnings, options=None):
    """Plot-ready views of every sweep of a graph, for the figure's measurement type."""
    options=options or {}
    m=sm.method(options.get('method'))
    raw=[]
    for trace,spec in trace_specs:
        channel=matching_channel(spec,graph.get('channel',''))
        if channel is None and m.sweep!='bias':
            channel=next((c for c in sm.y_channels(spec,m)
                          if sm._key(c)==sm._key(graph.get('channel',''))),None)
        if channel is None:
            warnings.append(f"{Path(spec.path).name}: does not record {graph.get('channel')}")
            continue
        if m.key=='bias_kpfm':
            views=get_views(spec,channel)
            found=re.findall(r'\(([^()]*)\)',channel)
            label,native,extra=re.sub(r'\s*\([^)]*\)\s*$','',channel).strip(),(found[-1] if found else ''),[]
            if options.get('average') and 'Forward' in views and 'Backward' in views:
                views=sm.process_views(spec,channel,{**options,'smooth':0})[0]
        else:
            views,label,native,extra=sm.process_views(spec,channel,options)
        warnings.extend(extra)
        if not views:
            warnings.append(f"{Path(spec.path).name}: no {sm.x_label(m,options.get('x_channel','')) or 'X'} axis "
                            f"for {channel}")
        for direction,(x,y) in views.items():
            if trace.get('direction','Both') not in ('Both',direction):
                continue
            x=np.asarray(x,float);y=np.asarray(y,float)
            if x.shape!=y.shape or x.ndim!=1:
                warnings.append(f'{Path(spec.path).name}: x/y shape mismatch')
                continue
            raw.append((trace,spec,direction,x,y,channel,label,native))
    return raw


def _prepare_comparison(graphs, specs, options, warnings):
    """Precompute one X range and per-physical-channel Y ranges for all graphs."""
    raw_groups=[_gather_views(g,pairs,warnings,options) for g,pairs in zip(graphs,specs)]
    # All Auto units for the same native observable use a single pooled unit.
    pools=defaultdict(list)
    natives={}
    for graph,raw in zip(graphs,raw_groups):
        base=re.sub(r'\s*\([^)]*\)\s*$', '',graph.get('channel','')).strip().casefold()
        pools[base].extend([entry[4] for entry in raw])
        natives[base]=next((entry[7] for entry in raw),'')
    auto_units={}
    for base,ys in pools.items():
        try:
            values=np.concatenate([np.asarray(v,float) for v in ys if len(v)]) if ys else np.array([])
            auto_units[base]=sm.convert_y(values,natives.get(base,''),'Auto')[1] if values.size else 'Raw'
        except ValueError:
            auto_units[base]='Raw'
    prepared=[];labels=[];xvalues=[];ypools=defaultdict(list)
    offset=0.
    try:offset=float(options.get('offset',0) or 0)
    except (TypeError,ValueError):warnings.append('Invalid waterfall offset; using 0')
    for graph,raw in zip(graphs,raw_groups):
        base=re.sub(r'\s*\([^)]*\)\s*$', '',graph.get('channel','')).strip().casefold()
        requested=graph.get('unit','Auto')
        desired=auto_units.get(base,'Raw') if requested=='Auto' else requested
        converted=[];effective_units=set()
        order={}
        for trace,spec,direction,x,y,channel,label,native in raw:
            yy,unit=sm.convert_y(y,native,desired)
            k=order.setdefault(id(trace),len(order))
            if offset:yy=yy+k*offset
            converted.append((trace,spec,direction,x,yy,channel,unit))
            effective_units.add(unit)
            xvalues.append(x)
            ypools[_comparison_key(graph,unit)].append(yy)
        if len(effective_units)>1:
            warnings.append(f"{graph.get('title','Graph')}: mixed Y units; only like-unit graphs share a Y scale")
        prepared.append(converted)
        labels.append(next((entry[6] for entry in raw),None))
    overrides=_manual_bounds(options,warnings)
    shared_x=_finite_limits(xvalues)
    shared_y={k:_finite_limits(values) for k,values in ypools.items()}
    return prepared,{'x':shared_x,'y':shared_y,'overrides':overrides,'labels':labels,
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
    for _trace,_spec,_direction,x,y,_ch,_unit in (prepared if graph.get('_method','bias_kpfm')=='bias_kpfm' else []):
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




# ---------------------------------------------------------------------------- v0.0.10 layout
# Every panel is placed by Matplotlib's constrained layout: titles, axis labels, tick labels,
# colourbars, the figure title and the legend reserve their own space and can never overlap.

def _letter(index):
    return chr(ord('a')+index) if index<26 else f'a{index-25}'


def _panel_title(ax, title, letter, font, *, image=False):
    text=str(title or '').strip()
    if letter:
        text=(f'$\\mathbf{{{letter}}}$' + ('   '+text if text else ''))
    if text:
        ax.set_title(text,loc='left',pad=4 if image else 5,fontsize=font+(0.5 if image else 0.7),
                     fontweight='medium')


def _parameter_box(ax, scan, channel, corner, font, warnings):
    if corner in (None,'','None'):return
    try:
        from . import scan_parameters as sp
        lines=sp.lines_for(scan,sp.default_selection(scan,channel),channel)
    except Exception as exc:
        warnings.append(f'Measurement parameters unavailable: {exc}')
        return
    if not lines:
        warnings.append(f'{Path(scan.path).name}: no bias / setpoint in the header')
        return
    corner=str(corner).lower().replace(' ','_')
    x=.03 if corner.endswith('left') else .97
    y=.97 if corner.startswith('top') else .03
    if corner=='bottom_right':y=.20   # above the scale bar
    ax.text(x,y,'\n'.join(lines),transform=ax.transAxes,ha='left' if corner.endswith('left') else 'right',
            va='top' if corner.startswith('top') else 'bottom',fontsize=max(5.,font-1.6),color='white',
            linespacing=1.15,zorder=40,
            bbox=dict(boxstyle='round,pad=0.25',facecolor='black',alpha=.55,edgecolor='none'))


def _image_data(panel, scan, warnings):
    source_name=panel.get('channel','')
    cd=scan.channels[source_name]
    direction=panel.get('direction','forward')
    if direction not in cd.traces:
        warnings.append(f"{Path(scan.path).name}: {source_name} {direction} unavailable")
        direction=next(iter(cd.traces))
    data=cd.get(direction)
    style=None
    if panel.get('processed',True) and isinstance(panel.get('style'),dict):
        try:
            snapshot=panel['style']
            style=ImageStyle(**{k:v for k,v in snapshot.items() if k in ImageStyle.__dataclass_fields__})
            steps=[ProcessingStep(**v) for v in snapshot.get('processing_steps',[])]
            data=apply_processing(data,steps) if steps else np.asarray(data,dtype=float).copy()
        except Exception as exc:
            warnings.append(f"Image processing unavailable for {source_name}: {exc}")
    return np.array(data,dtype=float,copy=True),style,cd


def image_aspect(panel, scan):
    """Height / width of an image panel (physical when calibrated)."""
    try:
        dims=scan_size_nm(scan)
        if dims and dims[0]>0:return float(dims[1])/float(dims[0])
        shape=scan.channels[panel.get('channel','')].geometry.shape
        return float(shape[0])/float(shape[1])
    except Exception:
        return 1.0


def _plot_image(fig, ax, panel, scan, marker_specs, font, warnings, letter=''):
    source_name=panel.get('channel','')
    if source_name not in scan.channels:
        warnings.append(f"{Path(scan.path).name}: channel {source_name!r} is missing")
        ax.text(.5,.5,'Channel unavailable',ha='center',va='center',transform=ax.transAxes,fontsize=font)
        ax.set_axis_off();return
    data,style,cd=_image_data(panel,scan,warnings)
    finite=data[np.isfinite(data)]
    if not finite.size:
        ax.text(.5,.5,'No finite image pixels',ha='center',va='center',transform=ax.transAxes)
        ax.set_axis_off();return
    low,high=np.percentile(finite,[2,98])
    if style is not None:
        try:low,high=display_bounds(data,style)
        except Exception as exc:warnings.append(f'Could not apply SPM Studio range: {exc}')
    if low==high:low-=.5;high+=.5
    for field_name in ('vmin','vmax'):
        try:
            value=float(panel.get(field_name,''))
            if field_name=='vmin':low=value
            else:high=value
        except (TypeError,ValueError):pass
    if low>=high:
        warnings.append(f'Invalid color limits for {source_name}; using 2–98%')
        low,high=np.percentile(finite,[2,98]);high=max(high,low+1e-12)
    unit=cd.unit or ''
    selected_unit=panel.get('unit','Auto')
    if selected_unit=='Auto':
        if unit=='m':selected_unit='pm' if np.nanpercentile(np.abs(finite),90)<.5e-9 else 'nm'
        elif unit=='V':selected_unit='mV' if np.nanpercentile(np.abs(finite),90)<.2 else 'V'
        elif unit=='A':selected_unit='pA' if np.nanpercentile(np.abs(finite),90)<1e-9 else 'nA'
        else:selected_unit=unit
    scale={('m','pm'):1e12,('m','nm'):1e9,('V','mV'):1e3,('A','pA'):1e12,('A','nA'):1e9}
    multiplier=scale.get((unit,selected_unit),1.)
    shown_unit=selected_unit if multiplier!=1. else unit
    data*=multiplier;low*=multiplier;high*=multiplier
    dims=scan_size_nm(scan)
    if dims:
        w,h=dims
    else:
        h,w=data.shape
        warnings.append(f'{Path(scan.path).name}: physical scan size missing; markers suppressed')
    im=ax.imshow(data,origin='upper',extent=[0,w,0,h],
                 cmap=ListedColormap(studio_lut(panel.get('cmap','gray'))/255.),
                 vmin=low,vmax=high,interpolation='nearest',aspect='equal',rasterized=True)
    ax.set_anchor('N')
    _panel_title(ax,panel.get('title','') or source_name,letter,font,image=True)
    ax.set_xticks([]);ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(True);spine.set_linewidth(.6);spine.set_color('#222222')
    if panel.get('scalebar',True) and dims:
        dist=_round_scale(w*.24)
        if dist>0:
            from matplotlib import patheffects
            x0=w*.95-dist;y0=h*.06
            line=ax.plot([x0,x0+dist],[y0,y0],color='white',lw=2.1,solid_capstyle='butt',zorder=12)[0]
            line.set_path_effects([patheffects.Stroke(linewidth=3.3,foreground='black'),patheffects.Normal()])
            label=ax.annotate(f'{dist:g} nm',(x0+dist/2,y0),xytext=(0,3.5),textcoords='offset points',
                              ha='center',va='bottom',color='white',fontsize=max(5.,font-1.3),zorder=12)
            label.set_path_effects([patheffects.withStroke(linewidth=2,foreground='black')])
    if panel.get('markers',True) and dims:
        by_xy=defaultdict(list)
        for t,spec in marker_specs:
            point=map_to_scan_nm(scan,spec.x_m,spec.y_m,
                                 bool(panel.get('flip_x',False)),bool(panel.get('flip_y',False)),
                                 float(panel.get('drift_x',0)),float(panel.get('drift_y',0)))
            if isinstance(t.get('manual_nm'),(list,tuple)) and len(t['manual_nm'])==2:
                point=tuple(map(float,t['manual_nm']))
            if point is None:
                warnings.append(f"No trustworthy XY conversion: {Path(scan.path).name} / {Path(spec.path).name}")
                continue
            if not in_scan(scan,point):
                warnings.append(f"Out of scan: {Path(spec.path).name} ({point[0]:.2f}, {point[1]:.2f} nm)")
                continue
            by_xy[(round(point[0],3),round(point[1],3))].append(t)
        for (x,y),traces in by_xy.items():
            # Same XY, different Z offsets: concentric outlines retain all colours.
            for j,tr in enumerate(traces):
                ax.plot([x],[y],marker='o',markersize=6.2+j*2.8,markerfacecolor='none',
                        markeredgecolor=tr.get('color','#C8102E'),markeredgewidth=1.35,
                        linestyle='None',zorder=20+j)
            ax.plot([x],[y],marker='+',color='white',markersize=3.,markeredgewidth=1.,zorder=31)
        ax.set_xlim(0,w);ax.set_ylim(0,h)
    _parameter_box(ax,scan,source_name,panel.get('parameters','None'),font,warnings)
    right=panel.get('colorbar','Bottom')=='Right'
    cb=fig.colorbar(im,ax=ax,location='right' if right else 'bottom',
                    fraction=.05,pad=.015 if right else .02,aspect=22 if right else 28,shrink=1.)
    cb.outline.set_linewidth(.6)
    cb.ax.tick_params(labelsize=max(5.,font-1.6),direction='in',length=2.5,width=.6)
    cb.locator=MaxNLocator(3);cb.update_ticks()
    clean=re.sub(r'\s*\([^)]*\)\s*$','',source_name).strip() or source_name
    cb.set_label(f'{clean} ({shown_unit})' if shown_unit else clean,fontsize=max(5.,font-1.2),
                 labelpad=2)
    ax.set_anchor('N');cb.ax.set_anchor('N')


def _plot_graph(fig, axes, graph, trace_specs, prepared, comparison, font, diagnostics, warnings,
                graph_index, options, letter=''):
    ax,trend_ax=axes
    m=sm.method(options.get('method'))
    trend_mode=graph.get('trend','None') if graph.get('trend','None') in m.fits else 'None'
    trend_on=trend_mode!='None' and trend_ax is not None
    _panel_title(ax,graph.get('title',m.graph_title),letter,font)
    _style(ax,font)
    ax._spm_graph_index=graph_index
    ax._spm_plot_main=True
    log_y=bool(options.get('log_y')) and 'log_y' in m.options
    unit=prepared[0][6] if prepared else ''
    lines=0
    trend_points=[]
    kind='kink' if trend_mode=='Kink vs height' else 'cpd'
    fits_allowed=m.key=='bias_kpfm'
    for trace,spec,direction,x,yy,channel,unit in prepared:
        color=trace.get('color','#C8102E')
        c=color if direction=='Forward' else backward_color(color)
        ax.plot(x,np.abs(yy) if log_y else yy,color=c,ls='-' if direction=='Forward' else '--',lw=1.25,
                solid_capstyle='round',alpha=.96,zorder=3 if direction=='Forward' else 2)
        lines+=1
        if not fits_allowed or not (trend_on or graph.get('annotate',False)) or not trace.get('fit_enabled',True):
            continue
        fit=find_kink(x,yy,min_bic=float(graph.get('min_bic',14.0)),
                      min_sigma=float(graph.get('min_sigma',4.0))) if kind=='kink' else fit_cpd(x,yy)
        diagnostics.append({'graph':graph.get('title',''),'source':str(spec.path),
             'trace':trace.get('label',spec.path.stem),'channel':channel,
             'direction':direction,'z_offset_nm':spec.z_nm,
             'kind':kind,'accepted':fit.success,'voltage_V':fit.voltage,
             'voltage_uncertainty_V':fit.uncertainty,'BIC_gain':fit.bic_gain,
             'reason':fit.evidence})
        if fit.success:
            yi=float(np.interp(fit.voltage,np.sort(x),yy[np.argsort(x)]))
            ax.scatter([fit.voltage],[yi],color=c,s=20,marker='|',zorder=6)
            if kind=='cpd' and graph.get('annotate',False):
                ax.axvline(fit.voltage,color=c,ls=(0,(2,2)),lw=.72,alpha=.65,zorder=1)
            if trend_on:
                trend_points.append((spec.z_nm,fit.voltage,fit.uncertainty,direction,c))
    limits=comparison['overrides']
    if comparison['share_x']:
        chosen=_bounds_with_manual(comparison['x'],limits['bias'])
    else:
        chosen=_bounds_with_manual(_finite_limits([entry[3] for entry in prepared]),limits['bias'])
    if chosen is not None:ax.set_xlim(*chosen)
    if log_y:
        ax.set_yscale('log')
    else:
        if comparison['share_y']:
            y_auto=comparison['y'].get(_comparison_key(graph,unit))
        else:
            y_auto=_finite_limits([entry[4] for entry in prepared])
        y_limits=_bounds_with_manual(y_auto,limits['signal'])
        if y_limits is not None:ax.set_ylim(*y_limits)
    x_label=sm.x_label(m,options.get('x_channel','')) or 'X'
    ax.set_xlabel(x_label,fontsize=font,labelpad=3)
    labels=comparison.get('labels') or []
    label=(labels[graph_index] if graph_index<len(labels) and labels[graph_index] else
           re.sub(r'\s*\([^)]*\)\s*$','',graph.get('channel','Signal')))
    if log_y:label=f'|{label}|'
    units=[unit if unit else 'a.u.'] if prepared else []
    if options.get('offset') not in (None,'',0,'0') and lines>1:
        units.append('offset')
    ax.set_ylabel(f"{label} ({', '.join(units)})" if units else label,fontsize=font,labelpad=3)
    if not lines:
        ax.text(.5,.5,'No matching spectroscopy data',transform=ax.transAxes,ha='center',va='center',fontsize=font)
    _draw_inset(ax,{**graph,'_method':m.key},prepared,font,warnings)
    if trend_ax is None:
        return
    _style(trend_ax,font)
    if not trend_on:
        trend_ax.set_visible(False);return
    branch=graph.get('trend_direction','Forward')
    chosen=[p for p in trend_points if p[3]==branch and np.isfinite(p[0])]
    # Never combine a molecular site and a metal reference into one height fit.
    sites=[(s.x_m*1e9,s.y_m*1e9) for tr,s in trace_specs
           if np.isfinite(s.x_m) and np.isfinite(s.y_m) and tr.get('fit_enabled',True)]
    if len(sites)>1 and (np.ptp([p[0] for p in sites])>.75 or np.ptp([p[1] for p in sites])>.75):
        warnings.append(f"{graph.get('title','Graph')}: mixed measurement sites; height trend disabled")
        chosen=[]
    for z,v,e,_direc,c in chosen:
        trend_ax.errorbar(z,v,yerr=e if np.isfinite(e) and e>0 else None,
                          fmt='o',markersize=3,capsize=1,color=c,lw=.7)
    regression=linear_trend([(p[0],p[1],p[2]) for p in chosen])
    if regression:
        zvals=[p[0] for p in chosen]
        xx=np.linspace(min(zvals),max(zvals),100)
        trend_ax.plot(xx,regression['intercept']+regression['slope']*xx,color='#202A33',lw=1.15)
        trend_ax.text(.02,.94,f"dV/dz = {regression['slope']:+.3g} ± {regression['slope_err']:.2g} V/nm",
                      ha='left',va='top',transform=trend_ax.transAxes,fontsize=max(5.,font-1.4))
    else:
        trend_ax.text(.98,.92,'≥3 accepted heights needed for a linear fit',ha='right',va='top',
                      transform=trend_ax.transAxes,fontsize=max(5.,font-1.6),color='#8A4030')
    trend_ax.set_xlabel('Z offset (nm)',fontsize=font-.8,labelpad=2)
    trend_ax.set_ylabel('Kink bias (V)' if kind=='kink' else 'CPD (V)',fontsize=font-.8,labelpad=2)
    diagnostics.append({'graph':graph.get('title',''),'kind':f'{kind} trend',
                        'direction':branch,'regression':regression or {}})


def _fit_image_cells(fig, axes, gs, image_heights, graph_heights, rounds=4):
    """Shrink (or grow) each image row to the height its fixed-aspect image really uses.

    The first estimate of an image's height cannot know the exact space taken by titles and
    colourbars; a few layout rounds remove the empty band that would otherwise separate an
    image from its colourbar. The figure height follows when the images set it."""
    ratios=list(image_heights)
    dpi=fig.dpi
    for _ in range(rounds):
        changed=False
        for i,ax in enumerate(axes):
            if not ax.images:continue
            box=ax.get_position(original=True).transformed(ax.figure.transSubfigure)
            active=ax.bbox
            slack=(box.height-active.height)/dpi          # empty vertical space (in)
            deficit=0.
            if active.width<box.width-1.5 and active.width>0:  # width-limited: cell too short
                deficit=(box.width*active.height/active.width-active.height)/dpi
            delta=deficit-slack
            if abs(delta)>.01:
                ratios[i]=max(.3,ratios[i]+delta);changed=True
        if not changed:break
        column=sum(ratios)
        graphs=sum(graph_heights)
        if column>=graphs:
            # Images set the page height: adjust the figure itself.
            fig.set_figheight(max(1.2,fig.get_figheight()+column-max(sum(image_heights),graphs)))
            image_heights=list(ratios)
            spare=1e-3
        else:
            spare=graphs-column
        gs.set_height_ratios(ratios+[spare])
        fig.draw_without_rendering()


def _legend_handles(unique_labels, show_directions):
    handles=[Line2D([0],[0],color=col,linewidth=1.8,label=lab) for lab,col in unique_labels[:50]]
    if show_directions:
        handles.extend([Line2D([0],[0],color='#333333',ls='-',lw=1.5,label='Forward (solid)'),
                        Line2D([0],[0],color='#777777',ls='--',lw=1.5,label='Backward (dashed)')])
    return handles


def create_figure(project: dict, scan_files: dict, spectra: dict) -> tuple[Figure, list[dict], list[str]]:
    """No GUI dependencies: generate a reproducible figure using configured scans."""
    images=project.get('images',[])
    graphs=project.get('graphs',[])
    if not images and not graphs:
        raise ValueError('Add at least one image or spectroscopy graph')
    options=dict(project.get('options',{}))
    m=sm.method(options.get('method'))
    font=float(options.get('font',8.0))
    width=float(options.get('width',11.0))
    letters=bool(options.get('panel_labels',True))
    unique_labels=[];marker_specs=defaultdict(list);directions=set()
    for g in graphs:
        for t in g.get('traces',[]):
            spec=spectra.get(t.get('path'))
            if not spec or not t.get('enabled',True):continue
            if t.get('scan',''):marker_specs[t['scan']].append((t,spec))
            directions.add(t.get('direction','Both'))
            label=t.get('label',spec.path.stem)
            if not any(l==label and c==t.get('color') for l,c in unique_labels):
                unique_labels.append((label,t.get('color','#C8102E')))
    diagnostics=[];warnings=[]
    # --------------------------------------------------------------- page geometry (inches)
    scale=font/8.
    both=bool(images and graphs)
    image_fraction=.40 if both else .62
    image_width=width*image_fraction-.2
    image_heights=[]
    for panel in images:
        scan=scan_files.get(panel.get('scan',''))
        aspect=image_aspect(panel,scan) if scan is not None else 1.
        bar=.55*scale if panel.get('colorbar','Bottom')!='Right' else .1
        image_heights.append(min(image_width*aspect,9.)+ .42*scale+bar)
    graph_heights=[(2.35+(1.0 if g.get('trend','None') in m.fits and g.get('trend','None')!='None' else 0.))*scale
                   for g in graphs]
    show_directions=any(d=='Both' for d in directions) and not options.get('average')
    n_legend=len(unique_labels[:50])+(2 if show_directions else 0)
    legend_cols=max(1,min(6,n_legend))
    legend_h=(math.ceil(n_legend/legend_cols)*.2*scale+.12) if graphs and n_legend else 0.
    title=str(options.get('title','') or '').strip()
    title_h=.34*scale if title else 0.
    height=max(sum(image_heights),sum(graph_heights),1.6)+legend_h+title_h+.15
    fig=Figure(figsize=(width,height),dpi=110,facecolor='white',layout='constrained')
    fig.get_layout_engine().set(w_pad=4/72,h_pad=4/72,hspace=.04,wspace=.04)
    fig._spm_method=m.key
    # --------------------------------------------------------------- panels
    if both:
        img_fig,graph_fig=fig.subfigures(1,2,width_ratios=[image_fraction,1-image_fraction],wspace=.02)
    else:
        img_fig=graph_fig=fig
    image_axes=[]
    if images:
        # One extra (empty) row at the bottom takes the space the images do not need, so every
        # image cell is exactly as tall as its image: the colourbar stays under the image.
        spare=max(0.,sum(graph_heights)-sum(image_heights))+1e-3
        if both:
            image_gs=img_fig.add_gridspec(len(images)+1,1,height_ratios=image_heights+[spare])
            image_axes=[img_fig.add_subplot(image_gs[i,0]) for i in range(len(images))]
        else:
            image_gs=img_fig.add_gridspec(len(images)+1,3,width_ratios=[.19,.62,.19],
                                          height_ratios=image_heights+[spare])
            image_axes=[img_fig.add_subplot(image_gs[i,1]) for i in range(len(images))]
    graph_axes=[]
    if graphs:
        gs=graph_fig.add_gridspec(len(graphs),1,height_ratios=graph_heights)
        for i,g in enumerate(graphs):
            trend=g.get('trend','None') in m.fits and g.get('trend','None')!='None'
            if trend:
                inner=gs[i,0].subgridspec(2,1,height_ratios=[2.35,1.0],hspace=.02)
                main=graph_fig.add_subplot(inner[0,0]);sub=graph_fig.add_subplot(inner[1,0])
                graph_axes.append((main,sub))
            else:
                graph_axes.append((graph_fig.add_subplot(gs[i,0]),None))
    index=0
    for i,panel in enumerate(images):
        path=panel.get('scan','')
        scan=scan_files.get(path)
        letter=_letter(index) if letters and len(images)+len(graphs)>1 else ''
        index+=1
        if scan is None:
            warnings.append(f'Image {i+1}: scan not loaded: {path}')
            image_axes[i].set_axis_off();continue
        _plot_image(fig,image_axes[i],panel,scan,marker_specs.get(path,[]),font,warnings,letter)
    plot_specs=[]
    for graph in graphs:
        pairs=[]
        for trace in graph.get('traces',[]):
            if trace.get('enabled',True):
                spec=spectra.get(trace.get('path'))
                if spec:pairs.append((trace,spec))
                else:warnings.append(f"Missing spectrum: {trace.get('path')}")
        plot_specs.append(pairs)
    prepared,comparison=_prepare_comparison(graphs,plot_specs,options,warnings)
    for i,graph in enumerate(graphs):
        letter=_letter(index) if letters and len(images)+len(graphs)>1 else ''
        index+=1
        _plot_graph(fig,graph_axes[i],graph,plot_specs[i],prepared[i],comparison,font,diagnostics,
                    warnings,i,options,letter)
    if title:
        fig.suptitle(title,x=.01,ha='left',fontsize=font+3,weight='medium')
    if graphs and n_legend:
        fig.legend(handles=_legend_handles(unique_labels,show_directions),loc='outside lower center',
                   frameon=False,ncol=legend_cols,fontsize=max(5.2,font-1.2),
                   columnspacing=1.6,handlelength=2.4,borderaxespad=.2)
        if len(unique_labels)>50:warnings.append('Legend displays the first 50 traces; all data still plotted')
    # Run the layout now so positions are final for tests, previews and exports.
    try:
        fig.draw_without_rendering()
        if image_axes:
            _fit_image_cells(fig,image_axes,image_gs,image_heights,graph_heights)
    except Exception as exc:warnings.append(f'Layout could not be computed: {exc}')
    return fig,diagnostics,sorted(set(warnings))
