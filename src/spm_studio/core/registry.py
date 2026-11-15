"""Manifest-only discovery: never import or execute third-party scripts at scan time."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import importlib.util
import re

API_VERSION = '1.0'
VALID_PARAM_TYPES = {'integer','float','bool','string','choice','file','folder','channel','direction','color','region','text'}

@dataclass(frozen=True)
class ModuleInfo:
    id: str
    name: str
    description: str
    path: Path
    mode: str
    entrypoint: str
    version: str
    category: str
    parameters: dict[str,dict[str,Any]]
    requires: tuple[str,...]
    status: str = 'operational'
    builtin: bool = False
    interaction: str = 'none'
    snapshot_channels: str = 'selected'
    selection: dict[str,Any] | None = None
    snapshot_parameter_channels: tuple[str, ...] = ()

    def missing_dependencies(self):
        return [name for name in self.requires if importlib.util.find_spec(name.replace('-', '_')) is None]


def load_manifest(path: Path, *, builtin=False) -> ModuleInfo:
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('api_version') != API_VERSION:
        raise ValueError('Unsupported module API version; expected 1.0')
    id_ = data.get('id','')
    if re.fullmatch(r'[a-z][a-z0-9_]{1,80}',id_) is None:
        raise ValueError('Module id must be a safe lowercase identifier')
    if data.get('mode','analysis') == 'instrument':
        raise ValueError('Instrument module is disabled in the offline application')
    ep = data.get('entrypoint','module:run')
    if not re.fullmatch(r'[a-zA-Z_]\w*:[a-zA-Z_]\w*', ep):
        raise ValueError('Entry point must be module:run (safe Python identifier)')
    interaction = data.get('interaction','none')
    if interaction not in ('none','line_profiles','histogram_masks'):
        raise ValueError('Unsupported module interaction (none/line_profiles/histogram_masks)')
    selection = data.get('selection')
    if selection is None:
        defaults = {'line_profiles': {'tools':['line'], 'multiple':True, 'preview':'profiles'},
                    'histogram_masks': {'tools':['rectangle'], 'multiple':False, 'preview':'histogram'}}
        selection = defaults.get(interaction, {'tools': [], 'multiple':False, 'preview':'none'})
    if not isinstance(selection,dict) or set(selection)-{'tools','multiple','preview'}:
        raise ValueError('selection must declare tools, multiple and preview only')
    if (not isinstance(selection.get('tools'),list) or
        len(set(map(str,selection['tools'])))!=len(selection['tools']) or
        any(v not in ('line','rectangle','point') for v in selection['tools']) or
        type(selection.get('multiple',False)) is not bool or
        selection.get('preview','none') not in ('none','profiles','histogram','molecule_placement')):
        raise ValueError('Invalid selection declaration: tools=line/rectangle/point, multiple=bool, preview=none/profiles/histogram/molecule_placement')
    if selection.get('preview')=='profiles' and 'line' not in selection['tools']:
        raise ValueError('profiles preview requires line tool')
    snapshot_channels = data.get('snapshot_channels','selected')
    if snapshot_channels not in ('selected','all'):
        raise ValueError('snapshot_channels must be selected or all')
    params = data.get('parameters',{})
    extras = data.get('snapshot_parameter_channels', [])
    if not isinstance(extras,list) or any(not isinstance(n,str) for n in extras) or len(extras)>12:
        raise ValueError('snapshot_parameter_channels must be a list of parameter names')
    if not isinstance(params, dict) or len(params) > 60:
        raise ValueError('Module parameters must be an object of at most 60 entries')
    for name, descriptor in params.items():
        if not isinstance(descriptor, dict) or descriptor.get('type') not in VALID_PARAM_TYPES:
            raise ValueError(f'Invalid parameter {name}')
        if descriptor['type'] == 'choice' and not isinstance(descriptor.get('choices'),list):
            raise ValueError(f'Choice parameter {name} requires choices')
    if any(n not in params or params[n].get('type') != 'channel' for n in extras):
        raise ValueError('snapshot_parameter_channels must reference channel parameters')
    module_py = path.parent / (ep.split(':')[0] + '.py')
    if not module_py.is_file():
        raise ValueError(f'Module entrypoint file missing: {module_py}')
    return ModuleInfo(id_, str(data.get('name',id_)), str(data.get('description','')),
                      path.parent, data.get('mode','analysis'), ep,
                      str(data.get('version','0.0.0')), str(data.get('category','Analysis')),
                      params, tuple(data.get('requires', [])),
                      str(data.get('status','operational')), builtin, interaction, snapshot_channels, selection, tuple(extras))


def discover_modules(directories: list[Path]):
    """Returns modules and human-readable discovery warnings. Earlier roots win."""
    modules, problems = {}, []
    for i, directory in enumerate(directories):
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if entry.is_dir() and (entry/'module.json').is_file():
                try:
                    mod = load_manifest(entry/'module.json', builtin=(i==len(directories)-1))
                    if mod.id in modules:
                        problems.append(f'Duplicate module {mod.id}: {entry} ignored')
                    else:
                        modules[mod.id] = mod
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    problems.append(f'{entry.name}: {exc}')
            elif entry.is_file() and entry.suffix.lower() == '.py' and not entry.name.startswith('_'):
                stem = re.sub(r'\W', '_', entry.stem.lower())
                key = f'legacy_{stem}'
                if key not in modules:
                    modules[key] = ModuleInfo(key, entry.stem, 'Standalone script (subprocess; uses SPM_CONTEXT_JSON environment variable)',
                                             entry, 'legacy', '', 'legacy', 'Compatibility', {}, (), 'experimental', i==len(directories)-1)
    return modules, problems


def validate_params(mod: ModuleInfo, values: dict):
    out = {}
    for name, d in mod.parameters.items():
        v = values.get(name, d.get('default'))
        t = d['type']
        if t == 'integer':
            v = int(v)
        elif t == 'float':
            v = float(v)
        elif t == 'bool':
            v = bool(v)
        else:
            v = '' if v is None else str(v)
        if t in ('float','integer') and (('min' in d and v < d['min']) or ('max' in d and v > d['max'])):
            raise ValueError(f'{name}: outside allowed range')
        if t == 'choice' and v not in d['choices']:
            from .plot_settings import is_colormap_parameter
            # v34: colormap parameters accept every colormap of the viewer.
            if not (is_colormap_parameter(name) and v and len(v)<200 and '/' not in v and '\\' not in v):
                raise ValueError(f'{name}: not among allowed choices')
        out[name] = v
    return out
