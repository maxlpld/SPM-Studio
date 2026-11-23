"""v0.0.16: 3D print — Fix Zero / image contrast on the colour bar, STEP readable by CAD/slicers, Bambu Studio
project 3MF with automatic colour gradients, text and background colours, printer and nozzle."""
import json
import os
import xml.etree.ElementTree as ET
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest

from spm_studio.core import print3d as P
from spm_studio.core import print3d_bambu as B
from spm_studio.core import print3d_plate as Q
from spm_studio.core.print3d_step import check_step

FAST = {'resolution_mm': .5, 'text_resolution_mm': .1, 'width_mm': 40}
NS = {'m': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02',
      'p': 'http://schemas.microsoft.com/3dmanufacturing/production/2015/06'}


def _scan(rows=96, cols=128, phase=0.0):
    yy, xx = np.mgrid[0:rows, 0:cols]
    return (np.sin(xx / 6. + phase) * np.cos(yy / 7.)) * 1e-10


def _panel(title='Z', phase=0.0, colors=('#112233', '#FFEE00'), **kw):
    return Q.Panel(_scan(phase=phase), (20.0, 15.0), 'pm', 1e12, title, None, colors, **kw)


# ------------------------------------------------------------------ Fix Zero / image range
def test_fix_zero_labels_start_at_zero():
    ticks = Q._ticks(-1e-10, 2e-10, 1e12, 4)
    zero = Q._ticks(-1e-10, 2e-10, 1e12, 4, zero=True)
    assert [t for _f, t in ticks] == ['-100', '0', '100', '200']
    assert [t for _f, t in zero] == ['0', '100', '200', '300']
    plate = Q.build_plate([_panel(zero_reference=True, range={'range_mode': 'absolute', 'low': -1e-10,
                                                              'high': 2e-10})], FAST)
    recipe = Q.gradient_recipe(plate)['panels'][0]
    assert recipe['low_value'] == pytest.approx(0) and recipe['high_value'] == pytest.approx(300)
    plain = Q.build_plate([_panel(range={'range_mode': 'absolute', 'low': -1e-10, 'high': 2e-10})], FAST)
    assert Q.gradient_recipe(plain)['panels'][0]['low_value'] == pytest.approx(-100)
    # the labels really differ (other tick texts are embossed)
    a = next(b for b in plate.bodies if b.name == 'labels')
    b = next(b for b in plain.bodies if b.name == 'labels')
    assert len(a.faces) != len(b.faces)


# ------------------------------------------------------------------ STEP
def test_step_is_a_valid_brep_for_every_layout(tmp_path):
    plate = Q.build_plate([_panel('Z'), _panel('I', 1)], {**FAST, 'layout': 'row2', 'magnets': True,
                                                         'main_title': 'Title'})
    path, n, notes = Q.export_plate(plate, tmp_path / 'plate.step')
    text = path.read_text()
    report = check_step(text)                       # closed loops, shared edges, planar faces
    assert report['solids'] == len(plate.bodies)
    assert 'FACETED_BREP' not in text and 'POLY_LOOP' not in text and 'ADVANCED_BREP_SHAPE_REPRESENTATION' in text
    assert report['faces'] < n                      # coplanar triangles merged into planar faces
    # the old single-relief engine writes the same standard form
    model = P.build_model(_scan(), (20, 15), {'resolution_mm': .5, 'width_mm': 40})
    old, _n, _notes = P.export(model, tmp_path / 'old.step')
    assert check_step(old.read_text())['solids'] == 1


def test_step_uses_a_lighter_relief_with_the_same_outline():
    plate = Q.build_plate([_panel()], {'quality': 'fine', 'width_mm': 60, 'text_resolution_mm': .1})
    bodies, notes = Q.step_bodies(plate.bodies, max_cells=2000)
    full = next(b for b in plate.bodies if b.name == 'relief 1')
    light = next(b for b in bodies if b.name == 'relief 1')
    assert len(light.faces) < len(full.faces) / 5 and notes
    for axis in (0, 1):
        assert light.verts[:, axis].min() == pytest.approx(full.verts[:, axis].min())
        assert light.verts[:, axis].max() == pytest.approx(full.verts[:, axis].max())
    assert Q.edge_report(light.faces) == (0, 0) and P.check_normals(light.verts, light.faces) > 0


# ------------------------------------------------------------------ colours
def test_text_and_background_colours():
    plate = Q.build_plate([_panel()], {**FAST, 'text_color': '#FF0000', 'background_color': '#00FF00'})
    parts = plate.parts()
    assert parts['Plate'][0].color == '#00FF00' and parts['Labels'][0].color == '#FF0000'
    rgb = plate.preview_rgb
    assert rgb.shape[:2] == plate.preview[0].shape
    assert np.allclose(rgb[0, 0], [0, 1, 0])        # corner = background
    assert np.any(np.all(np.isclose(rgb, [1, 0, 0]), axis=-1))   # some text pixels
    # default: black text on a white plate; v0.0.15 'base_color' still sets the plate colour
    default = Q.build_plate([_panel()], FAST)
    assert default.parts()['Labels'][0].color == '#000000' and default.parts()['Plate'][0].color == '#FFFFFF'
    legacy = Q.build_plate([_panel()], {**FAST, 'base_color': '#123456'})
    assert legacy.parts()['Plate'][0].color == '#123456'


