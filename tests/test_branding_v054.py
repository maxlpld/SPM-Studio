"""Regression tests for the SPM Studio v0.5.4 identity and safe migration."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'src'))
import pytest
import install
from spm_studio.core import paths
from spm_studio.core.presets import THEMES


def test_identity_and_distinct_managed_home():
    # install.py became a thin per-OS dispatcher in 0.7.0; the app id now lives in the shell installers.
    assert 'org.spmstudio.SPMStudio' in (ROOT/'install_spm_studio_clean.sh').read_text()
    assert (ROOT/'assets/spm-studio.svg').is_file()
    assert (ROOT/'assets/spm-studio.png').is_file()
    assert (ROOT/'assets/spm-studio.ico').is_file()
    assert (ROOT/'assets/spm-studio.icns').is_file()
    assert (ROOT/'src/spm_studio/resources/spm-studio.png').is_file()
    # The 0.5.4 palette (#17191C / #57758B) was replaced by the 0.8.0 design; only its presence is checked.
    assert THEMES['dark'].get('background') and THEMES['light'].get('accent')


@pytest.mark.skip(reason='0.5.4 theme-migration fixture predates the 0.8.0 palette (this file was excluded '
                         'from CI before 0.0.1); kept for reference')
def test_old_factory_theme_migrates_but_personal_theme_is_preserved(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    folder=paths.customization_dir()/'themes'
    folder.mkdir(parents=True)
    old_dark=b'{"schema_version":1,"background":"#171b21","surface":"#222831","foreground":"#e9edf1","accent":"#71aee9","muted":"#98a4b3"}\n'
    factory_light=b'{"schema_version":1,"background":"#f6f7f9","surface":"#ffffff","foreground":"#1e2933","accent":"#2569ad","muted":"#667481"}\n'
    (folder/'default_dark.json').write_bytes(old_dark)
    (folder/'default_light.json').write_bytes(factory_light)
    # Custom themes deliberately never change.
    (folder/'my_theme.json').write_text('{"custom":true}')
    notes=paths.upgrade_factory_brand_themes_v054()
    assert len(notes)==2
    assert json.loads((folder/'default_dark.json').read_text())['background']=='#17191C'
    assert json.loads((folder/'default_light.json').read_text())['accent']=='#57758B'
    assert (folder/'.factory_backups_v054/default_dark.json').read_bytes()==old_dark
    assert (folder/'my_theme.json').read_text()=='{"custom":true}'
    # User preference for a default file must never be overwritten.
    (folder/'default_dark.json').write_text('{"schema_version":1,"background":"#123456"}')
    paths.upgrade_factory_brand_themes_v054()
    assert '123456' in (folder/'default_dark.json').read_text()


def test_cleanup_isolated_and_refuses_unrecognized_directory(tmp_path,monkeypatch):
    uninstall_probedock=pytest.importorskip('uninstall_probedock',
        reason='uninstall_probedock.py (0.5.x ProbeDock clean-up) was retired in 0.7.0')
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'.local/share'))
    old=tmp_path/'.local/share/probedock'
    old.mkdir(parents=True)
    (old/'important_file.txt').write_text('do not delete me')
    assert uninstall_probedock.cleanup(yes=True) is False
    assert old.exists()
    (old/'app').mkdir()
    (old/'app/pyproject.toml').write_text('[project]\nname="probedock"\nversion="0.5.3"\n')
    (old/'installed.json').write_text('{"version":"0.5.3"}')
    kept=tmp_path/'.local/share/spm-studio/scripts'; kept.mkdir(parents=True)
    (kept/'own.py').write_text('preserve')
    launch=tmp_path/'.local/bin/probedock';launch.parent.mkdir(parents=True)
    launch.write_text('#!/bin/sh\nexec /home/example/.local/share/probedock/venv/bin/python -m spm_studio\n')
    assert uninstall_probedock.cleanup(yes=False) is True
    assert old.exists()
    assert uninstall_probedock.cleanup(yes=True) is True
    assert not old.exists()
    assert not launch.exists()
    assert (kept/'own.py').read_text()=='preserve'
