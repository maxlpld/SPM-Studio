"""Non-destructive scan processing. Operations use finite-data masks and retain SI values.

The named native operations follow Gwyddion's *categories*, not an assertion of
bit-for-bit equivalence with Gwyddion's independently implemented algorithms.
"""
from __future__ import annotations
import numpy as np
from .models import ProcessingStep

# User-visible catalogue; all listed native commands have a working implementation.
PROCESS_GROUPS = {
    'Level': [
        ('Plane subtract', 'plane'), ('Raw median (align rows)', 'row_median'),
        ('Fix Zero (colorbar only)', 'fix_zero'), ('Zero Mean Value', 'zero_mean'),
        ('Median background', 'subtract_median'), ('Row mean', 'row_mean'),
        ('Column median', 'column_median'), ('Column mean', 'column_mean'),
        ('Line polynomial', 'line_poly'), ('2D polynomial background', 'polynomial_2d'),
    ],
    'Correct scan lines': [
        ('Scar row correction', 'median_scar'), ('Median difference rows', 'median_difference'),
        ('Median difference columns', 'median_difference_columns'),
        ('Despike', 'despike'), ('Remove stripe background', 'remove_stripes'),
    ],
    'Filters': [
        ('Gaussian smooth', 'gaussian'), ('Median filter', 'median_filter'),
        ('Mean filter', 'mean_filter'), ('Minimum filter', 'minimum_filter'),
        ('Maximum filter', 'maximum_filter'), ('Gaussian high-pass', 'highpass'),
        ('Unsharp mask', 'unsharp'), ('Difference of Gaussians', 'dog'),
        ('Laplacian', 'laplace'), ('Sobel magnitude', 'sobel'),
    ],
    'Transforms / arithmetic': [
        ('Invert sign', 'invert'), ('Absolute value', 'absolute'),
        ('Square', 'square'), ('Square root of positive values', 'sqrt'),
        ('Multiply by factor', 'multiply'), ('Add offset', 'add'),
        ('Clip limits', 'clip'), ('Threshold binary', 'threshold'),
    ],
}
DEFAULT_PARAMETERS = {
    'line_poly': {'degree': 1}, 'polynomial_2d': {'degree': 2},
    'median_scar': {'threshold': 5.0}, 'despike': {'threshold': 5.0, 'size': 3},
    'gaussian': {'sigma': 1.0}, 'median_filter': {'size': 3},
    'mean_filter': {'size': 3}, 'minimum_filter': {'size': 3},
    'maximum_filter': {'size': 3}, 'highpass': {'sigma': 5.0},
    'unsharp': {'sigma': 1.5, 'amount': 1.0},
    'dog': {'sigma': 1.0, 'sigma2': 3.0}, 'clip': {'low': 0.0, 'high': 1.0},
    'threshold': {'value': 0.0}, 'multiply': {'factor': 1.0},
    'add': {'value': 0.0}, 'remove_stripes': {'sigma': 7.0},
}
OPERATIONS = {name: op for items in PROCESS_GROUPS.values() for name, op in items}


def _finite_filter(a, callback, **params):
    """Exclude invalid pixels from local filters without filling them permanently."""
    from scipy.ndimage import gaussian_filter, uniform_filter, generic_filter
    valid = np.isfinite(a)
    if not valid.any():
        return a.copy()
    base = np.where(valid, a, 0.0)
    name = callback
    if name == 'gaussian':
        sigma = max(0.01, float(params.get('sigma', 1)))
        weight = gaussian_filter(valid.astype(float), sigma, mode='reflect')
        result = gaussian_filter(base, sigma, mode='reflect') / np.maximum(weight, 1e-12)
    elif name == 'mean':
        size = max(1, int(params.get('size', 3)))
        weight = uniform_filter(valid.astype(float), size, mode='reflect')
        result = uniform_filter(base, size, mode='reflect') / np.maximum(weight, 1e-12)
    else:
        from scipy.ndimage import median_filter, minimum_filter, maximum_filter
        size = max(1, int(params.get('size', 3)))
        if size % 2 == 0: size += 1
        filled = np.where(valid, a, float(np.nanmedian(a)))
        function = {'median':median_filter, 'minimum':minimum_filter,
                    'maximum':maximum_filter}[name]
        result = function(filled, size=size, mode='reflect')
    result[~valid] = np.nan
    return result


