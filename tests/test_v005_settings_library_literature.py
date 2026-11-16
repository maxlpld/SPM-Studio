"""SPM Studio 0.0.5: Settings window, library import/export, folder guides, export profiles,
literature sources (Zotero / Consensus) and the interface clean-up.

The first part needs no Qt. The GUI part runs when PySide6 is installed (offscreen).
"""
import io
import json
import os
import re
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Disposable SPM Studio folders (config, data, cache)."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    from spm_studio.core import paths
    paths.install_factory_modules()
    paths.install_factory_customization()
    return tmp_path


# ------------------------------------------------------------------------- guides
def test_every_folder_gets_a_guide_and_user_edits_are_kept(home):
    from spm_studio.core import paths
    notes = paths.ensure_guides()
    assert notes
    custom = paths.customization_dir()
    for folder in ('profiles', 'export_presets', 'themes', 'colormaps', 'plot_styles', 'shortcuts'):
        guide = custom / folder / 'README.md'
        assert guide.is_file(), folder
        assert paths.guide_for(custom / folder) == guide
    scripts_guide = paths.scripts_dir() / 'README.md'
    assert scripts_guide.is_file() and (paths.scripts_dir() / 'README_SCRIPT.md').is_file()
    assert 'README.md' in scripts_guide.read_text(encoding='utf8')
    assert paths.ensure_guides() == []                      # nothing to do the second time
    scripts_guide.write_text('my own notes\n', encoding='utf8')
    paths.ensure_guides()
    assert scripts_guide.read_text(encoding='utf8') == 'my own notes\n'
    # A guide is not a tool, a profile or a colormap: discovery still works.
    from spm_studio.core.registry import discover_modules
    mods, problems = discover_modules([paths.scripts_dir()])
    assert 'cpd_histogram' in mods and not problems


def _json_blocks(path):
    return [json.loads(b) for b in re.findall(r'```json\n(.*?)```', Path(path).read_text(encoding='utf8'), re.S)]


def test_examples_in_the_guides_are_valid():
    from spm_studio.core.presets import validate_profile, validate_export, validate_theme
    from spm_studio.core.plot_settings import validate_plot
    custom = ROOT / 'customization'
    profiles = _json_blocks(custom / 'profiles' / 'README.md')
    assert profiles and all(validate_profile(b) for b in profiles)
    exports = [validate_export(b) for b in _json_blocks(custom / 'export_presets' / 'README.md')]
    assert any('layout' in e and len(e['layout']['panels']) == 4 for e in exports)
    assert all(validate_theme(b) for b in _json_blocks(custom / 'themes' / 'README.md'))
    assert all(validate_plot(b) for b in _json_blocks(custom / 'plot_styles' / 'README.md'))
    # Every processing operation named in the profile guide exists.
    import numpy as np
    from spm_studio.core.models import ProcessingStep
    from spm_studio.core.processing import apply
    text = (custom / 'profiles' / 'README.md').read_text(encoding='utf8')
    table = text[text.index('| Group | Operations |'):text.index('Use only these names')]
    operations = set(re.findall(r'`([a-z_0-9]+)`', table)) - {'degree', 'threshold_', 'sigma', 'sigma2', 'size',
                                                              'amount', 'factor', 'value', 'low', 'high'}
    operations |= {'threshold'}
    assert {'plane', 'row_median', 'fix_zero', 'median_scar', 'gaussian'} <= operations
    image = np.random.default_rng(0).normal(size=(24, 24))
    for name in sorted(operations):
        apply(image, [ProcessingStep(name, {}, True)])


def test_every_bundled_tool_has_a_readme():
    from spm_studio.core import paths
    for manifest in sorted((ROOT / 'scripts').glob('*/module.json')):
        assert paths.module_readme(manifest.parent) is not None, manifest.parent.name
    assert paths.module_readme(ROOT / 'scripts' / 'cpd_histogram' / 'module.json').name == 'README.md'


def test_assistant_context_points_at_the_guides_and_requires_a_readme(home):
    from spm_studio.ai.config import spm_context_file
    from spm_studio.core import paths
    text = spm_context_file(paths.scripts_dir()).read_text(encoding='utf8')
    assert 'Read the guide of a folder BEFORE you create or change anything in it' in text
    for folder in ('profiles', 'export_presets', 'themes', 'colormaps', 'plot_styles', 'shortcuts'):
        assert str(paths.customization_dir() / folder / 'README.md') in text
    assert str(paths.scripts_dir() / 'README.md') in text
    assert 'Every tool folder must contain a `README.md`' in text
    assert 'Literature sources' not in text                  # nothing connected yet


