"""3D print plates (v0.0.15): one or several scan panels, crisp text, magnets, STL / STEP / 3MF (Qt-free).

Compared with the single height field of ``print3d.build_model`` (kept unchanged), a plate is made of separate
closed solids that slightly overlap (slicers merge them):

* **plate**: a box (or, for a fridge magnet, a box over a lower slab with four round pockets);
* **relief** of each panel: a smooth height field at the chosen quality, standing on the plate;
* **3D colour bar** of each panel: an exact wedge (low value = plate height, high value = full relief);
* **labels**: every text, tick and scale bar, drawn from vector font outlines (bold) and extruded on a fine
  grid (0.05 mm by default) with vertical walls, so letters stay sharp and printable.

The layout is computed from the exact size of every text, then the plate gets equal margins on all four sides:
the content is centred whatever the title / colour-bar options.
"""
from __future__ import annotations

import json
import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import print3d as P

QUALITY = {'draft': 0.35, 'standard': 0.20, 'fine': 0.12}      # relief grid (mm)
LAYOUTS = {
    'single': ('One channel', [(0, 0)]),
    'row2': ('Two side by side', [(0, 0), (0, 1)]),
    'col2': ('Two stacked', [(0, 0), (1, 0)]),
    'row3': ('Three in a row', [(0, 0), (0, 1), (0, 2)]),
    'triangle3': ('Three as a triangle', [(0, 0), (0, 1), (1, 0.5)]),
    'grid4': ('Four (2 × 2)', [(0, 0), (0, 1), (1, 0), (1, 1)]),
    'row4': ('Four in a row', [(0, 0), (0, 1), (0, 2), (0, 3)]),
    'custom': ('Custom grid (rows × columns)', None),
}
DEFAULTS = dict(P.DEFAULTS)
DEFAULTS.update({
    'quality': 'standard', 'resolution_mm': QUALITY['standard'], 'text_resolution_mm': 0.05,
    'font_mm': 5.0, 'label_mm': 1.0, 'margin_mm': 5.0, 'panel_gap_mm': 8.0,
    'layout': 'single', 'layout_rows': 1, 'layout_cols': 1,
    'channel_titles': True, 'main_title': '', 'base_color': '#F2F2F2',
    'background_color': '#FFFFFF', 'text_color': '#000000', 'nozzle_mm': 0.4,
    'magnets': False, 'magnet_radius_mm': 5.1, 'magnet_depth_mm': 2.0, 'magnet_inset_mm': 3.0,
})
OVERLAP = 0.05                 # solids sink this much into the plate so that slicers merge them
MIN_FLOOR = 0.8                # plate left above a magnet pocket
TEXT_FONT = {'family': 'DejaVu Sans', 'weight': 'bold'}


@dataclass
class Panel:
    """One scan on the plate."""
    data: np.ndarray
    size_nm: tuple | None
    unit: str = ''
    factor: float = 1.0                        # data unit → displayed unit
    title: str = ''                            # channel name shown above the panel (if enabled)
    overlay: P.Overlay | None = None
    colors: tuple = ('#1D3F8F', '#F5C342')     # 3MF gradient: lowest → highest
    range: dict = field(default_factory=dict)  # per-panel range overrides ('range_mode', 'low', 'high', 'invert')
    zero_reference: bool = False               # Fix Zero: colour-bar labels start at 0 (values − low)


@dataclass
class Body:
    name: str
    verts: np.ndarray
    faces: np.ndarray
    part: str                                   # 3MF part this solid belongs to
    color: str = '#F2F2F2'
    grid: dict | None = None                    # height field source (lets STEP use a lighter grid)


@dataclass
class Plate:
    bodies: list
    size_mm: tuple
    params: dict
    panels: list                                # per panel: {'title','low','high','unit','factor','box','bar','colors'}
    notes: list
    preview: tuple                              # (z grid, cell) for the live 3D preview
    preview_rgb: np.ndarray | None = None       # colours of the preview grid (plate, labels, gradients)

    @property
    def triangles(self) -> int:
        return int(sum(len(b.faces) for b in self.bodies))

    def parts(self) -> dict:
        out = {}
        for b in self.bodies:
            out.setdefault(b.part, []).append(b)
        return out


# ====================================================================== geometry: closed solids
class _Mesh:
    def __init__(self):
        self.index = {}
        self.verts = []
        self.faces = []

    def v(self, key, xyz):
        i = self.index.get(key)
        if i is None:
            i = self.index[key] = len(self.verts)
            self.verts.append(xyz)
        return i

    def arrays(self):
        return np.asarray(self.verts, float).reshape(-1, 3), np.asarray(self.faces, np.int64).reshape(-1, 3)


def box_body(x0, y0, x1, y1, z0, z1):
    """Closed axis-aligned box (mesh coordinates, y up)."""
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                  [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], np.int64)
    return v, f


def wedge_body(x0, y0, x1, y1, zb, z_lo, z_hi, axis):
    """Box whose top rises linearly from z_lo to z_hi along +x (axis='x') or +y (axis='y')."""
    v, f = box_body(x0, y0, x1, y1, zb, 1.0)
    top = v[:, 2] == 1.0
    t = (v[:, 0] - x0) / (x1 - x0) if axis == 'x' else (v[:, 1] - y0) / (y1 - y0)
    v[top, 2] = z_lo + (z_hi - z_lo) * t[top]
    return v, f


