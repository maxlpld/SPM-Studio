"""Strict, versioned publication-style settings shared by all native modules.

This is distinct from Qt application themes and image processing presets.
No scientific data are modified by these settings.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json

DEFAULT_PLOT = {
    'schema_version': 1, 'name': 'Clean publication',
    'font_family': 'DejaVu Sans', 'font_size': 10,
    'title_size': 11, 'label_size': 10, 'tick_size': 9,
    'legend_size': 8, 'line_width': 1.5, 'marker_size': 4,
    'grid': False, 'axes_spines': ['left','right','top','bottom'],
    'journal_frame': True, 'panel_labels': True, 'transparent_background': False,
    'max_ticks': 5, 'scientific_notation': True,
    'figure_width_in': 7.0, 'figure_height_in': 4.4,
    'dpi': 600, 'background': '#ffffff',
    'image_colormap': 'gray', 'image_interpolation': 'nearest',
    'image_colorbar': True, 'image_aspect': 'equal',
    'auto_limits': True,
    'channel_colormaps': {'Z': 'gray', 'Bias': 'coolwarm',
                          'Current': 'viridis', 'Excitation': 'inferno'},
    # v32 figure customization (applied to every script figure before saving)
    'colormap_override': '',          # '' = keep each script's colormap; else force for all image plots (incl. FFT, Δf)
    'show_titles': True,
    'text_replacements': '',          # lines "old => new": rename any title / axis label / legend / colourbar label
    'colorbar_mode': 'auto',          # auto | hide | right | left | top | bottom
    'colorbar_size_pct': 5.0,         # thickness as % of the plot, used when a position is chosen
    'legend_mode': 'auto',            # auto | hide | best | upper right | upper left | lower right | lower left | outside right
    'legend_frame': False,
    # v34: the display the user set up on the scan (per channel: colormap LUT, title, range);
    # filled at run time when "Use the current scan display" is ticked in the tool panel.
    'viewer_config': {},
}
VALID_MPL_CMAPS = {'gray','Greys','viridis','plasma','inferno','magma','cividis',
                   'coolwarm','RdBu_r','turbo','cubehelix','Blues','hot','bone',
                   'Spectral','seismic','YlGnBu','nipy_spectral','gist_heat',
                   'afmhot','copper','twilight','PuOr','BrBG','PiYG','Reds','Greens','Purples','Oranges','gray_r'}
COLORBAR_MODES=('auto','hide','right','left','top','bottom')
LEGEND_MODES=('auto','hide','best','upper right','upper left','lower right','lower left','outside right')


def validate_plot(data):
    if not isinstance(data,dict) or data.get('schema_version') != 1:
        raise ValueError('Plot style must be a JSON object with schema_version: 1')
    unknown=set(data)-set(DEFAULT_PLOT)
    if unknown:raise ValueError('Unsupported plot style keys: '+', '.join(sorted(unknown)))
    result=deepcopy(DEFAULT_PLOT)
    result.update(data)
    for key in ('font_size','title_size','label_size','tick_size','legend_size',
                'line_width','marker_size','figure_width_in','figure_height_in'):
        v=result[key]
        if type(v) not in (float,int) or not (0 < v <= 80):
            raise ValueError(f'{key} must be a positive number ≤ 80')
    for key in ('dpi','max_ticks'):
        v=result[key]
        if type(v) is not int or not (1<=v<=2400 if key=='dpi' else 2<=v<=20):
            raise ValueError(f'{key} must be a valid integer')
    if result['colormap_override'] not in ('',)+tuple(VALID_MPL_CMAPS):
        raise ValueError('Unsupported colormap_override')
    if result['colorbar_mode'] not in COLORBAR_MODES:raise ValueError('Invalid colorbar_mode')
    if result['legend_mode'] not in LEGEND_MODES:raise ValueError('Invalid legend_mode')
    if type(result['colorbar_size_pct']) not in (int,float) or not (1<=result['colorbar_size_pct']<=40):
        raise ValueError('colorbar_size_pct must be 1–40')
    if not isinstance(result['text_replacements'],str) or len(result['text_replacements'])>20000:
        raise ValueError('text_replacements must be text')
    if not isinstance(result['viewer_config'],dict):raise ValueError('viewer_config must be an object')
    for key in ('grid','scientific_notation','image_colorbar','auto_limits','journal_frame','panel_labels','transparent_background',
                'show_titles','legend_frame'):
        if type(result[key]) is not bool:raise ValueError(f'{key} must be boolean')
    if result['image_colormap'] not in VALID_MPL_CMAPS:
        raise ValueError('Unsupported image_colormap')
    if not isinstance(result['channel_colormaps'],dict):
        raise ValueError('channel_colormaps must be a dictionary')
    for key,cmap in result['channel_colormaps'].items():
        if not isinstance(key,str) or not key or cmap not in VALID_MPL_CMAPS:
            raise ValueError('Invalid channel colormap mapping')
    if result['image_interpolation'] not in ('nearest','none','bilinear'):
        raise ValueError('image_interpolation must be nearest, none or bilinear')
    if result['image_aspect'] not in ('equal','auto'):
        raise ValueError('image_aspect must be equal or auto')
    spines=result['axes_spines']
    if not isinstance(spines,list) or any(x not in ('left','right','top','bottom') for x in spines):
        raise ValueError('axes_spines must be a list of known sides')
    if not isinstance(result['font_family'],str) or len(result['font_family'])>100:
        raise ValueError('Invalid font_family')
    if not isinstance(result['name'],str) or not result['name'].strip():
        raise ValueError('Style name is required')
    if not isinstance(result['background'],str) or len(result['background'])>50:
        raise ValueError('Invalid background')
    return result


def load_plot(path):
    return validate_plot(json.loads(Path(path).read_text(encoding='utf8')))


def available_styles(directory):
    results={'Clean publication':deepcopy(DEFAULT_PLOT)}
    errors=[]
    for p in sorted(Path(directory).glob('*.json')):
        try: results[p.stem]=load_plot(p)
        except (OSError,ValueError,TypeError) as ex: errors.append(f'{p.name}: {ex}')
    return results, errors


def viewer_channel(profile, channel):
    """The viewer display of ``channel`` passed to a script run, or None."""
    cfg=(profile or {}).get('viewer_config') or {}
    if not cfg.get('enabled'):return None
    return (cfg.get('channels') or {}).get(channel)


def clean_title(text):
    """A title that can always be drawn (v34.1).

    Doubled backslashes ("$\\\\Delta f$", left by older profiles/sessions) are
    collapsed; if the LaTeX between $ $ still cannot be typeset, the $ signs are
    shown literally instead of making the figure fail.
    """
    s=str(text or '')
    while '\\\\' in s:s=s.replace('\\\\','\\')
    if '$' in s:
        try:
            from matplotlib.mathtext import MathTextParser
            MathTextParser('path').parse(s)
        except Exception:
            s=s.replace('$','')
    return s


def viewer_title(profile, channel, default=None):
    info=viewer_channel(profile,channel)
    return clean_title((info or {}).get('title') or (default if default is not None else channel))


def viewer_limits(profile, channel, data):
    """(low, high) colour limits as set in the viewer for this channel, else None."""
    import numpy as np
    info=viewer_channel(profile,channel)
    if not info:return None
    a=np.asarray(data,dtype=float);a=a[np.isfinite(a)]
    if not a.size:return None
    if info.get('range_mode')=='percentile':
        lo,hi=np.percentile(a,[float(info.get('low',1)),float(info.get('high',99))])
    elif info.get('range_mode')=='absolute':
        lo,hi=float(info.get('low')),float(info.get('high'))
    else:
        lo,hi=float(a.min()),float(a.max())
    return (float(lo),float(hi)) if hi>lo else None


def resolve_cmap(name):
    """Matplotlib colormap for a Matplotlib name, a Studio palette or a custom palette file.

    Lets every script accept ALL colormaps of the viewer (Gwyddion imports, custom CSV …).
    """
    if not isinstance(name,str):return name
    try:
        import matplotlib
        if name in matplotlib.colormaps:return name
    except Exception:
        pass
    try:
        from matplotlib.colors import ListedColormap
        from .display import lut
        return ListedColormap(lut(name)/255.,name=str(name))
    except Exception:
        return 'gray'


def display_cmap(channel, profile):
    info=viewer_channel(profile,channel)
    if info and info.get('lut'):
        try:
            import numpy as np
            from matplotlib.colors import ListedColormap
            return ListedColormap(np.asarray(info['lut'],dtype=float)/255.,name=str(info.get('colormap','viewer')))
        except Exception:
            pass
    for key,val in profile.get('channel_colormaps',{}).items():
        if key.lower() in channel.lower():return val
    return profile['image_colormap']


def all_colormap_choices():
    """[(label, key)] of every colormap of the viewer: built-in palettes + palette files."""
    from .display import PALETTES
    out=[(k,k) for k in PALETTES]
    try:
        from .paths import customization_dir
        folder=customization_dir()/'colormaps'
        if folder.is_dir():
            out+=[(f.stem,f.name) for f in sorted(folder.iterdir()) if f.suffix.lower() in ('.csv','.txt')]
    except Exception:
        pass
    return out


def is_colormap_parameter(name):
    n=str(name).lower()
    return any(w in n for w in ('cmap','colormap','palette'))


def default_channel_title(channel):
    """Default colourbar title of a channel (LaTeX)."""
    n=str(channel).lower()
    if 'excitation' in n:
        return r'$V_{exc,TR}$' if ('m2' in n or 'tors' in n) else r'$V_{exc}$'
    return str(channel)


def default_scale_bar_color(channel):
    """Topography: black bar; excitation and torsional channels: white bar."""
    n=str(channel).lower().replace('$','').replace('\\mathrm','').strip()
    # channel names and their usual titles ($V_{exc}$, $\Delta f_{TR}$, $Z$) are both recognised
    if 'excitation' in n or 'exc' in n or 'm2' in n or 'tors' in n or '_{tr' in n or '_tr' in n:return '#ffffff'
    if n=='z' or n.startswith('z ') or n.startswith('z/') or 'topo' in n or 'height' in n:return '#000000'
    return '#111111'


def default_viewer_palette(channel, profile):
    """Default colormap of a channel in the viewer; Bias uses Gwyddion's Caribbean when installed."""
    from .display import PALETTES
    if 'bias' in str(channel).lower():
        try:
            from .paths import customization_dir
            if (customization_dir()/'colormaps'/'Gwy - Caribbean.csv').is_file():return 'Gwy - Caribbean.csv'
        except Exception:
            pass
    name=display_cmap(channel,profile)
    return name if isinstance(name,str) and name in PALETTES else 'gray'


def ensure_bundled_styles(config_folder):
    """Copy bundled examples to writable user configuration once; never overwrite."""
    target=Path(config_folder)
    target.mkdir(parents=True,exist_ok=True)
    source=Path(__file__).resolve().parents[3]/'customization'/'plot_styles'
    if source.is_dir():
        for p in source.glob('*.json'):
            destination=target/p.name
            if not destination.exists():
                from shutil import copy2
                copy2(p,destination)
    return target
