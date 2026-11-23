"""3D printable relief of a scan channel, with a 3D colour bar (Qt-free).

The whole model is one height field on a regular grid (cell = ``resolution_mm``):

* the **scan relief**: height = base + relief × (value − low) / (high − low), clipped to
  [low, high] — the user can cut the range so a few tall features do not flatten the rest;
* the **3D colour bar**: printers cannot print a colormap, so the bar is a wedge whose height
  rises linearly from the lowest value (base) to the highest (base + relief) — the same mapping
  as the relief, so a height on the scan can be read on the bar; raised ticks and value labels
  run along it;
* **embossed annotations** on the base plate (title, scale bar, colour-bar values, lattice
  legend) and **on the relief** (lattice vectors, molecules) are rasterised with Matplotlib
  into masks and raised by ``label_mm`` / ``overlay_mm``.

The height field becomes a closed, watertight triangle mesh (top, flat bottom, side walls)
written as binary **STL** or as **STEP** (AP214 faceted B-rep, read by FreeCAD, Fusion,
SolidWorks …). Nothing here imports Qt; tests run without a display.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

POSITIONS = ('right', 'left', 'top', 'bottom', 'none')

DEFAULTS = {
    'width_mm': 80.0,          # printed width of the scan
    'base_mm': 2.0,            # plate thickness under the lowest point
    'relief_mm': 6.0,          # height difference low → high value
    'resolution_mm': 0.25,     # grid cell (≈ nozzle diameter / 2 … nozzle)
    'range_mode': 'percentile',  # 'percentile' | 'absolute'
    'low': 1.0, 'high': 99.0,  # percentiles or absolute values (data unit)
    'invert': False,
    'smooth_px': 0.0,          # optional Gaussian smoothing (scan pixels) against noise spikes
    'colorbar': 'right',
    'colorbar_width_mm': 10.0,
    'colorbar_gap_mm': 5.0,
    'colorbar_ticks': 5,
    'margin_mm': 4.0,
    'label_mm': 0.8,           # height of embossed text above the plate
    'overlay_mm': 1.0,         # height of embossed vectors / molecules above the relief
    'font_mm': 4.0,
    'title': '',
    'scale_bar': True,
    'unit': '',
    'value_scale': 1.0,        # data unit → displayed unit (e.g. 1e12 for m → pm)
}


def nice_number(x):
    if x <= 0 or not math.isfinite(x):
        return 0.0
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * e >= x * .999:
            return m * e
    return 10 * e


def display_unit(unit, values):
    """(factor, unit) to show values in readable units (pm/nm, pA/nA, mV …)."""
    finite = np.abs(np.asarray(values, float))
    finite = finite[np.isfinite(finite)]
    m = float(np.percentile(finite, 95)) if finite.size else 0.0
    table = {'m': [(1e12, 'pm', 1e-9), (1e9, 'nm', 1e-6), (1e6, 'µm', np.inf)],
             'A': [(1e12, 'pA', 1e-9), (1e9, 'nA', 1e-6), (1e6, 'µA', np.inf)],
             'V': [(1e3, 'mV', 1.0), (1.0, 'V', np.inf)],
             'S': [(1e12, 'pS', 1e-9), (1e9, 'nS', 1e-6), (1e6, 'µS', np.inf)]}
    for factor, name, limit in table.get(unit, []):
        if m < limit:
            return factor, name
    return 1.0, unit


@dataclass
class Overlay:
    """Things embossed on the relief, in nm with the origin at the image centre, +y up."""
    vectors: list = field(default_factory=list)       # [(vx, vy, label)] from the centre
    legend: list = field(default_factory=list)        # text lines embossed on the plate
    molecules: list = field(default_factory=list)     # [(cx, cy)] sites
    molecule_mask: np.ndarray | None = None           # 2-D alpha (0…1) of the artwork
    molecule_size_nm: tuple = (1.0, 1.0)
    molecule_angle_deg: float = 0.0
    vector_scale: int = 1                              # arrows drawn as N × a, N × b


@dataclass
class Model:
    z: np.ndarray                 # height field (mm), rows top → bottom
    cell_mm: float
    image_box: tuple              # (x0, y0, w, h) mm of the scan on the plate (y from the top)
    bar_box: tuple | None
    low: float
    high: float
    notes: list = field(default_factory=list)

    @property
    def size_mm(self):
        return self.z.shape[1] * self.cell_mm, self.z.shape[0] * self.cell_mm


def value_range(data, p):
    finite = np.asarray(data, float)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        raise ValueError('The channel has no finite values')
    if p.get('range_mode', 'percentile') == 'absolute':
        lo, hi = float(p['low']), float(p['high'])
    else:
        lo, hi = np.percentile(finite, [float(p.get('low', 1)), float(p.get('high', 99))])
    if not hi > lo:
        raise ValueError('The colour-bar range is empty: the high value must be above the low value')
    return float(lo), float(hi)


def _resample(data, shape):
    """Bilinear resampling of the scan onto the print grid (NaN → nearest finite value)."""
    from scipy.ndimage import map_coordinates
    a = np.asarray(data, float)
    if not np.isfinite(a).all():
        finite = np.isfinite(a)
        if finite.any():
            from scipy.ndimage import distance_transform_edt
            _d, idx = distance_transform_edt(~finite, return_indices=True)
            a = a[tuple(idx)]
        else:
            a = np.zeros_like(a)
    rows, cols = shape
    r = (np.arange(rows) + .5) / rows * a.shape[0] - .5
    c = (np.arange(cols) + .5) / cols * a.shape[1] - .5
    rr, cc = np.meshgrid(r, c, indexing='ij')
    return map_coordinates(a, [rr, cc], order=1, mode='nearest')


def _layout(p, image_w, image_h, legend=False):
    """Plate size and boxes (mm, y measured from the top edge)."""
    m = float(p['margin_mm'])
    font = float(p['font_mm'])
    pos = p.get('colorbar', 'right')
    bw, gap = float(p['colorbar_width_mm']), float(p['colorbar_gap_mm'])
    label_space = font * 4.2                   # room for the value labels next to the bar
    title_h = font * 1.8 if str(p.get('title', '')).strip() else 0.0
    under_h = (font * 1.9 if p.get('scale_bar', True) else 0.0) + (font * 1.5 if legend else 0.0)
    x0, y0 = m, m + title_h
    width = m + image_w + m
    height = y0 + image_h + under_h + m
    bar = None
    if pos == 'right':
        bar = (x0 + image_w + gap, y0, bw, image_h)
        width += gap + bw + label_space
    elif pos == 'left':
        x0 += bw + gap + label_space
        bar = (m + label_space, y0, bw, image_h)
        width += gap + bw + label_space
    elif pos == 'top':
        y0 += bw + gap + font * 1.8
        bar = (x0, m + title_h + font * 1.8, image_w, bw)
        height += gap + bw + font * 1.8
    elif pos == 'bottom':
        bar = (x0, y0 + image_h + under_h + gap, image_w, bw)
        height += gap + bw + font * 1.9
    return (width, height), (x0, y0, image_w, image_h), bar


def build_model(data, size_nm, params=None, overlay: Overlay | None = None) -> Model:
    """Height field of the whole printable plate."""
    p = dict(DEFAULTS)
    p.update(params or {})
    a = np.asarray(data, float)
    if a.ndim != 2 or min(a.shape) < 2:
        raise ValueError('A 2-D scan channel is needed')
    wn, hn = (float(size_nm[0]), float(size_nm[1])) if size_nm else (float(a.shape[1]), float(a.shape[0]))
    image_w = float(p['width_mm'])
    image_h = image_w * hn / wn
    cell = float(p['resolution_mm'])
    if not 0.02 <= cell <= 5:
        raise ValueError('Resolution must be between 0.02 and 5 mm')
    notes = []
    (W, H), ibox, bar = _layout(p, image_w, image_h, bool(overlay is not None and overlay.legend))
    cols, rows = int(math.ceil(W / cell)), int(math.ceil(H / cell))
    if cols * rows > 9_000_000:
        raise ValueError(f'{cols} × {rows} cells is too fine: increase the resolution (mm)')
    base, relief = float(p['base_mm']), float(p['relief_mm'])
    if base < .2 or relief <= 0:
        raise ValueError('Base must be ≥ 0.2 mm and the relief > 0 mm')
    z = np.full((rows, cols), base)
    lo, hi = value_range(a, p)
    # ---- relief
    ic0, ir0 = int(round(ibox[0] / cell)), int(round(ibox[1] / cell))
    icn, irn = max(2, int(round(ibox[2] / cell))), max(2, int(round(ibox[3] / cell)))
    src = a
    if float(p.get('smooth_px', 0) or 0) > 0:
        from scipy.ndimage import gaussian_filter
        filled = np.where(np.isfinite(a), a, np.nanmedian(a))
        src = gaussian_filter(filled, float(p['smooth_px']))
    grid = _resample(src, (irn, icn))
    t = np.clip((grid - lo) / (hi - lo), 0, 1)
    if p.get('invert'):
        t = 1 - t
    clipped = float(np.mean((grid < lo) | (grid > hi)))
    if clipped > .002:
        notes.append(f'{clipped * 100:.1f} % of the scan is outside the colour-bar range and printed flat at '
                     'the lowest / highest height')
    z[ir0:ir0 + irn, ic0:ic0 + icn] = base + relief * t
    # ---- 3D colour bar (wedge)
    if bar is not None:
        bc0, br0 = int(round(bar[0] / cell)), int(round(bar[1] / cell))
        bcn, brn = max(2, int(round(bar[2] / cell))), max(2, int(round(bar[3] / cell)))
        vertical = p['colorbar'] in ('left', 'right')
        ramp = np.linspace(1, 0, brn)[:, None] * np.ones((1, bcn)) if vertical else \
            np.ones((brn, 1)) * np.linspace(0, 1, bcn)[None, :]
        if p.get('invert'):
            ramp = 1 - ramp
        z[br0:br0 + brn, bc0:bc0 + bcn] = base + relief * ramp
    # ---- embossed text / marks / overlays
    plate_mask, relief_mask = _annotation_masks(p, (W, H), (rows, cols), cell, ibox, bar, lo, hi,
                                                (wn, hn), overlay)
    label = float(p['label_mm'])
    on_plate = plate_mask & (np.abs(z - base) < 1e-9)
    z[on_plate] = base + label
    if relief_mask is not None and relief_mask.any():
        z[relief_mask] += float(p['overlay_mm'])
    # ticks on the bar are carved: they are part of relief_mask handled above
    return Model(z, cell, ibox, bar, lo, hi, notes)


def _annotation_masks(p, size_mm, shape, cell, ibox, bar, lo, hi, size_nm, overlay):
    """Rasterise texts (plate) and vectors / molecules / ticks (relief) with Matplotlib."""
    import matplotlib
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    W, H = size_mm
    rows, cols = shape
    dpi = 100.0

    def canvas():
        fig = Figure(figsize=(cols / dpi, rows / dpi), dpi=dpi)
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, cols * cell)
        ax.set_ylim(rows * cell, 0)          # mm, y down like the grid
        ax.set_axis_off()
        fig.patch.set_alpha(0)
        return fig, ax

    def mask(fig):
        fig.canvas.draw()
        rgba = np.asarray(fig.canvas.buffer_rgba())
        return rgba[..., 3] > 110

    # 1 grid cell = 1 pixel = 72/dpi points → a length of L mm = L/cell px = L/cell*72/dpi pt
    def mm_to_pt(L):
        return L / cell * 72.0 / dpi
    font_pt = mm_to_pt(float(p['font_mm']))
    stroke = max(mm_to_pt(.6), .5)
    # ---------------- plate layer
    fig, ax = canvas()
    x0, y0, iw, ih = ibox
    title = str(p.get('title', '')).strip()
    if title:
        ax.text(x0, y0 - float(p['font_mm']) * .5, title, fontsize=font_pt * 1.15, ha='left', va='bottom',
                fontweight='bold')
    factor = float(p.get('value_scale', 1.0) or 1.0)
    unit = str(p.get('unit', '') or '')
    if p.get('scale_bar', True) and size_nm[0] > 0:
        nm_per_mm = size_nm[0] / iw
        length_nm = nice_number(size_nm[0] * .25)
        L = length_nm / nm_per_mm
        yb = y0 + ih + float(p['font_mm']) * .55
        ax.add_patch(matplotlib.patches.Rectangle((x0 + iw - L, yb), L, float(p['font_mm']) * .28, color='k', lw=0))
        text = f'{length_nm:g} nm' if length_nm >= 1 else f'{length_nm * 1000:g} pm'
        ax.text(x0 + iw - L - float(p['font_mm']) * .5, yb + float(p['font_mm']) * .14, text,
                fontsize=font_pt * .85, ha='right', va='center')
    if bar is not None:
        bx, by, bw, bh = bar
        n = max(2, int(p.get('colorbar_ticks', 5)))
        vertical = p['colorbar'] in ('left', 'right')
        step = (hi - lo) * factor / (n - 1)
        decimals = max(0, int(-math.floor(math.log10(abs(step)))) + 1) if step else 0
        for k in range(n):
            f = k / (n - 1)
            value = (lo + f * (hi - lo)) * factor
            if abs(value) < abs(step) * 1e-3:
                value = 0.0
            label = f'{value:.{decimals}f}'
            if vertical:
                yy = by + bh * (1 - f) if not p.get('invert') else by + bh * f
                if p['colorbar'] == 'right':
                    ax.text(bx + bw + float(p['font_mm']) * .6, yy, label, fontsize=font_pt * .8, ha='left',
                            va='center')
                    ax.plot([bx + bw, bx + bw + float(p['font_mm']) * .4], [yy, yy], color='k', lw=stroke)
                else:
                    ax.text(bx - float(p['font_mm']) * .6, yy, label, fontsize=font_pt * .8, ha='right', va='center')
                    ax.plot([bx - float(p['font_mm']) * .4, bx], [yy, yy], color='k', lw=stroke)
            else:
                xx = bx + bw * f if not p.get('invert') else bx + bw * (1 - f)
                if p['colorbar'] == 'bottom':
                    ax.text(xx, by + bh + float(p['font_mm']) * .5, label, fontsize=font_pt * .8, ha='center',
                            va='top')
                    ax.plot([xx, xx], [by + bh, by + bh + float(p['font_mm']) * .35], color='k', lw=stroke)
                else:
                    ax.text(xx, by - float(p['font_mm']) * .5, label, fontsize=font_pt * .8, ha='center',
                            va='bottom')
                    ax.plot([xx, xx], [by - float(p['font_mm']) * .35, by], color='k', lw=stroke)
        if unit:
            if vertical:
                ux = bx + bw / 2
                ax.text(ux, by - float(p['font_mm']) * .4, unit, fontsize=font_pt * .8, ha='center', va='bottom')
            else:
                ax.text(bx + bw + float(p['font_mm']) * .5, by + bh / 2, unit, fontsize=font_pt * .8, ha='left',
                        va='center')
    if overlay is not None and overlay.legend:
        lines = list(overlay.legend)
        below = float(p['font_mm']) * (2.0 if p.get('scale_bar', True) else .55)
        ax.text(x0, y0 + ih + below, '   '.join(lines), fontsize=font_pt * .8, ha='left', va='top')
    plate = mask(fig)
    # ---------------- relief layer (follows the surface)
    relief = None
    if overlay is not None and (overlay.vectors or overlay.molecules):
        fig, ax = canvas()
        sx, sy = iw / size_nm[0], ih / size_nm[1]
        cxm, cym = x0 + iw / 2, y0 + ih / 2

        def to_mm(x_nm, y_nm):
            return cxm + x_nm * sx, cym - y_nm * sy
        if overlay.molecules and overlay.molecule_mask is not None:
            from matplotlib.transforms import Affine2D
            mw, mh = overlay.molecule_size_nm
            art = np.asarray(overlay.molecule_mask, float)
            rgba = np.zeros(art.shape + (4,))
            rgba[..., 3] = np.clip(art, 0, 1)
            for cx, cy in overlay.molecules:
                if abs(cx) > size_nm[0] / 2 or abs(cy) > size_nm[1] / 2:
                    continue
                mx, my = to_mm(cx, cy)
                im = ax.imshow(rgba, extent=(-mw / 2 * sx, mw / 2 * sx, mh / 2 * sy, -mh / 2 * sy),
                               interpolation='bilinear')
                im.set_transform(Affine2D().rotate_deg(-overlay.molecule_angle_deg).translate(mx, my) + ax.transData)
                im.set_clip_path(matplotlib.patches.Rectangle((x0, y0), iw, ih, transform=ax.transData))
        for vx, vy, label in overlay.vectors:
            n = max(1, int(overlay.vector_scale))
            ex, ey = to_mm(vx * n, vy * n)
            ax.annotate('', (ex, ey), (cxm, cym), arrowprops=dict(arrowstyle='-|>', lw=stroke * 1.6, color='k',
                                                                   mutation_scale=font_pt * 1.2,
                                                                   shrinkA=0, shrinkB=0))
            ax.text(ex, ey, f' {label}', fontsize=font_pt * .8, ha='left', va='bottom', fontweight='bold')
        relief = mask(fig)
        # stay inside the scan area
        box = np.zeros_like(relief)
        r0, c0 = int(round(y0 / cell)), int(round(x0 / cell))
        box[r0:r0 + int(round(ih / cell)), c0:c0 + int(round(iw / cell))] = True
        relief &= box
    return plate, relief


# ---------------------------------------------------------------------------- mesh
def heightfield_mesh(z, cell):
    """Closed triangle mesh of a height field: top, flat bottom (z = 0) and four walls.

    Vertices sit on the cell centres; faces are wound counter-clockwise seen from outside
    (normals point out), as STL and STEP expect.
    """
    z = np.asarray(z, float)
    rows, cols = z.shape
    x = (np.arange(cols) + .5) * cell
    y = ((rows - 1 - np.arange(rows)) + .5) * cell        # row 0 = top edge = largest y
    X, Y = np.meshgrid(x, y)
    top = np.column_stack([X.ravel(), Y.ravel(), z.ravel()])
    bottom = top.copy()
    bottom[:, 2] = 0.0
    verts = np.vstack([top, bottom])
    n = rows * cols
    idx = np.arange(n).reshape(rows, cols)
    a = idx[:-1, :-1].ravel()
    b = idx[:-1, 1:].ravel()
    c = idx[1:, 1:].ravel()
    d = idx[1:, :-1].ravel()
    # row r is above row r+1 in y: a(top-left) b(top-right) c(bottom-right) d(bottom-left)
    faces = [np.column_stack([a, d, c]), np.column_stack([a, c, b])]                 # top, normal +z
    faces += [np.column_stack([a + n, b + n, c + n]), np.column_stack([a + n, c + n, d + n])]  # bottom, −z

    def wall(line, outward_flip):
        p, q = line[:-1], line[1:]
        t1 = np.column_stack([p, q, q + n])
        t2 = np.column_stack([p, q + n, p + n])
        if outward_flip:
            t1, t2 = t1[:, ::-1], t2[:, ::-1]
        return [t1, t2]
    faces += wall(idx[0, :], False)         # top edge (largest y), normal +y
    faces += wall(idx[-1, :], True)         # bottom edge, normal −y
    faces += wall(idx[:, 0], True)          # left edge, normal −x
    faces += wall(idx[:, -1], False)        # right edge, normal +x
    return verts, np.vstack(faces).astype(np.int64)


def check_normals(verts, faces):
    """Signed volume (> 0 when the mesh is closed and wound outward)."""
    v = np.asarray(verts, float)
    f = np.asarray(faces)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0)


def decimate(z, cell, max_cells):
    """Coarser height field (block maximum keeps thin raised text) with at most max_cells cells."""
    rows, cols = z.shape
    k = int(math.ceil(math.sqrt(rows * cols / max_cells)))
    if k <= 1:
        return z, cell
    r, c = rows // k * k, cols // k * k
    block = z[:r, :c].reshape(r // k, k, c // k, k)
    return block.max(axis=(1, 3)), cell * k


def write_stl(path, verts, faces, name='SPM Studio relief'):
    path = Path(path)
    v = np.asarray(verts, np.float32)
    f = np.asarray(faces)
    tri = v[f]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(normal, axis=1, keepdims=True)
    normal = np.divide(normal, length, out=np.zeros_like(normal), where=length > 0)
    record = np.zeros(len(f), dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)), ('attr', '<u2')])
    record['n'] = normal
    record['v'] = tri
    with path.open('wb') as fh:
        fh.write(name.encode('ascii', 'replace')[:80].ljust(80, b' '))
        fh.write(struct.pack('<I', len(f)))
        fh.write(record.tobytes())
    return path


def write_step(path, verts, faces, name='SPM Studio relief'):
    """ISO 10303-21 (AP214) file with one B-rep solid (planar faces with shared edges, millimetres).

    v0.0.16: written as ADVANCED_FACE / PLANE / EDGE_CURVE (what CAD programs write) instead of the bare
    FACETED_BREP faces, which OpenCASCADE-based importers such as Bambu Studio read as "no geometry".
    """
    from .print3d_step import write_step_solids
    return write_step_solids(path, [(name, verts, faces)], name)


MAX_STEP_CELLS = 40_000     # ≈ 80 000 triangles — CAD programs import faceted STEP slowly


def export(model: Model, path, fmt=None):
    """Write the model (format from ``fmt`` or the file suffix); returns (path, triangles, notes)."""
    fmt = (fmt or Path(path).suffix or 'stl').lower().lstrip('.')
    notes = []
    z, cell = model.z, model.cell_mm
    if fmt in ('step', 'stp'):
        z2, cell2 = decimate(z, cell, MAX_STEP_CELLS)
        if z2.shape != z.shape:
            notes.append(f'STEP: grid coarsened to {cell2:.2f} mm (faceted STEP files become very large; use STL '
                         'for the full resolution)')
        verts, faces = heightfield_mesh(z2, cell2)
        return write_step(path, verts, faces), len(faces), notes
    verts, faces = heightfield_mesh(z, cell)
    return write_stl(path, verts, faces), len(faces), notes


# ---------------------------------------------------------------------------- overlays from results
def overlay_from_lattice(doc, vector_scale=None):
    """Lattice vectors and legend from a ``lattice_result.json`` document."""
    basis = np.asarray(doc['basis_local_nm'], float)
    a, b = float(doc.get('a_nm', np.linalg.norm(basis[:, 0]))), float(doc.get('b_nm', np.linalg.norm(basis[:, 1])))
    size = doc['roi_geometry']['size_nm']
    n = vector_scale or max(1, int(round(.18 * min(size) / max(a, b, 1e-9))))
    legend = [f'a = {a:.3g} nm', f'b = {b:.3g} nm', f'γ = {float(doc.get("gamma_deg", 0)):.1f}°']
    if n > 1:
        legend.append(f'(arrows {n} × a, b)')
    return Overlay(vectors=[(basis[0, 0], basis[1, 0], 'a'), (basis[0, 1], basis[1, 1], 'b')], legend=legend,
                   vector_scale=n)


def overlay_from_molecules(lattice_doc, placement_doc, artwork_alpha, vector_scale=None):
    ov = overlay_from_lattice(lattice_doc, vector_scale)
    ov.molecules = [(float(s[0]), float(s[1])) for s in placement_doc.get('lattice_sites', [])]
    ov.molecule_mask = artwork_alpha
    ov.molecule_size_nm = (float(placement_doc['width_nm']), float(placement_doc['height_nm']))
    ov.molecule_angle_deg = float(placement_doc.get('rotation_deg', 0))
    ov.legend.append(f'{len(ov.molecules)} molecules')
    return ov


def artwork_alpha(path, long_side=400):
    """Opacity mask of a PNG / JPG molecule drawing (transparent or white background)."""
    from PIL import Image
    image = Image.open(path).convert('RGBA')
    scale = long_side / max(image.size)
    if scale < 1:
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    rgba = np.asarray(image, float) / 255
    alpha = rgba[..., 3]
    if alpha.min() > .98:                         # opaque drawing: dark lines on white
        alpha = 1 - rgba[..., :3].mean(axis=2)
    return np.clip(alpha, 0, 1)