# ----------------------------------------------------------------------- profiles
def test_only_one_kpfm_profile_remains(home):
    from spm_studio.core import paths
    profiles = paths.customization_dir() / 'profiles'
    old = profiles / 'KPFM.json'
    old.write_text(json.dumps({'schema_version': 1, 'name': 'KPFM', 'channel_contains': 'Bias'}), encoding='utf8')
    duplicate = profiles / 'KPFM_v7.json'
    duplicate.write_text((ROOT / 'customization' / 'profiles' / 'KPFM.json').read_text(encoding='utf8'), encoding='utf8')
    notes = paths.cleanup_kpfm_profiles_v005()
    assert notes and not duplicate.exists()
    kept = json.loads(old.read_text(encoding='utf8'))
    assert kept['name'] == 'KPFM' and kept['visible_channels'] == ['Z', 'Bias']
    backup = profiles / '.profile_backups_v005'
    assert (backup / 'KPFM_previous.json').is_file() and (backup / 'KPFM_v7.json').is_file()
    assert paths.cleanup_kpfm_profiles_v005() == []          # once
    assert sorted(p.stem for p in profiles.glob('KPFM*.json')) == ['KPFM']


def test_fresh_installation_never_creates_a_second_kpfm_profile(home):
    from spm_studio.core import paths
    paths.upgrade_factory_profiles_v7()
    paths.cleanup_kpfm_profiles_v005()
    assert sorted(p.stem for p in (paths.customization_dir() / 'profiles').glob('KPFM*.json')) == ['KPFM']


# ------------------------------------------------------------------------ library
def test_library_lists_exports_imports_and_removes(home, tmp_path):
    from spm_studio.core import library, paths
    assert {'scripts', 'profiles', 'exports', 'themes', 'colormaps', 'plots', 'shortcuts'} == set(library.KINDS)
    names = {i.name for i in library.list_items('profiles')}
    assert {'KPFM.json', 'STM.json'} <= names and 'README.md' not in names
    assert all(i.valid for i in library.list_items('profiles'))
    tools = {i.name: i for i in library.list_items('scripts')}
    assert 'cpd_histogram' in tools and tools['cpd_histogram'].is_dir and 'README.md' not in tools

    # export two profiles and a tool, as single files to send to a colleague
    pack = library.export_items('profiles', ['KPFM.json', 'STM.json'], tmp_path / 'out' / 'mine')
    assert pack.name == 'mine.zip'
    manifest = library.read_pack_manifest(pack)
    assert manifest['kind'] == 'profiles' and manifest['items'] == ['KPFM.json', 'STM.json']
    tool_pack = library.export_items('scripts', ['cpd_histogram'], tmp_path / 'tool.zip')
    with zipfile.ZipFile(tool_pack) as z:
        assert 'items/cpd_histogram/module.json' in z.namelist()
        assert not any('__pycache__' in n for n in z.namelist())

    # importing what is already there asks first; "rename" keeps both, "replace" backs up
    with pytest.raises(library.ConflictError) as conflict:
        library.import_path('profiles', pack)
    assert conflict.value.names == ['KPFM.json', 'STM.json']
    copies = library.import_path('profiles', pack, on_conflict='rename')
    assert [p.name for p in copies] == ['KPFM_2.json', 'STM_2.json']
    library.import_path('profiles', pack, on_conflict='replace')
    assert any(library.trash_dir().rglob('KPFM.json'))

    # a pack is refused in the wrong section, and nothing is installed
    with pytest.raises(library.LibraryError):
        library.import_path('themes', pack)

    # remove = move away (recoverable), and a removed factory file does not come back
    moved = library.remove_item('profiles', 'Multipass.json')
    assert moved.is_file() and not (paths.customization_dir() / 'profiles' / 'Multipass.json').exists()
    paths.install_factory_customization()
    assert not (paths.customization_dir() / 'profiles' / 'Multipass.json').exists()
    assert 'profiles/Multipass.json' in paths.removed_factory_items()
    # importing it again lifts the tombstone
    library.import_path('profiles', ROOT / 'customization' / 'profiles' / 'Multipass.json')
    assert 'profiles/Multipass.json' not in paths.removed_factory_items()

    # tools: remove, then install again from the pack
    library.remove_item('scripts', 'cpd_histogram')
    assert 'cpd_histogram' not in {i.name for i in library.list_items('scripts')}
    installed = library.import_path('scripts', tool_pack)
    assert installed[0].name == 'cpd_histogram' and (installed[0] / 'module.py').is_file()


