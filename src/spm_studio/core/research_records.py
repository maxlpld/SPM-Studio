"""Scientific run records from SPM module snapshots and emitted result tables."""
from pathlib import Path
from datetime import datetime, timezone
import json, math, platform, sys, uuid
from spm_studio.shared import ResearchStore, fingerprint, utcnow
from spm_studio.shared.store import input_fingerprint
from spm_studio.shared.ui_strings import ui_label


def module_code_hash(mod):
    """Hash algorithm source/config rather than trusting semantic version alone."""
    import hashlib
    h=hashlib.sha256()
    root=Path(mod.path)
    files=[root] if root.is_file() else sorted(
        p for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.json')
        and '__pycache__' not in p.parts)
    for file in files:
        h.update(str(file.relative_to(root) if root.is_dir() else file.name).encode())
        h.update(file.read_bytes())
    return h.hexdigest()


def execution_key(source_sha, context, module):
    rois={'main':context.get('roi'),'additional':context.get('rois')}
    return input_fingerprint(source_sha,context['channel'],context['direction'],
        context['parameters'],rois,context.get('processing'),
        context.get('geometry'),f'{module.id}:{module.version}:{module_code_hash(module)}')


def measurements_from_tables(run_dir):
    """Retain native column/row context; no unit or uncertainty guessed.

    Numeric values become structured observations only if the scientific module
    emitted a table.  NaN/Inf are *not* silently converted to zero.
    """
    data=[]
    for path in sorted(Path(run_dir).glob('*.table.json')):
        try:
            obj=json.loads(path.read_text(encoding='utf8'))
            columns=list(map(str,obj.get('columns',[])))
            for i,row in enumerate(obj.get('rows',[])):
                if not isinstance(row,list):continue
                for col,val in zip(columns,row):
                    if isinstance(val,(float,int)) and not isinstance(val,bool) and math.isfinite(val):
                        data.append({'key':col,'table':obj.get('title',''),
                            'row_index':i,'row':dict(zip(columns,row)),
                            'value':val,'unit':row[columns.index('unit')] if 'unit' in columns and isinstance(row[columns.index('unit')],str) else None,'uncertainty':None,
                            'quality':'unreviewed','source_file':str(path)})
        except (OSError,ValueError,TypeError):
            continue
    return data


def make_record(context_path,mod,ok,run_files,source_sha=None):
    ctx=json.loads(Path(context_path).read_text(encoding='utf8'))
    source=Path(ctx['scan_path'])
    store=ResearchStore()
    scan_id,sha=store.scan_id(source, full_hash=source_sha or ctx.get('source_sha256'))
    fp=execution_key(sha,ctx,mod)
    st=source.stat()
    changed=bool(ctx.get('source_changed_during_snapshot') or
        st.st_size!=ctx.get('source_size',st.st_size) or
        st.st_mtime_ns!=ctx.get('source_mtime_ns',st.st_mtime_ns))
    data_folder=Path(context_path).parent
    run_dir=data_folder.parent if data_folder.name=='Data' else data_folder
    arts=[str(f) for f in run_files if Path(f).is_file()]
    arts.extend(str(p) for p in sorted(data_folder.glob('*.table.json')) if str(p) not in arts)
    measurements=measurements_from_tables(data_folder)
    record={'schema_version':1,'result_id':str(uuid.uuid4()),'scan_id':scan_id,
        'source_path':str(source.resolve()),'source_sha256':sha,'source_bytes':st.st_size,
        'source_mtime_ns':st.st_mtime_ns,'module_id':mod.id,'module_version':mod.version,
        'algorithm_sha256':module_code_hash(mod),
        'channel':ctx['channel'],'direction':ctx['direction'],'unit':ctx.get('unit'),
        'scan_geometry':ctx.get('geometry'),'metadata':ctx.get('metadata'),
        'parameters':ctx.get('parameters'), 'preprocessing':ctx.get('processing'),
        'roi':ctx.get('roi'),'rois':ctx.get('rois'),
        'input_fingerprint':fp,'measurements':measurements,'artifacts':arts,
        'run_folder':str(run_dir),'status':'stale' if changed else ('completed' if ok else 'failed'),
        'created_at':utcnow(),'provenance':{'context_json':str(context_path),
        'run_log':str(data_folder/'run.log'),'python':sys.version.split()[0],
        'platform':platform.platform()},
        'warnings':['The source changed during or after the analysis snapshot; do not reuse this result.'] if changed else []}
    # Write a portable, non-destructive manifest beside original module outputs.
    # Never overwrite an analysis engine's own manifest.json / record.json.
    # The provenance index is a separate, clearly labeled internal file.
    manifest=data_folder/'research_record.json'
    manifest.write_text(json.dumps(record,indent=2,ensure_ascii=False,default=str),encoding='utf8')
    store.save_run(record)
    return record


def format_record(record):
    if not record:return 'No saved analysis run for this scan and tool.'
    lines=[f"{ui_label(record['status'])}  ·  {record['source_path'].split('/')[-1]}",
           f"{ui_label(record['module_id'])} v{record['module_version']}  ·  {record['created_at']}",
           f"Channel: {record['channel']} / {record['direction']}",
           f"Run ID: {record['result_id']}"]
    if not record.get('measurements'):
        lines.append('No numeric result tables. Open the run outputs to see figures and data.')
    else:
        for m in record['measurements'][:30]:
            value=m['value'];precision=f'{value:.6g}' if isinstance(value,(float,int)) else str(value)
            context=ui_label(m.get('table',''))
            row=m.get('row',{})
            label=str(row.get('type',row.get('polarity',row.get('line',''))))
            lines.append(f"{context} / {label}: {ui_label(m['key'])} = {precision}"
                +(f" {m['unit']}" if m.get('unit') else ' [unit not declared]'))
        if len(record['measurements'])>30:lines.append(f"… {len(record['measurements'])-30} more measurements in manifest")
    lines.append(f"Outputs: {len(record.get('artifacts',[]))} · {record.get('run_folder','')}")
    return '\n'.join(lines)
