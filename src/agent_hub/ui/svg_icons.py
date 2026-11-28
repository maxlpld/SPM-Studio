"""Line icons of Agent Hub: the same 24 px SVG set as SPM Studio (stroke 1.75, round caps and joins),
coloured from the live theme tokens. Icons that SPM Studio does not have (brainstorm, dock, full access — an
octopus: its tentacles reach anything —, layouts, archive, help, calendar, to-do, mail …) are drawn in the
same style. No emoji or font glyphs are used anywhere.
"""
from __future__ import annotations

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{d}</svg>')

ICONS = {
    'attach': '<path d="M15.5 7.5 8.8 14.2a2 2 0 0 0 2.8 2.8l6.9-6.9a4 4 0 0 0-5.7-5.7l-6.9 6.9a6 6 0 0 0 8.5 8.5l6.1-6.1"/>',
    'mic': '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11v1a6.5 6.5 0 0 0 13 0v-1"/><path d="M12 18v2.5M8.5 20.5h7"/>',
    'stop': '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>',
    'send': '<path d="M4 12 20 4l-5 16-3.5-6.5z"/><path d="M11.5 13.5 20 4"/>',
    'close': '<path d="M6 6l12 12M18 6 6 18"/>',
    'settings': '<path d="M4 7h9M18 7h2M4 17h3M12 17h8"/><circle cx="15.5" cy="7" r="2.2"/><circle cx="9.5" cy="17" r="2.2"/>',
    'gear': '<path d="M10.19 5.24 L10.56 2.91 L13.44 2.91 L13.81 5.24 L15.50 5.94 L17.41 4.56 L19.44 6.59 L18.06 8.50 L18.76 10.19 L21.09 10.56 L21.09 13.44 L18.76 13.81 L18.06 15.50 L19.44 17.41 L17.41 19.44 L15.50 18.06 L13.81 18.76 L13.44 21.09 L10.56 21.09 L10.19 18.76 L8.50 18.06 L6.59 19.44 L4.56 17.41 L5.94 15.50 L5.24 13.81 L2.91 13.44 L2.91 10.56 L5.24 10.19 L5.94 8.50 L4.56 6.59 L6.59 4.56 L8.50 5.94z"/><circle cx="12" cy="12" r="3.1"/>',
    'refresh': '<path d="M19.5 12A7.5 7.5 0 1 1 17 6.4"/><path d="M19.5 4v4h-4"/>',
    'copy': '<rect x="8" y="8" width="11.5" height="11.5" rx="1.5"/><path d="M5 15.5V5.5A1 1 0 0 1 6 4.5h9.5"/>',
    'edit': '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    'more': '<circle cx="6" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18" cy="12" r="1.2"/>',
    'menu': '<path d="M4 7h16M4 12h16M4 17h16"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'float': '<rect x="3.5" y="6.5" width="12" height="12" rx="1.5"/><path d="M12 3.5h8.5V12"/><path d="M20.5 3.5 13 11"/>',
    'scan': '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M3.5 16l5-5 4 4 3-3 5 5"/><circle cx="15.5" cy="8.5" r="1.3"/>',
    'info': '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 7.6v.1"/>',
    'search': '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    'trash': '<path d="M4.5 7h15"/><path d="M9 7V5h6v2"/><path d="M6.5 7l1 12.5h9l1-12.5"/>',
    'check': '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    'chevron-down': '<path d="M6 9l6 6 6-6"/>',
    'chevron-up': '<path d="M6 15l6-6 6 6"/>',
    'folder': '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    'ai': '<path d="M11 3.5l1.8 4.9 4.9 1.8-4.9 1.8L11 16.9l-1.8-4.9-4.9-1.8 4.9-1.8z"/><path d="M18 14.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    'history': '<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4h4"/><path d="M12 8v4l3 2"/>',
    'keep': '<path d="M9 4h6l-1 6 3 3H7l3-3z"/><path d="M12 13v7"/>',
    'compare': '<rect x="3.5" y="5" width="7" height="14" rx="1.5"/><rect x="13.5" y="5" width="7" height="14" rx="1.5"/>',
    'download': '<path d="M12 4v11"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19.5h14"/>',
    'export': '<path d="M12 15V4"/><path d="M7.5 8.5 12 4l4.5 4.5"/><path d="M5 13.5v5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-5"/>',
    'import': '<path d="M12 4v11"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M5 13.5v5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-5"/>',
    'minus': '<path d="M6 12h12"/>',
    'link': '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    'run': '<path d="M8 5.5v13l10-6.5z"/>',
    'brainstorm': '<path d="M9.5 17.5h5M10.5 20.5h3"/><path d="M12 3.5a5.8 5.8 0 0 0-3.4 10.5c.6.5.9 1.1.9 1.9v.1h5v-.1c0-.8.3-1.4.9-1.9A5.8 5.8 0 0 0 12 3.5z"/>',
    'dock': '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M20.5 4.5 13.5 11.5"/><path d="M13.5 7.5v4h4"/>',
    'full': '<path d="M7 12.5V9.3a5 5.3 0 0 1 10 0v3.2"/><path d="M10 9.4v.1M14 9.4v.1"/>'
            '<path d="M7 12.5c-.2 2.2-2.6 2.6-3.1 4.5-.4 1.4 1 2.3 2.1 1.4"/><path d="M9.5 13c.2 2.6-.6 4.8-2 6.6"/>'
            '<path d="M12 13.2c-.9 2.2.9 4.3 0 6.8"/><path d="M14.5 13c-.2 2.6.6 4.8 2 6.6"/>'
            '<path d="M17 12.5c.2 2.2 2.6 2.6 3.1 4.5.4 1.4-1 2.3-2.1 1.4"/>',
    'classic': '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M14.5 4.5v15"/><path d="M16.8 8.5h1.7M16.8 11.5h1.7"/>',
    'archive': '<rect x="3.5" y="4.5" width="17" height="4.5" rx="1"/><path d="M5 9v9.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V9"/><path d="M10 13h4"/>',
    'help': '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.6a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.1-2.4 3.6"/><path d="M12 16.9v.1"/>',
    'layout-single': '<rect x="4" y="5" width="16" height="14" rx="1.5"/>',
    'layout-columns': '<rect x="3.5" y="5" width="7" height="14" rx="1.5"/><rect x="13.5" y="5" width="7" height="14" rx="1.5"/>',
    'layout-grid': '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    'warning': '<path d="M12 4.5 3 19.5h18z"/><path d="M12 10v4.5"/><path d="M12 17.2v.1"/>',
    'regenerate': '<path d="M19.5 12A7.5 7.5 0 1 1 17 6.4"/><path d="M19.5 4v4h-4"/><path d="M10 9.5v5l4-2.5z"/>',
    'prompt': '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5"/><path d="M8.8 12.5l2 1.7-2 1.8M12.5 16.5h3"/>',
    'chat-new': '<path d="M5 5.5h14v10H10l-4 3.5v-3.5H5z"/><path d="M12 8v5M9.5 10.5h5"/>',
    'usage': '<path d="M4 19.5h16"/><path d="M7 16v-4M12 16V7M17 16v-6"/>',
    # ---- 0.3: calendar, to-do, e-mail, sidebar
    'calendar': '<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17"/><path d="M8 3.5v3M16 3.5v3"/>',
    'calendar-day': '<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17"/><path d="M8 3.5v3M16 3.5v3"/><rect x="7.5" y="12.5" width="4" height="4" rx=".8"/>',
    'calendar-week': '<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17"/><path d="M8 3.5v3M16 3.5v3"/><path d="M7 14h10"/>',
    'calendar-month': '<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17"/><path d="M8 3.5v3M16 3.5v3"/><path d="M7.5 13h.1M12 13h.1M16.5 13h.1M7.5 16.5h.1M12 16.5h.1M16.5 16.5h.1"/>',
    'schedule': '<path d="M9 6.5h11M9 12h11M9 17.5h11"/><path d="M4.5 6.5h.1M4.5 12h.1M4.5 17.5h.1"/>',
    'todo': '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 12.2l2.6 2.6L16 9.4"/>',
    'checklist': '<path d="M4 6.5l1.5 1.5L8 5.5M4 12.5l1.5 1.5L8 11.5"/><path d="M11 7h9M11 13h9M11 19h9"/><path d="M5 19h1.5"/>',
    'circle': '<circle cx="12" cy="12" r="7.5"/>',
    'circle-check': '<circle cx="12" cy="12" r="7.5"/><path d="M8.6 12.2l2.3 2.3 4.5-4.6"/>',
    'mail': '<rect x="3.5" y="5.5" width="17" height="13" rx="1.5"/><path d="M4 6.5l8 6 8-6"/>',
    'mail-send': '<rect x="3.5" y="5.5" width="12" height="10" rx="1.5"/><path d="M4 6.5l5.5 4.5 5.5-4.5"/><path d="M14 19h6.5M18 16.5l2.5 2.5-2.5 2.5"/>',
    'inbox': '<path d="M4 13.5 6.5 5.5h11l2.5 8v5A1.5 1.5 0 0 1 18.5 20h-13A1.5 1.5 0 0 1 4 18.5z"/><path d="M4 13.5h4.5l1 2h5l1-2H20"/>',
    'bell': '<path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 1.5H5z"/><path d="M10 20.5h4"/>',
    'repeat': '<path d="M5 11V9.5A2.5 2.5 0 0 1 7.5 7H18"/><path d="M15.5 4.5 18 7l-2.5 2.5"/><path d="M19 13v1.5a2.5 2.5 0 0 1-2.5 2.5H6"/><path d="M8.5 19.5 6 17l2.5-2.5"/>',
    'tag': '<path d="M4 4.5h7.5l8.5 8.5-7 7-8.5-8.5z"/><path d="M8.2 8.7v.1"/>',
    'flag': '<path d="M5.5 20.5V4"/><path d="M5.5 4.5h11l-2.5 4 2.5 4h-11"/>',
    'clock': '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    'location': '<path d="M12 20.5s6-5.6 6-10.5a6 6 0 0 0-12 0c0 4.9 6 10.5 6 10.5z"/><circle cx="12" cy="10" r="2.2"/>',
    'notes': '<path d="M6 3.5h12v17H6z"/><path d="M9 8h6M9 12h6M9 16h3.5"/>',
    'chevron-left': '<path d="M15 6l-6 6 6 6"/>',
    'chevron-right': '<path d="M9 6l6 6-6 6"/>',
    'eye': '<path d="M3 12s3.3-6 9-6 9 6 9 6-3.3 6-9 6-9-6-9-6z"/><circle cx="12" cy="12" r="2.6"/>',
    'eye-off': '<path d="M4 4l16 16"/><path d="M10.5 6.2A9.6 9.6 0 0 1 12 6c5.7 0 9 6 9 6a15 15 0 0 1-2.6 3.3M6.6 7.7A15 15 0 0 0 3 12s3.3 6 9 6c1.5 0 2.8-.4 4-1"/>',
    'palette': '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.2 0 1.7-.8 1.7-1.6 0-1.4-1.4-1.6-1.4-2.9 0-1 .8-1.6 1.8-1.6h2.1a3.3 3.3 0 0 0 3.3-3.3c0-4.3-3.4-7.6-7.5-7.6z"/><path d="M7.8 11.5h.1M10 8h.1M14 8h.1"/>',
    'list': '<path d="M9 6.5h11M9 12h11M9 17.5h11"/><path d="M4.5 6.5h1M4.5 12h1M4.5 17.5h1"/>',
    'star': '<path d="M12 4l2.5 5.1 5.6.8-4 4 .9 5.6-5-2.7-5 2.7.9-5.6-4-4 5.6-.8z"/>',
    'briefcase': '<rect x="3.5" y="7.5" width="17" height="12" rx="1.5"/><path d="M9 7.5V5.5h6v2"/><path d="M3.5 12.5h17"/>',
    'home': '<path d="M4 11 12 4.5l8 6.5"/><path d="M6 9.5v10h12v-10"/><path d="M10 19.5v-5h4v5"/>',
    'book': '<path d="M5 4.5h10.5A2.5 2.5 0 0 1 18 7v13H7.5A2.5 2.5 0 0 1 5 17.5z"/><path d="M5 17.5A2.5 2.5 0 0 1 7.5 15H18"/>',
    'code': '<path d="M8.5 7.5 4 12l4.5 4.5M15.5 7.5 20 12l-4.5 4.5"/><path d="M13.5 5.5l-3 13"/>',
    'chart': '<path d="M4 19.5h16"/><path d="M5 15.5l4.5-5 3.5 3 6-7"/>',
    'today': '<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17"/><path d="M8 3.5v3M16 3.5v3"/><circle cx="12" cy="14.5" r="2"/>',
    'upcoming': '<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17"/><path d="M8 3.5v3M16 3.5v3"/><path d="M8 14.5h7M13 12.5l2 2-2 2"/>',
    'overdue': '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5.5"/><path d="M12 16.4v.1"/>',
    'sort': '<path d="M7 4.5v15M4 16.5l3 3 3-3"/><path d="M17 19.5v-15M14 7.5l3-3 3 3"/>',
    'filter': '<path d="M4 5.5h16l-6.2 7.3v5.2l-3.6 1.8v-7z"/>',
    'grip': '<path d="M9 6.5h.1M15 6.5h.1M9 12h.1M15 12h.1M9 17.5h.1M15 17.5h.1"/>',
    'undo': '<path d="M9 14.5 4.5 10 9 5.5"/><path d="M4.5 10H15a4.5 4.5 0 0 1 0 9h-3"/>',
    'outbox': '<path d="M4 13.5 6.5 5.5h11l2.5 8v5A1.5 1.5 0 0 1 18.5 20h-13A1.5 1.5 0 0 1 4 18.5z"/><path d="M12 15V8.5M9.5 11l2.5-2.5 2.5 2.5"/>',
    'file-pdf': '<path d="M6 3.5h8.5L19 8v12.5H6z"/><path d="M14 3.5V8h5"/><path d="M9 12.5h6M9 15.5h6M9 18h3.5"/>',
    'form': '<rect x="4.5" y="3.5" width="15" height="17" rx="1.5"/><path d="M8 8h8M8 12h8M8 16h4.5"/>',
    'folder-closed': '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    'folder-open': '<path d="M3.5 17.5V7.5A1.5 1.5 0 0 1 5 6h4l2 2h6.5A1.5 1.5 0 0 1 19 9.5V11"/><path d="M3.5 17.5 6 11.5h15l-2.6 6.5A1.5 1.5 0 0 1 17 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    'chat': '<path d="M5 5.5h14v10H10l-4 3.5v-3.5H5z"/>',
    'pin': '<path d="M9 4h6l-1 6 3 3H7l3-3z"/><path d="M12 13v7"/>',
    'rename': '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    'sparkle': '<path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z"/>',
}

