"""Validated, portable keyboard shortcut profiles for the Studio GUI.

Profiles describe action IDs, not callbacks or executable code. GUI binding is
handled centrally by MainWindow; importing a JSON profile never executes it.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import re

SCHEMA_VERSION = 1

@dataclass(frozen=True)
class ShortcutAction:
    id: str
    category: str
    label: str
    default: str
    help: str = ''

# Keys use Qt's portable QKeySequence strings (same across Linux/Windows/macOS).
ACTIONS = (
    ShortcutAction('nav.scan_previous','Navigation','Previous scan','Up','Select the previous visible scan'),
    ShortcutAction('nav.scan_next','Navigation','Next scan','Down','Select the next visible scan'),
    ShortcutAction('nav.channel_left','Navigation','Channels left','Left','Move left in the channel preview strip'),
    ShortcutAction('nav.channel_right','Navigation','Channels right','Right','Move right in the channel preview strip'),
    ShortcutAction('file.open','Files','Add scans to the project','Ctrl+O'),
    ShortcutAction('file.dataset','Files','Open project (folder)','Ctrl+Shift+O'),
    ShortcutAction('file.remove','Files','Remove selected scans from the list','Ctrl+Delete','Never deletes the original scan files'),
    ShortcutAction('file.export','Files','Export current view','Ctrl+E'),
    ShortcutAction('file.save_profile','Files','Save scan/channel profile','Ctrl+Shift+S'),
    ShortcutAction('file.import_profile','Files','Import scan/channel profile','Ctrl+Shift+P'),
    ShortcutAction('file.import_export','Files','Import figure export preset','Ctrl+Alt+E'),
    ShortcutAction('file.import_theme','Files','Import appearance theme','Ctrl+Alt+T'),
    ShortcutAction('file.import_colormap','Files','Import colormap','Ctrl+Alt+C'),
    ShortcutAction('view.fit','View','Fit image','Ctrl+0'),
    ShortcutAction('view.results','View','Show or hide results','Ctrl+L'),
    ShortcutAction('view.clear_roi','View','Clear active selections','Esc'),
    ShortcutAction('view.back_to_scan','View','Back to scan','Ctrl+B'),
    ShortcutAction('view.line','Selections','Draw line','L'),
    ShortcutAction('view.rectangle','Selections','Draw region','R'),
    ShortcutAction('view.point','Selections','Mark point','M'),
    ShortcutAction('view.undo_selection','Selections','Undo last selection','Ctrl+Z'),
    ShortcutAction('view.delete_selection','Selections','Delete selected region / line','Ctrl+Backspace'),
    ShortcutAction('view.clear_selections','Selections','Clear all selections','Ctrl+Shift+Backspace'),
    ShortcutAction('view.active_channel_next','View','Next active channel','Alt+Right'),
    ShortcutAction('view.active_channel_previous','View','Previous active channel','Alt+Left'),
    ShortcutAction('view.trace_toggle','View','Toggle forward/backward trace','Alt+T'),
    ShortcutAction('view.profile_apply','Profiles','Apply selected profile','Ctrl+Shift+A'),
    ShortcutAction('view.profile_next','Profiles','Next profile','Alt+P'),
    ShortcutAction('view.export_preset_next','Profiles','Next figure preset','Alt+E'),
    ShortcutAction('panel.files','Panels','Show Files sidebar','F6'),
    ShortcutAction('panel.tools','Panels','Show Tools sidebar','F7'),
    ShortcutAction('panel.inspector','Panels','Show Inspector','F8'),
    ShortcutAction('panel.tool_settings','Panels','Show Tool settings','F9'),
    ShortcutAction('panel.logs','Panels','Show Logs','F10'),
    ShortcutAction('tool.run','Tools','Run selected analysis','Ctrl+R'),
    ShortcutAction('tool.cancel','Tools','Cancel running analysis','Ctrl+Shift+R'),
    ShortcutAction('tool.next','Tools','Next tool in list','Alt+J'),
    ShortcutAction('tool.previous','Tools','Previous tool in list','Alt+K'),
    ShortcutAction('tool.import','Tools','Import module','Ctrl+I'),
    ShortcutAction('tool.refresh','Tools','Refresh modules','Ctrl+Shift+I'),
    ShortcutAction('tool.scripts_folder','Tools','Open Scripts folder','Ctrl+Alt+S'),
    ShortcutAction('tool.customization_folder','Tools','Open Customization folder','Ctrl+Alt+U'),
    ShortcutAction('tool.clear_cache','Tools','Clear preview cache','Ctrl+Alt+M'),
    ShortcutAction('options.plot','Options','Scientific plots and results','Ctrl+Alt+P'),
    ShortcutAction('options.shortcuts','Options','Keyboard shortcuts reference/editor','Ctrl+Alt+K'),
    ShortcutAction('options.import_shortcuts','Options','Import keyboard shortcut file','Ctrl+Alt+I'),
    ShortcutAction('options.export_shortcuts','Options','Export keyboard shortcut file','Ctrl+Alt+X'),
) + tuple(ShortcutAction(f'tool.slot{i}','Tools',f'Select tool {i}',f'Ctrl+{i}',
                          'Select tool by its current position in the Tools list') for i in range(1,9))

ACTION_BY_ID = {a.id:a for a in ACTIONS}
DEFAULT_BINDINGS = {a.id:a.default for a in ACTIONS}
_SAFE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')

class ShortcutConfigError(ValueError):
    """Malformed or conflicting shortcut configuration."""


def validate_profile(data:dict, *,canonicalize=None)->dict:
    """Validate a profile without Qt; Qt caller can supply a key normalizer.

    Empty strings unbind actions. Unknown action IDs fail closed so typos in an
    imported profile are visible instead of silently creating dead shortcuts.
    """
    if not isinstance(data,dict) or data.get('schema_version')!=SCHEMA_VERSION:
        raise ShortcutConfigError('Shortcuts JSON requires schema_version: 1')
    name=data.get('name')
    if not isinstance(name,str) or not _SAFE_NAME.fullmatch(name):
        raise ShortcutConfigError('Shortcut profile name: use 1–64 letters, digits, dots, underscores or dashes')
    mapping=data.get('bindings')
    if not isinstance(mapping,dict):
        raise ShortcutConfigError('Shortcuts JSON must contain a bindings object')
    # The Pan action was removed from the UI. Ignore this one legacy binding
    # when reading saved user profiles, without changing their files or any
    # other shortcuts. Newly saved profiles no longer contain the old action.
    mapping={id_:key for id_,key in mapping.items() if id_!='view.pan'}
    unknown=set(mapping)-ACTION_BY_ID.keys()
    if unknown:raise ShortcutConfigError('Unknown shortcut action IDs: '+', '.join(sorted(unknown)))
    merged=DEFAULT_BINDINGS.copy()
    for id_,value in mapping.items():
        if not isinstance(value,str):raise ShortcutConfigError(f'Shortcut for {id_} must be a string')
        if len(value)>80:raise ShortcutConfigError(f'Shortcut too long: {id_}')
        merged[id_]=canonicalize(value) if canonicalize is not None else value.strip()
    taken={}
    for id_,sequence in merged.items():
        if not sequence:continue
        normalized=sequence.casefold()
        if normalized in taken:
            raise ShortcutConfigError(f'"{sequence}" conflicts: {taken[normalized]} and {id_}')
        taken[normalized]=id_
    return {'schema_version':1,'name':name,'bindings':merged}


def load_profile(path:Path,*,canonicalize=None)->dict:
    path=Path(path)
    if path.stat().st_size>256*1024:
        raise ShortcutConfigError('Shortcut file exceeds 256 KiB')
    try:
        raw=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,UnicodeError,json.JSONDecodeError) as e:
        raise ShortcutConfigError(f'Cannot read shortcut profile: {e}') from e
    return validate_profile(raw,canonicalize=canonicalize)


def write_profile(path:Path,profile:dict,*,canonicalize=None)->dict:
    valid=validate_profile(profile,canonicalize=canonicalize)
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(valid,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    temporary.replace(path)
    return valid


def default_profile(name='default')->dict:
    return {'schema_version':1,'name':name,'bindings':DEFAULT_BINDINGS.copy()}


def read_profiles(directory:Path,*,canonicalize=None)->dict[str,dict]:
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    if not (directory/'default.json').exists():
        write_profile(directory/'default.json',default_profile())
    valid={}
    for path in sorted(directory.glob('*.json')):
        try:
            profile=load_profile(path,canonicalize=canonicalize)
            if path.stem!=profile['name']:
                continue
            valid[path.stem]=profile
        except (ShortcutConfigError,OSError,ValueError):
            continue
    if 'default' not in valid:
        valid['default']=default_profile()
    return valid
