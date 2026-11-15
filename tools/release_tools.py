#!/usr/bin/env python3
"""Release helpers (used by .github/workflows/release.yml and by hand).

    python tools/release_tools.py set-repo OWNER/NAME     # point updates + README + get scripts at your repo
    python tools/release_tools.py show-repo               # which repository the project points at
    python tools/release_tools.py check-repo OWNER/NAME   # fail unless the project points at OWNER/NAME
    python tools/release_tools.py check-tag v0.0.1        # tag must equal pyproject version
    python tools/release_tools.py notes 0.0.1             # CHANGELOG section -> stdout (release notes)
    python tools/release_tools.py check-changelog         # CHANGELOG section + README badge match the version
    python tools/release_tools.py bump 0.0.2              # new version: pyproject, README badge, CHANGELOG stub
    python tools/release_tools.py archive OUT_DIR         # the cross-platform release archive (one zip)

The release archive is the source code plus installers (the same files for every operating system);
each installer builds a private Python environment on the user's machine. There are no compiled
executables. ``zips`` is kept as an alias of ``archive`` for older instructions.
"""
import datetime, json, os, re, stat, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = 'YOUR_GITHUB_USER/SPM-Studio'
CONFIG = ROOT / 'src/spm_studio/update_config.json'
REPO_FILES = ['README.md', 'README_INSTALL.md', 'INSTALL_README_Ubuntu.md', 'INSTALL_README_Windows.md',
              'INSTALL_README_macOS.md', 'get-spm-studio.sh', 'get-spm-studio.ps1', 'docs/RELEASING.md',
              'docs/UPDATES.md', 'GITHUB_FIRST_UPLOAD.md', 'CONTRIBUTING.md', 'SECURITY.md',
              'src/spm_studio/update_config.json']
SKIP_DIRS = {'__pycache__', '.pytest_cache', '.git', '.ruff_cache', '.mypy_cache', 'venv', '.venv', 'node_modules',
             'dist', 'build', '.idea', '.vscode'}
SKIP_FILES = {'auth.json', '.env', '.DS_Store', 'Thumbs.db'}
REPO_RE = r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+'


def version() -> str:
    return re.search(r'^version = "(.+)"', (ROOT / 'pyproject.toml').read_text(encoding='utf8'), re.M).group(1)


def configured_repo() -> str:
    return json.loads(CONFIG.read_text(encoding='utf8')).get('repository', PLACEHOLDER)


def set_repo(repo: str):
    if not re.fullmatch(REPO_RE, repo):
        sys.exit('Use OWNER/NAME, e.g. jdoe/SPM-Studio')
    current = configured_repo()
    for rel in REPO_FILES:
        p = ROOT / rel
        if p.is_file():
            text = p.read_text(encoding='utf8')
            new = text.replace(current, repo).replace(PLACEHOLDER, repo)
            if new != text:
                p.write_text(new, encoding='utf8')
                print('updated', rel)
    print('Repository set to', repo)


def check_repo(expected: str):
    current = configured_repo()
    if current == PLACEHOLDER:
        sys.exit(f'The project still points at the placeholder {PLACEHOLDER}. Run:\n'
                 f'  python tools/release_tools.py set-repo {expected or "OWNER/SPM-Studio"}\n'
                 'commit, push, and tag again. Otherwise installed copies could not find their updates.')
    if expected and current.lower() != expected.lower():
        sys.exit(f'update_config.json points at {current}, but this is {expected}. Run set-repo {expected}.')
    print('ok', current)


README_BADGE = re.compile(r'(img\.shields\.io/badge/version-)([0-9A-Za-z.+-]+?)(-[0-9A-Fa-f]{6}|-[a-z]+)')


def readme_version() -> str:
    m = README_BADGE.search((ROOT / 'README.md').read_text(encoding='utf8'))
    return m.group(2).replace('--', '-') if m else ''


