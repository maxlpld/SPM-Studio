"""TeX installation, compile commands and log parsing (Qt-free).

SPM Studio does not ship TeX: it uses the distribution of the computer (TeX Live, MacTeX,
MiKTeX) or Tectonic. GUI applications started from a desktop launcher often have a shorter
``PATH`` than a terminal (macOS especially), so the usual install folders are searched too.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

BUILD_DIR = '.spm_build'      # compile output, kept out of the project files (like Overleaf)

INSTALL_HINT = {
    'linux': 'Install TeX Live:  sudo apt install texlive-latex-extra texlive-science latexmk '
             '(add texlive-xetex / texlive-luatex for XeLaTeX / LuaLaTeX, texlive-lang-* for languages).',
    'darwin': 'Install MacTeX from https://tug.org/mactex/ (or: brew install --cask mactex-no-gui).',
    'win32': 'Install MiKTeX from https://miktex.org/download (allow it to install missing packages '
             'on the fly), or TeX Live from https://tug.org/texlive/.',
}


def _extra_dirs() -> list[str]:
    dirs = ['/Library/TeX/texbin', '/usr/texbin', '/opt/homebrew/bin', '/usr/local/bin',
            '/usr/local/texlive/*/bin/*', str(Path.home() / '.local/bin'), str(Path.home() / 'bin')]
    if sys.platform.startswith('win'):
        local = os.environ.get('LOCALAPPDATA', '')
        program = os.environ.get('ProgramFiles', r'C:\Program Files')
        dirs += [rf'{program}\MiKTeX\miktex\bin\x64', rf'{local}\Programs\MiKTeX\miktex\bin\x64',
                 r'C:\texlive\*\bin\windows', r'C:\texlive\*\bin\win64', r'C:\texlive\*\bin\win32']
    found = []
    for pattern in dirs:
        for match in sorted(glob.glob(pattern), reverse=True):   # newest TeX Live year first
            if os.path.isdir(match):
                found.append(match)
    return found


def search_path() -> str:
    """PATH used for TeX programs: the environment's PATH plus the usual TeX folders."""
    parts = [p for p in os.environ.get('PATH', '').split(os.pathsep) if p]
    for extra in _extra_dirs():
        if extra not in parts:
            parts.append(extra)
    return os.pathsep.join(parts)


def which(program: str) -> str | None:
    return shutil.which(program, path=search_path())


def available_engines() -> dict[str, str]:
    """{engine: executable} for every engine found on this computer."""
    found = {}
    for name in ('latexmk', 'pdflatex', 'xelatex', 'lualatex', 'tectonic'):
        exe = which(name)
        if exe:
            found[name] = exe
    if 'latexmk' in found and 'pdflatex' not in found:
        found.pop('latexmk')            # latexmk alone cannot compile anything
    return found


def install_hint() -> str:
    key = 'win32' if sys.platform.startswith('win') else 'darwin' if sys.platform == 'darwin' else 'linux'
    return INSTALL_HINT[key]


def best_engine(preferred: str) -> str | None:
    found = available_engines()
    if preferred in found:
        return preferred
    for name in ('latexmk', 'pdflatex', 'xelatex', 'lualatex', 'tectonic'):
        if name in found:
            return name
    return None


def compile_steps(engine: str, main: Path, outdir: str = BUILD_DIR, *, bibliography: str = 'auto',
                  draft: bool = False) -> list[list[str]]:
    """Commands (run in the project folder) that build ``main`` into ``outdir``.

    ``latexmk`` and ``tectonic`` do everything in one step; for a plain engine one pass is
    made, and :func:`needs_rerun` decides whether BibTeX/Biber and further passes follow.
    """
    main = Path(main)
    name = main.name
    if engine == 'latexmk':
        flavour = '-pdf'
        return [[which('latexmk') or 'latexmk', flavour, '-interaction=nonstopmode', '-file-line-error',
                 '-synctex=1', f'-outdir={outdir}', '-f', name]]
    if engine == 'tectonic':
        return [[which('tectonic') or 'tectonic', '--synctex', '--keep-logs', '--keep-intermediates',
                 '-o', outdir, name]]
    exe = which(engine) or engine
    command = [exe, '-interaction=nonstopmode', '-file-line-error', '-synctex=1', f'-output-directory={outdir}']
    if draft:
        command.append('-draftmode')
    return [command + [name]]


def bibliography_step(main: Path, outdir: str = BUILD_DIR) -> list[str] | None:
    """BibTeX or Biber command after a first plain-engine pass (``None`` if not needed)."""
    out = Path(main).parent / outdir
    stem = Path(main).stem
    if (out / f'{stem}.bcf').is_file():
        exe = which('biber')
        return [exe or 'biber', f'--input-directory={outdir}', f'--output-directory={outdir}', stem] if exe else None
    aux = out / f'{stem}.aux'
    try:
        text = aux.read_text(encoding='utf8', errors='replace')
    except OSError:
        return None
    if '\\citation' in text and '\\bibdata' in text:
        exe = which('bibtex')
        if exe:
            return [exe, f'{outdir}/{stem}']
    return None


def needs_rerun(log_text: str) -> bool:
    return bool(re.search(r'Rerun to get|Label\(s\) may have changed|Please \(re\)run|rerun LaTeX', log_text))


