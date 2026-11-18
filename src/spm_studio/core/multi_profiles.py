"""v32 multi-line profiles: several coloured lines, several channels, several graphs.

Pure computation and Matplotlib figure building (no Qt), so it is testable and
reusable by any tool.  Lines are stored in source-pixel coordinates
``((col0,row0),(col1,row1))`` of the channel they were drawn on and are re-used on
other channels of the same frame through fractional coordinates, so a line keeps
the same physical position on every channel.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import csv
import numpy as np

from .analysis_utils import profile_between, profile_along, polyline_length

# Distinct, colour-blind friendly line colours (Okabe–Ito + extras).
LINE_COLORS = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00', '#56B4E9',
               '#F0E442', '#000000', '#8C564B', '#7F7F7F', '#17BECF', '#BCBD22']


def line_color(index: int) -> str:
    return LINE_COLORS[index % len(LINE_COLORS)]


@dataclass
class LineSpec:
    """One drawn line and how it is shown."""
    points_px: tuple                     # ((c0,r0),(c1,r1)) on the reference grid
    reference_shape: tuple               # (rows, cols) of the grid the line was drawn on
    name: str = 'Line'
    color: str = '#0072B2'
    graph: int = 1                       # 1-based graph number
    inset: bool = False                  # draw in the inset of that graph
    visible: bool = True
    scan_width: float = 2.0               # exported scan overlay thickness factor

    def to_dict(self):
        d = asdict(self)
        d['points_px'] = [list(p) for p in self.points_px]
        d['reference_shape'] = list(self.reference_shape)
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(points_px=tuple(tuple(map(float, p)) for p in d['points_px']),
                   reference_shape=tuple(int(v) for v in d['reference_shape']),
                   name=str(d.get('name', 'Line')), color=str(d.get('color', '#0072B2')),
                   graph=int(d.get('graph', 1)), inset=bool(d.get('inset', False)),
                   visible=bool(d.get('visible', True)),
                   scan_width=float(d.get('scan_width', 2.0)))


def map_points(points_px, reference_shape, target_shape):
    """Same physical line on another channel of the same frame (fractional mapping)."""
    ry, rx = reference_shape
    ty, tx = target_shape
    if (ry, rx) == (ty, tx):
        return tuple(tuple(map(float, p)) for p in points_px)
    # pixel-centre convention: (c+0.5)/n is preserved
    return tuple(((c + .5) / rx * tx - .5, (r + .5) / ry * ty - .5) for c, r in points_px)


def physical_length_nm(points_px, shape, size_m):
    """Length of the line (or of the whole polyline) in nm; ``None`` when uncalibrated."""
    if not size_m:
        return None
    ny, nx = shape
    return polyline_length(points_px, (size_m[0] / nx * 1e9, size_m[1] / ny * 1e9))


@dataclass
class Profile:
    line: str
    channel: str
    unit: str
    distance: np.ndarray
    values: np.ndarray
    distance_unit: str
    color: str
    graph: int
    inset: bool
    points_px: tuple = field(default=())


def compute_profiles(lines, channels):
    """Profiles for every (visible line × channel).

    ``channels``: list of dicts {name, data (2-D processed array), unit, size_m}.
    Distances are in nm when the channel is calibrated, otherwise in pixels.
    """
    out = []
    for ch in channels:
        data = np.asarray(ch['data'], dtype=float)
        for line in lines:
            if not line.visible:
                continue
            pts = map_points(line.points_px, line.reference_shape, data.shape)
            size_m = ch.get('size_m')
            if size_m:
                ny, nx = data.shape
                dist, z = profile_along(data, pts, spacing=(size_m[0] / nx * 1e9, size_m[1] / ny * 1e9))
                unit = 'nm'
            else:
                dist, z = profile_along(data, pts)
                unit = 'px'
            out.append(Profile(line.name, ch['name'], ch.get('unit', ''), dist, z, unit,
                               line.color, int(line.graph), bool(line.inset), pts))
    return out


def write_csv(profiles, path):
    """Long-format CSV: one row per sample (line, channel, distance, value)."""
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['line', 'channel', 'graph', 'inset', 'distance', 'distance_unit', 'value', 'value_unit',
                    'col0', 'row0', 'col1', 'row1', 'vertices'])
        for p in profiles:
            (c0, r0), (c1, r1) = p.points_px[0], p.points_px[-1]
            vertices = ' '.join(f'{c:.3f}:{r:.3f}' for c, r in p.points_px)
            for d, v in zip(p.distance, p.values):
                w.writerow([p.line, p.channel, p.graph, int(p.inset), f'{d:.8g}', p.distance_unit,
                            '' if not np.isfinite(v) else f'{v:.10g}', p.unit,
                            f'{c0:.3f}', f'{r0:.3f}', f'{c1:.3f}', f'{r1:.3f}', vertices])
    return path


def write_wide_csv(profiles, path):
    """Wide CSV: two columns (distance, value) per line × channel, side by side."""
    cols = []
    for p in profiles:
        cols.append((f'{p.line} · {p.channel} distance ({p.distance_unit})', p.distance))
        cols.append((f'{p.line} · {p.channel} ({p.unit})', p.values))
    n = max((len(c[1]) for c in cols), default=0)
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow([c[0] for c in cols])
        for i in range(n):
            w.writerow([(f'{c[1][i]:.10g}' if i < len(c[1]) and np.isfinite(c[1][i]) else '') for c in cols])
    return path


def _display_scale(unit, values):
    try:
        from .models import preferred_display_unit
        shown, mult = preferred_display_unit(unit, np.asarray(values, float))
        return shown, mult
    except Exception:
        return unit, 1.


def build_figure(profiles, *, n_graphs=1, channels=None, normalize=False, plot_style=None,
                 graph_titles=None, inset_position='upper right', width_in=None, height_in=None):
    """Publication figure: rows = channels (unless normalized), columns = graphs.

    Each graph shows the lines assigned to it; lines flagged ``inset`` are drawn in
    an inset axes of that graph.  Journal axes and a, b, c letters are added by
    ``finalize_publication_figure`` when the figure is saved.
    """
    from .plots import plot_style as _style, finalize_publication_figure
    channels = channels or list(dict.fromkeys(p.channel for p in profiles))
    rows = [None] if normalize else channels
    n_graphs = max(1, int(n_graphs))
    style = plot_style or {'schema_version': 1}
    with _style(style):
        from matplotlib.figure import Figure
        w = width_in or max(3.4, 3.3 * n_graphs)
        h = height_in or max(2.6, 2.5 * len(rows))
        fig = Figure(figsize=(w, h))
        axes = fig.subplots(len(rows), n_graphs, squeeze=False)
        for ri, row_channel in enumerate(rows):
            for gi in range(n_graphs):
                ax = axes[ri][gi]
                sel = [p for p in profiles if p.graph == gi + 1 and (normalize or p.channel == row_channel)]
                main = [p for p in sel if not p.inset]
                ins = [p for p in sel if p.inset]
                unit = main[0].unit if main else (ins[0].unit if ins else '')
                shown, mult = _display_scale(unit, np.concatenate([p.values for p in sel]) if sel else np.array([0.]))
                inset_ax = None
                if ins:
                    loc = {'upper right': [.58, .58, .38, .36], 'upper left': [.1, .58, .38, .36],
                           'lower right': [.58, .12, .38, .36], 'lower left': [.1, .12, .38, .36]}[inset_position]
                    inset_ax = ax.inset_axes(loc)
                    inset_ax._spm_inset = True
                for target, group in ((ax, main), (inset_ax, ins)):
                    if target is None:
                        continue
                    for p in group:
                        y = np.asarray(p.values, float)
                        if normalize:
                            lo, hi = np.nanmin(y), np.nanmax(y)
                            y = (y - lo) / (hi - lo) if hi > lo else y * 0
                        else:
                            y = y * mult
                        multi_ch = normalize and len(channels) > 1
                        label = f'{p.line} · {p.channel}' if multi_ch else p.line
                        target.plot(p.distance, y, color=p.color, lw=1.4 if target is ax else 1.0, label=label,
                                    ls=['-', '--', ':', '-.'][channels.index(p.channel) % 4] if multi_ch else '-')
                dunit = (sel[0].distance_unit if sel else 'nm')
                ax.set_xlabel(f'Distance ({dunit})')
                if normalize:
                    ax.set_ylabel('Normalized signal')
                else:
                    ax.set_ylabel(f'{row_channel} ({shown})' if shown else str(row_channel))
                if graph_titles and gi < len(graph_titles) and graph_titles[gi] and ri == 0:
                    ax.set_title(graph_titles[gi])
                if main:
                    ax.legend(fontsize='small', frameon=False)
                if inset_ax is not None:
                    inset_ax.tick_params(labelsize=7, direction='in', top=True, right=True)
                    inset_ax.legend(fontsize=6, frameon=False, loc='best')
                if not sel:
                    ax.text(.5, .5, 'no line assigned', transform=ax.transAxes, ha='center', va='center',
                            color='#888888', fontsize=8)
        try:
            fig.tight_layout(rect=(0, 0, 1, .95))   # room above for the a, b, c letters
        except Exception:
            pass
        finalize_publication_figure(fig, style)
    return fig
