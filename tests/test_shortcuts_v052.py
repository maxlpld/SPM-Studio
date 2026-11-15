"""Shortcut profile validation plus optional Qt keyboard navigation regressions."""
import json
from pathlib import Path
import pytest
from spm_studio.core.shortcuts import (
    ACTIONS, ACTION_BY_ID, DEFAULT_BINDINGS, ShortcutConfigError,
    default_profile, load_profile, read_profiles, validate_profile, write_profile,
)


def test_registry_has_unique_ids_and_defaults():
    assert len(ACTIONS)>=50
    assert len(ACTION_BY_ID)==len(ACTIONS)
    assert len({a.default.casefold() for a in ACTIONS})==len(ACTIONS)
    assert DEFAULT_BINDINGS['nav.scan_previous']=='Up'
    assert DEFAULT_BINDINGS['nav.channel_right']=='Right'
    assert DEFAULT_BINDINGS['tool.run']=='Ctrl+R'
    assert DEFAULT_BINDINGS['options.shortcuts']=='Ctrl+Alt+K'


def test_partial_json_keeps_the_unmodified_defaults(tmp_path):
    profile={'schema_version':1,'name':'personal','bindings':{
        'nav.scan_next':'Alt+S','nav.scan_previous':'Alt+W',
        'nav.channel_left':'Alt+A','nav.channel_right':'Alt+D'}}
    path=tmp_path/'personal.json'
    write_profile(path,profile)
    result=load_profile(path)
    assert result['bindings']['nav.scan_next']=='Alt+S'
    assert result['bindings']['file.open']=='Ctrl+O'
    assert result['bindings']['tool.run']=='Ctrl+R'
    assert len(result['bindings'])==len(ACTIONS)
    assert read_profiles(tmp_path)['personal']['name']=='personal'


def test_profile_can_unbind_shortcuts(tmp_path):
    p=default_profile('blank')
    p['bindings']['view.clear_roi']=''
    write_profile(tmp_path/'blank.json',p)
    assert load_profile(tmp_path/'blank.json')['bindings']['view.clear_roi']==''


@pytest.mark.parametrize('modify',[
    lambda d:d.update(schema_version=999),
    lambda d:d.update(name='../other'),
    lambda d:d['bindings'].update({'nonexistent.action':'Ctrl+Y'}),
    lambda d:d['bindings'].update({'nav.scan_next':'Up'}),
    lambda d:d['bindings'].update({'tool.run':101}),
    lambda d:d['bindings'].update({'tool.run':'K'*81}),
])
def test_invalid_profiles_rejected(modify):
    profile=default_profile('bad')
    modify(profile)
    with pytest.raises(ShortcutConfigError):validate_profile(profile)


def test_invalid_import_keeps_existing_profile_untouched(tmp_path):
    path=tmp_path/'saved.json'
    write_profile(path,default_profile('saved'))
    previous=path.read_bytes()
    invalid=default_profile('saved')
    invalid['bindings']['tool.run']='Ctrl+O'
    with pytest.raises(ShortcutConfigError):write_profile(path,invalid)
    assert path.read_bytes()==previous


def test_import_profile_does_not_execute_python(tmp_path):
    sentinel=tmp_path/'executed'
    malicious={'schema_version':1,'name':'safe_name','bindings':{
        'file.open':"__import__('os').system('touch %s')"%sentinel}}
    path=tmp_path/'safe_name.json'
    path.write_text(json.dumps(malicious),encoding='utf-8')
    # Non-Qt validator accepts a string as data; the Qt validator rejects
    # invalid key notation. Neither calls eval/exec or runs arbitrary code.
    try:
        load_profile(path)
    except ShortcutConfigError:
        pass  # Also valid: reject the value as an invalid shortcut string.
    assert not sentinel.exists()


def test_corrupted_user_default_falls_back_to_registered_defaults(tmp_path):
    (tmp_path/'default.json').write_text('not JSON',encoding='utf8')
    result=read_profiles(tmp_path)
    assert result['default']['bindings']==DEFAULT_BINDINGS
    # The corrupted file should not be overwritten without the user's consent.
    assert (tmp_path/'default.json').read_text()=='not JSON'


