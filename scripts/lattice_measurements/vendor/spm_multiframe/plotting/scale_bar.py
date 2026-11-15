from __future__ import annotations

import math
from matplotlib.axes import Axes

def nice_scale_length_nm(width_nm: float, fraction: float = 0.25) -> float:
    """Choose 1, 2 or 5 x 10^n near 25% width; never exceed 35%."""
    if not math.isfinite(width_nm) or width_nm <= 0:
        raise ValueError('width_nm must be positive and finite')
    target=width_nm*fraction
    exponent=math.floor(math.log10(target))
    candidates=[base*10.0**p for p in range(exponent-2,exponent+2)
                for base in (1.0,2.0,5.0)]
    valid=[v for v in candidates if v>0 and v<=width_nm*0.35]
    return min(valid,key=lambda v:(abs(math.log(v/target)),-v)) if valid else target

def add_scale_bar(ax: Axes, *, length_nm: float | None = None, color: str = 'black',
                  linewidth: float = 2.2, location: str = 'lower right',
                  margin_fraction: float = 0.06) -> float:
    xmin,xmax=ax.get_xlim();ymin,ymax=ax.get_ylim()
    width=abs(xmax-xmin);height=abs(ymax-ymin)
    length=nice_scale_length_nm(width) if length_nm is None else float(length_nm)
    if location not in ('lower right','lower left','upper right','upper left'):
        raise ValueError('Invalid scale-bar corner')
    left=location.endswith('left'); top=location.startswith('upper')
    margin=margin_fraction*width
    x0=min(xmin,xmax)+margin if left else max(xmin,xmax)-margin-length
    yt=min(ymin,ymax); yb=max(ymin,ymax)
    y0=yb-margin_fraction*height if top else yt+margin_fraction*height
    tick=.03*height
    ax.plot([x0,x0+length],[y0,y0],color=color,lw=linewidth,solid_capstyle='butt')
    for x in (x0,x0+length):
        ax.plot([x,x],[y0-tick/2,y0+tick/2],color=color,lw=linewidth,solid_capstyle='butt')
    label=f'{length:g} nm' if length>=.1 else f'{length*1000:g} pm'
    label_y=y0-.045*height if top else y0+.045*height
    ax.text(x0+length/2,label_y,label,color=color,ha='center',
            va='top' if top else 'bottom')
    return length
