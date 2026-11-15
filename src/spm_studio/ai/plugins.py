"""Atomic-ish staged installation of manifest-based analysis modules.

Existing app executes modules as subprocesses. Staging tests are not a secure OS
sandbox; do not accept arbitrary untrusted code without inspection.
"""
from __future__ import annotations
import ast,json,os,shutil,tempfile,subprocess,sys,uuid
from pathlib import Path
from spm_studio.core.registry import load_manifest
from .security import checked_child


def validate_staged(folder:Path):
    folder=Path(folder).expanduser().resolve()
    info=load_manifest(folder/'module.json')
    if not folder.is_dir():raise ValueError('Module folder not found')
    if folder.is_symlink():raise ValueError('Symlink modules are not accepted')
    files=[]
    for p in folder.rglob('*'):
        if p.is_symlink():raise ValueError('Module must contain no symlinks: '+p.name)
        if p.is_file():
            if not (p.suffix in {'.py','.json','.md','.txt','.csv'}):
                raise ValueError('Unexpected executable or binary file: '+p.name)
            if p.stat().st_size>3_000_000:raise ValueError('Oversize plugin file: '+p.name)
            if p.suffix=='.py':ast.parse(p.read_text(encoding='utf8'),filename=str(p))
            files.append(p)
    if len(files)>80:raise ValueError('Plugin file count limit exceeded')
    return info,files


def preflight(folder:Path):
    info,files=validate_staged(folder)
    # Syntax compilation is safe and does not execute module code.
    cmd=[sys.executable,'-I','-c',
         'import ast, pathlib, sys; [ast.parse(pathlib.Path(p).read_text(encoding="utf8")) for p in sys.argv[1:]]']
    proc=subprocess.run(cmd+[str(p) for p in files if p.suffix=='.py'],
                        capture_output=True,text=True,timeout=15,check=False)
    if proc.returncode:raise ValueError('Python syntax test failed: '+proc.stderr[-1000:])
    return info,len(files)


def install_staged(folder:Path,target_root:Path) -> str:
    info,_=preflight(folder)
    target_root=Path(target_root).expanduser().resolve()
    target_root.mkdir(parents=True,exist_ok=True)
    destination=target_root/info.id
    if destination.exists():raise FileExistsError('Module already exists; remove/backup it manually: '+str(destination))
    with tempfile.TemporaryDirectory(prefix='.spm-stage-',dir=target_root) as staging:
        stage=Path(staging)/info.id
        shutil.copytree(folder,stage,symlinks=False)
        preflight(stage)
        os.replace(stage,destination)
    return info.id


def remove_installed(name:str,root:Path):
    from spm_studio.core.registry import load_manifest
    root=Path(root).expanduser().resolve()
    dest=checked_child(root,root/name)
    if dest.name!=name or not dest.is_dir() or dest.is_symlink():
        raise ValueError('Invalid or missing plugin')
    info=load_manifest(dest/'module.json')
    if info.id!=name:raise ValueError('Manifest mismatch')
    # Rollback is by moving rather than irreversibly removing analysis code.
    backup=root/'.removed_plugins'/f'{name}-{uuid.uuid4().hex[:8]}'
    backup.parent.mkdir(parents=True,exist_ok=True)
    dest.rename(backup)
    return backup
