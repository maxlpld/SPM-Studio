"""SVG skins (Qt-free part): template export, strict package validation, SVG sanitizing, stylesheet.

How a skin is drawn
-------------------
Qt style sheets support *nine-slice* images (``border-image``): the corners of the image keep their size, the
edges stretch along one axis and the centre stretches in both, so rounded corners and decorations are never
deformed when a widget is resized. Every skinned role/state is one SVG with a ``viewBox`` and insets
(left, top, right, bottom) that say where the corners end. The SVG replaces the **background and border** of the
widget only: text, selection, editing, tooltips, keyboard focus and hit areas stay those of the real widget.

Package layout (exact, case-sensitive paths)::

    manifest.json
    README.md
    svg/<role>/<state>.svg        e.g. svg/button.primary/hover.svg
    preview.png                   optional
"""
from __future__ import annotations

import json
import re
import shutil
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import model

SCHEMA = 1
KIND = 'spm-svg-skin'
SVG_NS = 'http://www.w3.org/2000/svg'
XLINK = '{http://www.w3.org/1999/xlink}href'

# role → reference size (w, h), default insets (l, t, r, b), {state: required?}
SKIN_ROLES = {
    'button': ((120, 32), (10, 10, 10, 10), {'normal': True, 'hover': True, 'pressed': True, 'disabled': True,
                                             'focus': False}),
    'button.primary': ((120, 32), (10, 10, 10, 10), {'normal': True, 'hover': True, 'pressed': True,
                                                     'disabled': True, 'focus': False}),
    'input': ((200, 30), (8, 8, 8, 8), {'normal': True, 'focus': True, 'disabled': False}),
    'panel': ((240, 160), (16, 16, 16, 16), {'normal': True}),
    'log': ((320, 160), (16, 16, 16, 16), {'normal': True}),
    'progress.track': ((200, 18), (9, 9, 9, 9), {'normal': True}),
    'progress.fill': ((200, 18), (9, 9, 9, 9), {'normal': True}),
    'tab': ((100, 30), (8, 8, 8, 8), {'normal': False, 'hover': False, 'selected': False}),
    'menu': ((180, 120), (12, 12, 12, 12), {'normal': False}),
}
UNSUPPORTED = {
    'Check boxes, radio buttons, sliders, scroll bars': 'Qt draws their indicators separately; use colours instead.',
    'Drop-down lists and their pop-ups': 'Platform pop-up windows; use colours in the Visual Editor.',
    'Tooltips, window title bars, native dialogs': 'Drawn by the operating system / not reliably skinnable.',
    'Plots, scan images, tables': 'Data must stay exact; only colours of the surrounding chrome can change.',
}
MAX_FILES = 300
MAX_TOTAL = 20 * 1024 * 1024
MAX_SVG = 512 * 1024
MAX_ELEMENTS = 5000
MAX_DEPTH = 40
MAX_DATA_IMAGE = 256 * 1024
FORBIDDEN_TAGS = {'script', 'foreignObject', 'iframe', 'object', 'embed', 'audio', 'video', 'canvas', 'animate',
                  'animateMotion', 'animateTransform', 'set', 'discard', 'handler', 'listener', 'feImage'}


class SkinError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__('\n'.join(problems))
        self.problems = problems


def required_files() -> list[str]:
    return [f'svg/{role}/{state}.svg' for role, (_s, _i, states) in SKIN_ROLES.items()
            for state, req in states.items() if req]


def optional_files() -> list[str]:
    return [f'svg/{role}/{state}.svg' for role, (_s, _i, states) in SKIN_ROLES.items()
            for state, req in states.items() if not req]


