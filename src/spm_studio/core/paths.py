"""User-owned application directories; no current-working-directory assumptions."""
from pathlib import Path
import os


def bundled_studio_root() -> Path:
    """Find the installed application's *actual* bundled script sources.

    Wheel installations put ``spm_studio`` under site-packages, so deriving a
    bundled scripts directory by walking three package parents is incorrect.
    The isolated installed application includes its own source script folder.
    """
    # All bundled scripts are physically in this standalone application tree.
    return Path(__file__).resolve().parents[3]


def config_dir() -> Path:
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'spm-studio-ai'


def data_dir() -> Path:
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'spm-studio-ai'


def cache_dir() -> Path:
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'spm-studio-ai'


def scripts_dir() -> Path:
    d = data_dir() / 'scripts'
    d.mkdir(parents=True, exist_ok=True)
    return d


def customization_dir() -> Path:
    d = config_dir() / 'customization'
    d.mkdir(parents=True, exist_ok=True)
    return d


def runs_dir() -> Path:
    d = data_dir() / 'runs'
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    """Local, offline model assets (e.g. the push-to-talk speech model). Never
    uploaded; nothing under this directory is sent to any network service."""
    d = data_dir() / 'models'
    d.mkdir(parents=True, exist_ok=True)
    return d


def install_factory_modules(source=None):
    """Populate the folder opened by the GUI, without overwriting local edits.

    Module folders themselves are the executable extensions; startup only reads
    their manifests. Removing a folder removes that tool on Refresh.
    """
    import shutil
    destination = scripts_dir()
    sources = ([Path(source)] if source else [])
    sources += [bundled_studio_root() / 'scripts',
                Path(__file__).resolve().parents[1] / 'builtin_modules']
    marker=destination/'.factory_modules_installed_v041'
    if marker.exists():return destination
    had_existing_modules=any(p.is_dir() and (p/'module.json').is_file()
                             for p in destination.iterdir())
    for src in sources:
        if not src.is_dir():
            continue
        for module in sorted(src.iterdir()):
            if module.is_dir() and (module / 'module.json').is_file():
                target = destination / module.name
                if not target.exists():
                    shutil.copytree(module,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    # The editable prompt is always available in the very same folder.
    docs = bundled_studio_root() / 'scripts' / 'README_SCRIPT.md'
    if not docs.is_file():
        docs = Path(__file__).resolve().parents[1] / 'builtin_modules' / 'README_SCRIPT.md'
    if docs.is_file() and not (destination / 'README_SCRIPT.md').exists():
        shutil.copy2(docs,destination / 'README_SCRIPT.md')
    marker.write_text('Bundled examples copied once. Remove/edit modules freely.\n',encoding='utf8')
    if not had_existing_modules:
        (destination/'.factory_modules_checked_v042').write_text('Fresh factory v0.4.2 installation\n',encoding='utf8')
    return destination


def install_factory_customization():
    """Add editable examples to the GUI-linked folder once, preserving user files."""
    import shutil
    source = bundled_studio_root() / 'customization'
    destination = customization_dir()
    if not source.is_dir():return destination
    # v0.0.5: a factory file the user removed in Settings › Library stays removed.
    removed=removed_factory_items()
    for item in source.iterdir():
        if item.is_file() and not (destination/item.name).exists():
            shutil.copy2(item,destination/item.name)
        elif item.is_dir():
            folder=destination/item.name;folder.mkdir(parents=True,exist_ok=True)
            for entry in item.iterdir():
                if f'{item.name}/{entry.name}' in removed:continue
                if entry.is_file() and not (folder/entry.name).exists():
                    shutil.copy2(entry,folder/entry.name)
    return destination


def upgrade_factory_modules():
    """Update unchanged v0.4.1 factory scripts once; never replace user edits.

    Removed modules stay removed. A user's edited file is skipped, not overwritten.
    A copy of each upgraded original is placed in .factory_backups_v042.
    """
    import hashlib, json, shutil
    dest = scripts_dir()
    checked = dest / '.factory_modules_checked_v042'
    if checked.exists() or not (dest/'.factory_modules_installed_v041').exists():
        return []
    bundled = bundled_studio_root() / 'scripts'
    legacy = json.loads((bundled/'factory_v041_hashes.json').read_text(encoding='utf8')) if (bundled/'factory_v041_hashes.json').is_file() else {}
    events=[]
    for name, files in legacy.items():
        if not (dest/name/'module.json').is_file():
            continue
        for fn, digest in files.items():
            old,new=dest/name/fn,bundled/name/fn
            if not old.is_file() or not new.is_file():continue
            if hashlib.sha256(old.read_bytes()).hexdigest()!=digest:
                events.append(f'{name}/{fn}: locally modified; preserved')
                continue
            if old.read_bytes()==new.read_bytes():continue
            backup=dest/'.factory_backups_v042'/name/fn
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(old,backup)
            shutil.copy2(new,old)
            events.append(f'{name}/{fn}: upgraded (backup saved)')
    # The editable prompt is updated only if it matches the unmodified old version.
    old_prompt=dest/'README_SCRIPT.md'
    new_prompt=bundled/'README_SCRIPT.md'
    digest_file=bundled/'factory_v041_prompt.sha256'
    if old_prompt.is_file() and new_prompt.is_file() and digest_file.is_file():
        if hashlib.sha256(old_prompt.read_bytes()).hexdigest()==digest_file.read_text().strip():
            shutil.copy2(old_prompt,dest/'.factory_backups_v042'/'README_SCRIPT.md')
            shutil.copy2(new_prompt,old_prompt)
            events.append('README_SCRIPT.md upgraded')
    checked.write_text('Factory v0.4.2 migration checked; custom edits and removed modules kept.\n',encoding='utf8')
    return events


def upgrade_factory_customization():
    """Refresh only the unchanged v0.4.1 prompt; preserve personal edits."""
    import hashlib, shutil
    root=customization_dir()
    target=root/'README_CUSTOMIZATION.md'
    source=bundled_studio_root()/'customization'/'README_CUSTOMIZATION.md'
    marker=root/'.factory_customization_checked_v042'
    if marker.exists():return []
    changed=[]
    old_hash='1f90de820047b91eb81fc8ef4ec0243fbce4856f84ec1e1104f68bb74c7889be'
    if target.is_file() and source.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==old_hash:
        backup=root/'.factory_backups_v042'/'README_CUSTOMIZATION.md'
        backup.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(target,backup)
        shutil.copy2(source,target)
        changed.append('README_CUSTOMIZATION.md upgraded (original backed up)')
    marker.write_text('Customization migration checked; custom edits kept.\n',encoding='utf8')
    return changed


def upgrade_factory_modules_v043():
    """Migrate intact v0.4.2 CPD files; protect user modifications and removals."""
    import hashlib, json, shutil
    destination=scripts_dir()
    marker=destination/'.factory_modules_checked_v043'
    if marker.exists():
        return []
    bundled=bundled_studio_root()/'scripts'
    hashes_file=bundled/'factory_v042_hashes.json'
    if not hashes_file.is_file():
        return ['v0.4.3 migration reference unavailable; no files replaced']
    known=json.loads(hashes_file.read_text(encoding='utf8'))
    notes=[]
    for folder,files in known.items():
        if not (destination/folder/'module.json').is_file():
            continue  # user intentionally removed this module
        for filename,old_hash in files.items():
            target=destination/folder/filename
            fresh=bundled/folder/filename
            if not target.is_file() or not fresh.is_file():
                continue
            current=target.read_bytes()
            updated=fresh.read_bytes()
            if current==updated:
                continue
            if hashlib.sha256(current).hexdigest()!=old_hash:
                notes.append(f'{folder}/{filename}: local edits / other version preserved')
                continue
            backup=destination/'.factory_backups_v043'/folder/filename
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,backup)
            shutil.copy2(fresh,target)
            notes.append(f'{folder}/{filename}: upgraded (v0.4.2 backup saved)')
    prompt_old=destination/'README_SCRIPT.md'
    prompt_new=bundled/'README_SCRIPT.md'
    digest_path=bundled/'factory_v042_prompt.sha256'
    if prompt_old.is_file() and prompt_new.is_file() and digest_path.is_file():
        prior=prompt_old.read_bytes()
        if (prior!=prompt_new.read_bytes() and
                hashlib.sha256(prior).hexdigest()==digest_path.read_text().strip()):
            backup=destination/'.factory_backups_v043'/'README_SCRIPT.md'
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(prompt_old,backup)
            shutil.copy2(prompt_new,prompt_old)
            notes.append('README_SCRIPT.md: upgraded (backup saved)')
    marker.write_text('Factory v0.4.3 migration complete\n',encoding='utf8')
    return notes


