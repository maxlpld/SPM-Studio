import numpy as np
from spm_studio.core.plots import plot_style
from spm_studio.core.plot_settings import display_cmap,DEFAULT_PLOT
from spm_studio.core.analysis_utils import save_plot,roi_values

def _fit_populations(values,k,bins,initial_peaks=None, *, with_quality=False):
    """Least-squares Gaussian sum in normalized coordinates for nm/mV-scale stability."""
    from scipy.optimize import least_squares
    reference=float(np.median(values))
    spread=float(np.std(values))
    scale=max(spread,float(np.ptp(values))/10,1e-30)
    standardized=(values-reference)/scale
    hist,edges=np.histogram(standardized,bins=bins,density=True)
    xx=(edges[1:]+edges[:-1])/2
    sigma0=max(float(np.std(standardized))/max(k,1),float(np.ptp(xx))/max(50,k*8),1e-6)
    means=np.quantile(standardized,np.linspace(.1,.9,k))
    if initial_peaks:
        for j,guess in enumerate(initial_peaks[:k]):
            means[j]=(float(guess)-reference)/scale
    def predict(p):
        means=p[:k];sigmas=np.exp(p[k:2*k]); amps=np.exp(p[2*k:])
        return sum(a*np.exp(-.5*((xx-m)/s)**2) for m,s,a in zip(means,sigmas,amps))
    x0=np.r_[means,np.full(k,np.log(sigma0)),np.full(k,np.log(max(hist.max()/k,1e-12)))]
    res=least_squares(lambda p:predict(p)-hist,x0,max_nfev=2500,
                      loss='soft_l1',f_scale=max(float(np.max(hist))/15,1e-12))
    pars=res.x
    components=sorted([(float(m*scale+reference),float(np.exp(s)*scale),float(np.exp(a)/scale))
                       for m,s,a in zip(pars[:k],pars[k:2*k],pars[2*k:])],key=lambda v:v[0])
    # Error bars are local least-squares covariance estimates (not a bootstrap).
    # They are unavailable if the Jacobian is rank deficient or underdetermined.
    predicted=predict(res.x)
    residual=hist-predicted
    ss_total=float(np.sum((hist-np.mean(hist))**2))
    r_squared=1-float(np.sum(residual**2))/ss_total if ss_total>0 else float('nan')
    errors={}
    try:
        jac=np.asarray(res.jac,dtype=float)
        dof=len(hist)-len(res.x)
        if dof>0 and np.linalg.matrix_rank(jac)==len(res.x):
            cov=np.linalg.pinv(jac.T@jac)*(np.sum(residual**2)/dof)
            diag=np.maximum(np.diag(cov),0)
            # Transform dmu/dp, dsigma/dlog(sigma), dA/dlog(A).
            mean_err=np.sqrt(diag[:k])*scale
            sigma_err=np.sqrt(diag[k:2*k])*np.exp(res.x[k:2*k])*scale
            amp_err=np.sqrt(diag[2*k:])*np.exp(res.x[2*k:])/scale
            errors={float(m*scale+reference):(float(ae),float(me),float(se))
                    for m,ae,me,se in zip(res.x[:k],amp_err,mean_err,sigma_err)}
    except (FloatingPointError,ValueError,np.linalg.LinAlgError):
        pass
    quality={'r_squared':r_squared,'error_model':'local Jacobian, bin residuals (approximate)',
             'errors':errors,'success':bool(res.success),'reason':res.message}
    if with_quality:
        return xx*scale+reference,hist/scale,components,quality
    return xx*scale+reference,hist/scale,components

