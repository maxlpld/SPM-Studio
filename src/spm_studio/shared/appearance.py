"""SPM Studio design system (v0.8): tokens → one application-wide Qt style.

Everything visual comes from a *theme file* (``customization/themes/*.json``).
Only five colours are required (background, surface, foreground, accent,
muted); every other token is derived, but any of them can be overridden in the
JSON, together with ``font_family``, ``font_size`` (pt) and ``radius`` (px).
Importing a theme file is therefore enough to restyle the whole application.

The design is deliberately quiet: neutral surfaces, one accent colour used
sparingly, a single type scale, one control height and one corner radius, so
that buttons, inputs, menus, tabs and dialogs all look like one family.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

# ---------------------------------------------------------------- tokens
DEFAULT_THEME = 'graphite'

BUILTIN_THEMES = {
    # Dark, neutral graphite with a calm teal accent (default).
    'graphite': dict(background='#121417', surface='#1A1D22', foreground='#E6E8EC',
                     accent='#3FB8A6', muted='#99A1AE'),
    # Light, paper-like neutral with the same accent family.
    'porcelain': dict(background='#F2F3F5', surface='#FFFFFF', foreground='#16181D',
                      accent='#0F7C6F', muted='#5E6672'),
}

COLOR_TOKENS = ('background', 'surface', 'raised', 'sidebar', 'input', 'foreground', 'muted', 'subtle',
                'border', 'border_strong', 'hover', 'pressed', 'accent', 'accent_hover', 'accent_fg',
                'accent_soft', 'selection', 'danger', 'success', 'warning')
EXTRA_TOKENS = ('font_family', 'font_size', 'radius', 'design', 'tint_a', 'tint_b', 'tint_text')

# Back-compat for modules that imported the old palette table.
PALETTES = {'light': BUILTIN_THEMES['porcelain'], 'dark': BUILTIN_THEMES['graphite']}

FONT_PREFERENCE = ('Inter', 'Inter Variable', 'IBM Plex Sans', 'Source Sans 3', 'Noto Sans',
                   'Cantarell', 'Ubuntu', 'Segoe UI', 'Helvetica Neue', 'DejaVu Sans')

_CURRENT = {}
_ICON_WIDGETS = []


def _rgb(value):
    v = str(value).lstrip('#')
    if len(v) == 3:
        v = ''.join(c * 2 for c in v)
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return '#%02X%02X%02X' % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def mix(a, b, t):
    """Linear blend: t=0 → a, t=1 → b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * float(t) for x, y in zip(ra, rb)))


def luminance(color):
    def lin(c):
        c = c / 255.
        return c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(color))
    return .2126 * r + .7152 * g + .0722 * b


def is_dark(tokens):
    return luminance(tokens.get('background', '#000000')) < .25


def complete_tokens(theme):
    """Fill every token from a theme that may only define the five base colours."""
    base = dict(BUILTIN_THEMES[DEFAULT_THEME])
    base.update({k: v for k, v in (theme or {}).items() if v not in (None, '')})
    bg, surface, fg, accent, muted = (base['background'], base['surface'], base['foreground'],
                                      base['accent'], base['muted'])
    dark = luminance(bg) < .25
    t = dict(base)
    t.setdefault('raised', mix(surface, fg, .045) if dark else surface)
    t.setdefault('sidebar', mix(bg, surface, .45))
    t.setdefault('input', mix(surface, bg, .55) if dark else surface)
    t.setdefault('subtle', mix(muted, bg, .38))
    t.setdefault('border', mix(surface, fg, .11 if dark else .13))
    t.setdefault('border_strong', mix(surface, fg, .20 if dark else .24))
    t.setdefault('hover', mix(surface, fg, .065 if dark else .05))
    t.setdefault('pressed', mix(surface, fg, .11 if dark else .09))
    t.setdefault('accent_hover', mix(accent, '#FFFFFF', .12) if dark else mix(accent, '#000000', .10))
    la = luminance(accent)
    t.setdefault('accent_fg', '#FFFFFF' if (1.05 / (la + .05)) >= ((la + .05) / .0537) else '#0B0D10')
    t.setdefault('accent_soft', mix(surface, accent, .20 if dark else .13))
    t.setdefault('selection', t['accent_soft'])
    t.setdefault('danger', '#F07070' if dark else '#C23A33')
    t.setdefault('success', '#4CC38A' if dark else '#1E8A55')
    t.setdefault('warning', '#E8B54D' if dark else '#B7791F')
    t.setdefault('font_family', '')
    try:
        t['font_size'] = max(7., min(20., float(t.get('font_size') or 10)))
    except (TypeError, ValueError):
        t['font_size'] = 10.
    try:
        t['radius'] = max(0, min(16, int(t.get('radius') if t.get('radius') is not None else 6)))
    except (TypeError, ValueError):
        t['radius'] = 6
    return t


def colors(widget=None):
    """Current resolved tokens (for custom-painted widgets)."""
    return dict(_CURRENT) if _CURRENT else complete_tokens(BUILTIN_THEMES[DEFAULT_THEME])


# ---------------------------------------------------------------- fonts
def load_bundled_fonts():
    """Register the bundled Inter family once (SIL OFL 1.1, see resources/fonts/OFL.txt)."""
    from PySide6.QtGui import QFontDatabase
    folder = Path(__file__).resolve().parents[1] / 'resources' / 'fonts'
    families = set()
    if folder.is_dir():
        for f in sorted(folder.glob('*.otf')) + sorted(folder.glob('*.ttf')):
            fid = QFontDatabase.addApplicationFont(str(f))
            if fid >= 0:
                families.update(QFontDatabase.applicationFontFamilies(fid))
    return families


def pick_font_family(preferred=''):
    from PySide6.QtGui import QFontDatabase
    available = set(QFontDatabase.families())
    for name in ((preferred,) if preferred else ()) + FONT_PREFERENCE:
        if name and name in available:
            return name
    return ''


# ---------------------------------------------------------------- icons
_I = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" ' \
     'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{d}</svg>'