def test_library_validates_before_installing(home, tmp_path):
    from spm_studio.core import library
    bad = tmp_path / 'broken.json'
    bad.write_text('{"schema_version": 2}', encoding='utf8')
    with pytest.raises(library.LibraryError):
        library.import_path('profiles', bad)
    assert not (library.kind_dir('profiles') / 'broken.json').exists()
    # a folder of files, and a tool folder given as a folder or by its module.json
    folder = tmp_path / 'many'
    folder.mkdir()
    for name in ('a_theme.json', 'b_theme.json'):
        (folder / name).write_text(json.dumps({'schema_version': 1, 'accent': '#112233'}), encoding='utf8')
    assert len(library.import_path('themes', folder)) == 2
    tool = tmp_path / 'my_tool'
    tool.mkdir()
    (tool / 'module.json').write_text(json.dumps({
        'api_version': '1.0', 'id': 'my_tool', 'name': 'My tool', 'version': '1.0.0', 'description': 'd',
        'category': 'Examples', 'mode': 'analysis', 'status': 'experimental', 'entrypoint': 'module:run',
        'interaction': 'none', 'snapshot_channels': 'selected', 'requires': [], 'parameters': {}}), encoding='utf8')
    (tool / 'module.py').write_text('def run(ctx):\n    ctx.log("hi")\n', encoding='utf8')
    (tool / 'README.md').write_text('# My tool\n', encoding='utf8')
    assert library.detect_kind(tool) == 'scripts'
    assert library.import_path('scripts', tool / 'module.json')[0].name == 'my_tool'
    (tool / 'module.py').write_text('def run(ctx:\n', encoding='utf8')
    with pytest.raises(library.LibraryError):
        library.import_path('scripts', tool, on_conflict='rename')
    # Python is never executed on import: a module with side effects stays inert.
    marker = tmp_path / 'executed'
    (tool / 'module.py').write_text(f'open({str(marker)!r}, "w").write("x")\ndef run(ctx):pass\n', encoding='utf8')
    library.import_path('scripts', tool, on_conflict='rename')
    assert not marker.exists()


def test_pack_with_unsafe_paths_is_refused(home, tmp_path):
    from spm_studio.core import library
    evil = tmp_path / 'evil.zip'
    with zipfile.ZipFile(evil, 'w') as z:
        z.writestr(library.PACK_MANIFEST, json.dumps({'format': library.PACK_FORMAT, 'kind': 'themes',
                                                     'items': ['x.json']}))
        z.writestr('items/x.json', json.dumps({'schema_version': 1}))
        z.writestr('items/../../escaped.json', '{}')
    with pytest.raises(library.LibraryError):
        library.import_pack(evil)
    assert not (tmp_path / 'escaped.json').exists()
    with pytest.raises(library.LibraryError):
        library.import_path('themes', ROOT / 'pyproject.toml')
    not_a_pack = tmp_path / 'plain.zip'
    with zipfile.ZipFile(not_a_pack, 'w') as z:
        z.writestr('a.txt', 'x')
    with pytest.raises(library.LibraryError):
        library.import_path('themes', not_a_pack)


def test_library_edit_and_duplicate(home):
    from spm_studio.core import library
    text = library.read_text('profiles', 'STM.json')
    data = json.loads(text)
    data['visible_channels'] = ['Z', 'Current']
    saved = library.save_text('profiles', 'STM.json', json.dumps(data, indent=2))
    assert json.loads(saved.read_text(encoding='utf8'))['visible_channels'] == ['Z', 'Current']
    assert saved.with_name('STM.json.bak').is_file()
    with pytest.raises(Exception):
        library.save_text('profiles', 'STM.json', '{"schema_version": 1, "style": {"gamma": -1}}')
    assert json.loads(saved.read_text(encoding='utf8'))['visible_channels'] == ['Z', 'Current']   # untouched
    assert not list(library.kind_dir('profiles').glob('check_*')) and not list(library.kind_dir('profiles').glob('*.edit'))
    copy = library.duplicate_item('profiles', 'STM.json', 'STM_gold')
    assert copy.name == 'STM_gold.json' and json.loads(copy.read_text(encoding='utf8'))['name'] == 'STM_gold'
    tool = library.duplicate_item('scripts', 'flake_height', 'flake_height_v2')
    assert json.loads((tool / 'module.json').read_text(encoding='utf8'))['id'] == 'flake_height_v2'
    assert library.editable_file('scripts', 'flake_height_v2').name == 'module.json'


# ----------------------------------------------------------------- export profiles
def test_grid_layout_cells():
    from spm_studio.core.export_layout import layout_cells, grid_shape, MAX_PANELS
    assert grid_shape(6) == (3, 2) and grid_shape(5, 2) == (2, 3) and grid_shape(4, 9) == (4, 1)
    cells = layout_cells(5, 1000, 800, 50, 20, 'grid', 3)
    assert len(cells) == 5
    widths = {round(c[2], 3) for c in cells}
    heights = {round(c[3], 3) for c in cells}
    assert len(widths) == 1 and len(heights) == 1                 # equal panels
    assert cells[0][0] == 50 and round(cells[2][0] + cells[2][2], 6) == 950
    assert cells[3][1] > cells[0][1]
    # the incomplete last row (2 of 3) is centred
    left_gap = cells[3][0] - 50
    right_gap = 950 - (cells[4][0] + cells[4][2])
    assert abs(left_gap - right_gap) < 1e-6 and left_gap > 0
    # older arrangements are unchanged
    assert layout_cells(3, 1000, 900, 50, 20, 'row')[1][0] > layout_cells(3, 1000, 900, 50, 20, 'row')[0][0]
    assert MAX_PANELS == 12


