"""v0.8.0 — script figures identical to Export…, SVG-only results, design tokens, Pi RPC."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
HAS_QT = importlib.util.find_spec('PySide6') is not None


# ---------------------------------------------------------------- script figure helpers
def _viewer_cfg(channel='Z', colormap='viridis', lut=None, **extra):
    info = {'colormap': colormap, 'range_mode': 'percentile', 'low': 2., 'high': 98., 'gamma': 1.,
            'scale_bar': True, 'colorbar': True, 'title': '$Z$'}
    if lut is not None:
        info['lut'] = lut
    return {'schema_version': 1, 'viewer_config': {'enabled': True, 'channels': {channel: info}, **extra}}


def test_figure_formats_default_svg_only_and_ordered():
    from spm_studio.core.script_figures import figure_formats
    assert figure_formats(None) == ['svg']
    assert figure_formats(()) == ['svg']
    assert figure_formats(('png', 'svg', 'pdf', 'svg')) == ['svg', 'pdf', 'png']
    assert figure_formats(('bogus',)) == ['svg']


def test_scan_display_style_uses_viewer_colormap_not_gray():
    from spm_studio.core.script_figures import scan_display_style
    style = scan_display_style(_viewer_cfg(colormap='viridis'), 'Z')
    assert style.colormap == 'viridis'
    assert (style.range_mode, style.low, style.high) == ('percentile', 2., 98.)


def test_unknown_viewer_palette_is_registered_from_its_lut():
    from spm_studio.core.script_figures import scan_display_style
    from spm_studio.core import display
    table = [[0, 0, 0], [255, 0, 0], [255, 255, 255]]
    style = scan_display_style(_viewer_cfg(colormap='My lab palette.csv', lut=table), 'Z')
    assert style.colormap == 'My lab palette.csv'
    out = display.lut(style.colormap)
    assert tuple(out[0]) == (0, 0, 0) and tuple(out[-1]) == (255, 255, 255)
    assert out[128][0] == 255 and out[128][2] < 10   # middle is red


def test_colormap_override_and_style_roundtrip():
    from spm_studio.core.script_figures import scan_display_style, style_to_dict, style_from_dict
    style = scan_display_style(_viewer_cfg(colormap='gray'), 'Z', colormap_override='magma')
    assert style.colormap == 'magma'
    again = style_from_dict(style_to_dict(style))
    assert again == style
    # 'Current scan display' keeps the viewer colormap
    assert scan_display_style(_viewer_cfg(colormap='copper'), 'Z', colormap_override='Current scan display').colormap == 'copper'


def test_export_preset_comes_from_main_window_selection():
    from spm_studio.core.script_figures import export_preset
    cfg = _viewer_cfg(export_preset={'schema_version': 1, 'name': 'double_column', 'width_mm': 178.,
                                     'height_mm': 115., 'dpi': 1200, 'font_family': 'DejaVu Sans',
                                     'font_size_pt': 9, 'margin_mm': 4})
    assert export_preset(cfg)['width_mm'] == 178.
    assert export_preset({'schema_version': 1})['name'] == 'single_column'


def test_lattice_module_no_longer_writes_gray_preview_png():
    source = (ROOT / 'scripts/lattice_measurements/module.py').read_text()
    assert "lattice_preview.png" not in source
    assert 'export_scan_figure' in source
    assert "'display_style':figures.style_to_dict(style)" in source
    manifest = json.loads((ROOT / 'scripts/lattice_measurements/module.json').read_text())
    assert manifest['parameters']['export_gwy']['default'] is False
    molecule = json.loads((ROOT / 'scripts/molecule_placement/module.json').read_text())
    assert molecule['parameters']['export_gwy']['default'] is False


# ---------------------------------------------------------------- results library
def test_public_files_lists_svg_once(tmp_path):
    from spm_studio.core.result_library import public_files
    run = tmp_path / 'SPM_Studio_Results' / 'scan' / 'Data' / 'lattice_measurements_20261114_101010_abcdef'
    run.mkdir(parents=True)
    images = run.parent.parent / 'Images'
    images.mkdir()
    for ext in ('svg', 'pdf'):
        (images / f'{run.name}__07_reference_scan_lattice_overlay.{ext}').write_text('x')
    files = public_files(run)
    assert [f.suffix for f in files] == ['.svg']


# ---------------------------------------------------------------- factory upgrade of user scripts
def test_v080_upgrade_replaces_unmodified_070_tools_and_keeps_edits(tmp_path, monkeypatch):
    from spm_studio.core import paths
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    bundled = tmp_path / 'bundle'
    for module in paths.V080_FACTORY_PREVIOUS_SHA256:
        (bundled / 'scripts' / module).mkdir(parents=True)
        for name in paths.V080_FACTORY_PREVIOUS_SHA256[module]:
            (bundled / 'scripts' / module / name).write_text(f'new {module}/{name}\n')
    monkeypatch.setattr(paths, 'bundled_studio_root', lambda: bundled)
    installed = paths.scripts_dir() / 'lattice_measurements'
    installed.mkdir(parents=True)
    # Fake "0.7.0" file: make its digest match the table entry.
    old = b'old shipped module.py'
    monkeypatch.setitem(paths.V080_FACTORY_PREVIOUS_SHA256['lattice_measurements'], 'module.py',
                        hashlib.sha256(old).hexdigest())
    (installed / 'module.py').write_bytes(old)
    (installed / 'module.json').write_text('{"edited": true}')
    notes = paths.upgrade_factory_tools_v080()
    assert (installed / 'module.py').read_text() == 'new lattice_measurements/module.py\n'
    assert (paths.scripts_dir() / '.factory_backups_v080' / 'lattice_measurements' / 'module.py').read_bytes() == old
    assert (installed / 'module.json').read_text() == '{"edited": true}'
    assert any('kept' in n for n in notes)
    paths.upgrade_factory_tools_v080(force=True)
    assert (installed / 'module.json').read_text().startswith('new ')


def test_old_factory_themes_retired_but_custom_kept(tmp_path, monkeypatch):
    from spm_studio.core import paths
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    themes = paths.customization_dir() / 'themes'
    themes.mkdir(parents=True)
    original = (b'{\n  "schema_version": 1,\n  "background": "#17191C",\n  "surface": "#353A40",\n'
                b'  "foreground": "#F4F5F6",\n  "accent": "#57758B",\n  "muted": "#B0BAC2"\n}\n')
    (themes / 'default_dark.json').write_bytes(original)
    (themes / 'default_light.json').write_text('{"schema_version":1,"accent":"#ff0000"}')
    if hashlib.sha256(original).hexdigest() != 'e47408806d1a40167477c1c9b9cb1234fc1086d35edf7bc3f005e0fb42fbb810':
        pytest.skip('fixture bytes differ from the shipped 0.7.0 theme')
    paths.migrate_themes_v080()
    assert not (themes / 'default_dark.json').exists()
    assert (themes / 'default_light.json').exists()


# ---------------------------------------------------------------- design system
def test_design_tokens_complete_and_stylesheet_resolved():
    from spm_studio.shared import appearance as a
    for name, base in a.BUILTIN_THEMES.items():
        tokens = a.complete_tokens(base)
        assert set(a.COLOR_TOKENS) <= set(tokens)
        qss = a.stylesheet(tokens, '/tmp/assets')
        assert '@' not in qss.replace('@media', '')
        assert qss.count('{') == qss.count('}')
    # Only five colours are needed for a full theme (old theme files keep working)
    legacy = a.complete_tokens({'background': '#171e28', 'surface': '#202b36', 'foreground': '#f4f6f7',
                                'accent': '#c90021', 'muted': '#a4aeb9'})
    assert legacy['accent'] == '#c90021' and legacy['border'].startswith('#')


def test_accent_text_has_readable_contrast():
    from spm_studio.shared.appearance import complete_tokens, luminance
    for accent in ('#3FB8A6', '#0F7C6F', '#C90021', '#FFD166', '#57758B'):
        t = complete_tokens({'accent': accent})
        la, lf = luminance(accent), luminance(t['accent_fg'])
        ratio = (max(la, lf) + .05) / (min(la, lf) + .05)
        assert ratio >= 4.0, (accent, t['accent_fg'], ratio)


def test_theme_files_validate_with_optional_font_and_radius():
    from spm_studio.core.presets import validate_theme
    for path in sorted((ROOT / 'customization/themes').glob('*.json')):
        tokens = validate_theme(json.loads(path.read_text()))
        assert tokens['accent'].startswith('#')
    with pytest.raises(ValueError):
        validate_theme({'schema_version': 1, 'font_size': 99})
    assert validate_theme({'schema_version': 1, 'radius': 0})['radius'] == 0


def test_bundled_font_license_present():
    fonts = ROOT / 'src/spm_studio/resources/fonts'
    assert (fonts / 'OFL.txt').read_text().startswith('Inter font family')
    assert (fonts / 'Inter-Regular.otf').stat().st_size > 100_000


# ---------------------------------------------------------------- Pi RPC protocol
def test_rpc_reducer_dialogs_status_and_old_agent_end():
    from spm_studio.ai.rpc_events import RpcEvents
    r = RpcEvents()
    assert r.interpret({'type': 'extension_ui_request', 'id': '1', 'method': 'select'})[0] == 'extension_dialog'
    assert r.interpret({'type': 'extension_ui_request', 'id': '2', 'method': 'notify', 'message': 'routed: fast'}) == ('status', 'routed: fast')
    assert r.interpret({'type': 'agent_end'}) == ('done', 'agent_end')
    err = r.interpret({'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': 'error', 'errorMessage': 'rate limit'}})
    assert err == ('log', 'Model: rate limit')


def test_pi_install_uses_current_package_name():
    # v0.8.2: the guided installer lives in pi_setup.py
    source = (ROOT / 'src/spm_studio/ai/pi_setup.py').read_text()
    assert "PI_PACKAGE = '@earendil-works/pi-coding-agent'" in source


# ---------------------------------------------------------------- Qt: parity with Export…
@pytest.mark.skipif(not HAS_QT, reason='PySide6 not installed in this test environment')
def test_script_figure_is_pixel_identical_to_export_panel(tmp_path):
    """Without overlay, a script figure must equal a one-panel Export… of the same data."""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])
    from PIL import Image
    from spm_studio.core.models import Scan, Channel, Geometry, ImageStyle
    from spm_studio.core.export_layout import export_publication
    from spm_studio.core.script_figures import export_scan_figure
    from spm_studio.core.presets import DEFAULT_EXPORT
    rng = np.random.default_rng(3)
    data = rng.normal(size=(96, 128)).astype(float)
    geo = Geometry(shape=(96, 128), size_m=(12e-9, 9e-9))
    src = tmp_path / 'scan.sxm'
    src.write_bytes(b'fixture')
    scan = Scan(path=src, channels={'Z': Channel('Z', 'm', {'forward': data}, geo)}, metadata={})
    style = ImageStyle(colormap='viridis', range_mode='percentile', low=2, high=98)
    preset = dict(DEFAULT_EXPORT)
    spec = {'kind': 'channel', 'channel': 'Z', 'trace': 'forward', 'title': 'Z', 'unit': '', 'style': style,
            'colorbar_position': 'below', 'show_colorbar': True, 'scale_bar_color': '#000000',
            'scale_bar_position': 'bottom_right', 'show_scale_bar': True, 'steps': []}
    a = export_publication(scan, [spec], tmp_path / 'panel.png', preset, panel_letters=False)
    b = export_scan_figure(tmp_path / 'script', scan_path=src, data=data, size_nm=(12., 9.), channel='Z',
                           unit='m', plot_config={'schema_version': 1}, formats=('png',), style=style,
                           title='Z', scale_bar_color='#000000', preset=preset)[0]
    pa, pb = np.asarray(Image.open(a).convert('RGB')), np.asarray(Image.open(b).convert('RGB'))
    assert pa.shape == pb.shape
    assert np.abs(pa.astype(int) - pb.astype(int)).max() <= 2


# ---------------------------------------------------------------- v0.8.1 agent workspace
def test_chat_agent_defaults_and_context_file(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'c'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'd'))
    from spm_studio.ai import config
    conf = config.load()
    assert conf['chat_tools'] is True and conf['chat_tools_ack'] is False   # asks once, then tools on
    from spm_studio.core import paths
    text = config.spm_context_file(paths.scripts_dir()).read_text()
    assert str(paths.scripts_dir()) in text and 'module.json' in text and 'without' not in text.split('NO restart')[0][-5:]
    assert 'never send commands to microscopes' in text


def test_pi_rpc_passes_context_and_tools_flags():
    source = (ROOT / 'src/spm_studio/ai/pi_rpc.py').read_text()
    assert "'--append-system-prompt'" in source and "args += ['--no-tools']" in source
    # v0.1.0: the assistant is Agent Hub: Pi gets the context and the approval gate; tools are built in the
    # Scripts project (staging folder, then "Install a staged tool")
    core = (ROOT / 'src/agent_hub/core.py').read_text(encoding='utf8')
    assert "'--append-system-prompt'" in core and "args += ['-e', self.gate]" in core
    develop = (ROOT / 'src/spm_studio/assistant/develop.py').read_text(encoding='utf8')
    assert 'install_staged' in develop and 'README_SCRIPT.md' in develop
    window = (ROOT / 'src/spm_studio/ui/main_window.py').read_text()
    assert '_start_scripts_watch' in window and 'New tool available in Tools' in window