def heightfield_body(zgrid, x0, y_top, dx, dy, zb):
    """Closed solid under a height field sampled at grid *points* (rows from the top); flat bottom at zb.

    The flat bottom only uses the outline vertices (a fan around its centre), so the file holds the detail
    where it is visible: on the top surface.
    """
    zgrid = np.asarray(zgrid, float)
    rows, cols = zgrid.shape
    x = x0 + np.arange(cols) * dx
    y = y_top - np.arange(rows) * dy
    X, Y = np.meshgrid(x, y)
    top = np.column_stack([X.ravel(), Y.ravel(), zgrid.ravel()])
    idx = np.arange(rows * cols).reshape(rows, cols)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    faces = [np.column_stack([a, d, c]), np.column_stack([a, c, b])]
    # outline, clockwise seen from above: top row →, right column ↓, bottom row ←, left column ↑
    ring = np.concatenate([idx[0, :], idx[1:, -1], idx[-1, -2::-1], idx[-2:0:-1, 0]])
    n_top = len(top)
    bottom = top[ring].copy()
    bottom[:, 2] = zb
    centre = np.array([[x.mean(), y.mean(), zb]])
    verts = np.vstack([top, bottom, centre])
    b_idx = n_top + np.arange(len(ring))
    nxt = np.roll(b_idx, -1)
    centre_i = n_top + len(ring)
    faces.append(np.column_stack([np.full(len(ring), centre_i), b_idx, nxt]))      # bottom, normal −z
    t_idx, t_nxt = ring, np.roll(ring, -1)
    faces.append(np.column_stack([t_idx, nxt, b_idx]))                              # walls, outward
    faces.append(np.column_stack([t_idx, t_nxt, nxt]))
    return verts, np.vstack(faces).astype(np.int64)


def _no_diagonal_contacts(mask):
    """Fill one cell of every 2×2 checkerboard so the extruded solid is a proper 2-manifold."""
    m = mask.copy()
    for _ in range(4):
        a, b, c, d = m[:-1, :-1], m[:-1, 1:], m[1:, :-1], m[1:, 1:]
        bad1 = a & d & ~b & ~c
        bad2 = b & c & ~a & ~d
        if not (bad1.any() or bad2.any()):
            break
        r, cc = np.nonzero(bad1)
        m[r, cc + 1] = True
        r, cc = np.nonzero(bad2)
        m[r, cc] = True
    return m


