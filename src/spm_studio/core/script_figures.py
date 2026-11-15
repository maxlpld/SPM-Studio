"""Script figures drawn by the SAME renderer as the Export panel (v0.8).

Analysis scripts (lattice measurements, molecule placement, …) used to draw
their own Matplotlib/Qt figures, so their gap between scan and colourbar,
scale bar, fonts and colormap differed from a figure exported with *Export…*.
Every scan-like script figure now goes through
:func:`spm_studio.core.export_layout.export_publication` with a single panel,
using the scan display the user set in the viewer and the export preset that is
selected in the main window.  Only the overlay (lattice vectors, molecules) is
added on top of the image rectangle.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import os

import numpy as np

from .models import ImageStyle

FIGURE_FORMATS = ('svg', 'pdf', 'png')


def ensure_qt_gui():
    """A QGuiApplication for fonts/painters inside a headless analysis subprocess."""
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


def figure_formats(plot_formats, default=('svg',)):
    """Requested figure formats, SVG first; unknown entries are ignored."""
    wanted = [str(f).lower().lstrip('.') for f in (plot_formats or ()) if str(f).lower().lstrip('.') in FIGURE_FORMATS]
    if not wanted:
        wanted = list(default)
    return sorted(dict.fromkeys(wanted), key=FIGURE_FORMATS.index)


def _viewer_info(plot_config, channel):
    from .plot_settings import viewer_channel
    return viewer_channel(plot_config or {}, channel) or {}


def _register_table(name, table):
    """Make a viewer LUT usable by name in this process (custom palettes, Gwyddion…)."""
    from . import display
    try:
        display.lut(name)
        return name
    except Exception:
        pass
    if table is None:
        return None
    arr = np.asarray(table, dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 3 or len(arr) < 2:
        return None
    key = str(name or 'viewer')
    display.PALETTES[key] = tuple(tuple(float(c) for c in row[:3]) for row in arr)
    return key


def scan_display_style(plot_config, channel, *, colormap_override=None):
    """The ImageStyle the user sees on ``channel`` in the viewer.

    Falls back to the channel's default viewer palette (never silently gray for
    a channel that is shown in colour).
    """
    from .plot_settings import default_viewer_palette, DEFAULT_PLOT
    info = _viewer_info(plot_config, channel)
    style = ImageStyle()
    if info:
        try:
            style = ImageStyle(colormap=str(info.get('colormap', 'gray')),
                               range_mode=str(info.get('range_mode', 'percentile')),
                               low=float(info.get('low', 1.)), high=float(info.get('high', 99.)),
                               gamma=float(info.get('gamma', 1.)),
                               scale_bar=bool(info.get('scale_bar', True)),
                               colorbar=bool(info.get('colorbar', True)))
        except (TypeError, ValueError):
            style = ImageStyle()
        name = _register_table(style.colormap, info.get('lut'))
        style = replace(style, colormap=name or 'gray')
    else:
        profile = {**DEFAULT_PLOT, **(plot_config or {})}
        try:
            style = replace(style, colormap=default_viewer_palette(channel, profile))
        except Exception:
            pass
    override = str(colormap_override or '').strip()
    if override and override not in ('Current scan display', 'auto'):
        name = _register_table(override, None)
        if name is None:
            # Matplotlib names that are not Studio palettes.
            try:
                import matplotlib
                cmap = matplotlib.colormaps[override]
                table = (np.asarray(cmap(np.linspace(0, 1, 256)))[:, :3] * 255.)
                name = _register_table(override, table)
            except Exception:
                name = None
        if name:
            style = replace(style, colormap=name)
    return style


def style_to_dict(style):
    from . import display
    out = {'colormap': style.colormap, 'range_mode': style.range_mode, 'low': float(style.low),
           'high': float(style.high), 'gamma': float(style.gamma), 'scale_bar': bool(style.scale_bar),
           'colorbar': bool(style.colorbar)}
    try:
        out['lut'] = display.lut(style.colormap).tolist()
    except Exception:
        pass
    return out


def style_from_dict(info):
    if not isinstance(info, dict):
        return None
    try:
        style = ImageStyle(colormap=str(info.get('colormap', 'gray')),
                           range_mode=str(info.get('range_mode', 'percentile')),
                           low=float(info.get('low', 1.)), high=float(info.get('high', 99.)),
                           gamma=float(info.get('gamma', 1.)), scale_bar=bool(info.get('scale_bar', True)),
                           colorbar=bool(info.get('colorbar', True)))
    except (TypeError, ValueError):
        return None
    name = _register_table(style.colormap, info.get('lut'))
    return replace(style, colormap=name or 'gray')


def colorbar_title(plot_config, channel, explicit=''):
    from .plot_settings import viewer_title, default_channel_title, clean_title
    if str(explicit or '').strip():
        return clean_title(str(explicit).strip())
    return viewer_title(plot_config or {}, channel, default_channel_title(channel))


def export_preset(plot_config):
    """The export preset currently selected in the main window (falls back to single column)."""
    from .presets import validate_export, DEFAULT_EXPORT
    cfg = (plot_config or {}).get('viewer_config') or {}
    candidate = cfg.get('export_preset') if isinstance(cfg, dict) else None
    try:
        return validate_export(candidate) if candidate else validate_export(dict(DEFAULT_EXPORT))
    except (TypeError, ValueError):
        return validate_export(dict(DEFAULT_EXPORT))


def export_scan_figure(output_base, *, scan_path, data, size_nm, channel, unit, plot_config,
                       formats=('svg',), style=None, lattice=None, decorate=None,
                       colorbar_position='below', show_colorbar=True, title='', display_zero=False,
                       scale_bar_color=None, scale_bar_position='bottom_right', show_scale_bar=True,
                       figure_title='', preset=None, transparent=None):
    """Write ``output_base.<fmt>`` for every format with the Export-panel renderer.

    ``lattice`` is a lattice manifest-like dict (``basis_local_nm``, ``gamma_deg``,
    ``roi_geometry``, ``vector_colors``, ``vector_legend_corner``) drawn exactly as a
    lattice panel in *Export…*.  ``decorate(painter, image_rect)`` is drawn on the
    image before the lattice vectors (e.g. molecules).
    """
    ensure_qt_gui()
    from .export_layout import export_publication
    from .plot_settings import default_scale_bar_color
    base = Path(output_base)
    if base.suffix.lower() in ('.svg', '.pdf', '.png', '.jpg'):
        base = base.with_suffix('')
    style = style or scan_display_style(plot_config, channel)
    spec = {'kind': 'array', 'data': np.asarray(data), 'size_nm': [float(size_nm[0]), float(size_nm[1])],
            'style': style, 'title': title or colorbar_title(plot_config, channel), 'unit': '',
            'base_unit': str(unit or ''), 'colorbar_position': colorbar_position if show_colorbar else 'none',
            'show_colorbar': bool(show_colorbar),
            'scale_bar_color': scale_bar_color or default_scale_bar_color(channel),
            'scale_bar_position': scale_bar_position, 'show_scale_bar': bool(show_scale_bar),
            'display_zero': bool(display_zero), 'lattice': lattice, 'decorate': decorate,
            'figure_title': str(figure_title or '').strip()}
    if transparent is None:
        transparent = bool((plot_config or {}).get('transparent_background', False))
    scan = SimpleNamespace(path=Path(scan_path), channels={})
    written = []
    for fmt in figure_formats(formats):
        written.append(export_publication(scan, [spec], Path(str(base) + '.' + fmt), preset or export_preset(plot_config),
                                          plot_config=plot_config, transparent=transparent, panel_letters=False))
    return written