def test_nozzle_sets_the_minimum_stroke():
    thin = Q.build_plate([_panel()], {**FAST, 'nozzle_mm': .2})
    thick = Q.build_plate([_panel()], {**FAST, 'nozzle_mm': .8})
    assert any('small for a 0.8 mm nozzle' in n for n in thick.notes)
    assert not any('nozzle' in n for n in thin.notes)


# ------------------------------------------------------------------ Bambu Studio project
def _read(path):
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def test_bambu_project_with_automatic_gradients(tmp_path):
    plate = Q.build_plate([_panel('Z', 0, ('#102030', '#F0E010')), _panel('I', 1, ('#102030', '#FF0000'))],
                          {**FAST, 'layout': 'row2'})
    path, n, notes = Q.export_plate(plate, tmp_path / 'plate.3mf',
                                    bambu={'printer': 'Bambu Lab P1S', 'nozzle': 0.4})
    files = _read(path)
    assert {'3D/3dmodel.model', '3D/Objects/object_1.model', '3D/_rels/3dmodel.model.rels',
            'Metadata/model_settings.config', 'Metadata/project_settings.config', '[Content_Types].xml',
            '_rels/.rels'} <= set(files)
    main = ET.fromstring(files['3D/3dmodel.model'])
    meta = {m.get('name'): m.text for m in main.findall('m:metadata', NS)}
    assert meta['Application'].startswith('BambuStudio-')           # Bambu reads the project settings
    components = main.findall('.//m:component', NS)
    assert len(components) == len(plate.parts())
    assert all(c.get(f'{{{NS["p"]}}}path') == '/3D/Objects/object_1.model' for c in components)
    sub = ET.fromstring(files['3D/Objects/object_1.model'])
    assert sum(len(o.findall('.//m:triangle', NS)) for o in sub.findall('.//m:object', NS)) == plate.triangles
    cfg = json.loads(files['Metadata/project_settings.config'])
    names = B.preset_names('Bambu Lab P1S', .4)
    assert cfg['printer_settings_id'] == 'Bambu Lab P1S 0.4 nozzle' == names['printer']
    assert cfg['print_settings_id'] == names['process'] and cfg['printer_model'] == 'Bambu Lab P1S'
    physical = ['#FFFFFF', '#000000', '#102030', '#F0E010', '#FF0000']   # background, text, shared low, highs
    n_all = len(physical) + 2
    assert cfg['filament_colour'][:5] == physical and len(cfg['filament_colour']) == n_all
    for key in ('filament_settings_id', 'filament_is_mixed', 'filament_mixed_components', 'filament_self_index',
                'filament_extruder_variant', 'filament_map', 'filament_mixed_gradient',
                'filament_mixed_gradient_range'):
        assert len(cfg[key]) == n_all, key
    assert cfg['filament_is_mixed'] == ['0'] * 5 + ['1', '1']
    assert cfg['filament_mixed_components'][5:] == ['3,4', '3,5']
    assert cfg['filament_mixed_gradient'][5:] == ['1', '1']
    assert cfg['filament_mixed_gradient_range'][5:] == ['0.9000,0.1000'] * 2   # low colour at the bottom
    assert cfg['enable_mixed_color_sublayer'] == '1'
    assert cfg['different_settings_to_system'][0] == 'enable_mixed_color_sublayer'
    assert len(cfg['different_settings_to_system']) == n_all + 2
    assert len(cfg['flush_volumes_matrix']) == n_all * n_all
    assert cfg['filament_self_index'] == [str(i + 1) for i in range(n_all)]
    settings = ET.fromstring(files['Metadata/model_settings.config'])
    extruder = {}
    for part in settings.findall('.//part'):
        meta = {m.get('key'): m.get('value') for m in part.findall('metadata')}
        extruder[meta['name']] = int(meta['extruder'])
    assert extruder['Plate'] == 1 and extruder['Labels'] == 2
    assert extruder['Panel 1 — Z'] == 6 and extruder['Panel 2 — I'] == 7     # their mixed gradient filaments
    assert settings.find('.//plate/model_instance') is not None
    assert any('gradient mixed filament' in n for n in notes) and any('AMS' in n for n in notes)


