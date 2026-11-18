"""Shared simple offline analysis helpers; no GUI dependencies."""
from __future__ import annotations
from pathlib import Path
import numpy as np


def polyline_length(points, spacing=(1.0, 1.0)):
    """Length of a line or polyline ``((col,row), …)``; ``spacing`` = (dx, dy) per pixel."""
    pts=np.asarray(points,dtype=float).reshape(-1,2)
    if len(pts)<2:return 0.0
    d=np.diff(pts,axis=0)*np.asarray(spacing,dtype=float)
    return float(np.hypot(d[:,0],d[:,1]).sum())


def profile_along(data, points, samples=None, spacing=(1.0, 1.0)):
    """Bilinear profile along a polyline (two or more vertices, ``(col,row)``).

    Samples are evenly spaced along the path in *physical* arc length (``spacing`` gives
    the pixel size in X and Y), so the returned distance is exact also at the corners.
    """
    pts=np.asarray(points,dtype=float).reshape(-1,2)
    if len(pts)<2:raise ValueError('A profile needs at least two points')
    if len(pts)==2 and tuple(spacing)==(1.0,1.0):
        return profile_between(data,tuple(pts[0]),tuple(pts[1]),samples=samples)
    sx,sy=(float(spacing[0]),float(spacing[1]))
    seg=np.diff(pts,axis=0)
    seg_len=np.hypot(seg[:,0]*sx,seg[:,1]*sy)
    total=float(seg_len.sum())
    pixel_len=float(np.hypot(seg[:,0],seg[:,1]).sum())
    n=samples or max(2,int(pixel_len*2)+1)
    distance=np.linspace(0,total,n)
    edges=np.concatenate([[0.],np.cumsum(seg_len)])
    if total<=0:
        cols=np.full(n,pts[0,0]);rows=np.full(n,pts[0,1])
    else:
        cols=np.interp(distance,edges,pts[:,0]);rows=np.interp(distance,edges,pts[:,1])
    return distance,_bilinear(np.asarray(data),cols,rows)


def _bilinear(image,x,y):
    x=np.clip(x,0,image.shape[1]-1)
    y=np.clip(y,0,image.shape[0]-1)
    x0=np.floor(x).astype(int);x1=np.minimum(x0+1,image.shape[1]-1)
    y0=np.floor(y).astype(int);y1=np.minimum(y0+1,image.shape[0]-1)
    dx=x-x0;dy=y-y0
    samples=((1-dx)*(1-dy), image[y0,x0]), (dx*(1-dy), image[y0,x1]), \
            ((1-dx)*dy, image[y1,x0]), (dx*dy, image[y1,x1])
    z=np.zeros(len(x),dtype=float)
    for weight,values in samples:
        z+=np.where(weight>1e-14,weight*values,0.0)
    return z


def geometry_spacing(geometry, scale=1.0):
    """Pixel size (dx, dy) of a Geometry (metres × ``scale``), or (1, 1) when uncalibrated."""
    if geometry is None or not getattr(geometry,'size_m',None):return (1.0,1.0)
    ny,nx=geometry.shape
    return (geometry.size_m[0]/nx*scale,geometry.size_m[1]/ny*scale)


def profile_between(data, p0, p1, *more, samples=None):
    """Bilinear profile with NaNs propagated; p0/p1=(col,row), pixel-center convention.

    Extra vertices (a polyline drawn with Shift+click) are followed segment by segment.
    """
    if more:
        return profile_along(data,(p0,p1)+tuple(more),samples=samples)
    image=np.asarray(data)
    length=float(np.hypot(p1[0]-p0[0],p1[1]-p0[1]))
    n=samples or max(2,int(length*2)+1)
    x=np.linspace(p0[0],p1[0],n)
    y=np.linspace(p0[1],p1[1],n)
    x=np.clip(x,0,image.shape[1]-1)
    y=np.clip(y,0,image.shape[0]-1)
    x0=np.floor(x).astype(int);x1=np.minimum(x0+1,image.shape[1]-1)
    y0=np.floor(y).astype(int);y1=np.minimum(y0+1,image.shape[0]-1)
    dx=x-x0;dy=y-y0
    # Zero-weight neighbours must not contaminate exact pixel centres via 0*NaN.
    samples=((1-dx)*(1-dy), image[y0,x0]), (dx*(1-dy), image[y0,x1]), \
            ((1-dx)*dy, image[y1,x0]), (dx*dy, image[y1,x1])
    z=np.zeros(n,dtype=float)
    for weight,values in samples:
        z+=np.where(weight>1e-14,weight*values,0.0)
    return np.linspace(0,length,n),z