# ------------------------------------------------------------------ template generation
def _style_for(profile: dict, tokens: dict, role: str, state: str) -> dict:
    """Fill, stroke, stroke width and radius of a role/state from the theme + Visual Editor overrides."""
    t = tokens
    r = int(t.get('radius', 6))
    base = {
        'button': {'normal': (t['raised'], t['border']), 'hover': (t['hover'], t['border_strong']),
                   'pressed': (t['pressed'], t['border_strong']), 'disabled': (t['hover'], t['border']),
                   'focus': (t['raised'], t['accent'])},
        'button.primary': {'normal': (t['accent'], t['accent']), 'hover': (t['accent_hover'], t['accent_hover']),
                           'pressed': (t['accent'], t['border_strong']), 'disabled': (t['hover'], t['border']),
                           'focus': (t['accent'], t['foreground'])},
        'input': {'normal': (t['input'], t['border']), 'focus': (t['input'], t['accent']),
                  'disabled': (t['hover'], t['border'])},
        'panel': {'normal': (t['surface'], t['border'])},
        'log': {'normal': (t['input'], t['border'])},
        'progress.track': {'normal': (t['hover'], t['border'])},
        'progress.fill': {'normal': (t['accent'], t['accent'])},
        'tab': {'normal': ('#00000000', '#00000000'), 'hover': (t['hover'], '#00000000'),
                'selected': (t['accent_soft'], t['accent'])},
        'menu': {'normal': (t['raised'], t['border_strong'])},
    }[role][state]
    radius = {'progress.track': 9, 'progress.fill': 9, 'panel': r + 2, 'log': r, 'menu': r + 2}.get(role, r)
    props = dict(profile.get('roles', {}).get(role, {}).get('normal', {}))
    props.update(profile.get('roles', {}).get(role, {}).get(state if state != 'selected' else 'selected', {}))
    return {'fill': props.get('background', base[0]), 'stroke': props.get('border_color', base[1]),
            'stroke_width': props.get('border_width', 2 if state == 'focus' else 1),
            'radius': props.get('radius', radius), 'disabled': state == 'disabled'}


def _paint(value: str) -> tuple[str, str]:
    r, g, b, a = model.parse_color(value)
    return f'#{r:02X}{g:02X}{b:02X}', f'{a / 255:.3f}'.rstrip('0').rstrip('.') or '0'


def template_svg(role: str, state: str, profile: dict, tokens: dict, insets=None) -> str:
    (w, h), default_insets, _states = SKIN_ROLES[role]
    insets = insets or default_insets
    s = _style_for(profile, tokens, role, state)
    fill, fill_op = _paint(s['fill'])
    stroke, stroke_op = _paint(s['stroke'])
    sw = s['stroke_width']
    half = sw / 2
    rx = min(s['radius'], h / 2, w / 2)
    opacity = ' opacity="0.6"' if s['disabled'] else ''
    extra = ''
    if role == 'tab' and state == 'selected':
        extra = f'\n  <rect id="indicator" x="6" y="{h - 3}" width="{w - 12}" height="3" rx="1.5" fill="{stroke}"/>'
        stroke_op = '0'
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="{SVG_NS}" width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
            f'  <!-- SPM Studio skin: role "{role}", state "{state}". Reference size {w}x{h} px.\n'
            f'       Nine-slice insets (left top right bottom): {" ".join(map(str, insets))} px — keep corners and\n'
            f'       decorations inside them; the edges and the centre are stretched. No text here: the widget\n'
            f'       draws its own text on top. Allowed: shapes, paths, gradients, patterns, clip paths, embedded\n'
            f'       PNG/JPEG (data: URI). Not allowed: scripts, external links, fonts, animations. -->\n'
            f'  <g id="surface"{opacity}>\n'
            f'    <rect id="frame" x="{half}" y="{half}" width="{w - sw}" height="{h - sw}" rx="{rx}" ry="{rx}"\n'
            f'          fill="{fill}" fill-opacity="{fill_op}" stroke="{stroke}" stroke-opacity="{stroke_op}"'
            f' stroke-width="{sw}"/>{extra}\n'
            f'  </g>\n</svg>\n')


