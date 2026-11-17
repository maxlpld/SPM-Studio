"""LaTeX and presentation templates (Qt-free), kept in the customization folder like profiles.

======================== ================================================ =========================
kind                      folder                                           one template is
======================== ================================================ =========================
LaTeX templates           ``<config>/customization/latex_templates``       a folder with
                                                                           ``template.json`` + files,
                                                                           or one ``.tex`` file
Presentation templates    ``<config>/customization/presentation_templates`` a ``.json`` file, or a
                                                                           folder with
                                                                           ``template.json`` + images
======================== ================================================ =========================

The ``README.md`` of each folder (installed by :func:`spm_studio.core.paths.ensure_guides`)
explains how to write one; the assistant reads it before it creates a template.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import latex_project, tex

LATEX_FOLDER = 'latex_templates'
SLIDES_FOLDER = 'presentation_templates'
MARKER = 'template.json'
SLIDES_FORMAT = 'spm-slides-template-v1'


class TemplateError(ValueError):
    pass


@dataclass(frozen=True)
class Template:
    kind: str           # 'latex' | 'slides'
    name: str           # file / folder name
    label: str
    description: str
    path: Path
    category: str = ''


def folder(kind: str) -> Path:
    from spm_studio.core import paths
    d = paths.customization_dir() / (LATEX_FOLDER if kind == 'latex' else SLIDES_FOLDER)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_marker(path: Path) -> dict:
    try:
        data = json.loads((path / MARKER).read_text(encoding='utf8'))
    except (OSError, ValueError) as exc:
        raise TemplateError(f'{path.name}/{MARKER}: {exc}') from exc
    if not isinstance(data, dict):
        raise TemplateError(f'{path.name}/{MARKER} must be a JSON object')
    return data


# ------------------------------------------------------------------------ validation
def validate_latex(path) -> dict:
    """Raise :class:`TemplateError` unless ``path`` is a usable LaTeX template; returns its info."""
    path = Path(path)
    if path.is_file():
        if path.suffix.lower() != '.tex':
            raise TemplateError('A single-file LaTeX template is a .tex file')
        text = path.read_text(encoding='utf8', errors='replace')
        if not re.search(r'^\s*\\documentclass', text, re.M):
            raise TemplateError(f'{path.name} has no \\documentclass line')
        return {'name': path.stem.replace('_', ' '), 'description': 'Single-file template', 'main': path.name}
    if not path.is_dir():
        raise TemplateError(f'Not found: {path}')
    info = _read_marker(path) if (path / MARKER).is_file() else {}
    main = info.get('main') or 'main.tex'
    if not (path / main).is_file():
        found = tex.find_main_file(path)
        if found is None:
            raise TemplateError(f'{path.name}: no {main} (or other .tex file with \\documentclass)')
        main = found.relative_to(path).as_posix()
    info.setdefault('name', path.name.replace('_', ' '))
    info['main'] = main
    return info


def validate_slides(path) -> dict:
    path = Path(path)
    if path.is_dir():
        data = _read_marker(path)
    else:
        if path.suffix.lower() != '.json':
            raise TemplateError('A presentation template is a .json file (or a folder with template.json)')
        try:
            data = json.loads(path.read_text(encoding='utf8'))
        except (OSError, ValueError) as exc:
            raise TemplateError(f'{path.name}: {exc}') from exc
    if not isinstance(data, dict):
        raise TemplateError('The template must be a JSON object')
    if data.get('format') != SLIDES_FORMAT:
        raise TemplateError(f'"format" must be "{SLIDES_FORMAT}"')
    theme = data.get('theme', {})
    if not isinstance(theme, dict):
        raise TemplateError('"theme" must be an object')
    for key, value in theme.items():
        if key.endswith('color') and not re.fullmatch(r'#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?', str(value)):
            raise TemplateError(f'theme.{key}: use a colour like "#1A1D22"')
    if 'slides' in data and not isinstance(data['slides'], list):
        raise TemplateError('"slides" must be a list')
    from .settings import SLIDE_SIZES
    if data.get('size', '16:9') not in SLIDE_SIZES:
        raise TemplateError('"size" must be one of ' + ', '.join(SLIDE_SIZES))
    data.setdefault('name', path.stem.replace('_', ' '))
    return data


# --------------------------------------------------------------------------- listing
def list_templates(kind: str) -> list[Template]:
    items = []
    for entry in sorted(folder(kind).iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith('.') or entry.name.lower() == 'readme.md':
            continue
        try:
            info = validate_latex(entry) if kind == 'latex' else validate_slides(entry)
        except TemplateError:
            continue
        items.append(Template(kind, entry.name, str(info.get('name') or entry.stem), str(info.get('description', '')),
                              entry, str(info.get('category', ''))))
    return items


def find(kind: str, name: str) -> Template | None:
    wanted = (name or '').lower()
    for item in list_templates(kind):
        if wanted in (item.name.lower(), item.label.lower(), Path(item.name).stem.lower()):
            return item
    return None


def load_slides_template(name_or_path) -> dict:
    path = Path(name_or_path)
    if not path.exists():
        found = find('slides', str(name_or_path))
        if found is None:
            raise TemplateError(f'Presentation template not found: {name_or_path}')
        path = found.path
    data = validate_slides(path)
    data['_base'] = str(path if path.is_dir() else path.parent)
    return data


# ---------------------------------------------------------------------------- saving
def save_latex_template(project, name: str, description: str = '', *, include_figures: bool = False) -> Path:
    """*Save as template*: copy the project's sources (no build files, figures optional)."""
    project = Path(project)
    main = latex_project.main_file(project)
    if main is None:
        raise TemplateError('The project has no root .tex file')
    target = latex_project.unique_folder(folder('latex'), name.replace(' ', '_'))
    ignore = list(latex_project.IGNORED_NAMES) + ['*.pdf', '*.synctex.gz', latex_project.PROJECT_MARKER]
    shutil.copytree(project, target, ignore=shutil.ignore_patterns(*ignore))
    if not include_figures:
        figures = target / 'figures'
        if figures.is_dir():
            shutil.rmtree(figures)
            figures.mkdir()
    info = {'name': name, 'description': description or f'Saved from {project.name}',
            'main': main.relative_to(project).as_posix(), 'category': 'My templates'}
    (target / MARKER).write_text(json.dumps(info, indent=2) + '\n', encoding='utf8')
    return target


