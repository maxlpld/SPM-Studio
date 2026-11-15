"""Functional tests runnable without Qt, credentials, network, or hardware."""
import json,os,sys,tempfile,subprocess
from pathlib import Path
import pytest
from spm_studio.ai import config
from spm_studio.ai.security import checked_child,redact,CredentialStore
from spm_studio.ai.providers import endpoint,request_chat
from spm_studio.ai.rpc_events import RpcEvents
from spm_studio.ai.plugins import install_staged,preflight,remove_installed
from spm_studio.ai.judge import profiles
from spm_studio.core.registry import discover_modules


def test_standalone_shared_code_and_module_registry():
    from spm_studio.shared.store import ResearchStore
    root=Path(__file__).resolve().parents[1]
    mods,errors=discover_modules([root/'src/spm_studio/builtin_modules'])
    assert len(mods)>=4,errors
    assert 'flake_height' in mods


def test_config_without_secrets(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    s=config.load();assert s['backend']=='none'
    s['backend']='pi';s['pi_executable']='/usr/bin/pi';config.save(s)
    assert config.load()['backend']=='pi'
    assert (tmp_path/'spm-studio-ai/ai/settings.json').stat().st_mode & 0o077==0
    assert 'sk-something-should-never-go-in-config' not in (tmp_path/'spm-studio-ai/ai/settings.json').read_text()
    with pytest.raises(ValueError):
        s['backend']='unsupported';config.save(s)


def test_history_limited_and_resumable(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path))
    config.save_history('Demo',[{'role':'user','content':'hello'},{'role':'assistant','content':'world'}])
    assert config.load_history('Demo')[-1]['content']=='world'
    assert 'Demo' in config.list_histories()
    assert config.history_path('../Demo').parent==config.session_dir()


def test_pi_event_semantics():
    parser=RpcEvents()
    assert parser.interpret({'type':'message_update','assistantMessageEvent':{'type':'text_delta','delta':'good'}})==('text','good')
    assert parser.interpret({'type':'agent_settled'})==('done','agent_settled')
    assert parser.interpret({'type':'extension_ui_request','id':'x','method':'confirm'})[0]=='extension_dialog'
    assert parser.interpret({'type':'response','command':'prompt','success':True,'data':{'disposition':'handled'}})==('done','')
    assert parser.interpret({'type':'response','command':'get_state','success':True,'data':{'model':{'provider':'openai-codex','id':'example'}}})==('model',('openai-codex','example'))
    assert parser.interpret({'type':'response','command':'prompt','success':False,'error':'no auth'})==('error','no auth')


def test_endpoint_and_redaction():
    assert endpoint('ollama')=='http://127.0.0.1:11434'
    with pytest.raises(ValueError):endpoint('custom','http://malicious.example.com')
    with pytest.raises(ValueError):endpoint('custom','https://test:pass@example.com')
    assert 'secret' not in redact('Authorization: Bearer secret').lower()
    # macOS resolves /tmp to /private/tmp; compare canonical locations.
    assert checked_child(Path('/tmp/root'), Path('/tmp/root/file')) == Path('/tmp/root/file').resolve()
    with pytest.raises(ValueError):checked_child(Path('/tmp/root'),Path('/tmp/root/../private'))


def test_api_provider_requires_key_without_network():
    with pytest.raises(ValueError,match='No API key'):
        request_chat('openai','example',[{'role':'user','content':'hello'}])


def test_local_judge_offline_candidates():
    assert profiles({'models':[]})==[]
    found=profiles({'models':[{'name':'small','size':1},{'name':'medium','size':2},{'name':'big','size':3}]})
    assert [m['name'] for m in found]==['small','medium','big']


def test_plugin_install_refresh_and_rollback(tmp_path):
    stage=tmp_path/'stage';stage.mkdir()
    manifest={'api_version':'1.0','id':'example_analysis','name':'Example analysis',
              'entrypoint':'module:run','requires':['numpy'],'mode':'analysis','parameters':{}}
    (stage/'module.json').write_text(json.dumps(manifest))
    (stage/'module.py').write_text('def run(ctx):\n    return None\n')
    assert preflight(stage)[0].id=='example_analysis'
    root=tmp_path/'user_scripts'
    assert install_staged(stage,root)=='example_analysis'
    mods,issues=discover_modules([root]);assert 'example_analysis' in mods,issues
    with pytest.raises(FileExistsError):install_staged(stage,root)
    backup=remove_installed('example_analysis',root)
    mods,_=discover_modules([root]);assert 'example_analysis' not in mods
    assert (backup/'module.json').exists()


def test_plugin_rejects_symlinks_and_invalid_syntax(tmp_path):
    stage=tmp_path/'plugin';stage.mkdir()
    (stage/'module.json').write_text(json.dumps({'api_version':'1.0','id':'plugin_test','name':'Test'}))
    (stage/'module.py').write_text('def run(ctx):\n  return ((\n')
    with pytest.raises(SyntaxError):preflight(stage)
    (stage/'module.py').write_text('def run(ctx):\n return 1\n')
    (stage/'outside.py').symlink_to('/etc/passwd')
    with pytest.raises(ValueError,match='symlinks'):preflight(stage)