def _masks(parameters):
    import json
    masks = json.loads(parameters.get('masks_json','[]') or '[]')
    if not isinstance(masks,list) or len(masks)>16:
        raise ValueError('Expected a list of at most 16 named masks')
    output=[]
    for n,mask in enumerate(masks):
        if not isinstance(mask,dict):raise ValueError('Invalid mask object')
        name=str(mask.get('name','Mask '+str(n+1)))[:64]
        lo,hi=float(mask['low']),float(mask['high'])
        if not (np.isfinite(lo) and np.isfinite(hi) and lo<=hi):
            raise ValueError(f'{name}: invalid value-range limits')
        count=int(mask.get('populations',parameters['populations']))
        if count<0 or count>8:raise ValueError('0–8 Gaussian components allowed per mask')
        color=str(mask.get('color','C'+str(n%10)))
        peaks=mask.get('peaks',[])
        if isinstance(peaks,str):peaks=[x.strip() for x in peaks.split(',') if x.strip()]
        if not isinstance(peaks,list) or len(peaks)>count:raise ValueError(f'{name}: too many initial peak positions')
        peaks=[float(x) for x in peaks]
        if not all(np.isfinite(x) for x in peaks):raise ValueError(f'{name}: non-finite initial peak')
        output.append(dict(name=name,low=lo,high=hi,populations=count,color=color,peaks=peaks))
    return output


def _panel_source(ctx, channel, direction):
    """Return an independent raw scan panel; never register unlike rasters."""
    from spm_studio.core.models import Geometry
    if not channel or channel.lower() == 'auto':
        return None
    for trace in (direction, 'forward', 'backward'):
        key = f'{channel}|{trace}'
        if key in ctx.arrays:
            geo_info = (ctx.channel_geometries or {}).get(channel)
            geo = Geometry.from_dict(geo_info) if geo_info else ctx.geometry
            return np.asarray(ctx.arrays[key]), geo, (ctx.channel_units or {}).get(channel,ctx.unit), trace
    return None


def _peak_difference_rows(masks, fit_details, *, which='all'):
    """Absolute differences of dominant fitted peak positions, matching legacy x_max."""
    import itertools
    data=[]
    for mask in masks:
        fit=fit_details.get(mask['name'],{})
        peaks=fit.get('components') or []
        if peaks:
            peak=max(peaks,key=lambda item:item['amplitude'])
            data.append((mask['name'],peak['mu'],peak.get('mu_error',float('nan'))))
    pairs=[]
    names=[n for n,*_ in data]
    for a,b in zip(names,names[1:]):pairs.append((a,b))
    if len(names)>2:pairs.append((names[-1],names[0]))
    for a,b in itertools.combinations(names,2):
        if (a,b) not in pairs and (b,a) not in pairs:pairs.append((a,b))
    selected={p.strip() for p in str(which).split(',') if p.strip()}
    if str(which).strip().lower() in ('none','off','false','0'):return []
    byname={x[0]:x for x in data}
    rows=[]
    for a,b in pairs:
        if (selected and str(which).strip().lower()!='all' and
            f'{a}-{b}' not in selected and f'{b}-{a}' not in selected):
            continue
        _,ma,ea=byname[a];_,mb,eb=byname[b]
        err=float(np.hypot(ea,eb)) if np.isfinite(ea) and np.isfinite(eb) else float('nan')
        rows.append((a,b,abs(ma-mb),err))
    return rows


