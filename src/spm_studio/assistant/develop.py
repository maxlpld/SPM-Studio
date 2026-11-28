"""The classic panel's *Develop* tab, in Agent Hub: a chat in the *Scripts & analysis tools* project builds one
new analysis tool in a staging folder, and *Install a staged tool…* checks it and installs it into the Tools
list (both in the project's menu). Same instructions, checks and installer as before."""
from __future__ import annotations

import uuid
from pathlib import Path


def staging_root() -> Path:
    from spm_studio.ai.security import private_dir
    from spm_studio.core import paths
    return private_dir(paths.data_dir() / 'ai' / 'staging')


def _guide(name: str) -> Path:
    from spm_studio.core import paths
    user = paths.scripts_dir() / name
    return user if user.is_file() else paths.bundled_studio_root() / 'scripts' / name


def instructions(stage: Path, request: str) -> str:
    return ('Build ONE new SPM Studio API 1.0 analysis module. Write module.json, module.py and README.md inside '
            f'the folder {stage} (create nothing outside it). Do not send commands to laboratory hardware or '
            'Nanonis; analysis is OFFLINE ONLY. FIRST read the checklist ' + str(_guide('README.md')) +
            ' and the exact module contract ' + str(_guide('README_SCRIPT.md')) + ', and follow both. The '
            'README.md is required: it is what the user reads with the "Read me" button of the Analysis panel. '
            'Use only non-destructive analysis of saved data. Run syntax validation and write a brief test report. '
            'Never install global dependencies or change Pi settings. When you are done, tell the user to use '
            '"Install a staged tool…" in the menu of the Scripts project.\n\nUser request:\n' + request)


def start(hub, main_window=None):
    from PySide6.QtWidgets import QInputDialog
    text, ok = QInputDialog.getMultiLineText(hub, 'Develop a new analysis tool',
                                             'Describe the tool (what it measures, inputs, outputs):')
    if not ok or not text.strip():
        return None
    stage = staging_root() / ('module-' + uuid.uuid4().hex[:10])
    stage.mkdir(mode=0o700)
    chat = hub.core.store.new_chat(project='scripts', title='New tool: ' + text.strip().splitlines()[0][:60])
    hub.core.store.set_meta(chat['id'], links={'staging': str(stage)})
    hub.core.chatsChanged.emit()
    hub.open_chat(chat['id'], new_panel=True)
    hub.core.run_for(chat['id']).send(instructions(stage, text.strip()), chat.get('backend', 'auto'))
    return stage


def install(hub, main_window=None, folder: Path | None = None, approve: bool = True) -> str:
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from spm_studio.ai.plugins import install_staged, preflight
    from spm_studio.core import paths
    if folder is None:
        latest = sorted(staging_root().glob('module-*'), key=lambda p: p.stat().st_mtime, reverse=True)
        chosen = QFileDialog.getExistingDirectory(hub, 'Select the staged tool folder',
                                                  str(latest[0] if latest else staging_root()))
        if not chosen:
            return ''
        folder = Path(chosen)
    if not (folder / 'module.json').exists():
        subdirs = [f for f in folder.iterdir() if f.is_dir() and (f / 'module.json').exists()]
        if len(subdirs) != 1:
            QMessageBox.warning(hub, 'Install a tool', 'Expected one module.json in the folder or one subfolder.')
            return ''
        folder = subdirs[0]
    try:
        info, n = preflight(folder)
    except Exception as exc:
        QMessageBox.warning(hub, 'Tool check failed', str(exc))
        return ''
    if approve and QMessageBox.question(hub, 'Install the tool', f'{info.name} ({info.id}), {n} files. Syntax and '
                                        'manifest verified, but scientific correctness and code safety are NOT '
                                        'established. Install it into your SPM Studio tools?') != \
            QMessageBox.StandardButton.Yes:
        return ''
    module_id = install_staged(folder, paths.scripts_dir())
    try:
        main_window.refresh_modules()
    except Exception:
        pass
    QMessageBox.information(hub, 'Install a tool', f'Installed: {module_id} (now in Tools).')
    return module_id