def test_bambu_project_without_gradient_and_dual_nozzle(tmp_path):
    plate = Q.build_plate([_panel('Z', 0, ('#FFFFFF', '#000000'))], FAST)
    path, _n, notes = Q.export_plate(plate, tmp_path / 'p.3mf',
                                     bambu={'printer': 'Bambu Lab H2D', 'nozzle': 0.6, 'gradient': False})
    cfg = json.loads(_read(path)['Metadata/project_settings.config'])
    assert cfg['filament_colour'] == ['#FFFFFF', '#000000']          # identical colours shared
    assert cfg['filament_is_mixed'] == ['0', '0'] and cfg['enable_mixed_color_sublayer'] == '0'
    assert cfg['nozzle_diameter'] == ['0.6', '0.6'] and len(cfg['extruder_type']) == 2
    assert len(cfg['flush_volumes_matrix']) == 2 * 2 * 2
    assert cfg['printer_settings_id'] == 'Bambu Lab H2D 0.6 nozzle'


def test_bambu_printers_and_bed_check(tmp_path):
    assert 'Bambu Lab X1 Carbon' in B.printer_names() and 'Bambu Lab A1 mini' in B.printer_names()
    for name in B.printer_names():
        for nozzle in B.NOZZLES:
            names = B.preset_names(name, float(nozzle))
            assert names['printer'] == f'{name} {nozzle} nozzle' and names['process'] and names['filament']
    with pytest.raises(ValueError):
        B.preset_names('Bambu Lab X1 Carbon', 1.0)
    big = Q.build_plate([_panel('A'), _panel('B', 1)], {**FAST, 'width_mm': 120, 'layout': 'row2'})
    _p, _n, notes = Q.export_plate(big, tmp_path / 'big.3mf', bambu={'printer': 'Bambu Lab A1 mini', 'nozzle': .4})
    assert any('larger than the Bambu Lab A1 mini bed' in n for n in notes)


def test_plain_3mf_is_kept(tmp_path):
    plate = Q.build_plate([_panel()], FAST)
    path, _n, notes = Q.export_plate(plate, tmp_path / 'plain.3mf')
    files = _read(path)
    assert 'Metadata/project_settings.config' not in files and 'Metadata/README_colour_gradient.txt' in files
    assert notes


# ------------------------------------------------------------------ dialog
@pytest.fixture
def app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_image_range_fix_zero_and_bambu(app, tmp_path, monkeypatch):
    from spm_studio.core.models import Geometry, ImageStyle, ProcessingStep
    from spm_studio.ui.print3d_dialog import Print3DDialog
    data = _scan(80, 100)
    channels = {'Z': SimpleNamespace(traces={'forward': data, 'backward': data}, unit='m',
                                     geometry=Geometry(data.shape, (20e-9, 16e-9)), get=lambda t: data)}
    scan = SimpleNamespace(path=tmp_path / 'scan.sxm', channels=channels)
    style = ImageStyle(range_mode='manual', low=-5e-11, high=5e-11)
    inspector = SimpleNamespace(channel=SimpleNamespace(currentText=lambda: 'Z'), selected_trace=lambda: 'forward',
                                steps=lambda: [ProcessingStep('fix_zero', {}, True)], get_style=lambda: style)
    main = SimpleNamespace(scan=scan, inspector=inspector, pipelines={}, styles={}, last_export_dir=tmp_path,
                           _log=lambda *a, **k: None)
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: pytest.fail(str(a[2:])))
    holder = QWidget()
    dialog = Print3DDialog(main, holder)
    dialog.layout_combo.setCurrentIndex(dialog.layout_combo.findData('single'))
    dialog.width_mm.setValue(30)
    dialog.quality.setCurrentIndex(dialog.quality.findData('draft'))
    dialog.range_mode.setCurrentIndex(dialog.range_mode.findData('display'))
    dialog.zero_mode.setCurrentIndex(dialog.zero_mode.findData('image'))
    dialog.processed.setChecked(True)
    dialog.text_color.set_color('#FF0000')
    dialog.printer.setCurrentIndex(dialog.printer.findData('Bambu Lab A1'))
    dialog.nozzle.setCurrentIndex(dialog.nozzle.findData('0.4'))
    dialog.update_preview()
    panel = dialog.plate.panels[0]
    assert panel['low'] == pytest.approx(-5e-11) and panel['high'] == pytest.approx(5e-11)   # image contrast
    assert panel['zero_reference'] is True and 'range 0 …' in dialog.info.text()            # Fix Zero
    assert 'A1 bed' in dialog.info.text()
    dialog.zero_mode.setCurrentIndex(dialog.zero_mode.findData('values'))
    dialog.update_preview()
    assert dialog.plate.panels[0]['zero_reference'] is False
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path / 'out.3mf'), ''))
    dialog.export('3mf')
    files = _read(tmp_path / 'out.3mf')
    cfg = json.loads(files['Metadata/project_settings.config'])
    assert cfg['printer_settings_id'] == 'Bambu Lab A1 0.4 nozzle' and '#FF0000' in cfg['filament_colour']
    dialog.bambu_project.setChecked(False)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path / 'plain.3mf'), ''))
    dialog.export('3mf')
    assert 'Metadata/project_settings.config' not in _read(tmp_path / 'plain.3mf')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path / 'out.step'), ''))
    dialog.export('step')
    assert check_step((tmp_path / 'out.step').read_text())['solids'] >= 3
    dialog.close()