def find_main_file(project: Path) -> Path | None:
    """The root document: ``main.tex`` if it has ``\\documentclass``, else the first such file."""
    project = Path(project)
    candidates = [project / 'main.tex'] + sorted(project.glob('*.tex')) + sorted(project.glob('*/*.tex'))
    for path in candidates:
        try:
            head = path.read_text(encoding='utf8', errors='replace')[:20000]
        except OSError:
            continue
        if re.search(r'^\s*\\documentclass', head, re.M):
            return path
    return None


# ----------------------------------------------------------------------------- log parsing
@dataclass
class LogEntry:
    level: str              # 'error' | 'warning' | 'badbox'
    message: str
    file: str = ''
    line: int = 0
    context: str = ''

    def location(self) -> str:
        if self.file and self.line:
            return f'{self.file}:{self.line}'
        return self.file


@dataclass
class LogSummary:
    entries: list = field(default_factory=list)

    @property
    def errors(self):
        return [e for e in self.entries if e.level == 'error']

    @property
    def warnings(self):
        return [e for e in self.entries if e.level == 'warning']

    @property
    def badboxes(self):
        return [e for e in self.entries if e.level == 'badbox']


_FILE_LINE_ERROR = re.compile(r'^(?P<file>(?:[A-Za-z]:)?[^:\n]+\.(?:tex|sty|cls|bib|bbl|ltx|dtx|clo|def)):(?P<line>\d+): (?P<msg>.+)$', re.M)
_BANG = re.compile(r'^! (?P<msg>.+)$', re.M)
_LINE_NO = re.compile(r'^l\.(\d+)\s?(.*)$', re.M)
_WARNING = re.compile(r'^(?:LaTeX|Package|Class) (?:(?P<pkg>\S+) )?Warning: (?P<msg>.+?)(?:\n(?!\(|\s*$).+?)*?(?: on input line (?P<line>\d+))?\.?$',
                      re.M)
_BADBOX = re.compile(r'^(?P<msg>(?:Over|Under)full \\[hv]box .*?)(?:in paragraph at lines (?P<line>\d+)--\d+|detected at line (?P<line2>\d+))?$', re.M)
_BIB_ERROR = re.compile(r'^(?:ERROR|WARN) - (?P<msg>.+)$', re.M)


def parse_log(text: str, main_name: str = 'main.tex') -> LogSummary:
    """Errors, warnings and bad boxes of a LaTeX (or latexmk/biber) log, with file and line."""
    text = text or ''
    # TeX wraps log lines at 79 characters; join them back so messages are complete.
    joined = re.sub(r'(?m)^(.{79})\n(?=\S)', r'\1', text)
    summary = LogSummary()
    seen = set()

    def add(entry):
        key = (entry.level, entry.message.strip()[:160], entry.file, entry.line)
        if key not in seen:
            seen.add(key)
            summary.entries.append(entry)

    for m in _FILE_LINE_ERROR.finditer(joined):
        file = m.group('file').strip()
        if file.startswith('./'):
            file = file[2:]
        after = joined[m.end():m.end() + 400]
        ctx = _LINE_NO.search(after)
        add(LogEntry('error', m.group('msg').strip(), file, int(m.group('line')),
                     ctx.group(2).strip() if ctx else ''))
    if not summary.errors:
        for m in _BANG.finditer(joined):
            after = joined[m.end():m.end() + 600]
            ctx = _LINE_NO.search(after)
            add(LogEntry('error', m.group('msg').strip(), main_name, int(ctx.group(1)) if ctx else 0,
                         ctx.group(2).strip() if ctx else ''))
    for m in _WARNING.finditer(joined):
        msg = ' '.join(m.group('msg').split())
        if m.group('pkg'):
            msg = f'{m.group("pkg")}: {msg}'
        line = int(m.group('line')) if m.group('line') else 0
        add(LogEntry('warning', msg, main_name if line else '', line))
    for m in _BADBOX.finditer(joined):
        line = m.group('line') or m.group('line2')
        add(LogEntry('badbox', m.group('msg').strip(), main_name if line else '', int(line) if line else 0))
    for m in _BIB_ERROR.finditer(joined):
        add(LogEntry('error' if m.group(0).startswith('ERROR') else 'warning', 'Biber: ' + m.group('msg').strip()))
    if 'Emergency stop' in joined and not summary.errors:
        add(LogEntry('error', 'Emergency stop — see the raw log', main_name))
    return summary


def word_count(text: str) -> int:
    """Approximate number of words of a LaTeX source (comments, commands and math removed)."""
    text = re.sub(r'(?<!\\)%.*', '', text)
    body = text.split('\\begin{document}', 1)[-1].split('\\end{document}', 1)[0]
    body = re.sub(r'\$\$.*?\$\$|\\\[.*?\\\]|(?<!\\)\$.*?(?<!\\)\$', ' ', body, flags=re.S)
    body = re.sub(r'\\begin\{(equation|align|gather|multline|figure|table|tikzpicture)\*?\}.*?\\end\{\1\*?\}',
                  ' ', body, flags=re.S)
    body = re.sub(r'\\(?:label|ref|eqref|cite\w*|includegraphics|input|include|usepackage|bibliography\w*)'
                  r'(?:\[[^\]]*\])?\{[^}]*\}', ' ', body)
    body = re.sub(r'\\[A-Za-z@]+\*?', ' ', body)
    body = re.sub(r'[{}\[\]~&#^_]', ' ', body)
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’\-]*", body))
