"""Native, non-destructive Gwyddion-inspired interactive scan measurements.

All calculations use the *currently processed* SI-valued raster. Geometric
measurements use Geometry's physical scale; uncalibrated scans are in pixels.
Pure NumPy/SciPy functions allow regression tests without a Qt display.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np


@dataclass(frozen=True)
class Tool:
    identifier: str
    label: str
    symbol: str
    selection: str
    instructions: str


TOOLS = (
    Tool('navigate','Navigate / move','↖','pan','Drag the scan to move it; scroll to zoom.'),
    Tool('read_value','Read value','⌖','point','Click a pixel to read its calibrated position and value.'),
    Tool('distance','Distance / angle','↗','line','Draw a line to read Δx, Δy, distance, angle and Δz.'),
    Tool('axes_profile','Profiles along axes','╋','point','Click to display the horizontal and vertical profiles.'),
    Tool('profile','Line profile','〽','line','Draw or adjust a line; the profile updates live.'),
    Tool('radial','Radial profile','◎','line','Draw a radius from the centre; radial averages update live.'),
    Tool('channel_values','Channel values','⊙','point','Read the same pixel across available channels (not a spectroscopy curve).'),
    Tool('statistics','Area statistics','Σ','rectangle','Draw a rectangle to calculate height statistics and area.'),
    Tool('distribution','Height distribution','▥','rectangle','Draw a rectangle for a live height histogram.'),
    Tool('row_stats','Row / column statistics','≋','rectangle','Draw a rectangle for row and column mean profiles.'),
    Tool('correlation','Correlation length','∿','rectangle','Draw a rectangle for a row autocorrelation and correlation length.'),
    Tool('roughness','Line roughness','≈','line','Draw a line to calculate Ra, Rq and Rz.'),
    Tool('three_point','Three-point level','△','point','Click three non-collinear points; Apply levels the scan non-destructively.'),
    Tool('path_level','Path level','╱','line','Draw a reference path; Apply removes its measured tilt.'),
    Tool('crop','Crop selection','▣','rectangle','Draw a rectangle and apply a reversible crop. The same physical region is used by every channel and retained when profiles change.'),
    Tool('mask','Mask editor','▨','rectangle','Draw rectangles to add to the mask; use buttons to subtract or invert.'),
    Tool('grain_measure','Grain measurement','◉','rectangle','Measure connected mask regions in the selected rectangle.'),
    Tool('grain_remove','Remove mask grain','⊗','point','Click a masked grain to remove it from the mask.'),
    Tool('spot_remove','Spot remover','✕','point','Click a defect to preview local replacement; Apply keeps the edit reversible.'),
    Tool('color_range','Color range','◐','rectangle','Select a rectangle; Apply sets its min/max as the display range.'),
    Tool('filter','Filter preview','▤','rectangle','Draw a region to see filter statistics; Apply adds a Gaussian filter step.'),
    Tool('selection_manager','Selection manager','☷','rectangle','Inspect the current selection; clear or change tools as needed.'),
    Tool('fft','FFT / spectrum','∿','rectangle','Draw a rectangle to preview its radial spatial-frequency spectrum.'),
)
TOOL_BY_ID = {tool.identifier:tool for tool in TOOLS}


def roi_slice(shape, roi):
    """Return a bounded nonempty rectangular slice, or the complete image."""
    rows,cols=shape
    if roi is None or roi.kind != 'rectangle' or len(roi.points_px)<2:
        return slice(0, rows),slice(0, cols)
    (x0,y0),(x1,y1)=roi.points_px[:2]
    left=max(0,min(cols-1,int(math.floor(min(x0,x1)))))
    right=max(left+1,min(cols,int(math.ceil(max(x0,x1)))+1))
    top=max(0,min(rows-1,int(math.floor(min(y0,y1)))))
    bottom=max(top+1,min(rows,int(math.ceil(max(y0,y1)))+1))
    return slice(top,bottom),slice(left,right)


def point_pixel(roi, shape):
    if roi is None or roi.kind not in ('point','line') or not roi.points_px:return None
    x,y=roi.points_px[0]
    return (max(0,min(shape[1]-1,int(round(x)))),max(0,min(shape[0]-1,int(round(y)))))


def _axis_scale(geometry):
    ny,nx=geometry.shape
    if geometry.size_m:
        return geometry.size_m[0]/nx,geometry.size_m[1]/ny,'m'
    return 1.0,1.0,'px'


def line_profile(data, geometry, roi, max_samples=1600):
    if roi is None or roi.kind != 'line' or len(roi.points_px)<2:return None
    pts=np.asarray(roi.points_px,dtype=float)
    seg=np.diff(pts,axis=0)
    pixel_length=float(np.hypot(seg[:,0],seg[:,1]).sum())
    n=max(2,min(max_samples,int(math.ceil(pixel_length))+1))
    sx,sy,u=_axis_scale(geometry)
    # v0.0.10: a polyline (Shift+click) is followed segment by segment.
    seg_len=np.hypot(seg[:,0]*sx,seg[:,1]*sy)
    edges=np.concatenate([[0.],np.cumsum(seg_len)])
    distance=np.linspace(0,float(edges[-1]),n)
    if edges[-1]>0:
        xx=np.interp(distance,edges,pts[:,0]);yy=np.interp(distance,edges,pts[:,1])
    else:
        xx=np.full(n,pts[0,0]);yy=np.full(n,pts[0,1])
    from scipy.ndimage import map_coordinates
    values=map_coordinates(np.asarray(data,dtype=float),[yy,xx],order=1,mode='nearest')
    return distance,values


def area_statistics(data, geometry, roi=None, mask=None):
    ys,xs=roi_slice(data.shape,roi)
    arr=np.asarray(data[ys,xs],dtype=float)
    good=np.isfinite(arr)
    if mask is not None:good &= np.asarray(mask[ys,xs],bool)
    values=arr[good]
    if not values.size:return {'count':0}
    sx,sy,_=_axis_scale(geometry)
    mean=float(np.mean(values))
    result={'count':int(values.size),'minimum':float(values.min()),'maximum':float(values.max()),
            'mean':mean,'median':float(np.median(values)),
            'std':float(np.std(values)),'rms':float(np.sqrt(np.mean(values**2))),
            'ra':float(np.mean(np.abs(values-mean))),
            'area':float(values.size*sx*sy)}
    return result


def radial_profile(data, geometry, roi, bins=160):
    if roi is None or roi.kind!='line' or len(roi.points_px)<2:return None
    (x0,y0),(x1,y1)=roi.points_px[:2]
    sx,sy,u=_axis_scale(geometry)
    radius=math.hypot((x1-x0)*sx,(y1-y0)*sy)
    if radius<=0:return None
    px_radius_x=radius/sx;px_radius_y=radius/sy
    l=max(0,int(x0-px_radius_x));r=min(data.shape[1],int(x0+px_radius_x)+2)
    t=max(0,int(y0-px_radius_y));b=min(data.shape[0],int(y0+px_radius_y)+2)
    if r<=l or b<=t:return None
    # Bound memory and interactive latency with regular sampling when necessary.
    stride=max(1,int(math.ceil(math.sqrt((r-l)*(b-t)/350_000))))
    yy,xx=np.mgrid[t:b:stride,l:r:stride]
    rr=np.hypot((xx-x0)*sx,(yy-y0)*sy)
    values=np.asarray(data[t:b:stride,l:r:stride],float)
    valid=np.isfinite(values)&(rr<=radius)
    if not valid.any():return None
    edge=np.linspace(0,radius,bins+1)
    ix=np.minimum(bins-1,np.searchsorted(edge,rr[valid],side='right')-1)
    counts=np.bincount(ix,minlength=bins)
    sums=np.bincount(ix,weights=values[valid],minlength=bins)
    return (edge[:-1]+edge[1:])/2,np.divide(sums,counts,out=np.full(bins,np.nan),where=counts>0)


def autocorrelation_profile(region, geometry, max_points=512):
    region=np.asarray(region,dtype=float)
    stride=max(1,math.ceil(region.shape[1]/2048))
    a=region[:,::stride]
    # SPM images can contain invalid lines; ignore those rows.
    x=np.nanmean(a,axis=0)
    valid=np.isfinite(x)
    if np.count_nonzero(valid)<4:return None
    x=np.where(valid,x,np.nanmean(x))
    x-=np.mean(x)
    correlation=np.correlate(x,x,mode='full')[len(x)-1:]
    if correlation[0]<=0:return None
    correlation/=correlation[0]
    correlation=correlation[:max_points]
    sx,_,_=_axis_scale(geometry)
    lag=np.arange(len(correlation))*sx*stride
    beyond=np.flatnonzero(correlation<=1/math.e)
    correlation_length=lag[beyond[0]] if len(beyond) else np.nan
    return lag,correlation,float(correlation_length)


def fft_radial(region, geometry, bins=180):
    a=np.asarray(region,float)
    stride=max(1,math.ceil(max(a.shape)/512))
    a=a[::stride,::stride]
    if a.shape[0]<4 or a.shape[1]<4:return None
    good=np.isfinite(a)
    if not good.any():return None
    a=np.where(good,a,float(np.nanmedian(a)))
    a-=np.mean(a)
    wy,wx=np.hanning(a.shape[0]),np.hanning(a.shape[1])
    power=np.abs(np.fft.fftshift(np.fft.fft2(a*wy[:,None]*wx[None,:])))**2
    sx,sy,_=_axis_scale(geometry)
    fy=np.fft.fftshift(np.fft.fftfreq(a.shape[0],d=sy*stride))
    fx=np.fft.fftshift(np.fft.fftfreq(a.shape[1],d=sx*stride))
    radii=np.hypot(fy[:,None],fx[None,:])
    maxf=float(np.max(radii))
    if maxf<=0:return None
    ix=np.minimum(bins-1,(radii/maxf*bins).astype(int))
    total=np.bincount(ix.ravel(),weights=power.ravel(),minlength=bins)
    counts=np.bincount(ix.ravel(),minlength=bins)
    return (np.arange(bins)+.5)*maxf/bins,np.divide(total,counts,out=np.zeros(bins),where=counts>0)


def three_point_plane_coefficients(data, points):
    """Fit z = ax + by + c at exactly three pixel positions."""
    if len(points)!=3:raise ValueError('Select exactly three points')
    samples=[]
    for x,y in points:
        x=int(round(x));y=int(round(y))
        if x<0 or y<0 or x>=data.shape[1] or y>=data.shape[0]:raise ValueError('Point outside image')
        if not np.isfinite(data[y,x]):raise ValueError('Point is not finite')
        samples.append(float(data[y,x]))
    design=np.asarray([[x,y,1.] for x,y in points],dtype=float)
    if abs(np.linalg.det(design)) < 1e-6:raise ValueError('Choose three non-collinear points')
    return np.linalg.solve(design,np.asarray(samples))


def measure(tool, data, geometry, roi=None, *, points=(), mask=None, channels=None):
    """Return independent, live UI-safe numbers and 1D series.

    Result keys are 'lines' (user-visible), 'series' (for LivePlot), 'extra'.
    A missing selection produces instructions rather than fake values.
    """
    a=np.asarray(data)
    if a.ndim!=2:raise ValueError('Expected 2-D scan')
    desc=TOOL_BY_ID[tool]
    lines=[];series=[];extra={}
    sx,sy,unit=_axis_scale(geometry)
    xyunit='nm' if unit=='m' else 'px'
    factor=1e9 if unit=='m' else 1
    target=roi
    ys,xs=roi_slice(a.shape,roi)
    region=a[ys,xs]
    pp=point_pixel(roi,a.shape)
    if tool=='navigate':
        lines=['Drag to move the scan. Scroll to zoom. Fit resets all scan views.']
    elif tool=='selection_manager':
        lines=['Current selection: '+(str(roi.kind) if roi else 'none'),
               f'Available scan pixels: {a.shape[1]} × {a.shape[0]}']
    elif tool in ('read_value','channel_values'):
        if pp:
            x,y=pp
            px,py=geometry.pixel_to_local(y,x)
            lines=[f'X = {float(px)*factor:.6g} {xyunit}',f'Y = {float(py)*factor:.6g} {xyunit}',
                   f'Signal = {a[y,x]:.7g} (SI)']
            if tool=='channel_values' and channels:
                for name,v in channels.items():
                    if y<v.shape[0] and x<v.shape[1]:
                        lines.append(f'{name}: {v[y,x]:.6g}')
        else:lines=['Click a pixel for live readout.']
    elif tool in ('distance','profile','roughness','path_level','radial'):
        if roi is None or roi.kind!='line':lines=['Draw a line on the scan.']
        else:
            p=line_profile(a,geometry,roi)
            if p is not None:
                distance,z=p
                (_, _),(_x1,_y1)=roi.points_px[:2]
                x0,y0=roi.points_px[0]
                dx=(_x1-x0)*sx;dy=-( _y1-y0)*sy
                angle=math.degrees(math.atan2(dy,dx))
                lines=[f'Δx = {dx*factor:.5g} {xyunit}',f'Δy = {dy*factor:.5g} {xyunit}',
                       f'R = {distance[-1]*factor:.6g} {xyunit}',f'φ = {angle:.3f}°',
                       f'Δz = {z[-1]-z[0]:.6g} (SI)']
                if tool in ('profile','roughness','path_level'):
                    series=[('Profile',distance*factor,z)]
                if tool=='roughness':
                    q=z[np.isfinite(z)]
                    if q.size:
                        m=np.mean(q)
                        lines.extend([f'Ra = {np.mean(np.abs(q-m)):.6g}',f'Rq = {np.sqrt(np.mean((q-m)**2)):.6g}',f'Rz = {q.max()-q.min():.6g}'])
                if tool=='path_level' and distance[-1]>0:
                    slope=float(np.polyfit(distance[np.isfinite(z)],z[np.isfinite(z)],1)[0]) if np.isfinite(z).sum()>=2 else np.nan
                    lines.append(f'Path slope = {slope:.6g} (SI/{unit})')
                if tool=='radial':
                    rad=radial_profile(a,geometry,roi)
                    if rad is not None:series=[('Radial mean',rad[0]*factor,rad[1])]
    elif tool=='axes_profile':
        if pp:
            x,y=pp
            series=[('Row',np.arange(a.shape[1])*sx*factor,a[y,:]),
                    ('Column',np.arange(a.shape[0])*sy*factor,a[:,x])]
            lines=[f'Crosshair pixel = ({x}, {y})']
        else:lines=['Click a point for horizontal/vertical profiles.']
    elif tool=='three_point':
        lines=[f'{len(points)}/3 point(s) selected']
        if len(points)==3:
            try:
                coeff=three_point_plane_coefficients(a,points)
                lines.extend([f'Plane slope x = {coeff[0]:.6g}',f'Plane slope y = {coeff[1]:.6g}',
                              'Ready to level scan using these points.'])
            except ValueError as e: lines.append(str(e))
    elif tool in ('statistics','distribution','row_stats','correlation','crop','mask','grain_measure','color_range','filter','fft'):
        if roi is None or roi.kind!='rectangle': lines=['Drag a rectangle on the scan.']
        else:
            stats=area_statistics(a,geometry,roi,mask=mask if tool=='grain_measure' else None)
            lines=[f'Pixels = {stats.get("count",0)}',f'Size = {region.shape[1]} × {region.shape[0]} pixels']
            if stats.get('count'):
                lines.extend([f'Min = {stats["minimum"]:.6g} (SI)',f'Max = {stats["maximum"]:.6g} (SI)',
                              f'Mean = {stats["mean"]:.6g} (SI)',f'Std = {stats["std"]:.6g} (SI)',
                              f'Ra = {stats["ra"]:.6g} (SI)',f'Area = {stats["area"]:.6g} {unit}²'])
            if tool=='distribution':
                values=region[np.isfinite(region)]
                if values.size:
                    if values.size>400_000:values=values[::math.ceil(values.size/400_000)]
                    hist,edge=np.histogram(values,bins=90)
                    series=[('Height distribution',(edge[:-1]+edge[1:])/2,hist)]
            elif tool=='row_stats':
                series=[('Row mean',np.arange(region.shape[0])*sy*factor,np.nanmean(region,axis=1)),
                        ('Column mean',np.arange(region.shape[1])*sx*factor,np.nanmean(region,axis=0))]
            elif tool=='correlation':
                res=autocorrelation_profile(region,geometry)
                if res:
                    lag,corr,corrlen=res
                    series=[('Autocorrelation',lag*factor,corr)]
                    lines.append(f'1/e correlation length ≈ {corrlen*factor:.5g} {xyunit}')
            elif tool=='color_range' and stats.get('count'):
                extra['limits']=(stats['minimum'],stats['maximum'])
            elif tool=='crop':extra['shape']=region.shape
            elif tool=='grain_measure':
                from scipy.ndimage import label
                cut=(mask[ys,xs] if mask is not None else region>np.nanmedian(region))
                labeled,n=label(np.asarray(cut,bool))
                sizes=np.bincount(labeled.ravel())[1:]
                lines.extend([f'Connected grains = {n}',f'Average grain area = {np.mean(sizes)*sx*sy:.6g} {unit}²' if n else 'No grains'])
            elif tool=='filter':
                from scipy.ndimage import gaussian_filter
                vals=np.asarray(region,float)
                if vals.size:
                    sm=gaussian_filter(np.where(np.isfinite(vals),vals,np.nanmedian(vals)),1.)
                    lines.append(f'Gaussian σ=1 px preview RMS = {float(np.std(sm)):.6g}')
            elif tool=='fft':
                res=fft_radial(region,geometry)
                if res:series=[('Radial power spectrum',res[0],res[1])]
    elif tool in ('grain_remove','spot_remove'):
        if pp:lines=[f'Selected pixel = ({pp[0]}, {pp[1]})', 'Use the action below to update the preview.']
        else:lines=['Click a pixel on the preview.']
    else:lines=['Select an area on the preview.']
    return {'lines':lines,'series':series,'extra':extra}