def _mask_legend_details(masks,fit_details,valid_count,unit_scale,unit_name, overrides=None):
    """Retain the exact information categories of the original CPD legend."""
    overrides=overrides or {}
    records=[]
    for mask in masks:
        name=mask['name'];d=fit_details.get(name,{})
        count=d.get('n',0)
        if not count:continue
        lines=[f'{name} histogram',f'N = {count:,} pixels ({100*count/valid_count:.1f}%)']
        if not d.get('components'):
            lines.append('No Gaussian fit' if d.get('requested',0)==0 else 'Gaussian fit unavailable')
        else:
            lines.append('Gaussian fit')
            for j,c in enumerate(d['components'],1):
                suffix=f' {j}' if len(d['components'])>1 else ''
                fnum=lambda value,err: (f'{value:.4g} ± {err:.2g}' if np.isfinite(err) else f'{value:.4g} (error unavailable)')
                lines.append(f'Gaussian{suffix}' if suffix else 'Gaussian')
                amp=c['amplitude']*(count/valid_count)/unit_scale
                ae=c.get('amplitude_error',float('nan'))*(count/valid_count)/unit_scale
                lines.append(f'A{suffix} = {fnum(amp,ae)} {unit_name}⁻¹')
                lines.append(f'x_max{suffix} = μ{suffix} = {fnum(c["mu"]*unit_scale,c.get("mu_error",float("nan"))*unit_scale)} {unit_name}')
                lines.append(f'σ{suffix} = {fnum(c["sigma"]*unit_scale,c.get("sigma_error",float("nan"))*unit_scale)} {unit_name}')
            r2=d.get('r_squared',float('nan'))
            lines.append(f'R² = {r2:.4f}' if np.isfinite(r2) else 'R² unavailable')
        user_override=overrides.get(name)
        records.append((name,mask['color'],str(user_override) if user_override is not None else '\n'.join(lines)))
    return records


