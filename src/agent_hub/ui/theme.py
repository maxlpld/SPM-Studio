"""Semantic theme tokens for Agent Hub (one schema for every view).

Embedded in a host (SPM Studio), the hub follows the host's live tokens (``Host.colors()``: the same names as
SPM Studio / Theme Studio themes). Standalone, it uses a built-in light or dark theme, or a theme JSON file
(the SPM Studio theme format: ``{"name", "tokens": {...}}`` or a flat token dict) chosen in Settings ›
Appearance. Tokens missing from an older theme get the defaults below, so old themes keep working.

Hub-specific tokens (all optional in a theme file):
``hub_user_bubble``, ``hub_user_text``, ``hub_code_bg``, ``hub_composer_bg``, ``hub_sidebar_bg``,
``hub_status_running``, ``hub_status_approval``, ``hub_status_done``, ``hub_status_error``, ``hub_graph_1``,
``hub_graph_2``, ``hub_radius`` (px).
"""
from __future__ import annotations

import json
from pathlib import Path

LIGHT = {  # warm paper, inspired by calm reading interfaces (our own palette)
    'window': '#F7F5F0', 'surface': '#FFFFFF', 'surface_alt': '#F1EEE7', 'border': '#E2DDD3',
    'text': '#2A2723', 'muted': '#6F6A62', 'subtle': '#9A948A', 'accent': '#C8673A', 'accent_fg': '#FFFFFF',
    'selection': '#F3D9C9', 'warning': '#D69A2D', 'error': '#C94A3F', 'success': '#3E9A62',
    'hub_user_bubble': '#EFE9DE', 'hub_user_text': '#2A2723', 'hub_code_bg': '#F4F1EA',
    'hub_composer_bg': '#FFFFFF', 'hub_sidebar_bg': '#F1EEE7', 'hub_status_running': '#4C8DF6',
    'hub_status_approval': '#E8A33D', 'hub_status_done': '#3BB273', 'hub_status_error': '#E5534B',
    'hub_graph_1': '#C8673A', 'hub_graph_2': '#4C8DF6', 'hub_radius': 12, 'font_family': '', 'font_size': 13,
}
DARK = {
    'window': '#1F1E1C', 'surface': '#262523', 'surface_alt': '#2D2B28', 'border': '#3A3834',
    'text': '#ECE8E1', 'muted': '#A59F95', 'subtle': '#7E786F', 'accent': '#E0895C', 'accent_fg': '#1F1E1C',
    'selection': '#4A3428', 'warning': '#E8B54D', 'error': '#E5675B', 'success': '#5DC28A',
    'hub_user_bubble': '#33302C', 'hub_user_text': '#ECE8E1', 'hub_code_bg': '#1A1917',
    'hub_composer_bg': '#2D2B28', 'hub_sidebar_bg': '#1A1917', 'hub_status_running': '#6EA4FF',
    'hub_status_approval': '#F0B355', 'hub_status_done': '#5DC28A', 'hub_status_error': '#F0716A',
    'hub_graph_1': '#E0895C', 'hub_graph_2': '#6EA4FF', 'hub_radius': 12, 'font_family': '', 'font_size': 13,
}
BUILTIN = {'light': LIGHT, 'dark': DARK}

# One colour per provider / account group, used everywhere a provider is shown: usage rings, the model picker,
# the model line under each reply. Readable on the light and the dark theme.
PROVIDER_COLORS = {
    'anthropic': '#D97757',      # Claude subscription (Claude Code)
    'openai': '#10A37F',         # ChatGPT subscription (Codex)
    'pi': '#8B6CEF',             # Pi accounts
    'local': '#4C8DF6',          # this computer
    'api': '#E0A030',            # API keys (generic)
    'api:openai': '#10A37F', 'api:anthropic': '#D97757', 'api:gemini': '#4285F4', 'api:openrouter': '#6467F2',
    'api:mistral': '#FA520F', 'api:deepseek': '#4D6BFE', 'api:groq': '#F55036', 'api:xai': '#9AA0A6',
    'api:together': '#0F6FFF', 'api:custom': '#E0A030',
}


