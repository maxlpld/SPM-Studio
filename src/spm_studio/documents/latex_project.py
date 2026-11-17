"""LaTeX projects (Qt-free): a folder with a root ``.tex`` file, like an Overleaf project.

* :func:`create_project` — new folder ``<root>/<Name>`` from a template;
* :func:`import_zip` / :func:`export_zip` — Overleaf-compatible source archives;
* :func:`add_figure` — copy a figure into ``figures/`` and return the LaTeX that shows it;
* :func:`ensure_package`, :func:`insertion_offset` — keep the preamble working;
* :func:`outline`, :func:`labels`, :func:`bib_keys` — navigation and completion.
"""
from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import tex

TEXT_SUFFIXES = {'.tex', '.bib', '.sty', '.cls', '.bst', '.txt', '.md', '.cfg', '.def', '.clo', '.ltx', '.bbx',
                 '.cbx', '.lbx', '.csv', '.dat', '.tikz', '.pgf', '.ist', '.latexmkrc', '.json'}
IGNORED_NAMES = {tex.BUILD_DIR, '.git', '__pycache__', '.DS_Store'}
MAX_ZIP_BYTES = 500 * 1024 * 1024
FIGURE_PREFERENCE = ('.pdf', '.png', '.jpg', '.jpeg', '.eps', '.svg')
PROJECT_MARKER = '.spm_latex.json'


class ProjectError(ValueError):
    """A plain message for the user."""


def safe_folder_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', ' ', str(name)).strip().strip('.')
    name = re.sub(r'\s+', ' ', name)
    return name[:120] or 'Untitled'


def unique_folder(root: Path, name: str) -> Path:
    root = Path(root)
    target = root / safe_folder_name(name)
    n = 2
    while target.exists():
        target = root / f'{safe_folder_name(name)} ({n})'
        n += 1
    return target


def substitute(text: str, values: dict) -> str:
    """``{{title}}``, ``{{author}}``, ``{{date}}`` … placeholders of a template file."""
    def repl(match):
        key = match.group(1).strip().lower()
        return str(values.get(key, match.group(0)))
    return re.sub(r'\{\{\s*([A-Za-z_]+)\s*\}\}', repl, text)


