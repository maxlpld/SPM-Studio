"""v0.8.2: guided Pi setup, local Judge, Claude Code / Codex backends, Windows/macOS helpers.

Runs without Qt, network, credentials or hardware: a fake Pi CLI (Node script) and
a fake Ollama HTTP server stand in for the real programs.
"""
import json
import shutil
import stat
import tarfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from spm_studio.ai import platform_util as pu
from spm_studio.ai import pi_setup, judge, config
from spm_studio.ai.cli_events import CliEvents, build_args
from spm_studio.ai.judge_proxy import JudgeProxy, to_native

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')

FAKE_PI = r"""#!/usr/bin/env node
const fs=require('fs'),path=require('path'),os=require('os');
const dir=process.env.PI_CODING_AGENT_DIR||path.join(os.homedir(),'.pi','agent');
const a=process.argv.slice(2);
const read=f=>{try{return JSON.parse(fs.readFileSync(path.join(dir,f),'utf8'))}catch(e){return {}}};
if(a[0]==='--version'){console.log('1.5.2');process.exit(0)}
if(a[0]==='install'){fs.mkdirSync(dir,{recursive:true});const s=read('settings.json');
  s.packages=(s.packages||[]).concat([a[1]]);fs.writeFileSync(path.join(dir,'settings.json'),JSON.stringify(s));process.exit(0)}
if(a[0]==='--list-models'){const auth=read('auth.json');
  console.log('provider      model              context  max-out  thinking  images');
  if(auth.openai){console.log('openai        gpt-test-mini      400K     128K     yes       yes');
                  console.log('openai        gpt-test-large     400K     128K     yes       yes');}
  process.exit(0)}
if(a.includes('-p')){const s=read('settings.json');if(!s.defaultModel){console.error('No model configured');process.exit(1)}
  console.log('SPM OK '+s.defaultProvider+'/'+s.defaultModel);process.exit(0)}
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated HOME + XDG dirs; a sentinel ~/.pi that must never change."""
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    for var, sub in (('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache')):
        monkeypatch.setenv(var, str(tmp_path / sub))
    personal = tmp_path / 'home' / '.pi' / 'agent'
    personal.mkdir(parents=True)
    (personal / 'settings.json').write_text('{"defaultModel": "personal-model"}')
    return tmp_path


def _install_fake_pi():
    pkg = pi_setup.package_dir()
    (pkg / 'dist').mkdir(parents=True)
    (pkg / 'package.json').write_text(json.dumps({'name': pi_setup.PI_PACKAGE, 'version': '1.5.2',
                                                  'bin': {'pi': 'dist/cli.js'}}))
    (pkg / 'dist' / 'cli.js').write_text(FAKE_PI)
    return pi_setup.managed_pi_entry()


# ------------------------------------------------------------------ platform helpers
def test_version_and_node_release_selection():
    assert pu.parse_version('v22.19.0') == (22, 19, 0)
    index = [{'version': 'v25.1.0', 'lts': False, 'files': ['linux-x64', 'osx-arm64-tar', 'win-x64-zip']},
             {'version': 'v24.11.1', 'lts': 'Krypton', 'files': ['linux-x64', 'osx-arm64-tar', 'win-x64-zip']},
             {'version': 'v22.18.0', 'lts': 'Jod', 'files': ['linux-x64']}]
    assert pi_setup.pick_node_release(index, 'linux-x64') == 'v24.11.1'
    assert pi_setup.pick_node_release(index, 'darwin-arm64') == 'v24.11.1'
    assert pi_setup.pick_node_release(index, 'win-x64') == 'v24.11.1'
    with pytest.raises(RuntimeError):
        pi_setup.pick_node_release(index[2:], 'linux-x64')        # 22.18 is below Pi's minimum


def test_archive_extraction_rejects_traversal(tmp_path):
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr('../evil.txt', 'x')
    with pytest.raises(RuntimeError):
        pi_setup._safe_extract(bad, tmp_path / 'out')
    assert not (tmp_path / 'evil.txt').exists()
    good = tmp_path / 'node.tar.gz'
    src = tmp_path / 'node-v1-linux-x64' / 'bin'
    src.mkdir(parents=True)
    (src / 'node').write_text('x')
    with tarfile.open(good, 'w:gz') as t:
        t.add(src.parent, arcname='node-v1-linux-x64')
    pi_setup._safe_extract(good, tmp_path / 'ok')
    assert (tmp_path / 'ok' / 'node-v1-linux-x64' / 'bin' / 'node').is_file()