def mask_body(mask, res, x0, y_top, z0, z1):
    """Watertight extrusion of a boolean mask (rows from the top) between z0 and z1.

    Rows are merged into runs; every edge is split at the breakpoints of both neighbouring rows, so faces,
    walls and neighbours share exactly the same edges (no T-junctions, no cracks).
    """
    m = _no_diagonal_contacts(np.asarray(mask, bool))
    rows, cols = m.shape
    pad = np.zeros((rows + 2, cols + 2), np.int8)
    pad[1:-1, 1:-1] = m
    runs = []
    for r in range(rows):
        d = np.diff(pad[r + 1])
        runs.append(list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))))
    breaks = []
    for line in range(rows + 1):
        s = set()
        for rr in (line - 1, line):
            if 0 <= rr < rows:
                for a, b in runs[rr]:
                    s.add(int(a))
                    s.add(int(b))
        breaks.append(np.array(sorted(s), int))
    mesh = _Mesh()

    def V(xi, line, level):
        return mesh.v((xi, line, level), (x0 + xi * res, y_top - line * res, z1 if level else z0))

    def filled(r, x0i, x1i):
        if not 0 <= r < rows:
            return False
        return bool(m[r, (x0i + x1i) // 2]) if x1i - x0i > 1 else bool(m[r, x0i])
    for r in range(rows):
        top_line, bot_line = breaks[r], breaks[r + 1]
        for s, e in runs[r]:
            A = top_line[(top_line >= s) & (top_line <= e)]
            B = bot_line[(bot_line >= s) & (bot_line <= e)]
            i = j = 0
            while i < len(A) - 1 or j < len(B) - 1:
                if i < len(A) - 1 and (j == len(B) - 1 or A[i + 1] <= B[j + 1]):
                    tri = (V(A[i], r, 1), V(B[j], r + 1, 1), V(A[i + 1], r, 1))
                    low = (V(A[i], r, 0), V(A[i + 1], r, 0), V(B[j], r + 1, 0))
                    i += 1
                else:
                    tri = (V(A[i], r, 1), V(B[j], r + 1, 1), V(B[j + 1], r + 1, 1))
                    low = (V(A[i], r, 0), V(B[j + 1], r + 1, 0), V(B[j], r + 1, 0))
                    j += 1
                mesh.faces.append(tri)
                mesh.faces.append(low)
            # end walls of the run (normal −x at s, +x at e)
            mesh.faces += [(V(s, r, 0), V(s, r + 1, 0), V(s, r + 1, 1)), (V(s, r, 0), V(s, r + 1, 1), V(s, r, 1)),
                           (V(e, r, 0), V(e, r + 1, 1), V(e, r + 1, 0)), (V(e, r, 0), V(e, r, 1), V(e, r + 1, 1))]
    for line in range(rows + 1):
        bp = breaks[line]
        for k in range(len(bp) - 1):
            xa, xb = int(bp[k]), int(bp[k + 1])
            above, below = filled(line - 1, xa, xb), filled(line, xa, xb)
            if above == below:
                continue
            p1, p2, p3, p4 = V(xa, line, 0), V(xb, line, 0), V(xb, line, 1), V(xa, line, 1)
            if below:          # solid below the line → outward normal +y
                mesh.faces += [(p1, p3, p2), (p1, p4, p3)]
            else:              # solid above → outward −y
                mesh.faces += [(p1, p2, p3), (p1, p3, p4)]
    return mesh.arrays()


def edge_report(faces):
    """(edges used once, edges used more than twice) — both 0 for a closed 2-manifold."""
    f = np.asarray(faces)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    key = np.sort(e, axis=1)
    _u, counts = np.unique(key, axis=0, return_counts=True)
    return int((counts == 1).sum()), int((counts > 2).sum())


# ====================================================================== text (vector outlines)
def _text_path(text, size, ha='left', va='baseline', x=0.0, y=0.0, angle=0.0):
    """Matplotlib TextPath in plate coordinates (mm, y down), aligned like ax.text."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    from matplotlib.transforms import Affine2D
    path = TextPath((0, 0), str(text), size=size, prop=FontProperties(**TEXT_FONT))
    ext = path.get_extents()
    dx = {'left': -ext.x0, 'center': -(ext.x0 + ext.x1) / 2, 'right': -ext.x1}[ha]
    dy = {'baseline': 0.0, 'bottom': -ext.y0, 'center': -(ext.y0 + ext.y1) / 2, 'top': -ext.y1}[va]
    t = Affine2D().translate(dx, dy).scale(1, -1).rotate_deg(-angle).translate(x, y)
    return path.transformed(t)


def text_size(text, size):
    """(width, height) in mm of a text drawn with TEXT_FONT."""
    if not str(text):
        return 0.0, 0.0
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    ext = TextPath((0, 0), str(text), size=size, prop=FontProperties(**TEXT_FONT)).get_extents()
    return float(ext.width), float(ext.height)


class _Drawing:
    """Shapes on the plate (mm, y down from the top-left corner), rasterised once at the text resolution."""

    def __init__(self):
        self.items = []           # ('path', Path) | ('rect', x, y, w, h) | ('line', x0, y0, x1, y1, width)

    def text(self, *a, **k):
        self.items.append(('path', _text_path(*a, **k)))

    def rect(self, x, y, w, h):
        self.items.append(('rect', x, y, w, h))

    def line(self, x0, y0, x1, y1, width):
        self.items.append(('line', x0, y0, x1, y1, width))

    def bbox(self):
        boxes = []
        for item in self.items:
            if item[0] == 'path':
                e = item[1].get_extents()
                boxes.append((e.x0, e.y0, e.x1, e.y1))
            elif item[0] == 'rect':
                _k, x, y, w, h = item
                boxes.append((x, y, x + w, y + h))
            else:
                _k, x0, y0, x1, y1, w = item
                boxes.append((min(x0, x1) - w / 2, min(y0, y1) - w / 2, max(x0, x1) + w / 2, max(y0, y1) + w / 2))
        return boxes

    def raster(self, W, H, res, shift=(0.0, 0.0)):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.patches import PathPatch, Rectangle
        from matplotlib.transforms import Affine2D
        cols, rows = int(math.ceil(W / res)), int(math.ceil(H / res))
        dpi = 100.0
        fig = Figure(figsize=(cols / dpi, rows / dpi), dpi=dpi)
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, cols * res)
        ax.set_ylim(rows * res, 0)
        ax.set_axis_off()
        fig.patch.set_alpha(0)
        move = Affine2D().translate(*shift)
        for item in self.items:
            if item[0] == 'path':
                ax.add_patch(PathPatch(item[1].transformed(move), facecolor='k', edgecolor='none', lw=0))
            elif item[0] == 'rect':
                _k, x, y, w, h = item
                ax.add_patch(Rectangle((x + shift[0], y + shift[1]), w, h, facecolor='k', edgecolor='none', lw=0))
            else:
                _k, x0, y0, x1, y1, w = item
                if abs(x1 - x0) >= abs(y1 - y0):
                    ax.add_patch(Rectangle((min(x0, x1) + shift[0], y0 - w / 2 + shift[1]), abs(x1 - x0), w,
                                           facecolor='k', lw=0))
                else:
                    ax.add_patch(Rectangle((x0 - w / 2 + shift[0], min(y0, y1) + shift[1]), w, abs(y1 - y0),
                                           facecolor='k', lw=0))
        fig.canvas.draw()
        alpha = np.asarray(fig.canvas.buffer_rgba())[..., 3]
        return alpha[:rows, :cols] > 127


# ====================================================================== layout
def slots(params, n):
    key = params.get('layout', 'single')
    if key == 'custom':
        r, c = max(1, int(params.get('layout_rows', 1))), max(1, int(params.get('layout_cols', 1)))
        return [(i // c, i % c) for i in range(min(n, r * c))]
    return list(LAYOUTS.get(key, LAYOUTS['single'])[1])[:n]


def panel_count(params) -> int:
    key = params.get('layout', 'single')
    if key == 'custom':
        return max(1, int(params.get('layout_rows', 1))) * max(1, int(params.get('layout_cols', 1)))
    return len(LAYOUTS.get(key, LAYOUTS['single'])[1])


def _ticks(lo, hi, factor, n, zero=False):
    """(fraction, label) of the colour-bar ticks; zero=True labels them from 0 (Fix Zero)."""
    if zero:
        lo, hi = 0.0, hi - lo
    step = (hi - lo) * factor / (n - 1)
    decimals = max(0, int(-math.floor(math.log10(abs(step)))) + 1) if step else 0
    out = []
    for k in range(n):
        f = k / (n - 1)
        value = (lo + f * (hi - lo)) * factor
        if abs(value) < abs(step) * 1e-3:
            value = 0.0
        out.append((f, f'{value:.{decimals}f}'))
    return out


def _panel_layout(p, panel, lo, hi):
    """Geometry of one panel relative to its image's top-left corner + its drawing; returns the content box."""
    a = np.asarray(panel.data)
    wn, hn = (float(panel.size_nm[0]), float(panel.size_nm[1])) if panel.size_nm else (a.shape[1], a.shape[0])
    iw = float(p['width_mm'])
    ih = iw * hn / wn
    font = float(p['font_mm'])
    small = font * .8
    pos = p.get('colorbar', 'right')
    bw, gap = float(p['colorbar_width_mm']), float(p['colorbar_gap_mm'])
    rng = {**p, **panel.range}
    draw = _Drawing()
    stroke = max(0.8, font * .16, 2 * float(p.get('nozzle_mm', .4)))   # ≥ 2 nozzle widths
    bar = None
    ticks = _ticks(lo, hi, panel.factor, max(2, int(p.get('colorbar_ticks', 5))),
                   bool(getattr(panel, 'zero_reference', False))) if pos != 'none' else []
    invert = bool(rng.get('invert'))
    if pos in ('right', 'left'):
        bx = iw + gap if pos == 'right' else -gap - bw
        bar = (bx, 0.0, bw, ih)
        for f, label in ticks:
            yy = ih * (1 - f) if not invert else ih * f
            if pos == 'right':
                draw.line(bx + bw, yy, bx + bw + font * .45, yy, stroke)
                draw.text(label, small, ha='left', va='center', x=bx + bw + font * .7, y=yy)
            else:
                draw.line(bx - font * .45, yy, bx, yy, stroke)
                draw.text(label, small, ha='right', va='center', x=bx - font * .7, y=yy)
        if panel.unit:
            draw.text(panel.unit, small, ha='center', va='bottom', x=bx + bw / 2, y=-font * .5)
    elif pos in ('top', 'bottom'):
        by = -gap - bw if pos == 'top' else ih + gap
        bar = (0.0, by, iw, bw)
        for f, label in ticks:
            xx = iw * f if not invert else iw * (1 - f)
            if pos == 'bottom':
                draw.line(xx, by + bw, xx, by + bw + font * .4, stroke)
                draw.text(label, small, ha='center', va='top', x=xx, y=by + bw + font * .6)
            else:
                draw.line(xx, by - font * .4, xx, by, stroke)
                draw.text(label, small, ha='center', va='bottom', x=xx, y=by - font * .6)
        if panel.unit:
            draw.text(panel.unit, small, ha='left', va='center', x=iw + font * .6, y=by + bw / 2)
    # scale bar + lattice legend under the image (or under a bottom colour bar)
    below = ih + font * .7
    if pos == 'bottom':
        below = ih + gap + bw + font * 2.4
    if p.get('scale_bar', True) and wn > 0:
        length_nm = P.nice_number(wn * .25)
        L = length_nm / (wn / iw)
        thick = max(stroke, font * .3)
        draw.rect(iw - L, below, L, thick)
        label = f'{length_nm:g} nm' if length_nm >= 1 else f'{length_nm * 1000:g} pm'
        draw.text(label, small, ha='right', va='center', x=iw - L - font * .6, y=below + thick / 2)
        below += thick + font * .9
    if panel.overlay is not None and panel.overlay.legend:
        draw.text('   '.join(panel.overlay.legend), small, ha='left', va='top', x=0.0, y=below)
    title = panel.title.strip() if p.get('channel_titles', True) else ''
    if title:
        top = 0.0
        if pos == 'top':
            top = -gap - bw - font * 1.6
        elif pos in ('left', 'right') and panel.unit:
            top = -font * 1.5
        draw.text(title, font, ha='center', va='bottom', x=iw / 2, y=top - font * .5)
    boxes = draw.bbox() + [(0.0, 0.0, iw, ih)] + ([(bar[0], bar[1], bar[0] + bar[2], bar[1] + bar[3])] if bar else [])
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return {'iw': iw, 'ih': ih, 'bar': bar, 'draw': draw, 'box': (x0, y0, x1, y1), 'size_nm': (wn, hn)}


# ====================================================================== plate
def build_plate(panels: list, params: dict | None = None, preview_cell: float | None = None) -> Plate:
    p = dict(DEFAULTS)
    p.update(params or {})
    if not panels:
        raise ValueError('No channel to print')
    if p.get('quality') in QUALITY and 'resolution_mm' not in (params or {}):
        p['resolution_mm'] = QUALITY[p['quality']]
    cell = float(p['resolution_mm'])
    if not 0.04 <= cell <= 2:
        raise ValueError('Relief resolution must be between 0.04 and 2 mm')
    notes = []
    base, relief = float(p['base_mm']), float(p['relief_mm'])
    if p.get('magnets'):
        need = float(p['magnet_depth_mm']) + MIN_FLOOR
        if base < need:
            notes.append(f'Plate thickened from {base:.1f} to {need:.1f} mm to hold the magnet pockets')
            base = need
    if base < .4 or relief <= 0:
        raise ValueError('Base must be ≥ 0.4 mm and the relief > 0 mm')
    p['base_mm'] = base
    # ---- panels, their own layout, ranges
    infos = []
    for panel in panels:
        a = np.asarray(panel.data, float)
        if a.ndim != 2 or min(a.shape) < 2:
            raise ValueError('A 2-D scan channel is needed for every panel')
        rng = {**p, **panel.range}
        lo, hi = P.value_range(a, rng)
        infos.append((panel, lo, hi, _panel_layout(p, panel, lo, hi)))
    grid = slots(p, len(infos))
    if len(grid) < len(infos):
        infos = infos[:len(grid)]
        notes.append('More channels than places in the layout: the extra ones are not printed')
    cw = max(info[3]['box'][2] - info[3]['box'][0] for info in infos)
    ch = max(info[3]['box'][3] - info[3]['box'][1] for info in infos)
    gapp = float(p['panel_gap_mm'])
    font = float(p['font_mm'])
    draw = _Drawing()
    title = str(p.get('main_title', '') or '').strip()
    offset_y = 0.0
    if title:
        tw, th = text_size(title, font * 1.4)
        offset_y = th + font * 1.0
    n_cols = max(c for _r, c in grid) + 1 if grid else 1
    placed = []
    for (r, c), (panel, lo, hi, lay) in zip(grid, infos):
        bx0, by0, bx1, by1 = lay['box']
        cx = c * (cw + gapp) + (cw - (bx1 - bx0)) / 2       # centre the panel in its cell
        cy = offset_y + r * (ch + gapp) + (ch - (by1 - by0)) / 2
        ox, oy = cx - bx0, cy - by0                          # image top-left on the drawing
        for item in lay['draw'].items:
            draw.items.append(_shift(item, ox, oy))
        placed.append((panel, lo, hi, lay, ox, oy))
    content_w = n_cols * cw + (n_cols - 1) * gapp
    if title:
        draw.text(title, font * 1.4, ha='center', va='top', x=content_w / 2, y=0.0)
    boxes = draw.bbox()
    for panel, lo, hi, lay, ox, oy in placed:
        boxes.append((ox, oy, ox + lay['iw'], oy + lay['ih']))
        if lay['bar']:
            b = lay['bar']
            boxes.append((ox + b[0], oy + b[1], ox + b[0] + b[2], oy + b[1] + b[3]))
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    m = float(p['margin_mm'])
    if p.get('magnets'):
        m = max(m, 2 * float(p['magnet_radius_mm']) + 2 * float(p['magnet_inset_mm']) - 2)
    W, H = (x1 - x0) + 2 * m, (y1 - y0) + 2 * m
    sx, sy = m - x0, m - y0                                  # drawing → plate coordinates (equal margins)

    def mesh_y(y):                                           # plate y (down) → mesh y (up)
        return H - y
    bodies = []
    if params and 'base_color' in params and 'background_color' not in params:
        p['background_color'] = params['base_color']          # v0.0.15 name of the plate colour
    base_color = str(p.get('background_color') or '#FFFFFF')
    text_color = str(p.get('text_color') or '#000000')
    nozzle = float(p.get('nozzle_mm', .4))
    if font < 10 * nozzle:
        notes.append(f'Text {font:g} mm is small for a {nozzle:g} mm nozzle (≥ {10 * nozzle:g} mm recommended)')
    # ---- plate (with magnet pockets: lower slab with round holes + upper slab)
    if p.get('magnets'):
        depth, rad, inset = float(p['magnet_depth_mm']), float(p['magnet_radius_mm']), float(p['magnet_inset_mm'])
        pocket_res = min(.2, max(.08, float(p.get('text_resolution_mm', .05))))
        cols = max(2, int(round(W / pocket_res)))
        res = W / cols
        rows = max(2, int(round(H / res)))
        yy, xx = np.mgrid[0:rows, 0:cols]
        X, Y = (xx + .5) * res, (yy + .5) * res
        mask = np.ones((rows, cols), bool)
        centres = [(inset + rad, inset + rad), (W - inset - rad, inset + rad), (inset + rad, H - inset - rad),
                   (W - inset - rad, H - inset - rad)]
        for cx, cy in centres:
            mask &= (X - cx) ** 2 + (Y - cy) ** 2 > rad ** 2
        v, f = mask_body(mask, res, 0.0, H, 0.0, depth)
        bodies.append(Body('plate lower slab (magnet pockets)', v, f, 'Plate', base_color))
        v, f = box_body(0, 0, W, H, depth - OVERLAP, base)
        bodies.append(Body('plate', v, f, 'Plate', base_color))
        notes.append(f'Fridge magnet: 4 pockets Ø {2 * rad:.1f} mm, {depth:.1f} mm deep, under the corners')
    else:
        v, f = box_body(0, 0, W, H, 0.0, base)
        bodies.append(Body('plate', v, f, 'Plate', base_color))
    # ---- reliefs and 3D colour bars
    panel_info = []
    for k, (panel, lo, hi, lay, ox, oy) in enumerate(placed):
        part = f'Panel {k + 1}' + (f' — {panel.title.strip()}' if panel.title.strip() else '')
        rng = {**p, **panel.range}
        iw, ih = lay['iw'], lay['ih']
        nx, ny = max(2, int(round(iw / cell)) + 1), max(2, int(round(ih / cell)) + 1)
        a = np.asarray(panel.data, float)
        src = a
        if float(p.get('smooth_px', 0) or 0) > 0:
            from scipy.ndimage import gaussian_filter
            src = gaussian_filter(np.where(np.isfinite(a), a, np.nanmedian(a)), float(p['smooth_px']))
        values = P._resample(src, (ny, nx))
        t = np.clip((values - lo) / (hi - lo), 0, 1)
        if rng.get('invert'):
            t = 1 - t
        clipped = float(np.mean((values < lo) | (values > hi)))
        if clipped > .002:
            notes.append(f'{part}: {clipped * 100:.1f} % outside the colour-bar range (printed flat)')
        z = base + relief * t
        if panel.overlay is not None and (panel.overlay.vectors or panel.overlay.molecules):
            ov = P.Overlay(**{**panel.overlay.__dict__, 'legend': []})
            _plate, rmask = P._annotation_masks({**p, 'title': '', 'scale_bar': False, 'colorbar': 'none'},
                                                (iw, ih), (ny, nx), iw / (nx - 1), (0, 0, iw, ih), None, lo, hi,
                                                lay['size_nm'], ov)
            if rmask is not None:
                z = z + float(p['overlay_mm']) * rmask
        px, py = ox + sx, oy + sy
        grid = {'z': z, 'x0': px, 'y_top': mesh_y(py), 'dx': iw / (nx - 1), 'dy': ih / (ny - 1), 'zb': base - OVERLAP}
        v, f = heightfield_body(z, px, mesh_y(py), iw / (nx - 1), ih / (ny - 1), base - OVERLAP)
        bodies.append(Body(f'relief {k + 1}', v, f, part, panel.colors[0], grid))
        bar = None
        if lay['bar']:
            b = lay['bar']
            bx0, by0 = px + b[0], py + b[1]
            bar = (bx0, by0, b[2], b[3])
            lo_z, hi_z = (base + relief, base) if rng.get('invert') else (base, base + relief)
            if p['colorbar'] in ('left', 'right'):          # low value at the bottom of the bar
                v, f = wedge_body(bx0, mesh_y(by0 + b[3]), bx0 + b[2], mesh_y(by0), base - OVERLAP, lo_z, hi_z, 'y')
            else:
                v, f = wedge_body(bx0, mesh_y(by0 + b[3]), bx0 + b[2], mesh_y(by0), base - OVERLAP, lo_z, hi_z, 'x')
            bodies.append(Body(f'3D colour bar {k + 1}', v, f, part, panel.colors[0]))
        panel_info.append({'title': panel.title.strip(), 'low': lo, 'high': hi, 'unit': panel.unit,
                           'factor': panel.factor, 'box': (px, py, iw, ih), 'bar': bar, 'part': part,
                           'colors': tuple(panel.colors), 'zero_reference': bool(panel.zero_reference)})
    # ---- labels: every text / tick / scale bar, sharp
    tres = float(p.get('text_resolution_mm', .05))
    tres = max(tres, math.sqrt(W * H / 14e6))                 # keep the raster below ~14 M pixels
    label_mask = draw.raster(W, H, tres, shift=(sx, sy))
    if label_mask.any():
        v, f = mask_body(label_mask, tres, 0.0, H, base - OVERLAP, base + float(p['label_mm']))
        bodies.append(Body('labels', v, f, 'Labels', text_color))
    preview, rgb = _preview_grid(W, H, base, relief, bodies, label_mask, tres, panel_info, p, preview_cell)
    return Plate(bodies, (W, H), p, panel_info, notes, preview, rgb)


def _shift(item, dx, dy):
    from matplotlib.transforms import Affine2D
    if item[0] == 'path':
        return ('path', item[1].transformed(Affine2D().translate(dx, dy)))
    if item[0] == 'rect':
        _k, x, y, w, h = item
        return ('rect', x + dx, y + dy, w, h)
    _k, x0, y0, x1, y1, w = item
    return ('line', x0 + dx, y0 + dy, x1 + dx, y1 + dy, w)


PREVIEW_CELLS = 260      # preview grid along the long side of the plate


def _preview_grid(W, H, base, relief, bodies, label_mask, tres, panels, p, cell=None):
    """Height field of the whole plate for the 3D preview (top surface) and its print colours.

    Reliefs are sampled exactly from their own height grid; texts are averaged from the fine label raster, so
    their edges are smooth instead of blocky.
    """
    cell = cell or max(W, H) / PREVIEW_CELLS
    cols, rows = max(2, int(round(W / cell))), max(2, int(round(H / cell)))
    z = np.full((rows, cols), float(base))
    cover = np.zeros((rows, cols))               # label coverage 0…1
    kind = np.zeros((rows, cols), int)          # 0 plate / labels, 2 + k panel k
    if label_mask.any():
        from scipy.ndimage import zoom
        k = max(1, int(round(cell / tres)))
        r2, c2 = label_mask.shape[0] // k * k, label_mask.shape[1] // k * k
        if r2 and c2:
            pooled = label_mask[:r2, :c2].reshape(r2 // k, k, c2 // k, k).mean(axis=(1, 3))
            pooled = np.clip(zoom(pooled, (rows / pooled.shape[0], cols / pooled.shape[1]), order=1), 0, 1)
            cover[:pooled.shape[0], :pooled.shape[1]] = pooled[:rows, :cols]
            z += float(p['label_mm']) * cover
    gx = (np.arange(cols) + .5) * cell
    gy = H - (np.arange(rows) + .5) * cell              # mesh y of every preview row
    for body in bodies:
        if not body.name.startswith(('relief', '3D colour bar')):
            continue
        k = int(body.name.split()[-1]) - 1 if body.name.split()[-1].isdigit() else 0
        g = body.grid
        if g is not None:
            zz = np.asarray(g['z'], float)
            fx = (gx - g['x0']) / g['dx']
            fy = (g['y_top'] - gy) / g['dy']
            cs = np.flatnonzero((fx >= 0) & (fx <= zz.shape[1] - 1))
            rs = np.flatnonzero((fy >= 0) & (fy <= zz.shape[0] - 1))
            if not len(cs) or not len(rs):
                continue
            from scipy.ndimage import map_coordinates
            FY, FX = np.meshgrid(fy[rs], fx[cs], indexing='ij')
            vals = map_coordinates(zz, [FY.ravel(), FX.ravel()], order=1, mode='nearest').reshape(FY.shape)
        else:                                   # wedge: plane through its top corners
            v = body.verts
            top = v[v[:, 2] > base - OVERLAP / 2]
            if len(top) < 3:
                continue
            cs = np.flatnonzero((gx >= top[:, 0].min()) & (gx <= top[:, 0].max()))
            rs = np.flatnonzero((gy >= top[:, 1].min()) & (gy <= top[:, 1].max()))
            if not len(cs) or not len(rs):
                continue
            A = np.column_stack([top[:, 0], top[:, 1], np.ones(len(top))])
            coef = np.linalg.lstsq(A, top[:, 2], rcond=None)[0]
            GX, GY = np.meshgrid(gx[cs], gy[rs])
            vals = coef[0] * GX + coef[1] * GY + coef[2]
        block = z[np.ix_(rs, cs)]
        higher = vals >= block - 1e-9
        z[np.ix_(rs, cs)] = np.maximum(block, vals)
        kb = kind[np.ix_(rs, cs)]
        kb[higher] = 2 + k
        kind[np.ix_(rs, cs)] = kb
        cb = cover[np.ix_(rs, cs)]
        cb[higher] = 0
        cover[np.ix_(rs, cs)] = cb

    def c(hexa):
        h = str(hexa).lstrip('#')
        return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]) if len(h) >= 6 else np.array([.8, .8, .8])
    back, text = c(p.get('background_color', '#FFFFFF')), c(p.get('text_color', '#000000'))
    rgb = back[None, None, :] * (1 - cover[..., None]) + text[None, None, :] * cover[..., None]
    t = np.clip((z - base) / max(relief, 1e-9), 0, 1)
    for k, info in enumerate(panels):
        m = kind == 2 + k
        if m.any():
            lo, hi = c(info['colors'][0]), c(info['colors'][1])
            rgb[m] = lo[None, :] * (1 - t[m, None]) + hi[None, :] * t[m, None]
    return (z, cell), rgb


# ====================================================================== writers
def merged(bodies):
    verts, faces, offset = [], [], 0
    for b in bodies:
        verts.append(b.verts)
        faces.append(b.faces + offset)
        offset += len(b.verts)
    return np.vstack(verts), np.vstack(faces)


MAX_STEP_RELIEF_CELLS = 12_000     # per relief: CAD/slicer STEP import meshes every face, keep it light


def step_bodies(bodies, max_cells=MAX_STEP_RELIEF_CELLS):
    """Bodies for STEP: reliefs on a lighter grid (every triangle of a relief is a CAD face)."""
    out, notes = [], []
    for b in bodies:
        g = b.grid
        if g is not None:
            z = np.asarray(g['z'])
            rows, cols = z.shape
            step = max(1, int(math.ceil(math.sqrt((rows - 1) * (cols - 1) / max_cells))))
            if step > 1:
                ri = np.unique(np.r_[np.arange(0, rows, step), rows - 1])
                ci = np.unique(np.r_[np.arange(0, cols, step), cols - 1])
                # keep the exact outline: last row/column even when the stride does not land on it
                zz = z[np.ix_(ri, ci)]
                x = g['x0'] + ci * g['dx']
                y = g['y_top'] - ri * g['dy']
                v, f = heightfield_body(zz, 0.0, 0.0, 1.0, 1.0, g['zb'])
                n = len(ri) * len(ci)
                X, Y = np.meshgrid(x, y)
                v[:n, 0], v[:n, 1] = X.ravel(), Y.ravel()
                ring = np.arange(n).reshape(len(ri), len(ci))
                ring = np.concatenate([ring[0, :], ring[1:, -1], ring[-1, -2::-1], ring[-2:0:-1, 0]])
                v[n:n + len(ring), 0], v[n:n + len(ring), 1] = X.ravel()[ring], Y.ravel()[ring]
                v[-1, 0], v[-1, 1] = x.mean(), y.mean()
                out.append(Body(b.name, v, f, b.part, b.color))
                notes.append(f'STEP: {b.name} on a {g["dx"] * step:.2f} mm grid (lighter for CAD; STL / 3MF keep '
                             f'the full {g["dx"]:.2f} mm)')
                continue
        out.append(b)
    return out, notes


def write_step_bodies(path, bodies, name='SPM Studio plate'):
    """AP214 STEP with one B-rep solid (planar faces, shared edges) per body."""
    from .print3d_step import write_step_solids
    return write_step_solids(path, [(b.name, b.verts, b.faces) for b in bodies], name)


def _xml(text) -> str:
    return (str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'))


def gradient_recipe(plate: Plate) -> dict:
    """What to set in Bambu Studio (Color Mixing › Gradient) for each panel part."""
    out = {'how': 'Bambu Studio ≥ 2.5.3: load the two filaments of each panel, Filament list › Add Mixed Filament › '
                  'choose them, tick Gradient (low colour first), OK; then assign that mixed filament to the panel '
                  'part. The gradient follows the height: the 3D colour bar shows exactly the same colours as the '
                  'relief at the same height.',
           'plate_and_labels_colour': plate.params.get('background_color', '#FFFFFF'),
           'plate_colour': plate.params.get('background_color', '#FFFFFF'),
           'text_colour': plate.params.get('text_color', '#000000'), 'panels': []}
    base, relief = plate.params['base_mm'], plate.params['relief_mm']
    for info in plate.panels:
        shift = info['low'] if info.get('zero_reference') else 0.0
        out['panels'].append({'part': info['part'], 'low_colour': info['colors'][0], 'high_colour': info['colors'][1],
                              'low_value': (info['low'] - shift) * info['factor'],
                              'high_value': (info['high'] - shift) * info['factor'],
                              'unit': info['unit'], 'low_height_mm': base, 'high_height_mm': base + relief})
    return out


def write_3mf(path, plate: Plate, name='SPM Studio plate'):
    """3MF (core specification): one object assembled from parts — "Plate", "Labels" and one part per panel
    (relief + its 3D colour bar) — each with its display colour; the gradient recipe is stored inside."""
    path = Path(path)
    parts = plate.parts()
    recipe = gradient_recipe(plate)
    colours = []
    for part_name, bodies in parts.items():
        colours.append(bodies[0].color)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
             f'<metadata name="Title">{_xml(name)}</metadata>',
             '<metadata name="Application">SPM Studio</metadata>',
             f'<metadata name="Description">{_xml(recipe["how"])}</metadata>',
             '<resources>', '<basematerials id="1">']
    for i, (part_name, colour) in enumerate(zip(parts, colours)):
        lines.append(f'<base name="{_xml(part_name)}" displaycolor="{colour.upper()}FF"/>')
    lines.append('</basematerials>')
    ids = []
    for i, (part_name, bodies) in enumerate(parts.items()):
        oid = i + 2
        ids.append(oid)
        verts, faces = merged(bodies)
        lines.append(f'<object id="{oid}" type="model" name="{_xml(part_name)}" pid="1" pindex="{i}"><mesh><vertices>')
        lines.extend(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
        lines.append('</vertices><triangles>')
        lines.extend(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
        lines.append('</triangles></mesh></object>')
    assembly = len(ids) + 2
    lines.append(f'<object id="{assembly}" type="model" name="{_xml(name)}"><components>')
    lines.extend(f'<component objectid="{oid}"/>' for oid in ids)
    lines.append('</components></object>')
    lines.append('</resources>')
    lines.append(f'<build><item objectid="{assembly}"/></build>')
    lines.append('</model>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                     '<Default Extension="json" ContentType="application/json"/>'
                     '<Default Extension="txt" ContentType="text/plain"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    tmp = path.with_suffix('.tmp')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('3D/3dmodel.model', '\n'.join(lines))
        zf.writestr('Metadata/spm_studio_gradients.json', json.dumps(recipe, indent=1, ensure_ascii=False))
        zf.writestr('Metadata/README_colour_gradient.txt', recipe_text(recipe))
    tmp.replace(path)
    return path


def recipe_text(recipe: dict) -> str:
    lines = ['SPM Studio — colour gradient for Bambu Studio (Color Mixing, Gradient mode)', '', recipe['how'], '',
             f"Plate: one solid filament (colour {recipe.get('plate_colour', recipe['plate_and_labels_colour'])}).",
             f"Labels (texts, ticks, scale bar): one solid filament (colour {recipe.get('text_colour', '#000000')}).",
             '']
    for panel in recipe['panels']:
        lines.append(f"{panel['part']}: gradient {panel['low_colour']} (lowest, {panel['low_value']:.4g} "
                     f"{panel['unit']} at {panel['low_height_mm']:.1f} mm) → {panel['high_colour']} (highest, "
                     f"{panel['high_value']:.4g} {panel['unit']} at {panel['high_height_mm']:.1f} mm)")
    return '\n'.join(lines) + '\n'


MAX_STEP_TRIANGLES = 400_000


def export_plate(plate: Plate, path, fmt=None, name='SPM Studio plate', bambu=None):
    """Write STL / STEP / 3MF; returns (path, triangles, notes).

    bambu: for 3MF, a dict {'printer': model, 'nozzle': 0.4, 'gradient': True} writes a Bambu Studio project
    (printer, nozzle, filaments and one mixed gradient filament per channel already set); None writes the
    generic 3MF of v0.0.15.
    """
    fmt = (fmt or Path(path).suffix or 'stl').lower().lstrip('.')
    notes = []
    if fmt in ('step', 'stp'):
        bodies, notes = step_bodies(plate.bodies)
        triangles = int(sum(len(b.faces) for b in bodies))
        if triangles > MAX_STEP_TRIANGLES:
            notes.append(f'STEP with {triangles:,} triangles: CAD programs may need a while to open it '
                         '(choose Draft quality for a lighter file)')
        return write_step_bodies(path, bodies, name), triangles, notes
    if fmt == '3mf':
        if bambu:
            from . import print3d_bambu as B
            written, extra = B.write_bambu_3mf(path, plate, name=name, **bambu)
            return written, plate.triangles, extra
        notes.append('3MF: in Bambu Studio create one gradient mixed filament per panel part (recipe inside the file '
                     'and in the .txt next to it)')
        return write_3mf(path, plate, name), plate.triangles, notes
    verts, faces = merged(plate.bodies)
    return P.write_stl(path, verts, faces, name), len(faces), notes
