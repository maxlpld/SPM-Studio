"""v32: auto-crop, overlay stack, customization, multi-line profiles, manual molecules."""
from pathlib import Path
import json
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_incomplete_scan_detection():
    from spm_studio.core.cropping import detect_incomplete_scan as d
    r = np.random.rand(64, 80)
    assert d(r) is None                       # complete scan: bypass, keep dimensions
    a = r.copy(); a[40:] = np.nan
    assert d(a) == (0, 40, 0, 80)
    b = r.copy(); b[:25] = 0
    assert d(b) == (25, 64, 0, 80)
    c = r.copy(); c[50:] = np.nan; c[49, 30:] = np.nan   # half-finished last line dropped
    assert d(c) == (0, 49, 0, 80)
    e = r.copy(); e[:, 70:] = .123
    assert d(e) == (0, 64, 0, 70)
    fwd, bwd = r.copy(), r.copy(); bwd[45:] = np.nan          # forward+backward intersection
    assert d(fwd, bwd) == (0, 45, 0, 80)
    with pytest.raises(ValueError):
        z = r.copy(); z[5:] = np.nan; d(z)


def test_afm_profiles_enable_autocrop():
    from spm_studio.core.presets import validate_profile
    for f in ('AFM_Dissipation_Excitation.json', 'AFM_Molecular_Resolution.json'):
        d = validate_profile(json.loads((ROOT / 'customization' / 'profiles' / f).read_text()))
        assert d['auto_crop_incomplete'] is True
    stm = validate_profile(json.loads((ROOT / 'customization' / 'profiles' / 'STM.json').read_text()))
    assert stm['auto_crop_incomplete'] is False


def test_overlay_viewer_channel_equal_to_layer_two_is_not_used_twice():
    from spm_studio.core.channel_overlay import make_layers
    img = np.zeros((4, 4)); data = {'Z': img, 'Exc': img + 1}
    layers = make_layers('Exc', img + 1, 'V', [], data.__getitem__, {}, {'channel_2': 'Exc', 'channel_3': 'Z'},
                         skip_duplicates=True)
    assert [l.name for l in layers] == ['Exc', 'Z']


def test_customization_validation_and_apply(tmp_path):
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt
    from spm_studio.core.plot_settings import DEFAULT_PLOT, validate_plot
    from spm_studio.core.plots import apply_figure_customization
    cfg = validate_plot(dict(DEFAULT_PLOT, colormap_override='afmhot', colorbar_mode='hide', legend_mode='hide',
                             text_replacements='Old title => New $x$'))
    fig, ax = plt.subplots()
    im = ax.imshow(np.random.rand(5, 5), cmap='gray'); cb = fig.colorbar(im)
    ax.plot([0, 1], [0, 1], label='a'); ax.legend(); ax.set_title('Old title')
    apply_figure_customization(fig, cfg)
    assert im.get_cmap().name == 'afmhot' and ax.get_legend() is None and ax.get_title() == 'New $x$'
    assert not cb.ax.get_visible()
    with pytest.raises(ValueError):
        validate_plot(dict(DEFAULT_PLOT, colorbar_mode='diagonal'))
    plt.close(fig)


