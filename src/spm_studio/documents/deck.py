"""Presentation model (Qt-free): slides, items, theme, saved as JSON next to a media folder.

A presentation is a **project folder** ``<root>/<Name>/`` containing ``<Name>.spmdeck`` (JSON) and
``media/`` (images, GIFs, videos, figures sent from SPM Studio). Coordinates are in points of a
960 pt wide slide (16:9 → 960×540, 4:3 → 960×720), origin top left.

Item types: ``text`` (rich text, HTML), ``latex`` (LaTeX source rendered by the editor), ``image``,
``gif``, ``video``, ``shape`` (rect, rounded, ellipse, line, arrow, triangle).
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from .settings import SLIDE_SIZES

FORMAT = 'spm-deck-v1'
SUFFIX = '.spmdeck'
MEDIA = 'media'
ITEM_TYPES = ('text', 'latex', 'image', 'gif', 'video', 'shape')
SHAPES = ('rect', 'rounded', 'ellipse', 'line', 'arrow', 'triangle')
LAYOUTS = {'title': 'Title slide', 'title_content': 'Title and content', 'two_columns': 'Two columns',
           'section': 'Section header', 'title_only': 'Title only', 'image_caption': 'Picture with caption',
           'formula': 'Title and formula', 'blank': 'Blank'}
TRANSITIONS = ('none', 'fade', 'push')
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.svg', '.bmp', '.webp', '.pdf')
VIDEO_SUFFIXES = ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v')

DEFAULT_THEME = {
    'background_color': '#FFFFFF', 'text_color': '#1A1D22', 'muted_color': '#5E6672',
    'accent_color': '#0F7C6F', 'title_font': 'Inter', 'body_font': 'Inter',
    'title_size': 34, 'body_size': 20, 'background_image': '',
    'title_bar': False, 'title_bar_color': '#0F7C6F', 'footer': '', 'slide_numbers': True,
}


class DeckError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def slide_size(size: str) -> tuple[float, float]:
    return SLIDE_SIZES.get(size, SLIDE_SIZES['16:9'])


def text_html(text: str, *, size: float, color: str, font: str, bold: bool = False, align: str = 'left') -> str:
    """Rich text stored in a text box (simple, valid Qt rich-text HTML)."""
    from html import escape
    weight = 600 if bold else 400
    paragraphs = []
    lines = str(text).split('\n')
    bullets = all(line.startswith('• ') for line in lines if line.strip()) and any(lines)
    if bullets:
        rows = ''.join(f'<li>{escape(line[2:])}</li>' for line in lines if line.strip())
        return (f'<ul style="margin:0; font-family:\'{font}\'; font-size:{size:g}pt; color:{color};">{rows}</ul>')
    for line in lines:
        paragraphs.append(f'<p align="{align}" style="margin:0; font-family:\'{font}\'; font-size:{size:g}pt; '
                          f'font-weight:{weight}; color:{color};">{escape(line) or "&nbsp;"}</p>')
    return ''.join(paragraphs)


def make_item(kind: str, x: float, y: float, w: float, h: float, **props) -> dict:
    if kind not in ITEM_TYPES:
        raise DeckError(f'Unknown item type {kind!r}')
    item = {'id': new_id(), 'type': kind, 'x': float(x), 'y': float(y), 'w': float(w), 'h': float(h),
            'rotation': 0.0, 'opacity': 1.0, 'locked': False}
    if kind == 'text':
        item.update({'html': '', 'fill_color': '', 'line_color': '', 'line_width': 0.0, 'padding': 6.0,
                     'valign': 'top', 'role': 'body'})
    elif kind == 'latex':
        item.update({'source': r'$E = mc^2$', 'size': 24.0, 'color': '#1A1D22', 'align': 'center',
                     'fill_color': '', 'display': False})
    elif kind in ('image', 'gif'):
        item.update({'src': '', 'fit': 'contain', 'line_color': '', 'line_width': 0.0, 'radius': 0.0})
    elif kind == 'video':
        item.update({'src': '', 'autoplay': False, 'loop': False, 'muted': False, 'fit': 'contain'})
    elif kind == 'shape':
        item.update({'shape': 'rect', 'fill_color': '#0F7C6F', 'line_color': '', 'line_width': 0.0,
                     'radius': 12.0, 'html': ''})
    item.update(props)
    return item


def layout_items(layout: str, theme: dict, size: tuple[float, float], *, title: str = '',
                 subtitle: str = '') -> list[dict]:
    """Placeholder boxes of a layout, styled with the theme."""
    t = {**DEFAULT_THEME, **(theme or {})}
    w, h = size
    m = 48.0
    tf, bf = t['title_font'], t['body_font']
    ts, bs = float(t['title_size']), float(t['body_size'])
    tc, mc, ac = t['text_color'], t['muted_color'], t['accent_color']

    def title_box(text, y=36.0, height=72.0, size_=ts, align='left'):
        return make_item('text', m, y, w - 2 * m, height, role='title',
                         html=text_html(text, size=size_, color=tc, font=tf, bold=True, align=align))

    def body_box(text, x=m, y=128.0, width=None, height=None):
        return make_item('text', x, y, width or (w - 2 * m), height or (h - y - 56), role='body',
                         html=text_html(text, size=bs, color=tc, font=bf))
    if layout == 'title':
        return [make_item('text', m, h * 0.34, w - 2 * m, 90, role='title',
                          html=text_html(title or 'Presentation title', size=ts * 1.35, color=tc, font=tf,
                                         bold=True, align='center')),
                make_item('text', m, h * 0.34 + 100, w - 2 * m, 60, role='subtitle',
                          html=text_html(subtitle or 'Author · Institution · Date', size=bs, color=mc, font=bf,
                                         align='center')),
                make_item('shape', w / 2 - 40, h * 0.34 + 92, 80, 4, shape='rect', fill_color=ac, radius=2)]
    if layout == 'section':
        return [make_item('shape', m, h * 0.42 - 6, 6, 92, shape='rect', fill_color=ac, radius=3),
                make_item('text', m + 24, h * 0.42, w - 2 * m - 24, 80, role='title',
                          html=text_html(title or 'Section title', size=ts * 1.2, color=tc, font=tf, bold=True))]
    if layout == 'title_only':
        return [title_box(title or 'Slide title')]
    if layout == 'two_columns':
        col = (w - 2 * m - 32) / 2
        return [title_box(title or 'Slide title'),
                body_box('• First point\n• Second point', x=m, width=col),
                body_box('• First point\n• Second point', x=m + col + 32, width=col)]
    if layout == 'image_caption':
        return [title_box(title or 'Slide title'),
                make_item('shape', m, 124, w - 2 * m, h - 220, shape='rect', fill_color='#E9ECEF', radius=8,
                          html=text_html('Insert › Image, or send a figure from SPM Studio', size=14, color=mc,
                                         font=bf, align='center'), placeholder=True),
                make_item('text', m, h - 88, w - 2 * m, 44, role='caption',
                          html=text_html('Caption', size=bs * 0.8, color=mc, font=bf, align='center'))]
    if layout == 'formula':
        return [title_box(title or 'Slide title'),
                make_item('latex', m, 150, w - 2 * m, 120, size=30.0, color=tc,
                          source=r'\[ \hat{H}\psi = E\psi \]', display=True),
                body_box('Explanation of the formula.', y=300, height=h - 360)]
    if layout == 'blank':
        return []
    return [title_box(title or 'Slide title'), body_box('• First point\n• Second point\n• Third point')]


def new_slide(layout: str = 'title_content', theme: dict | None = None, size=(960.0, 540.0), **kw) -> dict:
    return {'id': new_id(), 'layout': layout if layout in LAYOUTS else 'title_content', 'background_color': '',
            'background_image': '', 'hidden': False, 'transition': 'none', 'notes': '',
            'items': layout_items(layout, theme or DEFAULT_THEME, size, **kw)}


def new_deck(title: str = 'Presentation', size: str = '16:9', template: dict | None = None) -> dict:
    template = template or {}
    size = template.get('size', size) if size == '16:9' and template.get('size') else size
    w, h = slide_size(size)
    theme = {**DEFAULT_THEME, **template.get('theme', {})}
    deck = {'format': FORMAT, 'title': title, 'size': size, 'width': w, 'height': h, 'theme': theme,
            'formula_preamble': template.get('formula_preamble', ''), 'slides': []}
    if template.get('slides'):
        for slide in copy.deepcopy(template['slides']):
            slide.setdefault('items', [])
            for item in slide['items']:
                item['id'] = new_id()
            slide['id'] = new_id()
            deck['slides'].append(normalise_slide(slide))
        if deck['slides'] and deck['slides'][0].get('layout') == 'title':
            _retitle(deck['slides'][0], title)
    else:
        deck['slides'].append(new_slide('title', theme, (w, h), title=title))
    return deck


def _retitle(slide: dict, title: str):
    for item in slide['items']:
        if item.get('type') == 'text' and item.get('role') == 'title':
            html = item.get('html', '')
            item['html'] = re.sub(r'>([^<>]*)</p>', lambda m: '>' + _escape(title) + '</p>', html, count=1)
            return


def _escape(text):
    from html import escape
    return escape(text)


def normalise_item(item: dict) -> dict:
    kind = item.get('type')
    if kind not in ITEM_TYPES:
        raise DeckError(f'Unknown item type {kind!r}')
    base = make_item(kind, 0, 0, 100, 50)
    base.update({k: v for k, v in item.items()})
    for key in ('x', 'y', 'w', 'h', 'rotation', 'opacity'):
        try:
            base[key] = float(base[key])
        except (TypeError, ValueError):
            base[key] = 0.0 if key != 'opacity' else 1.0
    base['w'] = max(4.0, base['w'])
    base['h'] = max(2.0, base['h'])
    base['opacity'] = min(1.0, max(0.0, base['opacity']))
    if kind == 'shape' and base.get('shape') not in SHAPES:
        base['shape'] = 'rect'
    return base


def normalise_slide(slide: dict) -> dict:
    out = {'id': slide.get('id') or new_id(), 'layout': slide.get('layout', 'blank'),
           'background_color': str(slide.get('background_color', '') or ''),
           'background_image': str(slide.get('background_image', '') or ''),
           'hidden': bool(slide.get('hidden', False)),
           'transition': slide.get('transition', 'none') if slide.get('transition') in TRANSITIONS else 'none',
           'notes': str(slide.get('notes', '') or ''),
           'items': [normalise_item(i) for i in slide.get('items', []) if isinstance(i, dict)]}
    return out


def validate(deck: dict) -> dict:
    if not isinstance(deck, dict) or deck.get('format') != FORMAT:
        raise DeckError('Not an SPM Studio presentation (format spm-deck-v1)')
    size = deck.get('size', '16:9')
    if size not in SLIDE_SIZES:
        size = '16:9'
    w, h = slide_size(size)
    out = {'format': FORMAT, 'title': str(deck.get('title', 'Presentation')), 'size': size, 'width': w,
           'height': h, 'theme': {**DEFAULT_THEME, **(deck.get('theme') or {})},
           'formula_preamble': str(deck.get('formula_preamble', '') or ''),
           'slides': [normalise_slide(s) for s in deck.get('slides', []) if isinstance(s, dict)]}
    if not out['slides']:
        out['slides'].append(new_slide('blank', out['theme'], (w, h)))
    return out


# ----------------------------------------------------------------------- project files
def deck_file(path) -> Path:
    """The ``.spmdeck`` file of a project folder (or the file itself)."""
    path = Path(path)
    if path.is_file():
        return path
    if path.is_dir():
        named = path / (path.name + SUFFIX)
        if named.is_file():
            return named
        found = sorted(path.glob('*' + SUFFIX))
        if found:
            return found[0]
        return named
    return path


def create_project(root, name: str, *, size: str = '16:9', template: dict | None = None) -> Path:
    from .latex_project import unique_folder
    folder = unique_folder(Path(root).expanduser(), name)
    (folder / MEDIA).mkdir(parents=True)
    deck = new_deck(name, size, template)
    base = Path(template['_base']) if template and template.get('_base') else None
    if base is not None:
        _copy_template_media(deck, base, folder)
    save(deck, folder / (folder.name + SUFFIX))
    return folder / (folder.name + SUFFIX)


def _copy_template_media(deck: dict, base: Path, folder: Path):
    refs = [deck['theme'].get('background_image', '')]
    for slide in deck['slides']:
        refs.append(slide.get('background_image', ''))
        refs += [i.get('src', '') for i in slide['items']]
    for rel in filter(None, refs):
        source = base / rel
        if source.is_file():
            out = folder / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, out)


def load(path) -> dict:
    file = deck_file(path)
    try:
        data = json.loads(file.read_text(encoding='utf8'))
    except (OSError, ValueError) as exc:
        raise DeckError(f'Cannot read {file.name}: {exc}') from exc
    return validate(data)


def save(deck: dict, path) -> Path:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    data = validate(deck)
    temp = file.with_name('.' + file.name + '.tmp')
    temp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf8')
    os.replace(temp, file)
    return file


def add_media(project_dir, source, name: str | None = None) -> str:
    """Copy a file into ``media/``; returns its path relative to the project (``media/x.png``)."""
    project_dir = Path(project_dir)
    source = Path(source)
    media = project_dir / MEDIA
    media.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[^A-Za-z0-9_\-]+', '_', Path(name or source.name).stem).strip('_') or 'media'
    target = media / f'{stem}{source.suffix.lower()}'
    n = 2
    while target.exists():
        try:
            if target.stat().st_size == source.stat().st_size and target.read_bytes() == source.read_bytes():
                return target.relative_to(project_dir).as_posix()
        except OSError:
            pass
        target = media / f'{stem}_{n}{source.suffix.lower()}'
        n += 1
    shutil.copy2(source, target)
    return target.relative_to(project_dir).as_posix()


def media_kind(path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == '.gif':
        return 'gif'
    if suffix in VIDEO_SUFFIXES:
        return 'video'
    return 'image'


def copy_project(deck_path, destination_root, name: str) -> Path:
    """*Save as*: copy the project (deck + media) to another place under a new name."""
    from .latex_project import unique_folder
    source_dir = Path(deck_path).parent
    target = unique_folder(Path(destination_root).expanduser(), name)
    shutil.copytree(source_dir, target, ignore=shutil.ignore_patterns('.*.tmp', '.spm_render'))
    old = target / Path(deck_path).name
    new = target / (target.name + SUFFIX)
    if old.exists() and old != new:
        old.rename(new)
    deck = load(new)
    deck['title'] = name
    save(deck, new)
    return new


def export_zip(deck_path, destination) -> Path:
    deck_path = Path(deck_path)
    destination = Path(destination)
    if destination.suffix.lower() != '.zip':
        destination = destination.with_name(destination.name + '.zip')
    folder = deck_path.parent
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(deck_path, f'{folder.name}/{deck_path.name}')
        for file in sorted((folder / MEDIA).rglob('*')) if (folder / MEDIA).is_dir() else []:
            if file.is_file():
                z.write(file, f'{folder.name}/{file.relative_to(folder).as_posix()}')
    return destination


def import_zip(archive, root) -> Path:
    from .latex_project import unique_folder, _safe_members
    archive = Path(archive)
    with zipfile.ZipFile(archive) as z:
        members = list(_safe_members(z))
        decks = [rel for _m, rel in members if rel.suffix == SUFFIX]
        if not decks:
            raise DeckError('No .spmdeck file in the archive')
        top = decks[0].parts[0] if len(decks[0].parts) > 1 else None
        target = unique_folder(Path(root).expanduser(), top or archive.stem)
        target.mkdir(parents=True)
        for member, rel in members:
            if top and rel.parts[0] == top:
                rel = Path(*rel.parts[1:])
            out = target / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, open(out, 'wb') as dst:
                shutil.copyfileobj(src, dst)
    file = deck_file(target)
    load(file)
    return file


def outline(deck: dict) -> list[dict]:
    """Short description of every slide (for the assistant and the slide list)."""
    out = []
    for index, slide in enumerate(deck.get('slides', []), 1):
        texts = []
        for item in slide.get('items', []):
            if item['type'] == 'text':
                texts.append(plain_text(item.get('html', '')))
            elif item['type'] == 'latex':
                texts.append('LaTeX: ' + item.get('source', ''))
            elif item['type'] in ('image', 'gif', 'video'):
                texts.append(f'{item["type"]}: {item.get("src", "")}')
            elif item['type'] == 'shape' and item.get('html'):
                texts.append(plain_text(item['html']))
        out.append({'index': index, 'id': slide['id'], 'layout': slide.get('layout', ''),
                    'hidden': slide.get('hidden', False), 'notes': slide.get('notes', ''),
                    'items': [{'id': i['id'], 'type': i['type'], 'role': i.get('role', ''),
                               'box': [round(i['x']), round(i['y']), round(i['w']), round(i['h'])]}
                              for i in slide.get('items', [])],
                    'text': [t for t in texts if t]})
    return out


def plain_text(html: str) -> str:
    text = re.sub(r'<li[^>]*>', '• ', html or '')
    text = re.sub(r'</p>|<br\s*/?>|</li>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    from html import unescape
    return '\n'.join(line.strip() for line in unescape(text).splitlines() if line.strip())
