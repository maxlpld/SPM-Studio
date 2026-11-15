import numpy as np
from spm_studio.core.plots import plot_style
from spm_studio.core.plot_settings import display_cmap,DEFAULT_PLOT
from spm_studio.core.analysis_utils import save_plot,roi_values

def _fit_populations(values,k,bins):
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
        output.append(dict(name=name,low=lo,high=hi,populations=count,color=color))
    return output


def run(ctx):
    import csv, json
    masks=_masks(ctx.parameters)
    choice=ctx.parameters['trace_mode']
    dirs=([ctx.direction] if choice=='selected' else
          ['forward','backward'] if choice=='both' else [choice])
    all_records=[]
    all_masks=[]
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
            axs[0].set(xlabel=f'{ctx.channel} ({ctx.unit})',ylabel='Probability density',
                       title=f'{direction.title()} · raw distribution')
            fig_compare,axc=plt.subplots(figsize=((ctx.plot_config or {}).get('figure_width_in',7),4.4))
            axc.stairs(raw_hist,edges,color='black',label='All pixels')
            imgmask=np.zeros_like(arr,dtype=bool)
            mask_metadata=[]
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
                    xs,ys,gaussians=_fit_populations(selected,m['populations'],int(ctx.parameters['bins']))
                    # Plot the fitted mask (density normalized to mask pixels) and
                    # its weighted contribution to the full raw histogram.
                    fit=np.zeros_like(xs)
                    for j,(mu,sigma,amp) in enumerate(gaussians,1):
                        yy=amp*np.exp(-.5*((xs-mu)/sigma)**2)
                        fit+=yy
                        ax.plot(xs,yy,ls='--',label=f'G{j}: μ={mu:.4g}, σ={sigma:.3g}')
                        all_records.append([direction,name,j,mu,sigma,amp,mask_sum,nr])
                    ax.plot(xs,fit,c='black',ls=':',label='Sum of fitted Gaussians')
                    axc.plot(xs,fit*mask_sum/nr,ls='--',c=color)
                ax.set(xlabel=f'{ctx.channel} ({ctx.unit})',ylabel='Density within mask',
                       title=f'{direction} · {name} ({mask_sum} px)')
                ax.legend()
                save_plot(ctx,fig_detail,f'{direction}_mask_{idx+1:02d}')
                imgmask |= mask
                maskfile=ctx.output_dir/f'{direction}_mask_{idx+1:02d}.npy'
                np.save(maskfile,mask,allow_pickle=False)
                ctx.result_file(maskfile,f'{name} boolean pixel mask')
                mask_metadata.append(dict(**m,pixels=int(mask.sum())))
                all_masks.append([direction,name,int(mask.sum()),m['low'],m['high']])
            axs[0].legend()
            mask_image=axs[1].imshow(np.where(imgmask,arr,np.nan) if masks else arr,
                   cmap=display_cmap(ctx.channel,ctx.plot_config or DEFAULT_PLOT),
                   origin='upper',interpolation='nearest')
            axs[1].set(title='Selected mask pixels' if masks else 'Raw image',xlabel='Column',ylabel='Row')
            if ctx.plot_config['image_colorbar']:
                fig.colorbar(mask_image,ax=axs[1],label=ctx.unit)
            save_plot(ctx,fig,f'{direction}_histograms_and_mask')
            axc.set(xlabel=f'{ctx.channel} ({ctx.unit})',ylabel='Density / all valid pixels',
                    title=f'{direction}: mask comparison')
            axc.legend()
            save_plot(ctx,fig_compare,f'{direction}_mask_comparison')
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