def test_multi_line_profiles_cross_channel_and_csv(tmp_path):
    import matplotlib
    matplotlib.use('Agg', force=True)
    from spm_studio.core.multi_profiles import LineSpec, compute_profiles, build_figure, write_csv, write_wide_csv
    y, x = np.mgrid[0:100, 0:100]
    lines = [LineSpec(((0, 50), (99, 50)), (100, 100), 'L1', '#000000', graph=1),
             LineSpec(((50, 0), (50, 99)), (100, 100), 'L2', '#ff0000', graph=2, inset=False),
             LineSpec(((0, 0), (99, 99)), (100, 100), 'L3', '#00ff00', graph=2, inset=True)]
    chans = [{'name': 'Z', 'data': x * 1e-11, 'unit': 'm', 'size_m': (10e-9, 10e-9)},
             {'name': 'df', 'data': (y * 1.)[::2, ::2], 'unit': 'Hz', 'size_m': (10e-9, 10e-9)}]  # other grid
    pr = compute_profiles(lines, chans)
    assert len(pr) == 6
    assert pr[0].distance[-1] == pytest.approx(9.9, rel=1e-3)     # nm along L1
    # Same physical line on the half-resolution channel
    assert pr[3].points_px[0][1] == pytest.approx(24.75)
    fig = build_figure(pr, n_graphs=2)
    letters = sorted(t.get_text() for t in fig.texts if getattr(t, '_spm_panel_label', False))
    assert letters == ['a', 'b', 'c', 'd']
    write_csv(pr, tmp_path / 'p.csv'); write_wide_csv(pr, tmp_path / 'w.csv')
    head = (tmp_path / 'p.csv').read_text().splitlines()[0]
    assert head.startswith('line,channel,graph,inset,distance')


def test_manual_molecule_chain():
    from spm_studio.core.manual_molecules import Molecule, continue_chain, chain_step, nm_to_px, px_to_nm
    ms = [Molecule(1, 1, 0), Molecule(2, 1.5, 10)]
    out, n = continue_chain(ms, 3)
    assert n == 3 and out[-1].x_nm == pytest.approx(5) and out[-1].angle_deg == pytest.approx(40)
    out, n = continue_chain(ms, 10, bounds_nm=(5, 5))
    assert n == 3
    assert chain_step([Molecule(0, 0), Molecule(1.1, 0), Molecule(1.9, 0)], 'average')[0] == pytest.approx(.95)
    with pytest.raises(ValueError):
        continue_chain([Molecule(0, 0)], 2)
    c, r = nm_to_px(2.5, 1.0, (256, 128), (10, 20))
    assert px_to_nm(c, r, (256, 128), (10, 20)) == pytest.approx((2.5, 1.0))


def test_lattice_manifest_has_customization():
    m = json.loads((ROOT / 'scripts' / 'lattice_measurements' / 'module.json').read_text())
    for k in ('scan_colormap', 'fft_colormap', 'show_colorbar', 'overlay_title'):
        assert k in m['parameters']
    from spm_studio.core.registry import load_manifest
    assert load_manifest(ROOT / 'scripts' / 'lattice_measurements' / 'module.json').id


def test_v33_multi_format_export_names(tmp_path, monkeypatch):
    from spm_studio.core import export_layout as el
    calls = []
    monkeypatch.setattr(el, 'export_publication', lambda scan, panels, dest, preset, **kw: calls.append(dest) or dest)
    out = el.export_publication_formats(None, [], tmp_path / 'scan.0012_Z.pdf', {}, ['pdf', 'png', 'svg', 'png'])
    assert [p.name for p in out] == ['scan.0012_Z.pdf', 'scan.0012_Z.png', 'scan.0012_Z.svg']
    out = el.export_publication_formats(None, [], tmp_path / 'scan.0012_Z', {}, ['svg'])
    assert out[0].name == 'scan.0012_Z.svg'
    with pytest.raises(ValueError):
        el.export_publication_formats(None, [], tmp_path / 'x', {}, [])