def test_windows_cmd_shim_is_resolved_to_node_entry(tmp_path):
    bin_dir = tmp_path / 'npm'
    target = bin_dir / 'node_modules' / '@earendil-works' / 'pi-coding-agent' / 'dist' / 'cli.js'
    target.parent.mkdir(parents=True)
    target.write_text('// js')
    shim = bin_dir / 'pi.cmd'
    shim.write_text('@ECHO off\r\nGOTO start\r\n:start\r\nSETLOCAL\r\nSET dp0=%~dp0\r\n'
                    'IF EXIST "%dp0%\\node.exe" (SET "_prog=%dp0%\\node.exe") ELSE (SET "_prog=node")\r\n'
                    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
                    '"%dp0%\\node_modules\\@earendil-works\\pi-coding-agent\\dist\\cli.js" %*\r\n')
    assert pu._shim_target(shim) == target.resolve()


def test_resolve_command_runs_js_and_shebang_scripts_with_node(tmp_path):
    js = tmp_path / 'cli.js'
    js.write_text(FAKE_PI)
    program, prefix = pu.resolve_command(str(js))
    assert prefix == [str(js)]
    if not pu.IS_WINDOWS:
        link_dir = tmp_path / '.bin'
        link_dir.mkdir()
        (link_dir / 'pi').symlink_to(js)
        program2, prefix2 = pu.resolve_command(str(link_dir / 'pi'))
        assert prefix2 == [str(js.resolve())]
    with pytest.raises(FileNotFoundError):
        pu.resolve_command(str(tmp_path / 'missing'))


def test_terminal_scripts_are_readable_and_quoted(tmp_path):
    script = pu.write_terminal_script(tmp_path, 'demo', {'PI_CODING_AGENT_DIR': str(tmp_path / "a b")},
                                      ['node', str(tmp_path / 'x y' / 'cli.js')], 'Line one\nLine two')
    text = script.read_text()
    assert 'PI_CODING_AGENT_DIR' in text and 'Line two' in text
    if not pu.IS_WINDOWS:
        assert script.stat().st_mode & stat.S_IXUSR


def test_hardware_report_never_raises():
    hw = pu.hardware()
    assert hw['os'] in ('Linux', 'macOS', 'Windows')
    assert 'gpu' in hw and 'ram_bytes' in hw
    assert isinstance(judge.describe_hardware(hw), str)


# ------------------------------------------------------------------ private Pi setup
def test_auth_store_is_private_and_never_returns_secrets(home):
    pi_setup.set_api_key('openai', 'sk-test-ABCDEFGHIJKLMNOP')
    path = pi_setup.agent_dir() / 'auth.json'
    if not pu.IS_WINDOWS:
        assert path.stat().st_mode & 0o077 == 0
    assert pi_setup.auth_status() == {'openai': 'api_key'}
    assert 'sk-test' not in json.dumps(pi_setup.auth_status())
    with pytest.raises(ValueError):
        pi_setup.set_api_key('openai', 'has spaces in it')
    with pytest.raises(ValueError):
        pi_setup.set_api_key('../evil', 'sk-x')
    pi_setup.remove_auth('openai')
    assert pi_setup.auth_status() == {}
    # the personal Pi folder was not touched
    assert json.loads((home / 'home/.pi/agent/settings.json').read_text()) == {'defaultModel': 'personal-model'}
    assert not (home / 'home/.pi/agent/auth.json').exists()


def test_list_models_parser():
    text = ('provider      model              context  max-out  thinking  images\n'
            'openai        gpt-x              400K     128K     yes       yes\n'
            '─────────────────────────\n'
            'anthropic     claude-y           200K     64K      yes       yes\n'
            'openai        gpt-x              400K     128K     yes       yes\n')
    assert pi_setup.parse_list_models(text) == [{'provider': 'openai', 'id': 'gpt-x'},
                                                {'provider': 'anthropic', 'id': 'claude-y'}]


def test_router_config_matches_documented_schema():
    cfg = pi_setup.router_config([('openai', 'fast-a'), ('deepseek', 'fast-b')], [('anthropic', 'smart')],
                                 'local', 'qwen3.5:2b', 'eco', orchestration=True)
    assert cfg['tiers']['fast']['models'][1] == {'provider': 'deepseek', 'model': 'fast-b', 'priority': 2}
    assert cfg['routing']['mode'] == 'auto'
    assert cfg['routing']['judge'] == {'mode': 'custom', 'models': [
        {'provider': pi_setup.LOCAL_PROVIDER, 'model': 'qwen3.5:2b', 'priority': 1}]}
    assert cfg['routing']['economics']['mode'] == 'eco'
    assert cfg['orchestration']['mode'] == 'auto'
    cloud = pi_setup.router_config([('a', 'b')], [('c', 'd')], 'cloud', economics='default')
    assert cloud['routing']['judge']['mode'] == 'fast-chain'
    with pytest.raises(ValueError):
        pi_setup.router_config([], [('c', 'd')], 'cloud')
    with pytest.raises(ValueError):
        pi_setup.router_config([('a', 'b')], [('c', 'd')], 'cloud', economics='balanced')


