"""User library: scripts and customization files (Qt-free, used by Settings › Library).

One place to list, import, export, edit and remove everything a user can add to
SPM Studio:

========== =================================== ============================
kind        folder                              items
========== =================================== ============================
scripts     ``<data>/scripts``                  tool folders, loose ``.py``
profiles    ``<config>/customization/profiles`` ``*.json``
exports     ``…/export_presets``                ``*.json``
themes      ``…/themes``                        ``*.json``
colormaps   ``…/colormaps``                     ``*.csv`` / ``*.txt``
plots       ``…/plot_styles``                   ``*.json``
shortcuts   ``…/shortcuts``                     ``*.json``
latex_tpl   ``…/latex_templates``               template folders, ``*.tex``
slide_tpl   ``…/presentation_templates``        ``*.json``, template folders
========== =================================== ============================

*Export* writes one ``.zip`` *pack* that another user imports with **Import…**;
a pack is an ordinary zip (``spm-studio-pack.json`` + the files), so it can also
be opened by hand. *Remove* never deletes: the item is moved to
``<data>/removed/<date>/`` and can be put back.

Nothing here executes imported code. Scripts are only syntax-checked.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import paths

PACK_FORMAT = 'spm-studio-pack-v1'
PACK_MANIFEST = 'spm-studio-pack.json'
MAX_PACK_BYTES = 400 * 1024 * 1024     # refuse absurd archives
MAX_PACK_FILES = 5000
IGNORED = ('__pycache__',)


@dataclass(frozen=True)
class Kind:
    key: str
    label: str            # plural, shown in the list
    singular: str
    folder: str           # sub-folder of the customization dir ('' for scripts)
    suffixes: tuple       # accepted file suffixes
    description: str


KINDS = {
    'scripts': Kind('scripts', 'Analysis scripts', 'script', '', ('.py',),
                    'Tools shown in the Tools list. One folder per tool (module.json + module.py + README.md).'),
    'profiles': Kind('profiles', 'Profiles', 'profile', 'profiles', ('.json',),
                     'Channels to show with their processing steps, colormaps and titles.'),
    'exports': Kind('exports', 'Export profiles', 'export profile', 'export_presets', ('.json',),
                    'Figure page, layout and panels used by Export.'),
    'themes': Kind('themes', 'Themes', 'theme', 'themes', ('.json',),
                   'Colours, font and corner radius of the interface.'),
    'colormaps': Kind('colormaps', 'Colormaps', 'colormap', 'colormaps', ('.csv', '.txt'),
                      'RGB(A) colour tables for scan images.'),
    'plots': Kind('plots', 'Plot styles', 'plot style', 'plot_styles', ('.json',),
                  'Fonts, line widths and colours of analysis plots.'),
    'shortcuts': Kind('shortcuts', 'Keyboard shortcuts', 'shortcut file', 'shortcuts', ('.json',),
                      'Keyboard shortcut sets.'),
    # v0.0.8: templates of the LaTeX and presentation editors.
    'latex_templates': Kind('latex_templates', 'LaTeX templates', 'LaTeX template', 'latex_templates', ('.tex',),
                            'Starting points for new LaTeX projects: a folder with template.json and its files, '
                            'or one .tex file. Import a LaTeX project folder or an Overleaf .zip to make one.'),
    'slide_templates': Kind('slide_templates', 'Presentation templates', 'presentation template',
                            'presentation_templates', ('.json',),
                            'Theme, layouts and starter slides of new presentations (.json, or a folder with '
                            'template.json and its images).'),
}
TEMPLATE_KINDS = ('latex_templates', 'slide_templates')
TEMPLATE_MARKER = 'template.json'


@dataclass(frozen=True)
class Item:
    kind: str
    name: str             # file or folder name inside the kind folder
    path: Path
    is_dir: bool
    label: str
    detail: str = ''
    valid: bool = True


class LibraryError(ValueError):
    """Anything the user should read as a plain message."""


class ConflictError(LibraryError):
    def __init__(self, names):
        super().__init__('Already present: ' + ', '.join(names))
        self.names = list(names)


# ------------------------------------------------------------------------- folders
def kind_dir(kind: str) -> Path:
    info = KINDS[kind]
    folder = paths.scripts_dir() if kind == 'scripts' else paths.customization_dir() / info.folder
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def guide(kind: str):
    """Guide of the folder (``README.md``), read by the Assistant before it builds something."""
    return paths.guide_for(kind_dir(kind))


def _safe_name(name: str) -> str:
    name = str(name).replace('\\', '/').split('/')[-1].strip()
    if not name or name in ('.', '..') or name.startswith('.'):
        raise LibraryError(f'Unusable name: {name!r}')
    return name


def _is_tool_folder(path: Path) -> bool:
    return path.is_dir() and (path / 'module.json').is_file()


# ------------------------------------------------------------------------- listing
def list_items(kind: str) -> list[Item]:
    info = KINDS[kind]
    folder = kind_dir(kind)
    items = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith('.') or entry.name in IGNORED:
            continue
        if kind == 'scripts':
            if _is_tool_folder(entry):
                label, detail, valid = entry.name, '', True
                try:
                    meta = json.loads((entry / 'module.json').read_text(encoding='utf-8'))
                    label = str(meta.get('name') or entry.name)
                    detail = 'v' + str(meta.get('version', '?')) + ' · ' + str(meta.get('category', ''))
                    if paths.module_readme(entry) is None:
                        detail += ' · no README'
                except (OSError, ValueError) as exc:
                    detail, valid = f'invalid module.json: {exc}', False
                items.append(Item(kind, entry.name, entry, True, label, detail.strip(' ·'), valid))
            elif entry.is_file() and entry.suffix.lower() == '.py' and not entry.name.startswith('_'):
                items.append(Item(kind, entry.name, entry, False, entry.stem, 'standalone script'))
            continue
        if kind in TEMPLATE_KINDS:
            if entry.name.lower() == 'readme.md' or entry.name.endswith('.bak'):
                continue
            if entry.is_file() and entry.suffix.lower() not in info.suffixes:
                continue
            label, detail, valid = entry.stem.replace('_', ' '), '', True
            try:
                meta = _validate_template(kind, entry)
                label = str(meta.get('name') or label)
                detail = str(meta.get('description') or ('folder' if entry.is_dir() else 'single file'))
            except Exception as exc:
                detail, valid = f'invalid: {exc}', False
            items.append(Item(kind, entry.name, entry, entry.is_dir(), label, detail[:90], valid))
            continue
        if not entry.is_file() or entry.suffix.lower() not in info.suffixes:
            continue
        detail, valid = '', True
        try:
            validate_file(kind, entry)
        except Exception as exc:                       # shown, never raised while listing
            detail, valid = f'invalid: {exc}', False
        items.append(Item(kind, entry.name, entry, False, entry.stem.replace('_', ' '), detail, valid))
    return items


# ---------------------------------------------------------------------- validation
def validate_file(kind: str, path) -> None:
    """Raise if ``path`` is not a usable file of this kind. Never executes anything."""
    path = Path(path)
    info = KINDS[kind]
    if kind == 'scripts':
        if path.suffix.lower() == '.json':
            from .registry import load_manifest
            load_manifest(path)
        elif path.suffix.lower() == '.py':
            compile(path.read_text(encoding='utf-8'), str(path), 'exec')
        return
    if kind in TEMPLATE_KINDS:
        if path.is_file() and path.suffix.lower() == '.json' and kind == 'latex_templates':
            data = json.loads(path.read_text(encoding='utf-8'))      # template.json being edited
            if not isinstance(data, dict):
                raise LibraryError('template.json must be a JSON object')
            return
        _validate_template(kind, path)
        return
    if path.suffix.lower() not in info.suffixes:
        raise LibraryError(f'{info.singular.capitalize()} files end in ' + ' / '.join(info.suffixes))
    if kind == 'profiles':
        from .presets import read_json, validate_profile
        read_json(path, validate_profile)
    elif kind == 'exports':
        from .presets import read_json, validate_export
        read_json(path, validate_export)
    elif kind == 'themes':
        from .presets import read_json, validate_theme
        read_json(path, validate_theme)
    elif kind == 'colormaps':
        from .display import read_colormap_csv
        read_colormap_csv(path)
    elif kind == 'plots':
        from .plot_settings import validate_plot
        validate_plot(json.loads(path.read_text(encoding='utf-8')))
    elif kind == 'shortcuts':
        from .shortcuts import validate_profile as validate_shortcuts
        validate_shortcuts(json.loads(path.read_text(encoding='utf-8')))


def _validate_template(kind: str, path) -> dict:
    from spm_studio.documents import templates
    try:
        return templates.validate_latex(path) if kind == 'latex_templates' else templates.validate_slides(path)
    except templates.TemplateError as exc:
        raise LibraryError(str(exc)) from exc


def _template_candidates(kind: str, source: Path) -> list[Path]:
    """A template folder, or the template folders inside ``source``."""
    try:
        _validate_template(kind, source)
        return [source]
    except LibraryError:
        pass
    found = []
    for child in sorted(source.iterdir()):
        if child.name.startswith('.') or child.name.lower() == 'readme.md':
            continue
        if child.is_dir() or child.suffix.lower() in KINDS[kind].suffixes:
            try:
                _validate_template(kind, child)
                found.append(child)
            except LibraryError:
                continue
    return found


def validate_tool_folder(folder) -> str:
    """Check a tool folder (manifest + Python syntax); returns the module id."""
    folder = Path(folder)
    manifest = folder / 'module.json'
    if not manifest.is_file():
        raise LibraryError(f'{folder.name}: no module.json')
    from .registry import load_manifest
    info = load_manifest(manifest)
    for source in folder.rglob('*.py'):
        if '__pycache__' in source.parts:
            continue
        try:
            compile(source.read_text(encoding='utf-8'), str(source), 'exec')
        except SyntaxError as exc:
            raise LibraryError(f'{source.relative_to(folder)}: {exc.msg} (line {exc.lineno})') from exc
    return info.id


# -------------------------------------------------------------------------- import
def _unique(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix = (target.name, '') if target.is_dir() else (target.stem, target.suffix)
    n = 2
    while (target.parent / f'{stem}_{n}{suffix}').exists():
        n += 1
    return target.parent / f'{stem}_{n}{suffix}'


def _place(kind: str, source: Path, name: str, on_conflict: str) -> Path:
    """Copy one validated file or tool folder into the kind folder."""
    target = kind_dir(kind) / _safe_name(name)
    if target.exists():
        if on_conflict == 'error':
            raise ConflictError([target.name])
        if on_conflict == 'rename':
            target = _unique(target)
        elif on_conflict == 'replace':
            _to_trash(kind, target)
        else:
            raise LibraryError(f'Unknown conflict policy {on_conflict!r}')
    if source.is_dir():
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git'))
    else:
        shutil.copy2(source, target)
    if kind == 'latex_templates' and target.is_dir() and not (target / TEMPLATE_MARKER).exists():
        meta = _validate_template(kind, target)
        (target / TEMPLATE_MARKER).write_text(json.dumps(
            {'name': target.name.replace('_', ' '), 'description': 'Imported LaTeX project',
             'main': meta.get('main', 'main.tex'), 'category': 'Imported'}, indent=2) + '\n', encoding='utf-8')
    if kind != 'scripts':
        paths.mark_factory_item_removed(f'{KINDS[kind].folder}/{target.name}', False)
    return target


def detect_kind(source) -> str | None:
    """Best guess of what a file / folder is (used by drag-and-drop style imports)."""
    source = Path(source)
    if source.is_dir():
        if _is_tool_folder(source) or any(_is_tool_folder(p) for p in source.iterdir() if p.is_dir()):
            return 'scripts'
        for kind in TEMPLATE_KINDS:
            if _template_candidates(kind, source):
                return kind
        return None
    if source.suffix.lower() == '.zip':
        try:
            return read_pack_manifest(source)['kind']
        except LibraryError:
            return None
    if source.suffix.lower() == '.py' or source.name == 'module.json':
        return 'scripts'
    if source.suffix.lower() == '.tex':
        return 'latex_templates'
    for kind in ('slide_templates', 'profiles', 'exports', 'themes', 'plots', 'shortcuts', 'colormaps'):
        try:
            validate_file(kind, source)
            return kind
        except Exception:
            continue
    return None


def import_path(kind: str, source, on_conflict: str = 'error') -> list[Path]:
    """Import a file, a folder or a ``.zip`` pack. Returns the installed paths.

    ``on_conflict``: ``error`` (raise :class:`ConflictError`), ``rename`` or ``replace``
    (the replaced item goes to the removed-items folder).
    """
    source = Path(source).expanduser()
    if not source.exists():
        raise LibraryError(f'Not found: {source}')
    if source.is_file() and source.suffix.lower() == '.zip':
        if kind == 'latex_templates':
            try:
                read_pack_manifest(source)
            except LibraryError:
                return _import_latex_archive(source, on_conflict)   # an Overleaf / LaTeX source .zip
        return import_pack(source, kind, on_conflict)
    info = KINDS[kind]
    if kind in TEMPLATE_KINDS:
        if source.is_dir():
            chosen = _template_candidates(kind, source)
            if not chosen:
                raise LibraryError('No template found: a LaTeX template has a .tex file with \\documentclass; '
                                   'a presentation template is a .json file (see the guide of this folder)')
        else:
            _validate_template(kind, source)
            chosen = [source]
        _check_conflicts(kind, [c.name for c in chosen], on_conflict)
        return [_place(kind, c, c.name, on_conflict) for c in chosen]
    if kind == 'scripts':
        if source.is_file() and source.name == 'module.json':
            source = source.parent
        if source.is_dir():
            folders = [source] if _is_tool_folder(source) else \
                [p for p in sorted(source.iterdir()) if _is_tool_folder(p)]
            if not folders:
                raise LibraryError('No tool found: a tool folder contains module.json and module.py')
            for folder in folders:
                validate_tool_folder(folder)
            _check_conflicts(kind, [f.name for f in folders], on_conflict)
            return [_place(kind, folder, folder.name, on_conflict) for folder in folders]
        if source.suffix.lower() != '.py':
            raise LibraryError('Choose a tool folder, its module.json, a .py script or a .zip pack')
        validate_file(kind, source)
        return [_place(kind, source, source.name, on_conflict)]
    files = [source] if source.is_file() else \
        [p for p in sorted(source.iterdir()) if p.is_file() and p.suffix.lower() in info.suffixes]
    if not files:
        raise LibraryError(f'No {info.singular} file ({" / ".join(info.suffixes)}) found in {source.name}')
    problems = []
    for file in files:
        try:
            validate_file(kind, file)
        except Exception as exc:
            problems.append(f'{file.name}: {exc}')
    if problems:
        raise LibraryError('Not imported — ' + '; '.join(problems))
    _check_conflicts(kind, [f.name for f in files], on_conflict)
    return [_place(kind, file, file.name, on_conflict) for file in files]


def _import_latex_archive(archive: Path, on_conflict: str) -> list[Path]:
    import tempfile
    from spm_studio.documents import latex_project
    with tempfile.TemporaryDirectory() as tmp:
        try:
            project = latex_project.import_zip(archive, tmp, archive.stem)
        except latex_project.ProjectError as exc:
            raise LibraryError(str(exc)) from exc
        name = archive.stem.replace(' ', '_')
        staged = Path(tmp) / name
        if project != staged:
            project.rename(staged)
        _check_conflicts('latex_templates', [name], on_conflict)
        return [_place('latex_templates', staged, name, on_conflict)]


def _check_conflicts(kind, names, on_conflict):
    if on_conflict != 'error':
        return
    folder = kind_dir(kind)
    existing = [n for n in names if (folder / n).exists()]
    if existing:
        raise ConflictError(existing)


# --------------------------------------------------------------------------- packs
def read_pack_manifest(archive) -> dict:
    try:
        with zipfile.ZipFile(archive) as z:
            data = json.loads(z.read(PACK_MANIFEST).decode('utf-8'))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise LibraryError('Not an SPM Studio pack (use Export… in Settings › Library to create one)') from exc
    if not isinstance(data, dict) or data.get('format') != PACK_FORMAT or data.get('kind') not in KINDS:
        raise LibraryError('Unsupported pack format')
    return data


def export_items(kind: str, names, destination) -> Path:
    """Write the chosen items into one ``.zip`` pack that Import… accepts."""
    names = [_safe_name(n) for n in names]
    if not names:
        raise LibraryError('Select at least one item to export')
    folder = kind_dir(kind)
    destination = Path(destination).expanduser()
    if destination.suffix.lower() != '.zip':
        destination = destination.with_name(destination.name + '.zip')
    destination.parent.mkdir(parents=True, exist_ok=True)
    from .updates import current_version
    try:
        version = current_version()
    except Exception:
        version = ''
    manifest = {'format': PACK_FORMAT, 'kind': kind, 'items': names, 'spm_studio_version': version,
                'exported': datetime.now().isoformat(timespec='seconds')}
    temp = destination.with_name(destination.name + '.tmp')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(PACK_MANIFEST, json.dumps(manifest, indent=2) + '\n')
        for name in names:
            source = folder / name
            if not source.exists():
                raise LibraryError(f'Not found: {name}')
            if source.is_dir():
                for file in sorted(source.rglob('*')):
                    if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                        z.write(file, f'items/{name}/{file.relative_to(source).as_posix()}')
            else:
                z.write(source, f'items/{name}')
    temp.replace(destination)
    return destination


def import_pack(archive, kind: str | None = None, on_conflict: str = 'error') -> list[Path]:
    """Install a pack written by :func:`export_items` (validated, path-traversal safe)."""
    import tempfile
    archive = Path(archive)
    manifest = read_pack_manifest(archive)
    pack_kind = manifest['kind']
    if kind is not None and kind != pack_kind:
        raise LibraryError(f'This pack contains {KINDS[pack_kind].label.lower()}, not {KINDS[kind].label.lower()}. '
                           f'Import it from the “{KINDS[pack_kind].label}” section.')
    names = [_safe_name(n) for n in manifest.get('items', []) if isinstance(n, str)]
    if not names:
        raise LibraryError('The pack is empty')
    with zipfile.ZipFile(archive) as z, tempfile.TemporaryDirectory() as tmp:
        members = [m for m in z.infolist() if m.filename.startswith('items/') and not m.is_dir()]
        if len(members) > MAX_PACK_FILES or sum(m.file_size for m in members) > MAX_PACK_BYTES:
            raise LibraryError('The pack is too large')
        root = Path(tmp).resolve()
        for member in members:
            relative = Path(member.filename[len('items/'):])
            if relative.is_absolute() or '..' in relative.parts or not relative.parts:
                raise LibraryError('Unsafe path in pack: ' + member.filename)
            if relative.parts[0] not in names:
                continue
            target = (root / relative).resolve()
            if not target.is_relative_to(root):
                raise LibraryError('Unsafe path in pack: ' + member.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out)
        extracted = []
        for name in names:
            item = root / name
            if not item.exists():
                raise LibraryError(f'{name} is listed in the pack but missing')
            if pack_kind == 'scripts' and item.is_dir():
                validate_tool_folder(item)
            else:
                validate_file(pack_kind, item)
            extracted.append(item)
        _check_conflicts(pack_kind, names, on_conflict)
        return [_place(pack_kind, item, item.name, on_conflict) for item in extracted]


# -------------------------------------------------------------------------- remove
def trash_dir() -> Path:
    folder = paths.data_dir() / 'removed'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _to_trash(kind: str, target: Path) -> Path:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    destination = _unique(trash_dir() / stamp / kind / target.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(destination))
    return destination


def remove_item(kind: str, name: str) -> Path:
    """Move an item out of the library (recoverable). Returns where it went."""
    target = kind_dir(kind) / _safe_name(name)
    if not target.exists():
        raise LibraryError(f'Not found: {name}')
    moved = _to_trash(kind, target)
    if kind != 'scripts':
        # Factory examples are re-installed when missing; remember that this one was removed.
        paths.mark_factory_item_removed(f'{KINDS[kind].folder}/{target.name}', True)
    return moved


# ---------------------------------------------------------------------------- edit
def editable_file(kind: str, name: str) -> Path:
    """The text file shown by Edit… (``module.json`` for a tool folder)."""
    target = kind_dir(kind) / _safe_name(name)
    if target.is_dir() and kind in TEMPLATE_KINDS:
        if (target / TEMPLATE_MARKER).is_file():
            target = target / TEMPLATE_MARKER
        else:
            meta = _validate_template(kind, target)
            target = target / meta.get('main', 'main.tex')
    elif target.is_dir():
        target = target / 'module.json'
    if not target.is_file():
        raise LibraryError(f'Nothing to edit in {name}')
    return target


def read_text(kind: str, name: str) -> str:
    return editable_file(kind, name).read_text(encoding='utf-8')


def save_text(kind: str, name: str, text: str) -> Path:
    """Validate ``text`` as this kind, then replace the file atomically (a ``.bak`` is kept)."""
    target = editable_file(kind, name)
    candidate = target.with_name(target.name + '.edit')
    candidate.write_text(text, encoding='utf-8')
    check = candidate.with_name('check_' + target.name)   # validators look at the real suffix
    try:
        candidate.replace(check)
        validate_file(kind, check)
        backup = target.with_name(target.name + '.bak')
        shutil.copy2(target, backup)
        check.replace(target)
    finally:
        for leftover in (candidate, check):
            if leftover.exists():
                leftover.unlink()
    return target


def duplicate_item(kind: str, name: str, new_name: str) -> Path:
    """Copy an item under a new name (a profile to adapt, a script to start from)."""
    source = kind_dir(kind) / _safe_name(name)
    if not source.exists():
        raise LibraryError(f'Not found: {name}')
    new_name = _safe_name(new_name)
    if source.is_file() and not new_name.lower().endswith(source.suffix.lower()):
        new_name += source.suffix
    target = kind_dir(kind) / new_name
    if target.exists():
        raise ConflictError([new_name])
    if source.is_dir() and kind in TEMPLATE_KINDS:
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        marker = target / TEMPLATE_MARKER
        if marker.is_file():
            try:
                data = json.loads(marker.read_text(encoding='utf-8'))
                data['name'] = new_name.replace('_', ' ')
                marker.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            except (OSError, ValueError):
                pass
        return target
    if source.is_dir():
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        manifest = target / 'module.json'
        try:      # a tool id must be unique and match a safe identifier
            data = json.loads(manifest.read_text(encoding='utf-8'))
            import re
            data['id'] = re.sub(r'[^a-z0-9_]', '_', new_name.lower()).strip('_') or data.get('id', 'tool')
            if not data['id'][0].isalpha():
                data['id'] = 't_' + data['id']
            data['name'] = new_name.replace('_', ' ')
            manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        except (OSError, ValueError):
            pass
    else:
        shutil.copy2(source, target)
        if target.suffix.lower() == '.json':
            try:
                data = json.loads(target.read_text(encoding='utf-8'))
                if isinstance(data, dict) and 'name' in data:
                    data['name'] = target.stem
                    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            except (OSError, ValueError):
                pass
    return target