def test_v34_scan_display_in_scripts_and_defaults():
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt
    from spm_studio.core import plot_settings as ps
    from spm_studio.core.plots import apply_figure_customization
    from spm_studio.core.presets import validate_profile
    from spm_studio.core.registry import load_manifest
    lut = [[i, 0, 255 - i] for i in range(256)]
    cfg = ps.validate_plot({'schema_version': 1, 'viewer_config': {'enabled': True, 'channels': {
        'OC M1 Excitation': {'colormap': 'x', 'lut': lut, 'title': '$V_{exc}$', 'range_mode': 'percentile', 'low': 10, 'high': 90},
        'Z': {'colormap': 'gray', 'lut': lut, 'title': '$Z$', 'range_mode': 'absolute', 'low': 1., 'high': 2.}}}})
    cmap = ps.display_cmap('OC M1 Excitation', cfg)
    assert tuple(np.round(np.array(cmap(0.)[:3]) * 255)) == (0, 0, 255)
    data = np.arange(101.)
    assert ps.viewer_limits(cfg, 'OC M1 Excitation', data) == pytest.approx((10, 90))
    assert ps.viewer_limits(cfg, 'Z', data) == (1., 2.)
    assert ps.viewer_limits(ps.validate_plot({'schema_version': 1}), 'Z', data) is None
    fig, ax = plt.subplots()
    ax.set_xlabel('OC M1 Excitation (mV)'); ax.set_ylabel('Z'); ax.set_title('Zoom of area')
    apply_figure_customization(fig, cfg)
    assert ax.get_xlabel() == '$V_{exc}$ (mV)' and ax.get_ylabel() == '$Z$' and ax.get_title() == 'Zoom of area'
    plt.close(fig)
    # titles: no doubled backslash, excitation default
    prof = validate_profile(json.loads((ROOT / 'customization' / 'profiles' / 'AFM_Molecular_Resolution.json').read_text()))
    assert prof['channel_titles']['OC M2 Freq'] == r'$\Delta f_{TR}$'
    assert prof['channel_titles']['OC M1 Excitation'] == '$V_{exc}$'
    old = validate_profile({'schema_version': 1, 'name': 'x', 'channel_titles': {'A': '$\\\\Delta f_{TR}$', 'B': 'Excitations'}})
    assert old['channel_titles'] == {'A': r'$\Delta f_{TR}$', 'B': '$V_{exc}$'}
    assert ps.default_channel_title('OC M1 Excitation') == '$V_{exc}$'
    assert ps.default_scale_bar_color('Z') == '#000000' and ps.default_scale_bar_color('$V_{exc}$') == '#ffffff'
    assert ps.default_scale_bar_color('OC M2 Freq') == '#ffffff'
    # any viewer colormap is accepted by colormap parameters, other choices stay strict
    from spm_studio.core.registry import validate_params as validate_parameters
    m = load_manifest(ROOT / 'scripts' / 'lattice_measurements' / 'module.json')
    out = validate_parameters(m, {'scan_colormap': 'Gwy - Caribbean.csv'})
    assert out['scan_colormap'] == 'Gwy - Caribbean.csv' and out['colorbar_position'] == 'below'
    with pytest.raises(ValueError):
        validate_parameters(m, {'colorbar_position': 'diagonal'})


def test_v34_export_panel_defaults():
    from spm_studio.core.export_layout import panel_defaults
    from types import SimpleNamespace
    ch = SimpleNamespace(unit='V', traces={'forward': None})
    scan = SimpleNamespace(channels={'OC M1 Excitation': ch, 'Z': ch})
    d = panel_defaults(scan, {'kind': 'channel', 'channel': 'OC M1 Excitation'})
    assert d['title'] == '$V_{exc}$' and d['colorbar_position'] == 'below' and d['scale_bar_color'] == '#ffffff'
    assert panel_defaults(scan, {'kind': 'channel', 'channel': 'Z'})['scale_bar_color'] == '#000000'


def test_v35_bad_latex_title_never_breaks_a_figure(tmp_path):
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt
    from spm_studio.core.plot_settings import clean_title
    from spm_studio.core.plots import savefig_maybe_transparent
    assert clean_title('$\\\\Delta f_{TR}$') == r'$\Delta f_{TR}$'
    assert clean_title(r'$V_{exc}$') == r'$V_{exc}$'
    assert '$' not in clean_title('$V_{exc$')
    fig, ax = plt.subplots()
    ax.set_title('$\\\\Delta f_{TR}$ [pm]'); ax.set_xlabel('$broken_{')
    savefig_maybe_transparent(fig, tmp_path / 'f.pdf')
    assert (tmp_path / 'f.pdf').stat().st_size > 0
    plt.close(fig)
