"""The bundled KBr tutorial scans: three unmodified Nanonis .sxm files, checked by SHA-256.

The originals inside the installed package are never opened for writing. The tutorial works on a copy in a
user-owned folder (``<data>/tutorial/kbr_scans``) so nothing a lesson does can touch the bundled files.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

FILES = {
    '20261119-KBr001_008.sxm': 'cd842999e4257341837771fe2f2911f2d910f04c75324bda3235e87bcb263514',
    '20261119-KBr001_009.sxm': 'b5dfb2f61f69ca44f94e16a6966ee044c513ef47815e98a3b210db8b0ae27554',
    '20261119-KBr001_015.sxm': '6ea4232c8bd5887923a73691e8561466c762963f3bd46b5ef147ab8890d66424',
}
MAIN, UP_SCAN, INCOMPLETE = list(FILES)


def bundled_dir() -> Path:
    return Path(__file__).resolve().parents[1] / 'resources' / 'tutorial_scan'


def manifest() -> dict:
    return json.loads((bundled_dir() / 'manifest.json').read_text(encoding='utf8'))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def verify(folder: Path | None = None) -> dict[str, bool]:
    """``{file name: checksum matches}`` for the bundled (or another) folder."""
    folder = folder or bundled_dir()
    return {name: (folder / name).is_file() and sha256(folder / name) == digest for name, digest in FILES.items()}


def workspace() -> Path:
    from spm_studio.core import paths
    return paths.data_dir() / 'tutorial' / 'kbr_scans'


def prepare_workspace() -> Path:
    """Copy the scans (and their manifest/README) into the user's tutorial folder; return that folder.

    A file already there is kept when its checksum is right and replaced by a fresh copy otherwise.
    """
    source, target = bundled_dir(), workspace()
    target.mkdir(parents=True, exist_ok=True)
    bad = [name for name, ok in verify(source).items() if not ok]
    if bad:
        raise RuntimeError('The bundled tutorial scans are damaged: ' + ', '.join(bad) + '. Reinstall SPM Studio.')
    for name in list(FILES) + ['manifest.json', 'README.md', 'SHA256SUMS.txt']:
        dest = target / name
        if name in FILES and dest.is_file() and sha256(dest) == FILES[name]:
            continue
        if name not in FILES and dest.is_file():
            continue
        shutil.copyfile(source / name, dest)
    return target