def manifest_for(name: str, insets_override: dict | None = None) -> dict:
    roles = {}
    for role, ((w, h), insets, states) in SKIN_ROLES.items():
        ins = list((insets_override or {}).get(role, insets))
        roles[role] = {'reference_size': [w, h], 'viewBox': f'0 0 {w} {h}', 'insets': ins, 'scaling': 'nine-slice',
                       'states': {st: {'file': f'svg/{role}/{st}.svg', 'required': req} for st, req in states.items()}}
    return {'schema': SCHEMA, 'kind': KIND, 'name': model.clean_name(name), 'created': time.strftime('%Y-%m-%d'),
            'compatible': {'spm_studio': '>=0.0.14', 'extension_api': 1},
            'precedence': 'SVG surfaces replace background and border of skinned roles; text colour and fonts come '
                          'from the Visual Editor roles, then from the base theme.',
            'required_files': required_files(), 'optional_files': optional_files(), 'roles': roles}


README = """# SPM Studio SVG skin — {name}

This package was exported from **Theme Studio** (SPM Studio) from your current theme. Edit the SVG files with
Inkscape (or any vector editor), then import the package again in *Settings › Theme Studio › SVG Skins ›
Import SVG personalization package*.

## ⚠ Exact file names are required

Importing needs **every required file below, at exactly this path and with exactly this name** (case-sensitive).
Do not rename, move or delete files. Missing or renamed files → the import is refused with a precise report and
nothing changes. Optional files may be deleted; the theme colours are used instead.

### Required ({n_req} files)
{required}

### Optional ({n_opt} files)
{optional}

## What each file draws

Each SVG is the **background and border** of one kind of control in one state. Text is drawn by SPM Studio on top
(it stays real, selectable, readable). Buttons keep their normal click area (the rectangle of the widget), even if
you draw another shape.

| Role | Used for | Reference size | Corner insets (l t r b) |
|---|---|---|---|
{table}

**Nine-slice scaling:** the parts inside the insets (corners) keep their size; the edges stretch along one
direction, the centre in both. Keep rounded corners, notches and decorations inside the insets. You may change the
insets of a role in `manifest.json` (`roles.<role>.insets`, at most half of the width/height).

## Rules (the import checks them)

- Keep the `viewBox`; you may draw anywhere inside it. Transparent areas stay transparent.
- Allowed: shapes, paths, groups, gradients, patterns, masks, clip paths, filters, embedded PNG/JPEG as `data:` URIs
  (≤ 256 KB each).
- Not allowed (the package is refused): scripts, `foreignObject`, links to files or web addresses, `<!DOCTYPE>`/
  entities, animations, event attributes (`onclick`…), more than {max_el} elements or {max_kb} KB per file.
- Text inside the SVGs is not shown as button text: buttons keep their own labels.

## In Inkscape

1. Open `svg/button/normal.svg`. *File › Document Properties*: do not change the size or the viewBox.
2. Edit the shape (Path › Object to Path to bend it), add patterns or gradients, change colours.
3. *File › Save As… › Plain SVG* with the **same name**. Repeat for the other states and roles.
4. Zip the folder again (the zip must contain `manifest.json` and `svg/` at its top level), or import the folder.

## What cannot be skinned

{unsupported}
"""


def export_template(dest: Path, name: str, profile: dict, tokens: dict, preview_png: bytes | None = None,
                    svgs: dict | None = None, insets: dict | None = None) -> Path:
    """Write a complete template package (.zip) reflecting ``tokens`` + Visual Editor overrides of ``profile``.
    ``svgs`` replaces generated files (used to re-export an installed, edited skin)."""
    dest = Path(dest)
    manifest = manifest_for(name, insets)
    files = {}
    for role, spec in manifest['roles'].items():
        for state, entry in spec['states'].items():
            files[entry['file']] = (svgs or {}).get(entry['file']) or template_svg(role, state, profile, tokens,
                                                                                    spec['insets'])
    table = '\n'.join(f"| `{role}` | {model.ROLES.get(role, {}).get('label', role)} | {spec['reference_size'][0]}×"
                      f"{spec['reference_size'][1]} | {' '.join(map(str, spec['insets']))} |"
                      for role, spec in manifest['roles'].items())
    readme = README.format(name=manifest['name'], n_req=len(required_files()), n_opt=len(optional_files()),
                           required='\n'.join(f'- `{f}`' for f in required_files()),
                           optional='\n'.join(f'- `{f}`' for f in optional_files()), table=table,
                           max_el=MAX_ELEMENTS, max_kb=MAX_SVG // 1024,
                           unsupported='\n'.join(f'- **{k}** — {v}' for k, v in UNSUPPORTED.items()))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.tmp')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('manifest.json', json.dumps(manifest, indent=1))
        zf.writestr('README.md', readme)
        for path, text in sorted(files.items()):
            zf.writestr(path, text)
        if preview_png:
            zf.writestr('preview.png', preview_png)
    tmp.replace(dest)
    return dest