ICONS = {
    'open': '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    'dataset': '<path d="M12 4 3.5 8.5 12 13l8.5-4.5z"/><path d="M3.5 12.5 12 17l8.5-4.5"/><path d="M3.5 16.2 12 20.7l8.5-4.5"/>',
    'export': '<path d="M12 15V4"/><path d="M7.5 8.5 12 4l4.5 4.5"/><path d="M5 13.5v5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-5"/>',
    'compare': '<rect x="3.5" y="5" width="7" height="14" rx="1.5"/><rect x="13.5" y="5" width="7" height="14" rx="1.5"/>',
    'ai': '<path d="M11 3.5l1.8 4.9 4.9 1.8-4.9 1.8L11 16.9l-1.8-4.9-4.9-1.8 4.9-1.8z"/><path d="M18 14.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    'fit': '<path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9"/><path d="M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9"/><path d="M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15"/><path d="M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15"/>',
    'line': '<path d="M6 18 18 6"/><circle cx="6" cy="18" r="1.8"/><circle cx="18" cy="6" r="1.8"/>',
    'rect': '<rect x="4" y="5" width="16" height="14" rx="1.5" stroke-dasharray="3 2.4"/>',
    'point': '<circle cx="12" cy="12" r="3"/><path d="M12 3v4M12 17v4M3 12h4M17 12h4"/>',
    'keep': '<path d="M9 4h6l-1 6 3 3H7l3-3z"/><path d="M12 13v7"/>',
    'crop': '<path d="M7 3v14h14"/><path d="M3 7h14v14"/>',
    'profile': '<path d="M4 4v16h16"/><path d="M7 15l4-5 3 3 5-6"/>',
    'molecule': '<path d="M12 3.5l7.5 4.3v8.4L12 20.5l-7.5-4.3V7.8z"/><circle cx="12" cy="12" r="2.2"/>',
    'info': '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 7.6v.1"/>',
    'prev': '<path d="M14.5 6 8.5 12l6 6"/>',
    'next': '<path d="M9.5 6l6 6-6 6"/>',
    'back': '<path d="M10 6 4 12l6 6"/><path d="M4.5 12H20"/>',
    'settings': '<path d="M4 7h9M18 7h2M4 17h3M12 17h8"/><circle cx="15.5" cy="7" r="2.2"/><circle cx="9.5" cy="17" r="2.2"/>',
    'run': '<path d="M8 5.5v13l10-6.5z"/>',
    'stop': '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    # v0.0.20: projects, Files panel and Appearance
    'theme': '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.1 0 1.7-.8 1.7-1.6 0-1.2-1.1-1.5-1.1-2.6 0-.9.7-1.5 1.6-1.5h2.1A4.2 4.2 0 0 0 20.5 11 7.9 7.9 0 0 0 12 3.5z"/><circle cx="7.6" cy="11" r=".9"/><circle cx="10" cy="7.4" r=".9"/><circle cx="14.5" cy="7.6" r=".9"/>',
    'project_new': '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M12 11v5M9.5 13.5h5"/>',
    'project_open': '<path d="M3.5 17.5V7.5A1.5 1.5 0 0 1 5 6h4l2 2h6.5A1.5 1.5 0 0 1 19 9.5V11"/><path d="M3.5 17.5 6 12h15l-2.5 5.5a1.5 1.5 0 0 1-1.4.9H4.6a1.1 1.1 0 0 1-1.1-.9z"/>',
    'add_scans': '<path d="M14 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3.5V8h4.5"/><path d="M12 11v6M9 14h6"/>',
    'clear_list': '<path d="M4 7h10M4 12h10M4 17h6"/><path d="M15 15l5 5M20 15l-5 5"/>',
    'select_mode': '<rect x="4" y="4" width="7" height="7" rx="1.5"/><path d="M5.8 7.6l1.3 1.3 2.3-2.6"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><path d="M5.8 16.6l1.3 1.3 2.3-2.6"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    'copy_to': '<rect x="8.5" y="8.5" width="11" height="11" rx="1.5"/><path d="M15.5 8.5V6A1.5 1.5 0 0 0 14 4.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/><path d="M12 14h5M15 12l2 2-2 2"/>',
    'close': '<path d="M6 6l12 12M18 6 6 18"/>',
    'trash': '<path d="M4.5 7h15"/><path d="M9 7V5h6v2"/><path d="M6.5 7l1 12.5h9l1-12.5"/>',
    'copy': '<rect x="8" y="8" width="11.5" height="11.5" rx="1.5"/><path d="M5 15.5V5.5A1 1 0 0 1 6 4.5h9.5"/>',
    'send': '<path d="M4 12 20 4l-5 16-3.5-6.5z"/><path d="M11.5 13.5 20 4"/>',
    'attach': '<path d="M15.5 7.5 8.8 14.2a2 2 0 0 0 2.8 2.8l6.9-6.9a4 4 0 0 0-5.7-5.7l-6.9 6.9a6 6 0 0 0 8.5 8.5l6.1-6.1"/>',
    'scan': '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M3.5 16l5-5 4 4 3-3 5 5"/><circle cx="15.5" cy="8.5" r="1.3"/>',
    'edit': '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    'refresh': '<path d="M19.5 12A7.5 7.5 0 1 1 17 6.4"/><path d="M19.5 4v4h-4"/>',
    'more': '<circle cx="6" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18" cy="12" r="1.2"/>',
    'chevron-down': '<path d="M6 9l6 6 6-6"/>',
    'chevron-up': '<path d="M6 15l6-6 6 6"/>',
    'check': '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    'minus': '<path d="M6 12h12"/>',
    'float': '<rect x="3.5" y="6.5" width="12" height="12" rx="1.5"/><path d="M12 3.5h8.5V12"/><path d="M20.5 3.5 13 11"/>',
    'tools': '<path d="M14.5 5.5a4 4 0 0 0 4 5.5l-8 8a2 2 0 0 1-3-3l8-8a4 4 0 0 0-1-2.5z"/>',
    'layers': '<path d="M12 4 3.5 8.5 12 13l8.5-4.5z"/><path d="M3.5 13 12 17.5 20.5 13"/>',
    'history': '<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4h4"/><path d="M12 8v4l3 2"/>',
    # v0.0.5: a real cog for the Settings button, plus library / literature glyphs.
    'gear': '<path d="M10.19 5.24 L10.56 2.91 L13.44 2.91 L13.81 5.24 L15.50 5.94 L17.41 4.56 L19.44 6.59 L18.06 8.50 L18.76 10.19 L21.09 10.56 L21.09 13.44 L18.76 13.81 L18.06 15.50 L19.44 17.41 L17.41 19.44 L15.50 18.06 L13.81 18.76 L13.44 21.09 L10.56 21.09 L10.19 18.76 L8.50 18.06 L6.59 19.44 L4.56 17.41 L5.94 15.50 L5.24 13.81 L2.91 13.44 L2.91 10.56 L5.24 10.19 L5.94 8.50 L4.56 6.59 L6.59 4.56 L8.50 5.94z"/><circle cx="12" cy="12" r="3.1"/>',
    'logs': '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M7 9.5l3 2.5-3 2.5"/><path d="M12.5 15h4.5"/>',
    'book': '<path d="M5 4.5h10.5A2.5 2.5 0 0 1 18 7v12.5H7.2A2.2 2.2 0 0 1 5 17.3z"/><path d="M5 17.3A2.2 2.2 0 0 1 7.2 15H18"/><path d="M8.5 8.5h6"/>',
    'import': '<path d="M12 4v11"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M5 13.5v5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-5"/>',
    'folder': '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    'link': '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    'save': '<path d="M5 4.5h11l3.5 3.5v11.5H5z"/><path d="M8 4.5v5h7v-5"/><rect x="8" y="13.5" width="8" height="6"/>',
    'mic': '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11v1a6.5 6.5 0 0 0 13 0v-1"/><path d="M12 18v2.5M8.5 20.5h7"/>',
    # v0.0.8: LaTeX editor, presentation editor and Overleaf.
    'latex': '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5"/><path d="M8.5 12.5h2.2l1.3 4 1.6-6h2"/>',
    'todo': '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M7.5 9l1.5 1.5 3-3M14 9.5h3M7.5 15l1.5 1.5 3-3M14 15.5h3"/>',
    'slides': '<rect x="3.5" y="4.5" width="17" height="11.5" rx="1.5"/><path d="M12 16v3.5M8.5 19.5h7"/><path d="M8 12.5l2.5-3 2 2 3-3.5"/>',
    'overleaf': '<path d="M19.5 4.5C11 4.5 5 9 5 15.5c0 2.5 1.6 4 3.8 4 5.2 0 8.7-6.5 10.7-15z"/><path d="M5 19.5c2.2-4.4 5.4-7.6 9.5-10"/>',
    'bold': '<path d="M7.5 5h5.5a3.25 3.25 0 0 1 0 6.5H7.5z"/><path d="M7.5 11.5h6.5a3.25 3.25 0 0 1 0 6.5H7.5z"/>',
    'italic': '<path d="M14 5h-4M14 19h-4M13.5 5l-3 14"/>',
    'underline': '<path d="M7.5 4.5v6a4.5 4.5 0 0 0 9 0v-6"/><path d="M6 20h12"/>',
    'text': '<path d="M5 6.5V5h14v1.5"/><path d="M12 5v14"/><path d="M9.5 19h5"/>',
    'formula': '<path d="M17.5 5.5h-9l5 6.5-5 6.5h9"/>',
    'image': '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><circle cx="9" cy="9.5" r="1.6"/><path d="M20.5 15.5l-5-5-9 9"/>',
    'video': '<rect x="3.5" y="6" width="12" height="12" rx="1.5"/><path d="M15.5 10.5l5-3v9l-5-3z"/>',
    'gif': '<rect x="3.5" y="5.5" width="17" height="13" rx="1.5"/><path d="M10 10.5H8.2a1.2 1.2 0 0 0-1.2 1.2v.6A1.2 1.2 0 0 0 8.2 13.5H10v-1.4"/><path d="M12.5 10.5v3"/><path d="M15 13.5v-3h2.2M15 12h1.6"/>',
    'shape': '<rect x="3.5" y="10" width="9" height="9.5" rx="1"/><circle cx="15.5" cy="8.5" r="5"/>',
    'undo': '<path d="M9 7.5 4.5 12 9 16.5"/><path d="M5 12h9.5a5 5 0 0 1 0 10H12"/>',
    'redo': '<path d="M15 7.5l4.5 4.5-4.5 4.5"/><path d="M19 12H9.5a5 5 0 0 0 0 10H12"/>',
    'search': '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    'play': '<path d="M8 5.5v13l10-6.5z"/>',
    'list': '<path d="M9 7h11M9 12h11M9 17h11"/><circle cx="5" cy="7" r=".8"/><circle cx="5" cy="12" r=".8"/><circle cx="5" cy="17" r=".8"/>',
    'numbered': '<path d="M10 7h10M10 12h10M10 17h10"/><path d="M4.5 5.5 6 5v4"/><path d="M4.5 14.5h2l-2 3h2"/>',
    'table': '<rect x="3.5" y="5" width="17" height="14" rx="1.5"/><path d="M3.5 10h17M3.5 14.5h17M9.5 5v14M15 5v14"/>',
    'align-left': '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
    'align-center': '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
    'align-right': '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
    'front': '<rect x="8.5" y="8.5" width="11" height="11" rx="1.2"/><path d="M15.5 8.5V5a.5.5 0 0 0-.5-.5H5a.5.5 0 0 0-.5.5v10c0 .3.2.5.5.5h3.5"/>',
    'back-layer': '<rect x="4.5" y="4.5" width="11" height="11" rx="1.2"/><path d="M15.5 8.5H19a.5.5 0 0 1 .5.5v10a.5.5 0 0 1-.5.5H9a.5.5 0 0 1-.5-.5v-3.5"/>',
    'sigma': '<path d="M17 5H7l6 7-6 7h10"/>',
    'comment': '<path d="M5 5.5h14v10H10l-4 3.5v-3.5H5z"/>',
    'fullscreen': '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    'zoom-in': '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5M8 10.5h5M10.5 8v5"/>',
    'zoom-out': '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5M8 10.5h5"/>',
    'download': '<path d="M12 4v11"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19.5h14"/>',
    'upload': '<path d="M12 15V4"/><path d="M7.5 8.5 12 4l4.5 4.5"/><path d="M5 19.5h14"/>',
    'file-plus': '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5"/><path d="M12.5 11v6M9.5 14h6"/>',
    'folder-plus': '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M12 10.5v5M9.5 13h5"/>',
    'menu': '<path d="M4 7h16M4 12h16M4 17h16"/>',
    'send-to': '<path d="M4 12h12"/><path d="M12 7l5 5-5 5"/><path d="M20 5v14"/>',
    # v0.1.0: calendar (same style as the Agent Hub calendar icon)
    'calendar': '<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17"/><path d="M8 3.5v3M16 3.5v3"/>',
}


