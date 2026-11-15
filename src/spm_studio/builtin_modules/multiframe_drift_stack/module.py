from pathlib import Path
import numpy as np
from scipy.ndimage import map_coordinates
from spm_studio.core.io import read_scan
from spm_studio.core.analysis_utils import save_plot,region_mask
from spm_studio.core.plots import plot_style

def run(ctx):
    if ctx.parameters['estimate_drift']:
        raise RuntimeError('Physical drift estimation has not been integrated from the archived spm-multiframe v0.1.2 engines')
    if not ctx.parameters['allow_unverified_orientation']:
        raise ValueError('Unverified SXM/GWY image orientation: manually verify a fiducial and check Acknowledge unverified orientation to proceed')
    exclusions={s.strip() for s in ctx.parameters['exclude_filenames'].split(',') if s.strip()}
    files=list(dict.fromkeys([str(ctx.scan_path)]+list(map(str,ctx.source_paths))))
    files=[p for p in files if Path(p).name not in exclusions]
    if len(files)<2:raise ValueError('Select at least two source scans in the Files panel')
    geom=ctx.geometry
    if not geom.calibrated or geom.center_m is None or geom.angle_deg is None:
        raise ValueError('Reference scan needs physical size, center and angle metadata; no guessed absolute coordinates')
    ny,nx=ctx.data.shape
    rr,cc=np.indices((ny,nx))
    sample_x,sample_y=geom.pixel_to_sample(rr,cc)
    accum=np.zeros((ny,nx),float)
    accum_sq=np.zeros((ny,nx),float)
    counts=np.zeros((ny,nx),np.uint16)
    reports=[]
    for i,path in enumerate(files):
        ctx.progress(100*i/len(files),f'Physical resampling {Path(path).name}')
        scan=read_scan(path)
        if ctx.channel not in scan.channels:
            ctx.log(f'Skipped {path}: requested channel unavailable','warning')
            continue
        ch=scan.channels[ctx.channel]
        if ctx.direction not in ch.traces:
            ctx.log(f'Skipped {path}: requested trace unavailable','warning')
            continue
        gg=ch.geometry
        if not gg.calibrated or gg.center_m is None or gg.angle_deg is None:
            ctx.log(f'Skipped {path}: absolute scan geometry unavailable','warning')
            continue
        row,col=gg.sample_to_pixel(sample_x,sample_y)
        input_data=ch.get(ctx.direction)
        # Bilinear interpolation requires all neighbor pixels to be valid.
        valid=(row>=0)&(col>=0)&(row<gg.shape[0]-1)&(col<gg.shape[1]-1)
        sampled=map_coordinates(input_data,[row.ravel(),col.ravel()],order=1,mode='constant',cval=np.nan).reshape(ny,nx)
        valid &= np.isfinite(sampled)
        accum[valid]+=sampled[valid]
        accum_sq[valid]+=sampled[valid]**2
        counts[valid]+=1
        reports.append([Path(path).name,int(valid.sum()),float(np.mean(valid)),str(gg.angle_deg),gg.scan_direction])
    minimum=ctx.parameters['min_contributors']
    valid=(counts>=minimum)&region_mask(ctx.roi,counts.shape)
    if not valid.any():raise ValueError('No shared physical region with requested minimum contributors')
    mean=np.full((ny,nx),np.nan)
    sigma=np.full((ny,nx),np.nan)
    mean[valid]=accum[valid]/counts[valid]
    sigma[valid]=np.sqrt(np.maximum(0,accum_sq[valid]/counts[valid]-mean[valid]**2))
    stderr=np.full((ny,nx),np.nan)
    stderr[valid]=sigma[valid]/np.sqrt(counts[valid])
    counts[~region_mask(ctx.roi,counts.shape)]=0
    for name,a in [('physical_stack_mean.npy',mean),('physical_stack_sigma.npy',sigma),
                   ('physical_stack_sem.npy',stderr),('physical_coverage_count.npy',counts)]:
        path=ctx.output_dir/name
        np.save(path,a,allow_pickle=False)
        ctx.result_file(path)
    ctx.result_table(['source','pixels_in_reference_grid','coverage_fraction','angle_deg','scan_direction'],reports,'Scan contributions')
    ctx.log(f'Physical overlap has {np.count_nonzero(valid)}/{ny*nx} valid reference pixels; {len(reports)} contributing scans')
    ctx.log('No drift, time-ordered line motion, or atomic tracking correction was estimated; quantitative interpretation needs real-data orientation validation.','warning')
    with plot_style(ctx.plot_config) as plt:
        fig,axes=plt.subplots(1,3,figsize=((ctx.plot_config or {}).get('figure_width_in',7)*1.6,
                                      (ctx.plot_config or {}).get('figure_height_in',4.4)))
        for ax,a,title in zip(axes,[mean,sigma,counts],['Mean (SI)','Population σ (SI)','Contributors']):
            obj=ax.imshow(a,cmap=__import__('spm_studio.core.plot_settings',fromlist=['display_cmap']).display_cmap(ctx.channel,ctx.plot_config or {'schema_version':1}),origin='upper',interpolation='none')
            ax.set_title(title)
            fig.colorbar(obj,ax=ax,shrink=.8)
        fig.tight_layout()
        save_plot(ctx,fig,'physical_stack_diagnostics')
    ctx.progress(100,'Done')
