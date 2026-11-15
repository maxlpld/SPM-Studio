import json,hashlib,zipfile
from pathlib import Path
from spm_studio.core.paths import scripts_dir,upgrade_factory_modules_v043

ROOT=Path(__file__).resolve().parents[1]


def test_v042_factory_is_upgraded_but_local_edits_preserved(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    dest=scripts_dir()
    # (The developer-only reference archive legacy_reference/CPD HISTO.zip is not needed here and is not
    # shipped; the v0.4.2 originals come from tests/fixtures.)
    original=ROOT/'tests/fixtures/factory_v042/cpd_histogram'
    module=dest/'cpd_histogram';module.mkdir()
    for name in ('module.json','module.py'):
        (module/name).write_bytes((original/name).read_bytes())
    new=ROOT/'scripts/cpd_histogram'
    hashes=json.loads((ROOT/'scripts/factory_v042_hashes.json').read_text())
    for filename,digest in hashes['cpd_histogram'].items():
        assert hashlib.sha256((module/filename).read_bytes()).hexdigest()==digest
    # Existing local edits in the actual algorithm may not be overwritten.
    (module/'module.py').write_text((module/'module.py').read_text()+'\n# custom code\n')
    notes=upgrade_factory_modules_v043()
    assert (module/'module.json').read_bytes()==(new/'module.json').read_bytes()
    assert '# custom code' in (module/'module.py').read_text()
    assert any('preserved' in x for x in notes)
    assert (dest/'.factory_backups_v043/cpd_histogram/module.json').exists()
    assert upgrade_factory_modules_v043()==[]


def test_removed_modules_stay_removed_v043(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    dest=scripts_dir()
    assert upgrade_factory_modules_v043()==[]
    assert not (dest/'cpd_histogram').exists()


def test_stock_prompt_updated_without_touching_modified_prompt(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    folder=scripts_dir()
    old_prompt=ROOT/'tests/fixtures/factory_v042/README_SCRIPT.md'
    prompt=folder/'README_SCRIPT.md'
    prompt.write_bytes(old_prompt.read_bytes())
    notes=upgrade_factory_modules_v043()
    assert 'README_SCRIPT.md: upgraded (backup saved)' in notes
    assert prompt.read_bytes()==(ROOT/'scripts/README_SCRIPT.md').read_bytes()