def _svg(name, color):
    return _I.format(c=color, d=ICONS.get(name, ICONS['more']))


def _asset_dir(tokens):
    from spm_studio.core.paths import cache_dir
    key = hashlib.sha256(repr(sorted((k, str(v)) for k, v in tokens.items())).encode()).hexdigest()[:12]
    folder = cache_dir() / 'theme' / key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_assets(tokens):
    """Small SVG glyphs for combo arrows, spin buttons, check marks (theme coloured)."""
    folder = _asset_dir(tokens)
    files = {
        'arrow-down.svg': _svg('chevron-down', tokens['muted']),
        'arrow-up.svg': _svg('chevron-up', tokens['muted']),
        'arrow-down-disabled.svg': _svg('chevron-down', tokens['subtle']),
        'arrow-up-disabled.svg': _svg('chevron-up', tokens['subtle']),
        'check.svg': _I.format(c=tokens['accent_fg'], d=ICONS['check']).replace('stroke-width="1.75"', 'stroke-width="2.6"'),
        'partial.svg': _I.format(c=tokens['accent_fg'], d=ICONS['minus']).replace('stroke-width="1.75"', 'stroke-width="2.6"'),
        'radio.svg': f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" fill="{tokens["accent_fg"]}"/></svg>',
        'menu-check.svg': _svg('check', tokens['foreground']),
        'tab-close.svg': _svg('close', tokens['muted']),            # v0.0.20: project tabs
        'tab-close-hover.svg': _svg('close', tokens['foreground']),
    }
    for name, text in files.items():
        path = folder / name
        if not path.is_file() or path.read_text(encoding='utf8') != text:
            path.write_text(text, encoding='utf8')
    return folder


