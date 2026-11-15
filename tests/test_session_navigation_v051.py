"""Session/list navigation regression tests for v0.5.1.

Qt tests run offscreen on machines with PySide6. They are intentionally skipped
when Qt is not installed; no screenshot result is substituted for a GUI test.
"""
from pathlib import Path
import pytest


def test_customization_guide_upgrades_only_if_unmodified(tmp_path,monkeypatch):
    from spm_studio.core.paths import customization_dir,upgrade_factory_customization_v051
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    target=customization_dir()/'README_CUSTOMIZATION.md'
    original=Path(__file__).resolve().parent/'fixtures'/'README_CUSTOMIZATION_v050.md'
    target.write_bytes(original.read_bytes())
    notes=upgrade_factory_customization_v051()
    assert any('updated' in note for note in notes)
    assert 'horizontally scrollable' in target.read_text(encoding='utf8')
    assert (target.parent/'.factory_backups_v051'/'README_CUSTOMIZATION.md').read_bytes()==original.read_bytes()
    other=tmp_path/'different'
    monkeypatch.setenv('XDG_CONFIG_HOME',str(other))
    user_target=customization_dir()/'README_CUSTOMIZATION.md'
    user_target.write_text(original.read_text()+'\n# Custom notes\n',encoding='utf8')
    notes=upgrade_factory_customization_v051()
    assert any('local edits' in note for note in notes)
    assert user_target.read_text().endswith('# Custom notes\n')


def test_profile_accepts_many_simultaneous_channels():
    from spm_studio.core.presets import validate_profile, DEFAULT_PROFILE
    profile={**DEFAULT_PROFILE,'visible_channels':[f'C{i}' for i in range(16)]}
    assert len(validate_profile(profile)['visible_channels'])==16


def test_cache_evicts_one_scan_without_flushing_others():
    from spm_studio.core.cache import ArrayCache
    cache=ArrayCache(1)
    cache.put(('scan',('/a/one.sxm',123,9)),'scan-one',size=100)
    cache.put(('scan',('/a/two.sxm',124,9)),'scan-two',size=100)
    cache.evict_scan(Path('/a/one.sxm'))
    assert cache.get(('scan',('/a/one.sxm',123,9))) is None
    assert cache.get(('scan',('/a/two.sxm',124,9)))=='scan-two'
    assert cache.memory_bytes==100


# Running the remaining tests requires working Qt bindings.
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PySide6.QtCore import Qt, QSettings
    from PySide6.QtWidgets import QApplication, QListWidgetItem
except ImportError:
    Qt=None


@pytest.fixture
def app():
    if Qt is None:
        pytest.skip('PySide6 is not installed')
    return QApplication.instance() or QApplication([])


def test_browser_navigation_and_removal_does_not_unlink_source(app,tmp_path):
    from spm_studio.ui.browser_panel import BrowserPanel
    panel=BrowserPanel();panel.show();app.processEvents()
    selected=[];removed=[]
    panel.fileSelected.connect(selected.append)
    panel.removeRequested.connect(removed.append)
    files=[tmp_path/f'scan{i}.sxm' for i in range(5)]
    for path in files:
        path.write_bytes(b'fixture')
        item=QListWidgetItem(path.name)
        item.setData(Qt.ItemDataRole.UserRole,str(path))
        panel.files.addItem(item)
    panel.files.setCurrentRow(1)
    assert panel.select_relative_file(1)
    assert selected[-1]==str(files[2])
    panel.file_search.setText('scan4')
    assert panel.select_relative_file(1)
    assert selected[-1]==str(files[4])
    panel.request_remove_selected()
    assert removed[-1]==str(files[4])
    assert files[4].exists()  # requesting removal NEVER deletes a physical file
    panel.close()


def test_inspector_supports_more_than_four_visible_channels(app):
    import numpy as np
    from spm_studio.core.models import Channel, Geometry, Scan
    from spm_studio.ui.inspector_panel import InspectorPanel
    channel_names=['Z','Bias','Current','dF','Excitation','Phase','Amplitude']
    a=np.zeros((8,8),dtype=np.float32)
    scan=Scan(Path('/tmp/example.sxm'),{
        name:Channel(name,'V',{'forward':a},Geometry((8,8)))
        for name in channel_names})
    panel=InspectorPanel();panel.show();app.processEvents()
    panel.set_channels(scan,'Z')
    panel.set_visible_channels(channel_names)
    assert panel.visible_channel_names()==channel_names
    panel.close()