def upgrade_factory_modules_v050():
    """Upgrade only intact v0.4.3 files; install missing original engine assets.

    Removing a module is permanent until the user imports it again. User edits
    are not overwritten, and the previous factory version is backed up.
    """
    import hashlib, json, shutil
    dest=scripts_dir()
    marker=dest/'.factory_modules_checked_v050'
    if marker.exists():return []
    bundled=bundled_studio_root()/'scripts'
    reference=bundled/'factory_v043_hashes.json'
    if not reference.is_file():return ['v0.5.0 factory hashes unavailable']
    known=json.loads(reference.read_text(encoding='utf8'))
    messages=[]
    for module,old_files in known.items():
        target=dest/module
        source=bundled/module
        if not (target/'module.json').is_file():continue
        for name,known_digest in old_files.items():
            current=target/name
            fresh=source/name
            if not current.is_file() or not fresh.is_file():continue
            if current.read_bytes()==fresh.read_bytes():continue
            if hashlib.sha256(current.read_bytes()).hexdigest()!=known_digest:
                messages.append(f'{module}/{name}: custom changes preserved')
                continue
            backup=dest/'.factory_backups_v050'/module/name
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(current,backup)
            shutil.copy2(fresh,current)
            messages.append(f'{module}/{name}: upgraded (backup saved)')
        # Keep each scientific engine next to its owning module.  Never replace
        # a locally edited engine file. New assets are copied without overwrite.
        for name in ('legacy_engine.py','vendor'):
            path=source/name
            if not path.exists():continue
            dst=target/name
            if path.is_dir():
                shutil.copytree(path,dst,dirs_exist_ok=True,
                                copy_function=_copy_missing_only)
            elif not dst.exists():
                shutil.copy2(path,dst)
                messages.append(f'{module}/{name}: original engine adapter installed')
    marker.write_text('Factory 0.5.0 checked. Locally edited modules retained.\n',encoding='utf8')
    return messages


def _copy_missing_only(src,dst):
    """shutil.copytree callback that leaves already-present vendor files intact."""
    import shutil
    if not Path(dst).exists():shutil.copy2(src,dst)
    return dst