def icon(name, color=None):
    """A theme-coloured line icon (QIcon) from the built-in icon set."""
    from PySide6.QtGui import QIcon
    tokens = colors()
    folder = _asset_dir(tokens)
    col = color or tokens['foreground']
    path = folder / f'icon-{name}-{col.lstrip("#")}.svg'
    if not path.is_file():
        path.write_text(_svg(name, col), encoding='utf8')
    ic = QIcon(str(path))
    if color is None:
        # Distinct disabled glyph, still in the theme family.
        dis = folder / f'icon-{name}-{tokens["subtle"].lstrip("#")}.svg'
        if not dis.is_file():
            dis.write_text(_svg(name, tokens['subtle']), encoding='utf8')
        from PySide6.QtCore import QSize
        for size in (16, 18, 20, 24, 32):
            ic.addFile(str(dis), QSize(size, size), QIcon.Mode.Disabled)
    return ic


def set_icon(widget, name, *, color_token=None):
    """Assign an icon that follows theme changes."""
    try:
        widget.setIcon(icon(name, colors().get(color_token) if color_token else None))
    except Exception:
        return widget
    _ICON_WIDGETS.append((widget, name, color_token))
    return widget


DOCK_CLOSE_ICON = 18      # px, glyph of the dock close cross
DOCK_CLOSE_BUTTON = 28    # px, clickable area


def style_dock_titlebar(dock, keep_floatable: bool = False):
    """Dock header with a clearly visible close button (Logs, Assistant).

    Qt draws the built-in dock close button at the style's small-icon size and
    ignores ``setIconSize``, which left a cross that was hard to see and to
    hit. v0.0.5 therefore installs its own title bar: the panel title and one
    normal tool button (``DOCK_CLOSE_ICON`` px glyph in a ``DOCK_CLOSE_BUTTON``
    px target) that follows the theme. Dragging the bar still moves the dock;
    a detached (floating) panel keeps the operating system's own window frame.
    The separate float button stays removed (callers needing float keep their
    own explicit button).
    """
    from PySide6.QtWidgets import QDockWidget, QWidget, QHBoxLayout, QLabel
    from PySide6.QtCore import QSize, Qt
    if not keep_floatable:          # v0.1.0: the assistant keeps "drag out into a window of its own"
        dock.setFeatures(dock.features() & ~QDockWidget.DockWidgetFeature.DockWidgetFloatable)
    bar = QWidget(dock)
    bar.setObjectName('dockTitleBar')
    bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    # Qt may shrink the custom QDockWidget title bar below its layout's
    # size hint (on Windows, macOS and Xvfb), clipping the 28px close
    # button to ~25px. Reserve enough vertical room for its hit target.
    bar.setMinimumHeight(DOCK_CLOSE_BUTTON + 12)
    row = QHBoxLayout(bar)
    row.setContentsMargins(10, 4, 6, 4)
    row.setSpacing(6)
    title = QLabel(dock.windowTitle(), bar)
    title.setObjectName('dockTitleLabel')
    close = tool_button('', 'close', 'Close this panel', icon_only=True, parent=bar)
    close.setObjectName('dockCloseButton')
    close.setIconSize(QSize(DOCK_CLOSE_ICON, DOCK_CLOSE_ICON))
    close.setFixedSize(QSize(DOCK_CLOSE_BUTTON, DOCK_CLOSE_BUTTON))
    close.setAccessibleName('Close panel')
    close.clicked.connect(dock.close)
    row.addWidget(title, 1)
    row.addWidget(close)
    dock.windowTitleChanged.connect(title.setText)

    def sync(floating):
        # A detached panel keeps the window frame of the operating system (move, resize, close),
        # exactly as before; the custom bar is only used while the panel is docked.
        dock.setTitleBarWidget(None if floating else bar)

    dock.topLevelChanged.connect(sync)
    sync(dock.isFloating())
    dock.spm_close_button = close
    dock.spm_title_bar = bar
    return close


def _refresh_icons():
    alive = []
    for widget, name, token in _ICON_WIDGETS:
        try:
            widget.setIcon(icon(name, colors().get(token) if token else None))
            alive.append((widget, name, token))
        except RuntimeError:   # widget deleted
            continue
    _ICON_WIDGETS[:] = alive


