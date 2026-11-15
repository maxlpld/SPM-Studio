"""v14: actual SVG picker binding and stale installed module cleanup."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'src/spm_studio'


def test_factory_molecule_tool_and_obsolete_tools_removed():
    from spm_studio.core.registry import discover_modules,load_manifest
    scripts,issues=discover_modules([ROOT/'scripts'])
    assert issues==[]
    assert 'batch_scan_report' not in scripts
    assert not (SRC/'builtin_modules'/'batch_scan_report').exists()
    assert not (SRC/'builtin_modules'/'molecule_placement').exists()
    molecule=load_manifest(ROOT/'scripts/molecule_placement/module.json')
    assert molecule.id=='molecule_placement'
    assert molecule.status=='experimental'
    assert molecule.version=='0.10.0'
    assert molecule.parameters['molecule_image']['type']=='file'
    assert molecule.selection['preview']=='molecule_placement'
    for field in ('molecule_width_nm','molecule_height_nm','rotation_offset_deg','molecule_count'):
        assert field in molecule.parameters


def test_migrate_legacy_molecule_and_retire_batch_on_existing_install(tmp_path,monkeypatch):
    from spm_studio.core import paths
    local=tmp_path/'scripts';local.mkdir()
    monkeypatch.setattr(paths,'scripts_dir',lambda:local)
    monkeypatch.setattr(paths,'bundled_studio_root',lambda:ROOT)
    old=local/'molecule_placement';old.mkdir()
    old_manifest={'api_version':'1.0','id':'molecule_placement','name':'Physically informed placement',
                  'status':'unavailable'}
    (old/'module.json').write_text(json.dumps(old_manifest))
    (old/'module.py').write_text('custom legacy source; preserve my changes\n')
    batch=local/'batch_scan_report';batch.mkdir()
    (batch/'module.json').write_text(json.dumps({'id':'batch_scan_report','name':'Batch scan report'}))
    (batch/'my_notes.txt').write_text('keep these notes')
    notices=paths.synchronize_molecule_tools_v14()
    assert notices
    assert not batch.exists()
    assert json.loads((old/'module.json').read_text())['version']=='0.10.0'
    assert (old/'preview_worker.py').exists()
    backups=local/'.factory_backups_v14'
    assert any(p.read_text()=='keep these notes' for p in backups.rglob('my_notes.txt'))
    assert any('custom legacy source' in p.read_text() for p in backups.rglob('module.py'))
    # Later user customizations should survive repeated starts.
    (old/'module.py').write_text('# deliberate user edit\n')
    assert paths.synchronize_molecule_tools_v14()==[]
    assert (old/'module.py').read_text()=='# deliberate user edit\n'
    assert not batch.exists()


def test_molecule_file_picker_bound_to_real_run_parameter():
    panel=(SRC/'ui/module_panel.py').read_text()
    window=(SRC/'ui/main_window.py').read_text()
    ast.parse(panel);ast.parse(window)
    assert 'LoadMoleculeSVG_v14' in panel
    assert 'Load molecule SVG / PNG…' in panel
    assert 'self.widgets[name]=self.molecule_file_path' in panel
    assert 'self.molecule_file_path.setText(chosen)' in panel
    assert 'self.molecule_file_path.textChanged.connect(self.changed)' in panel
    assert 'self.module_panel.values()' in window
    assert 'paths.synchronize_molecule_tools_v14()' in window
    assert "mod.id=='batch_scan_report'" in window


def test_picker_really_opens_svg_and_is_used_as_analysis_input(tmp_path,monkeypatch):
    """Real Qt interaction test; runs on a workstation with PySide6 installed."""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication,QFileDialog
    from spm_studio.core.registry import load_manifest,validate_params
    from spm_studio.ui.module_panel import ModulePanel
    app=QApplication.instance() or QApplication([])
    doc=tmp_path/'my molecule.svg'
    doc.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="100"><rect x="5" y="5" width="145" height="80" fill="red"/></svg>')
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args,**kwargs:(str(doc),'SVG'))
    panel=ModulePanel()
    panel.set_module(load_manifest(ROOT/'scripts/molecule_placement/module.json'))
    assert not panel.artwork_group.isHidden()
    panel.molecule_file_button.click()
    assert panel.molecule_file_path.text()==str(doc)
    assert 'Loaded:' in panel.molecule_artwork_status.text()
    assert panel.molecule_artwork_thumbnail.pixmap() is not None
    values=panel.values()
    assert values['molecule_image']==str(doc)
    params=validate_params(panel.module,values)
    assert params['molecule_image']==str(doc)
    assert float(params['molecule_width_nm'])>0
    assert float(params['molecule_height_nm'])>0
    panel.deleteLater()
