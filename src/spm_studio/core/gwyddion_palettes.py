"""Import the *actual* installed Gwyddion GwyGradient resources.

Gwyddion gradients are ASCII resources with ``Gwyddion resource GwyGradient``
followed by increasing ``position r g b alpha`` control points in [0, 1].
These points are interpolated to 256 RGB rows, which Studio can read without
loading Gwyddion at runtime. Original resources are never modified.
"""
from __future__ import annotations
from pathlib import Path
import os
import re
import numpy as np


def parse_gwyddion_gradient(path: str | Path) -> np.ndarray:
    """Return an RGB 256x3 LUT, or raise for invalid/unsupported resources."""
    raw=Path(path).read_text(encoding='utf-8-sig')
    rows=[]
    first=False
    for line in raw.splitlines():
        stripped=line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if not first:
            if stripped!='Gwyddion resource GwyGradient':
                raise ValueError('Not a GwyGradient resource')
            first=True
            continue
        fields=stripped.split()
        if len(fields)!=5:
            raise ValueError('Gwyddion gradient row must have position + RGBA values')
        try:rows.append(tuple(float(v) for v in fields))
        except ValueError as exc:raise ValueError('Invalid gradient numeric value') from exc
    if len(rows)<2:
        raise ValueError('Gwyddion gradient requires at least two color stops')
    arr=np.asarray(rows,dtype=np.float64)
    if not np.isfinite(arr).all() or np.any(arr<0) or np.any(arr>1):
        raise ValueError('Invalid gradient: points must be finite and in 0–1')
    if abs(arr[0,0])>1e-9 or abs(arr[-1,0]-1.0)>1e-9 or np.any(np.diff(arr[:,0])<=0):
        raise ValueError('Gradient positions must strictly increase from 0 to 1')
    if not np.allclose(arr[:,4],1):
        raise ValueError('Unsupported non-opaque Gwyddion gradient')
    x=np.linspace(0,1,256)
    return np.stack([np.interp(x,arr[:,0],arr[:,i]) for i in (1,2,3)],axis=-1)


def safe_gradient_name(name):
    """Keep the original visible resource name, while preventing traversal."""
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(name)).strip(' .')[:96]


def import_gwyddion_directory(source: str | Path, destination: str | Path) -> list[Path]:
    source=Path(source).expanduser()
    destination=Path(destination).expanduser()
    if not source.is_dir():raise ValueError(f'Not a gradient directory: {source}')
    destination.mkdir(parents=True,exist_ok=True)
    imported=[]
    for entry in sorted(source.iterdir()):
        if not entry.is_file() or entry.is_symlink() or entry.name.startswith('.'):
            continue
        title=safe_gradient_name(entry.name)
        if not title:continue
        target=destination/f'Gwy - {title}.csv'
        if target.exists():continue
        try:
            rgb=parse_gwyddion_gradient(entry)
        except (OSError,UnicodeError,ValueError):
            continue
        # Preserve all user palettes. Stage writes and make visible atomically.
        temp=target.with_suffix('.csv.tmp')
        try:
            np.savetxt(temp,rgb,delimiter=',',fmt='%.8f')
            temp.replace(target)
            imported.append(target)
        finally:
            temp.unlink(missing_ok=True)
    return imported


def gwyddion_directories() -> list[Path]:
    """Known system and per-user gradient folders; no Gwyddion dependency."""
    home=Path.home()
    candidates=[
        home/'.gwyddion'/'gradients',
        home/'.config'/'gwyddion'/'gradients',
        Path('/usr/share/gwyddion/gradients'),
        Path('/usr/local/share/gwyddion/gradients'),
        Path('/usr/share/gwyddion2/gradients'),
    ]
    for key in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA','APPDATA'):
        value=os.environ.get(key)
        if value:
            candidates.extend([Path(value)/'Gwyddion'/'gradients',Path(value)/'gwyddion'/'gradients',
                               Path(value)/'Gwyddion'/'share'/'gwyddion'/'gradients'])
    # macOS: Gwyddion.app bundle, Homebrew and MacPorts
    for prefix in (Path('/Applications/Gwyddion.app/Contents/Resources'),home/'Applications/Gwyddion.app/Contents/Resources',
                   Path('/opt/homebrew'),Path('/opt/local')):
        candidates.extend([prefix/'share'/'gwyddion'/'gradients',prefix/'gradients'])
    # Do not recursively scan arbitrary disks; only discover known locations.
    return [folder for folder in dict.fromkeys(candidates) if folder.is_dir()]


def import_installed_gwyddion_gradients(destination: str | Path) -> list[Path]:
    imported=[]
    for folder in gwyddion_directories():
        imported.extend(import_gwyddion_directory(folder,destination))
    return imported