# ---------------------------------------------------------------- stylesheet
def stylesheet(tokens, assets=None):
    """Complete application QSS for the resolved tokens."""
    t = complete_tokens(tokens)
    a = Path(assets) if assets else None
    r = int(t['radius'])
    rs = max(0, r - 2)
    px = max(9, round(float(t['font_size']) * 96 / 72))
    small = max(8, px - 2)

    def url(name):
        return f'url("{(a / name).as_posix()}")' if a else 'none'

    qss = f'''
* {{ outline: 0; }}
QWidget {{ color: @fg; font-size: {px}px; }}
QMainWindow, QDialog, QMessageBox {{ background: @bg; }}
QMainWindow::separator {{ background: @border; width: 1px; height: 1px; }}
QWidget#workbenchRoot {{ background: @bg; }}
QLabel {{ background: transparent; border: 0; }}
QLabel:disabled {{ color: @subtle; }}
QLabel#muted, QLabel[role="muted"], QLabel#BrandSubtitle {{ color: @muted; }}
QLabel#hint, QLabel[role="hint"] {{ color: @subtle; font-size: {small}px; }}
QLabel#sectionTitle, QLabel#eyebrow, QLabel[role="section"] {{ color: @muted; font-size: {small}px; font-weight: 600; letter-spacing: .4px; }}
QLabel#heading, QLabel[role="heading"] {{ font-size: {px + 3}px; font-weight: 600; }}
QLabel#BrandName {{ font-size: {px + 1}px; font-weight: 600; }}
QLabel#hero {{ font-size: {px * 2}px; font-weight: 700; }}
QLabel[chip="true"] {{ background: @hover; color: @muted; border-radius: {r}px; padding: 2px 8px; font-size: {small}px; }}

/* ---------- application header and toolbars ---------- */
QFrame#appHeader {{ background: @sidebar; border: 0; border-bottom: 1px solid @border; }}
QFrame#viewToolbar {{ background: transparent; border: 0; }}
QFrame#vSeparator {{ background: @border; min-width: 1px; max-width: 1px; margin: 5px 4px; }}
QScrollArea#headerScroll, QScrollArea#headerScroll > QWidget, QScrollArea#headerScroll > QWidget > QWidget {{ background: @sidebar; border: 0; }}

/* ---------- buttons ---------- */
QPushButton, QToolButton {{
    background: @raised; color: @fg; border: 1px solid @border; border-radius: {r}px;
    padding: 4px 11px; min-height: 20px; font-weight: 500; }}
QPushButton:hover, QToolButton:hover {{ background: @hover; border-color: @border_strong; }}
QPushButton:pressed, QToolButton:pressed {{ background: @pressed; }}
QPushButton:checked, QToolButton:checked {{ background: @accent_soft; color: @fg; border-color: @accent; }}
QPushButton:disabled, QToolButton:disabled {{ color: @subtle; background: transparent; border-color: @border; }}
QPushButton:focus, QToolButton:focus {{ border-color: @accent; }}
QPushButton:default {{ border-color: @accent; }}
QPushButton#primaryAction, QPushButton[primary="true"], QToolButton[primary="true"] {{
    background: @accent; color: @accent_fg; border: 1px solid @accent; font-weight: 600; }}
QPushButton#primaryAction:hover, QPushButton[primary="true"]:hover, QToolButton[primary="true"]:hover {{
    background: @accent_hover; border-color: @accent_hover; }}
QPushButton[primary="true"]:disabled, QToolButton[primary="true"]:disabled {{ background: @hover; color: @subtle; border-color: @border; }}
QPushButton[destructive="true"], QToolButton[destructive="true"] {{ color: @danger; }}
QPushButton[destructive="true"]:hover, QToolButton[destructive="true"]:hover {{ border-color: @danger; }}
QToolButton[recording="true"] {{ background: @danger; border-color: @danger; color: @accent_fg; }}
QToolButton[recording="true"]:hover {{ background: @danger; border-color: @danger; }}
/* quiet buttons: toolbar glyphs, header actions, inline links */
QPushButton[flat="true"], QToolButton[flat="true"], QToolButton[autoRaise="true"] {{
    background: transparent; border: 1px solid transparent; padding: 4px 8px; }}
QPushButton[flat="true"]:hover, QToolButton[flat="true"]:hover, QToolButton[autoRaise="true"]:hover {{ background: @hover; border-color: transparent; }}
QPushButton[flat="true"]:checked, QToolButton[flat="true"]:checked {{ background: @accent_soft; border-color: transparent; color: @fg; }}
QPushButton[flat="true"]:disabled, QToolButton[flat="true"]:disabled {{ background: transparent; border-color: transparent; }}
QToolButton[iconOnly="true"] {{ padding: 4px; min-width: 22px; }}
QToolButton::menu-indicator {{ image: {url('arrow-down.svg')}; subcontrol-origin: padding; subcontrol-position: center right; width: 10px; height: 10px; right: 5px; }}
QToolButton[popupMode="1"] {{ padding-right: 22px; }}
QToolButton[popupMode="2"] {{ padding-right: 20px; }}
QToolButton::menu-button {{ border: 0; border-left: 1px solid @border; width: 18px; border-top-right-radius: {r}px; border-bottom-right-radius: {r}px; }}
QToolButton::menu-button:hover {{ background: @pressed; }}
QToolButton::menu-arrow {{ image: {url('arrow-down.svg')}; width: 10px; height: 10px; }}
/* segmented control (sidebar Files / Tools / Metadata) */
QPushButton[segment="true"] {{ background: transparent; border: 0; border-radius: {rs}px; color: @muted; padding: 4px 8px; }}
QPushButton[segment="true"]:hover {{ color: @fg; background: @hover; }}
QPushButton[segment="true"]:checked {{ background: @raised; color: @fg; font-weight: 600; }}
QFrame#segmented {{ background: @input; border: 1px solid @border; border-radius: {r}px; }}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QAbstractSpinBox {{
    background: @input; color: @fg; border: 1px solid @border; border-radius: {r}px;
    padding: 3px 8px; min-height: 20px; selection-background-color: @accent; selection-color: @accent_fg; }}
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {{ border-color: @border_strong; }}
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: @accent; }}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {{ color: @subtle; background: transparent; }}
QLineEdit[readOnly="true"] {{ background: transparent; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: 0; }}
QComboBox::down-arrow {{ image: {url('arrow-down.svg')}; width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: {url('arrow-down-disabled.svg')}; }}
QComboBox QAbstractItemView {{ background: @raised; color: @fg; border: 1px solid @border_strong; border-radius: {r}px;
    padding: 4px; selection-background-color: @accent_soft; selection-color: @fg; outline: 0; }}
QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 0 8px; border-radius: {rs}px; }}
QAbstractSpinBox {{ padding-right: 20px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 18px; border: 0; background: transparent; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: {r}px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: {r}px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: @hover; }}
QAbstractSpinBox::up-arrow {{ image: {url('arrow-up.svg')}; width: 10px; height: 10px; }}
QAbstractSpinBox::down-arrow {{ image: {url('arrow-down.svg')}; width: 10px; height: 10px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: {url('arrow-up-disabled.svg')}; }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: {url('arrow-down-disabled.svg')}; }}
QPlainTextEdit, QTextEdit, QTextBrowser {{ background: @input; color: @fg; border: 1px solid @border; border-radius: {r}px;
    padding: 6px; selection-background-color: @accent; selection-color: @accent_fg; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: @subtle; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; border: 1px solid @border_strong; background: @input; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: @accent; }}
QCheckBox::indicator:checked {{ background: @accent; border-color: @accent; image: {url('check.svg')}; }}
QCheckBox::indicator:indeterminate {{ background: @accent; border-color: @accent; image: {url('partial.svg')}; }}
QRadioButton::indicator:checked {{ background: @accent; border-color: @accent; image: {url('radio.svg')}; }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ background: @hover; border-color: @border; }}
QSlider::groove:horizontal {{ height: 4px; background: @border; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: @accent; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; background: @fg; border: 2px solid @accent; }}
QSlider::groove:vertical {{ width: 4px; background: @border; border-radius: 2px; }}
QSlider::handle:vertical {{ width: 14px; height: 14px; margin: 0 -6px; border-radius: 7px; background: @fg; border: 2px solid @accent; }}

/* ---------- lists, tables, trees ---------- */
QListView, QListWidget, QTreeView, QTreeWidget, QTableView, QTableWidget {{
    background: @input; alternate-background-color: @surface; color: @fg; border: 1px solid @border; border-radius: {r}px;
    padding: 3px; gridline-color: @border; selection-background-color: @accent_soft; selection-color: @fg; }}
QAbstractItemView::item {{ min-height: 24px; padding: 0 6px; border-radius: {rs}px; }}
QAbstractItemView::item:hover:!selected {{ background: @hover; }}
QAbstractItemView::item:selected {{ background: @accent_soft; color: @fg; }}
QHeaderView {{ background: transparent; border: 0; }}
QHeaderView::section {{ background: @surface; color: @muted; border: 0; border-bottom: 1px solid @border;
    padding: 5px 8px; font-weight: 600; font-size: {small}px; }}
QTableCornerButton::section {{ background: @surface; border: 0; }}

/* ---------- containers ---------- */
QGroupBox {{ background: @surface; border: 1px solid @border; border-radius: {r + 2}px;
    margin-top: {px + 10}px; padding: 10px 10px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 2px; top: 1px;
    padding: 0 2px; color: @muted; font-size: {small}px; font-weight: 600; }}
QGroupBox::indicator {{ width: 14px; height: 14px; }}
QGroupBox[flat="true"] {{ background: transparent; border: 0; border-top: 1px solid @border; border-radius: 0; padding: 8px 0 0 0; }}
QTabWidget::pane {{ border: 0; background: transparent; top: -1px; }}
QTabWidget::tab-bar {{ left: 4px; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: @muted; border: 0; border-bottom: 2px solid transparent;
    padding: 7px 12px; margin-right: 2px; font-weight: 500; }}
QTabBar::tab:hover {{ color: @fg; }}
QTabBar::tab:selected {{ color: @fg; border-bottom-color: @accent; font-weight: 600; }}
QTabBar::tab:disabled {{ color: @subtle; }}
QTabBar::close-button {{ subcontrol-position: right; }}
QTabBar#ProjectTabsV0020 {{ background: transparent; }}
QTabBar#ProjectTabsV0020::tab {{ padding: 5px 10px 5px 12px; min-width: 90px; max-width: 260px; }}
QTabBar#ProjectTabsV0020::close-button {{ image: {url('tab-close.svg')}; width: 14px; height: 14px; margin-left: 4px;
    border-radius: 7px; }}
QTabBar#ProjectTabsV0020::close-button:hover {{ image: {url('tab-close-hover.svg')}; background: @hover; }}
QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QStackedWidget {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 5px; }}
QSplitter::handle:vertical {{ height: 5px; }}
QSplitter::handle:hover {{ background: @accent_soft; }}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: @border; }}
QFrame#card, QFrame#cardPanel {{ background: @surface; border: 1px solid @border; border-radius: {r + 2}px; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: @border_strong; border-radius: 3px; min-height: 28px; margin: 0 1px; }}
QScrollBar::handle:horizontal {{ background: @border_strong; border-radius: 3px; min-width: 28px; margin: 1px 0; }}
QScrollBar::handle:hover {{ background: @muted; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: 0; background: transparent; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- menus ---------- */
QMenuBar {{ background: @bg; color: @fg; border: 0; padding: 2px 6px; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; border-radius: {rs}px; }}
QMenuBar::item:selected {{ background: @hover; }}
QMenuBar::item:pressed {{ background: @pressed; }}
QMenu {{ background: @raised; color: @fg; border: 1px solid @border_strong; border-radius: {r + 2}px; padding: 5px; }}
QMenu::item {{ padding: 5px 28px 5px 12px; border-radius: {rs}px; background: transparent; }}
QMenu::item:selected {{ background: @accent_soft; color: @fg; }}
QMenu::item:disabled {{ color: @subtle; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: @border; margin: 5px 6px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
QMenu::indicator:checked {{ image: {url('menu-check.svg')}; }}
QMenu::right-arrow {{ width: 10px; height: 10px; }}
QMenu::section {{ color: @muted; font-size: {small}px; font-weight: 600; padding: 6px 12px 2px 12px; }}

/* ---------- docks, status, tooltips, progress ---------- */
QDockWidget {{ color: @fg; }}
QDockWidget::title {{ background: @sidebar; text-align: left; padding: 6px 10px; border-bottom: 1px solid @border; font-weight: 600; }}
QDockWidget::close-button, QDockWidget::float-button {{ border: 0; background: transparent; padding: 2px; icon-size: 14px; }}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{ background: @hover; border-radius: {rs}px; }}
QWidget#dockTitleBar {{ background: @sidebar; border-bottom: 1px solid @border; }}
QLabel#dockTitleLabel {{ font-weight: 600; }}
QToolButton#dockCloseButton {{ padding: 0; border: 1px solid transparent; border-radius: {rs}px; background: transparent; }}
QToolButton#dockCloseButton:hover {{ background: @hover; border-color: @border_strong; }}
QToolButton#dockCloseButton:pressed {{ background: @pressed; }}
QStatusBar {{ background: @sidebar; color: @muted; border-top: 1px solid @border; font-size: {small}px; }}
QStatusBar::item {{ border: 0; }}
QStatusBar QLabel {{ color: @muted; }}
QToolTip {{ background: @raised; color: @fg; border: 1px solid @border_strong; border-radius: {rs}px; padding: 5px 8px; }}
QProgressBar {{ background: @hover; border: 1px solid @border; border-radius: 6px; text-align: center; color: @fg;
    min-height: 12px; max-height: 12px; font-size: {small}px; font-weight: 600; }}
QProgressBar::chunk {{ background: @accent; border-radius: 5px; }}
/* v0.0.5: the bars shown while a script runs or the assistant works are tall enough to read */
QProgressBar[role="activity"] {{ min-height: 18px; max-height: 18px; border-radius: 9px; }}
QProgressBar[role="activity"]::chunk {{ border-radius: 8px; }}
QFrame#activityStrip {{ background: @accent_soft; border: 1px solid @border; border-radius: {r}px; }}
QFrame#activityStrip QLabel {{ color: @fg; font-weight: 600; }}
QToolButton#SettingsGearV005 {{ padding: 5px; min-width: 26px; }}
QLabel#aboutTitle {{ font-size: {px + 8}px; font-weight: 700; }}
/* v0.0.7: choice cards of the assistant Quick start page */
QFrame#choiceCard {{ background: @surface; border: 1px solid @border; border-radius: {r}px; }}
QFrame#choiceCard[selected="true"] {{ border: 1px solid @accent; background: @accent_soft; }}
QRadioButton#choiceTitle {{ font-weight: 600; font-size: {px + 1}px; }}
QLabel#badge {{ background: @accent; color: @accent_fg; border-radius: {rs}px; padding: 1px 7px;
    font-size: {small}px; font-weight: 600; }}
QMessageBox QLabel {{ min-height: 20px; }}
QDialogButtonBox {{ background: transparent; padding-top: 6px; }}
QToolBar {{ background: transparent; border: 0; spacing: 4px; padding: 2px; }}
QToolBar::separator {{ background: @border; width: 1px; margin: 4px 4px; }}
QCalendarWidget QWidget {{ alternate-background-color: @surface; }}
/* v0.0.8: LaTeX editor, presentation editor, launchers */
QFrame#docHeader {{ background: @sidebar; border: 0; border-bottom: 1px solid @border; }}
QFrame#docRibbon {{ background: @surface; border: 0; border-bottom: 1px solid @border; }}
QLabel#docTitle {{ font-size: {px + 1}px; font-weight: 600; }}
QLabel#docKind {{ color: @muted; font-size: {small}px; font-weight: 600; letter-spacing: .4px; }}
QFrame#docPanel {{ background: @surface; border: 1px solid @border; border-radius: {r}px; }}
QLabel#panelTitle {{ color: @muted; font-size: {small}px; font-weight: 600; letter-spacing: .4px; padding: 2px 2px; }}
QPlainTextEdit#latexCode {{ background: @input; border: 0; border-radius: 0; padding: 0; font-size: {px + 1}px; }}
QWidget#lineGutter {{ background: @surface; }}
QFrame#pdfPane {{ background: @bg; border: 0; }}
/* v0.0.20: the page list of the Settings windows (never cut, comfortable rows) */
QListWidget#SettingsNavigationV005 {{ background: @sidebar; border: 0; border-radius: {r + 2}px; padding: 6px 4px;
    outline: 0; }}
QListWidget#SettingsNavigationV005::item {{ min-height: 30px; padding: 4px 10px; margin: 1px 2px; border: 0;
    border-radius: {rs + 2}px; color: @fg; }}
QListWidget#SettingsNavigationV005::item:hover:!selected {{ background: @hover; }}
QListWidget#SettingsNavigationV005::item:selected {{ background: @accent_soft; color: @fg; font-weight: 600; }}
QListWidget#slideThumbs {{ background: @sidebar; border: 0; border-right: 1px solid @border; border-radius: 0; padding: 6px; }}
QListWidget#slideThumbs::item {{ border: 2px solid transparent; border-radius: {r}px; padding: 4px; margin: 2px; }}
QListWidget#slideThumbs::item:selected {{ border-color: @accent; background: @accent_soft; }}
QPlainTextEdit#speakerNotes {{ border: 0; border-top: 1px solid @border; border-radius: 0; }}
QFrame#launcherCard {{ background: @surface; border: 1px solid @border; border-radius: {r + 2}px; }}
QFrame#launcherCard:hover {{ border-color: @accent; }}
QLabel#launcherTitle {{ font-size: {px + 1}px; font-weight: 600; }}
QLabel#errorBadge {{ background: @danger; color: @accent_fg; border-radius: 8px; padding: 0 6px; font-size: {small}px; font-weight: 700; }}
QLabel#warnBadge {{ background: @warning; color: @bg; border-radius: 8px; padding: 0 6px; font-size: {small}px; font-weight: 700; }}
QFrame#findBar {{ background: @surface; border: 0; border-top: 1px solid @border; }}
/* v0.0.18: normalised pieces shared by every window */
QLabel#stepBadge {{ border: 1.5px solid @fg; border-radius: 13px; padding: 2px 9px; min-height: 18px;
    font-weight: 600; font-size: {small + 1}px; background: transparent; }}
QLabel#stepTitle {{ font-weight: 600; font-size: {px + 1}px; }}
QToolButton[attention="true"] {{ color: @accent; }}
QToolButton[attention="true"]:!checked {{ border: 1px solid @accent; }}
QLabel#BetaBadgeV0014 {{ background: @accent_soft; color: @fg; border: 1px solid @accent; border-radius: 8px;
    padding: 0 7px; font-size: {small}px; font-weight: 700; }}
QDialog#DocViewerV0018 {{ background: @bg; }}
QTextBrowser#docBody {{ background: @bg; border: 0; border-radius: 0; padding: 0; }}
QListWidget#docOutline {{ background: @sidebar; border: 0; border-right: 1px solid @border; border-radius: 0;
    padding: 8px 4px; }}
QListWidget#docOutline::item {{ min-height: 22px; color: @muted; }}
QListWidget#docOutline::item:selected {{ color: @fg; }}
QLabel#emptyState, QLabel#TodoEmptyHintV0014 {{ color: @muted; font-size: {px + 1}px; }}
QDialog[spmRounded="true"], QMessageBox[spmRounded="true"] {{ background: transparent; }}
QLabel#popupTitle {{ color: @muted; font-weight: 600; font-size: {small}px; }}
/* v0.0.19: no coloured check / cross icons on pop-up buttons */
QDialogButtonBox {{ dialogbuttonbox-buttons-have-icons: 0; }}
'''
    from .studio_design import is_studio, overlay as studio_overlay
    if is_studio(t):
        qss += studio_overlay(t)
    for key in sorted(COLOR_TOKENS, key=len, reverse=True):
        alias = {'background': 'bg', 'foreground': 'fg'}.get(key, key)
        qss = qss.replace('@' + alias, str(t[key]))
    return qss