def upgrade_factory_customization_v051():
    """Refresh the v0.5.0 customization guide only when it is unmodified.

    This is documentation migration only: user-created presets are never read
    or overwritten, and a user-edited README stays untouched.
    """
    import hashlib
    import shutil
    root=customization_dir()
    marker=root/'.factory_customization_checked_v051'
    if marker.exists():
        return []
    target=root/'README_CUSTOMIZATION.md'
    bundled=bundled_studio_root()/'customization'/'README_CUSTOMIZATION.md'
    old_sha='b451e1c88c2bf6e5e88c382f96b24323902433c58e77d0249cd88ddbbfc2795a'
    # The digest is intentionally pinned to the last released factory guide.
    notes=[]
    if target.is_file() and bundled.is_file() and target.read_bytes()!=bundled.read_bytes():
        if hashlib.sha256(target.read_bytes()).hexdigest()==old_sha:
            backup=root/'.factory_backups_v051'/'README_CUSTOMIZATION.md'
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,backup)
            shutil.copy2(bundled,target)
            notes.append('README_CUSTOMIZATION.md updated (old version backed up)')
        else:
            notes.append('README_CUSTOMIZATION.md has local edits; kept unchanged')
    marker.write_text('v0.5.1 documentation migration checked.\n',encoding='utf8')
    return notes


def upgrade_factory_brand_themes_v054():
    """Use SPM Studio's new neutral palette without overwriting a custom theme.

    A copied 0.5.3 default may exist in the user-owned customization folder.
    Refresh that file only if its hash matches exactly the original factory
    bytes. Existing user edits and user-created themes remain unchanged.
    """
    import hashlib
    import shutil
    original_hashes = {
        'default_dark.json': 'bf23fea23162fc860bf90ab2247e5a230a06be3c72d14072d7cde902de0d8d83',
        'default_light.json': '0127d4452264829158e01bb01b96ec55fa16cceaccde2544e811e73224781886',
    }
    directory = customization_dir() / 'themes'
    directory.mkdir(parents=True, exist_ok=True)
    factory = bundled_studio_root() / 'customization' / 'themes'
    messages=[]
    for name,digest in original_hashes.items():
        existing=directory/name
        target=factory/name
        if not existing.is_file() or not target.is_file():
            continue
        if existing.read_bytes() == target.read_bytes():
            continue
        if hashlib.sha256(existing.read_bytes()).hexdigest()!=digest:
            messages.append(f'{name}: personalized colors preserved')
            continue
        backup=directory/'.factory_backups_v054'/name
        backup.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(existing,backup)
        shutil.copy2(target,existing)
        messages.append(f'{name}: migrated to SPM Studio palette; original backed up')
    return messages


def upgrade_factory_modules_v055():
    """Update only the untouched v0.7 lattice renderer to the vector-PDF fix.

    A custom scientific script is never overwritten; old source is backed up.
    All other modules use the common result library and need no engine edits.
    """
    import hashlib
    import shutil
    dest=scripts_dir()
    marker=dest/'.factory_modules_checked_results_v071'
    if marker.exists():return []
    source=bundled_studio_root()/'scripts'/'lattice_measurements'/'module.py'
    target=dest/'lattice_measurements'/'module.py'
    known={'b5a461f6d866e702bc9fe7eda76500b80283035fe08fda1e59b42c7ba903580f'}
    notes=[]
    if target.is_file() and source.is_file() and target.read_bytes()!=source.read_bytes():
        current=hashlib.sha256(target.read_bytes()).hexdigest()
        if current in known:
            backup=dest/'.factory_backups_results_v071'/'lattice_measurements'/'module.py'
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,backup)
            shutil.copy2(source,target)
            notes.append('Lattice renderer upgraded to vector PDF/SVG; original backed up')
        else:
            notes.append('Lattice module customized: kept intact; result organization still applies')
    marker.write_text('Result renderer upgrade checked. Custom work preserved.\n',encoding='utf8')
    return notes


def upgrade_factory_lattice_20261108():
    """Apply the narrowly-scoped new lattice report to unchanged factory modules.

    Never overwrite scientific scripts edited by the user. A backup is stored
    before each factory replacement, also if an earlier marker already exists.
    """
    import hashlib, shutil
    source=bundled_studio_root()/'scripts'/'lattice_measurements'
    target=scripts_dir()/'lattice_measurements'
    if not (target/'module.json').is_file():return []
    hashes={'module.py': 'd9972970d848c9126102d0c3b7c47a7534ac6c95879e2b4672b16818547100c2', 'module.json': 'af9a073c9fa0e683d4010e11a2730eab98c7d65fa3abfbd6733758d14eb436ad', 'legacy_engine.py': 'dbabad9ee945102bcad5f7b713145ff92adc688abb4456ced4d4ad54ad2e608c', 'lattice_artifacts.py': '9b88eabb4293ed8be8bd7600829412b327c662d873a011809e6a18185b15a7ed'}
    notes=[]
    for filename,digest in hashes.items():
        old=target/filename;updated=source/filename
        if not old.is_file() or not updated.is_file():continue
        before=old.read_bytes();after=updated.read_bytes()
        if before==after:continue
        if hashlib.sha256(before).hexdigest()!=digest:
            notes.append(f'{filename}: local lattice edits preserved')
            continue
        backup=target.parent/'.factory_backups_20261108'/'lattice_measurements'/filename
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():shutil.copy2(old,backup)
        shutil.copy2(updated,old)
        notes.append(f'{filename}: updated for new lattice report (backed up)')
    return notes


