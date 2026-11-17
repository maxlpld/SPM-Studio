"""Preferences of the LaTeX editor, the presentation editor and Overleaf (Qt-free).

Stored as JSON in ``<config>/documents.json`` so that the editors, the export dialog, the
assistant and the tests all read the same file. Secrets (the Overleaf Git token) are *not*
stored here: they go to the system keyring or a private file (``ai.lit_store``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ENGINES = ('latexmk', 'pdflatex', 'xelatex', 'lualatex', 'tectonic')
ENGINE_LABELS = {'latexmk': 'latexmk (pdfLaTeX, runs BibTeX/Biber automatically)',
                 'pdflatex': 'pdfLaTeX', 'xelatex': 'XeLaTeX', 'lualatex': 'LuaLaTeX',
                 'tectonic': 'Tectonic'}
SLIDE_SIZES = {'16:9': (960.0, 540.0), '4:3': (960.0, 720.0), '16:10': (960.0, 600.0)}
TARGETS = ('folder', 'latex', 'slides', 'overleaf')

DEFAULTS = {
    'latex_enabled': False,
    'author': '',                   # {{author}} of new LaTeX projects
    'slides_enabled': False,
    'latex_root': '',               # '' → ~/Documents/SPM Studio/LaTeX
    'slides_root': '',              # '' → ~/Documents/SPM Studio/Presentations
    'latex_engine': 'latexmk',
    'latex_autocompile': True,
    'latex_autocompile_delay_ms': 1200,
    'latex_autosave': True,
    'latex_figures_folder': 'figures',
    'latex_font_size': 11,
    'latex_wrap': True,
    'latex_default_template': 'Article',
    'slides_default_template': 'Clean_Light',
    'slides_size': '16:9',
    'slides_autosave': True,
    'formula_preamble': '\\usepackage{amsmath,amssymb,bm}\n\\usepackage{siunitx}',
    'formula_autorender': True,
    'overleaf_server': 'https://www.overleaf.com',
    'overleaf_git_url': '',         # '' → derived from the server (git.overleaf.com for overleaf.com)
    'overleaf_projects': [],        # [{"name": ..., "id": ..., "url": ...}]
    'overleaf_last_project': '',
    'overleaf_last_folder': 'figures',
    'export_targets': ['folder'],   # last choice in the export dialog
    'recent_latex': [],
    'recent_slides': [],
}
MAX_RECENT = 12


def _config_file() -> Path:
    from spm_studio.core import paths
    return paths.config_dir() / 'documents.json'


def documents_home() -> Path:
    """``~/Documents/SPM Studio`` (``~/SPM Studio`` when there is no Documents folder)."""
    home = Path.home()
    docs = home / 'Documents'
    return (docs if docs.is_dir() else home) / 'SPM Studio'


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        stored = json.loads(_config_file().read_text(encoding='utf8'))
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS and (type(value) is type(DEFAULTS[key])
                                        or (isinstance(DEFAULTS[key], (int, float)) and isinstance(value, (int, float))
                                            and not isinstance(value, bool))):
                    data[key] = value
    except (OSError, ValueError):
        pass
    if data['latex_engine'] not in ENGINES:
        data['latex_engine'] = 'latexmk'
    if data['slides_size'] not in SLIDE_SIZES:
        data['slides_size'] = '16:9'
    data['export_targets'] = [t for t in data['export_targets'] if t in TARGETS] or ['folder']
    return data


def save(data: dict) -> dict:
    merged = load()
    for key, value in data.items():
        if key in DEFAULTS:
            merged[key] = value
    path = _config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + '\n', encoding='utf8')
    os.replace(temp, path)
    return merged


def update(**changes) -> dict:
    return save(changes)


def latex_root(conf: dict | None = None) -> Path:
    conf = conf or load()
    root = Path(conf.get('latex_root') or documents_home() / 'LaTeX').expanduser()
    return root


def slides_root(conf: dict | None = None) -> Path:
    conf = conf or load()
    return Path(conf.get('slides_root') or documents_home() / 'Presentations').expanduser()


def add_recent(kind: str, path) -> list:
    key = 'recent_latex' if kind == 'latex' else 'recent_slides'
    path = str(Path(path).expanduser())
    items = [p for p in load()[key] if p != path]
    items.insert(0, path)
    save({key: items[:MAX_RECENT]})
    return items[:MAX_RECENT]


def recent(kind: str) -> list[Path]:
    key = 'recent_latex' if kind == 'latex' else 'recent_slides'
    return [Path(p) for p in load()[key] if Path(p).exists()]


def any_enabled(conf: dict | None = None) -> bool:
    conf = conf or load()
    return bool(conf.get('latex_enabled') or conf.get('slides_enabled') or conf.get('overleaf_projects'))