def test_export_profile_keeps_its_figure_layout(home):
    from spm_studio.core.presets import validate_export, write_json, read_json
    from spm_studio.core import paths
    profile = {'schema_version': 1, 'name': 'six', 'width_mm': 178, 'height_mm': 120, 'dpi': 1200,
               'layout': {'arrangement': 'grid', 'columns': 3, 'panel_letters': True, 'formats': ['svg', 'pdf'],
                          'panels': [{'source': 'channel', 'channel': 'Z', 'scan': 'current'}] * 5 +
                                    [{'source': 'result', 'result': 'histogram', 'show_colorbar': False}]}}
    target = paths.customization_dir() / 'export_presets' / 'six.json'
    write_json(target, profile, validate_export)
    back = read_json(target, validate_export)
    assert back['layout']['columns'] == 3 and len(back['layout']['panels']) == 6
    assert back['layout']['panels'][5] == {'source': 'result', 'result': 'histogram', 'show_colorbar': False}
    assert 'layout' not in validate_export({'schema_version': 1})          # plain presets are unchanged
    for bad in ({'arrangement': 'spiral', 'panels': [{}]}, {'panels': []}, {'panels': [{}] * 13},
                {'panels': [{'source': 'webcam'}]}, {'columns': 99, 'panels': [{}]}, {'formats': ['gif'], 'panels': [{}]}):
        with pytest.raises(ValueError):
            validate_export({'schema_version': 1, 'layout': bad})
    from spm_studio.core import library
    assert next(i for i in library.list_items('exports') if i.name == 'six.json').valid


# --------------------------------------------------------------------- literature
class _Zotero(BaseHTTPRequestHandler):
    """Minimal stand-in for Zotero's local API."""
    items = [{'key': 'AAAA1111', 'data': {'key': 'AAAA1111', 'itemType': 'journalArticle',
                                          'title': 'Kelvin probe force microscopy of graphene',
                                          'creators': [{'lastName': 'Meyer'}, {'lastName': 'Glatzel'}],
                                          'date': '2019-03-01', 'publicationTitle': 'Phys. Rev. B',
                                          'DOI': '10.1000/kpfm', 'abstractNote': 'We measure the CPD.',
                                          'tags': [{'tag': 'KPFM'}]}}]
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).requests.append((self.path, dict(self.headers)))
        path = self.path.split('?')[0]
        if 'forbidden' in self.path:
            self.send_response(403); self.end_headers(); return
        if path.endswith('/items/top'):
            body = self.items
        elif path.endswith('/AAAA1111/children'):
            body = [{'data': {'key': 'PDF00001', 'itemType': 'attachment', 'title': 'paper.pdf',
                              'contentType': 'application/pdf'}},
                    {'data': {'key': 'NOTE0001', 'itemType': 'note', 'note': '<p>Check <b>figure 3</b></p>'}}]
        elif path.endswith('/PDF00001/fulltext'):
            body = {'content': 'Full text of the paper. ' * 10}
        elif path.endswith('/items/AAAA1111'):
            body = self.items[0]
        elif path.endswith('/collections'):
            body = [{'key': 'COLL0001', 'data': {'name': 'KPFM papers', 'parentCollection': False}}]
        else:
            self.send_response(404); self.end_headers(); return
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def zotero(monkeypatch):
    server = HTTPServer(('127.0.0.1', 0), _Zotero)
    _Zotero.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    from spm_studio.ai import literature
    monkeypatch.setattr(literature, 'ZOTERO_LOCAL', f'http://127.0.0.1:{server.server_port}/api')
    yield literature
    server.shutdown()
    server.server_close()


def test_zotero_local_library_is_read(zotero):
    conf = {'zotero_mode': 'local'}
    found = zotero.zotero_search('graphene', limit=5, conf=conf)
    assert found == [{'key': 'AAAA1111', 'type': 'journalArticle', 'title': 'Kelvin probe force microscopy of graphene',
                      'creators': 'Meyer, Glatzel', 'year': '2019', 'publication': 'Phys. Rev. B',
                      'doi': '10.1000/kpfm', 'tags': ['KPFM']}]
    path, headers = _Zotero.requests[-1]
    assert '/users/0/items/top' in path and 'q=graphene' in path and 'limit=5' in path
    assert 'Zotero-Api-Key' not in headers and 'Zotero-API-Key' not in headers      # no key for the local app
    item = zotero.zotero_item('AAAA1111', conf=conf)
    assert item['abstract'] == 'We measure the CPD.' and item['notes'] == ['Check  figure 3'] \
        and item['attachments'][0]['key'] == 'PDF00001'
    assert zotero.zotero_collections(conf=conf) == [{'key': 'COLL0001', 'name': 'KPFM papers', 'parent': ''}]
    text = zotero.zotero_fulltext('AAAA1111', max_chars=1000, conf=conf)        # via the item's PDF
    assert text['key'] == 'PDF00001' and text['text'].startswith('Full text') and text['truncated'] is False
    assert zotero.zotero_status(conf)['connected'] is True
    assert zotero.zotero_status({'zotero_mode': 'off'})['connected'] is False