def upgrade_factory_lattice_v5():
    """Upgrade *only* known unmodified v4 lattice files, preserving local edits.

    Existing installations keep user-owned scripts in the workspace, so simply
    installing updated bundled sources is not enough. Do not overwrite unknown
    hashes: users may have modified their scientific analysis pipelines.
    """
    import hashlib
    import shutil
    factory=bundled_studio_root()/'scripts'/'lattice_measurements'
    local=scripts_dir()/'lattice_measurements'
    known={
        'module.py': {'b3733bdf0cd22011e9f0b756d62a051e466c3e6a1c9d492354e7f273ffa3d38a'},
        'vendor/spm_multiframe/plotting/scale_bar.py':
            {'31d8ed25f88fe70c59265293259da6c4cb5b2fb0855aef4db266dd90ce69b9c5'},
    }
    messages=[]
    for name, trusted in known.items():
        current=local/name
        replacement=factory/name
        if not current.is_file() or not replacement.is_file():continue
        if current.read_bytes()==replacement.read_bytes():continue
        sha=hashlib.sha256(current.read_bytes()).hexdigest()
        if sha not in trusted:
            messages.append(f'{name}: locally edited lattice file preserved')
            continue
        backup=local.parent/'.factory_backups_display_v5'/'lattice_measurements'/name
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():shutil.copy2(current,backup)
        shutil.copy2(replacement,current)
        messages.append(f'{name}: display/scale upgrade applied; v4 backup saved')
    return messages


def repair_missing_factory_helpers():
    """Restore missing companion assets for installed, editable factory modules.

    Earlier installations copied modules once, then wrote a marker. Newer
    module.py versions import helper sources that may never have been copied,
    causing ModuleNotFoundError in the isolated runner. This operation is
    idempotent, marker-independent, and NEVER overwrites locally edited files,
    manifests or entrypoints. Removed *modules* remain removed.
    """
    import json
    import shutil
    bundled = bundled_studio_root() / 'scripts'
    local = scripts_dir()
    messages = []
    if not bundled.is_dir():
        return [f'Factory module asset source unavailable: {bundled}']
    for original in sorted(bundled.iterdir()):
        if not original.is_dir() or not (original / 'module.json').is_file():
            continue
        target = local / original.name
        manifest = target / 'module.json'
        if not manifest.is_file():
            continue  # do not reinstall deleted tools
        try:
            factory_id = json.loads((original / 'module.json').read_text(encoding='utf8')).get('id')
            installed_id = json.loads(manifest.read_text(encoding='utf8')).get('id')
        except (OSError, ValueError, TypeError):
            continue
        if not factory_id or factory_id != installed_id:
            continue  # unrelated user module happens to share a folder name
        # Only restore helper Python files and vendor support trees. The main
        # user-editable entrypoint and manifest are never touched.
        for source in sorted(original.iterdir()):
            if source.name in ('module.py', 'module.json', 'README.md'):
                continue
            if source.is_file() and source.suffix == '.py':
                dst = target / source.name
                if not dst.exists():
                    shutil.copy2(source, dst)
                    messages.append(f'{original.name}/{source.name}: restored missing script helper')
            elif source.is_dir() and source.name in ('vendor', 'resources', 'assets'):
                for child in sorted(source.rglob('*')):
                    if not child.is_file() or '__pycache__' in child.parts:
                        continue
                    dst = target / child.relative_to(original)
                    if not dst.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(child, dst)
                        messages.append(f'{original.name}/{child.relative_to(original)}: restored missing asset')
    return messages


def upgrade_factory_profiles_v7():
    """Safely migrate the *original*, unedited factory KPFM profile only.

    Custom profiles are never overwritten.  A v7 factory profile may be added
    to existing installations that already have customization folders.
    """
    import hashlib, shutil
    source=bundled_studio_root()/'customization'/'profiles'
    dest=customization_dir()/'profiles'
    dest.mkdir(parents=True,exist_ok=True)
    notes=[]
    marker=dest/'.factory_profile_upgrade_v7'
    if marker.exists():return notes
    for name in ('AFM_Molecular_Resolution.json',):
        target=dest/name
        if not target.exists() and (source/name).is_file():
            shutil.copy2(source/name,target)
            notes.append(f'Installed new profile {name}')
    old=dest/'KPFM.json'
    replacement=source/'KPFM.json'
    # Exact SHA-256 of the unmodified KPFM factory profile used by v6.
    digest='51b861134eef04b58a70c53de886d55297034a298d2188366815d7a39ad33409'
    if old.is_file() and replacement.is_file():
        if hashlib.sha256(old.read_bytes()).hexdigest()==digest:
            backup=dest/'.factory_profile_backups_v7'/'KPFM.json'
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(old,backup)
            shutil.copy2(replacement,old)
            notes.append('Updated original KPFM profile (backup kept)')
        else:
            # v0.0.5: no second "KPFM_v7" profile any more; the customized file is kept as it is.
            notes.append('Preserved customized KPFM.json')
    marker.write_text('Factory profile migration completed; personal profiles preserved.\n',encoding='utf-8')
    return notes


