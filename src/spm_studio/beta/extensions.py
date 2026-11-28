"""Optional extensions: signed manifests, verified archives, safe install / rollback, loading.

An extension is a zip whose root holds ``extension.json`` and one Python package::

    extension.json   {"id", "name", "vendor", "version", "core_api": ">=1,<2", "entry": "pkg:activate",
                      "permissions": [...], "requires_beta": true}
    pkg/__init__.py  def activate(api): ...   (optional) def deactivate(): ...

Installed under ``<data>/extensions/<id>/<version>/``; ``<data>/extensions/state.json`` records the active and
the previous version (rollback) and whether it is enabled. Nothing is executed before the user enabled it, and
nothing from the network is extracted before its size, SHA-256 and the manifest signature are verified.
"""
from __future__ import annotations

import base64
import hashlib
import importlib
import json
import re
import shutil
import stat
import sys
import time
import zipfile
from pathlib import Path

from . import ed25519
from .client import BetaError

CORE_API = 1
ID_RE = re.compile(r'^[a-z][a-z0-9-]{2,40}$')
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+(?:[-.]?(?:a|b|rc|alpha|beta)\.?\d+)?$')
ENTRY_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$')
MAX_FILES = 2000
MAX_UNPACKED = 300 * 1024 * 1024
MAX_RATIO = 200
PERMISSIONS = {'settings_page', 'assistant_state', 'assistant_instructions', 'todo_read', 'tutorial_decorator',
               'main_window_overlay'}


def root() -> Path:
    from spm_studio.core import paths
    return paths.data_dir() / 'extensions'


def downloads_dir() -> Path:
    folder = root() / '.downloads'
    folder.mkdir(parents=True, exist_ok=True)
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    return folder


# ------------------------------------------------------------------ versions
def parse_version(text: str) -> tuple:
    m = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:[-.]?(a|b|rc|alpha|beta)\.?(\d+))?$', str(text).strip())
    if not m:
        raise ValueError(f'Bad version {text!r}')
    rank = {'a': 0, 'alpha': 0, 'b': 1, 'beta': 1, 'rc': 2, None: 3}[m.group(4)]
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), rank, int(m.group(5) or 0)


def api_compatible(spec: str, api: int = CORE_API) -> bool:
    """``'>=1,<2'`` style range on the integer core extension API."""
    for part in [p.strip() for p in str(spec).split(',') if p.strip()]:
        m = re.match(r'^(>=|<=|==|<|>)\s*(\d+)$', part)
        if not m:
            return False
        op, value = m.group(1), int(m.group(2))
        if not {'>=': api >= value, '<=': api <= value, '==': api == value, '<': api < value,
                '>': api > value}[op]:
            return False
    return True