def scale_font(font, factor: float, minimum: float = 7.0):
    """``font`` scaled by ``factor`` — works for fonts set in points or in pixels (host themes use pixels)."""
    if font.pointSizeF() > 0:
        font.setPointSizeF(max(minimum, font.pointSizeF() * factor))
    elif font.pixelSize() > 0:
        font.setPixelSize(max(int(minimum * 1.33), round(font.pixelSize() * factor)))
    return font


def provider_color(group: str, provider: str = '') -> str:
    if provider and f'api:{provider}' in PROVIDER_COLORS:
        return PROVIDER_COLORS[f'api:{provider}']
    return PROVIDER_COLORS.get(group, PROVIDER_COLORS.get(group.split(':')[0], '#9AA0A6'))


def dot_icon(color: str, size: int = 12):
    """A small filled circle (QIcon) in a provider colour — vector-drawn, no glyph."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(size * 0.5, size * 0.5, size, size))
    p.end()
    return QIcon(pix)

_override: dict | None = None


ALIASES = {  # SPM Studio / Theme Studio token → hub token (only when the hub token is absent)
    'background': 'window', 'foreground': 'text', 'raised': 'surface_alt', 'sidebar': 'hub_sidebar_bg',
    'input': 'hub_composer_bg', 'danger': 'error', 'accent_soft': 'selection',
}


def normalize(found: dict) -> dict:
    """Accept SPM Studio theme names (background, foreground, …) as well as hub names."""
    out = {k: v for k, v in (found or {}).items() if isinstance(v, (str, int, float)) and v not in ('', None)}
    for spm, hub in ALIASES.items():
        if spm in out and hub not in out:
            out[hub] = out[spm]
    if 'radius' in out and 'hub_radius' not in out:
        try:
            out['hub_radius'] = max(6, min(20, int(out['radius']) + 6))
        except (TypeError, ValueError):
            pass
    return out


def load_theme_file(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding='utf8'))
    found = data.get('tokens', data) if isinstance(data, dict) else {}
    return normalize(found)


def set_standalone(name_or_path: str):
    """Standalone theme: 'light', 'dark' or a theme JSON path."""
    global _override
    if name_or_path in BUILTIN:
        _override = dict(BUILTIN[name_or_path])
    else:
        try:
            base = DARK if 'dark' in str(name_or_path).lower() else LIGHT
            _override = {**base, **load_theme_file(Path(name_or_path))}
        except (OSError, ValueError):
            _override = dict(LIGHT)


def tokens() -> dict:
    """The live tokens: host theme if it provides one, else the standalone theme; defaults fill gaps."""
    from ..host import current
    try:
        host = current().colors() or {}
    except Exception:
        host = {}
    if host:
        host = normalize(host)
        dark = _is_dark(host.get('window') or host.get('surface') or '#FFFFFF')
        base = dict(DARK if dark else LIGHT)
        base.update(host)
        if 'hub_user_bubble' not in host:
            base['hub_user_bubble'] = host.get('surface_alt') or host.get('selection') or base['hub_user_bubble']
        if 'hub_code_bg' not in host and 'hub_composer_bg' in host:
            base['hub_code_bg'] = host['hub_composer_bg']
        return base
    return dict(_override or LIGHT)


def _is_dark(color: str) -> bool:
    c = str(color).lstrip('#')
    if len(c) < 6:
        return False
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError:
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


def stylesheet(t: dict | None = None) -> str:
    """Hub-scoped QSS (object names start with ``hub``); never changes the host's own widgets."""
    t = t or tokens()
    radius = int(t.get('hub_radius', 12))
    font = f"font-family: '{t['font_family']}';" if t.get('font_family') else ''
    return f"""
#hubRoot {{ background: {t['window']}; color: {t['text']}; {font} }}
#hubSidebar {{ background: {t.get('hub_sidebar_bg', t['surface_alt'])}; border-right: 1px solid {t['border']}; }}
#hubSidebar QTreeWidget {{ background: transparent; border: none; }}
#hubSidebar QTreeWidget::item {{ padding: 4px 2px; border-radius: 6px; }}
#hubSidebar QTreeWidget::item:selected {{ background: {t['selection']}; color: {t['text']}; }}
#hubSearch {{ border: 1px solid {t['border']}; border-radius: 8px; padding: 5px 8px; background: {t['surface']}; }}
#hubConversation {{ background: {t['window']}; border: none; }}
#hubComposer {{ background: {t.get('hub_composer_bg', t['surface'])}; border: 1px solid {t['border']};
               border-radius: {radius}px; }}
#hubComposer QPlainTextEdit {{ background: transparent; border: none; color: {t['text']}; }}
#hubComposer[brainstorm="true"] {{ border: 2px solid {t['warning']}; }}
#hubComposer[recording="true"] {{ border: 2px solid {t['error']}; }}
QToolButton#hubIcon {{ border: none; border-radius: 8px; padding: 4px; }}
QToolButton#hubIcon:hover {{ background: {t['surface_alt']}; }}
QToolButton#hubIcon:checked {{ background: {t['selection']}; }}
QToolButton#hubFullAccess {{ border: 1px solid transparent; border-radius: 8px; padding: 4px; }}
QToolButton#hubFullAccess:hover {{ background: {t['surface_alt']}; }}
QToolButton#hubFullAccess:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
#hubSidebarTree {{ background: transparent; border: none; outline: none; }}
#hubSidebarTree::item {{ border: none; }}
#hubSidebarTree::item:selected, #hubSidebarTree::item:hover {{ background: transparent; }}
#hubUsageIndicator {{ border: none; border-radius: 8px; }}
#hubUsageIndicator:hover, #hubUsageIndicator:focus {{ background: {t['surface']}; }}
#hubCard[kind="mail"] {{ border-color: {t['accent']}; border-width: 2px; }}
#hubCard[kind="result"] {{ border-color: {t['border']}; }}
#hubCard[kind="form"] {{ border-color: {t['warning']}; }}
#hubMailBody {{ background: {t.get('hub_code_bg', t['surface_alt'])}; border: 1px solid {t['border']};
               border-radius: 6px; }}
QPushButton#hubAttachment {{ text-align: left; padding: 4px 8px; border: 1px solid {t['border']}; border-radius: 6px;
                            background: {t['surface']}; }}
QPushButton#hubSend {{ background: {t['accent']}; color: {t['accent_fg']}; border: none; border-radius: 8px;
                      padding: 5px 12px; font-weight: 600; }}
QPushButton#hubSend:disabled {{ background: {t['border']}; color: {t['muted']}; }}
#hubCard {{ border: 1px solid {t['accent']}; border-radius: {radius - 2}px; background: {t['surface']}; }}
#hubCard[kind="approval"] {{ border-color: {t['warning']}; }}
#hubCard:focus {{ border-width: 2px; }}
#hubHint {{ color: {t['muted']}; }}
#hubMeta {{ color: {t['subtle']}; }}
#hubStrip {{ background: {t['surface_alt']}; border-top: 1px solid {t['border']}; }}
#hubModeBadge {{ color: {t['accent_fg']}; background: {t['warning']}; border-radius: 6px; padding: 1px 6px; }}
"""


def html_css(t: dict | None = None) -> str:
    """Inline styles for the conversation HTML (QTextBrowser supports a CSS subset)."""
    t = t or tokens()
    return (f"body {{ color: {t['text']}; }} pre {{ background: {t.get('hub_code_bg', t['surface_alt'])}; "
            f"padding: 8px; }} code {{ background: {t.get('hub_code_bg', t['surface_alt'])}; }} "
            f"table {{ border-collapse: collapse; }} td, th {{ border: 1px solid {t['border']}; padding: 3px 6px; }} "
            f"a {{ color: {t['accent']}; }}")