def test_apply_configuration_only_writes_private_agent_dir(home):
    summary = pi_setup.apply_configuration([('openai', 'fast')], [('anthropic', 'smart')], 'local', 'qwen3.5:0.8b',
                                           'eco', use_router=True, orchestration=False, port=12345)
    d = pi_setup.agent_dir()
    assert summary['default'] == 'openai/fast' and summary['router']
    models = json.loads((d / 'models.json').read_text())
    assert models['providers'][pi_setup.LOCAL_PROVIDER]['baseUrl'] == 'http://127.0.0.1:12345/v1'
    assert 'ollama' not in models['providers']                    # never shadows a user "ollama" provider
    assert pi_setup.set_judge_port(23456)
    assert '23456' in (d / 'models.json').read_text()
    assert pi_setup.read_router_summary()['judge'] == pi_setup.LOCAL_PROVIDER + '/qwen3.5:0.8b'
    pi_setup.apply_configuration([('openai', 'fast')], [('openai', 'fast')], 'none', '', 'eco',
                                 use_router=False, orchestration=False)
    assert not (d / 'pi-shift-router.json').exists() and (d / 'pi-shift-router.json.disabled').exists()
    assert json.loads((home / 'home/.pi/agent/settings.json').read_text()) == {'defaultModel': 'personal-model'}


@pytest.mark.skipif(not NODE or pu.node_version(NODE) is None or pu.node_version(NODE) < pu.NODE_MIN,
                    reason='Node.js 22.19+ needed to run the fake Pi CLI')
def test_end_to_end_with_fake_pi_cli(home):
    entry = _install_fake_pi()
    assert entry is not None and pi_setup.managed_pi_version() == '1.5.2'
    assert pi_setup.pi_version() == '1.5.2'
    logs = []
    assert pi_setup.install_extension(pi_setup.ROUTER_PACKAGE, logs.append)
    assert pi_setup.install_extension(pi_setup.SUBAGENTS_PACKAGE, logs.append)
    assert pi_setup.installed_packages() == [pi_setup.ROUTER_PACKAGE, pi_setup.SUBAGENTS_PACKAGE]
    assert pi_setup.list_models() == []                            # no account yet
    pi_setup.set_api_key('openai', 'sk-fake-0123456789')
    assert {'provider': 'openai', 'id': 'gpt-test-mini'} in pi_setup.list_models()
    ok, text = pi_setup.smoke_test()
    assert not ok and 'No model' in text
    pi_setup.apply_configuration([('openai', 'gpt-test-mini')], [('openai', 'gpt-test-large')], 'cloud', '',
                                 'default', use_router=True, orchestration=True)
    ok, text = pi_setup.smoke_test()
    assert ok and 'openai/gpt-test-mini' in text
    script = pi_setup.login_script('openai-codex')
    assert '/login openai-codex' in script.read_text() and str(pi_setup.agent_dir()) in script.read_text()
    # config.detect_pi never offers SPM's private Pi as the user's "existing" Pi
    assert all(not pi_setup.is_managed(p) for p in config.detect_pi())
    assert str(entry) in config.detect_pi(include_managed=True)
    assert json.loads((home / 'home/.pi/agent/settings.json').read_text()) == {'defaultModel': 'personal-model'}


# ------------------------------------------------------------------ judge
def test_recommendations_are_hardware_aware():
    cat = {'models': judge.CATALOG}
    gib = 1024 ** 3
    big_gpu = judge.recommend({'gpu_memory_bytes': 12 * gib, 'ram_bytes': 32 * gib}, cat)
    assert [m['tag'] for m in big_gpu['profiles'].values()] == ['qwen3.5:0.8b', 'qwen3.5:2b', 'qwen3.5:9b']
    assert all(m['runs_on'] == 'GPU' for m in big_gpu['profiles'].values())
    cpu = judge.recommend({'gpu_memory_bytes': None, 'ram_bytes': 16 * gib}, cat)
    assert [m['tag'] for m in cpu['profiles'].values()] == ['qwen3.5:0.8b', 'qwen3.5:2b', 'qwen3.5:4b']
    assert any('CPU' in n for n in cpu['notes'])
    tiny = judge.recommend({'gpu_memory_bytes': None, 'ram_bytes': 4 * gib}, cat)
    assert list(tiny['profiles']) == ['fastest'] and any('Only 1' in n for n in tiny['notes'])