def test_zotero_errors_are_explained(zotero, monkeypatch):
    with pytest.raises(zotero.LiteratureError, match='not connected'):
        zotero.zotero_search('x', conf={'zotero_mode': 'off'})
    with pytest.raises(zotero.LiteratureError, match='library ID'):
        zotero.zotero_search('x', conf={'zotero_mode': 'web', 'zotero_library_id': ''})
    monkeypatch.setattr(zotero, 'zotero_api_key', lambda: '')
    with pytest.raises(zotero.LiteratureError, match='API key'):
        zotero.zotero_search('x', conf={'zotero_mode': 'web', 'zotero_library_id': '123'})
    with pytest.raises(zotero.LiteratureError, match='Allow other applications'):
        zotero.zotero_search('x', conf={'zotero_mode': 'local'}, collection='forbidden')
    monkeypatch.setattr(zotero, 'ZOTERO_LOCAL', 'http://127.0.0.1:9/api')      # nothing listens there
    status = zotero.zotero_status({'zotero_mode': 'local'})
    assert status['connected'] is False and 'Start the Zotero app' in status['message']


def test_zotero_web_api_sends_the_key_only_to_zotero(monkeypatch):
    from spm_studio.ai import literature
    seen = {}

    def fake_get(url, headers, timeout=20, raw=False):
        seen.update(url=url, headers=headers)
        return []
    monkeypatch.setattr(literature, '_get', fake_get)
    monkeypatch.setattr(literature, 'zotero_api_key', lambda: 'SECRETKEY')
    literature.zotero_search('afm', conf={'zotero_mode': 'web', 'zotero_library_id': '4242',
                                          'zotero_library_type': 'group'})
    assert seen['url'].startswith('https://api.zotero.org/groups/4242/items/top?')
    assert seen['headers'] == {'Zotero-API-Key': 'SECRETKEY'}
    assert 'SECRETKEY' not in seen['url']


def test_zotero_mcp_server_and_command_line(zotero, home, capsys):
    from spm_studio.ai.config import load, save
    conf = load()
    conf['zotero_mode'] = 'local'
    save(conf)
    stdin = io.StringIO('\n'.join(json.dumps(m) for m in (
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'zotero_search',
                                                                      'arguments': {'query': 'graphene'}}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'nope', 'arguments': {}}},
        {'jsonrpc': '2.0', 'id': 5, 'method': 'unknown/method'})) + '\nnot json\n')
    stdout = io.StringIO()
    assert zotero.serve_mcp(stdin, stdout) == 0
    answers = [json.loads(line) for line in stdout.getvalue().splitlines()]
    by_id = {a['id']: a for a in answers}
    assert by_id[1]['result']['protocolVersion'] == '2025-06-18' and by_id[1]['result']['serverInfo']['name'] == 'spm-zotero'
    assert [t['name'] for t in by_id[2]['result']['tools']] == ['zotero_search', 'zotero_item', 'zotero_collections',
                                                               'zotero_fulltext']
    assert 'Kelvin probe' in by_id[3]['result']['content'][0]['text'] and by_id[3]['result']['isError'] is False
    assert by_id[4]['result']['isError'] is True
    assert by_id[5]['error']['code'] == -32601 and by_id[None]['error']['code'] == -32700
    assert len(answers) == 6                                   # the notification got no answer
    # every tool is read-only by construction
    assert not any(word in json.dumps(zotero.TOOLS).lower() for word in ('delete', 'create', 'update', 'write'))
    # the same search from the shell, as the agent runs it
    assert zotero.main(['search', 'graphene', '--limit', '3']) == 0
    assert json.loads(capsys.readouterr().out)[0]['key'] == 'AAAA1111'
    assert zotero.main(['status']) == 0 and json.loads(capsys.readouterr().out)['connected'] is True


