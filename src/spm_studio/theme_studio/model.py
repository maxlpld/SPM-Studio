"""Theme Studio data model (Qt-free): style roles, profiles, stylesheet generation, contrast checks.

Cascade (later wins):
  1. Global tokens — the base theme (colours, font, radius) applied by SPM Studio's own design system.
  2. Component roles — e.g. "button" (all buttons), then more specific roles such as "button.primary".
  3. State variants — normal, hover, pressed, focus, disabled, selected/checked.
  4. SVG skin surfaces — replace the *background and border* of skinned roles; text colour and fonts still come
     from 2–3 (or the base theme).

Nothing here targets single widget instances: every role is a stable class / property selector already used by
SPM Studio's stylesheet, so a profile never breaks when a widget is renamed.
"""
from __future__ import annotations

import copy
import re
import time

SCHEMA = 1
STATES = ('normal', 'hover', 'pressed', 'focus', 'disabled', 'selected')
STATE_SUFFIX = {'normal': '', 'hover': ':hover', 'pressed': ':pressed', 'focus': ':focus', 'disabled': ':disabled',
                'selected': ':checked'}

# property → (label, kind)
PROPS = {
    'color': ('Text colour', 'color'),
    'background': ('Background', 'color'),
    'border_color': ('Border colour', 'color'),
    'border_width': ('Border width (px)', 'int:0:8'),
    'border_style': ('Border style', 'choice:solid,dashed,dotted,none'),
    'radius': ('Corner radius (px)', 'int:0:24'),
    'padding': ('Padding (px)', 'int:0:24'),
    'font_family': ('Font family', 'font'),
    'font_size': ('Font size (px)', 'int:7:32'),
    'font_weight': ('Font weight', 'choice:normal,600,bold'),
    'italic': ('Italic', 'bool'),
}
TEXT_PROPS = ('color', 'font_family', 'font_size', 'font_weight', 'italic')
BOX_PROPS = ('background', 'border_color', 'border_width', 'border_style', 'radius', 'padding')
ALL = TEXT_PROPS + BOX_PROPS


def _role(label, category, selectors, states=('normal',), props=ALL, state_selectors=None, note=''):
    return {'label': label, 'category': category, 'selectors': selectors, 'states': states, 'props': props,
            'state_selectors': state_selectors or {}, 'note': note}