def test_catalog_falls_back_offline(home, monkeypatch):
    def offline(tag, timeout=6):
        raise OSError('offline')
    monkeypatch.setattr(judge, 'registry_size', offline)
    cat = judge.catalog(refresh=True)
    assert cat['source'] == 'builtin' and len(cat['models']) == len(judge.CATALOG)
    monkeypatch.setattr(judge, 'registry_size', lambda tag, timeout=6: 1_000_000_000)
    cat = judge.catalog(refresh=True)
    assert cat['source'] == 'registry' and cat['models'][0]['download_bytes'] == 1_000_000_000
    assert judge.catalog()['source'] == 'cache'


class _FakeOllama(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, data, code=200):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/api/tags':
            return self._send({'models': [{'name': 'qwen3.5:0.8b', 'size': 1_000_000_000}]})
        if self.path == '/api/version':
            return self._send({'version': '0.13.0'})
        self._send({}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        _FakeOllama.seen.append((self.path, body))
        prompt = json.dumps(body)
        tier = 'Smart' if 'multi-file' in prompt.split('Task:')[-1] else 'Fast'
        answer = json.dumps({'tier': tier, 'confidence': 0.9, 'reason': 'test'})
        if self.path == '/api/chat' and body.get('stream'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson')
            self.end_headers()
            for piece in (answer[:10], answer[10:]):
                self.wfile.write(json.dumps({'message': {'content': piece}, 'done': False}).encode() + b'\n')
            self.wfile.write(json.dumps({'message': {'content': ''}, 'done': True,
                                         'prompt_eval_count': 5, 'eval_count': 7}).encode() + b'\n')
            return
        if self.path == '/api/chat':
            return self._send({'message': {'content': answer}, 'done': True})
        if self.path == '/api/generate':
            return self._send({'response': answer})
        self._send({}, 404)


@pytest.fixture
def fake_ollama():
    server = ThreadingHTTPServer(('127.0.0.1', 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _FakeOllama.seen.clear()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()


def test_judge_proxy_disables_thinking_and_translates(fake_ollama):
    proxy = JudgeProxy(upstream=fake_ollama, port=0).start()
    try:
        results = judge.benchmark('qwen3.5:0.8b', proxy.base_v1)
        assert [r['tier'] for r in results] == ['Fast', 'Smart'] and all(r['correct'] for r in results)
        native = [b for p, b in _FakeOllama.seen if p == '/api/chat']
        assert native and all(b['think'] is False and b.get('format') == 'json' for b in native)
        # streaming translation (what the router uses)
        from urllib.request import Request, urlopen
        req = Request(proxy.base_v1 + '/chat/completions', method='POST', headers={'Content-Type': 'application/json'},
                      data=json.dumps({'model': 'qwen3.5:0.8b', 'stream': True,
                                       'messages': [{'role': 'developer', 'content': [{'type': 'text', 'text': 'hi'}]}]}).encode())
        with urlopen(req, timeout=10) as r:
            body = r.read().decode()
        chunks = [json.loads(x[6:]) for x in body.split('\n\n') if x.startswith('data: {')]
        text = ''.join(c['choices'][0]['delta'].get('content', '') for c in chunks)
        assert json.loads(text)['tier'] == 'Fast' and body.rstrip().endswith('data: [DONE]')
        assert chunks[-1]['choices'][0]['finish_reason'] == 'stop' and chunks[-1]['usage']['total_tokens'] == 12
        with urlopen(proxy.base_v1 + '/models', timeout=5) as r:
            assert json.load(r)['data'][0]['id'] == 'qwen3.5:0.8b'
    finally:
        proxy.stop()
    assert to_native({'model': 'm', 'messages': [{'role': 'tool', 'content': 'x'}]})['messages'] == []
    assert judge.classify('What is 2+2?', 'qwen3.5:0.8b', base=fake_ollama)['tier'] == 'Fast'
    assert _FakeOllama.seen[-1][1]['think'] is False
    assert judge.ollama_running(fake_ollama) == '0.13.0'
    assert judge.installed_models(fake_ollama)[0]['name'] == 'qwen3.5:0.8b'


# ------------------------------------------------------------------ claude code / codex
def test_claude_code_stream_parsing_and_args():
    p = CliEvents('claude-code')
    out = p.interpret({'type': 'system', 'subtype': 'init', 'session_id': 's1', 'model': 'claude-x'})
    assert ('session', 's1') in out and ('model', 'claude-x') in out
    assert p.interpret({'type': 'stream_event', 'event': {'type': 'content_block_delta',
                                                          'delta': {'type': 'text_delta', 'text': 'Hel'}}}) == [('text', 'Hel')]
    assert p.interpret({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Hello'}]}}) == [('text', '\n\n')]
    assert p.interpret({'type': 'result', 'subtype': 'success', 'result': 'Hello', 'session_id': 's1'})[-1] == ('done', 'result')
    q = CliEvents('claude-code')       # no partial messages: full text exactly once
    assert q.interpret({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Hi'}]}}) == [('text', 'Hi')]
    assert ('replace', 'Hi') not in q.interpret({'type': 'result', 'subtype': 'success', 'result': 'Hi'})
    err = CliEvents('claude-code').interpret({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True})
    assert err[0][0] == 'error'
    args = build_args('claude-code', 's1', False, 'ctx')
    assert args[:3] == ['-p', '--output-format', 'stream-json'] and '--resume' in args and 'plan' in args
    assert 'acceptEdits' in build_args('claude-code', '', True)


def test_codex_jsonl_parsing_and_args():
    p = CliEvents('codex')
    assert p.interpret({'type': 'thread.started', 'thread_id': 't1'}) == [('session', 't1')]
    assert p.interpret({'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'ls'}})[0][0] == 'activity'
    assert p.interpret({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Done'}}) == [('text', 'Done')]
    assert p.interpret({'type': 'item.completed', 'item': {'item_type': 'assistant_message', 'text': 'More'}}) == [('text', '\n\nMore')]
    assert p.interpret({'type': 'turn.completed', 'usage': {}}) == [('done', 'turn.completed')]
    assert p.interpret({'type': 'turn.failed', 'error': {'message': 'quota'}})[0] == ('error', 'quota')
    fresh = build_args('codex', '', False)
    assert fresh == ['exec', '--json', '--skip-git-repo-check', '--sandbox', 'read-only', '-']
    resumed = build_args('codex', 't1', True)
    assert resumed[:3] == ['exec', 'resume', 't1'] and resumed[-1] == '-' and 'sandbox_mode="workspace-write"' in resumed


def test_config_accepts_agent_backends(home):
    s = config.load()
    assert s['pi_managed'] is False and s['judge_proxy_port'] == 11436
    for backend in ('claude-code', 'codex'):
        s['backend'] = backend
        config.save(s)
        assert config.load()['backend'] == backend
    assert 'claude-code' not in config.PROVIDERS


# ------------------------------------------------------------------ installers & release hygiene
def test_platform_installers_present_and_safe():
    ps1 = (ROOT / 'install_spm_studio_windows.ps1').read_text(encoding='utf8')
    mac = (ROOT / 'install_spm_studio_macos.sh').read_text(encoding='utf8')
    for text in (ps1, mac):
        assert '--smoke-test' in text and 'pip install' in text
        assert 'Remove-Item -Recurse -Force $HOME' not in text and 'rm -rf "$HOME"' not in text
    assert 'Administrator' in ps1                      # refuses elevated runs
    assert 'EUID' in mac and 'timeout 45' not in mac   # no GNU timeout on macOS
    assert (ROOT / 'install_spm_studio_windows.bat').is_file()
    assert (ROOT / 'uninstall_spm_studio_windows.ps1').is_file() and (ROOT / 'uninstall_spm_studio_macos.sh').is_file()


def test_release_tree_contains_no_secrets_or_private_state():
    import re
    pattern = re.compile(r'(sk-(?=[A-Za-z0-9_-]*\d)(?:ant-|or-v1-|proj-)?[A-Za-z0-9_-]{24,}|AIza[0-9A-Za-z_-]{30,}|ghp_[A-Za-z0-9]{30,}'
                         r'|xox[bpa]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY)')
    hits = []
    for p in ROOT.rglob('*'):
        if not p.is_file() or p.suffix in ('.otf', '.png', '.ico', '.icns', '.pyc') or '.git' in p.parts:
            continue
        if p.name in ('auth.json', '.env') or p.suffix in ('.pem', '.key', '.sqlite', '.db'):
            hits.append(str(p))
            continue
        try:
            text = p.read_text(encoding='utf8', errors='ignore')
        except OSError:
            continue
        hits += [f'{p}: {m}' for m in pattern.findall(text)]
    assert not hits, hits