def test_literature_sources_reach_each_agent(home):
    from spm_studio.ai import literature
    from spm_studio.ai.cli_events import build_args
    from spm_studio.ai.config import load, save, spm_context_file, DEFAULT
    from spm_studio.core import paths
    assert DEFAULT['consensus_enabled'] is False and DEFAULT['zotero_mode'] == 'off'      # opt-in
    assert literature.agent_context(dict(DEFAULT)) == '' and literature.allowed_tools(dict(DEFAULT)) == []
    conf = load()
    conf.update(consensus_enabled=True, zotero_mode='local')
    save(conf)
    assert load()['consensus_enabled'] is True
    text = spm_context_file(paths.scripts_dir()).read_text(encoding='utf8')
    assert 'Literature sources the user connected' in text and 'https://mcp.consensus.app/mcp' in text
    assert '-m spm_studio.ai.literature search' in text and 'never\ninvent' not in text
    assert 'never invent a reference' in text
    # Claude Code: registered once for the user, and callable without a prompt in non-interactive turns
    add = literature.mcp_registration('claude-code', 'claude', literature.CONSENSUS_SERVER)
    assert add == ['claude', 'mcp', 'add', '--scope', 'user', '--transport', 'http', 'consensus',
                   'https://mcp.consensus.app/mcp']
    zot = literature.mcp_registration('claude-code', 'claude', literature.ZOTERO_SERVER)
    assert zot[:7] == ['claude', 'mcp', 'add', '--scope', 'user', 'spm-zotero', '--'] and zot[-3:] == \
        ['-m', 'spm_studio.ai.literature', '--mcp'] and zot[7] == sys.executable
    assert literature.mcp_registration('codex', 'codex', 'consensus') == \
        ['codex', 'mcp', 'add', 'consensus', '--url', 'https://mcp.consensus.app/mcp']
    assert literature.mcp_registration('codex', 'codex', 'consensus', remove=True) == ['codex', 'mcp', 'remove', 'consensus']
    with pytest.raises(ValueError):
        literature.mcp_registration('claude-code', 'claude', 'something-else')
    assert literature.allowed_tools(conf) == ['mcp__consensus', 'mcp__spm-zotero']
    args = build_args('claude-code', '', True, 'ctx', allowed_tools=literature.allowed_tools(conf))
    assert args[args.index('--allowedTools') + 1] == 'mcp__consensus,mcp__spm-zotero'
    assert '--allowedTools' not in build_args('claude-code', '', True, 'ctx')            # default unchanged
    # Pi: merged into its mcp.json, other servers untouched, removed again when switched off
    agent_dir = home / 'pi-agent'
    agent_dir.mkdir()
    (agent_dir / 'mcp.json').write_text(json.dumps({'mcpServers': {'mine': {'url': 'https://example.org/mcp'}},
                                                    'other': 1}), encoding='utf8')
    data = json.loads(literature.write_pi_mcp(agent_dir, conf).read_text(encoding='utf8'))
    assert set(data['mcpServers']) == {'mine', 'consensus', 'spm-zotero'} and data['other'] == 1
    assert data['mcpServers']['consensus'] == {'url': 'https://mcp.consensus.app/mcp'}
    conf.update(consensus_enabled=False, zotero_mode='off')
    assert set(json.loads(literature.write_pi_mcp(agent_dir, conf).read_text(encoding='utf8'))['mcpServers']) == {'mine'}
    # invalid settings are refused, and no key is ever written to the settings file
    conf['zotero_mode'] = 'cloud'
    with pytest.raises(ValueError):
        save(conf)
    from spm_studio.ai.config import base_dir
    assert 'key' not in (base_dir() / 'settings.json').read_text(encoding='utf8').lower().replace('api_base', '')


# ------------------------------------------------------------------------- release
def test_version_and_changelog_match_current_package():
    # This regression should remain valid for subsequent patch releases.
    match = re.search(r'^version = "(\d+\.\d+\.\d+)"',
                      (ROOT / 'pyproject.toml').read_text(encoding='utf8'), re.M)
    assert match
    current = match.group(1)
    assert tuple(map(int, current.split('.'))) >= (0, 0, 5)
    assert f'## {current} — ' in (ROOT / 'CHANGELOG.md').read_text(encoding='utf8')
    assert f'version-{current}-' in (ROOT / 'README.md').read_text(encoding='utf8')
    assert 'SPM Studio — Scientific image & data analysis' not in \
        (ROOT / 'src' / 'spm_studio' / 'ui' / 'main_window.py').read_text(encoding='utf8')
    from spm_studio.core import paths
    assert paths.GITHUB_URL == 'https://github.com/maxlpld/SPM-Studio' and paths.AUTHOR_NAME == 'maxlpld'


def test_recap_folder_names_are_cleaned():
    pytest.importorskip('PySide6')
    from spm_studio.ui.recap_dialog import clean_folder_name
    assert clean_folder_name('  my recap  ') == 'my recap'
    assert clean_folder_name('a/b\\c:d*e?') == 'a_b_c_d_e_'
    assert clean_folder_name('...') == '' and clean_folder_name('') == ''


# ================================================================== GUI (needs Qt)
@pytest.fixture
def window(home, monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    monkeypatch.setenv('SPM_STUDIO_NO_UPDATE_CHECK', '1')
    app = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(home / 'config'))
    from spm_studio.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    app.processEvents()
    yield win
    win.close()
    app.processEvents()


def test_window_has_no_menu_bar_but_a_gear_and_a_logs_button(window):
    from PySide6.QtWidgets import QApplication
    assert window.windowTitle() == 'SPM Studio'
    assert not window.menuBar().isVisible()
    # every command keeps its keyboard shortcut although the menus are hidden
    assert window._shortcut_actions['file.open'].shortcut().toString() == 'Ctrl+O'
    assert window._shortcut_actions['file.open'] in window.actions()
    gear = window.settings_button
    assert gear.isVisible() and gear.text() == '' and not gear.icon().isNull() and 'Settings' in gear.toolTip()
    assert not window.log_dock.isVisible() and not window.logs_toolbar_button.isChecked()
    window.logs_toolbar_button.click()
    QApplication.processEvents()
    assert window.log_dock.isVisible() and window.logs_toolbar_button.isChecked()


