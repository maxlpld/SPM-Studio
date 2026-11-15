"""Tests of targeted removal using only temporary simulated old installs."""
from __future__ import annotations
import os,subprocess,sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_clean_installer_dry_run(tmp_path):
    env={**os.environ,'HOME':str(tmp_path),'XDG_DATA_HOME':str(tmp_path/'share')}
    if hasattr(os,'geteuid') and os.geteuid()==0:pytest.skip('Install scripts intentionally refuse root')
    res=subprocess.run(['bash',str(ROOT/'install_spm_studio_clean.sh'),'--dry-run'],
                       capture_output=True,text=True,env=env,check=True)
    import re as _re
    version=_re.search(r'^version = "(.+)"',(ROOT/'pyproject.toml').read_text(),_re.M).group(1)
    assert f'spm-studio-ai-app/releases/{version}' in res.stdout
    assert not (tmp_path/'share').exists()


def test_old_cleanup_never_deletes_data_or_pi(tmp_path):
    if hasattr(os,'geteuid') and os.geteuid()==0:pytest.skip('Cleanup intentionally refuses root')
    data=tmp_path/'share'
    old=data/'research-studio-app'
    (old/'apps/spm-studio').mkdir(parents=True)
    (old/'apps/research-workbench').mkdir(parents=True)
    (old/'apps/spm-studio/pyproject.toml').write_text('name="spm-studio"')
    pi=tmp_path/'.pi/agent';pi.mkdir(parents=True)
    (pi/'settings.json').write_text('{"model":"existing"}')
    scripts=data/'spm-studio/scripts';scripts.mkdir(parents=True)
    (scripts/'user_script.py').write_text('print("user data")')
    env={**os.environ,'HOME':str(tmp_path),'XDG_DATA_HOME':str(data),
         'XDG_STATE_HOME':str(tmp_path/'state')}
    target=str(ROOT/'uninstall_old_research_studio.sh')
    dry=subprocess.run(['bash',target,'--dry-run'],env=env,capture_output=True,text=True,check=True)
    assert str(old) in dry.stdout and old.is_dir()
    assert str(pi) not in dry.stdout.split('DRY RUN:')[0].split('OLD RESEARCH')[1].split('PRESERVED:')[0]
    applied=subprocess.run(['bash',target,'--apply'],env=env,input='REMOVE OLD APPS\n',
                          capture_output=True,text=True,check=True)
    assert not old.exists()
    assert (pi/'settings.json').exists()
    assert (scripts/'user_script.py').exists()
    assert list((tmp_path/'state/spm-studio-cleanup').glob('removed-*.json'))