def appearance_settings():
    from PySide6.QtCore import QSettings
    return QSettings('SPM Studio', 'Appearance AI 0.7')


def apply_theme(theme, app=None):
    """Apply ``theme`` (dict of tokens, partial allowed) to the whole application."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QColor, QPalette, QFont
    app = app or QApplication.instance()
    if app is None:
        return None
    from .studio_design import TONES, is_studio
    TONES.install(app)
    from .dialogs import install_dialog_style
    install_dialog_style()
    from .ergonomics import install as install_ergonomics
    install_ergonomics(app)
    t = complete_tokens(theme)
    _CURRENT.clear()
    _CURRENT.update(t)
    if app.property('spmStyleInstalled') is None:
        app.setStyle('Fusion')
        load_bundled_fonts()
        app.setProperty('spmStyleInstalled', True)
    palette = QPalette()
    roles = [('Window', 'background'), ('WindowText', 'foreground'), ('Base', 'input'),
             ('AlternateBase', 'surface'), ('Text', 'foreground'), ('Button', 'raised'),
             ('ButtonText', 'foreground'), ('Highlight', 'accent'), ('HighlightedText', 'accent_fg'),
             ('ToolTipBase', 'raised'), ('ToolTipText', 'foreground'), ('PlaceholderText', 'subtle'),
             ('Link', 'accent'), ('LinkVisited', 'accent'), ('BrightText', 'danger'),
             ('Dark', 'border_strong'), ('Mid', 'border'), ('Midlight', 'hover'), ('Light', 'raised'),
             ('Shadow', 'background')]
    for role, key in roles:
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(t[key]))
    for role in ('Text', 'WindowText', 'ButtonText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor(t['subtle']))
    app.setPalette(palette)
    family = pick_font_family(str(t.get('font_family') or ''))
    font = QFont(family) if family else QFont()
    font.setPointSizeF(float(t['font_size']))
    font.setStyleHint(QFont.StyleHint.SansSerif)
    try:
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    except Exception:
        pass
    app.setFont(font)
    app.setProperty('researchAppearance', 'dark' if is_dark(t) else 'light')
    assets = _write_assets(t)
    app.setStyleSheet(stylesheet(t, assets))
    TONES.set_enabled(is_studio(t), app)
    _refresh_icons()
    # Custom painted canvases re-read colours; scientific/export colours never depend on the UI theme.
    for widget in app.allWidgets():
        widget.update()
    return t


def apply_appearance(mode=None):
    """Back-compat: 'light' / 'dark' map to the built-in Porcelain / Graphite themes."""
    settings = appearance_settings()
    mode = mode or str(settings.value('mode', 'dark'))
    theme = BUILTIN_THEMES['porcelain' if mode == 'light' else 'graphite']
    settings.setValue('mode', 'light' if mode == 'light' else 'dark')
    return apply_theme(theme)


def step_row(number, text, parent=None):
    """A numbered step: the number in a round outlined badge ("01"), then a short title (v0.0.18)."""
    from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
    row = QWidget(parent)
    row.setObjectName('stepRow')
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 6, 0, 2)
    lay.setSpacing(10)
    badge = QLabel(f'{int(number):02d}', row)
    badge.setObjectName('stepBadge')
    badge.setAccessibleName(f'Step {int(number)}')
    title = QLabel(text, row)
    title.setObjectName('stepTitle')
    title.setWordWrap(True)
    lay.addWidget(badge)
    lay.addWidget(title, 1)
    row.badge, row.title = badge, title
    return row


def separator(parent=None):
    """Thin vertical divider for toolbars."""
    from PySide6.QtWidgets import QFrame
    line = QFrame(parent)
    line.setObjectName('vSeparator')
    line.setFrameShape(QFrame.Shape.NoFrame)
    line.setFixedWidth(1)
    return line


def tool_button(text='', icon_name=None, tooltip='', *, checkable=False, icon_only=False, flat=True,
                menu=None, primary=False, parent=None):
    """The one toolbar button used everywhere (consistent size, icon, tooltip)."""
    from PySide6.QtWidgets import QToolButton
    from PySide6.QtCore import Qt, QSize
    b = QToolButton(parent)
    b.setText(text)
    b.setToolTip(tooltip or text)
    b.setCheckable(checkable)
    b.setIconSize(QSize(16, 16))
    if icon_name:
        set_icon(b, icon_name, color_token='accent_fg' if primary else None)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if (icon_only or not text) else
                         Qt.ToolButtonStyle.ToolButtonTextBesideIcon if icon_name else
                         Qt.ToolButtonStyle.ToolButtonTextOnly)
    if icon_only:
        b.setProperty('iconOnly', True)
    if flat and not primary:
        b.setProperty('flat', True)
    if primary:
        b.setProperty('primary', True)
    if menu is not None:
        b.setMenu(menu)
        b.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def scroll_toolbar(layout, parent_layout, height=46):
    """Keep every action reachable when the window is narrow."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget, QScrollArea, QSizePolicy
    content = QWidget()
    content.setLayout(layout)
    scroll = QScrollArea()
    scroll.setObjectName('headerScroll')
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    scroll.setFixedHeight(height)
    parent_layout.addWidget(scroll)
    return scroll


def add_appearance_menu(window):
    """Standalone windows share the same theme actions."""
    from PySide6.QtGui import QAction
    menu = window.menuBar().addMenu('Appearance')
    for name, theme in BUILTIN_THEMES.items():
        action = QAction(name.title(), window)
        action.triggered.connect(lambda checked=False, th=theme: apply_theme(th))
        menu.addAction(action)
