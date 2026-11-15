"""V10 crop + sidebar regression checks (Qt UI interactions tested when available)."""
from pathlib import Path
import numpy as np
import pytest

from spm_studio.core.cropping import CropRegion, crop_channel
from spm_studio.core.models import Channel, Geometry, ROI, ProcessingStep
from spm_studio.core.processing import apply

UI = Path(__file__).resolve().parents[1] / 'src' / 'spm_studio' / 'ui'


def _channel(name, shape=(200, 200)):
    geometry = Geometry(shape, (20e-9, 20e-9), (0., 0.), 0.)
    data = np.arange(np.prod(shape), dtype=float).reshape(shape)
    return Channel(name, 'm', {'forward': data}, geometry)


def test_same_area_across_channels_and_processing_is_not_lost():
    z = _channel('Z')
    shift = _channel('OC M1 Freq Shift')
    exc = _channel('OC M1 Excitation')
    region = CropRegion.from_roi(ROI('rectangle', ((40, 30), (139, 129))), z.geometry)
    outputs = [crop_channel(original, region) for original in (z, shift, exc)]
    assert all(out.geometry.shape == (100, 100) for out in outputs)
    assert all(out.geometry.size_m == (10e-9, 10e-9) for out in outputs)
    assert all(out.geometry.center_m == outputs[0].geometry.center_m for out in outputs)
    steps = [ProcessingStep('plane'), ProcessingStep('row_median'), ProcessingStep('fix_zero')]
    raw = outputs[0].get('forward')
    np.testing.assert_array_equal(raw, z.get('forward')[30:130, 40:140])
    assert raw.flags.writeable is False
    assert len(steps) == 3
    processed = apply(raw, steps)
    assert processed.shape == raw.shape
    np.testing.assert_array_equal(raw, z.get('forward')[30:130, 40:140])


def test_repeat_crop_uses_original_source_not_previously_cropped_pixels():
    z = _channel('Z')
    first = CropRegion.from_roi(ROI('rectangle', ((20, 20), (119, 119))), z.geometry)
    level = crop_channel(z, first)
    second = CropRegion.from_roi(ROI('rectangle', ((10, 10), (59, 59))), level.geometry, first)
    final = crop_channel(z, second)
    np.testing.assert_array_equal(final.get('forward'), z.get('forward')[30:80, 30:80])
    assert final.geometry.shape == (50, 50)


def test_ui_source_has_crop_reuse_on_profile_and_multiview():
    window = (UI / 'main_window.py').read_text()
    assert 'CropRegionButton_v10' in window
    assert 'ResetCropButton_v10' in window
    assert 'ShowMetadataButton_v10' in window
    assert 'self._ensure_session_crop(channel)' in window
    assert 'for name in resolved:' in window and 'self._ensure_session_crop(name)' in window
    assert 'for name in previously|visible|{channel}:' in window
    assert '_crop_deferred' not in window
    assert 'self.scan.channels.update(self._crop_sources)' in window


def test_metadata_navigation_cannot_be_hidden_by_narrow_tab_bar():
    source = (UI / 'browser_panel.py').read_text()
    assert "('Files','Tools','Metadata')" in source
    assert 'self.tabs.tabBar().hide()' in source
    assert 'self.tab_navigation.addWidget' in source
    assert 'self.tabs.setCurrentWidget(self.metadata_panel)' in source


def test_qt_metadata_buttons_if_available(monkeypatch):
    pytest.importorskip('PySide6')
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from spm_studio.ui.browser_panel import BrowserPanel
    app = QApplication.instance() or QApplication([])
    panel = BrowserPanel()
    assert [b.text() for b in panel.tab_buttons] == ['Files', 'Tools', 'Metadata']
    assert all(b.isVisible() is False for b in panel.tab_buttons)  # panel not yet shown
    panel.show()
    app.processEvents()
    assert all(b.isVisible() for b in panel.tab_buttons)
    panel.tab_buttons[2].click()
    assert panel.tabs.currentWidget() is panel.metadata_panel
    panel.close()
