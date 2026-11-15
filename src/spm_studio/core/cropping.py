"""Reversible, co-registered multichannel crops for SPM Studio.

The crop is a **view**: every channel is sliced from its unprocessed source
array and its own non-destructive processing pipeline remains separate.
Fractions refer to the original acquisition geometry, never a processed image.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from .models import Channel, Geometry, ROI


class CropAlignmentError(ValueError):
    """No defensible pixel-to-physical mapping for this channel."""


@dataclass(frozen=True)
class CropRegion:
    left: float
    top: float
    right: float
    bottom: float
    reference: Geometry

    @classmethod
    def from_roi(cls, roi: ROI, geometry: Geometry, previous: 'CropRegion | None' = None):
        from .interactive_tools import roi_slice
        if roi is None or roi.kind != 'rectangle':
            raise ValueError('Draw a rectangle before cropping')
        ys, xs = roi_slice(geometry.shape, roi)
        ny, nx = geometry.shape
        u0, u1 = xs.start/nx, xs.stop/nx
        v0, v1 = ys.start/ny, ys.stop/ny
        if previous is None:
            return cls(u0, v0, u1, v1, geometry)
        return cls(previous.left + u0*(previous.right-previous.left),
                   previous.top + v0*(previous.bottom-previous.top),
                   previous.left + u1*(previous.right-previous.left),
                   previous.top + v1*(previous.bottom-previous.top),
                   previous.reference)

    def source_slices(self, shape: tuple[int,int]):
        ny, nx = shape
        left = max(0, min(nx-1, round(self.left*nx)))
        right = max(left+1, min(nx, round(self.right*nx)))
        top = max(0, min(ny-1, round(self.top*ny)))
        bottom = max(top+1, min(ny, round(self.bottom*ny)))
        return slice(top,bottom), slice(left,right)

    def to_dict(self):
        return {'left':self.left,'top':self.top,'right':self.right,'bottom':self.bottom,
                'reference_geometry':self.reference.to_dict()}


def _same_geometry(a: Geometry, b: Geometry) -> bool:
    """Same footprint and orientation; different pixel densities are allowed.

    A fractional crop is only physically meaningful between co-registered scans.
    In particular, never silently crop a different scan centre or rotation.
    """
    if a.source_orientation != b.source_orientation:
        return False
    if (a.size_m is None) != (b.size_m is None):
        return False
    if a.size_m is None and a.shape != b.shape:
        return False   # Pixel coordinates cannot identify a shared region.
    if a.size_m is not None and not np.allclose(a.size_m, b.size_m, rtol=1e-8, atol=0):
        return False
    if (a.center_m is None) != (b.center_m is None):
        return False
    if a.center_m is not None and not np.allclose(a.center_m,b.center_m,rtol=0,atol=1e-12):
        return False
    if (a.angle_deg is None) != (b.angle_deg is None):
        return False
    if a.angle_deg is not None and not math.isclose(a.angle_deg,b.angle_deg,abs_tol=1e-7):
        return False
    return True


def crop_channel(source: Channel, region: CropRegion) -> Channel:
    """Return a new read-only Channel preserving all raw traces and metadata.

    Cropping does not apply/re-apply plane subtraction, row leveling, or any
    other processing. The GUI runs the existing steps after slicing.
    """
    g=source.geometry
    if not _same_geometry(g,region.reference):
        raise CropAlignmentError(
            f'{source.name}: acquisition footprint/rotation differs from the '
            'cropped reference. Refusing an incorrectly aligned crop.')
    ys,xs=region.source_slices(g.shape)
    geometry_size=(g.size_m[0]*(xs.stop-xs.start)/g.shape[1],
                   g.size_m[1]*(ys.stop-ys.start)/g.shape[0]) if g.size_m else None
    center=None
    if g.center_m is not None and g.angle_deg is not None:
        cx=(xs.start+xs.stop-1)/2
        cy=(ys.start+ys.stop-1)/2
        center=tuple(map(float,g.pixel_to_sample(cy,cx)))
    new_geometry=Geometry(
        shape=(ys.stop-ys.start,xs.stop-xs.start),
        size_m=geometry_size,center_m=center,
        angle_deg=g.angle_deg,scan_direction=g.scan_direction,
        source_orientation=g.source_orientation,
        verified_orientation=g.verified_orientation)
    traces={direction:np.array(array[ys,xs],copy=True)
            for direction,array in source.traces.items()}
    return Channel(source.name,source.unit,traces,new_geometry,list(source.warnings))


# ---------------------------------------------------------------------------
# v32 — automatic crop of incomplete (aborted / partial) scans
# ---------------------------------------------------------------------------
def _invalid_lines(a, axis, *, min_finite=.98):
    """True for rows (axis=1) / columns (axis=0) that hold no measured data.

    A line is unmeasured when it is (almost) all NaN/inf, or perfectly constant
    (the 0 or repeated fill value written for lines the tip never scanned).
    """
    finite=np.isfinite(a)
    frac=finite.mean(axis=axis)
    import warnings
    with np.errstate(all='ignore'),warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        filled=np.where(finite,a,np.nan)
        spread=np.nanmax(filled,axis=axis)-np.nanmin(filled,axis=axis)
    scale=np.nanpercentile(np.abs(a[finite]),99) if finite.any() else 1.
    tol=max(1e-300,float(scale)*1e-9)
    flat=~np.isfinite(spread)|(spread<=tol)
    return (frac<min_finite)|flat


def _longest_run(valid):
    best=(0,0);start=None
    for i,v in enumerate(list(valid)+[False]):
        if v and start is None:start=i
        elif not v and start is not None:
            if i-start>best[1]-best[0]:best=(start,i)
            start=None
    return best


def detect_incomplete_scan(*arrays, min_size=8):
    """Valid-data rectangle of a partially acquired scan.

    Returns ``None`` when the scan is complete (nothing to crop), otherwise
    ``(top, bottom, left, right)`` pixel bounds (bottom/right exclusive) of the
    largest block of measured rows × columns shared by all ``arrays`` (e.g.
    forward and backward traces).  Raises ValueError when almost nothing was
    measured.
    """
    arrays=[np.asarray(a,dtype=float) for a in arrays if a is not None]
    if not arrays:raise ValueError('No data')
    shape=arrays[0].shape
    arrays=[a for a in arrays if a.shape==shape]
    ny,nx=shape
    bad_rows=np.zeros(ny,bool);bad_cols=np.zeros(nx,bool)
    for a in arrays:
        bad_rows|=_invalid_lines(a,1)
    top,bottom=_longest_run(~bad_rows)
    if bottom-top<min_size:raise ValueError('Fewer than 8 measured lines: nothing usable to keep')
    for a in arrays:
        bad_cols|=_invalid_lines(a[top:bottom],0)
    left,right=_longest_run(~bad_cols)
    if right-left<min_size:raise ValueError('Fewer than 8 measured columns: nothing usable to keep')
    if (top,bottom,left,right)==(0,ny,0,nx):return None
    return int(top),int(bottom),int(left),int(right)
