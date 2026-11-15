import numpy as np
from scipy.signal import find_peaks
from spm_studio.core.plots import plot_style
from spm_studio.core.analysis_utils import profile_from_roi, profile_between, save_plot,save_csv

def run(ctx):
    x,p=profile_from_roi(ctx)
    if not np.isfinite(p).all():raise ValueError('Profile has invalid samples; select a complete line ROI')
    # Each retained line is analyzed independently rather than silently using
    # only the last one.  The primary chart below shows the last active line.
    lines=[roi for roi in (ctx.rois or []) if roi.kind=='line']
    if ctx.roi and ctx.roi.kind=='line' and ctx.roi not in lines:lines.append(ctx.roi)
    if lines:
        import csv
        records=[]
        for i,roi in enumerate(lines,1):
            xx,yy=profile_between(ctx.data,*roi.points_px)
            if ctx.geometry.size_m:
                (x0,y0),(x1,y1)=roi.points_px
                d=np.hypot((x1-x0)*ctx.geometry.size_m[0]/ctx.geometry.shape[1],
                           (y1-y0)*ctx.geometry.size_m[1]/ctx.geometry.shape[0])
                xx=np.linspace(0,d,len(xx))
            if not np.isfinite(yy).all():
                ctx.log(f'Line {i} skipped: incomplete signal','warning')
                continue
            for polarity,signal in [('max',yy),('min',-yy)]:
                picks,_=find_peaks(signal,prominence=ctx.parameters['peak_prominence_si'],
                                   distance=ctx.parameters['min_distance_px'])
                periods=np.diff(xx[picks])
                if len(periods):
                    records.append([i,polarity,len(periods),float(np.mean(periods)),
                                    float(np.std(periods,ddof=1)) if len(periods)>1 else np.nan])
        if records:
            with (ctx.output_dir/'lattice_selected_lines.csv').open('w',newline='',encoding='utf8') as f:
                w=csv.writer(f);w.writerow(['line','polarity','intervals','mean_m_or_px','std_m_or_px']);w.writerows(records)
            ctx.result_file(ctx.output_dir/'lattice_selected_lines.csv','All selected line intervals')
            ctx.result_table(['line','polarity','intervals','mean_m_or_px','std_m_or_px'],records,'Per-line lattice spacing')
    ctx.progress(25,'Finding maxima and minima')
    pr=ctx.parameters['peak_prominence_si']
    d=ctx.parameters['min_distance_px']
    maxima,_=find_peaks(p,prominence=pr,distance=d)
    minima,_=find_peaks(-p,prominence=pr,distance=d)
    pairs=[]
    for label,points in [('maximum',maxima),('minimum',minima)]:
        distances=np.diff(x[points])
        if len(distances):
            mean=float(np.mean(distances));sd=float(np.std(distances,ddof=1)) if len(distances)>1 else np.nan
            sem=sd/np.sqrt(len(distances)) if len(distances)>1 else np.nan
            ctx.log(f'{label} spacing: {mean:.6g}, SD={sd:.3g}, SEM={sem:.3g}; n={len(distances)}')
            pairs.append([label,len(distances),mean,sd,sem])
    ctx.result_table(['type','intervals','mean_m_or_px','std','sem'],pairs,'Peak spacing')
    save_csv(ctx,'lattice_profile.csv',['distance_m_or_px','value_SI'],[x,p])
    image=np.asarray(ctx.data)
    if not np.isfinite(image).all():
        image=np.where(np.isfinite(image),image,np.nanmedian(image))
        ctx.log('FFT median-fills invalid values for visualization only','warning')
    image=image-np.mean(image)
    if ctx.parameters['window_fft']:
        image=image*np.outer(np.hanning(image.shape[0]),np.hanning(image.shape[1]))
    transform=np.fft.fftshift(np.abs(np.fft.fft2(image)))
    ny,nx=image.shape
    dx=ctx.geometry.size_m[0]/nx if ctx.geometry.size_m else 1.
    dy=ctx.geometry.size_m[1]/ny if ctx.geometry.size_m else 1.
    gx=np.fft.fftshift(np.fft.fftfreq(nx,dx))
    gy=np.fft.fftshift(np.fft.fftfreq(ny,dy))
    ctx.log('FFT spatial frequency convention: cycles/m (NOT rad/m), B = G^(-T).')
    fft_path=ctx.output_dir/'fft_magnitude.npy'
    np.save(fft_path,transform)
    ctx.result_file(fft_path)
    ctx.progress(75,'Saving diagnostics')
    with plot_style(ctx.plot_config) as plt:
        fig,axes=plt.subplots(1,2,figsize=((ctx.plot_config or {}).get('figure_width_in',7)*1.35,
                                     (ctx.plot_config or {}).get('figure_height_in',4.4)))
        f=1e9 if ctx.geometry.calibrated else 1.
        axes[0].plot(x*f,p,'k',lw=1)
        for indices,mark in [(maxima,'o'),(minima,'v')]:
            axes[0].plot(x[indices]*f,p[indices],mark,ms=4)
        axes[0].set(xlabel='Distance (nm)' if ctx.geometry.calibrated else 'Distance (px)',ylabel=ctx.unit,title='Peak positions')
        axes[1].imshow(np.log1p(transform),origin='lower',cmap=__import__('spm_studio.core.plot_settings',fromlist=['display_cmap']).display_cmap(ctx.channel,ctx.plot_config or {'schema_version':1}),
                  extent=[gx[0]/f,gx[-1]/f,gy[0]/f,gy[-1]/f],aspect='equal')
        axes[1].set(xlabel='qx (cycles/nm)' if ctx.geometry.calibrated else 'qx (cycles/px)',
                    ylabel='qy (cycles/nm)' if ctx.geometry.calibrated else 'qy (cycles/px)',title='2D FFT diagnostic')
        fig.tight_layout()
        save_plot(ctx,fig,'lattice_diagnostic')
    ctx.log('Primitive-basis reduction, Gauss-reduction and cross-channel lattice consistency are not implemented; do not treat an FFT harmonic as a primitive lattice vector.')
    ctx.progress(100,'Finished')
