import numpy as np
from scipy.ndimage import gaussian_filter1d,gaussian_gradient_magnitude
from spm_studio.core.plots import plot_style
from spm_studio.core.analysis_utils import profile_from_roi,save_plot,save_csv

def _crossing(x,y,target,edge,left_side):
    segments=range(edge-1,-1,-1) if left_side else range(edge,len(y)-1)
    for i in segments:
        j=i+1
        if (y[i]-target)*(y[j]-target)<=0 and y[j]!=y[i]:
            return float(x[i]+(target-y[i])*(x[j]-x[i])/(y[j]-y[i]))
    return np.nan

def run(ctx):
    tname=ctx.parameters['topography_channel']
    topo=ctx.image(tname,ctx.direction)
    cpd=ctx.data
    if topo.shape!=cpd.shape:
        raise ValueError('Topography/CPD shape differs; registration required before analysis')
    xt,ht=profile_from_roi(ctx,tname,ctx.direction)
    xc,cp=profile_from_roi(ctx)
    if not np.allclose(xt,xc):raise ValueError('Profile physical grid mismatch')
    if np.isfinite(ht).sum()<12 or np.isfinite(cp).sum()<12:raise ValueError('Not enough finite profile pixels')
    if not np.isfinite(ht).all() or not np.isfinite(cp).all():
        raise ValueError('Profile has incomplete/invalid values; select a fully valid line ROI')
    sigma=max(0.,float(ctx.parameters['smooth_sigma_px']))
    h=gaussian_filter1d(ht,sigma) if sigma else ht
    c=gaussian_filter1d(cp,sigma) if sigma else cp
    deriv=np.gradient(h,xt)
    idx=int(np.argmax(np.abs(deriv)))
    n=len(h)
    width=max(2,int(n*.15))
    before=np.mean(h[max(0,idx-width):max(1,idx-width//3)])
    after=np.mean(h[min(n-1,idx+width//3):min(n,idx+width)])
    if not np.isfinite(before+after) or abs(after-before)<1e-30:
        raise ValueError('Topographic edge contrast too small for 10–90% width')
    y10=before+.1*(after-before)
    y90=before+.9*(after-before)
    x10=_crossing(xt,h,y10,idx,True)
    x90=_crossing(xt,h,y90,idx,False)
    topo_width=abs(x90-x10) if np.isfinite(x10+x90) else np.nan
    # A local, linear-endpoint baseline for edge-localized CPD residuals.
    baseline=np.interp(xc,[xc[0],xc[-1]],[np.median(c[:max(2,n//8)]),np.median(c[-max(2,n//8):])])
    residual=c-baseline
    win=max(3,int(n*ctx.parameters['edge_window_fraction']))
    lo,hi=max(0,idx-win),min(n,idx+win+1)
    peak=lo+int(np.argmax(np.abs(residual[lo:hi])))
    half=abs(residual[peak])*.5
    abs_res=np.abs(residual)
    xp1=_crossing(xc,abs_res,half,peak,True)
    xp2=_crossing(xc,abs_res,half,peak,False)
    cpd_width=abs(xp2-xp1) if np.isfinite(xp1+xp2) else np.nan
    finite=np.isfinite(topo)&np.isfinite(cpd)
    if np.mean(finite)<.75:ctx.log('Warning: substantial invalid region in gradient correlation','warning')
    fill=np.nanmedian(topo[finite])
    gradient=gaussian_gradient_magnitude(np.where(finite,topo,fill),1)
    correlation=float(np.corrcoef(gradient[finite],cpd[finite])[0,1]) if finite.sum()>10 else np.nan
    ctx.result_table(['measurement','value','distance_unit'],[
        ['topographic 10–90% width',topo_width,'m' if ctx.geometry.calibrated else 'px'],
        ['CPD residual FWHM',cpd_width,'m' if ctx.geometry.calibrated else 'px'],
        ['absolute width difference',abs(cpd_width-topo_width),'m' if ctx.geometry.calibrated else 'px'],
        ['2D Pearson(gradient(Z), CPD)',correlation,'dimensionless']], 'KPFM edge metrics')
    ctx.log(f'Topo width={topo_width:.5g}, CPD residual FWHM={cpd_width:.5g}; correlation={correlation:.3g}')
    save_csv(ctx,'edge_profiles.csv',['x_m_or_px','topography_SI','CPD_SI','CPD_residual_SI'],[xt,ht,cp,residual])
    ctx.progress(80,'Saving plots')
    with plot_style(ctx.plot_config) as plt:
        fig,axes=plt.subplots(2,1,sharex=True,figsize=((ctx.plot_config or {}).get('figure_width_in',7),
                                       (ctx.plot_config or {}).get('figure_height_in',4.4)*1.25))
        scale=1e9 if ctx.geometry.calibrated else 1.
        axes[0].plot(xt*scale,h,'k',label='Z')
        axes[0].axvline(xt[idx]*scale,ls='--',c='C1')
        axes[0].set(ylabel='Topography (SI)',title='Edge-centered aligned profiles')
        axes[1].plot(xc*scale,cp,label='CPD')
        axes[1].plot(xc*scale,residual,label='Residual (linear baseline)')
        axes[1].legend(fontsize=7)
        axes[1].set(xlabel='Distance (nm)' if ctx.geometry.calibrated else 'Distance (px)',ylabel=ctx.unit+' (SI)')
        fig.tight_layout()
        save_plot(ctx,fig,'kpfm_edge')
    ctx.progress(100,'Finished')