def _composite_mask_figure(ctx, plt, direction, arr, spatial, masks, edges, raw_hist,
                           valid_count, figsize, mask_fit_curves=None, fit_details=None):
    """Original publication layout: stacked Z/Bias/masked panels and shared histogram.

    Source pixels, mask membership and histogram statistics are never rotated.
    Only exported scan images may use the legacy 180-degree display transform.
    """
    from matplotlib import colors
    from matplotlib.patches import Patch
    from mpl_toolkits.axes_grid1 import make_axes_locatable
    from spm_studio.core.models import preferred_display_unit

    config = ctx.plot_config or DEFAULT_PLOT
    params = ctx.parameters
    topo_channel = str(params.get('topography_channel','Z'))
    raw_channel = str(params.get('bias_panel_channel',ctx.channel))
    rotate = bool(params.get('rotate_export_180',True))
    image_panels = []
    for source_kind,enabled,channel,title,colorbar in (
        ('topography',params.get('show_topography',True),topo_channel,
         params.get('topography_title','Z / Topography'),params.get('topography_colorbar',True)),
        ('bias_panel',params.get('show_bias_panel',True),raw_channel,
         params.get('bias_panel_title','Bias raw'),params.get('bias_colorbar',True))):
        if not enabled:
            continue
        source=_panel_source(ctx,channel,direction)
        if source is None:
            ctx.log(f'{direction}: channel {channel!r} unavailable for the {title} comparison panel; '
                    'select an available channel in Tool settings',level='warning')
            continue
        pixels,geo,unit,trace=source
        cmap_setting=params.get(source_kind+'_cmap','From plot profile')
        image_panels.append(dict(kind='raw',name=str(title),pixels=pixels,
                                 channel=channel,geo=geo,unit=unit,colorbar=bool(colorbar),
                                 cmap=cmap_setting))
    if params.get('show_masked_panel',True) or not image_panels:
        image_panels.append(dict(kind='masked',name=str(params.get('masked_panel_title',
                 'Selected mask regions')),pixels=arr,channel=ctx.channel,geo=ctx.geometry,
                 unit=ctx.unit,colorbar=bool(params.get('masked_colorbar',False)),
                 cmap=params.get('masked_panel_cmap','From plot profile')))

    nrows=len(image_panels)
    fit_details=fit_details or {}
    figure_height=max(3.4*nrows+1,float(figsize[1]))
    # A dedicated third column reserves space for the complete fit legend.
    fig=plt.figure(figsize=(max(16.5,float(figsize[0])*1.25),figure_height))
    grid=fig.add_gridspec(nrows,3,width_ratios=(1,1.45,1.15),wspace=.25,hspace=.30)
    panel_axes=[]
    legend_handles=[]
    for idx,panel in enumerate(image_panels):
        ax=fig.add_subplot(grid[idx,0]);panel_axes.append(ax)
        data=np.asarray(panel['pixels'])
        geo=panel['geo']
        finite=np.isfinite(data)
        if not finite.any():
            ax.text(.5,.5,'No finite data',ha='center',va='center',transform=ax.transAxes)
            ax.set_axis_off();continue
        display_unit,factor=preferred_display_unit(panel['unit'],data)
        shown=np.asarray(data,dtype=np.float64)*factor
        lo,hi=np.nanpercentile(shown[finite],[2,98])
        if not np.isfinite(lo) or not np.isfinite(hi) or hi<=lo:
            hi=lo+max(abs(lo)*1e-6,1e-12)
        if geo.size_m:
            max_size=max(geo.size_m)
            multiplier,lateral_unit=(1e9,'nm') if max_size<1e-6 else ((1e6,'µm') if max_size<1e-3 else (1,'m'))
            width,height=[n*multiplier for n in geo.size_m]
        else:
            lateral_unit='px'
            height,width=data.shape
        # Reproduce the old CPD image display convention if requested.
        displayed=np.rot90(shown,2) if rotate else shown
        origin='lower' if rotate else 'upper'
        requested_cmap=panel.get('cmap','From plot profile')
        from spm_studio.core.plot_settings import resolve_cmap,viewer_limits,viewer_title
        cmap=display_cmap(panel['channel'],config) if requested_cmap=='From plot profile' else requested_cmap
        cmap=resolve_cmap(cmap)
        _vl=viewer_limits(config,panel['channel'],data)   # v34: contrast set on the scan
        if _vl:lo,hi=_vl[0]*factor,_vl[1]*factor
        img=ax.imshow(np.ma.masked_invalid(displayed),origin=origin,extent=[0,width,0,height],
                      cmap=cmap,interpolation=config.get('image_interpolation','nearest'),
                      vmin=lo,vmax=hi,aspect='equal')
        if panel['kind']=='masked':
            overlay=np.zeros((*data.shape,4),dtype=np.float32)
            for mask in masks:
                region=finite&spatial&(data>=mask['low'])&(data<=mask['high'])
                rgba=colors.to_rgba(mask['color'])
                overlay[region,:3]=rgba[:3]
                overlay[region,3]=.92
                if np.any(region):
                    legend_handles.append(Patch(facecolor=rgba,edgecolor='none',label=mask['name']))
            ax.imshow(np.rot90(overlay,2) if rotate else overlay,
                      origin=origin,extent=[0,width,0,height],interpolation='nearest',aspect='equal')
        ax.set_title(panel['name'])
        ax.set_axis_off()
        if geo.size_m and params.get('image_scale_bar',True):
            from math import floor,log10
            target=max(width/5,1e-12)
            order=10**floor(log10(target))
            scale_length=max((k*order for k in (1,2,5,10) if k*order<=target),default=order)
            xp=.075*width;yp=.075*height
            bar_color=params.get('scale_bar_color','white')
            ax.plot([xp,xp+scale_length],[yp,yp],c=bar_color,lw=3,solid_capstyle='butt')
            ax.text(xp+scale_length/2,yp+.024*height,f'{scale_length:g} {lateral_unit}',
                    color=bar_color,fontsize=9,ha='center',va='bottom',
                    bbox=dict(facecolor='black',alpha=.4,edgecolor='none',pad=1))
        if panel['colorbar'] and config.get('image_colorbar',True):
            cax=make_axes_locatable(ax).append_axes('bottom',size='8%',pad=.04)
            cb=fig.colorbar(img,cax=cax,orientation='horizontal')
            cb.set_label(f'{viewer_title(config,panel["channel"])} ({display_unit})',fontsize=8,labelpad=0)
            cb.ax.tick_params(labelsize=7,pad=1)
    hist=fig.add_subplot(grid[:,1])
    legend_ax=fig.add_subplot(grid[:,2]);legend_ax.set_axis_off()
    centers=(edges[1:]+edges[:-1])/2
    display_unit,xscale=preferred_display_unit(ctx.unit,centers)
    xedges=edges*xscale
    if params.get('histogram_raw_curve',True):
        hist.stairs(raw_hist/xscale,xedges,label='Raw selected area (100%)',color='#333333',lw=1.6)
    for idx,mask in enumerate(masks):
        selection=np.isfinite(arr)&spatial&(arr>=mask['low'])&(arr<=mask['high'])
        n=int(np.count_nonzero(selection))
        if n==0:continue
        # Normalize each mask to all valid analysis pixels, as in the legacy figure.
        density=np.histogram(arr[selection],bins=edges)[0]/valid_count/np.diff(edges)
        label=f'{mask["name"]} ({100*n/valid_count:.1f}%, n={n})'
        hist.stairs(density/xscale,xedges,color=mask['color'],lw=1.65,fill=True,
                    alpha=.13,label=label)
        hist.stairs(density/xscale,xedges,color=mask['color'],lw=1.7)
        if mask_fit_curves and idx in mask_fit_curves:
            xs,fitted=mask_fit_curves[idx]
            hist.plot(xs*xscale,fitted*n/valid_count/xscale,color=mask['color'],lw=1.8)
    hist.set(xlabel=params.get('x_axis_label','').strip() or f'{ctx.channel} ({display_unit})',
             ylabel=params.get('y_axis_label','').strip() or 'Probability density',
             title=params.get('plot_title','').strip() or f'{direction.title()} mask comparison')
    hist.set_xlim(float(xedges[0]),float(xedges[-1]));hist.set_ylim(bottom=0)
    # Reconstruct the original legend (population parameters, uncertainties, R²)
    # rather than only listing the mask names/percentages.
    import json
    try:
        overrides=json.loads(params.get('legend_texts_json','{}') or '{}')
        if not isinstance(overrides,dict):overrides={}
    except (TypeError,ValueError):
        overrides={}
    labels=_mask_legend_details(masks,fit_details,valid_count,xscale,display_unit,overrides)
    diffs=_peak_difference_rows(masks,fit_details,which=params.get('difference_pairs','all'))
    if bool(params.get('show_full_legend',True)):
        from matplotlib.patches import Patch
        handles=[Patch(facecolor=color,edgecolor='none',label=name) for name,color,_ in labels]
        texts=[body for _,_,body in labels]
        if diffs:
            msg=['Absolute peak differences']
            for a,b,value,error in diffs:
                d=value*xscale;e=error*xscale
                msg.append(f'|Δx_max({a}–{b})| = {d:.4g}'+
                           (f' ± {e:.2g}' if np.isfinite(e) else '')+f' {display_unit}')
            handles.append(Patch(facecolor='none',edgecolor='none'))
            texts.append('\n'.join(msg))
        if handles:
            size=float(params.get('legend_font_size',8.1))
            legend=legend_ax.legend(handles,texts,loc='upper left',bbox_to_anchor=(0,1),
                      borderaxespad=0,frameon=True,fancybox=True,framealpha=.90,
                      labelspacing=.9,fontsize=max(5,min(size,20)))
            for artist,(_,color,_) in zip(legend.get_texts(),labels):artist.set_color(color)
    fig._spm_cpd_legend_labels=[text for _,_,text in labels]
    fig._spm_cpd_differences=diffs
    # Explicit figure attributes also make its required three-panel structure testable.
    fig._spm_cpd_panel_names=[p['name'] for p in image_panels]
    fig._spm_cpd_panel_axes=panel_axes
    fig._spm_cpd_histogram_ax=hist
    return fig


