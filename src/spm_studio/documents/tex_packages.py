"""Missing or outdated LaTeX packages: detect them in a log and install / update them (Qt-free).

Strategies, tried in order until one works:

* **MiKTeX** (Windows, some macOS/Linux): ``miktex packages install <pkg>`` (older: ``mpm --install``),
  for the current user — no administrator rights needed.
* **TeX Live with tlmgr**: ``tlmgr install <pkg>`` when the installation is writable (TeX Live installed
  in the user's folder); on macOS (MacTeX) the same command with the administrator password dialog;
  on Debian/Ubuntu, whose TeX Live belongs to apt, tlmgr's *user mode* (packages go to ``~/texmf``),
  using the frozen repository of the installed TeX Live year when the main one is newer.
* **apt** (Debian/Ubuntu, last resort): ``pkexec apt-get install texlive-…`` — the system asks for the
  password; the Debian package is the TeX Live collection that contains the package.

File → package names come from ``tlmgr search --file`` when possible, else from a small table of
well-known cases, else the file name (true for most packages).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import tex

HISTORIC = 'https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/{year}/tlnet-final'
TIMEOUT = 900

# file stem → TeX Live / MiKTeX package (only where they differ)
KNOWN = {
    'tikz': 'pgf', 'pgf': 'pgf', 'pgfcore': 'pgf', 'pgfplotstable': 'pgfplots', 'tikz-cd': 'tikz-cd',
    'amsmath': 'amsmath', 'amssymb': 'amsfonts', 'amsfonts': 'amsfonts', 'amsthm': 'amscls',
    'graphicx': 'graphics', 'color': 'graphics', 'xcolor': 'xcolor', 'hyperref': 'hyperref',
    'algorithm': 'algorithms', 'algorithmic': 'algorithms', 'algpseudocode': 'algorithmicx',
    'subcaption': 'caption', 'caption': 'caption', 'mathtools': 'mathtools', 'bm': 'tools',
    'tabularx': 'tools', 'multicol': 'tools', 'array': 'tools', 'xspace': 'tools', 'varwidth': 'varwidth',
    'longtable': 'tools', 'dcolumn': 'tools', 'enumerate': 'tools', 'calc': 'tools', 'afterpage': 'tools',
    'fontenc': 'latex', 'inputenc': 'latex', 'lmodern': 'lm', 't1lmr': 'lm', 'ecrm1000': 'ec',
    'mhchem': 'mhchem', 'chemfig': 'chemfig', 'siunitx': 'siunitx', 'physics': 'physics',
    'braket': 'braket', 'cleveref': 'cleveref', 'biblatex': 'biblatex', 'natbib': 'natbib',
    'revtex4-2': 'revtex', 'revtex4-1': 'revtex4-1', 'achemso': 'achemso', 'elsarticle': 'elsarticle',
    'beamer': 'beamer', 'beamerthememetropolis': 'beamertheme-metropolis', 'standalone': 'standalone',
    'minted': 'minted', 'listings': 'listings', 'fontawesome5': 'fontawesome5', 'lipsum': 'lipsum',
    'authblk': 'preprint', 'wrapfig': 'wrapfig', 'float': 'float', 'booktabs': 'booktabs',
    'microtype': 'microtype', 'geometry': 'geometry', 'fancyhdr': 'fancyhdr', 'titlesec': 'titlesec',
    'setspace': 'setspace', 'csquotes': 'csquotes', 'multirow': 'multirow', 'enumitem': 'enumitem',
}
# TeX Live collection → Debian/Ubuntu package
DEBIAN = {
    'collection-latexextra': 'texlive-latex-extra', 'collection-latexrecommended': 'texlive-latex-recommended',
    'collection-latex': 'texlive-latex-base', 'collection-science': 'texlive-science',
    'collection-mathscience': 'texlive-science', 'collection-pictures': 'texlive-pictures',
    'collection-fontsextra': 'texlive-fonts-extra', 'collection-fontsrecommended': 'texlive-fonts-recommended',
    'collection-bibtexextra': 'texlive-bibtex-extra', 'collection-publishers': 'texlive-publishers',
    'collection-xetex': 'texlive-xetex', 'collection-luatex': 'texlive-luatex',
    'collection-humanities': 'texlive-humanities', 'collection-music': 'texlive-music',
    'collection-games': 'texlive-games', 'collection-formatsextra': 'texlive-formats-extra',
    'collection-plaingeneric': 'texlive-plain-generic', 'collection-binextra': 'texlive-extra-utils',
    'collection-fontutils': 'texlive-font-utils', 'collection-metapost': 'texlive-metapost',
}
BABEL_DEBIAN = {'french': 'texlive-lang-french', 'german': 'texlive-lang-german', 'ngerman': 'texlive-lang-german',
                'italian': 'texlive-lang-italian', 'spanish': 'texlive-lang-spanish',
                'portuguese': 'texlive-lang-portuguese', 'dutch': 'texlive-lang-european',
                'polish': 'texlive-lang-polish', 'russian': 'texlive-lang-cyrillic', 'greek': 'texlive-lang-greek'}


@dataclass(frozen=True)
class Need:
    kind: str            # 'missing' | 'outdated'
    file: str            # e.g. 'siunitx.sty' ('' for outdated / babel languages)
    package: str         # best guess of the package name
    detail: str = ''

    def label(self) -> str:
        return (f'Install {self.package}' if self.kind == 'missing' else f'Update {self.package}')


_MISSING = [
    re.compile(r"File [`'‘]([^`'’\s]+\.(?:sty|cls|def|cfg|bst|bbx|cbx|lbx|clo|fd|ldf|tex|code\.tex))['’] not found"),
    re.compile(r"I can't find file [`'‘]([^`'’\s]+)['’]"),
    re.compile(r"I couldn't open style file ([^\s]+\.bst)"),
    re.compile(r"Metric \(TFM\) file not found.*?=([a-z]+\d*)", re.S),
]
_BABEL = re.compile(r"Package babel Error: Unknown option [`'‘]([A-Za-z]+)['’]")
_OUTDATED = re.compile(r"You have requested,?\s*(?:on input line \d+,\s*)?(?:version|release)\s*[`'‘]([^`'’]*)['’]\s*"
                       r"of\s*(?:package|class|document class|LaTeX)?\s*([\w\-]+),?\s*but only\s*(?:version|release)\s*"
                       r"[`'‘]([^`'’]*)['’]", re.S)
_TOO_OLD = re.compile(r"Package ([\w\-]+) (?:Error|Warning): .*?(?:too old|update your|newer version)", re.I)


def package_for_file(name: str) -> str:
    stem = Path(name).name
    for suffix in ('.code.tex', '.sty', '.cls', '.def', '.cfg', '.bst', '.bbx', '.cbx', '.lbx', '.clo', '.fd', '.ldf',
                   '.tex'):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    if stem.startswith('tikzlibrary') or stem.startswith('pgflibrary'):
        return 'pgf'
    if stem.startswith('beamertheme') and stem not in KNOWN:
        return 'beamer'
    return KNOWN.get(stem, stem)


def needs(log: str) -> list[Need]:
    """Packages the log says are missing or too old (most useful first, no duplicates)."""
    text = re.sub(r'(?m)^(.{79})\n(?=\S)', r'\1', log or '')
    found, seen = [], set()

    def add(need):
        if need.package and need.package not in seen:
            seen.add(need.package)
            found.append(need)
    for pattern in _MISSING:
        for m in pattern.finditer(text):
            name = m.group(1)
            if pattern is _MISSING[3]:
                add(Need('missing', '', 'cm-super' if name.startswith(('ec', 'tc')) else name.rstrip('0123456789'),
                         'font ' + name))
                continue
            if '/' in name or name.startswith('.'):
                if not name.endswith(('.sty', '.cls')):
                    continue                                   # a missing project file, not a package
            if name.endswith('.tex') and not name.endswith('.code.tex'):
                continue
            add(Need('missing', Path(name).name, package_for_file(name)))
    for m in _BABEL.finditer(text):
        add(Need('missing', '', f'babel-{m.group(1).lower()}', f'babel language {m.group(1)}'))
    for m in _OUTDATED.finditer(text):
        add(Need('outdated', '', package_for_file(m.group(2) + '.sty'), f'needs {m.group(1)}, has {m.group(3)}'))
    for m in _TOO_OLD.finditer(text):
        add(Need('outdated', '', package_for_file(m.group(1) + '.sty')))
    return found


def is_installed(file: str) -> bool:
    exe = tex.which('kpsewhich')
    if not exe or not file:
        return False
    try:
        out = subprocess.run([exe, file], capture_output=True, text=True, timeout=20,
                             env={**os.environ, 'PATH': tex.search_path()}).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(out.strip())


def package_name_valid(name: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+\-]{0,80}', name or ''))


# ------------------------------------------------------------------------- managers
def manager() -> str | None:
    """'miktex' | 'tlmgr' | 'apt' | None (what can install packages on this computer)."""
    if tex.which('miktex') or tex.which('mpm'):
        return 'miktex'
    if tex.which('tlmgr'):
        return 'tlmgr'
    if sys.platform.startswith('linux') and shutil.which('apt-get'):
        return 'apt'
    return None


def manual_command(packages, update=False) -> str:
    """What to type in a terminal when automatic installation is not possible."""
    names = ' '.join(packages)
    kind = manager()
    if kind == 'miktex':
        return f'miktex packages {"update" if update else "install"} {names}'
    if kind == 'tlmgr':
        if _is_debian_texlive():
            return f'tlmgr init-usertree; tlmgr --usermode install {names}   (or: sudo apt install texlive-full)'
        return f'{"sudo " if sys.platform == "darwin" else ""}tlmgr {"update" if update else "install"} {names}'
    if kind == 'apt':
        return 'sudo apt install texlive-latex-extra texlive-science   (or texlive-full for everything)'
    return tex.install_hint()


def _env():
    return {**os.environ, 'PATH': tex.search_path(), 'LC_ALL': os.environ.get('LC_ALL') or 'C'}


def _run(command, log, timeout=TIMEOUT):
    log('$ ' + ' '.join(command))
    kwargs = {}
    if sys.platform.startswith('win'):
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf8', errors='replace',
                                timeout=timeout, env=_env(), **kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        log(str(exc))
        return 1, str(exc)
    output = (result.stdout or '') + (result.stderr or '')
    if output.strip():
        log(output.strip()[-4000:])
    return result.returncode, output


def _is_debian_texlive() -> bool:
    exe = tex.which('tlmgr') or ''
    return sys.platform.startswith('linux') and (exe.startswith('/usr/bin') or Path('/usr/share/texlive').is_dir()) \
        and Path('/etc/debian_version').exists()


def texlive_year() -> int | None:
    exe = tex.which('tlmgr') or tex.which('pdflatex')
    if not exe:
        return None
    try:
        out = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=30, env=_env()).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'TeX Live (?:\(https?://tug\.org/texlive\) version )?(\d{4})', out)
    return int(m.group(1)) if m else None


def _tlmgr_resolve(tlmgr, files, extra, log) -> list[str]:
    names = []
    for file in files:
        code, out = _run([tlmgr, *extra, 'search', '--global', '--file', '/' + file], log, timeout=180)
        if code == 0:
            for line in out.splitlines():
                m = re.match(r'^([A-Za-z0-9][\w.+\-]*):\s*$', line)
                if m and m.group(1) not in names:
                    names.append(m.group(1))
                    break
    return names


def _tlmgr_collection(tlmgr, package, extra, log) -> str | None:
    code, out = _run([tlmgr, *extra, 'info', package], log, timeout=180)
    m = re.search(r'^collection:\s*(\S+)', out, re.M)
    return m.group(1) if code == 0 and m else None


def install(needs_or_names, update=False, log=print) -> tuple[bool, str]:
    """Install (or update) packages. Returns ``(ok, message)``; ``log`` receives the commands and output."""
    items = list(needs_or_names)
    packages, files = [], []
    for item in items:
        if isinstance(item, Need):
            packages.append(item.package)
            if item.file:
                files.append(item.file)
        else:
            packages.append(str(item))
    packages = [p for p in dict.fromkeys(packages) if package_name_valid(p)]
    if not packages:
        return False, 'No valid package name'
    kind = manager()
    if kind is None:
        return False, 'No LaTeX package manager found. ' + tex.install_hint()
    if kind == 'miktex':
        ok = _miktex(packages, update, log)
    elif kind == 'tlmgr':
        ok = _tlmgr(packages, files, update, log)
    else:
        ok = _apt(packages, None, log)
    if ok and files:
        missing = [f for f in files if not is_installed(f)]
        if missing:
            return False, ('The installer finished, but LaTeX still cannot find ' + ', '.join(missing) +
                           '. Try in a terminal: ' + manual_command(packages, update))
    if ok:
        return True, f'{"Updated" if update else "Installed"} {", ".join(packages)}'
    return False, 'Automatic installation did not work. In a terminal: ' + manual_command(packages, update)


def _miktex(packages, update, log) -> bool:
    miktex = tex.which('miktex')
    if miktex:
        if update:
            return _run([miktex, 'packages', 'update', *packages], log)[0] == 0
        if _run([miktex, 'packages', 'install', *packages], log)[0] == 0:
            return True
        _run([miktex, 'packages', 'update-package-database'], log)
        return _run([miktex, 'packages', 'install', *packages], log)[0] == 0
    mpm = tex.which('mpm')
    flag = '--update=' if update else '--install='
    return all(_run([mpm, flag + p], log)[0] == 0 for p in packages)


def _tlmgr(packages, files, update, log) -> bool:
    tlmgr = tex.which('tlmgr')
    debian = _is_debian_texlive()
    extra = []
    if debian:
        _run([tlmgr, 'init-usertree'], log, timeout=120)          # harmless when it exists already
        extra = ['--usermode']
    year = texlive_year()
    resolved = _tlmgr_resolve(tlmgr, files, extra, log) if files else []
    names = list(dict.fromkeys(resolved + [p for p in packages if p not in resolved])) if resolved else packages
    verb = 'update' if update and not debian else 'install'
    attempts = [[tlmgr, *extra, verb, *names]]
    if year:
        attempts.append([tlmgr, *extra, '--repository', HISTORIC.format(year=year), verb, *names])
    for command in attempts:
        code, out = _run(command, log)
        if code == 0:
            return True
        low = out.lower()
        if not debian and ('permission denied' in low or 'not writable' in low or 'cannot be written' in low):
            if sys.platform == 'darwin':
                quoted = ' '.join(command).replace('"', '\\"')
                script = f'do shell script "{quoted}" with administrator privileges'
                if _run(['osascript', '-e', script], log)[0] == 0:
                    return True
            elif shutil.which('pkexec'):
                if _run(['pkexec', *command], log)[0] == 0:
                    return True
    if debian:
        collection = None
        for name in names:
            collection = _tlmgr_collection(tlmgr, name, extra + (['--repository', HISTORIC.format(year=year)]
                                                                 if year else []), log)
            if collection:
                break
        return _apt(packages, collection, log)
    return False


def _apt(packages, collection, log) -> bool:
    if not (sys.platform.startswith('linux') and shutil.which('apt-get') and shutil.which('pkexec')):
        return False
    targets = []
    for p in packages:
        if p.startswith('babel-') and p[6:] in BABEL_DEBIAN:
            targets.append(BABEL_DEBIAN[p[6:]])
    targets.append(DEBIAN.get(collection or '', 'texlive-latex-extra'))
    if 'texlive-latex-extra' not in targets:
        targets.append('texlive-latex-extra')
    return _run(['pkexec', 'apt-get', 'install', '-y', *dict.fromkeys(targets)], log)[0] == 0
