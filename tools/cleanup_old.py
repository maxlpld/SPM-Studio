#!/usr/bin/env python3
"""Source-derived, strictly targeted Research Studio/SPM Studio old-app removal.

Dry-run by default. Intentionally cannot delete scientific data or Pi credentials.
"""
from __future__ import annotations
import argparse,os,json,shutil,sys,time
from pathlib import Path

HOME=Path.home().resolve()
DATA=Path(os.environ.get('XDG_DATA_HOME', HOME/'.local/share')).expanduser().resolve()
BIN=HOME/'.local/bin'
APPS=DATA/'applications'
ICONS=DATA/'icons/hicolor/512x512/apps'


def owned(path,kind):
    if path.is_symlink():return False
    if kind=='research_app':return (path/'apps/spm-studio/pyproject.toml').is_file() and (path/'apps/research-workbench').is_dir()
    if kind=='research_venv':return (path/'pyvenv.cfg').is_file() and (path/'bin/python').exists()
    if kind=='spm_app':return (path/'installed.json').is_file() and (path/'app/src/spm_studio/app.py').is_file()
    if kind=='legacy_bin':
        try:
            if not path.is_file() or path.stat().st_size>50000:return False
            s=path.read_text(encoding='utf8',errors='replace')
            # Never remove the fresh AI-integrated launcher.
            return ('spm-studio-ai-app' not in s and
                ('research-studio' in s.lower() or 'spm-studio-app' in s or 'spm_studio' in s))
        except OSError:return False
    if kind=='desktop':
        try:
            if not path.is_file() or path.stat().st_size>25000:return False
            s=path.read_text(encoding='utf8',errors='replace')
            return ('[Desktop Entry]' in s and 'spm-studio-ai-app' not in s and
                    ('research-studio' in s.lower() or 'spm-studio-app' in s or 'spm_studio' in s))
        except OSError:return False
    return False


def candidates():
    roots=[(DATA/'research-studio-app','research_app','The old multi-application Research Studio source install'),
           (DATA/'research-studio-venv','research_venv','Dedicated old Research Studio Python environment'),
           (DATA/'spm-studio-app','spm_app','Dedicated older SPM Studio managed package')]
    scripts=[BIN/f for f in ('research-studio','research-studio-stop','spm-studio','spm-studio-update')]
    desktops=[APPS/f for f in ('research-studio.desktop','spm-studio.desktop','research-spm-studio.desktop',
             'org.spmstudio.SPMStudio.desktop')]
    for p in scripts:roots.append((p,'legacy_bin','Old application-specific launcher'))
    for p in desktops:roots.append((p,'desktop','Old application desktop entry'))
    result=[]
    for path,kind,why in roots:
        if not (path.exists() or path.is_symlink()):continue
        if not owned(path,kind):
            print('[PRESERVED/UNRECOGNIZED]',path, file=sys.stderr)
            continue
        if path.resolve()!=path or path==HOME or HOME not in path.parents:
            print('[PRESERVED/UNSAFE PATH]',path,file=sys.stderr);continue
        size=(sum(f.stat().st_size for f in path.rglob('*') if f.is_file() and not f.is_symlink())
              if path.is_dir() else path.stat().st_size)
        result.append({'path':str(path),'kind':kind,'reason':why,'size_bytes':size})
    return result


def main():
    parser=argparse.ArgumentParser()
    action=parser.add_mutually_exclusive_group()
    action.add_argument('--dry-run',action='store_true',help='List without deleting (default)')
    action.add_argument('--apply',action='store_true',help='Requires an additional typed confirmation')
    args=parser.parse_args()
    if os.geteuid()==0:parser.error('Run as your normal user, never sudo/root')
    found=candidates()
    print('\nOLD RESEARCH STUDIO / SPM STUDIO application removal inventory')
    print('Scope: old Research Studio AND old standalone SPM Studio managed installations.\n')
    for rec in found:print(f"  {rec['path']}\n    {rec['reason']} ({rec['size_bytes']/1024/1024:.1f} MiB)")
    print('\nPRESERVED: all research scans/projects, ~/.local/share/spm-studio/scripts, runs, '
          '~/.config/spm-studio, ~/.local/share/research-studio (legacy personal data), backups, '
          '~/.pi, Ollama models, provider credentials, and unrelated venvs.')
    print('NOT SCANNED: old checkout folders in Downloads/other paths, pip editable installs in other environments, system packages.')
    if not found:
        print('No verified old app components identified.');return 0
    if not args.apply:
        print('\nDRY RUN: no changes made. To remove verified components, rerun with --apply.');return 0
    print('\nThis removes the old Research Studio application, including its OTHER apps, not just SPM Studio.')
    if input('Type exactly REMOVE OLD APPS to proceed: ').strip()!='REMOVE OLD APPS':
        print('Cancelled. No files deleted.');return 2
    log=[]
    for rec in found:
        path=Path(rec['path'])
        # Reverify identity immediately before deletion, prevent swapped paths.
        if not owned(path,rec['kind']) or path.resolve()!=path:
            log.append({'path':str(path),'status':'SKIPPED identity changed'});continue
        try:
            if path.is_dir():shutil.rmtree(path)
            else:path.unlink()
            log.append({'path':str(path),'status':'removed'})
        except OSError as exc:log.append({'path':str(path),'status':'ERROR '+str(exc)})
    report=Path(os.environ.get('XDG_STATE_HOME',HOME/'.local/state'))/'spm-studio-cleanup'/('removed-'+time.strftime('%Y%m%d-%H%M%S')+'.json')
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(log,indent=2)+'\n',encoding='utf8')
    print('\nRemoval report:',report)
    for r in log:print(r['status'],r['path'])
    print('Remaining matching old components:',len(candidates()))
    return 1 if any(r['status'].startswith('ERROR') for r in log) else 0

if __name__=='__main__':raise SystemExit(main())