def upgrade_factory_analysis_v13():
    """Refresh v12 factory scripts on existing installations without losing edits.

    Previous installations use a one-time copy; bundles alone do not refresh
    ~/.local/share/spm-studio-ai/scripts. Back up before every known-file update.
    Unknown local edits are retained, and restored missing molecule tools are
    limited to this specific user-requested built-in workflow.
    """
    import hashlib, shutil
    previous={'lattice_measurements': {'module.py': 'd418daff46651738915a2f9105399f7f35aae39e061160b81049c2d8986a16e4', 'module.json': '42baa95cc7be9dbe94ad5ef31ce00e77b06d487024ce88cd76f77f21a9125df8', 'lattice_artifacts.py': '0817ed64d085934ed6d8090b22935c8233e86945a315ad30829845dc84f3c2d6', 'legacy_engine.py': '353218e70bd154911bd5a0d9524bda2622762881e0e8d08b20937fa372c83b85'}, 'molecule_placement': {'module.py': 'c9f6cbb426302289321364b00f4c4074d5aea75120412e8263cff6f423712039', 'module.json': '37989bcd1808b03615fefbb5ee8dad4553fab2085abdf80cbe593cef28842ed0', 'placement_engine.py': 'd53e112da668b6869e77f267fa59f89ac3dd99dd0f1e59181c9533bf91e3d730', 'preview_worker.py': '7c9838f6cdec9dddef70200421e2fc38fa92563ce4de83246dda161aa129ca1e'}}
    source=bundled_studio_root()/'scripts'
    local=scripts_dir()
    changes=[]
    for folder,hashes in previous.items():
        factory=source/folder
        if not (factory/'module.json').is_file():continue
        target=local/folder
        if not target.exists():
            shutil.copytree(factory,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            changes.append(f'Restored {folder} analysis module')
            continue
        for filename,digest in hashes.items():
            src=factory/filename; dst=target/filename
            if not src.exists():continue
            if not dst.exists():
                dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,dst)
                changes.append(f'Installed missing {folder}/{filename}')
                continue
            old=dst.read_bytes()
            if old==src.read_bytes():continue
            if hashlib.sha256(old).hexdigest()!=digest:
                changes.append(f'Preserved user edits in {folder}/{filename}')
                continue
            backup=local/'.factory_backups_v13'/folder/filename
            backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.exists():shutil.copy2(dst,backup)
            shutil.copy2(src,dst)
            changes.append(f'Updated {folder}/{filename} with backup')
    return changes


