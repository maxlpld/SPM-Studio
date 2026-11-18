"""Interactive multi-line island height analysis inside the Studio viewer.

Reference: legacy_reference/spm_image_selection_gui_v054*/.../flake_analysis.py.
The two endpoint-to-edge heights are reported individually; neither is
silently replaced by a difference between means of profile endpoints.
"""
from __future__ import annotations
import csv
import numpy as np
from spm_studio.core.analysis_utils import profile_between,save_plot
from spm_studio.core.plots import plot_style


def _edge_peak(y,run=3):
    """Walk from endpoint until `run` consecutive decreasing finite samples."""
    last_rise=0
    decreasing=0
    for i in range(1,len(y)):
        if not np.isfinite(y[i-1]) or not np.isfinite(y[i]):continue
        if y[i]>y[i-1]:
            last_rise=i
            decreasing=0
        elif y[i]<y[i-1]:
            decreasing+=1
            if decreasing>=run and last_rise>0:
                return last_rise
        else:
            decreasing=0
    return int(np.nanargmax(y))


def measure_profile(y,run=3):
    """Return left/right peak indices and signed and absolute apparent heights."""
    y=np.asarray(y,float)
    if y.ndim!=1 or len(y)<2*run+3 or not np.isfinite(y).all():
        raise ValueError('Line too short or contains invalid samples; draw within valid image')
    left=_edge_peak(y,run)
    right=len(y)-1-_edge_peak(y[::-1],run)
    return {'left_index':left, 'right_index':right,
            'left_signed':float(y[left]-y[0]),
            'right_signed':float(y[right]-y[-1]),
            'left_height':float(abs(y[left]-y[0])),
            'right_height':float(abs(y[right]-y[-1]))}


def _distance(ctx,*points_and_n):
    """Distances along a line or polyline: ``_distance(ctx, p0, p1[, p2 …], n)``."""
    from spm_studio.core.analysis_utils import polyline_length,geometry_spacing
    *points,n=points_and_n
    return np.linspace(0,polyline_length(points,geometry_spacing(ctx.geometry)),n)


