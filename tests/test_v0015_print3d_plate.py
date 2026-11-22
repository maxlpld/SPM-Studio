"""v0.0.15: 3D print plates — sharp labels, centred layout, several channels, magnets, STL / STEP / 3MF."""
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest

from spm_studio.core import print3d as P
from spm_studio.core import print3d_plate as Q


def _scan(rows=96, cols=128, phase=0.0):
    yy, xx = np.mgrid[0:rows, 0:cols]
    data = (np.sin(xx / 6. + phase) * np.cos(yy / 7.)) * 1e-10
    data[rows // 2, cols // 2] = 5e-9
    return data


def _panel(title='Z', phase=0.0, colors=('#112233', '#FFEE00')):
    return Q.Panel(_scan(phase=phase), (20.0, 15.0), 'pm', 1e12, title, None, colors)


FAST = {'resolution_mm': .5, 'text_resolution_mm': .1, 'width_mm': 40}


def _closed(body):
    assert Q.edge_report(body.faces) == (0, 0), body.name
    assert P.check_normals(body.verts, body.faces) > 0, body.name


def _content_margins(plate):
    pts = np.vstack([b.verts for b in plate.bodies if not b.name.startswith('plate')])
    W, H = plate.size_mm
    return pts[:, 0].min(), W - pts[:, 0].max(), pts[:, 1].min(), H - pts[:, 1].max()


def test_every_solid_is_closed_for_all_bar_positions():
    for position in P.POSITIONS:
        plate = Q.build_plate([_panel()], {**FAST, 'colorbar': position, 'main_title': 'Main'})
        names = [b.name for b in plate.bodies]
        assert 'plate' in names and 'relief 1' in names and 'labels' in names
        assert ('3D colour bar 1' in names) == (position != 'none')
        for body in plate.bodies:
            _closed(body)


def test_content_is_centred_with_equal_margins_with_or_without_title():
    for title in ('', 'A long main title'):
        for position in ('right', 'bottom', 'top', 'left'):
            plate = Q.build_plate([_panel()], {**FAST, 'main_title': title, 'colorbar': position})
            left, right, bottom, top = _content_margins(plate)
            m = plate.params['margin_mm']
            for side in (left, right, bottom, top):
                assert abs(side - m) < .25, (title, position, left, right, bottom, top)


def test_labels_are_fine_and_bold_enough_to_print():
    plate = Q.build_plate([_panel()], {'resolution_mm': .5, 'width_mm': 40})
    labels = next(b for b in plate.bodies if b.name == 'labels')
    steps = np.diff(np.unique(np.round(labels.verts[:, 0], 4)))
    assert steps.min() < .06                         # 0.05 mm text grid (was the 0.25 mm relief grid)
    assert plate.params['font_mm'] >= 5 and Q.TEXT_FONT['weight'] == 'bold'
    assert labels.verts[:, 2].max() == pytest.approx(plate.params['base_mm'] + plate.params['label_mm'])


def test_quality_presets_change_the_relief_grid():
    coarse = Q.build_plate([_panel()], {'quality': 'draft', 'width_mm': 40, 'text_resolution_mm': .1})
    fine = Q.build_plate([_panel()], {'quality': 'fine', 'width_mm': 40, 'text_resolution_mm': .1})
    relief = [next(b for b in p.bodies if b.name == 'relief 1') for p in (coarse, fine)]
    assert len(relief[1].faces) > 4 * len(relief[0].faces)


def test_multi_channel_layouts():
    sizes = {}
    for key, (_label, slots) in Q.LAYOUTS.items():
        params = {**FAST, 'layout': key, 'layout_rows': 2, 'layout_cols': 3}
        n = Q.panel_count(params)
        assert n == (6 if key == 'custom' else len(slots))
        plate = Q.build_plate([_panel(f'C{i}', i) for i in range(n)], params)
        assert len(plate.panels) == n and len(plate.parts()) == n + 1
        for body in plate.bodies:
            _closed(body)
        sizes[key] = plate.size_mm
    assert sizes['row2'][0] > 1.8 * sizes['single'][0] and sizes['col2'][1] > 1.8 * sizes['single'][1]
    assert sizes['triangle3'][0] == pytest.approx(sizes['row2'][0], abs=.5)
    assert sizes['grid4'][1] == pytest.approx(sizes['col2'][1], abs=.5)
    # the third panel of the triangle is centred under the first two
    tri = Q.build_plate([_panel(f'C{i}', i) for i in range(3)], {**FAST, 'layout': 'triangle3'})
    x = [p['box'][0] + p['box'][2] / 2 for p in tri.panels]
    assert x[2] == pytest.approx((x[0] + x[1]) / 2, abs=.01)
    extra = Q.build_plate([_panel(), _panel()], {**FAST, 'layout': 'single'})
    assert len(extra.panels) == 1 and any('extra' in n for n in extra.notes)


def test_channel_titles_and_main_title_can_be_switched():
    on = Q.build_plate([_panel('Current')], {**FAST, 'channel_titles': True})
    off = Q.build_plate([_panel('Current')], {**FAST, 'channel_titles': False})
    main = Q.build_plate([_panel('Current')], {**FAST, 'channel_titles': False, 'main_title': 'KBr'})
    assert on.size_mm[1] > off.size_mm[1] + 4 and main.size_mm[1] > off.size_mm[1] + 4
    assert on.size_mm[0] == pytest.approx(off.size_mm[0], abs=.2)


def test_fridge_magnet_pockets():
    plate = Q.build_plate([_panel()], {**FAST, 'magnets': True, 'base_mm': 1.0})
    assert plate.params['base_mm'] == pytest.approx(2.0 + Q.MIN_FLOOR) and any('thickened' in n for n in plate.notes)
    slab = next(b for b in plate.bodies if 'magnet' in b.name)
    _closed(slab)
    W, H = plate.size_mm
    r, d = 5.1, 2.0
    volume = P.check_normals(slab.verts, slab.faces)
    assert volume == pytest.approx(W * H * d - 4 * np.pi * r ** 2 * d, rel=.01)
    # a pocket under each corner: no slab vertex lies inside a circle, the circles touch the corner region
    inset = plate.params['magnet_inset_mm']
    for cx in (inset + r, W - inset - r):
        for cy in (inset + r, H - inset - r):
            dist = np.hypot(slab.verts[:, 0] - cx, slab.verts[:, 1] - cy)
            assert dist.min() > r - .1 and dist.min() < r + .2
    # the relief and texts stay out of the pockets' corners (margin grows to hold them)
    assert min(_content_margins(plate)) >= 2 * r + 2 * inset - 2 - .25


def test_stl_step_and_3mf_files(tmp_path):
    plate = Q.build_plate([_panel('Z', 0, ('#102030', '#F0E010')), _panel('Current', 1, ('#5B1A72', '#F28C28'))],
                          {**FAST, 'layout': 'row2', 'main_title': 'Sample'})
    path, n, _notes = Q.export_plate(plate, tmp_path / 'plate.stl')
    raw = path.read_bytes()
    assert int.from_bytes(raw[80:84], 'little') == n == plate.triangles and len(raw) == 84 + 50 * n
    step, n, _notes = Q.export_plate(plate, tmp_path / 'plate.step')
    text = step.read_text()
    ids = set(map(int, re.findall(r'^#(\d+)=', text, re.M)))
    assert not set(map(int, re.findall(r'#(\d+)', text))) - ids
    assert text.count('FACETED_BREP(') == len(plate.bodies) and text.count('FACE_OUTER_BOUND') == n
    mf, n, notes = Q.export_plate(plate, tmp_path / 'plate.3mf')
    assert notes and zipfile.is_zipfile(mf)
    with zipfile.ZipFile(mf) as zf:
        names = set(zf.namelist())
        assert {'[Content_Types].xml', '_rels/.rels', '3D/3dmodel.model',
                'Metadata/spm_studio_gradients.json'} <= names
        root = ET.fromstring(zf.read('3D/3dmodel.model'))
        recipe = json.loads(zf.read('Metadata/spm_studio_gradients.json'))
    ns = {'m': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
    objects = root.findall('.//m:object', ns)
    parts = [o.get('name') for o in objects if o.find('m:mesh', ns) is not None]
    assert parts[0] == 'Plate & labels' and parts[1].startswith('Panel 1') and parts[2].startswith('Panel 2')
    colours = [b.get('displaycolor') for b in root.findall('.//m:base', ns)]
    assert colours[1] == '#102030FF' and colours[2] == '#5B1A72FF'
    assembly = [o for o in objects if o.find('m:components', ns) is not None]
    assert len(assembly) == 1 and len(assembly[0].findall('.//m:component', ns)) == 3
    triangles = sum(len(o.findall('.//m:triangle', ns)) for o in objects)
    assert triangles == plate.triangles
    assert [p['high_colour'] for p in recipe['panels']] == ['#F0E010', '#F28C28']
    assert recipe['panels'][0]['low_height_mm'] == plate.params['base_mm']


def test_old_single_model_api_is_kept():
    model = P.build_model(_scan(), (20, 15), {'resolution_mm': .5})
    assert model.z.ndim == 2 and P.export


# ------------------------------------------------------------------ dialog
@pytest.fixture
def app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_four_channels_magnets_and_3mf(app, tmp_path, monkeypatch):
    from spm_studio.core.models import Geometry
    from spm_studio.ui.print3d_dialog import Print3DDialog
    channels = {}
    for i, name in enumerate(('Z', 'Current', 'Phase', 'Amplitude')):
        data = _scan(phase=i)
        channels[name] = SimpleNamespace(traces={'forward': data, 'backward': data}, unit='m',
                                         geometry=Geometry(data.shape, (20e-9, 15e-9)), get=lambda t, d=data: d)
    scan = SimpleNamespace(path=tmp_path / 'scan.sxm', channels=channels)
    inspector = SimpleNamespace(channel=SimpleNamespace(currentText=lambda: 'Z'), selected_trace=lambda: 'forward',
                                steps=lambda: [])
    main = SimpleNamespace(scan=scan, inspector=inspector, pipelines={}, last_export_dir=tmp_path,
                           _log=lambda *a, **k: None)
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: pytest.fail(str(a[2:])))
    holder = QWidget()
    dialog = Print3DDialog(main, holder)
    dialog.width_mm.setValue(30)
    dialog.quality.setCurrentIndex(dialog.quality.findData('draft'))
    dialog.layout_combo.setCurrentIndex(dialog.layout_combo.findData('grid4'))
    assert len(dialog.panel_rows) == 4
    assert [r['channel'].currentText() for r in dialog.panel_rows[1:]] == ['Current', 'Phase', 'Amplitude']
    dialog.magnets.setChecked(True)
    dialog.main_title.setText('Four channels')
    dialog.channel_titles.setChecked(False)
    dialog.update_preview()
    assert dialog.save_3mf.isEnabled() and 'Plate' in dialog.info.text() and '4 channel' in dialog.info.text()
    assert 'Fridge magnet' in dialog.info.text()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path / 'out.3mf'), ''))
    dialog.export('3mf')
    assert zipfile.is_zipfile(tmp_path / 'out.3mf')
    assert (tmp_path / 'out.colour_gradient.txt').read_text(encoding='utf8').count('Panel ') == 4
    info = json.loads((tmp_path / 'out.print3d.json').read_text(encoding='utf8'))
    assert len(info['panels']) == 4 and info['parameters']['magnets'] is True
    dialog.layout_combo.setCurrentIndex(dialog.layout_combo.findData('custom'))
    dialog.layout_rows.setValue(1)
    dialog.layout_cols.setValue(3)
    assert len(dialog.panel_rows) == 3
    dialog.close()