def bump(new: str):
    if not re.fullmatch(r'\d+\.\d+\.\d+([-.]?(a|b|rc|alpha|beta|dev)\.?\d*)?', new or ''):
        sys.exit('Use a version like 0.0.2 (or 0.1.0rc1)')
    old = version()
    toml = ROOT / 'pyproject.toml'
    toml.write_text(re.sub(r'^version = ".+"$', f'version = "{new}"', toml.read_text(encoding='utf8'), count=1,
                           flags=re.M), encoding='utf8')
    readme = ROOT / 'README.md'
    text = readme.read_text(encoding='utf8')
    readme.write_text(README_BADGE.sub(lambda m: m.group(1) + new.replace('-', '--') + m.group(3), text, count=1),
                      encoding='utf8')
    log = ROOT / 'CHANGELOG.md'
    text = log.read_text(encoding='utf8')
    if not re.search(rf'^##\s+\[?v?{re.escape(new)}\b', text, re.M):
        stub = f'## {new} — {datetime.date.today().isoformat()}\n\n- Describe what is new for users.\n\n'
        m = re.search(r'^##\s', text, re.M)
        text = text[:m.start()] + stub + text[m.start():] if m else text.rstrip() + '\n\n' + stub
        log.write_text(text, encoding='utf8')
    print(f'{old} -> {new}: pyproject.toml, README.md badge, CHANGELOG.md section. Now write the notes in CHANGELOG.md.')


def notes(v: str) -> str:
    sys.path.insert(0, str(ROOT / 'src'))
    from spm_studio.core.updates import changelog_sections
    for ver, body in changelog_sections((ROOT / 'CHANGELOG.md').read_text(encoding='utf8')):
        if ver == v.lstrip('v'):
            return body
    return f'SPM Studio {v}'


def release_files(exclude: Path | None = None) -> list[Path]:
    files = []
    for root, dirs, fs in os.walk(ROOT):
        here = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (exclude and (here / d).resolve() == exclude))
        files += [here / f for f in sorted(fs)
                  if not f.endswith(('.pyc', '.pyo')) and f not in SKIP_FILES and not f.startswith('.env')]
    return files


def archive(out: Path) -> Path:
    """One zip for all operating systems: SPM-Studio-<version>/... (same layout as a GitHub source archive)."""
    out.mkdir(parents=True, exist_ok=True)
    v = version()
    top = f'SPM-Studio-{v}/'
    z = out / f'SPM-Studio-{v}.zip'
    with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in release_files(out.resolve()):
            info = zipfile.ZipInfo.from_file(p, top + p.relative_to(ROOT).as_posix())
            info.external_attr = (stat.S_IFREG | (0o755 if p.suffix in ('.sh', '.command') else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, p.read_bytes())
    print(z)
    return z


if __name__ == '__main__':
    cmd, arg = (sys.argv[1:] + ['', ''])[:2]
    if cmd == 'set-repo':
        set_repo(arg)
    elif cmd == 'bump':
        bump(arg)
    elif cmd == 'show-repo':
        print(configured_repo())
    elif cmd == 'check-repo':
        check_repo(arg)
    elif cmd == 'check-tag':
        if arg.lstrip('v') != version():
            sys.exit(f'Tag {arg} does not match pyproject version {version()}')
        print('ok', version())
    elif cmd == 'check-changelog':
        sys.path.insert(0, str(ROOT / 'src'))
        from spm_studio.core.updates import changelog_sections
        found = dict(changelog_sections((ROOT / 'CHANGELOG.md').read_text(encoding='utf8')))
        if not found.get(version()):
            sys.exit(f'CHANGELOG.md has no (or an empty) "## {version()}" section: users would see no release notes.')
        if 'Describe what is new for users.' in found[version()]:
            sys.exit(f'CHANGELOG.md "## {version()}" still contains the placeholder text from `bump`.')
        if readme_version() != version():
            sys.exit(f'README.md shows version {readme_version() or "(no badge)"}, pyproject.toml has {version()}. '
                     f'Run: python tools/release_tools.py bump {version()}')
        print('ok', version())
    elif cmd == 'notes':
        print(notes(arg or version()))
    elif cmd in ('archive', 'zips'):
        archive(Path(arg or 'dist'))
    else:
        sys.exit(__doc__)