def synchronize_molecule_tools_v14():
    """Install working SVG placement, retire two unused tools, keep backups.

    Unlike old one-shot upgrade markers, run on every startup. Existing app
    installations use a user-owned script tree, so shipping a new wheel alone
    never replaces the broken old manifest/scripts. Existing contents are moved
    to hidden backup directories first, not silently destroyed.
    """
    import shutil, json, hashlib
    source = bundled_studio_root() / 'scripts' / 'molecule_placement'
    dest = scripts_dir()
    if not (source / 'module.json').is_file():
        return ['v14 molecule source missing; original files left untouched']
    backup_root = dest / '.factory_backups_v14'
    notes = []

    def backup_folder(folder, purpose):
        backup_root.mkdir(parents=True, exist_ok=True)
        # Files remain inspectable and restorable.  This also supports a user
        # who edited a factory module after its original installation.
        manifest = folder / 'module.json'
        digest = hashlib.sha256(manifest.read_bytes() if manifest.is_file()
                                else folder.name.encode()).hexdigest()[:12]
        backup = backup_root / (purpose + '_' + digest)
        suffix = 1
        while backup.exists():
            if sorted(p.relative_to(folder) for p in folder.rglob('*') if p.is_file()) == sorted(
                    p.relative_to(backup) for p in backup.rglob('*') if p.is_file()):
                if all((backup / p.relative_to(folder)).read_bytes() == p.read_bytes()
                       for p in folder.rglob('*') if p.is_file()):
                    shutil.rmtree(folder)
                    return backup
            backup = backup_root / (purpose + '_' + digest + '_' + str(suffix))
            suffix += 1
        shutil.move(str(folder), str(backup))
        return backup

    # Remove even old installations of the unwanted two tools. Their source
    # folders were removed from v14, so a future clean install won't re-add them.
    for folder in sorted(dest.iterdir()):
        manifest = folder / 'module.json'
        if not folder.is_dir() or not manifest.is_file():continue
        try: info = json.loads(manifest.read_text(encoding='utf8'))
        except (OSError,ValueError,TypeError):continue
        name = str(info.get('name','')).casefold()
        if (info.get('id') == 'batch_scan_report' or 'batch scan report' in name or
                ('physically informed' in name and info.get('id') != 'molecule_placement')):
            previous = backup_folder(folder,'retired_' + folder.name)
            notes.append(f'Removed obsolete tool {folder.name}; backup: {previous}')

    # v15: this legacy rectangle-only overlay is redundant with the full SVG
    # placement tool. Retire BOTH the scripts copy and any old builtin copy.
    # Keep a backup, and do not reintroduce it during factory installation.
    for folder in sorted(dest.iterdir()):
        if not folder.is_dir():continue
        manifest=folder/'module.json'
        if folder.name=='molecule_lattice_overlay':
            previous=backup_folder(folder,'retired_molecule_lattice_overlay')
            notes.append(f'Retired redundant molecule/lattice overlay: {previous}')
            continue
        if manifest.is_file():
            try:info=json.loads(manifest.read_text(encoding='utf8'))
            except (OSError,ValueError,TypeError):continue
            if info.get('id')=='molecule_lattice_overlay':
                previous=backup_folder(folder,'retired_'+folder.name)
                notes.append(f'Retired redundant molecule/lattice overlay: {previous}')

    target = dest / 'molecule_placement'
    marker = dest / '.factory_molecule_placement_v14_installed'
    # Completed upgrade remains user-editable. A later startup must not
    # overwrite modifications made after v14 was installed.
    if marker.is_file() and (target / 'module.json').is_file():
        return notes
    if target.exists():
        src_files = {p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc'}
        dst_files = {p.relative_to(target):p.read_bytes() for p in target.rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc'}
        if src_files == dst_files:
            marker.write_text('v14 molecule tool installed; subsequent edits remain user-owned\n',encoding='utf8')
            return notes
        prior = backup_folder(target,'molecule_placement_pre_v14')
        notes.append(f'Backed up existing molecule placement tool: {prior}')
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    marker.write_text('v14 molecule tool installed; subsequent edits remain user-owned\n',encoding='utf8')
    notes.append('Installed v14 molecule SVG/PNG placement tool with working file chooser')
    return notes

V15_FACTORY_PREVIOUS_SHA256={'lattice_measurements': {'module.json': '0141dcf0d2be5a7a9be6f7e27b9d957255262d8f67ae7c06cf489155fa490b20', 'module.py': '9cf021c5b310b6aba9055f6b0ccda828f5164e22dbbd3a28e02dc773ff1583cb', 'lattice_artifacts.py': 'f0d2880f66f2c04808aebe03185e888d04610567c4f27c3889806ef9f0409d27'}, 'molecule_placement': {'module.json': '8a259f454bb6936905f9af41ff8dae36f9ea565460a58b0585d18802bd2aabda', 'module.py': 'df42ea90d13b00af17073590f6d46d6611499c2e15698a5fdfc46e8496018b1c', 'placement_engine.py': 'f14235d17915dc05801c611f9ccad557d3df7b2adc39e6281a11a5bf1e0ef98d', 'lattice_artifacts.py': '9b88eabb4293ed8be8bd7600829412b327c662d873a011809e6a18185b15a7ed', 'preview_worker.py': '4a8a3b2c68a549cad185f2c8bf9cf3fa0dea6ddb7f90a791059980502e7414a3'}}


def upgrade_factory_overlays_v15():
    """Move unchanged v14 tool files to v15; preserve local script edits.

    Migration runs on every startup and compares with *exact* original v14
    contents; backup only files that are actually replaced. Old overlay tool
    is retired by synchronize_molecule_tools_v14 independently of markers.
    """
    import hashlib,shutil
    source=bundled_studio_root()/'scripts'
    dest=scripts_dir()
    known=V15_FACTORY_PREVIOUS_SHA256
    notes=[]
    for module,files in known.items():
        installed=dest/module
        packaged=source/module
        if not (installed/'module.json').is_file() or not packaged.is_dir():continue
        for file,digest in files.items():
            src=packaged/file
            dst=installed/file
            if not src.is_file():continue
            if not dst.is_file():
                # Only repair modules installed from the original factory.
                shutil.copy2(src,dst)
                notes.append(f'{module}/{file}: restored missing factory helper')
                continue
            data=dst.read_bytes()
            if data==src.read_bytes():continue
            if hashlib.sha256(data).hexdigest()!=digest:
                notes.append(f'{module}/{file}: custom or unknown version preserved; use restore script if needed')
                continue
            backup=dest/'.factory_backups_v15'/module/file
            backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.is_file():shutil.copy2(dst,backup)
            shutil.copy2(src,dst)
            notes.append(f'{module}/{file}: upgraded to v15 (backup saved)')
    return notes


V16_FACTORY_PREVIOUS_SHA256={'lattice_measurements': {'module.json': '07d551de9a1e2e61ad914637d3efeef0a37720257311a1423596d34e135e6116', 'module.py': 'f9861dd52af3c814b8a9715b927e35ca6e25511f081e4bff2f08cad966ccbac3', 'lattice_artifacts.py': 'c95ec605d0d22d5dd11cac5cff3cf6d940a53bd9931153c22a8a0d2bef532801'}, 'molecule_placement': {'module.json': 'e4917f7de60408e909c05e84837852254b81bb4a28acc3843a889479e7c71b1e', 'module.py': '07e762c6a7d7935f717dd907f7ba23fd2e5f37dfeedf7a01b828b5269f46b7df', 'lattice_artifacts.py': 'c95ec605d0d22d5dd11cac5cff3cf6d940a53bd9931153c22a8a0d2bef532801', 'placement_engine.py': '56359a1c1b0041426efe95b2f88a9350063a626b24922de8402d880f311e456b', 'preview_worker.py': '83442c37446a18a8f561ccf1b3aaf1de3636ee83b34d3388b95fe716f342789f'}}


def upgrade_factory_overlays_v16():
    """Upgrade original v15 lattice/molecule tools without overwriting edits.

    Every changed original file is backed up once. If a user customized any
    component, it remains unmodified and the v16 verifier explains the manual
    backed-up reset path.
    """
    import hashlib,shutil
    source=bundled_studio_root()/'scripts'
    destination=scripts_dir()
    notes=[]
    for module,files in V16_FACTORY_PREVIOUS_SHA256.items():
        target=destination/module
        packaged=source/module
        if not (target/'module.json').is_file() or not packaged.is_dir():
            continue
        for name,previous_digest in files.items():
            new=packaged/name
            installed=target/name
            if not new.is_file():continue
            if not installed.is_file():
                shutil.copy2(new,installed)
                notes.append(f'{module}/{name}: missing factory helper restored')
                continue
            original=installed.read_bytes()
            if original==new.read_bytes():continue
            if hashlib.sha256(original).hexdigest()!=previous_digest:
                notes.append(f'{module}/{name}: customized or unknown version preserved; use restore_analysis_tools_v16.sh to replace')
                continue
            backup=destination/'.factory_backups_v16'/module/name
            backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.exists():shutil.copy2(installed,backup)
            shutil.copy2(new,installed)
            notes.append(f'{module}/{name}: upgraded to v16; previous file backed up')
    return notes


def scan_recap_folder(source_folder) -> "Path":
    """The sibling folder a scan selection is exported to: ``<name>_scan_recap`` next to the
    opened dataset folder (``.../Data/20261106`` -> ``.../Data/20261106_scan_recap``). A folder
    that already is a recap folder maps to itself, so re-exporting keeps working in place."""
    from pathlib import Path as _Path
    source=_Path(source_folder)
    if source.name.endswith('_scan_recap'):
        return source
    return source.parent/f'{source.name}_scan_recap'


def ensure_factory_channel_overlay_v27():
    """Install the newly introduced tool even if older factory markers exist."""
    import shutil
    source=bundled_studio_root()/'scripts'/'channel_overlay'
    target=scripts_dir()/'channel_overlay'
    if source.is_dir() and not target.exists():
        shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        return ['Channel overlay tool added to Tools list']
    return []


# v0.8.0 — lattice / molecule figures drawn by the Export-panel renderer.
# Exact SHA-256 of the files shipped with SPM Studio 0.7.0. An installed copy
# that still matches is upgraded (with a backup); edited copies are preserved.
V080_FACTORY_PREVIOUS_SHA256={
    'lattice_measurements': {'module.py': '12b48b45ac7cab58a81ae5fea3b487f1e80a9bdcc57c64c1a75c63008d1d88b9',
                             'module.json': '09321db98ad5dc7435e4d25f41e8f89879ce9712de76169be557b2b8cbca56b0',
                             'legacy_engine.py': 'ead3d8be2d9672620e76a605d2874aa80c99db6681b588c4925f09dcd93d8ff4',
                             'lattice_artifacts.py': '8df09e68c82d4e1cbf904d5b73c02efc1e31d6690dd9d4294e02e2ead84837ce'},
    'molecule_placement': {'module.py': 'b7b74a25d59433352f6e3c1755744e999bb315d2c3e89710aa4b5a4ca309b8f5',
                           'module.json': '6279f0f623321e089cff7c0d4328e4a7f7bbf7487e70e8fed168147bddb22a8d',
                           'placement_engine.py': '81275740001d129e5802b6f8a33f82b34283cd534a62ba0f7c5ff9f24c6d0ee6',
                           'preview_worker.py': '10d6980a7862dfe81dafa6665730f9d269093843a95c19e06b1e2e58d89a3768',
                           'vector_publication.py': 'db9f758742e8e1ed28aa559c818b2c880f828b30c3f14ee72749bf22407d1a11',
                           'lattice_artifacts.py': '8df09e68c82d4e1cbf904d5b73c02efc1e31d6690dd9d4294e02e2ead84837ce'}}


def _known_previous_digests(module, name):
    digests={V080_FACTORY_PREVIOUS_SHA256.get(module,{}).get(name)}
    for table in (V16_FACTORY_PREVIOUS_SHA256, V15_FACTORY_PREVIOUS_SHA256):
        digests.add(table.get(module,{}).get(name))
    digests.discard(None)
    return digests


def upgrade_factory_tools_v080(force=False):
    """Bring the installed lattice / molecule tools to the 0.8.0 versions.

    Unchanged factory files are replaced (backup in ``.factory_backups_v080``);
    files the user edited are preserved unless ``force`` is True (menu action
    *Tools › Restore built-in tools*), which still backs them up first.
    """
    import hashlib, shutil
    source=bundled_studio_root()/'scripts'
    destination=scripts_dir()
    notes=[]
    for module,files in V080_FACTORY_PREVIOUS_SHA256.items():
        target=destination/module
        packaged=source/module
        if not (target/'module.json').is_file() or not packaged.is_dir():
            continue
        for name in files:
            new=packaged/name
            installed=target/name
            if not new.is_file():continue
            if not installed.is_file():
                shutil.copy2(new,installed)
                notes.append(f'{module}/{name}: installed 0.8 file')
                continue
            current=installed.read_bytes()
            if current==new.read_bytes():continue
            if not force and hashlib.sha256(current).hexdigest() not in _known_previous_digests(module,name):
                notes.append(f'{module}/{name}: your edited copy was kept (Tools › Restore built-in tools to replace it)')
                continue
            backup=destination/'.factory_backups_v080'/module/name
            backup.parent.mkdir(parents=True,exist_ok=True)
            if backup.exists():
                i=2
                while backup.with_name(f'{backup.name}.{i}').exists():i+=1
                backup=backup.with_name(f'{backup.name}.{i}')
            shutil.copy2(installed,backup)
            shutil.copy2(new,installed)
            notes.append(f'{module}/{name}: updated to 0.8 (backup saved)')
    return notes


def migrate_themes_v080():
    """Retire the unmodified old factory themes (now Graphite / Porcelain).

    Only files whose bytes are exactly a known factory version are moved to a
    backup folder; personalised themes always stay in the Appearance menu.
    """
    import hashlib, shutil
    factory = {
        'default_dark.json': {'e47408806d1a40167477c1c9b9cb1234fc1086d35edf7bc3f005e0fb42fbb810',
                              'bf23fea23162fc860bf90ab2247e5a230a06be3c72d14072d7cde902de0d8d83'},
        'default_light.json': {'00109ed6ea786fd4709b2fedcb84a7f8a145e87b869dae2618c07126f69dd0d6',
                               '0127d4452264829158e01bb01b96ec55fa16cceaccde2544e811e73224781886'},
    }
    directory = customization_dir() / 'themes'
    if not directory.is_dir():
        return []
    notes = []
    for name, digests in factory.items():
        path = directory / name
        if not path.is_file():
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() not in digests:
            continue
        backup = directory / '.factory_backups_v080' / name
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(path, backup)
        path.unlink()
        notes.append(f'{name}: replaced by the new Graphite / Porcelain themes (backup kept)')
    return notes


# ----------------------------------------------------------------------------- v0.0.5
GITHUB_URL = 'https://github.com/maxlpld/SPM-Studio'
AUTHOR_NAME = 'maxlpld'
AUTHOR_URL = 'https://github.com/maxlpld'

# Guide installed in every user folder: (source relative to the bundled tree, destination folder
# relative to its user root, root kind). The Assistant is told to read the guide of a folder
# before it creates or edits anything in that folder.
GUIDES = (
    ('scripts/README.md', '', 'scripts'),
    ('customization/profiles/README.md', 'profiles', 'customization'),
    ('customization/export_presets/README.md', 'export_presets', 'customization'),
    ('customization/themes/README.md', 'themes', 'customization'),
    ('customization/colormaps/README.md', 'colormaps', 'customization'),
    ('customization/plot_styles/README.md', 'plot_styles', 'customization'),
    ('customization/shortcuts/README.md', 'shortcuts', 'customization'),
)


def guide_sources() -> "Path":
    """Folder holding the bundled guides: the source tree when present, else the package copy."""
    root = bundled_studio_root()
    if (root / 'customization' / 'profiles' / 'README.md').is_file():
        return root
    return Path(__file__).resolve().parents[1] / 'resources' / 'guides'


def ensure_guides():
    """Make sure every scripts / customization folder holds its ``README.md`` guide.

    A missing guide is installed. A guide that is still an unmodified copy of an earlier
    release is refreshed; a guide the user edited is never overwritten. Returns notes.
    """
    import hashlib
    import json
    import shutil
    notes = []
    source_root = guide_sources()
    state_file = config_dir() / 'guides_installed.json'
    try:
        state = json.loads(state_file.read_text(encoding='utf8'))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    changed = False
    for relative, folder, kind in GUIDES:
        source = source_root / relative
        if not source.is_file():
            continue
        target_dir = (scripts_dir() if kind == 'scripts' else customization_dir()) / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / 'README.md'
        new_bytes = source.read_bytes()
        new_digest = hashlib.sha256(new_bytes).hexdigest()
        key = f'{kind}/{folder}'.rstrip('/')
        if not target.exists():
            shutil.copy2(source, target)
            notes.append(f'Installed guide {target}')
        else:
            current = hashlib.sha256(target.read_bytes()).hexdigest()
            if current != new_digest and current == state.get(key):
                shutil.copy2(source, target)      # untouched copy of an older release
                notes.append(f'Updated guide {target}')
            elif current != new_digest:
                continue                          # edited by the user (or pre-0.0.5 file): keep
        if state.get(key) != new_digest:
            state[key] = new_digest
            changed = True
    if changed:
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state, indent=2) + '\n', encoding='utf8')
        except OSError:
            pass
    return notes


