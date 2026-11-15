import numpy as np
import json
from pathlib import Path
from lattice_artifacts import rectangle_crop,normalize_gray,lattice_draw,write_gwy
from roi_pipeline import solve_roi
from scipy.signal import find_peaks
from spm_studio.core.plots import plot_style
from spm_studio.core.analysis_utils import profile_from_roi, profile_between, save_plot,save_csv

def run(ctx):
    if ctx.parameters.get('analysis_method','primitive_auto')=='primitive_auto':
        return run_primitive_with_crop(ctx)
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
        fig,axes=plt.subplots(1,2,figsize=((getattr(ctx,'plot_config',None) or {}).get('figure_width_in',7)*1.35,
                                     (getattr(ctx,'plot_config',None) or {}).get('figure_height_in',4.4)))
        f=1e9 if ctx.geometry.calibrated else 1.
        axes[0].plot(x*f,p,'k',lw=1)
        for indices,mark in [(maxima,'o'),(minima,'v')]:
            axes[0].plot(x[indices]*f,p[indices],mark,ms=4)
        _titles=bool(ctx.parameters.get('diagnostic_titles',True))
        axes[0].set(xlabel='Distance (nm)' if ctx.geometry.calibrated else 'Distance (px)',ylabel=ctx.unit,title='Peak positions' if _titles else '')
        _fft_cmap=str(ctx.parameters.get('fft_colormap','auto') or 'auto')
        if _fft_cmap=='auto':
            _fft_cmap=__import__('spm_studio.core.plot_settings',fromlist=['display_cmap']).display_cmap(ctx.channel,ctx.plot_config or {'schema_version':1})
        _fft_cmap=__import__('spm_studio.core.plot_settings',fromlist=['resolve_cmap']).resolve_cmap(_fft_cmap)
        axes[1].imshow(np.log1p(transform),origin='lower',cmap=_fft_cmap,
                  extent=[gx[0]/f,gx[-1]/f,gy[0]/f,gy[-1]/f],aspect='equal')
        axes[1].set(xlabel='qx (cycles/nm)' if ctx.geometry.calibrated else 'qx (cycles/px)',
                    ylabel='qy (cycles/nm)' if ctx.geometry.calibrated else 'qy (cycles/px)',title='2D FFT diagnostic' if _titles else '')
        fig.tight_layout()
        save_plot(ctx,fig,'lattice_diagnostic')
    ctx.log('Primitive-basis reduction, Gauss-reduction and cross-channel lattice consistency are not implemented; do not treat an FFT harmonic as a primitive lattice vector.')
    ctx.progress(100,'Finished')


