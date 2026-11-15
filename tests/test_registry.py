import json
from pathlib import Path
import pytest
from spm_studio.core.registry import discover_modules,load_manifest,validate_params

def test_discovery_no_execution_and_add_remove(tmp_path):
    root=tmp_path/'scripts';root.mkdir()
    marker=tmp_path/'danger'
    p=root/'other';p.mkdir()
    (p/'module.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("BAD")\ndef run(ctx):pass\n')
    manifest={'api_version':'1.0','id':'my_mod','name':'test','entrypoint':'module:run',
              'parameters':{'p':{'type':'integer','default':2,'min':1,'max':5}}}
    (p/'module.json').write_text(json.dumps(manifest))
    mods,warn=discover_modules([root])
    assert not marker.exists() and not warn and 'my_mod' in mods
    assert validate_params(mods['my_mod'],{'p':'4'})['p']==4
    with pytest.raises(ValueError):validate_params(mods['my_mod'],{'p':9})
    (p/'module.json').unlink()
    assert not discover_modules([root])[0]

def test_legacy_registration_without_running(tmp_path):
    root=tmp_path/'scripts';root.mkdir()
    path=root/'old.py';path.write_text('raise RuntimeError("not imported")')
    mods,_=discover_modules([root])
    assert 'legacy_old' in mods and mods['legacy_old'].mode=='legacy'

def test_instrument_rejected(tmp_path):
    p=tmp_path/'bad';p.mkdir()
    (p/'module.py').write_text('')
    (p/'module.json').write_text(json.dumps({'api_version':'1.0','id':'instrument_bad',
              'mode':'instrument','entrypoint':'module:run'}))
    with pytest.raises(ValueError):load_manifest(p/'module.json')