def guide_for(folder) -> "Path | None":
    """The guide an agent (or a person) should read before changing ``folder``."""
    folder = Path(folder)
    for name in ('README.md', 'README_SCRIPT.md', 'README_CUSTOMIZATION.md'):
        if (folder / name).is_file():
            return folder / name
    return None


def module_readme(module_path) -> "Path | None":
    """README of one analysis tool (``<tool>/README.md``, any case), if it has one."""
    folder = Path(module_path)
    if folder.is_file():
        folder = folder.parent
    try:
        for entry in sorted(folder.iterdir()):
            if entry.is_file() and entry.name.lower() in ('readme.md', 'readme.txt', 'readme'):
                return entry
    except OSError:
        return None
    return None


# ---- items the user removed in Settings › Library must not come back at the next start
def _removed_file() -> Path:
    return customization_dir() / '.removed_factory_items.json'


def removed_factory_items() -> set:
    import json
    try:
        data = json.loads(_removed_file().read_text(encoding='utf8'))
        return {str(x) for x in data} if isinstance(data, list) else set()
    except (OSError, ValueError):
        return set()


def mark_factory_item_removed(relative: str, removed: bool = True):
    """Remember (or forget) that ``<folder>/<file>`` of the customization tree was removed."""
    import json
    items = removed_factory_items()
    relative = str(relative).replace('\\', '/')
    if removed:
        items.add(relative)
    else:
        items.discard(relative)
    try:
        _removed_file().write_text(json.dumps(sorted(items), indent=2) + '\n', encoding='utf8')
    except OSError:
        pass


