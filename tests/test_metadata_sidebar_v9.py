"""Metadata sidebar: native SXM header integrity, GWY fields and UI wiring."""
from pathlib import Path
import sys
import types
import numpy as np
import pytest
from spm_studio.core.io import read_scan
from spm_studio.core.metadata_display import metadata_text, metadata_json, original_header


def _fixture_sxm(path: Path):
    header = ('\r\n'.join([
        ':SCAN_PIXELS:', '4 3', ':SCAN_RANGE:', '20e-9 20e-9',
        ':SCAN_OFFSET:', '2e-9 -3e-9', ':SCAN_ANGLE:', '45',
        ':BIAS:', '0.53', ':ACQ_TIME:', '0.003',
        ':SCANIT_TYPE:', 'FLOAT MSBFIRST', ':DATA_INFO:',
        'Channel\tName\tUnit\tDirection\tCalibration\tOffset',
        '0\tZ\tm\tboth\t1\t0',
        ':SCANIT_END:'
    ]) + '\r\n').encode('latin-1')
    path.write_bytes(header + b'\x1a\x04' + np.arange(24, dtype='>f4').tobytes())
    return path


def test_complete_sxm_parameters_and_exact_original_header(tmp_path):
    scan = read_scan(_fixture_sxm(tmp_path/'molecule.sxm'))
    content = metadata_text(scan)
    assert 'SCAN PIXELS' not in content  # Preserve original key spelling.
    for token in ('SCAN_PIXELS:', '20e-9 20e-9', 'SCAN_OFFSET:',
                  'BIAS:', '0.53', 'ACQ_TIME:', '0.003', 'Z',
                  '20 × 20 nm', 'Number of channels: 1'):
        assert token in content
    raw = original_header(scan)
    assert ':SCAN_PIXELS:\r\n4 3\r\n' in raw
    assert ':ACQ_TIME:\r\n0.003\r\n' in raw
    assert raw == scan.metadata['raw_header']
    assert '"header"' in metadata_json(scan)
    assert '"raw_header"' in metadata_json(scan)
    assert scan.channels['Z'].get('forward').flags.writeable is False


def test_gwy_preserves_extra_nested_metadata_without_copying_rasters(tmp_path, monkeypatch):
    a = np.ones((3, 4), dtype=float)
    field = types.SimpleNamespace(data=a, xreal=4e-9, yreal=3e-9,
                                  si_unit_xy=types.SimpleNamespace(unitstr='m'),
                                  si_unit_z=types.SimpleNamespace(unitstr='V'))
    gwy_container = {'/0/data': field, '/0/data/title': 'Bias',
                     '/0/meta': {'Setpoint': '25 pA', 'BIAS': '0.45 V'},
                     '/0/base/palette': 'Gold', '/meta/experiment': 'UHV KPFM'}
    fake = types.SimpleNamespace(load=lambda _: gwy_container,
                                 util=types.SimpleNamespace(get_datafields=lambda _ : {}))
    monkeypatch.setitem(sys.modules, 'gwyfile', fake)
    path = tmp_path/'kpfm.gwy'; path.write_bytes(b'fake')
    scan = read_scan(path)
    content = metadata_text(scan)
    for token in ('Setpoint:', '25 pA', 'BIAS:', '0.45 V',
                  '/0/base/palette:', 'Gold', 'UHV KPFM'):
        assert token in content
    assert len(scan.metadata['gwy_metadata']) == 4
    assert '/0/data' not in scan.metadata['gwy_metadata']
    assert 'No original plain-text instrument header' in original_header(scan)


def test_metadata_formats_do_not_mutate_source(tmp_path):
    scan = read_scan(_fixture_sxm(tmp_path/'source.sxm'))
    before = scan.path.read_bytes()
    for _ in range(2):
        assert metadata_text(scan)
        assert metadata_json(scan)
        assert original_header(scan)
    assert scan.path.read_bytes() == before


def test_left_sidebar_metadata_tab_and_search(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from spm_studio.ui.browser_panel import BrowserPanel
    app = QApplication.instance() or QApplication([])
    panel = BrowserPanel(); panel.show()
    assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == ['Files', 'Tools', 'Metadata']
    assert panel.metadata_panel.document.isReadOnly()
    scan = read_scan(_fixture_sxm(tmp_path/'source.sxm'))
    panel.metadata_panel.set_scan(scan)
    panel.tabs.setCurrentIndex(2)
    assert 'ACQ_TIME' in panel.metadata_panel.document.toPlainText()
    panel.metadata_panel.search.setText('ACQ_TIME')
    assert 'Match: ACQ_TIME' in panel.metadata_panel.status.text()
    panel.metadata_panel.view_mode.setCurrentIndex(1)
    assert ':ACQ_TIME:' in panel.metadata_panel.document.toPlainText()
    panel.metadata_panel.copy_all.click()
    assert QApplication.clipboard().text() == panel.metadata_panel.document.toPlainText()
    panel.metadata_panel.clear()
    assert panel.metadata_panel.document.toPlainText() == ''
    panel.close(); app.processEvents()