def run_primitive_with_crop(ctx):
    """Analyze selected ROI, save a calibrated derived GWY and reusable lattice artifact."""
    rectangles=[r for r in (ctx.rois or []) if r.kind=='rectangle']
    if ctx.roi is not None and ctx.roi.kind=='rectangle' and ctx.roi not in rectangles:
        rectangles.append(ctx.roi)
    roi=rectangles[-1] if rectangles else None
    crop,geometry=rectangle_crop(ctx.data,ctx.geometry,roi)
    multi=bool(ctx.parameters.get('use_all_scans',False))
    if multi and roi is not None:
        raise ValueError('Multi-scan FFT requires the full scan. Clear the rectangle ROI, or uncheck Analyze ALL scans in current folder.')
    ctx.progress(5,'Checking calibrated region')
    if roi is not None:
        if ctx.parameters.get('estimate_drift'):
            raise ValueError('ROI-only mode uses original FFT/primitive reduction but not a multiframe drift fit. Disable drift or analyze complete scans.')
        result=solve_roi(crop,geometry)
        ctx.log(f'Primitive basis from selected ROI: {result["a_nm"]:.4f} × {result["b_nm"]:.4f} nm, γ={result["gamma_deg"]:.2f}°')
    else:
        # Preserve the complete legacy calculation, uncertainty estimates and
        # optional drift analysis for full-field lattice measurements.
        from legacy_engine import run_original
        original=run_original(ctx,estimate_drift=ctx.parameters.get('estimate_drift',False),
                             use_all_scans=multi,stack=False,registration_channel=ctx.channel,
                             trace=ctx.parameters.get('trace_direction','forward'),
                             lattice_bootstrap=ctx.parameters.get('lattice_bootstrap',400),
                             drift_bootstrap=ctx.parameters.get('drift_bootstrap',32))
        source=json.loads(Path(original.manifest_path).read_text(encoding='utf8'))
        lat=source['lattice']
        world_basis=np.asarray(lat['basis_nm'],dtype=float)
        theta=np.deg2rad(geometry['scan_angle_deg'])
        unrotate=np.array([[np.cos(theta),np.sin(theta)],[-np.sin(theta),np.cos(theta)]])
        local_basis=unrotate@world_basis
        result={'basis_local_nm':local_basis.tolist(),
                'a_nm':float(lat['a_nm']),'b_nm':float(lat['b_nm']),
                'gamma_deg':float(lat['gamma_deg']),
                'method':'Original MultiFrame 0.1.2 full-scan drift/lattice analysis',
                'source_analysis_json':str(original.manifest_path)}
    local=np.asarray(result['basis_local_nm'],dtype=float)
    theta=np.deg2rad(geometry['scan_angle_deg'])
    rotated=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])@local
    npy=ctx.output_dir/'cropped_scan.npy'
    np.save(npy,np.asarray(crop))
    vector_colors=(str(ctx.parameters.get('vector_a_color','#16d8f5')),
                   str(ctx.parameters.get('vector_b_color','#fbb748')))
    legend_corner=ctx.parameters.get('vector_legend_corner','top_left')
    if legend_corner not in ('top_left','top_right','bottom_left','bottom_right'):
        raise ValueError('Unknown vector legend corner')
    side=ctx.parameters.get('colorbar_position','below')
    if side not in ('left','right','below','none'):
        raise ValueError('Colorbar position must be left, right, below or none')
    # v0.8: ONE publication figure, drawn by the very same renderer as the
    # Export panel (same gap scan/colourbar, scale bar, fonts, page size) with
    # the colormap and contrast currently set on the scan in the viewer.
    from spm_studio.core import script_figures as figures
    cfg=getattr(ctx,'plot_config',None) or {'schema_version':1}
    style=figures.scan_display_style(cfg,ctx.channel,colormap_override=ctx.parameters.get('scan_colormap',''))
    zero_legend=any(step.get('operation')=='fix_zero' and step.get('enabled',True)
                    for step in (getattr(ctx,'processing',None) or []))
    title=figures.colorbar_title(cfg,ctx.channel,ctx.parameters.get('colorbar_title',''))
    lattice_info={'basis_local_nm':result['basis_local_nm'],'gamma_deg':float(result['gamma_deg']),
                  'roi_geometry':geometry,'vector_colors':list(vector_colors),
                  'vector_legend_corner':legend_corner}
    from matplotlib.colors import is_color_like
    if not all(is_color_like(c) for c in vector_colors):
        raise ValueError('Vector colors must be valid colors, e.g. #16d8f5')
    ctx.progress(80,'Rendering publication figure (Export-panel layout)')
    written=figures.export_scan_figure(ctx.output_dir/'07_reference_scan_lattice_overlay',
        scan_path=ctx.scan_path,data=crop,size_nm=geometry['size_nm'],channel=ctx.channel,unit=ctx.unit,
        plot_config=cfg,formats=getattr(ctx,'plot_formats',('svg',)),style=style,lattice=lattice_info,
        colorbar_position=('below' if side=='none' else side),
        show_colorbar=bool(ctx.parameters.get('show_colorbar',True)) and side!='none',
        title=title,display_zero=zero_legend,figure_title=ctx.parameters.get('overlay_title',''))
    for path in written:
        ctx.result_file(path,'Lattice vectors on scan · '+path.suffix[1:].upper())
    gwy=None
    if bool(ctx.parameters.get('export_gwy',False)):
        gwy=ctx.output_dir/'lattice_region.gwy'
        try:
            gray=normalize_gray(crop)
            annotated=lattice_draw(gray,local,geometry,colors=vector_colors,legend_corner=legend_corner)
            write_gwy(gwy,[(ctx.channel+' (cropped '+ctx.direction+')',crop,ctx.unit),
                           ('Lattice vectors (display only)',np.asarray(annotated.convert('L'),float),'a.u.')],
                      geometry,basis_local_nm=local,extra_metadata={'Lattice a (nm)':result['a_nm'],
                      'Lattice b (nm)':result['b_nm'],'Lattice gamma (deg)':result['gamma_deg'],
                      'Scan orientation':geometry['orientation'],'Source scan':ctx.scan_path.name})
            ctx.result_file(gwy,'Gwyddion calibrated cropped scan and lattice annotation')
        except Exception as exc:
            ctx.log('GWY export could not be generated: '+str(exc),'warning')
            gwy=None
    manifest={
        'schema_version':1,'kind':'spm_studio_lattice_roi',
        'source_scan':str(ctx.scan_path.resolve()),
        'source_channel':ctx.channel,'source_direction':ctx.direction,
        'roi_geometry':geometry,'basis_local_nm':result['basis_local_nm'],
        'source_raster_geometry':ctx.geometry.to_dict(),
        'analysis_session_crop':(getattr(ctx,'metadata',{}) or {}).get('session_crop'),
        'basis_sample_nm':rotated.tolist(),'a_nm':result['a_nm'],'b_nm':result['b_nm'],
        'gamma_deg':result['gamma_deg'],'analysis_method':result['method'],
        'colorbar_zero_reference':zero_legend,
        'vector_legend_corner':legend_corner,'vector_colors':list(vector_colors),
        # v0.8: the scan display used for the figure, reused by molecule placement
        # and by Export… so every figure of this result has identical colours.
        'display_style':figures.style_to_dict(style),'colorbar_title':title,
        'colorbar_position':side,'show_colorbar':bool(ctx.parameters.get('show_colorbar',True)),
        'analysis_detail':result,'source_unit':ctx.unit,
        'cropped_scan_npy':str(npy),
        'publication_figures':[str(p) for p in written],
        'lattice_preview_png':None,
        'lattice_region_gwy':str(gwy) if gwy else None,
        'orientation_note':'Rasters use stored array orientation; physical inversion/flip must be instrument verified.'}
    artifact=ctx.output_dir/'lattice_result.json'
    artifact.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf8')
    ctx.result_file(artifact,'Lattice ROI manifest for molecule placement')
    ctx.result_table(['quantity','value','unit'],[
        ['a',result['a_nm'],'nm'],['b',result['b_nm'],'nm'],['gamma',result['gamma_deg'],'deg'],
        ['pixel X',geometry['pixel_size_nm'][0],'nm/pixel'],['pixel Y',geometry['pixel_size_nm'][1],'nm/pixel']],
        'Lattice calibration for molecule placement')
    ctx.progress(100,'Calibrated lattice region exported')
    return artifact


def _png_bytes(image):
    from io import BytesIO
    b=BytesIO();image.save(b,'PNG');return b.getvalue()
