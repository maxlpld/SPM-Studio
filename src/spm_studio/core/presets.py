"""Versioned, schema-checked editable JSON; failed loads never overwrite state."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json
from .models import ImageStyle, ProcessingStep

THEMES = {
    # v0.8 design system: only these five colours are required; every other
    # token (borders, hover, inputs, menus…) is derived by shared.appearance.
    'graphite': {'background':'#121417','surface':'#1A1D22','foreground':'#E6E8EC','accent':'#3FB8A6','muted':'#99A1AE'},
    'porcelain': {'background':'#F2F3F5','surface':'#FFFFFF','foreground':'#16181D','accent':'#0F7C6F','muted':'#5E6672'},
    'unibasel': {'background':'#171e28','surface':'#202b36','foreground':'#f4f6f7','accent':'#c90021','muted':'#a4aeb9'},
}
THEMES['dark']=THEMES['graphite'];THEMES['light']=THEMES['porcelain']
THEME_COLOR_KEYS=('background','surface','raised','sidebar','input','foreground','muted','subtle','border',
                  'border_strong','hover','pressed','accent','accent_hover','accent_fg','accent_soft',
                  'selection','danger','success','warning')
DEFAULT_PROFILE = {'schema_version': 1, 'name':'STM', 'style':asdict(ImageStyle()),
                   'processing':[], 'channel_contains':'Z', 'visible_channels':['Z']}
DEFAULT_EXPORT = {'schema_version':1, 'name':'single_column', 'width_mm':86.,
                  'height_mm':78., 'dpi':1200, 'font_family':'DejaVu Sans',
                  'font_size_pt':9, 'margin_mm':4}
HEX = set('0123456789abcdefABCDEF')


def validate_theme(d):
    """Theme JSON: schema_version 1, hex colours, optional font_family / font_size / radius."""
    if not isinstance(d, dict) or d.get('schema_version') != 1:
        raise ValueError('Theme requires schema_version: 1')
    tokens = dict(THEMES['graphite'])
    for key, val in d.items():
        if key in THEME_COLOR_KEYS:
            if not isinstance(val, str) or len(val) != 7 or val[0] != '#' or any(c not in HEX for c in val[1:]):
                raise ValueError(f'Invalid hexadecimal color for {key}')
            tokens[key] = val
        elif key == 'font_family':
            if not isinstance(val, str) or len(val) > 80:
                raise ValueError('font_family must be a font name')
            tokens[key] = val.strip()
        elif key == 'font_size':
            if type(val) not in (int, float) or not 7 <= val <= 20:
                raise ValueError('font_size must be 7–20 (points)')
            tokens[key] = float(val)
        elif key == 'radius':
            if type(val) not in (int, float) or not 0 <= val <= 16:
                raise ValueError('radius must be 0–16 (pixels)')
            tokens[key] = int(val)
    return tokens


def validate_profile(d):
    if not isinstance(d, dict) or d.get('schema_version') != 1:
        raise ValueError('Profile requires schema_version: 1')
    accepted = ImageStyle.__dataclass_fields__
    supplied = dict(d.get('style', {}))
    style = ImageStyle(**{k: v for k, v in supplied.items() if k in accepted})
    if style.gamma <= 0 or style.range_mode not in ('percentile','full','manual','sigma','mad'):
        raise ValueError('Invalid style range/gamma')
    if style.range_mode in ('manual','percentile') and style.high <= style.low:
        raise ValueError('Style high must exceed low')
    visible = d.get('visible_channels', [])
    if not isinstance(visible,list) or any(not isinstance(x,str) or not x.strip() or len(x)>120 for x in visible):
        raise ValueError('visible_channels must be a list of nonempty channel names or matching fragments')
    steps = [ProcessingStep(**x) for x in d.get('processing', [])]
    # Optional channel-specific rules are backwards compatible with v1 profiles.
    # Keys are channel fragments, matched case/punctuation-insensitively.
    specific_styles={}
    for fragment, value in d.get('channel_styles', {}).items():
        if not isinstance(fragment,str) or not isinstance(value,dict):
            raise ValueError('channel_styles expects channel fragments mapped to styles')
        merged={**asdict(style),**{k:v for k,v in value.items() if k in accepted}}
        candidate=ImageStyle(**merged)
        if candidate.gamma<=0 or (candidate.range_mode in ('percentile','manual') and candidate.high<=candidate.low):
            raise ValueError('Invalid channel style')
        specific_styles[fragment]=asdict(candidate)
    specific_steps={}
    for fragment, value in d.get('channel_processing', {}).items():
        if not isinstance(fragment,str) or not isinstance(value,list):
            raise ValueError('channel_processing expects channel fragments mapped to step lists')
        specific_steps[fragment]=[asdict(ProcessingStep(**item)) for item in value]
    titles=d.get('channel_titles',{})
    if isinstance(titles,dict):
        # v34: "$\\\\Delta f$" (doubled backslash) → "$\\Delta f$"; old default "Excitations" → $V_{exc}$
        fixed={}
        for k,v in titles.items():
            if isinstance(v,str):
                while '\\\\' in v:v=v.replace('\\\\','\\')
                if v.strip() in ('Excitations','Excitation'):v='$V_{exc}$'
            fixed[k]=v
        titles=fixed
    if not isinstance(titles,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in titles.items()):
        raise ValueError('channel_titles must map channel fragments to display names')
    return {'schema_version': 1, 'name': str(d.get('name','Profile')), 'style':asdict(style),
            'processing':[asdict(s) for s in steps], 'channel_contains':str(d.get('channel_contains','')),
            'visible_channels':visible, 'channel_styles':specific_styles,
            'channel_processing':specific_steps, 'channel_titles':titles,
            # v32: crop away the unmeasured part of aborted scans when this profile is applied
            # (AFM profiles default to on; a complete scan is never cropped).
            'auto_crop_incomplete':bool(d.get('auto_crop_incomplete','afm' in str(d.get('name','')).lower())),
            # v0.0.10: a Multipass profile reads the [P1] / [P2] … passes of the header
            'multipass':bool(d.get('multipass','multipass' in str(d.get('name','')).lower()))}


def validate_export(d):
    if not isinstance(d, dict) or d.get('schema_version') != 1:
        raise ValueError('Export preset requires schema_version: 1')
    output = dict(DEFAULT_EXPORT)
    output.update({k: v for k,v in d.items() if k in DEFAULT_EXPORT})
    for k in ('width_mm','height_mm','margin_mm','font_size_pt','dpi'):
        if not isinstance(output[k], (int,float)) or output[k] <= 0 and k != 'margin_mm':
            raise ValueError(f'Invalid export preset {k}')
    if output['width_mm'] <= output['margin_mm']*2 or output['height_mm'] <= output['margin_mm']*2:
        raise ValueError('Margins are larger than page')
    # v0.0.5: an export profile can also remember the whole figure (panels, grid, options).
    if d.get('layout') is not None:
        output['layout'] = validate_export_layout(d['layout'])
    return output


MAX_EXPORT_PANELS = 12
EXPORT_ARRANGEMENTS = ('row', 'triangle', 'inverted_triangle', 'grid')
_PANEL_TEXT = ('source', 'channel', 'trace', 'scan', 'result', 'title', 'unit', 'colorbar_position',
               'colorbar_source', 'scale_bar_color', 'scale_bar_position')
_PANEL_BOOL = ('show_colorbar', 'show_scale_bar')


def validate_export_layout(layout):
    """Optional ``layout`` block of an export profile (see export_presets/README.md).

    ``panels`` lists what each image shows. ``source`` is ``channel`` (a scan channel, matched by
    name on whatever scan is open) or ``result`` (an analysis figure, matched by file name).
    ``scan`` is ``current`` or the file name of another listed scan.
    """
    if not isinstance(layout, dict):
        raise ValueError('layout must be an object')
    out = {}
    arrangement = str(layout.get('arrangement', 'grid'))
    if arrangement not in EXPORT_ARRANGEMENTS:
        raise ValueError('layout.arrangement must be one of ' + ', '.join(EXPORT_ARRANGEMENTS))
    out['arrangement'] = arrangement
    columns = layout.get('columns', 0)
    if type(columns) is not int or not 0 <= columns <= MAX_EXPORT_PANELS:
        raise ValueError(f'layout.columns must be 0 (automatic) to {MAX_EXPORT_PANELS}')
    out['columns'] = columns
    for key in ('panel_letters', 'transparent'):
        out[key] = bool(layout.get(key, False))
    formats = layout.get('formats', ['svg'])
    if (not isinstance(formats, list) or not formats or
            any(f not in ('svg', 'pdf', 'png', 'jpg') for f in formats)):
        raise ValueError('layout.formats must list svg, pdf, png and/or jpg')
    out['formats'] = list(dict.fromkeys(formats))
    panels = layout.get('panels', [])
    if not isinstance(panels, list) or not 1 <= len(panels) <= MAX_EXPORT_PANELS:
        raise ValueError(f'layout.panels must list 1 to {MAX_EXPORT_PANELS} panels')
    clean = []
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError('Each layout panel must be an object')
        item = {}
        for key in _PANEL_TEXT:
            if key in panel:
                if not isinstance(panel[key], str) or len(panel[key]) > 400:
                    raise ValueError(f'layout panel {key} must be text')
                item[key] = panel[key]
        for key in _PANEL_BOOL:
            if key in panel:
                item[key] = bool(panel[key])
        if 'parameters' in panel:
            # v0.0.10: measurement-parameter box (corner + header values, e.g. P2 bias)
            box = panel['parameters']
            if not isinstance(box, dict):
                raise ValueError('layout panel parameters must be an object')
            corner = box.get('corner', 'top_left')
            if corner not in ('top_left', 'top_right', 'bottom_left', 'bottom_right'):
                raise ValueError('layout panel parameters.corner must be a corner name')
            keys = box.get('keys')
            if keys is not None and (not isinstance(keys, list) or len(keys) > 40
                                     or any(not isinstance(k, str) or not k or len(k) > 80 for k in keys)):
                raise ValueError('layout panel parameters.keys must be a list of parameter names')
            item['parameters'] = {'enabled': bool(box.get('enabled', True)), 'corner': corner,
                                  'keys': keys, 'color': str(box.get('color', '#ffffff'))[:40],
                                  'background': bool(box.get('background', True))}
        if item.get('source', 'channel') not in ('channel', 'result'):
            raise ValueError('layout panel source must be channel or result')
        item.setdefault('source', 'channel')
        clean.append(item)
    out['panels'] = clean
    return out


def read_json(path, validator):
    return validator(json.loads(Path(path).read_text(encoding='utf-8')))


def write_json(path, data, validator):
    normalized = validator(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(path)


def profiles_in(*directories):
    result = {}
    for directory in directories:
        for path in sorted(Path(directory).glob('*.json')):
            try:
                result[path.stem] = read_json(path, validate_profile)
            except (ValueError, OSError, KeyError, TypeError):
                continue
    return result