def run(ctx):
    rois=[r for r in (ctx.rois or []) if r.kind=='line']
    if not rois and ctx.roi and ctx.roi.kind=='line':rois=[ctx.roi]
    if not rois:
        raise ValueError('Draw one or more Line ROIs across the island before running the flake module')
    directions=['forward','backward'] if ctx.parameters.get('trace_mode')=='both' else [
        ctx.direction if ctx.parameters.get('trace_mode')=='selected' else ctx.parameters['trace_mode']]
    traces=[]
    for k,roi in enumerate(rois,1):
        for direction in directions:
            if f'{ctx.channel}|{direction}' not in ctx.arrays:
                ctx.log(f'Skipping unavailable trace {direction} for line {k}')
                continue
            arr=ctx.image(ctx.channel,direction)
            xpix,z=profile_between(arr,*roi.points_px)
            x=_distance(ctx,*roi.points_px,len(z))
            try:m=measure_profile(z,int(ctx.parameters.get('edge_decrease_run',3)))
            except ValueError as e:
                ctx.log(f'Line {k}, {direction}: {e}',level='warning')
                continue
            traces.append((k,direction,x,z,m))
    if not traces:raise ValueError('No valid selected line profiles')
    rows=[]; stripe_rows=[]
    ctx.progress(30,'Measuring left and right island edges')
    for i,(number,direction,x,y,m) in enumerate(traces):
        rows.append([number,direction,m['left_height'],m['right_height'],
                     m['left_signed'],m['right_signed'],m['left_index'],m['right_index']])
        if ctx.parameters.get('find_stripes',True):
            from scipy.signal import find_peaks
            lo,hi=sorted((m['left_index'],m['right_index']))
            if hi-lo>=8:
                yy=y[lo:hi+1]
                xx=x[lo:hi+1]
                baseline=np.polyval(np.polyfit(xx,yy,1),xx)
                d=yy-baseline
                peak_idx,_=find_peaks(d,prominence=max(float(ctx.parameters.get('prominence_si',0)),0))
                if len(peak_idx)>1:
                    for a,b in zip(peak_idx[:-1],peak_idx[1:]):
                        stripe_rows.append([number,direction,float(xx[b]-xx[a])])
        ctx.progress(30+40*(i+1)/len(traces),f'Profile {i+1} / {len(traces)}')
    with (ctx.output_dir/'heights.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.writer(f)
        w.writerow(['line','trace','left_height_SI','right_height_SI',
                    'left_signed_SI','right_signed_SI','left_peak_index','right_peak_index'])
        w.writerows(rows)
    ctx.result_file(ctx.output_dir/'heights.csv','Individual edge heights')
    ctx.result_table(['Line','Trace','Left height ('+ctx.unit+')','Right height ('+ctx.unit+')'],
                     [r[:4] for r in rows],'Edge heights')
    # Original workflow combines repeated forward/backward profiles by index.
    grouped={}
    for r in rows:grouped.setdefault(int(r[0]),[]).append(r)
    summaries=[]
    for number,group in sorted(grouped.items()):
        left=np.array([r[2] for r in group],dtype=float)
        right=np.array([r[3] for r in group],dtype=float)
        summaries.append([number,len(group),float(np.mean(left)),float(np.mean(right)),
                          float(np.std(left,ddof=1)) if len(left)>1 else float('nan'),
                          float(np.std(right,ddof=1)) if len(right)>1 else float('nan')])
    with (ctx.output_dir/'flake_height_summary.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.writer(f)
        w.writerow(['line','n_traces','left_mean_SI','right_mean_SI',
                    'left_sd_between_traces_SI','right_sd_between_traces_SI'])
        w.writerows(summaries)
    ctx.result_file(ctx.output_dir/'flake_height_summary.csv','Mean edge heights by drawn line')
    ctx.result_table(['Line','N traces','Left mean','Right mean','Left SD','Right SD'],
                     summaries,'Combined apparent heights')
    xscale=1e9 if ctx.geometry.calibrated else 1
    zscale=1e9 if ctx.unit=='m' else 1
    xunit='nm' if ctx.geometry.calibrated else 'px'
    with plot_style(ctx.plot_config) as plt:
        fig,axes=plt.subplots(2,1,figsize=((ctx.plot_config or {}).get('figure_width_in',7),
                                                  (ctx.plot_config or {}).get('figure_height_in',4.4)*1.55),
                                  constrained_layout=False)
        for number,direction,x,y,m in traces:
            label=f'Line {number} {direction}'
            axes[0].plot(x*xscale,y,label=label,lw=1)
            for idx,marker in ((m['left_index'],'o'),(m['right_index'],'^')):
                axes[0].scatter([x[idx]*xscale],[y[idx]],s=22,marker=marker)
        axes[0].set(xlabel=f'Distance ({xunit})',ylabel=f'{ctx.channel} ({ctx.unit})',
                    title='Profiles and detected edge maxima')
        axes[0].legend()
        xlabels=[f'{n} {d[0].upper()}' for n,d,*_ in rows]
        ix=np.arange(len(rows))
        axes[1].plot(ix,[r[2]*zscale for r in rows],'o-',label='Left edge')
        axes[1].plot(ix,[r[3]*zscale for r in rows],'s-',label='Right edge')
        axes[1].set_xticks(ix,xlabels)
        axes[1].set(xlabel='Profile / trace',ylabel=f'Apparent height ({"nm" if ctx.unit=="m" else ctx.unit})',
                    title='Independent left and right apparent heights')
        axes[1].legend()
        save_plot(ctx,fig,'flake_height')
        if summaries:
            fig,ax=plt.subplots(figsize=((ctx.plot_config or {}).get('figure_width_in',7),
                                         (ctx.plot_config or {}).get('figure_height_in',4.4)))
            ii=np.arange(len(summaries))
            yl=np.array([row[2]*zscale for row in summaries])
            yr=np.array([row[3]*zscale for row in summaries])
            el=np.nan_to_num(np.array([row[4]*zscale for row in summaries]),nan=0.)
            er=np.nan_to_num(np.array([row[5]*zscale for row in summaries]),nan=0.)
            ax.errorbar(ii-.07,yl,yerr=el,fmt='o',capsize=4,label='Left')
            ax.errorbar(ii+.07,yr,yerr=er,fmt='^',capsize=4,label='Right')
            ax.set_xticks(ii,[str(row[0]) for row in summaries])
            ax.set(xlabel='Drawn profile',
                   ylabel='Apparent height ('+('nm' if ctx.unit=='m' else ctx.unit)+')',
                   title='Forward/backward mean height and SD')
            ax.legend()
            save_plot(ctx,fig,'flake_mean_heights')
        if stripe_rows:
            fig,ax=plt.subplots(figsize=((ctx.plot_config or {}).get('figure_width_in',7),
                                            (ctx.plot_config or {}).get('figure_height_in',4.4)))
            for number,direction,spacing in stripe_rows:
                ax.scatter(number,spacing*xscale,label=f'Line {number} {direction}',s=25)
            ax.set(xlabel='Line number',ylabel=f'Stripe spacing ({xunit})',title='Adjacent top maxima spacings')
            save_plot(ctx,fig,'flake_stripes')
    if stripe_rows:
        with (ctx.output_dir/'stripes.csv').open('w',newline='',encoding='utf8') as f:
            w=csv.writer(f);w.writerow(['line','trace','spacing_m_or_px']);w.writerows(stripe_rows)
        ctx.result_file(ctx.output_dir/'stripes.csv','Stripe spacings')
    ctx.progress(100,'Finished')