# ------------------------------------------------------------------ SVG sanitizer (data only)
def check_svg(data: bytes, label: str = 'file') -> list[str]:
    """Problems of one SVG (empty = safe and usable). Never executes or fetches anything."""
    problems = []
    if len(data) > MAX_SVG:
        return [f'{label}: larger than {MAX_SVG // 1024} KB']
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return [f'{label}: not UTF-8 text']
    low = text.lower()
    for marker, why in (('<!doctype', 'DOCTYPE'), ('<!entity', 'entities'), ('<?xml-stylesheet', 'external style'),
                        ('javascript:', 'javascript: link'), ('@import', 'CSS @import')):
        if marker in low:
            problems.append(f'{label}: {why} not allowed')
    if problems:
        return problems
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [f'{label}: not valid XML ({exc})']
    if root.tag != f'{{{SVG_NS}}}svg':
        return [f'{label}: the root element must be <svg> (SVG namespace)']
    box = (root.get('viewBox') or '').replace(',', ' ').split()
    try:
        if len(box) != 4 or float(box[2]) <= 0 or float(box[3]) <= 0:
            raise ValueError
    except ValueError:
        problems.append(f'{label}: a valid viewBox="0 0 width height" is required')
    count = 0

    def walk(el, depth):
        nonlocal count
        count += 1
        if depth > MAX_DEPTH:
            problems.append(f'{label}: elements nested too deeply')
            return
        tag = el.tag.split('}')[-1] if isinstance(el.tag, str) else ''
        if tag in FORBIDDEN_TAGS:
            problems.append(f'{label}: <{tag}> not allowed')
        for key, value in el.attrib.items():
            name = key.split('}')[-1].lower()
            if name.startswith('on'):
                problems.append(f'{label}: event attribute {name} not allowed')
            if name == 'href' or key == XLINK:
                v = value.strip()
                ok = v.startswith('#') or (tag == 'image' and re.match(r'^data:image/(png|jpeg);base64,', v)
                                           and len(v) <= MAX_DATA_IMAGE * 4 // 3 + 40)
                if not ok:
                    problems.append(f'{label}: link "{v[:40]}" not allowed (only #ids and embedded PNG/JPEG)')
            if re.search(r'url\(\s*["\']?(?!#)', value, re.I):
                problems.append(f'{label}: url(...) to an external resource not allowed')
        if tag == 'style' and el.text and re.search(r'url\(\s*["\']?(?!#)', el.text, re.I):
            problems.append(f'{label}: url(...) to an external resource not allowed')
        for child in el:
            walk(child, depth + 1)
    walk(root, 0)
    if count > MAX_ELEMENTS:
        problems.append(f'{label}: more than {MAX_ELEMENTS} elements')
    return sorted(set(problems), key=problems.index)


# ------------------------------------------------------------------ package reading
def _read_package(source: Path) -> dict[str, bytes]:
    source = Path(source)
    files: dict[str, bytes] = {}
    problems = []
    total = 0
    if source.is_dir():
        entries = [p for p in source.rglob('*')]
        if len(entries) > MAX_FILES:
            raise SkinError([f'Too many files (more than {MAX_FILES})'])
        for p in entries:
            if p.is_symlink():
                raise SkinError([f'Links are not allowed: {p.relative_to(source)}'])
            if p.is_file():
                rel = p.relative_to(source).as_posix()
                total += p.stat().st_size
                if total > MAX_TOTAL:
                    raise SkinError(['Package too large'])
                files[rel] = p.read_bytes()
        return files
    try:
        zf = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise SkinError([f'Not a valid zip file ({exc})']) from None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES:
            raise SkinError([f'Too many files (more than {MAX_FILES})'])
        for info in infos:
            name = info.filename
            parts = [x for x in name.split('/') if x]
            if name.startswith(('/', '\\')) or '\\' in name or ':' in name or '..' in parts:
                raise SkinError([f'Unsafe path in the zip: {name[:80]}'])
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise SkinError([f'Links are not allowed: {name[:80]}'])
            if info.is_dir():
                continue
            total += info.file_size
            if total > MAX_TOTAL or (info.compress_size and info.file_size / info.compress_size > 100):
                raise SkinError(['Package too large once unpacked'])
            files[name] = zf.read(info)
    # a zip made from the folder itself may wrap everything in one top folder
    if 'manifest.json' not in files:
        tops = {k.split('/')[0] for k in files}
        if len(tops) == 1 and f'{next(iter(tops))}/manifest.json' in files:
            prefix = next(iter(tops)) + '/'
            files = {k[len(prefix):]: v for k, v in files.items() if k.startswith(prefix)}
    if problems:
        raise SkinError(problems)
    return files


def validate_package(source: Path) -> tuple[dict, dict[str, bytes]]:
    """(manifest, {path: svg bytes}) of a complete, safe package, or SkinError with every problem found."""
    files = _read_package(source)
    problems = []
    try:
        manifest = json.loads(files['manifest.json'].decode('utf-8'))
    except KeyError:
        raise SkinError(['manifest.json is missing at the top of the package']) from None
    except (ValueError, UnicodeDecodeError) as exc:
        raise SkinError([f'manifest.json is not valid JSON ({exc})']) from None
    if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA or manifest.get('kind') != KIND:
        problems.append('manifest.json: not an SPM Studio SVG skin manifest (schema 1, kind "spm-svg-skin")')
        raise SkinError(problems)
    insets = {}
    for role, ((w, h), default, _states) in SKIN_ROLES.items():
        spec = (manifest.get('roles') or {}).get(role) or {}
        ins = spec.get('insets', list(default))
        if not (isinstance(ins, list) and len(ins) == 4 and all(type(v) in (int, float) for v in ins)
                and 0 <= ins[0] + ins[2] <= w and 0 <= ins[1] + ins[3] <= h and min(ins) >= 0):
            problems.append(f'manifest.json: roles.{role}.insets must be 4 numbers, at most the size {w}×{h}')
            ins = list(default)
        insets[role] = [int(v) for v in ins]
    lower = {k.lower(): k for k in files}
    svgs = {}
    for path in required_files():
        if path in files:
            svgs[path] = files[path]
        else:
            hint = ''
            if path.lower() in lower:
                hint = f' (found "{lower[path.lower()]}" — names are case-sensitive)'
            else:
                folder = path.rsplit('/', 1)[0] + '/'
                near = [k for k in files if k.startswith(folder) and k.endswith('.svg')]
                if near:
                    hint = f' (this folder has: {", ".join(sorted(near))[:120]})'
            problems.append(f'Missing required file {path}{hint}')
    for path in optional_files():
        if path in files:
            svgs[path] = files[path]
    known = set(required_files()) | set(optional_files())
    for path in files:
        if path.startswith('svg/') and path.endswith('.svg') and path not in known:
            problems.append(f'Unknown file {path} (not used by SPM Studio: check its name and folder)')
    for path, data in svgs.items():
        problems.extend(check_svg(data, path))
    if problems:
        raise SkinError(problems)
    clean = manifest_for(manifest.get('name', 'Imported skin'), insets)
    clean['optional_present'] = sorted(p for p in optional_files() if p in svgs)
    return clean, svgs


def install(manifest: dict, svgs: dict[str, bytes], skins_dir: Path) -> Path:
    """Copy a validated skin into ``skins_dir/<slug>`` atomically (an existing skin of the same name is replaced)."""
    skins_dir = Path(skins_dir)
    skins_dir.mkdir(parents=True, exist_ok=True)
    slug = model.slug(manifest['name'])
    staging = skins_dir / f'.staging-{slug}-{int(time.time() * 1000)}'
    staging.mkdir()
    try:
        for path, data in svgs.items():
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=1), encoding='utf8')
        final = skins_dir / slug
        backup = None
        if final.exists():
            backup = skins_dir / f'.old-{slug}-{int(time.time() * 1000)}'
            final.rename(backup)
        staging.rename(final)
        if backup:
            shutil.rmtree(backup, ignore_errors=True)
        return final
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def installed_skins(skins_dir: Path) -> dict[str, dict]:
    out = {}
    for folder in sorted(Path(skins_dir).glob('*')) if Path(skins_dir).is_dir() else []:
        if folder.name.startswith('.') or not (folder / 'manifest.json').is_file():
            continue
        try:
            out[folder.name] = json.loads((folder / 'manifest.json').read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
    return out


def skin_files(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): p.read_text(encoding='utf8')
            for p in (Path(folder) / 'svg').rglob('*.svg')}


