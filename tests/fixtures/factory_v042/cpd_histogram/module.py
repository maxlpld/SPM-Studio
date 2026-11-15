import numpy as np
from spm_studio.core.plots import plot_style
from spm_studio.core.plot_settings import display_cmap,DEFAULT_PLOT
from spm_studio.core.analysis_utils import save_plot,roi_values

def _fit_populations(values,k,bins,initial_peaks=None):
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


def _composite_mask_figure(ctx, plt, direction, arr, spatial, masks, edges, raw_hist,
                           valid_count, figsize, mask_fit_curves=None):
    """Comparison image with colored mask pixels plus count-normalized curves.

    Histogram normalization uses the same denominator as the raw image. Physical
    extents are taken from source geometry, not the downsampled UI preview.
    """
    import matplotlib.colors as colors
    import matplotlib.patches as patches
    from pathlib import Path
    from spm_studio.core.models import preferred_display_unit
    from spm_studio.core.plot_settings import display_cmap,DEFAULT_PLOT

    fig,(ax_img,ax_hist)=plt.subplots(1,2,figsize=figsize,
                                     gridspec_kw={'width_ratios':[1.0,1.38]})
    valid=np.isfinite(arr)
    if np.count_nonzero(valid)==0:raise ValueError('No image pixels available')
    vmin,vmax=np.nanpercentile(arr[valid],[2,98])
    if vmin==vmax:vmax=vmin+max(abs(vmin)*1e-6,1e-15)
    geo=ctx.geometry
    if geo.size_m:
        physical=max(geo.size_m)
        if physical < 1e-6:
            multiplier,geo_unit=1e9,'nm'
        elif physical < 1e-3:
            multiplier,geo_unit=1e6,'µm'
        else:multiplier,geo_unit=1.,'m'
        width,height=[n*multiplier for n in geo.size_m]
    else:
        geo_unit='px'
        height,width=arr.shape
    extent=[0,width,0,height]
    base=np.ma.masked_invalid(arr)
    im=ax_img.imshow(base,origin='upper',extent=extent,
        cmap=display_cmap(ctx.channel,ctx.plot_config or DEFAULT_PLOT),
        interpolation=(ctx.plot_config or DEFAULT_PLOT).get('image_interpolation','nearest'),
        vmin=vmin,vmax=vmax,aspect='equal')
    rgba=np.zeros((*arr.shape,4),dtype=np.float32)
    xvals=(edges[:-1]+edges[1:])/2
    color_legend=[]
    ax_hist.stairs(raw_hist,edges,color='black',linewidth=1.7,label='Raw image (100%)')
    for idx,m in enumerate(masks):
        color=m['color']
        mask=valid&spatial&(arr>=m['low'])&(arr<=m['high'])
        n=int(np.count_nonzero(mask))
        # Allow overlapping value ranges; masks are not made artificially disjoint.
        rgba[mask,:3]=colors.to_rgba(color)[:3]
        rgba[mask,3]=.62
        if n<1:continue
        density=np.histogram(arr[mask],bins=edges)[0]/valid_count/np.diff(edges)
        label=f'{m["name"]} ({100*n/valid_count:.1f}%, n={n})'
        ax_hist.stairs(density,edges,linewidth=1.5,color=color,label=label)
        if mask_fit_curves and idx in mask_fit_curves:
            xs, fitted=mask_fit_curves[idx]
            ax_hist.plot(xs,fitted*n/valid_count,color=color,ls='--',lw=1.5)
        color_legend.append(patches.Patch(color=color,label=m['name']))
    ax_img.imshow(rgba,origin='upper',extent=extent,interpolation='nearest',aspect='equal')
    ax_img.set(xlabel=f'X ({geo_unit})',ylabel=f'Y ({geo_unit})',title='Masked image')
    if (ctx.plot_config or DEFAULT_PLOT).get('image_colorbar',True):
        fig.colorbar(im,ax=ax_img,orientation='horizontal',fraction=.06,
                     pad=.14,label=f'{ctx.channel} ({ctx.unit})')
    if color_legend:ax_img.legend(handles=color_legend,loc='upper right',fontsize='small')
    if geo.size_m and ctx.parameters.get('image_scale_bar',True):
        from math import floor,log10
        target=width/5
        decade=10**floor(log10(target)) if target>0 else 1
        length=max((v*decade for v in (1,2,5,10) if v*decade<=target),default=decade)
        xp=.08*width;yp=.08*height
        bar_color=ctx.parameters.get('scale_bar_color','white')
        ax_img.plot([xp,xp+length],[yp,yp],lw=3,color=bar_color,solid_capstyle='butt')
        ax_img.text(xp+length/2,yp+.028*height,f'{length:g} {geo_unit}',
                    color=bar_color,ha='center',va='bottom',fontsize=9,
                    bbox={'facecolor':'black','alpha':.35,'edgecolor':'none','pad':1})
    ax_hist.set(xlabel=ctx.parameters.get('x_axis_label','').strip() or f'{ctx.channel} ({ctx.unit})',
                ylabel=ctx.parameters.get('y_axis_label','').strip() or 'Density / all ROI pixels',
                title=ctx.parameters.get('plot_title','').strip() or f'{direction.title()} mask comparison')
    ax_hist.legend(loc='best',fontsize='small')
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
                if m['populations']:
                    xs,ys,gaussians=_fit_populations(selected,m['populations'],int(ctx.parameters['bins']),m.get('peaks'))
                    # Plot the fitted mask (density normalized to mask pixels) and
                    # its weighted contribution to the full raw histogram.
                    fit=np.zeros_like(xs)
                    for j,(mu,sigma,amp) in enumerate(gaussians,1):
                        yy=amp*np.exp(-.5*((xs-mu)/sigma)**2)
                        fit+=yy
                        ax.plot(xs,yy,ls='--',label=f'G{j}: μ={mu:.4g}, σ={sigma:.3g}')
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
                       (ctx.plot_config or DEFAULT_PLOT).get('figure_height_in',4.4)*1.28),fit_curves)
                import re
                channel_slug=re.sub(r'[^a-z0-9]+','_',ctx.channel.lower()).strip('_')
                stem=(f'{ctx.scan_path.stem}_with_masks_{channel_slug}_histogram_'
                      f'{direction}_mask_comparison_with_masked_image')
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