def validate_descriptor(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError('extension.json must be an object')
    for key in ('id', 'name', 'vendor', 'version', 'core_api', 'entry'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f'extension.json: missing {key}')
    if not ID_RE.match(data['id']):
        raise ValueError('extension.json: bad id')
    if not VERSION_RE.match(data['version']):
        raise ValueError('extension.json: bad version')
    if not ENTRY_RE.match(data['entry']):
        raise ValueError('extension.json: bad entry point')
    perms = data.get('permissions', [])
    if not isinstance(perms, list) or not set(perms) <= PERMISSIONS:
        raise ValueError('extension.json: unknown permission')
    return data


# ------------------------------------------------------------------ manifest & artifact
def canonical(manifest: dict) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf8')


def verify_manifest(manifest, signature: str, keys: list[bytes]) -> dict:
    """Signature (pinned keys), schema, platform and core compatibility of a private release manifest."""
    if not isinstance(manifest, dict):
        raise BetaError('BAD_RESPONSE', 'The release manifest is missing')
    if not keys:
        raise BetaError('BAD_RESPONSE', 'No trusted extension signing key in this version of SPM Studio')
    try:
        sig = base64.b64decode(signature or '', validate=True)
    except (ValueError, TypeError):
        sig = b''
    message = canonical(manifest)
    if not any(ed25519.verify(key, message, sig) for key in keys):
        raise BetaError('BAD_SIGNATURE', 'The release manifest is not signed by a trusted key; nothing was installed.')
    try:
        validate_descriptor({k: manifest.get(k) for k in ('id', 'name', 'vendor', 'version', 'core_api', 'entry')}
                            | {'permissions': manifest.get('permissions', [])})
        art = manifest['artifact']
        if not re.fullmatch(r'[0-9a-f]{64}', str(art['sha256'])) or int(art['size']) <= 0 \
                or not str(art['download_path']).startswith('/v1/beta/releases/'):
            raise ValueError('artifact')
    except (KeyError, TypeError, ValueError) as exc:
        raise BetaError('BAD_RESPONSE', f'The release manifest is malformed ({exc})') from None
    if not api_compatible(manifest['core_api']):
        raise BetaError('INCOMPATIBLE', f'This extension needs another version of SPM Studio '
                                        f'(extension API {manifest["core_api"]}, this version has {CORE_API}).')
    platforms = manifest.get('platforms') or ['any']
    if 'any' not in platforms and sys.platform not in platforms:
        raise BetaError('INCOMPATIBLE', 'This extension release is not built for this operating system.')
    return manifest


def check_artifact(path: Path, manifest: dict):
    art = manifest['artifact']
    if path.stat().st_size != int(art['size']):
        raise BetaError('BAD_ARTIFACT', 'The download is incomplete (size mismatch); nothing was installed.')
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    if h.hexdigest() != art['sha256']:
        raise BetaError('BAD_ARTIFACT', 'The download does not match its signed checksum; nothing was installed.')


def _safe_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_FILES:
        raise BetaError('BAD_ARTIFACT', 'The extension archive has too many files')
    total = 0
    for info in infos:
        name = info.filename
        parts = [part for part in name.split('/') if part]
        if name.startswith(('/', '\\')) or '\\' in name or ':' in name or not parts or '..' in parts:
            raise BetaError('BAD_ARTIFACT', f'Unsafe path in the extension archive: {name[:80]}')
        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise BetaError('BAD_ARTIFACT', 'Links are not allowed in an extension archive')
        total += info.file_size
        if total > MAX_UNPACKED or (info.compress_size and info.file_size / max(1, info.compress_size) > MAX_RATIO):
            raise BetaError('BAD_ARTIFACT', 'The extension archive is too large once unpacked')
    return infos


def install_archive(archive: Path, manifest: dict | None = None) -> dict:
    """Unpack a verified archive next to the installed versions and make it the active one (atomic)."""
    with zipfile.ZipFile(archive) as zf:
        infos = _safe_members(zf)
        try:
            descriptor = validate_descriptor(json.loads(zf.read('extension.json').decode('utf8')))
        except KeyError:
            raise BetaError('BAD_ARTIFACT', 'extension.json is missing from the archive') from None
        except ValueError as exc:
            raise BetaError('BAD_ARTIFACT', str(exc)) from None
        if manifest is not None and (descriptor['id'], descriptor['version']) != (manifest['id'], manifest['version']):
            raise BetaError('BAD_ARTIFACT', 'The archive does not contain the announced extension version')
        if not api_compatible(descriptor['core_api']):
            raise BetaError('INCOMPATIBLE', 'This extension needs another version of SPM Studio')
        base = root() / descriptor['id']
        base.mkdir(parents=True, exist_ok=True)
        staging = base / f'.staging-{int(time.time() * 1000)}'
        staging.mkdir()
        try:
            for info in infos:
                target = (staging / info.filename).resolve()
                if staging.resolve() not in target.parents and target != staging.resolve():
                    raise BetaError('BAD_ARTIFACT', 'Unsafe path in the extension archive')
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            final = base / descriptor['version']
            if final.exists():
                shutil.rmtree(final)
            staging.rename(final)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    states = load_states()
    entry = states.get(descriptor['id'], {})
    if entry.get('active') and entry['active'] != descriptor['version']:
        entry['previous'] = entry['active']
    entry.update(active=descriptor['version'], enabled=True, installed=time.time(), error='')
    states[descriptor['id']] = entry
    save_states(states)
    _prune(descriptor['id'], keep={entry.get('active'), entry.get('previous')})
    return descriptor


def _prune(ext_id: str, keep: set):
    for folder in (root() / ext_id).iterdir():
        if folder.is_dir() and not folder.name.startswith('.') and folder.name not in keep:
            shutil.rmtree(folder, ignore_errors=True)


# ------------------------------------------------------------------ state
def _states_file() -> Path:
    return root() / 'state.json'


def load_states() -> dict:
    try:
        data = json.loads(_states_file().read_text(encoding='utf8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_states(data: dict):
    path = _states_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=1), encoding='utf8')
    tmp.replace(path)


def installed() -> dict:
    """``{id: {'descriptor', 'path', 'enabled', 'previous', 'error'}}`` of installed, readable extensions."""
    result = {}
    for ext_id, entry in load_states().items():
        folder = root() / ext_id / str(entry.get('active', ''))
        try:
            descriptor = validate_descriptor(json.loads((folder / 'extension.json').read_text(encoding='utf8')))
        except (OSError, ValueError):
            continue
        result[ext_id] = {'descriptor': descriptor, 'path': folder, 'enabled': bool(entry.get('enabled')),
                          'previous': entry.get('previous', ''), 'error': entry.get('error', '')}
    return result


def set_enabled(ext_id: str, enabled: bool):
    states = load_states()
    if ext_id in states:
        states[ext_id]['enabled'] = bool(enabled)
        if enabled:
            states[ext_id]['error'] = ''
        save_states(states)


def rollback(ext_id: str) -> str:
    states = load_states()
    entry = states.get(ext_id, {})
    previous = entry.get('previous')
    if not previous or not (root() / ext_id / previous).is_dir():
        raise RuntimeError('No previous version to go back to')
    entry['previous'], entry['active'] = entry['active'], previous
    save_states(states)
    return previous


def uninstall(ext_id: str):
    states = load_states()
    states.pop(ext_id, None)
    save_states(states)
    shutil.rmtree(root() / ext_id, ignore_errors=True)


def record_error(ext_id: str, message: str):
    states = load_states()
    if ext_id in states:
        states[ext_id]['error'] = message[:500]
        states[ext_id]['enabled'] = False
        save_states(states)


# ------------------------------------------------------------------ loading
_loaded: dict[str, object] = {}


def load_enabled(api, beta_ok: bool) -> dict[str, str]:
    """Activate every enabled extension; ``{id: 'ok' | reason}``. Never raises."""
    report = {}
    try:
        # v0.1.0: the assistant engine is part of SPM Studio. Import it before any extension folder is put on
        # sys.path, so an extension that still ships its own copy can never replace the built-in one.
        import agent_hub  # noqa: F401
    except Exception:
        pass
    for ext_id, info in installed().items():
        d = info['descriptor']
        if not info['enabled']:
            report[ext_id] = 'disabled'
            continue
        if d.get('requires_beta', True) and not beta_ok:
            report[ext_id] = 'beta access not verified'
            continue
        if not api_compatible(d['core_api']):
            report[ext_id] = 'incompatible'
            continue
        module_name, func_name = d['entry'].split(':')
        path = str(info['path'])
        try:
            if path not in sys.path:
                sys.path.insert(0, path)
            module = importlib.import_module(module_name)
            getattr(module, func_name)(api.for_extension(d))
            _loaded[ext_id] = module
            report[ext_id] = 'ok'
        except Exception as exc:                      # a broken extension is disabled, the app keeps going
            record_error(ext_id, f'{type(exc).__name__}: {exc}')
            report[ext_id] = f'failed: {exc}'
            try:
                api.cleanup(ext_id)
            except Exception:
                pass
    return report


def unload(ext_id: str, api=None):
    module = _loaded.pop(ext_id, None)
    if module is not None and hasattr(module, 'deactivate'):
        try:
            module.deactivate()
        except Exception:
            pass
    if api is not None:
        api.cleanup(ext_id)