def test_dock_close_buttons_are_large_enough_to_see(window):
    from PySide6.QtWidgets import QApplication
    from spm_studio.shared.appearance import DOCK_CLOSE_BUTTON, DOCK_CLOSE_ICON
    assert DOCK_CLOSE_ICON >= 18 and DOCK_CLOSE_BUTTON >= 26
    window.log_dock.show()
    window.ai_dock.show()
    QApplication.processEvents()
    for dock in (window.log_dock, window.ai_dock):
        close = dock.spm_close_button
        assert close.isVisible() and close.width() >= 26 and close.height() >= 26
        assert close.iconSize().width() >= 18 and not close.icon().isNull()
        assert dock.titleBarWidget() is not None
        close.click()
        QApplication.processEvents()
        assert not dock.isVisible()


def test_tools_list_has_no_status_glyph_and_readme_button_opens(window, monkeypatch):
    from PySide6.QtCore import Qt
    tools = window.browser.tools
    names = [tools.item(i).text() for i in range(tools.count())]
    assert names and not any('◌' in n for n in names)
    assert not window.module_panel.readme_button.isVisible()
    row = next(i for i in range(tools.count()) if tools.item(i).data(Qt.ItemDataRole.UserRole) == 'cpd_histogram')
    tools.setCurrentRow(row)
    panel = window.module_panel
    assert not panel.readme_button.isHidden() and panel._readme_path.name == 'README.md'
    opened = []
    from spm_studio.ui import settings_dialog
    monkeypatch.setattr(settings_dialog.GuideDialog, 'exec', lambda self: opened.append(self.path) or 0)
    panel.readme_button.click()
    assert opened == [panel._readme_path]
    # the run progress strip is tall and follows the run
    assert panel.activity.isHidden()
    panel.set_run_state('progress', 'Fitting', 40)
    assert not panel.activity.isHidden() and panel.activity_bar.value() == 40
    assert panel.activity_bar.minimumHeight() >= 0 and panel.activity_bar.property('role') == 'activity'
    panel.set_run_state('idle')
    assert panel.activity.isHidden()
    assert window.logs.progress.property('role') == 'activity' and window.logs.progress.maximumWidth() >= 300
    assert window.ai_dock.busy_bar.property('role') == 'activity'


def test_settings_window_pages_and_library_actions(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QPushButton
    from spm_studio.ui.settings_dialog import SettingsDialog, PAGES
    from spm_studio.core import library, paths
    dialog = SettingsDialog(window, 'about')
    dialog.show()
    QApplication.processEvents()
    assert [p[0] for p in PAGES] == ['general', 'library', 'literature', 'about']
    assert dialog.stack.currentIndex() == 3
    author = dialog.findChild(type(dialog.about_version), 'AboutAuthorV005')
    assert 'maxlpld' in author.text() and 'https://github.com/maxlpld' in author.text()
    current = re.search(r'^version = "(\d+\.\d+\.\d+)"',
                        (ROOT / 'pyproject.toml').read_text(encoding='utf8'), re.M).group(1)
    assert f'Version {current}' in dialog.about_version.text()
    assert dialog.findChild(QPushButton, 'AboutGitHubButtonV005') is not None
    assert dialog.findChild(QPushButton, 'SettingsGitHubButtonV005') is not None
    # theme list follows the theme files
    dialog.show_page('general')
    assert dialog.theme_combo.findData('porcelain') >= 0
    # library: every kind lists something, and the profile list of the window follows a removal
    dialog.show_page('library')
    for index in range(dialog.kind_combo.count()):
        dialog.kind_combo.setCurrentIndex(index)
        assert dialog.items.count() > 0, dialog.kind_combo.itemData(index)
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData('profiles'))
    assert window.profile_combo.findData('Multipass') >= 0
    library.remove_item('profiles', 'Multipass.json')
    dialog._library_changed('removed')
    assert window.profile_combo.findData('Multipass') < 0
    library.import_path('profiles', ROOT / 'customization' / 'profiles' / 'Multipass.json')
    dialog._library_changed('imported')
    assert window.profile_combo.findData('Multipass') >= 0          # back without restarting
    assert window.profile_combo.findData('KPFM_v7') < 0
    # literature page reflects the saved settings and saves them
    dialog.show_page('literature')
    dialog.consensus_enabled.setChecked(True)
    dialog.zotero_mode.setCurrentIndex(dialog.zotero_mode.findData('local'))
    monkeypatch.setattr(window.ai_dock, '_open_backend', lambda: None)
    dialog._literature_apply()
    from spm_studio.ai.config import load
    assert load()['consensus_enabled'] is True and load()['zotero_mode'] == 'local'
    assert 'Saved.' in dialog.literature_result.text()
    dialog.close()