def cleanup_kpfm_profiles_v005():
    """Keep one KPFM profile.

    Installations upgraded from the internal v6 builds could end up with ``KPFM.json`` (the old
    profile) *and* ``KPFM_v7.json`` (the current one). The current factory profile becomes
    ``KPFM.json``; both previous files are kept in ``profiles/.profile_backups_v005``.
    """
    import shutil
    dest = customization_dir() / 'profiles'
    dest.mkdir(parents=True, exist_ok=True)
    marker = dest / '.kpfm_cleanup_v005'
    if marker.exists():
        return []
    notes = []
    duplicate = dest / 'KPFM_v7.json'
    current = dest / 'KPFM.json'
    factory = bundled_studio_root() / 'customization' / 'profiles' / 'KPFM.json'
    if duplicate.is_file():
        backup = dest / '.profile_backups_v005'
        backup.mkdir(parents=True, exist_ok=True)
        if current.is_file():
            shutil.copy2(current, backup / 'KPFM_previous.json')
        shutil.copy2(duplicate, backup / 'KPFM_v7.json')
        replacement = factory if factory.is_file() else duplicate
        # The profile keeps the plain name "KPFM" whatever the file it came from said.
        try:
            import json
            data = json.loads(replacement.read_text(encoding='utf8'))
            data['name'] = 'KPFM'
            current.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf8')
        except (OSError, ValueError):
            shutil.copy2(replacement, current)
        duplicate.unlink()
        notes.append('Profiles: kept one KPFM profile (the current one); the previous files are in '
                     'profiles/.profile_backups_v005')
    try:
        marker.write_text('Single KPFM profile since SPM Studio 0.0.5.\n', encoding='utf8')
    except OSError:
        pass
    return notes