def save_slides_template(deck_dict: dict, name: str, description: str = '', *, include_slides: bool = True,
                         media_root: Path | None = None) -> Path:
    """Store the theme (and optionally the slides) of a presentation as a template."""
    data = {'format': SLIDES_FORMAT, 'name': name, 'description': description,
            'size': deck_dict.get('size', '16:9'), 'theme': dict(deck_dict.get('theme', {}))}
    slides = deck_dict.get('slides', []) if include_slides else []
    media = set()
    for slide in slides:
        for item in slide.get('items', []):
            if item.get('src'):
                media.add(item['src'])
        if slide.get('background_image'):
            media.add(slide['background_image'])
    if data['theme'].get('background_image'):
        media.add(data['theme']['background_image'])
    data['slides'] = slides
    if media and media_root is not None:
        target = latex_project.unique_folder(folder('slides'), name.replace(' ', '_'))
        target.mkdir(parents=True)
        for rel in media:
            source = Path(media_root) / rel
            if source.is_file():
                out = target / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, out)
        (target / MARKER).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf8')
        return target
    target = folder('slides') / (re.sub(r'[^A-Za-z0-9_\- ]+', '', name).strip().replace(' ', '_') or 'Template')
    target = target.with_suffix('.json')
    n = 2
    while target.exists():
        target = target.with_name(f'{target.stem.rsplit("_", 1)[0]}_{n}.json')
        n += 1
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf8')
    return target
