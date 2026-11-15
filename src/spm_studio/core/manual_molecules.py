"""v32 manual molecule placement: click to place, adjust, and continue a chain.

Positions are physical, in nm from the scan's top-left corner (x → right,
y → down, like the image), so they survive crops of the display and resolution
changes.  Angles are in degrees, counter-clockwise on screen.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import csv
import json
import math
import numpy as np


@dataclass
class Molecule:
    x_nm: float
    y_nm: float
    angle_deg: float = 0.0

    def moved(self, dx=0., dy=0., dangle=0.):
        return Molecule(self.x_nm + dx, self.y_nm + dy, self.angle_deg + dangle)


def chain_step(molecules, mode='last'):
    """(dx, dy, dangle) of the established chain.

    ``last``: the vector between the last two molecules.
    ``average``: the mean step along the whole chain (robust to small click errors).
    """
    if len(molecules) < 2:
        raise ValueError('Place at least two molecules to define the chain step')
    if mode == 'average':
        a, b = molecules[0], molecules[-1]
        n = len(molecules) - 1
        return ((b.x_nm - a.x_nm) / n, (b.y_nm - a.y_nm) / n, _wrap(b.angle_deg - a.angle_deg) / n)
    a, b = molecules[-2], molecules[-1]
    return (b.x_nm - a.x_nm, b.y_nm - a.y_nm, _wrap(b.angle_deg - a.angle_deg))


def _wrap(angle):
    return (angle + 180.) % 360. - 180.


def continue_chain(molecules, count, mode='last', bounds_nm=None):
    """Append ``count`` molecules following the chain pattern.

    With ``bounds_nm=(width, height)`` molecules whose centre would leave the scan
    are not added.  Returns the new list (input untouched) and how many were added.
    """
    if count < 1:
        return list(molecules), 0
    dx, dy, da = chain_step(molecules, mode)
    if math.hypot(dx, dy) < 1e-6:
        raise ValueError('The last two molecules are at the same position: no chain direction')
    out = list(molecules)
    added = 0
    for _ in range(int(count)):
        nxt = out[-1].moved(dx, dy, da)
        if bounds_nm is not None:
            w, h = bounds_nm
            if not (0 <= nxt.x_nm <= w and 0 <= nxt.y_nm <= h):
                break
        out.append(nxt)
        added += 1
    return out, added


def nm_to_px(x_nm, y_nm, shape, size_nm):
    ny, nx = shape
    return x_nm / size_nm[0] * nx - .5, y_nm / size_nm[1] * ny - .5


def px_to_nm(col, row, shape, size_nm):
    ny, nx = shape
    return (col + .5) / nx * size_nm[0], (row + .5) / ny * size_nm[1]


def content_box(rgba, *, white_tolerance=12, alpha_min=8):
    """Visible-molecule box (x0, y0, x1, y1) of an RGBA artwork array (margins ignored)."""
    a = np.asarray(rgba)
    mask = (a[..., 3] > alpha_min) & (a[..., :3].min(axis=2) < 255 - int(white_tolerance))
    if not mask.any():
        return 0, 0, a.shape[1], a.shape[0]
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def save_positions(molecules, path, *, meta=None):
    path = str(path)
    if path.lower().endswith('.csv'):
        with open(path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['index', 'x_nm', 'y_nm', 'angle_deg'])
            for i, m in enumerate(molecules, 1):
                w.writerow([i, f'{m.x_nm:.6f}', f'{m.y_nm:.6f}', f'{m.angle_deg:.4f}'])
    else:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'kind': 'spm_studio_manual_molecules', 'schema_version': 1, **(meta or {}),
                       'molecules': [asdict(m) for m in molecules]}, fh, indent=2)
    return path


def load_positions(path):
    with open(path, encoding='utf-8') as fh:
        d = json.load(fh)
    return [Molecule(float(m['x_nm']), float(m['y_nm']), float(m.get('angle_deg', 0.))) for m in d['molecules']], d
