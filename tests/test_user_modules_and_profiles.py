"""Module/setting contracts that do not require Qt or experimental instruments."""
from pathlib import Path
import json
import pytest
from spm_studio.core.paths import install_factory_modules,install_factory_customization
from spm_studio.core.registry import discover_modules,load_manifest
from spm_studio.core.presets import validate_profile,DEFAULT_PROFILE


def test_user_folder_receives_real_modules_and_prompt_once(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    sources=Path(__file__).resolve().parents[1]/'scripts'
    folder=install_factory_modules(sources)
    mods,errors=discover_modules([folder])
    assert not errors
    assert set(mods)=={'channel_overlay','cpd_histogram','flake_height','kpfm_edge','lattice_measurements','microscope_calibration','molecule_placement','multiframe_drift_stack'}
    assert 'molecule_lattice_overlay' not in mods  # v15 removes redundant molecule overlay
    assert (folder/'README_SCRIPT.md').exists()
    assert mods['flake_height'].interaction=='line_profiles'
    assert mods['cpd_histogram'].interaction=='histogram_masks'
    assert mods['flake_height'].snapshot_channels=='selected'
    assert mods['multiframe_drift_stack'].snapshot_channels=='selected'  # reads other scans directly
    # Users own this folder. A deleted tool stays deleted at the next launch.
    import shutil
    shutil.rmtree(folder/'flake_height')
    install_factory_modules(sources)
    assert 'flake_height' not in discover_modules([folder])[0]


def test_customization_prompt_and_examples_available_in_real_folder(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    folder=install_factory_customization()
    assert (folder/'README_CUSTOMIZATION.md').is_file()
    assert (folder/'profiles'/'KPFM.json').is_file()
    profile=json.loads((folder/'profiles'/'KPFM.json').read_text())
    assert profile['visible_channels']==['Z','Bias']


def test_profile_visible_channels_roundtrip_and_validation():
    value={**DEFAULT_PROFILE,'visible_channels':['Z','Bias']}
    result=validate_profile(value)
    assert result['visible_channels']==['Z','Bias']
    assert len(validate_profile({**value,'visible_channels':[f'C{i}' for i in range(12)]})['visible_channels'])==12
    with pytest.raises(ValueError):validate_profile({**value,'visible_channels':['Z','']})


def test_any_module_can_declare_generic_roi_interaction(tmp_path):
    folder=tmp_path/'my_new_tool';folder.mkdir()
    (folder/'module.py').write_text('def run(ctx): pass\n')
    (folder/'module.json').write_text(json.dumps({'api_version':'1.0','id':'new_tool',
        'entrypoint':'module:run','interaction':'line_profiles','snapshot_channels':'all'}))
    module=load_manifest(folder/'module.json')
    assert module.interaction=='line_profiles'
    assert module.snapshot_channels=='all'
    with pytest.raises(ValueError):
        obj=json.loads((folder/'module.json').read_text());obj['interaction']='unsafe_gui'
        (folder/'module.json').write_text(json.dumps(obj));load_manifest(folder/'module.json')
