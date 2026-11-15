"""Bridge into the archived MultiFrame 0.1.2 computational engines.

Runs in Studio's external analysis worker; nothing is imported into the Qt GUI.
Only selected source files are discovered, preserving the original reader,
geometry reconstruction, drift fitter, lattice solver and stacker unchanged.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path


def _engine():
    vendored=Path(__file__).resolve().parent/'vendor'
    if not (vendored/'spm_multiframe'/'analysis'/'pipeline.py').is_file():
        raise RuntimeError('Original spm-multiframe-v0.1.2 vendor engine is missing')
    if str(vendored) not in sys.path:sys.path.insert(0,str(vendored))


def selected_sources(ctx, excludes='', include_dataset=False):
    """Select ONLY scans listed in Studio, never unrelated files in a folder."""
    ignored={x.strip() for x in excludes.split(',') if x.strip()}
    selected=Path(ctx.scan_path).resolve()
    if include_dataset:
        # The user explicitly opts into the entire CURRENT FOLDER, not every
        # unrelated scan open elsewhere in Studio. Do not recurse into results.
        inputs=[selected,*sorted(p for p in selected.parent.iterdir()
                                 if p.is_file() and p.suffix.lower()==selected.suffix.lower())]
    else:
        inputs=[selected]
    inputs=list(dict.fromkeys(inputs))
    scans=[x.resolve() for x in inputs if x.suffix.lower() in ('.sxm','.gwy')
           and x.name not in ignored]
    scans=list(dict.fromkeys(scans))
    for file in scans:
        if not file.is_file():raise FileNotFoundError(f'Scan not found: {file}')
    if not scans:raise ValueError('No scans selected')
    suffixes={x.suffix.lower() for x in scans}
    if len(suffixes)!=1:
        raise ValueError('Please select either SXM or GWY sources, not a mixture. '
                         'The original engine treats different format datasets separately.')
    root=Path(os.path.commonpath([str(p.parent) for p in scans]))
    return root,scans,('gwy' if '.gwy' in suffixes else 'sxm')


def run_original(ctx, *, estimate_drift=False, stack=False,
                 registration_channel=None, stack_channels=None,
                 trace='forward', excludes='', method='sigma_clipped_mean', use_all_scans=False,
                 drift_bootstrap=32, lattice_bootstrap=400,
                 atom_tracking_path='', atom_vx=None, atom_vy=None,
                 atom_units='nm/s', atom_convention='correction'):
    _engine()
    from spm_multiframe.analysis import pipeline
    from spm_multiframe.config import AnalysisConfig,StackConfig
    from spm_multiframe.io.atom_tracking import (load_atom_tracking_hint,
                                                  manual_atom_tracking_hint,
                                                  find_first_atom_tracking_hint)
    from spm_multiframe.stacking.stack_pipeline import run_stack
    folder,files,fmt=selected_sources(ctx,excludes,include_dataset=use_all_scans)
    channel=str(registration_channel or ctx.channel)
    if stack and len(files)<2:raise ValueError('Stacking requires at least two selected scans')
    if estimate_drift and len(files)<2:raise ValueError('Drift estimation requires at least two selected scans')
    ctx.log(f'Using original MultiFrame 0.1.2 engine: {len(files)} selected {fmt.upper()} scans'
            + (' (all scans in current folder)' if use_all_scans else ' (current scan only)'))
    ctx.log(f'Source dataset root: {folder}')
    analysis_output=ctx.output_dir/'multiframe_analysis'
    cfg=AnalysisConfig()
    cfg.trace_direction=str(trace)
    cfg.drift_bootstrap_repeats=int(drift_bootstrap)
    cfg.lattice_bootstrap_repeats=int(lattice_bootstrap)
    hint=None
    if estimate_drift:
        if atom_tracking_path.strip():
            hint=load_atom_tracking_hint(Path(atom_tracking_path).expanduser())
            if hint is None:raise ValueError('No unambiguous atom tracking velocities in supplied file')
        elif atom_vx is not None and atom_vy is not None:
            hint=manual_atom_tracking_hint(atom_vx,atom_vy,unit=atom_units,
                                           convention=atom_convention)
        else:
            hint,_=find_first_atom_tracking_hint(folder)
        if hint:ctx.log(f'Atom tracking hint: {hint.source}')
    def progress(start,end):
        def tick(index,total,message):
            ctx.progress(start+(end-start)*float(index)/float(total),message)
        return tick
    # The old algorithm's discovery is replaced ONLY by the exact GUI selection.
    # The original pipeline still reads the actual source files and metadata.
    original_discover=pipeline.discover_scan_files
    pipeline.discover_scan_files=lambda *args,**kwargs: list(files)
    try:
        result=pipeline.run_analysis(
            folder,registration_channel=channel,output_dir=analysis_output,
            input_format=fmt,estimate_drift=bool(estimate_drift),
            atom_tracking_hint=hint,config=cfg,progress=progress(0,72 if stack else 100))
    finally:
        pipeline.discover_scan_files=original_discover
    # Studio creates its own vector-annotated reference PDF below.  The vendor
    # engine also emitted 07_reference_scan_lattice_overlay, causing two files
    # with the same publication name after result organization ('...2.pdf').
    # Retain every scientific table and diagnosis, suppress only this duplicate.
    for duplicate in (analysis_output/'figures'/'07_reference_scan_lattice_overlay.pdf',
                      analysis_output/'figures'/'07_reference_scan_lattice_overlay.png'):
        duplicate.unlink(missing_ok=True)
    if not bool((getattr(ctx,'parameters',None) or {}).get('diagnostic_figures',False)):
        # v0.8: only the publication overlay is saved by default; the scientific
        # tables, manifest and Markdown report are kept in the private Data folder.
        for figure in (analysis_output/'figures').glob('*'):
            if figure.is_file() and figure.suffix.lower() in ('.png','.pdf','.svg'):
                figure.unlink(missing_ok=True)
    ctx.result_file(result.manifest_path,'Original drift and primitive lattice analysis')
    ctx.result_file(result.report_path,'Drift/lattice scientific report')
    # Save output files to the Results drawer, not just an unlinked subfolder.
    for path in sorted(analysis_output.rglob('*')):
        if path.is_file() and path not in (result.manifest_path,result.report_path):
            ctx.result_file(path,'Analysis: '+path.name)
    manifest=json.loads(result.manifest_path.read_text(encoding='utf8'))
    lat=manifest['lattice']
    ctx.log(f'Primitive lattice: a={lat.get("a_nm")} nm, b={lat.get("b_nm")} nm, γ={lat.get("gamma_deg")}°')
    if not stack:return result
    target=ctx.output_dir/'multiframe_stack'
    scfg=StackConfig(method=str(method),trace_direction=str(trace))
    requested=list(dict.fromkeys([n.strip() for n in stack_channels or [channel] if n.strip()]))
    if channel not in requested:requested.insert(0,channel)
    # The original common physical-overlap algorithm is used.  The old separate
    # preview dialog is deliberately NOT launched inside a worker subprocess.
    ctx.log('Automatic largest physical overlap: inspect coverage, exclusions and '
            'registration before using results quantitatively.',level='warning')
    stacked=run_stack(folder,registration_channel=channel,stack_channels=requested,
                     manifest_path=result.manifest_path,output_dir=target,
                     config=scfg,use_gui=False,progress=progress(72,100))
    ctx.result_file(stacked.manifest_path,'Original MultiFrame stack manifest')
    ctx.result_file(stacked.report_path,'Stacking report')
    for path in sorted(target.rglob('*')):
        if path.is_file() and path not in (stacked.manifest_path,stacked.report_path):
            ctx.result_file(path,'Stack: '+path.name)
    return stacked