def skin_qss(folder: Path, manifest: dict, scope: str = '', raster: dict | None = None) -> str:
    """Nine-slice rules for every SVG present. ``raster`` maps 'svg/x/y.svg' → PNG path (HiDPI-ready copy)."""
    folder = Path(folder)
    lines = []
    for role, spec in manifest['roles'].items():
        l, t, r, b = spec['insets']
        for state, entry in spec['states'].items():
            src = folder / entry['file']
            if not src.is_file():
                continue
            image = Path((raster or {}).get(entry['file'], src)).as_posix()
            sels = model.selectors(role, state) if role in model.ROLES else []
            if not sels:
                continue
            sel = ', '.join(f'{scope} {s}' if scope else s for s in sels)
            extra = ''
            if role in ('log',):
                extra = ' background: transparent;'
            lines.append(f'{sel} {{ border-image: url("{image}") {t} {r} {b} {l} stretch stretch; '
                         f'border-width: {t}px {r}px {b}px {l}px; border-style: solid; border-color: transparent; '
                         f'background: transparent;{extra} }}')
    if lines:
        # flat / segmented / toolbar-style buttons keep their own look (no frame image)
        flat = ', '.join(f'{scope} {s}' if scope else s for s in
                         ('QPushButton[flat="true"]', 'QPushButton:flat', 'QPushButton[segment="true"]'))
        lines.append(f'{flat} {{ border-image: none; }}')
    return '\n'.join(lines)