import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PySide6.QtCore import Qt,QSettings
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    Qt=None


@pytest.fixture
def app():
    if Qt is None:pytest.skip('PySide6 is not available in the test environment')
    return QApplication.instance() or QApplication([])


def _isolated_window(app,monkeypatch,tmp_path):
    from spm_studio.ui.main_window import MainWindow
    for name,folder in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:
        monkeypatch.setenv(name,str(tmp_path/folder))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(tmp_path/'config'))
    win=MainWindow()
    win.show()
    app.processEvents()
    return win


def test_global_arrows_work_after_switching_file_and_panel_focus(app,monkeypatch,tmp_path):
    from PySide6.QtWidgets import QListWidgetItem
    win=_isolated_window(app,monkeypatch,tmp_path)
    calls=[]
    win._load_file=lambda path:calls.append(('file',path))
    win._scroll_channels=lambda way:calls.append(('channel',way))
    for i in range(4):
        item=QListWidgetItem(f'scan-{i}')
        item.setData(Qt.ItemDataRole.UserRole,str(tmp_path/f'{i}.sxm'))
        win.browser.files.addItem(item)
    win.browser.files.setCurrentRow(0)
    win.browser.files.setFocus()
    app.processEvents()
    QTest.keyClick(win.browser.files,Qt.Key.Key_Down)
    assert win.browser.files.currentRow()==1
    QTest.keyClick(win.browser.files,Qt.Key.Key_Right)
    assert calls[-1]==('channel',1)
    win.browser.tabs.setCurrentIndex(1)
    win.browser.tools.setFocus()
    QTest.keyClick(win.browser.tools,Qt.Key.Key_Down)
    assert win.browser.files.currentRow()==2
    QTest.keyClick(win.browser.tools,Qt.Key.Key_Left)
    assert calls[-1]==('channel',-1)
    win.inspector.setFocus()
    QTest.keyClick(win.inspector,Qt.Key.Key_Up)
    assert win.browser.files.currentRow()==1
    QTest.keyClick(win.inspector,Qt.Key.Key_Right)
    assert calls[-1]==('channel',1)
    win.close()


def test_remap_applies_to_nav_and_actions_without_restart(app,monkeypatch,tmp_path):
    win=_isolated_window(app,monkeypatch,tmp_path)
    calls=[]
    win._scroll_channels=lambda direction:calls.append(direction)
    profile=default_profile('remapped')
    profile['bindings'].update({'nav.channel_right':'Alt+D','nav.channel_left':'Alt+A',
                                'nav.scan_previous':'Alt+W','nav.scan_next':'Alt+S'})
    win._apply_shortcuts('remapped',profile['bindings'])
    win.browser.tools.setFocus()
    QTest.keyClick(win.browser.tools,Qt.Key.Key_D,Qt.KeyboardModifier.AltModifier)
    assert calls==[1]
    assert win._shortcut_actions['tool.run'].shortcut().toString()=='Ctrl+R'
    assert win.settings.value('shortcut_profile')=='remapped'
    win.close()


def test_shortcut_options_updates_reference_after_import_or_edit(app,monkeypatch,tmp_path):
    from spm_studio.ui.shortcut_options import ShortcutOptions
    folder=tmp_path/'shortcuts'
    write_profile(folder/'default.json',default_profile())
    widget=ShortcutOptions(folder,'default')
    changes=[]
    widget.bindingsChanged.connect(lambda name,keys:changes.append((name,keys)))
    chosen=default_profile('custom')
    chosen['bindings']['nav.scan_next']='Alt+S'
    chosen['bindings']['nav.scan_previous']='Alt+W'
    chosen['bindings']['nav.channel_left']='Alt+A'
    chosen['bindings']['nav.channel_right']='Alt+D'
    write_profile(folder/'custom.json',chosen)
    widget.reload_profiles('custom')
    assert changes and changes[-1][0]=='custom'
    row=next(i for i,a in enumerate(ACTIONS) if a.id=='nav.scan_next')
    assert widget.table.item(row,2).text()=='Alt+S'
    widget.close()
