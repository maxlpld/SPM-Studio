from pathlib import Path
import hashlib,json
import pytest
from spm_studio.core.registry import load_manifest, discover_modules
from spm_studio.core.paths import upgrade_factory_modules, scripts_dir


def test_shared_selection_manifest_for_all_modules():
    root=Path(__file__).resolve().parents[1]/'scripts'
    modules,errors=discover_modules([root])
    assert not errors
    assert set(modules)=={'channel_overlay','cpd_histogram','flake_height','kpfm_edge','lattice_measurements','molecule_placement','multiframe_drift_stack'}
    assert 'molecule_lattice_overlay' not in modules  # redundant overlay removed
    assert modules['kpfm_edge'].selection['tools']==['line','rectangle']
    assert modules['cpd_histogram'].selection['preview']=='histogram'
    assert modules['flake_height'].selection['multiple'] is True
    assert modules['molecule_placement'].selection['tools']==[]
    for mid,mod in modules.items():
        assert mod.selection is not None, mid


def test_selection_schema_rejects_unknown_tools_and_unsupported_keys(tmp_path):
    folder=tmp_path/'custom';folder.mkdir()
    (folder/'module.py').write_text('def run(ctx): pass\n')
    manifest={'api_version':'1.0','id':'my_module','entrypoint':'module:run',
              'selection':{'tools':['rectangle'],'multiple':False,'preview':'histogram'}}
    p=folder/'module.json';p.write_text(json.dumps(manifest))
    assert load_manifest(p).selection['preview']=='histogram'
    manifest['selection']['tools']=['freehand-polygon'];p.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):load_manifest(p)
    manifest['selection']['tools']=['line'];manifest['selection']['preview']='profiles'
    manifest['selection']['evil']='import os';p.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):load_manifest(p)


def test_factory_migration_updates_only_stock_files_and_keeps_user_edits(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'local_data'))
    dst=scripts_dir()
    (dst/'.factory_modules_installed_v041').write_text('already installed\n')
    root=Path(__file__).resolve().parents[1]
    digest=json.loads((root/'scripts/factory_v041_hashes.json').read_text())
    fixtures=root/'tests/fixtures/factory_v041'
    for name in ('cpd_histogram','flake_height'):
        target=dst/name;target.mkdir()
        for fn in ('module.json','module.py'):
            bytes_old=(fixtures/name/fn).read_bytes()
            assert hashlib.sha256(bytes_old).hexdigest()==digest[name][fn]
            (target/fn).write_bytes(bytes_old)
    # A user-modified algorithm must not be overwritten by a factory update.
    custom=dst/'flake_height/module.py'
    custom.write_text(custom.read_text()+'\n# local adjustment\n')
    messages=upgrade_factory_modules()
    assert any('cpd_histogram/module.json: upgraded' in x for x in messages)
    assert (dst/'cpd_histogram/module.json').read_bytes()==(root/'scripts/cpd_histogram/module.json').read_bytes()
    assert '# local adjustment' in custom.read_text()
    assert (dst/'.factory_backups_v042/cpd_histogram/module.json').exists()
    assert (dst/'.factory_modules_checked_v042').exists()
    assert upgrade_factory_modules()==[]