def profile_from_roi(ctx, channel=None, direction=None):
    a=ctx.image(channel,direction)
    if ctx.roi and ctx.roi.kind=='line':
        if ctx.geometry.size_m is not None:
            return profile_along(a,ctx.roi.points_px,spacing=geometry_spacing(ctx.geometry))
        return profile_between(a,*ctx.roi.points_px)
    if ctx.roi and ctx.roi.kind=='rectangle':
        ys,xs=rectangle_slices(ctx.roi,a.shape)
        profile=np.nanmean(a[ys,xs],axis=0)
        columns=np.arange(xs.start,xs.stop)
    else:
        profile=np.nanmean(a,axis=0)
        columns=np.arange(a.shape[1])
    spacing=ctx.geometry.size_m[0]/a.shape[1] if ctx.geometry.size_m else 1
    return (columns+.5)*spacing,profile


def save_plot(ctx, fig, stem):
    """Save selected publication formats only, with one shared validated style."""
    from matplotlib import pyplot as plt
    from .plots import (style_axes, finalize_publication_figure, publication_dpi, savefig_maybe_transparent,
                        apply_figure_customization)
    style=getattr(ctx,'plot_config',None)
    style_axes(fig,style)
    apply_figure_customization(fig,style)
    if getattr(fig,'_spm_cpd_panel_names',None) is not None:
        fig.subplots_adjust(left=.035,right=.83,top=.96,bottom=.06)
    else:
        try:fig.tight_layout()
        except Exception:pass
    # Letters must be placed after the final layout so they sit beside the y labels.
    finalize_publication_figure(fig,style)
    formats=getattr(ctx,'plot_formats',('png','pdf'))
    for ext in formats:
        if ext not in ('png','pdf','svg'):
            raise ValueError('Unsupported figure output: '+str(ext))
        dest=ctx.output_dir/f'{stem}.{ext}'
        savefig_maybe_transparent(fig,dest,transparent=bool((style or {}).get('transparent_background',False)),
                    background=(style or {}).get('background','white'),
                    dpi=publication_dpi((style or {}).get('dpi',600)),bbox_inches='tight',pad_inches=.01)
        ctx.result_file(dest,stem)
    plt.close(fig)


def save_csv(ctx,name,columns,data):
    path=ctx.output_dir/name
    np.savetxt(path,np.column_stack(data),delimiter=',',header=','.join(columns),comments='')
    ctx.result_file(path,name)
    return path


def roi_values(ctx, array=None):
    a=ctx.data if array is None else array
    if ctx.roi and ctx.roi.kind=='rectangle':
        (x1,y1),(x2,y2)=ctx.roi.points_px
        lo_x=max(0,int(min(x1,x2)));hi_x=min(a.shape[1],int(max(x1,x2))+1)
        lo_y=max(0,int(min(y1,y2)));hi_y=min(a.shape[0],int(max(y1,y2))+1)
        return a[lo_y:hi_y,lo_x:hi_x]
    return a


def rectangle_slices(roi, shape):
    """Return bounded [row,column] slices; a missing ROI selects everything."""
    if roi is None or roi.kind!='rectangle':
        return slice(0,shape[0]),slice(0,shape[1])
    (x0,y0),(x1,y1)=roi.points_px
    xa=max(0,int(min(x0,x1)));xb=min(shape[1],int(max(x0,x1))+1)
    ya=max(0,int(min(y0,y1)));yb=min(shape[0],int(max(y0,y1))+1)
    if xa>=xb or ya>=yb:raise ValueError('Selected region is outside the source raster')
    return slice(ya,yb),slice(xa,xb)

def region_mask(roi, shape):
    """Full-size Boolean spatial ROI, without altering image numbers."""
    mask=np.zeros(shape,dtype=bool)
    y,x=rectangle_slices(roi,shape)
    mask[y,x]=True
    return mask
