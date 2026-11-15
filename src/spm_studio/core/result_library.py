"""Shared SPM output layout, independent of the scientific engine.

A scan has *one visible results directory* with Images/, Plots/ and Data/.
Images/ holds PDF/SVG image overlays and native GWY data; Plots/ holds PDF/SVG
plots. Data/ holds private-by-convention, uniquely named run folders with the
scientific inputs, CSV/JSON tables and raster dependencies. None of the original
scan files or previous versions of result files is ever deleted or overwritten.
"""
from __future__ import annotations
import json
import re
import shutil
from pathlib import Path

PUBLIC={'.pdf','.svg','.gwy'}


def run_path(scan_path:Path,module_id:str,timestamp:str,token:str)->Path:
    """Stage each analysis inside Data, not in another public directory tree."""
    module=re.sub('[^a-z0-9_-]+','_',str(module_id).lower()).strip('_')[:55]
    scan=Path(scan_path)
    return scan.parent/'SPM_Studio_Results'/scan.stem/'Data'/f'{module}_{timestamp}_{token}'


def _priority(file:Path):
    n=file.name.lower()
    return (0 if '07_reference_scan_lattice_overlay' in n else
            1 if 'lattice_overlay' in n else
            2 if any(term in n for term in ('summary','comparison','overview')) else 3,n)


def public_files(folder:Path)->list[Path]:
    """Publication figures (SVG / PDF) of exactly one run, including old 0.7-style folders.

    When the same figure exists as SVG and PDF only one entry is listed (SVG first),
    so a result never appears twice in the results preview.
    """
    folder=Path(folder)
    patterns=('*.svg','*.pdf')
    if folder.parent.name=='Data':
        visible=folder.parent.parent
        prefix=folder.name+'__'
        matches=[p for section in ('Images','Plots') for pat in patterns for p in (visible/section).glob(prefix+pat)]
    else:
        matches=[p for section in ('Images','Plots') for pat in patterns for p in (folder/section).glob(pat)]
        if not matches and folder.is_dir():
            # Compatible with original v0.7 deep vendor outputs. Read-only.
            matches=list(folder.rglob('*.pdf'))
    best={}
    for p in matches:
        if not p.is_file():continue
        key=(p.parent,p.stem)
        if key not in best or (p.suffix.lower()=='.svg' and best[key].suffix.lower()!='.svg'):
            best[key]=p
    return sorted(best.values(),key=_priority)


def preview_files(folder:Path, reports=None)->list[Path]:
    """Native full-resolution overlay PNGs first; vector PDFs remain browsable."""
    folder=Path(folder)
    report_list=list(public_files(folder) if reports is None else reports)
    pngs=[]
    if folder.is_dir():
        pngs=[p for p in folder.glob('*.png') if p.name.lower() in
              ('lattice_plus_molecules.png','lattice_preview.png','lattice_overlay.png',
               'molecule_overlay.png','scan_overlay.png')]
    pngs.sort(key=lambda p:(0 if p.name=='lattice_plus_molecules.png' else 1,p.name))
    return pngs+report_list


def _kind(src:Path)->str:
    ext=src.suffix.lower()
    name=src.stem.lower()
    if ext=='.gwy' or (ext in ('.pdf','.svg') and any(
       mark in name for mark in ('scan_lattice_overlay','lattice_overlay','masked_image',
                                 'molecule_overlay','scan_overlay','lattice_plus_molecules'))):
        return 'Images'
    if ext in ('.pdf','.svg'):
        return 'Plots'
    return 'Data'