def test_main_window_starts_empty_and_keeps_appearance_only(app,monkeypatch,tmp_path):
    from spm_studio.ui.main_window import MainWindow
    # Exercise the normal desktop settings route even when the full-suite
    # runner supplies an isolated Research Studio data directory.
    monkeypatch.delenv('RESEARCH_STUDIO_DATA', raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    monkeypatch.setenv('XDG_CACHE_HOME',str(tmp_path/'cache'))
    # Isolate QSettings from real user accounts and protect their preferences.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path/'config'))
    saved=QSettings('SPM Studio','SPM Modular Studio')
    saved.setValue('theme','default_dark')
    saved.setValue('last_file','/tmp/old-file.sxm')
    saved.setValue('masks_abcd','[{"name":"old"}]')
    saved.setValue('plot_format','pdf')
    saved.sync()
    window=MainWindow();window.show();app.processEvents()
    assert window.scan is None
    assert window.browser.files.count()==0
    assert window.module_panel.masks==[]
    assert window.settings.value('last_file') is None
    assert window.settings.value('masks_abcd') is None
    # Legacy default_dark is migrated to the current graphite theme.
    assert window.settings.value('theme')=='graphite'
    assert window.settings.value('plot_format')=='pdf'
    window.close()


def test_multichannel_keyboard_navigation_and_remove(app,monkeypatch,tmp_path):
    """End-to-end GUI behavior: multi-view, next scan and disk-safe removal."""
    from PySide6.QtTest import QTest
    from spm_studio.ui.main_window import MainWindow
    from test_fast_scan_opening import create_large_sparse_sxm

    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'data'))
    monkeypatch.setenv('XDG_CACHE_HOME',str(tmp_path/'cache'))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path/'config'))

    one=create_large_sparse_sxm(tmp_path/'one.sxm',nx=64,ny=64,channels=7)
    two=create_large_sparse_sxm(tmp_path/'two.sxm',nx=64,ny=64,channels=7)
    win=MainWindow();win.resize(1450,900);win.show();app.processEvents()

    def wait_for_path(path):
        # The global pool can still be finishing a scientific job from another
        # integration test. Keep processing GUI events while waiting for this
        # asynchronous reader rather than assuming an idle machine.
        for _ in range(500):
            if win.scan is not None and win.scan.path==path:
                return
            QTest.qWait(20)
        pytest.fail(f'Scan {path.name} failed to open during GUI test; '
                    f'status: {win.statusBar().currentMessage()}; '
                    f'pending: {win._pending_load_path}; tasks: {len(win._active_tasks)}')

    win._add_file(one)
    wait_for_path(one)
    win._add_file(two)
    channels=[f'C{i}' for i in range(7)]
    win.inspector.set_visible_channels(channels)
    app.processEvents();QTest.qWait(80)
    assert win.inspector.visible_channel_names()==channels
    assert len(win._secondary_views)==6
    assert win.channel_scroll.horizontalScrollBar().maximum()>0

    win.viewer.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(win.viewer,Qt.Key.Key_Down)
    wait_for_path(two)
    # v13: a newly opened scan does not inherit the first scan's profile.
    assert win.inspector.visible_channel_names()==['C0']
    assert win.browser.files.currentRow()==1
    win.browser.files.setCurrentRow(0)
    wait_for_path(one)
    assert win.inspector.visible_channel_names()==channels
    win.browser.files.setCurrentRow(1)
    wait_for_path(two)
    assert win.inspector.visible_channel_names()==['C0']

    win.remove_scan()
    assert two.exists()
    assert win.browser.files.count()==1
    wait_for_path(one)
    win.remove_scan()
    assert one.exists()
    assert win.scan is None
    assert win.browser.files.count()==0
    assert win.viewer.image is None
    win.close()