def run(ctx):
    import csv, json
    masks=_masks(ctx.parameters)
    choice=ctx.parameters['trace_mode']
    dirs=([ctx.direction] if choice=='selected' else
          ['forward','backward'] if choice=='both' else [choice])
    all_records=[]
    all_masks=[]
    x_label=ctx.parameters.get('x_axis_label','').strip() or f'{ctx.channel} ({ctx.unit})'
    y_label=ctx.parameters.get('y_axis_label','').strip() or 'Probability density'
    user_title=ctx.parameters.get('plot_title','').strip()
    with plot_style(ctx.plot_config) as plt:
        for direction in dirs:
            arr=ctx.image(ctx.channel,direction)
            area=roi_values(ctx,arr)
            # The saved Boolean mask must use the same spatial ROI as the
            # distribution being fitted, not silently select outside it.
            spatial=np.zeros(arr.shape,dtype=bool)
            if ctx.roi is not None and ctx.roi.kind=='rectangle':
                (x0,y0),(x1,y1)=ctx.roi.points_px
                xa=max(0,int(min(x0,x1)));xb=min(arr.shape[1],int(max(x0,x1))+1)
                ya=max(0,int(min(y0,y1)));yb=min(arr.shape[0],int(max(y0,y1))+1)
                spatial[ya:yb,xa:xb]=True
            else:spatial[:]=True
            values=area[np.isfinite(area)]
            if values.size < 8:raise ValueError(f'{direction}: Not enough finite values in ROI')
            edges=np.histogram_bin_edges(values,bins=ctx.parameters['bins'])
            centers=(edges[:-1]+edges[1:])/2
            width=np.diff(edges)
            nr=len(values)
            fig,axs=plt.subplots(1,2,figsize=((ctx.plot_config or {}).get('figure_width_in',7)*1.45,
                                      (ctx.plot_config or {}).get('figure_height_in',4.4)))
            raw_hist=np.histogram(values,bins=edges)[0]/nr/width
            axs[0].stairs(raw_hist,edges,label='Raw',color='black',lw=1.6)
            axs[0].set(xlabel=x_label,ylabel=y_label,
                       title=user_title or f'{direction.title()} · raw distribution')
            fig_compare,axc=plt.subplots(figsize=((ctx.plot_config or {}).get('figure_width_in',7),4.4))
            axc.stairs(raw_hist,edges,color='black',label='All pixels')
            imgmask=np.zeros_like(arr,dtype=bool)
            mask_metadata=[]
            fixed_components=[]
            fit_curves={}
            fit_details={}
            if not masks and ctx.parameters.get('raw_populations',0):
                _,_,raw_components=_fit_populations(values,int(ctx.parameters['raw_populations']),
                                                    int(ctx.parameters['bins']))
                raw_fit=np.zeros_like(centers)
                for j,(mu,sigma,amplitude) in enumerate(raw_components,1):
                    curve=amplitude*np.exp(-.5*((centers-mu)/sigma)**2)
                    raw_fit+=curve
                    axs[0].plot(centers,curve,ls='--',label=f'Raw Gaussian {j}')
                    all_records.append([direction,'Raw image',j,mu,sigma,amplitude,nr,nr])
                axs[0].plot(centers,raw_fit,color='C3',label='Raw Gaussian sum')
            for idx,m in enumerate(masks):
                mask=np.isfinite(arr)&spatial&(arr>=m['low'])&(arr<=m['high'])
                localmask=np.isfinite(area)&(area>=m['low'])&(area<=m['high'])
                selected=area[localmask]
                if len(selected)<6:
                    ctx.log(f'{direction}: {m["name"]} has fewer than 6 selected values',level='warning')
                    continue
                name=m['name']
                color=m['color']
                mask_sum=np.count_nonzero(localmask)
                hist=np.histogram(selected,bins=edges)[0]/nr/width
                axs[0].stairs(hist,edges,label=name,color=color)
                axc.stairs(hist,edges,label=f'{name} ({100*mask_sum/nr:.1f}%)',color=color)
                fig_detail,ax=plt.subplots(figsize=((ctx.plot_config or {}).get('figure_width_in',7),4.4))
                individual=np.histogram(selected,bins=edges)[0]/mask_sum/width
                ax.stairs(individual,edges,color=color,label=name)
                fit_details[name]={'n':int(mask_sum),'requested':int(m['populations']),
                                   'components':[]}
                if m['populations']:
                    xs,ys,gaussians,fit_quality=_fit_populations(selected,m['populations'],int(ctx.parameters['bins']),m.get('peaks'),with_quality=True)
                    fit_details[name]['r_squared']=fit_quality['r_squared']
                    # Plot the fitted mask (density normalized to mask pixels) and
                    # its weighted contribution to the full raw histogram.
                    fit=np.zeros_like(xs)
                    for j,(mu,sigma,amp) in enumerate(gaussians,1):
                        yy=amp*np.exp(-.5*((xs-mu)/sigma)**2)
                        fit+=yy
                        ax.plot(xs,yy,ls='--',label=f'G{j}: μ={mu:.4g}, σ={sigma:.3g}')
                        ae,me,se=fit_quality['errors'].get(mu,(float('nan'),)*3)
                        fit_details[name]['components'].append({'mu':mu,'sigma':sigma,
                            'amplitude':amp,'mu_error':me,'sigma_error':se,'amplitude_error':ae})
                        all_records.append([direction,name,j,mu,sigma,amp,mask_sum,nr])
                        fixed_components.append((name,color,mu,sigma))
                    ax.plot(xs,fit,c='black',ls=':',label='Sum of fitted Gaussians')
                    fit_curves[idx]=(xs,fit)
                    axc.plot(xs,fit*mask_sum/nr,ls='--',c=color)
                ax.set(xlabel=x_label,ylabel='Density within mask',
                       title=f'{direction} · {name} ({mask_sum} px)')
                ax.legend()
                save_plot(ctx,fig_detail,f'{direction}_mask_{idx+1:02d}')
                imgmask |= mask
                maskfile=ctx.output_dir/f'{direction}_mask_{idx+1:02d}.npy'
                np.save(maskfile,mask,allow_pickle=False)
                ctx.result_file(maskfile,f'{name} boolean pixel mask')
                mask_metadata.append(dict(**m,pixels=int(mask.sum())))
                all_masks.append([direction,name,int(mask.sum()),m['low'],m['high']])
            if fixed_components and ctx.parameters.get('add_mask_fits_to_raw',True):
                from scipy.optimize import nnls
                basis=np.column_stack([np.exp(-.5*((centers-mu)/sigma)**2)
                         for name,color,mu,sigma in fixed_components])
                amps,_=nnls(basis,raw_hist)
                fitted=basis@amps
                raw_fit_rows=[]
                for (name,color,mu,sigma),amp,curve in zip(fixed_components,amps,basis.T):
                    weight=float(amp*sigma*np.sqrt(2*np.pi))
                    raw_fit_rows.append([direction,name,mu,sigma,float(amp),weight])
                    axs[0].plot(centers,amp*curve,color=color,ls='--',
                                label=f'{name} from mask, w={weight:.3f}')
                axs[0].plot(centers,fitted,color='black',ls=':',label='Total mask-derived raw fit')
                ctx.result_table(['trace','mask','mu_SI','sigma_SI','amplitude','absolute_area'],
                                 raw_fit_rows,'Mask-derived raw fit (fixed μ and σ)')
            axs[0].legend()
            mask_image=axs[1].imshow(np.where(imgmask,arr,np.nan) if masks else arr,
                   cmap=display_cmap(ctx.channel,ctx.plot_config or DEFAULT_PLOT),
                   origin='upper',interpolation='nearest')
            axs[1].set(title='Selected mask pixels' if masks else 'Raw image',xlabel='Column',ylabel='Row')
            if ctx.plot_config['image_colorbar']:
                fig.colorbar(mask_image,ax=axs[1],label=ctx.unit)
            save_plot(ctx,fig,f'{direction}_histograms_and_mask')
            axc.set(xlabel=x_label,ylabel=y_label,
                    title=user_title or f'{direction}: mask comparison')
            axc.legend()
            save_plot(ctx,fig_compare,f'{direction}_mask_comparison')
            if masks and ctx.parameters.get('comparison_with_masked_image',True):
                composite=_composite_mask_figure(ctx,plt,direction,arr,spatial,masks,edges,raw_hist,nr,
                      ((ctx.plot_config or DEFAULT_PLOT).get('figure_width_in',7)*2.1,
                       (ctx.plot_config or DEFAULT_PLOT).get('figure_height_in',4.4)*1.28),fit_curves,fit_details)
                import re
                channel_slug=re.sub(r'[^a-z0-9]+','_',ctx.channel.lower()).strip('_')
                stem=(f'{ctx.scan_path.stem}_with_masks_{channel_slug}_histogram_'
                      f'{direction}_mask_comparison_with_masked_image')
                panel_meta={
                    'analysis_channel':ctx.channel, 'trace':direction,
                    'topography_channel':ctx.parameters.get('topography_channel','Z'),
                    'raw_panel_channel':ctx.parameters.get('bias_panel_channel',ctx.channel),
                    'available_channels':sorted({key.split('|')[0] for key in ctx.arrays}),
                    'rendered_panels':list(composite._spm_cpd_panel_names),
                    'legacy_rotation_180':bool(ctx.parameters.get('rotate_export_180',True)),
                    'roi':ctx.roi.to_dict() if ctx.roi else None,
                    'plot_profile':(ctx.plot_config or DEFAULT_PLOT).get('name'),
                    'fit_details':fit_details,
                    'absolute_peak_differences':_peak_difference_rows(masks,fit_details,which=ctx.parameters.get('difference_pairs','all')),
                    'masks':[{'name':m['name'],'color':m['color'],
                              'low_SI':m['low'],'high_SI':m['high']} for m in masks],
                }
                provenance=ctx.output_dir/f'{stem}_figure_settings.json'
                # JSON does not define NaN/Infinity; preserve missing uncertainties
                # as null instead of emitting non-standard values.
                def json_safe(value):
                    if isinstance(value,float) and not np.isfinite(value):return None
                    if isinstance(value,dict):return {k:json_safe(v) for k,v in value.items()}
                    if isinstance(value,list):return [json_safe(v) for v in value]
                    if isinstance(value,tuple):return [json_safe(v) for v in value]
                    return value
                provenance.write_text(json.dumps(json_safe(panel_meta),indent=2,allow_nan=False)+'\n',encoding='utf8')
                ctx.result_file(provenance,'Combined figure channels and settings')
                save_plot(ctx,composite,stem)
            path=ctx.output_dir/f'{direction}_masks.json'
            path.write_text(json.dumps(mask_metadata,indent=2)+'\n',encoding='utf8')
            ctx.result_file(path,'Reusable named masks')
            ctx.progress(100*(dirs.index(direction)+1)/len(dirs),direction+' complete')
    with (ctx.output_dir/'histogram_fits.csv').open('w',newline='',encoding='utf8') as f:
        writer=csv.writer(f)
        writer.writerow(['trace','mask','component','mean_SI','sigma_SI','amplitude_density','mask_pixels','all_pixels'])
        writer.writerows(all_records)
    ctx.result_file(ctx.output_dir/'histogram_fits.csv','Mask Gaussian fits')
    ctx.result_table(['Trace','Mask','Component','μ (SI)','σ (SI)','Amp','Mask pixels','All pixels'],
                     all_records,'Mask Gaussian components')
    ctx.progress(100,'Completed')