def organize_run(folder:Path,run_files:list[str]|None=None,*,success=True):
    """Move public output into one per-scan folder. Preserve data dependencies.

    All operations are restricted to this run's directory and to the public
    Images/Plots directories for the *same scan*. Existing visible files are
    never overwritten. On a failure, the run's internal files remain available.
    """
    root=Path(folder).resolve()
    if not root.is_dir():raise FileNotFoundError(root)
    is_compact=root.parent.name=='Data'
    visible=root.parent.parent if is_compact else root
    for section in ('Images','Plots'):(visible/section).mkdir(parents=True,exist_ok=True)
    if not is_compact:(root/'Data').mkdir(exist_ok=True)
    candidates=[p for p in root.rglob('*') if p.is_file() and
                (is_compact or not any(a in ('Images','Plots','Data') for a in p.relative_to(root).parts[:-1]))]
    # Preserve the best-quality original multiframe lattice report, not the
    # inferior raster-only lattice_preview.pdf when both are present.
    better=any('07_reference_scan_lattice_overlay' in p.name.lower() and p.suffix.lower()=='.pdf' for p in candidates)
    relocations={}
    trash=[]
    for src in sorted(candidates,key=lambda p:str(p)):
        group=_kind(src)
        if group=='Data':
            target=(root if is_compact else root/'Data')/src.name
        else:
            if src.name.lower()=='lattice_preview.pdf' and better:
                trash.append(src)
                continue
            name=(root.name+'__'+src.name) if is_compact else src.name
            target=visible/group/name
        if src==target:continue
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            i=2
            while target.with_name(f'{target.stem}_{i}{target.suffix}').exists():i+=1
            target=target.with_name(f'{target.stem}_{i}{target.suffix}')
        old=str(src.resolve())
        shutil.move(str(src),str(target))
        relocations[old]=str(target.resolve())
    for old in trash:old.unlink(missing_ok=True)
    # PNG-only modules still need a human-viewable PDF. Use the original pixels
    # at 300 dpi and retain the PNG privately when other tools reference it.
    if success:
        data_folder=root if is_compact else root/'Data'
        for png in data_folder.glob('*.png'):
            if png.stem.lower() in ('cropped_scan','plain_scan','lattice_preview'):
                continue
            visible_name=(root.name+'__'+png.stem+'.pdf') if is_compact else png.stem+'.pdf'
            dest=visible/('Images' if any(x in png.stem.lower() for x in ('overlay','masked_image')) else 'Plots')/visible_name
            if dest.exists():continue
            if (visible/'Images'/visible_name).exists() or (visible/'Plots'/visible_name).exists():continue
            try:
                from PIL import Image
                with Image.open(png) as im:
                    if im.width<180 or im.height<120:continue
                    if im.mode not in ('RGB','L'):im=im.convert('RGB')
                    im.save(dest,'PDF',resolution=300.0)
            except (ImportError,OSError,ValueError):pass
    # JSON manifests can be consumed by molecule-placement and multiframe tools.
    # Rewrite only *exact* generated absolute paths after moving outputs.
    def rewrite(value):
        if isinstance(value,str):return relocations.get(value,value)
        if isinstance(value,list):return [rewrite(x) for x in value]
        if isinstance(value,dict):return {key:rewrite(v) for key,v in value.items()}
        return value
    data_folder=root if is_compact else root/'Data'
    for file in data_folder.glob('*.json'):
        try:
            original=json.loads(file.read_text(encoding='utf-8'))
            updated=rewrite(original)
            if original!=updated:
                file.write_text(json.dumps(updated,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
        except (OSError,UnicodeDecodeError,ValueError):pass
    # Remove redundant *generated* raster plot files only after the equivalent
    # PDF has been safely published. Keep every PNG referenced by the science
    # manifests, plus the lattice/molecule image-dependency exceptions.
    # This operates on a newly staged internal run, never on acquisition data.
    if success:
        referenced_pngs={'lattice_preview.png','cropped_scan.png','plain_scan.png'}
        def references(value):
            if isinstance(value,str) and value.lower().endswith('.png'):
                referenced_pngs.add(Path(value).name)
            elif isinstance(value,list):
                for entry in value:references(entry)
            elif isinstance(value,dict):
                for entry in value.values():references(entry)
        for manifest in data_folder.glob('*.json'):
            try:references(json.loads(manifest.read_text(encoding='utf-8')))
            except (OSError,ValueError,UnicodeDecodeError):continue
        prefix=root.name+'__' if is_compact else ''
        published={p.stem.removeprefix(prefix) for section in ('Images','Plots')
                   for p in (visible/section).glob('*.pdf')
                   if not is_compact or p.stem.startswith(prefix)}
        for raster in data_folder.glob('*.png'):
            if raster.name not in referenced_pngs and raster.stem in published:
                raster.unlink(missing_ok=True)

    # Delete *empty* intermediate subdirectories only, not user data.
    for directory in sorted((p for p in root.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
        if directory!=root and directory!=data_folder and directory.name not in ('Images','Plots'):
            try:directory.rmdir()
            except OSError:pass
    files=[]
    for item in run_files or []:
        path=str(Path(item).resolve())
        current=relocations.get(path,path)
        if Path(current).is_file() and current not in files:files.append(current)
    for file in public_files(root):
        if str(file) not in files:files.append(str(file))
    gwys=(visible/'Images').glob((root.name+'__*.gwy') if is_compact else '*.gwy')
    for file in sorted(gwys):
        if str(file) not in files:files.append(str(file))
    return {'files':files,'context':data_folder/'context.json','folder':root,
            'public':public_files(root),'moved':relocations,'visible':visible}