def apply(data: np.ndarray, steps: list[ProcessingStep] | tuple[ProcessingStep, ...]) -> np.ndarray:
    a = np.array(data, dtype=np.float64, copy=True)
    if a.ndim != 2:
        raise ValueError('Processing expects 2-D images')
    for step in steps:
        if not step.enabled or step.operation == 'none': continue
        op, p = step.operation, step.params
        valid = np.isfinite(a)
        if not valid.any(): continue
        if op == 'plane':
            yy, xx = np.indices(a.shape)
            x, y = xx[valid]/max(a.shape[1]-1,1), yy[valid]/max(a.shape[0]-1,1)
            design = np.column_stack((x, y, np.ones(x.size)))
            coeff = np.linalg.lstsq(design, a[valid], rcond=None)[0]
            a -= coeff[0]*xx/max(a.shape[1]-1,1) + coeff[1]*yy/max(a.shape[0]-1,1) + coeff[2]
        elif op in ('row_mean', 'row_median', 'line_poly', 'column_mean', 'column_median'):
            transposed = op.startswith('column_')
            target = a.T if transposed else a
            reference = float(np.nanmedian(a))
            for i in range(target.shape[0]):
                finite = np.isfinite(target[i])
                if not finite.any(): continue
                if op.endswith('_mean'):
                    correction = float(np.mean(target[i, finite]))
                    target[i, finite] -= correction-reference
                elif op.endswith('_median'):
                    correction = float(np.median(target[i, finite]))
                    target[i, finite] -= correction-reference
                else:
                    degree = min(max(int(p.get('degree',1)),0),6)
                    if finite.sum()<degree+1: continue
                    x = np.linspace(-1,1,target.shape[1])
                    baseline = np.polynomial.polynomial.polyval(x,np.polynomial.polynomial.polyfit(x[finite],target[i,finite],degree))
                    target[i,finite] -= baseline[finite]-reference
        elif op == 'polynomial_2d':
            degree = min(max(int(p.get('degree',2)),0),5)
            yy,xx=np.indices(a.shape)
            x=xx[valid]/max(a.shape[1]-1,1)*2-1
            y=yy[valid]/max(a.shape[0]-1,1)*2-1
            terms=[(i,j) for i in range(degree+1) for j in range(degree+1-i)]
            matrix=np.column_stack([x**i*y**j for i,j in terms])
            coeff=np.linalg.lstsq(matrix,a[valid],rcond=None)[0]
            xx=xx/max(a.shape[1]-1,1)*2-1; yy=yy/max(a.shape[0]-1,1)*2-1
            background=sum(c*(xx**i)*(yy**j) for c,(i,j) in zip(coeff,terms))
            a[valid]-=background[valid]
        elif op == 'three_point_plane':
            from .interactive_tools import three_point_plane_coefficients
            points=[(float(p[f'x{i}']), float(p[f'y{i}'])) for i in (1,2,3)]
            cx,cy,offset=three_point_plane_coefficients(a,points)
            yy,xx=np.indices(a.shape)
            plane=cx*xx+cy*yy+offset
            a[valid]-=plane[valid]
        elif op == 'path_plane':
            x0,y0,x1,y1=(float(p[k]) for k in ('x0','y0','x1','y1'))
            dx,dy=x1-x0,y1-y0
            den=dx*dx+dy*dy
            if den < 1e-6: raise ValueError('Path endpoints must be distinct')
            from scipy.ndimage import map_coordinates
            z0=float(map_coordinates(a,[[y0],[x0]],order=1,mode='nearest')[0])
            z1=float(map_coordinates(a,[[y1],[x1]],order=1,mode='nearest')[0])
            yy,xx=np.indices(a.shape)
            trend=(z1-z0)/den*(dx*(xx-x0)+dy*(yy-y0))
            a[valid]-=trend[valid]
        elif op == 'spot_replace':
            x,y=(int(round(float(p[k]))) for k in ('x','y'))
            radius=max(1,min(10,int(p.get('radius',2))))
            if 0 <= x < a.shape[1] and 0 <= y < a.shape[0]:
                y0,y1=max(0,y-radius),min(a.shape[0],y+radius+1)
                x0,x1=max(0,x-radius),min(a.shape[1],x+radius+1)
                patch=a[y0:y1,x0:x1].copy()
                patch[y-y0,x-x0]=np.nan
                if np.isfinite(patch).any():
                    a[y,x]=float(np.nanmedian(patch))
        elif op == 'invert': a[valid]*=-1
        elif op == 'absolute': a[valid]=np.abs(a[valid])
        elif op == 'square': a[valid]=a[valid]**2
        elif op == 'sqrt': a[valid]=np.sqrt(np.maximum(a[valid],0))
        elif op == 'multiply': a[valid]*=float(p.get('factor',1))
        elif op == 'add': a[valid]+=float(p.get('value',0))
        elif op == 'clip':
            low,high=float(p.get('low',0)),float(p.get('high',1))
            if high<=low: raise ValueError('Clip upper bound must exceed lower bound')
            a[valid]=np.clip(a[valid],low,high)
        elif op == 'threshold': a[valid]=(a[valid]>=float(p.get('value',0))).astype(float)
        elif op == 'fix_zero':
            # Studio presentation-only mode: do not subtract from the data.
            # Gwyddion's *numerical* Fix Zero is a different operation.
            pass
        elif op == 'zero_mean': a[valid]-=float(np.mean(a[valid]))
        elif op == 'subtract_median': a[valid]-=float(np.median(a[valid]))
        elif op == 'median_scar':
            med=np.nanmedian(a,axis=1)
            global_med=float(np.nanmedian(med))
            mad=float(np.nanmedian(np.abs(med-global_med)))
            threshold=float(p.get('threshold',5))*max(1.4826*mad,1e-30)
            for i in np.flatnonzero(np.abs(med-global_med)>threshold):
                mask=np.isfinite(a[i]);a[i,mask]-=med[i]-global_med
        elif op in ('median_difference', 'median_difference_columns'):
            target=a.T if op.endswith('columns') else a
            med=np.nanmedian(target,axis=1)
            for i in range(1,target.shape[0]):
                if np.isfinite(med[i]) and np.isfinite(med[i-1]):
                    mask=np.isfinite(target[i]);target[i,mask]-=med[i]-med[i-1]
        elif op == 'remove_stripes':
            from scipy.ndimage import gaussian_filter1d
            row=np.nanmedian(a,axis=1)
            row=np.where(np.isfinite(row),row,float(np.nanmedian(a)))
            baseline=gaussian_filter1d(row,max(.1,float(p.get('sigma',7))))
            a -= (row-baseline)[:,None]
        elif op in ('gaussian','mean_filter','median_filter','minimum_filter','maximum_filter'):
            mode={'gaussian':'gaussian','mean_filter':'mean','median_filter':'median',
                  'minimum_filter':'minimum','maximum_filter':'maximum'}[op]
            a=_finite_filter(a,mode,**p)
        elif op in ('highpass','unsharp','dog'):
            smooth=_finite_filter(a,'gaussian',sigma=p.get('sigma',5))
            if op=='highpass':a[valid]-=smooth[valid]
            elif op=='unsharp':a[valid]+=float(p.get('amount',1))*(a[valid]-smooth[valid])
            else:
                wide=_finite_filter(a,'gaussian',sigma=p.get('sigma2',3))
                a[valid]=smooth[valid]-wide[valid]
        elif op=='despike':
            filtered=_finite_filter(a,'median',size=p.get('size',3))
            residual=np.abs(a-filtered)
            mad=float(np.nanmedian(np.abs(residual-np.nanmedian(residual))))
            threshold=float(p.get('threshold',5))*max(1.4826*mad,1e-30)
            replace=valid&(residual>threshold)
            a[replace]=filtered[replace]
        elif op in ('laplace','sobel'):
            from scipy.ndimage import laplace, sobel
            filled=np.where(valid,a,float(np.nanmedian(a)))
            if op=='laplace': result=laplace(filled)
            else: result=np.hypot(sobel(filled,axis=0),sobel(filled,axis=1))
            a[valid]=result[valid]
        else: raise ValueError(f'Unknown processing operation {op!r}')
    return a


def display_zero_enabled(steps) -> bool:
    """Whether a non-destructive legend-zero action is enabled for this channel."""
    return any(getattr(step, 'operation', '') == 'fix_zero' and
               getattr(step, 'enabled', True) for step in (steps or ()))


def display_bounds(lo: float, hi: float, steps) -> tuple[float, float]:
    """Legend values only; the pixel-to-colour mapping retains original lo/hi."""
    if display_zero_enabled(steps):
        return 0.0, float(hi) - float(lo)
    return float(lo), float(hi)