def test_export_dialog_custom_grid_and_saved_profile(window, home):
    import numpy as np
    from spm_studio.core.models import Scan, Channel, Geometry
    from spm_studio.core import paths
    from spm_studio.ui.export_dialog import PublicationDialog
    data = np.random.default_rng(1).normal(size=(32, 32))
    geom = Geometry(shape=(32, 32), size_m=(1e-8, 1e-8))
    first = home / 'first.sxm'
    first.write_bytes(b'a')
    second = home / 'second.sxm'
    second.write_bytes(b'b')
    scan = Scan(first, {name: Channel(name, unit, {'forward': data, 'backward': data}, geom)
                        for name, unit in (('Z', 'm'), ('Bias', 'V'), ('Current', 'A'))})
    other = Scan(second, {'Z': Channel('Z', 'm', {'forward': data}, geom)})
    dialog = PublicationDialog(scan, selected_channel='Z', other_scans=[('Other scan · second.sxm', str(second))],
                               scan_loader=lambda path: other, save_folder=paths.customization_dir() / 'export_presets')
    assert len(dialog.selection()) == 1 and dialog.panel_count.count() == 12
    dialog.layout_mode.setCurrentIndex(dialog.layout_mode.findData('custom'))
    dialog.panel_count.setCurrentIndex(4)                               # five images
    assert len(dialog.controls) == 5 and dialog.arrangement() == 'grid'
    dialog.grid_columns.setValue(3)
    assert dialog.columns() == 3
    dialog.controls[4]['scan'].setCurrentIndex(1)                       # fifth image from another scan
    panels = dialog.selection()
    assert len(panels) == 5 and panels[4]['scan_path'] == str(second) and panels[4]['trace'] == 'forward'
    dialog.controls[1]['title'].setText('$V_{CPD}$')
    saved = []
    dialog.profileSaved.connect(saved.append)
    from spm_studio.shared import dialogs
    import spm_studio.shared.dialogs as shared_dialogs
    original = shared_dialogs.TextInputDialog.getText
    shared_dialogs.TextInputDialog.getText = classmethod(lambda cls, *a, **k: ('five panels', True))
    try:
        dialog.save_as_profile()
    finally:
        shared_dialogs.TextInputDialog.getText = original
    assert saved == ['five_panels'] and dialogs is shared_dialogs
    stored = json.loads((paths.customization_dir() / 'export_presets' / 'five_panels.json').read_text(encoding='utf8'))
    assert stored['layout']['columns'] == 3 and stored['layout']['panels'][4]['scan'] == 'second.sxm'
    assert stored['layout']['panels'][1]['title'] == '$V_{CPD}$'
    # the main window lists it at once, and reopening the dialog rebuilds the figure
    window._export_profile_saved('five_panels')
    assert window.export_preset_combo.currentData() == 'five_panels'
    again = PublicationDialog(scan, selected_channel='Bias', preset=window.export_presets['five_panels'],
                              layout_name='five_panels', other_scans=[('Other scan · second.sxm', str(second))],
                              scan_loader=lambda path: other)
    assert again._n_panels() == 5 and again.columns() == 3 and again.controls[1]['title'].text() == '$V_{CPD}$'
    assert again.selection()[4]['scan_path'] == str(second)
    # and the renderer writes a five-panel grid, one panel coming from the other scan
    from spm_studio.core.export_layout import export_publication
    panels = again.selection()
    import spm_studio.core.io as scan_io
    original_reader = scan_io.read_scan
    scan_io.read_scan = lambda path: other
    try:
        out = export_publication(scan, panels, home / 'grid.png', again.resolved_preset() | {'dpi': 150},
                                 arrangement=again.arrangement(), columns=again.columns(), panel_letters=True)
    finally:
        scan_io.read_scan = original_reader
    assert out.is_file() and out.stat().st_size > 2000
    info = json.loads(Path(str(out) + '.provenance.json').read_text(encoding='utf8'))
    assert info['arrangement'] == 'grid' and info['columns'] == 3 and len(info['panels']) == 5
    dialog.close()
    again.close()


def test_recap_folder_is_chosen_by_the_user(window, home):
    from PySide6.QtWidgets import QApplication
    from spm_studio.ui.recap_dialog import RecapFolderDialog
    dialog = RecapFolderDialog(home / 'data_scan_recap', 2)
    assert dialog.folder() == home / 'data_scan_recap' and dialog.ok.isEnabled()
    dialog.name.setText('Paper figures')
    assert dialog.folder() == home / 'Paper figures'
    dialog.name.setText('')
    assert dialog.folder() is None and not dialog.ok.isEnabled()
    dialog.location.setText(str(home / 'does not exist'))
    dialog.name.setText('x')
    assert not dialog.ok.isEnabled()
    dialog.close()
    dataset = home / 'dataset'
    dataset.mkdir()
    for name in ('a.sxm', 'b.sxm'):
        (dataset / name).write_bytes(b'not a scan')
    window._source_paths = [str(dataset / 'a.sxm'), str(dataset / 'b.sxm')]
    window._session_folder = str(dataset)
    opened = []
    window._open_dataset_folder = opened.append
    target = home / 'somewhere else' / 'Paper figures'
    window.export_scan_selection(destination=target)
    QApplication.processEvents()
    assert sorted(p.name for p in target.iterdir()) == ['a.sxm', 'b.sxm', 'scan_recap.json']
    assert opened == [target] and (dataset / 'a.sxm').is_file()             # originals untouched