def create_project(root, name: str, template_dir: Path | None = None, *, author: str = '',
                   title: str = '', main_name: str = 'main.tex') -> Path:
    """Create ``<root>/<name>`` (made unique) from a template folder (or a minimal article)."""
    root = Path(root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    target = unique_folder(root, name)
    values = {'title': title or name, 'author': author, 'date': date.today().isoformat(),
              'project': target.name}
    if template_dir is not None and Path(template_dir).is_dir():
        shutil.copytree(template_dir, target, ignore=shutil.ignore_patterns(
            'template.json', 'preview.png', 'README.md', *IGNORED_NAMES))
        escaped = {k: latex_escape(v) for k, v in values.items()}
        for file in target.rglob('*'):
            if file.is_file() and file.suffix.lower() in ('.tex', '.bib', '.sty', '.cls', '.md', '.txt'):
                chosen = values if file.suffix.lower() in ('.md', '.txt') else escaped
                try:
                    file.write_text(substitute(file.read_text(encoding='utf8'), chosen), encoding='utf8')
                except (OSError, UnicodeDecodeError):
                    pass
    elif template_dir is not None and Path(template_dir).is_file():
        target.mkdir(parents=True)
        source = Path(template_dir)
        escaped = {k: latex_escape(v) for k, v in values.items()}
        (target / main_name).write_text(substitute(source.read_text(encoding='utf8'), escaped), encoding='utf8')
    else:
        target.mkdir(parents=True)
        escaped = {k: latex_escape(v) for k, v in values.items()}
        (target / main_name).write_text(substitute(MINIMAL_DOCUMENT, escaped), encoding='utf8')
    (target / 'figures').mkdir(exist_ok=True)
    if tex.find_main_file(target) is None:
        raise ProjectError('The template has no .tex file with \\documentclass')
    return target


MINIMAL_DOCUMENT = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage[margin=2.5cm]{geometry}
\usepackage{hyperref}

\title{ {{title}} }
\author{ {{author}} }
\date{ {{date}} }

\begin{document}
\maketitle

\section{Introduction}
Write here.

\end{document}
"""


def is_project(folder) -> bool:
    folder = Path(folder)
    return folder.is_dir() and tex.find_main_file(folder) is not None


def project_files(folder) -> list[Path]:
    folder = Path(folder)
    files = []
    for path in sorted(folder.rglob('*')):
        rel = path.relative_to(folder)
        if any(part in IGNORED_NAMES for part in rel.parts) or path.name == PROJECT_MARKER:
            continue
        if path.is_file():
            files.append(path)
    return files


def project_meta(folder) -> dict:
    import json
    try:
        data = json.loads((Path(folder) / PROJECT_MARKER).read_text(encoding='utf8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_project_meta(folder, **changes) -> dict:
    import json
    data = project_meta(folder)
    data.update(changes)
    (Path(folder) / PROJECT_MARKER).write_text(json.dumps(data, indent=2) + '\n', encoding='utf8')
    return data


def main_file(folder) -> Path | None:
    meta = project_meta(folder)
    chosen = meta.get('main')
    if chosen and (Path(folder) / chosen).is_file():
        return Path(folder) / chosen
    return tex.find_main_file(folder)


# --------------------------------------------------------------------------- archives
def _safe_members(archive: zipfile.ZipFile):
    members = [m for m in archive.infolist() if not m.is_dir()]
    if sum(m.file_size for m in members) > MAX_ZIP_BYTES:
        raise ProjectError('The archive is too large')
    for member in members:
        rel = Path(member.filename.replace('\\', '/'))
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:
            raise ProjectError('Unsafe path in archive: ' + member.filename)
        if rel.parts[0] in ('__MACOSX',):
            continue
        yield member, rel


def import_zip(archive, root, name: str | None = None) -> Path:
    """Unpack an Overleaf / LaTeX source archive into a new project folder."""
    archive = Path(archive)
    try:
        z = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise ProjectError(f'{archive.name} is not a zip archive') from exc
    with z:
        members = list(_safe_members(z))
        tops = {rel.parts[0] for _m, rel in members}
        strip = len(tops) == 1 and all(len(rel.parts) > 1 for _m, rel in members)
        target = unique_folder(Path(root).expanduser(), name or archive.stem)
        target.mkdir(parents=True)
        for member, rel in members:
            if strip:
                rel = Path(*rel.parts[1:])
            out = target / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, open(out, 'wb') as dst:
                shutil.copyfileobj(src, dst)
    if tex.find_main_file(target) is None:
        shutil.rmtree(target, ignore_errors=True)
        raise ProjectError('No .tex file with \\documentclass in the archive')
    return target


def import_folder(source, root, name: str | None = None) -> Path:
    source = Path(source)
    if not is_project(source):
        raise ProjectError('This folder has no .tex file with \\documentclass')
    target = unique_folder(Path(root).expanduser(), name or source.name)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
    return target


def export_zip(folder, destination) -> Path:
    """Source archive of the project (what Overleaf's *Upload project* accepts)."""
    folder = Path(folder)
    destination = Path(destination)
    if destination.suffix.lower() != '.zip':
        destination = destination.with_name(destination.name + '.zip')
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
        for file in project_files(folder):
            z.write(file, file.relative_to(folder).as_posix())
    return destination


def copy_project(folder, destination_root, name: str) -> Path:
    """*Save as*: copy the whole project to another place / name."""
    target = unique_folder(Path(destination_root).expanduser(), name)
    shutil.copytree(folder, target, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
    return target


# ---------------------------------------------------------------------------- figures
def figure_name(path) -> str:
    stem = re.sub(r'[^A-Za-z0-9_\-]+', '_', Path(path).stem).strip('_') or 'figure'
    return stem[:80]


def choose_figure(files) -> Path | None:
    """Best file for ``\\includegraphics`` among the formats of one export."""
    files = [Path(f) for f in files]
    for suffix in FIGURE_PREFERENCE:
        for f in files:
            if f.suffix.lower() == suffix:
                return f
    return files[0] if files else None


def add_figure(project, source, folder: str = 'figures', name: str | None = None) -> Path:
    """Copy ``source`` into ``<project>/<folder>/`` (never overwriting another figure)."""
    project = Path(project)
    source = Path(source)
    target_dir = project / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = figure_name(name or source.name)
    target = target_dir / f'{stem}{source.suffix.lower()}'
    n = 2
    while target.exists() and not _same_file(target, source):
        target = target_dir / f'{stem}_{n}{source.suffix.lower()}'
        n += 1
    if not target.exists():
        shutil.copy2(source, target)
    return target


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def is_beamer(text: str) -> bool:
    return bool(re.search(r'\\documentclass(\[[^\]]*\])?\{beamer\}', text))


def figure_snippet(relative: str, caption: str = '', label: str = '', *, beamer: bool = False,
                   width: str = '0.8\\linewidth') -> str:
    relative = relative.replace('\\', '/')
    label = label or 'fig:' + figure_name(relative)
    caption = caption or Path(relative).stem.replace('_', ' ')
    caption = latex_escape(caption)
    if beamer:
        return (f'\\begin{{frame}}{{{caption}}}\n  \\centering\n'
                f'  \\includegraphics[width=0.9\\linewidth,height=0.75\\textheight,keepaspectratio]{{{relative}}}\n'
                f'\\end{{frame}}\n')
    return (f'\\begin{{figure}}[htbp]\n  \\centering\n  \\includegraphics[width={width}]{{{relative}}}\n'
            f'  \\caption{{{caption}}}\n  \\label{{{label}}}\n\\end{{figure}}\n')


def latex_escape(text: str) -> str:
    replacements = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
                    '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(replacements.get(c, c) for c in str(text))


def preamble_end(text: str) -> int:
    m = re.search(r'\\begin\{document\}', text)
    return m.start() if m else -1


def ensure_package(text: str, package: str, options: str = '') -> str:
    """Add ``\\usepackage{package}`` to the preamble if it is not loaded yet."""
    if re.search(r'\\usepackage(\[[^\]]*\])?\{[^}]*\b' + re.escape(package) + r'\b[^}]*\}', text):
        return text
    if package == 'graphicx' and re.search(r'\\documentclass(\[[^\]]*\])?\{beamer\}', text):
        return text                                  # beamer loads graphicx itself
    line = f'\\usepackage{"[" + options + "]" if options else ""}{{{package}}}\n'
    m = re.search(r'^\\documentclass.*$', text, re.M)
    if not m:
        return line + text
    # after the last \usepackage of the preamble, else right after \documentclass
    end = preamble_end(text)
    region = text[:end] if end > 0 else text
    last = None
    for last in re.finditer(r'^\\usepackage.*$', region, re.M):
        pass
    at = (last.end() if last else m.end()) + 1
    return text[:at] + line + text[at:]


def insertion_offset(text: str, cursor: int) -> int:
    """Where a figure goes: at the cursor when it is in the body, else before ``\\end{document}``."""
    begin = preamble_end(text)
    end = text.rfind('\\end{document}')
    if begin < 0:
        return max(0, min(cursor, len(text)))
    body_start = text.find('\n', begin) + 1
    if body_start <= cursor and (end < 0 or cursor <= end):
        # start of the current line, so the environment is not glued to a word
        line_start = text.rfind('\n', 0, cursor) + 1
        if text[line_start:cursor].strip():
            nl = text.find('\n', cursor)
            return (nl + 1) if nl >= 0 else len(text)
        return line_start
    return end if end >= 0 else len(text)


def insert_figure_text(text: str, cursor: int, relative: str, caption: str = '') -> tuple[str, int, int]:
    """Return ``(new_text, start, end)`` with the figure inserted and graphicx loaded."""
    with_pkg = ensure_package(text, 'graphicx')
    shift = len(with_pkg) - len(text)
    begin = preamble_end(text)
    if begin >= 0 and cursor >= begin:
        cursor += shift
    snippet = figure_snippet(relative, caption, beamer=is_beamer(with_pkg))
    at = insertion_offset(with_pkg, cursor)
    before = with_pkg[:at]
    lead = '' if not before or before.endswith('\n\n') else ('\n' if before.endswith('\n') else '\n\n')
    block = lead + snippet + ('' if with_pkg[at:].startswith('\n') else '\n')
    new = with_pkg[:at] + block + with_pkg[at:]
    return new, at, at + len(block)


# ------------------------------------------------------------------------- navigation
SECTION_LEVELS = {'part': 0, 'chapter': 1, 'section': 2, 'subsection': 3, 'subsubsection': 4,
                  'paragraph': 5, 'frametitle': 3, 'frame': 3}


@dataclass
class OutlineItem:
    level: int
    title: str
    line: int          # 1-based
    kind: str


def outline(text: str) -> list[OutlineItem]:
    items = []
    pattern = re.compile(r'^[^%\n]*?\\(part|chapter|section|subsection|subsubsection|paragraph|frametitle)\*?'
                         r'(?:\[[^\]]*\])?\{([^}\n]*)\}'
                         r'|^[^%\n]*?\\begin\{frame\}(?:\[[^\]]*\])?\{([^}\n]*)\}', re.M)
    for m in pattern.finditer(text):
        kind = m.group(1) or 'frame'
        title = (m.group(2) if m.group(1) else m.group(3)) or ''
        line = text.count('\n', 0, m.start()) + 1
        items.append(OutlineItem(SECTION_LEVELS[kind], title.strip() or '(untitled)', line, kind))
    return items


def labels(texts) -> list[str]:
    found = []
    for text in texts:
        found += re.findall(r'\\label\{([^}]+)\}', text)
    return sorted(dict.fromkeys(found))


def bib_keys(project) -> list[str]:
    keys = []
    for bib in Path(project).rglob('*.bib'):
        if any(part in IGNORED_NAMES for part in bib.relative_to(project).parts):
            continue
        try:
            keys += re.findall(r'@\w+\s*\{\s*([^,\s]+)\s*,', bib.read_text(encoding='utf8', errors='replace'))
        except OSError:
            continue
    return sorted(dict.fromkeys(keys))


def user_commands(texts) -> list[str]:
    found = []
    for text in texts:
        found += re.findall(r'\\(?:re)?newcommand\*?\{?\\([A-Za-z@]+)\}?', text)
        found += re.findall(r'\\DeclareMathOperator\*?\{\\([A-Za-z]+)\}', text)
    return sorted(dict.fromkeys(found))


# ------------------------------------------------------------------------- completion
COMMANDS = sorted(set("""
documentclass usepackage begin end section subsection subsubsection paragraph chapter part
title author date maketitle tableofcontents listoffigures listoftables abstract appendix
textbf textit emph underline texttt textsc textrm textsf textsuperscript textsubscript
tiny scriptsize footnotesize small normalsize large Large LARGE huge Huge
label ref eqref pageref cite citep citet autocite footnote footnotemark url href
includegraphics caption centering raggedright raggedleft hfill vfill vspace hspace newline linebreak newpage clearpage
item itemize enumerate description frac dfrac tfrac sqrt sum prod int iint oint lim infty partial nabla
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho
varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi
Psi Omega mathrm mathbf mathit mathcal mathbb mathsf mathtt boldsymbol bm vec hat bar tilde dot ddot overline
underbrace overbrace left right big Big bigg Bigg cdot cdots ldots vdots ddots times div pm mp leq geq neq
approx sim simeq equiv propto in notin subset subseteq supset cup cap forall exists to rightarrow leftarrow
Rightarrow Leftarrow leftrightarrow Leftrightarrow mapsto quad qquad text operatorname
SI si num unit qty ang degree celsius angstrom nano micro milli electronvolt volt hertz newton tesla
newcommand renewcommand DeclareMathOperator input include bibliography bibliographystyle printbibliography
addbibresource toprule midrule bottomrule hline cline multicolumn multirow
frametitle framesubtitle pause only onslide uncover visible alert usetheme usecolortheme block
column columns tikz node draw fill path color textcolor colorbox definecolor
""".split()))

ENVIRONMENTS = sorted(set("""
document abstract figure figure* table table* tabular tabularx equation equation* align align* gather gather*
multline split cases itemize enumerate description center flushleft flushright minipage quote quotation verbatim
frame block alertblock exampleblock columns column tikzpicture thebibliography theorem lemma proof definition
subfigure wrapfigure lstlisting pmatrix bmatrix vmatrix matrix array
""".split()))

SNIPPETS = {
    'figure': ('Figure', '\\begin{figure}[htbp]\n  \\centering\n  \\includegraphics[width=0.8\\linewidth]{figures/}\n'
                         '  \\caption{}\n  \\label{fig:}\n\\end{figure}\n'),
    'table': ('Table', '\\begin{table}[htbp]\n  \\centering\n  \\begin{tabular}{lcc}\n    \\toprule\n'
                       '    A & B & C \\\\\n    \\midrule\n    1 & 2 & 3 \\\\\n    \\bottomrule\n  \\end{tabular}\n'
                       '  \\caption{}\n  \\label{tab:}\n\\end{table}\n'),
    'equation': ('Equation', '\\begin{equation}\n  \n  \\label{eq:}\n\\end{equation}\n'),
    'align': ('Aligned equations', '\\begin{align}\n  a &= b \\\\\n  c &= d\n\\end{align}\n'),
    'itemize': ('Bulleted list', '\\begin{itemize}\n  \\item \n\\end{itemize}\n'),
    'enumerate': ('Numbered list', '\\begin{enumerate}\n  \\item \n\\end{enumerate}\n'),
    'frame': ('Beamer frame', '\\begin{frame}{Title}\n  \n\\end{frame}\n'),
    'columns': ('Two columns (beamer)', '\\begin{columns}\n  \\column{0.5\\textwidth}\n  \n'
                                        '  \\column{0.5\\textwidth}\n  \n\\end{columns}\n'),
}


def table_snippet(rows: int, cols: int, booktabs: bool = True) -> str:
    rows, cols = max(1, rows), max(1, cols)
    spec = 'l' + 'c' * (cols - 1)
    header = ' & '.join(f'Header {i + 1}' for i in range(cols)) + ' \\\\'
    body = '\n'.join('    ' + ' & '.join('' for _ in range(cols)) + ' \\\\' for _ in range(rows - 1))
    top, mid, bottom = ('\\toprule', '\\midrule', '\\bottomrule') if booktabs else ('\\hline', '\\hline', '\\hline')
    return (f'\\begin{{table}}[htbp]\n  \\centering\n  \\begin{{tabular}}{{{spec}}}\n    {top}\n    {header}\n'
            f'    {mid}\n{body}\n    {bottom}\n  \\end{{tabular}}\n  \\caption{{}}\n  \\label{{tab:}}\n\\end{{table}}\n')
