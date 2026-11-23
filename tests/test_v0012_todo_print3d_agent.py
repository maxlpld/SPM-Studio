"""v0.0.12: to-do list connected to the assistant, 3D print relief, assistant permissions."""
import json
import os
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ 3D print (core)
def _edges_closed(faces):
    edges = Counter()
    for a, b, c in faces:
        for u, w in ((a, b), (b, c), (c, a)):
            edges[(u, w)] += 1
    return all(n == 1 and edges.get((w, u), 0) == 1 for (u, w), n in edges.items())


def test_mesh_is_watertight_and_outward():
    from spm_studio.core import print3d as P
    z = np.full((6, 9), 2.0)
    z[2:4, 3:6] = 5.0
    v, f = P.heightfield_mesh(z, .5)
    assert _edges_closed(f)
    assert P.check_normals(v, f) > 0


def _scan(rows=120, cols=160):
    yy, xx = np.mgrid[0:rows, 0:cols]
    data = (np.sin(xx / 6.) * np.cos(yy / 7.)) * 1e-10
    data[rows // 2, cols // 2] = 5e-9                    # one huge spike
    return data


def test_relief_colour_bar_and_range_cut():
    from spm_studio.core import print3d as P
    data = _scan()
    model = P.build_model(data, (20, 15), {'colorbar': 'right', 'title': 'Test', 'base_mm': 2, 'relief_mm': 5,
                                           'unit': 'pm', 'value_scale': 1e12})
    z = model.z
    assert z.min() >= 2 - 1e-9 and z.max() <= 2 + 5 + .8 + 1e-9
    # the spike is cut by the percentile range: most of the relief uses the full height
    x0, y0, w, h = model.image_box
    c0, r0 = int(round(x0 / model.cell_mm)), int(round(y0 / model.cell_mm))
    patch = z[r0:r0 + int(h / model.cell_mm), c0:c0 + int(w / model.cell_mm)]
    assert np.percentile(patch, 95) > 6.0
    assert any('outside the colour-bar range' in n for n in model.notes)
    # the wedge rises from the bottom (low value) to the top (high value)
    bx, by, bw, bh = model.bar_box
    col = int(round((bx + bw / 2) / model.cell_mm))
    top_row, bottom_row = int(round((by + 1) / model.cell_mm)), int(round((by + bh - 1) / model.cell_mm))
    assert z[top_row, col] > z[bottom_row, col] + 4


def test_absolute_range_and_positions():
    from spm_studio.core import print3d as P
    data = _scan()
    for pos in P.POSITIONS:
        m = P.build_model(data, (20, 15), {'colorbar': pos, 'range_mode': 'absolute', 'low': -5e-11, 'high': 5e-11})
        assert (m.bar_box is None) == (pos == 'none')
        assert m.low == -5e-11 and m.high == 5e-11
    with pytest.raises(ValueError):
        P.build_model(data, (20, 15), {'range_mode': 'absolute', 'low': 1, 'high': 0})


def test_lattice_and_molecule_overlays_raise_the_relief():
    from spm_studio.core import print3d as P
    data = np.add.outer(np.zeros(100), np.linspace(0, 1e-10, 100))      # a plane: well defined relief
    doc = {'basis_local_nm': [[.29, .145], [0, .25]], 'a_nm': .29, 'b_nm': .29, 'gamma_deg': 60,
           'roi_geometry': {'size_nm': [5, 5]}}

    def raised(model, plain):
        x0, y0, w, h = model.image_box
        c0, r0 = int(round(x0 / model.cell_mm)), int(round(y0 / model.cell_mm))
        sl = (slice(r0, r0 + int(h / model.cell_mm)), slice(c0, c0 + int(w / model.cell_mm)))
        return int((model.z[sl] - plain.z[sl] > .5).sum())
    plain = P.build_model(data, (5, 5), {'colorbar': 'none'})
    over = P.build_model(data, (5, 5), {'colorbar': 'none', 'overlay_mm': 1.0}, P.overlay_from_lattice(doc))
    assert raised(over, plain) > 50                                     # arrows raised on the relief
    placement = {'lattice_sites': [[0, 0, 0, 0], [1, 1, 1, 1]], 'width_nm': .8, 'height_nm': .5,
                 'rotation_deg': 30}
    mol = P.build_model(data, (5, 5), {'colorbar': 'none'},
                        P.overlay_from_molecules(doc, placement, np.ones((20, 30))))
    assert raised(mol, plain) > raised(over, plain) + 50                # + the two molecules


def test_stl_and_step_files(tmp_path):
    from spm_studio.core import print3d as P
    model = P.build_model(_scan(60, 80), (10, 7.5), {'resolution_mm': .5, 'width_mm': 40})
    path, triangles, _notes = P.export(model, tmp_path / 'relief.stl')
    raw = path.read_bytes()
    assert int.from_bytes(raw[80:84], 'little') == triangles and len(raw) == 84 + 50 * triangles
    step, n, notes = P.export(model, tmp_path / 'relief.step')
    text = step.read_text()
    assert text.startswith('ISO-10303-21;') and text.rstrip().endswith('END-ISO-10303-21;')
    ids = set(map(int, re.findall(r'^#(\d+)=', text, re.M)))
    refs = set(map(int, re.findall(r'#(\d+)', text))) - ids
    assert not refs                                          # every reference is defined
    # v0.0.16: standard B-rep (ADVANCED_FACE on PLANE) so OpenCASCADE importers (Bambu Studio…) see geometry
    from spm_studio.core.print3d_step import check_step
    assert check_step(text)['solids'] == 1 and 'MANIFOLD_SOLID_BREP(' in text and 'CLOSED_SHELL' in text
    assert 'POLY_LOOP' not in text and text.count('ADVANCED_FACE(') <= n
    big = P.build_model(_scan(), (20, 15), {'resolution_mm': .1})
    _p, n_big, notes = P.export(big, tmp_path / 'big.step')
    assert n_big <= 4 * P.MAX_STEP_CELLS * 1.05 + 20_000 and notes


# ------------------------------------------------------------------ to-do (model + protocol)
@pytest.fixture
def data_home(tmp_path, monkeypatch):
    for name, folder in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache')]:
        monkeypatch.setenv(name, str(tmp_path / folder))
    return tmp_path


def test_todo_is_saved_and_survives_reopening(data_home):
    from spm_studio.documents import todo
    data = todo.load()
    task = todo.add_task(data, 'CPD map of scan 0024', 'Z forward, plane', 'Analysis')
    data['notes'] = 'KBr terraces look clean'
    todo.save(data)
    again = todo.load()
    assert again['tasks'][0]['text'] == 'CPD map of scan 0024' and again['notes'].startswith('KBr')
    assert todo.find(again, 1)['id'] == task['id'] and todo.find(again, '#1')['id'] == task['id']
    todo.set_done(again['tasks'][0], True)
    assert '#1 [x]' in todo.as_text(again) and todo.as_text(again, include_done=False) == '(no tasks)'
    copy = todo.erase_all(again)
    assert copy.is_file() and json.loads(copy.read_text())['notes'].startswith('KBr')
    assert again['tasks'] == [] and again['notes'] == ''
    # a broken file falls back to the backup
    todo.save(again)
    todo.file().write_text('{broken')
    assert todo.load()['tasks'][0]['text'] == 'CPD map of scan 0024'
    assert todo.parse_quick('script: export STL') == ('export STL', 'Script')


def test_todo_protocol_and_actions(data_home):
    from spm_studio.documents import protocol, todo
    ai_action = todo.ai_action
    text = ('Done. <spm-doc>{"app": "todo", "action": "update_task", "item": 1, "done": true, '
            '"append": "script in scripts/stl_export"}</spm-doc>')
    requests = protocol.parse_requests(text)
    assert requests == [{'app': 'todo', 'action': 'update_task', 'append': 'script in scripts/stl_export',
                         'done': True, 'item': '1'}]
    assert ai_action({'app': 'todo', 'action': 'add_task', 'text': 'STL of scan 12', 'category': 'Script'})
    result = ai_action(requests[0])
    assert 'done' in result
    data = todo.load()
    assert data['tasks'][0]['done'] and 'stl_export' in data['tasks'][0]['details']
    assert '#1 [x]' in ai_action({'app': 'todo', 'action': 'read'})
    assert protocol.needs_followup([{'app': 'todo', 'action': 'read'}], [])
    ctx = protocol.agent_context(False, False, True)
    assert '"app": "todo"' in ctx and 'update_task' in ctx
    assert protocol.agent_context(False, False, False) == ''


# ------------------------------------------------------------------ assistant permissions
def test_assistant_defaults_and_full_access(data_home):
    from spm_studio.ai import config
    conf = config.load()
    assert conf['consensus_enabled'] is True and conf['zotero_mode'] == 'auto'
    granted = config.grant_full_access({**conf, 'zotero_mode': 'off', 'chat_tools': False})
    assert granted['chat_tools'] and granted['chat_tools_ack'] and granted['zotero_mode'] == 'auto'
    folders = [str(f) for f in config.app_folders()]
    from spm_studio.core import paths
    assert str(paths.scripts_dir()) in folders and str(paths.bundled_studio_root()) in folders
    text = config.spm_context_file(data_home / 'ws', True).read_text()
    assert 'You HAVE file and shell tools' in text and 'patch it whenever the user asks' in text
    assert 'WITHOUT file or shell tools' in config.spm_context_file(data_home / 'ws', False).read_text()


def test_agent_command_lines_reach_the_app_folders():
    from spm_studio.ai.cli_events import build_args
    args = build_args('claude-code', '', True, 'ctx', extra_dirs=['/a', '/b'])
    assert args.count('--add-dir') == 2 and '/b' in args
    assert '--add-dir' not in build_args('claude-code', '', False, 'ctx', extra_dirs=['/a'])
    codex = build_args('codex', '', True, extra_dirs=['/a'])
    assert any(a.startswith('sandbox_workspace_write.writable_roots=["/a"]') for a in codex) and codex[-1] == '-'
    source = (ROOT / 'src/spm_studio/ai/cli_agents.py').read_text()
    assert "'Bash'" in source and 'extra_dirs=folders' in source


# ------------------------------------------------------------------ Qt
@pytest.fixture
def app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_todo_window_check_style_erase_and_persist(app, data_home, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    from spm_studio.documents import todo
    from spm_studio.documents.ui.todo_window import TodoWindow
    hub = SimpleNamespace(unregister=lambda w: None, ask_assistant=lambda *a, **k: sent.append((a, k)))
    sent = []
    win = TodoWindow(hub)
    win.quick.setText('Analysis: lattice of scan 0024')
    win.add_from_quick()
    win.quick.setText('Write the KBr report')
    win.add_from_quick()
    assert win.list.count() == 2 and win.data['tasks'][0]['category'] == 'Analysis'
    win.list.item(0).setCheckState(Qt.CheckState.Checked)
    app.processEvents()
    assert win.data['tasks'][0]['done']
    assert win.list.item(0).font().strikeOut()
    win.done_style.setCurrentIndex(win.done_style.findData('hide'))
    assert win.list.count() == 1
    win.done_style.setCurrentIndex(win.done_style.findData('plain'))
    assert win.list.count() == 2 and not win.list.item(0).font().strikeOut()
    win.notes.setPlainText('Terrace width 40 nm')
    win.save()
    win.close()
    again = TodoWindow(hub)                         # reopening: nothing lost
    assert again.list.count() == 2 and again.notes.toPlainText() == 'Terrace width 40 nm'
    again.list.setCurrentRow(1)
    again.list.item(1).setSelected(True)
    again.ask_tasks('selected')
    assert sent and 'Write the KBr report' in sent[-1][0][0] and sent[-1][1]['send']
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    again.erase_all()
    assert again.list.count() == 0 and todo.load()['notes'] == ''
    assert list(todo.folder().glob('erased_*.json'))
    again.close()


def test_print3d_dialog_previews_and_exports(app, tmp_path, monkeypatch):
    from spm_studio.core.models import Geometry
    from spm_studio.ui.print3d_dialog import Print3DDialog
    data = _scan()
    channel = SimpleNamespace(traces={'forward': data}, unit='m', geometry=Geometry(data.shape, (20e-9, 15e-9)),
                              get=lambda trace: data)
    scan = SimpleNamespace(path=tmp_path / 'scan.sxm', channels={'Z': channel})
    inspector = SimpleNamespace(channel=SimpleNamespace(currentText=lambda: 'Z'), selected_trace=lambda: 'forward',
                                steps=lambda: [])
    main = SimpleNamespace(scan=scan, inspector=inspector, pipelines={}, last_export_dir=tmp_path,
                           _log=lambda *a, **k: None)
    from PySide6.QtWidgets import QWidget
    holder = QWidget()
    dialog = Print3DDialog(main, holder)
    dialog.update_preview()
    assert dialog.save_stl.isEnabled() and 'Plate' in dialog.info.text()
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path / 'out.stl'), ''))
    dialog.export('stl')
    assert (tmp_path / 'out.stl').stat().st_size > 10000 and (tmp_path / 'out.print3d.json').is_file()
    dialog.colorbar.setCurrentIndex(dialog.colorbar.findData('bottom'))
    dialog.range_mode.setCurrentIndex(dialog.range_mode.findData('absolute'))
    dialog.update_preview()
    assert 'pm' in dialog.info.text()
    dialog.close()
