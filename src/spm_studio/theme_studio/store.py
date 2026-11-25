"""Theme Studio storage (Qt-free): user profiles, portable theme packages, migration of plain theme JSON.

Everything lives in the user's customization folder (never in the installed application):
    <customization>/theme_studio/profiles/<slug>.json
    <customization>/theme_studio/skins/<slug>/...
Writes are atomic with a .bak copy. Packages are data only: JSON + SVG, nothing is executed.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from . import model, svgskin

PACKAGE_KIND = 'spm-theme-package'


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.profiles_dir = self.root / 'profiles'
        self.skins_dir = self.root / 'skins'
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.skins_dir.mkdir(parents=True, exist_ok=True)

    # -- profiles
    def path(self, slug: str) -> Path:
        return self.profiles_dir / f'{slug}.json'

    def list(self) -> dict[str, dict]:
        out = {}
        for p in sorted(self.profiles_dir.glob('*.json')):
            try:
                out[p.stem] = model.validate_profile(json.loads(p.read_text(encoding='utf8')))
            except (OSError, ValueError):
                backup = p.with_suffix('.json.bak')
                try:
                    out[p.stem] = model.validate_profile(json.loads(backup.read_text(encoding='utf8')))
                except (OSError, ValueError):
                    continue
        return out

    def load(self, slug: str) -> dict:
        return self.list()[slug]

    def save(self, profile: dict, slug: str | None = None, overwrite: bool = True) -> str:
        clean = model.validate_profile(profile)
        slug = slug or model.slug(clean['name'])
        target = self.path(slug)
        if target.exists() and not overwrite:
            raise FileExistsError(f'A profile named “{clean["name"]}” already exists')
        tmp = target.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(clean, indent=1), encoding='utf8')
        if target.exists():
            shutil.copyfile(target, target.with_suffix('.json.bak'))
        tmp.replace(target)
        return slug

    def unique_slug(self, name: str, reserved=()) -> str:
        base = model.slug(name)
        slug, n = base, 2
        while self.path(slug).exists() or slug in reserved:
            slug, n = f'{base}_{n}', n + 1
        return slug

    def delete(self, slug: str):
        for p in (self.path(slug), self.path(slug).with_suffix('.json.bak')):
            p.unlink(missing_ok=True)

    def rename(self, slug: str, new_name: str, reserved=()) -> str:
        profile = self.load(slug)
        profile['name'] = model.clean_name(new_name)
        new_slug = self.unique_slug(new_name, reserved) if model.slug(new_name) != slug else slug
        self.save(profile, new_slug)
        if new_slug != slug:
            self.delete(slug)
        return new_slug

    def duplicate(self, slug: str, new_name: str, reserved=()) -> str:
        profile = self.load(slug)
        profile['name'] = model.clean_name(new_name)
        return self.save(profile, self.unique_slug(new_name, reserved), overwrite=False)

    # -- packages
    def export_package(self, slug: str, dest: Path) -> Path:
        """ZIP: package.json + profile.json (+ theme.json in SPM Studio's own format) + the skin, if any."""
        profile = self.load(slug)
        dest = Path(dest)
        tmp = dest.with_suffix('.tmp')
        theme = {'schema_version': 1, **{k: v for k, v in profile['base'].items()
                                         if k in model.BASE_KEYS and v not in ('', None)}}
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('package.json', json.dumps({'kind': PACKAGE_KIND, 'schema': 1, 'name': profile['name'],
                                                    'contains': ['profile.json', 'theme.json'] +
                                                    (['skin/'] if profile['skin'] else [])}, indent=1))
            zf.writestr('profile.json', json.dumps(profile, indent=1))
            zf.writestr('theme.json', json.dumps(theme, indent=1))
            folder = self.skins_dir / profile['skin'] if profile['skin'] else None
            if folder and folder.is_dir():
                for p in sorted(folder.rglob('*')):
                    if p.is_file():
                        zf.write(p, 'skin/' + p.relative_to(folder).as_posix())
        tmp.replace(dest)
        return dest

    def import_package(self, source: Path, reserved=()) -> tuple[str, list[str]]:
        """Import a .zip package, a profile .json or a plain SPM Studio theme .json (migrated). → (slug, notes)."""
        source = Path(source)
        notes = []
        if source.suffix.lower() == '.json':
            data = json.loads(source.read_text(encoding='utf8'))
            profile = self._profile_from_json(data, source.stem, notes)
            return self.save(profile, self.unique_slug(profile['name'], reserved), overwrite=False), notes
        files = svgskin._read_package(source)                      # same safe unzip rules as skins
        if 'profile.json' not in files:
            raise ValueError('Not a Theme Studio package (profile.json is missing)')
        profile = model.validate_profile(json.loads(files['profile.json'].decode('utf8')))
        skin_files = {k[5:]: v for k, v in files.items() if k.startswith('skin/')}
        if skin_files:
            tmp = self.root / '.import-skin.zip'
            with zipfile.ZipFile(tmp, 'w') as zf:
                for k, v in skin_files.items():
                    zf.writestr(k, v)
            try:
                manifest, svgs = svgskin.validate_package(tmp)
            finally:
                tmp.unlink(missing_ok=True)
            folder = svgskin.install(manifest, svgs, self.skins_dir)
            profile['skin'] = folder.name
            notes.append(f'SVG skin “{manifest["name"]}” installed')
        elif profile['skin'] and not (self.skins_dir / profile['skin']).is_dir():
            notes.append('The profile refers to an SVG skin that is not in the package; it was removed from it')
            profile['skin'] = ''
        return self.save(profile, self.unique_slug(profile['name'], reserved), overwrite=False), notes

    @staticmethod
    def _profile_from_json(data, fallback_name: str, notes: list) -> dict:
        if isinstance(data, dict) and data.get('kind') == 'spm-theme-studio-profile':
            return model.validate_profile(data)
        if isinstance(data, dict) and data.get('schema_version') == 1:       # SPM Studio theme file (migration)
            base = {k: v for k, v in data.items() if k in model.BASE_KEYS}
            profile = model.validate_profile({**model.new_profile(fallback_name, {}), 'base': base})
            notes.append('Plain SPM Studio theme converted to a Theme Studio profile')
            return profile
        raise ValueError('Not a theme: expected a Theme Studio profile or an SPM Studio theme (schema_version 1)')


def theme_json(profile: dict) -> dict:
    """The profile's base tokens in SPM Studio's own theme format (shown in the normal theme menu)."""
    return {'schema_version': 1, **{k: v for k, v in profile['base'].items() if v not in ('', None)}}