BUTTON_STATES = ('normal', 'hover', 'pressed', 'focus', 'disabled', 'selected')
ROLES = {
    'window': _role('Window background', 'Global', ['QMainWindow', 'QDialog', 'QWidget#workbenchRoot'],
                    props=('background',)),
    'label': _role('Text labels', 'Global', ['QLabel'], ('normal', 'disabled'), TEXT_PROPS),
    'label.heading': _role('Headings', 'Global', ['QLabel#heading', 'QLabel[role="heading"]'], props=TEXT_PROPS),
    'label.hint': _role('Hints (small grey text)', 'Global', ['QLabel#hint', 'QLabel[role="hint"]'], props=TEXT_PROPS),
    'header': _role('Top bar', 'Panels', ['QFrame#appHeader'], props=('background', 'border_color')),
    'panel': _role('Panels / cards / groups', 'Panels', ['QFrame#card', 'QFrame#cardPanel', 'QGroupBox'],
                   props=ALL),
    'button': _role('All buttons', 'Buttons', ['QPushButton'], BUTTON_STATES),
    'button.primary': _role('Primary buttons', 'Buttons', ['QPushButton[primary="true"]',
                                                           'QToolButton[primary="true"]'], BUTTON_STATES),
    'button.destructive': _role('Destructive buttons (delete, cancel run)', 'Buttons',
                                ['QPushButton[destructive="true"]', 'QToolButton[destructive="true"]'],
                                BUTTON_STATES),
    'toolbutton': _role('Toolbar buttons', 'Buttons', ['QToolButton'], ('normal', 'hover', 'pressed', 'disabled',
                                                                        'selected')),
    'input': _role('Input fields', 'Inputs', ['QLineEdit', 'QAbstractSpinBox'], ('normal', 'hover', 'focus',
                                                                                  'disabled')),
    'combo': _role('Drop-down lists', 'Inputs', ['QComboBox'], ('normal', 'hover', 'focus', 'disabled')),
    'textarea': _role('Text areas (editable)', 'Inputs', ['QPlainTextEdit', 'QTextEdit'], ('normal', 'focus',
                                                                                            'disabled')),
    'log': _role('Logs / console (read-only text)', 'Inputs', ['QPlainTextEdit[readOnly="true"]',
                                                               'QTextBrowser'], ('normal',)),
    'checkbox': _role('Check boxes and radio buttons', 'Inputs', ['QCheckBox', 'QRadioButton'],
                      ('normal', 'disabled'), TEXT_PROPS),
    'tab': _role('Tabs', 'Navigation', ['QTabBar::tab'], ('normal', 'hover', 'selected', 'disabled'),
                 state_selectors={'selected': ':selected'}),
    'menu': _role('Menus', 'Navigation', ['QMenu'], props=ALL),
    'menu.item': _role('Menu items', 'Navigation', ['QMenu::item'], ('normal', 'selected', 'disabled'),
                       TEXT_PROPS + ('background', 'radius', 'padding'), state_selectors={'selected': ':selected'}),
    'menubar': _role('Menu bar', 'Navigation', ['QMenuBar'], props=('color', 'background', 'font_family',
                                                                     'font_size', 'font_weight')),
    'list': _role('Lists, trees, tables', 'Data views', ['QListView', 'QTreeView', 'QTableView'],
                  props=('color', 'background', 'border_color', 'border_width', 'radius', 'font_family', 'font_size')),
    'list.item': _role('List rows', 'Data views', ['QListView::item', 'QTreeView::item'], ('normal', 'hover',
                                                                                          'selected'),
                       ('color', 'background', 'padding', 'radius'), state_selectors={'selected': ':selected'}),
    'table.header': _role('Table headers', 'Data views', ['QHeaderView::section'], props=TEXT_PROPS + BOX_PROPS),
    'progress.track': _role('Progress bar — track', 'Progress', ['QProgressBar'], props=ALL),
    'progress.fill': _role('Progress bar — fill', 'Progress', ['QProgressBar::chunk'],
                           props=('background', 'radius', 'border_color', 'border_width')),
    'scrollbar.handle': _role('Scroll bar handle', 'Progress', ['QScrollBar::handle:vertical',
                                                                'QScrollBar::handle:horizontal'],
                              ('normal', 'hover'), ('background', 'radius')),
    'tooltip': _role('Tooltips', 'Overlays', ['QToolTip'], props=('color', 'background', 'border_color',
                                                                  'border_width', 'font_size')),
    'statusbar': _role('Status bar', 'Overlays', ['QStatusBar'], props=TEXT_PROPS + ('background',)),
}
CATEGORIES = tuple(dict.fromkeys(r['category'] for r in ROLES.values()))
NOT_EDITABLE = {
    'Plots and scan images': 'Scientific data colours are set by the image style / colour maps, never by the GUI theme.',
    'Native file and colour dialogs': 'Drawn by the operating system.',
    'Window title bars': 'Drawn by the operating system.',
}
HEX = re.compile(r'^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$')
FONT = re.compile(r'^[\w .,\-+]{1,60}$')


# ------------------------------------------------------------------ colours
def parse_color(value: str):
    """'#RRGGBB' or '#RRGGBBAA' → (r, g, b, a 0–255)."""
    if not HEX.match(str(value or '')):
        raise ValueError(f'Not a colour: {value!r} (use #RRGGBB or #RRGGBBAA)')
    v = value[1:]
    r, g, b = (int(v[i:i + 2], 16) for i in (0, 2, 4))
    a = int(v[6:8], 16) if len(v) == 8 else 255
    return r, g, b, a


def qss_color(value: str) -> str:
    r, g, b, a = parse_color(value)
    return f'#{r:02X}{g:02X}{b:02X}' if a == 255 else f'rgba({r}, {g}, {b}, {a})'


def luminance(rgb) -> float:
    def lin(c):
        c /= 255.
        return c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb[:3])
    return .2126 * r + .7152 * g + .0722 * b