# ------------------------------------------------------------------ demo skin (shapes, not just colours)
def demo_svgs(tokens: dict) -> dict[str, str]:
    """A visibly different skin: chamfered buttons with stripes, capsule primary buttons with a gradient and a
    notch, underline inputs, bracketed dotted panels, scan-line log, barber-pole progress fill."""
    a, fg, surf, inp = tokens['accent'], tokens['foreground'], tokens['surface'], tokens['input']
    afg, hov, brd = tokens['accent_fg'], tokens['hover'], tokens['border_strong']
    out = {}

    def svg(w, h, body):
        return (f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="{SVG_NS}" width="{w}" height="{h}" '
                f'viewBox="0 0 {w} {h}">\n{body}\n</svg>\n')
    stripes = (f'<defs><pattern id="st" width="8" height="8" patternUnits="userSpaceOnUse" '
               f'patternTransform="rotate(45)"><rect width="4" height="8" fill="{fg}" fill-opacity="0.06"/>'
               f'</pattern></defs>')
    for state, fill, edge in (('normal', surf, brd), ('hover', hov, a), ('pressed', brd, a), ('disabled', surf, brd),
                              ('focus', surf, a)):
        op = ' opacity="0.5"' if state == 'disabled' else ''
        out[f'svg/button/{state}.svg'] = svg(120, 32, f'''  {stripes}
  <g{op}><path d="M10 1 H110 L119 10 V22 L110 31 H10 L1 22 V10 Z" fill="{fill}" stroke="{edge}" stroke-width="{2 if state == 'focus' else 1.2}"/>
  <path d="M10 1 H110 L119 10 V22 L110 31 H10 L1 22 V10 Z" fill="url(#st)"/></g>''')
    for state, top, bottom in (('normal', a, a), ('hover', '#FFFFFF', a), ('pressed', a, '#000000'),
                               ('disabled', hov, hov), ('focus', a, a)):
        op = ' opacity="0.55"' if state == 'disabled' else ''
        out[f'svg/button.primary/{state}.svg'] = svg(120, 32, f'''  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{top}" stop-opacity="{0.35 if top == '#FFFFFF' else 1}"/><stop offset="0.25" stop-color="{a}"/>
    <stop offset="1" stop-color="{bottom}" stop-opacity="{0.8 if bottom == '#000000' else 1}"/></linearGradient></defs>
  <g{op}><rect x="1" y="1" width="118" height="30" rx="15" fill="{a}"/>
  <rect x="1" y="1" width="118" height="30" rx="15" fill="url(#g)"/>
  <path d="M8 16 L3 11 V21 Z M112 16 L117 11 V21 Z" fill="{afg}" fill-opacity="0.8"/>
  {'<rect x="2" y="2" width="116" height="28" rx="14" fill="none" stroke="' + afg + '" stroke-width="2"/>' if state == 'focus' else ''}</g>''')
    for state, line, w in (('normal', brd, 1.5), ('focus', a, 3), ('disabled', hov, 1)):
        out[f'svg/input/{state}.svg'] = svg(200, 30, f'''  <rect x="0" y="0" width="200" height="30" rx="4" fill="{inp}" fill-opacity="0.65"/>
  <rect x="0" y="{30 - w}" width="200" height="{w}" fill="{line}"/>''')
    out['svg/panel/normal.svg'] = svg(240, 160, f'''  <defs><pattern id="dots" width="12" height="12" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="1" fill="{fg}" fill-opacity="0.10"/></pattern></defs>
  <rect x="0.5" y="0.5" width="239" height="159" rx="3" fill="{surf}" stroke="{brd}"/>
  <rect x="0.5" y="0.5" width="239" height="159" rx="3" fill="url(#dots)"/>
  <path d="M1 14 V1 H14 M226 1 H239 V14 M239 146 V159 H226 M14 159 H1 V146" fill="none" stroke="{a}" stroke-width="2.5"/>''')
    out['svg/log/normal.svg'] = svg(320, 160, f'''  <defs><pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="1" fill="{a}" fill-opacity="0.07"/></pattern></defs>
  <rect x="0.5" y="0.5" width="319" height="159" rx="6" fill="{inp}" stroke="{brd}"/>
  <rect x="0.5" y="0.5" width="319" height="159" rx="6" fill="url(#scan)"/>
  <rect x="6" y="6" width="4" height="148" rx="2" fill="{a}" fill-opacity="0.6"/>''')
    out['svg/progress.track/normal.svg'] = svg(200, 18, f'''  <rect x="0.5" y="0.5" width="199" height="17" rx="8.5" fill="{hov}" stroke="{brd}"/>
  <path d="M50 4 V14 M100 4 V14 M150 4 V14" stroke="{fg}" stroke-opacity="0.15"/>''')
    out['svg/progress.fill/normal.svg'] = svg(200, 18, f'''  <defs><pattern id="pole" width="14" height="18" patternUnits="userSpaceOnUse" patternTransform="skewX(-30)">
    <rect width="7" height="18" fill="{afg}" fill-opacity="0.22"/></pattern></defs>
  <rect x="1" y="1" width="198" height="16" rx="8" fill="{a}"/>
  <rect x="1" y="1" width="198" height="16" rx="8" fill="url(#pole)"/>''')
    return out


def demo_package(dest: Path, tokens: dict) -> Path:
    """The bundled demonstration skin (complete package, ready to import)."""
    return export_template(dest, 'Demo — chamfer and stripes', model.new_profile('demo', tokens), tokens,
                           svgs=demo_svgs(tokens))