_cache = {}
_registered = []          # (widget, name, colour token) to recolour on theme changes


def svg(name: str, color: str) -> str:
    return _SVG.format(c=color, d=ICONS.get(name, ICONS['more']))


def icon(name: str, color: str | None = None):
    """QIcon for ``name`` in ``color`` (default: the theme text colour), with a muted disabled state."""
    from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
    from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    from . import theme
    t = theme.tokens()
    color = color or str(t.get('text', '#2A2723'))
    key = (name, color, str(t.get('subtle', '#9A948A')))
    if key in _cache:
        return _cache[key]

    def pix(col, size):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        renderer = QSvgRenderer(QByteArray(svg(name, col).encode('utf8')))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        return QPixmap.fromImage(image)
    ic = QIcon()
    for size in (16, 20, 24, 32, 48):
        ic.addPixmap(pix(color, size), QIcon.Mode.Normal)
        ic.addPixmap(pix(key[2], size), QIcon.Mode.Disabled)
    _cache[key] = ic
    return ic


def set_icon(widget, name: str, color_token: str | None = None):
    """Give a button a themed icon that follows later theme changes (see ``refresh``)."""
    from . import theme
    try:
        color = theme.tokens().get(color_token) if color_token else None
        widget.setIcon(icon(name, color))
        widget.setProperty('hubIconName', name)
    except RuntimeError:
        return widget
    _registered.append((widget, name, color_token))
    return widget


def refresh():
    """Recolour every registered icon after a theme change (deleted widgets are dropped)."""
    _cache.clear()
    alive = []
    for widget, _name, token in _registered:
        try:
            name = widget.property('hubIconName') or _name
            from . import theme
            widget.setIcon(icon(name, theme.tokens().get(token) if token else None))
            alive.append((widget, name, token))
        except RuntimeError:
            continue
    _registered[:] = alive