def blend(fg: str, bg: str):
    r, g, b, a = parse_color(fg)
    br, bgc, bb, _ = parse_color(bg)
    k = a / 255.
    return (r * k + br * (1 - k), g * k + bgc * (1 - k), b * k + bb * (1 - k))


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio of text ``fg`` over ``bg`` (alpha of fg blended over bg)."""
    l1, l2 = luminance(blend(fg, bg)), luminance(parse_color(bg))
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + .05) / (lo + .05)


# ------------------------------------------------------------------ profiles
def new_profile(name: str, base_tokens: dict, based_on: str = '') -> dict:
    return {'schema': SCHEMA, 'kind': 'spm-theme-studio-profile', 'name': clean_name(name), 'based_on': based_on,
            'base': {k: v for k, v in base_tokens.items() if k in BASE_KEYS}, 'roles': {}, 'skin': '',
            'modified': time.strftime('%Y-%m-%dT%H:%M:%S')}


BASE_KEYS = ('background', 'surface', 'raised', 'sidebar', 'input', 'foreground', 'muted', 'subtle', 'border',
             'border_strong', 'hover', 'pressed', 'accent', 'accent_hover', 'accent_fg', 'accent_soft', 'selection',
             'danger', 'success', 'warning', 'font_family', 'font_size', 'radius')


def clean_name(name) -> str:
    text = ' '.join(str(name or '').split())[:48]
    return ''.join(c for c in text if c.isalnum() or c in ' -_()+.') or 'My theme'


def slug(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '_', clean_name(name).lower()).strip('_')
    return (s or 'theme')[:40]


def validate_value(prop: str, value):
    kind = PROPS[prop][1]
    if kind == 'color':
        parse_color(value)
        return value.upper()
    if kind.startswith('int:'):
        _, lo, hi = kind.split(':')
        if type(value) not in (int, float) or not int(lo) <= value <= int(hi):
            raise ValueError(f'{PROPS[prop][0]} must be between {lo} and {hi}')
        return int(value)
    if kind.startswith('choice:'):
        choices = kind[7:].split(',')
        if str(value) not in choices:
            raise ValueError(f'{PROPS[prop][0]} must be one of {", ".join(choices)}')
        return str(value)
    if kind == 'bool':
        if not isinstance(value, bool):
            raise ValueError(f'{PROPS[prop][0]} must be true or false')
        return value
    if kind == 'font':
        if not FONT.match(str(value)):
            raise ValueError('Font family: letters, digits, spaces and . , - + only')
        return str(value).strip()
    raise ValueError(prop)


def validate_profile(data) -> dict:
    """Data-only check of an imported/stored profile; returns a clean copy (unknown keys dropped)."""
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or data.get('kind') != 'spm-theme-studio-profile':
        raise ValueError('Not a Theme Studio profile (schema 1)')
    out = new_profile(data.get('name', ''), {}, str(data.get('based_on', ''))[:60])
    base = data.get('base', {})
    if not isinstance(base, dict):
        raise ValueError('base must be an object')
    for key, value in base.items():
        if key not in BASE_KEYS:
            continue
        if key == 'font_family':
            if value and not FONT.match(str(value)):
                raise ValueError('Invalid base font_family')
            out['base'][key] = str(value or '')
        elif key == 'font_size':
            if type(value) not in (int, float) or not 7 <= value <= 20:
                raise ValueError('base font_size must be 7–20')
            out['base'][key] = float(value)
        elif key == 'radius':
            if type(value) not in (int, float) or not 0 <= value <= 16:
                raise ValueError('base radius must be 0–16')
            out['base'][key] = int(value)
        else:
            r, g, b, _a = parse_color(value)
            out['base'][key] = f'#{r:02X}{g:02X}{b:02X}'           # base theme colours are opaque
    roles = data.get('roles', {})
    if not isinstance(roles, dict):
        raise ValueError('roles must be an object')
    for role, states in roles.items():
        if role not in ROLES or not isinstance(states, dict):
            continue
        for state, props in states.items():
            if state not in ROLES[role]['states'] or not isinstance(props, dict):
                continue
            for prop, value in props.items():
                if prop in ROLES[role]['props']:
                    out['roles'].setdefault(role, {}).setdefault(state, {})[prop] = validate_value(prop, value)
    skin = str(data.get('skin', '') or '')
    out['skin'] = skin if re.fullmatch(r'[a-z0-9_]{0,40}', skin) else ''
    out['modified'] = str(data.get('modified', out['modified']))[:25]
    return out


def set_prop(profile: dict, role: str, state: str, prop: str, value) -> dict:
    """Set (or with ``value=None`` clear) one property; returns the profile."""
    if role not in ROLES or state not in ROLES[role]['states'] or prop not in ROLES[role]['props']:
        raise ValueError(f'{prop} is not editable for {role} / {state}')
    states = profile.setdefault('roles', {}).setdefault(role, {})
    if value is None or value == '':
        states.get(state, {}).pop(prop, None)
        if not states.get(state):
            states.pop(state, None)
        if not states:
            profile['roles'].pop(role, None)
    else:
        states.setdefault(state, {})[prop] = validate_value(prop, value)
    return profile


def get_prop(profile: dict, role: str, state: str, prop: str):
    return profile.get('roles', {}).get(role, {}).get(state, {}).get(prop)


# ------------------------------------------------------------------ stylesheet
def _declarations(props: dict) -> list[str]:
    out = []
    if 'color' in props:
        out.append(f"color: {qss_color(props['color'])};")
    if 'background' in props:
        out.append(f"background: {qss_color(props['background'])};")
    if any(k in props for k in ('border_color', 'border_width', 'border_style')):
        if 'border_width' in props:
            out.append(f"border-width: {props['border_width']}px;")
        if 'border_style' in props:
            out.append(f"border-style: {props['border_style']};")
        if 'border_color' in props:
            out.append(f"border-color: {qss_color(props['border_color'])};")
    if 'radius' in props:
        out.append(f"border-radius: {props['radius']}px;")
    if 'padding' in props:
        out.append(f"padding: {props['padding']}px;")
    if 'font_family' in props:
        out.append(f"font-family: \"{props['font_family']}\";")
    if 'font_size' in props:
        out.append(f"font-size: {props['font_size']}px;")
    if 'font_weight' in props:
        out.append(f"font-weight: {props['font_weight']};")
    if 'italic' in props:
        out.append(f"font-style: {'italic' if props['italic'] else 'normal'};")
    return out


def selectors(role: str, state: str) -> list[str]:
    spec = ROLES[role]
    suffix = spec['state_selectors'].get(state, STATE_SUFFIX[state])
    return [s + suffix for s in spec['selectors']]


def role_qss(profile: dict, scope: str = '') -> str:
    """QSS for the role/state overrides of a profile. ``scope`` prefixes every selector (preview gallery)."""
    lines = []
    for role in ROLES:                                  # registry order: general → specific (specific wins)
        states = profile.get('roles', {}).get(role, {})
        for state in STATES:
            props = states.get(state)
            if not props:
                continue
            decl = _declarations(props)
            if decl:
                sel = ', '.join((f'{scope} {s}' if scope else s) for s in selectors(role, state))
                lines.append(f"{sel} {{ {' '.join(decl)} }}")
    return '\n'.join(lines)


def contrast_warnings(profile: dict, tokens: dict) -> list[str]:
    """Readable-text safeguard for the most important pairs (WCAG 3:1 minimum for UI text)."""
    warnings = []
    pairs = [('button', 'normal', tokens.get('foreground'), tokens.get('raised')),
             ('button.primary', 'normal', tokens.get('accent_fg'), tokens.get('accent')),
             ('button.destructive', 'normal', tokens.get('danger'), tokens.get('raised')),
             ('input', 'normal', tokens.get('foreground'), tokens.get('input')),
             ('log', 'normal', tokens.get('foreground'), tokens.get('input')),
             ('panel', 'normal', tokens.get('foreground'), tokens.get('surface')),
             ('window', 'normal', tokens.get('foreground'), tokens.get('background'))]
    for role, state, fg, bg in pairs:
        props = profile.get('roles', {}).get(role, {}).get(state, {})
        fg = props.get('color', fg)
        bg = props.get('background', bg)
        if not (fg and bg):
            continue
        try:
            bg_opaque = '#' + ''.join(f'{int(c):02X}' for c in blend(bg, tokens.get('background', '#000000')))
            ratio = contrast(fg, bg_opaque)
        except ValueError:
            continue
        if ratio < 3.0:
            warnings.append(f'{ROLES[role]["label"]}: text contrast {ratio:.1f}:1 is too low (≥ 3:1 needed)')
    return warnings


def snapshot(profile: dict) -> dict:
    return copy.deepcopy(profile)
