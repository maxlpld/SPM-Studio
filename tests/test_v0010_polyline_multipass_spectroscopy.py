"""v0.0.10: polylines (Shift+click), Multipass parameters on exports, one spectroscopy composer."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from spm_studio.core.analysis_utils import profile_between, profile_along, polyline_length, geometry_spacing
from spm_studio.core.models import ROI, Geometry
from spm_studio.core import scan_parameters as sp
from spm_studio.core.presets import validate_profile, validate_export_layout, read_json
from spm_studio.core.bias_figure_analysis import Spectrum
from spm_studio.core import spectroscopy_methods as sm

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------ polylines
def test_profile_follows_every_segment_of_a_polyline():
    a = np.add.outer(np.arange(20.), np.arange(30.))     # value = row + col
    d, z = profile_between(a, (0, 0), (10, 0), (10, 10))
    assert d[-1] == pytest.approx(20.)
    assert z[0] == pytest.approx(0.) and z[-1] == pytest.approx(20.)
    corner = np.argmin(np.abs(d - 10))
    assert z[corner] == pytest.approx(10., abs=0.6)
    # two points: unchanged behaviour
    d2, z2 = profile_between(a, (0, 0), (3, 4))
    assert d2[-1] == pytest.approx(5.)


def test_polyline_physical_distance_uses_pixel_size():
    a = np.zeros((10, 10))
    d, _ = profile_along(a, [(0, 0), (4, 0), (4, 3)], spacing=(2., 1.))
    assert d[-1] == pytest.approx(8. + 3.)
    assert polyline_length([(0, 0), (4, 0), (4, 3)], (2., 1.)) == pytest.approx(11.)
    geometry = Geometry((10, 20), (2e-9, 1e-9))
    assert geometry_spacing(geometry) == pytest.approx((1e-10, 1e-10))


def test_multi_profiles_and_csv_keep_all_vertices(tmp_path):
    from spm_studio.core.multi_profiles import LineSpec, compute_profiles, write_csv, physical_length_nm
    data = np.add.outer(np.arange(50.), np.arange(50.))
    line = LineSpec(((5., 5.), (25., 5.), (25., 20.)), (50, 50), 'L1', '#ff0000')
    profiles = compute_profiles([line], [{'name': 'Z', 'data': data, 'unit': 'm', 'size_m': (5e-9, 5e-9)}])
    assert profiles[0].distance_unit == 'nm'
    assert profiles[0].distance[-1] == pytest.approx(3.5)            # (20 + 15) px × 0.1 nm
    assert physical_length_nm(line.points_px, (50, 50), (5e-9, 5e-9)) == pytest.approx(3.5)
    path = write_csv(profiles, tmp_path / 'p.csv')
    text = path.read_text()
    assert 'vertices' in text.splitlines()[0]
    assert '25.000:20.000' in text.splitlines()[1]


def test_interactive_line_profile_handles_polylines():
    from spm_studio.core.interactive_tools import line_profile
    data = np.add.outer(np.arange(40.), np.arange(40.))
    geometry = Geometry((40, 40), (4e-9, 4e-9))
    distance, values = line_profile(data, geometry, ROI('line', ((0., 0.), (10., 0.), (10., 10.))))
    assert distance[-1] == pytest.approx(2e-9)
    assert values[-1] == pytest.approx(20., abs=1e-6)


def test_overlay_and_flake_distance_accept_polylines():
    source = (ROOT / 'src/spm_studio/core/painting.py').read_text()
    assert "t == 'line' and len(points) >= 2" in source
    from spm_studio.builtin_modules.flake_height.module import _distance
    ctx = SimpleNamespace(geometry=Geometry((10, 10), (1e-9, 1e-9)))
    assert _distance(ctx, (0, 0), (3, 0), (3, 4), 8)[-1] == pytest.approx(0.7e-9)


# ------------------------------------------------------------------------------------ multipass
MULTIPASS_HEADER = {
    'BIAS': '-1.000E+0',
    'Z-CONTROLLER': '\tName\ton\tSetpoint\tP-gain\tI-gain\tT-const\n'
                    '\tlog Current\t1\t5.000E-11 A\t1E-12 m\t1E-8 m/s\t1E-4 s',
    'SCAN_TIME': '1.0 1.0', 'SCAN_RANGE': '5E-9 5E-9', 'SCAN_PIXELS': '256 256',
    'MULTIPASS-CONFIG': (
        'Record-Ch\tPlayback\tPlayback-Offset\tBOL-delay_[cycles]\tEOL-delay_[cycles]\tZ-Offset_(m)\t'
        'Setpoint_action\tSetpoint\tBias_override\tBias_(V)\tTime-per-line_override\tTime-per-line\tSpeed-ratio\n'
        '0\tFALSE\t0.000E+0\t0\t0\t0.000E+0\tFALSE\t0.000E+0\tFALSE\t0.000E+0\tFALSE\t1.000E+0\t1.000E+0\n'
        '0\tTRUE\t0.000E+0\t0\t0\t-3.000E-10\tFALSE\t0.000E+0\tTRUE\t5.000E-1\tFALSE\t1.000E+0\t1.000E+0'),
}


def multipass_scan():
    return SimpleNamespace(path=Path('mp.sxm'), metadata={'header': dict(MULTIPASS_HEADER)},
                           channels={'Z [P1]': None, 'Z [P2]': None, 'OC M1 Freq. Shift [P2]': None})


def test_multipass_table_and_pass_tags():
    scan = multipass_scan()
    table = sp.multipass_table(scan)
    assert [p['pass'] for p in table] == [1, 2]
    assert table[1]['bias'] == (0.5, 'V') and table[1]['bias_override'] is True
    assert table[1]['z_offset'] == (-3e-10, 'm')
    assert sp.pass_of_channel('Z [P2]') == 2 and sp.pass_of_channel('[P1]_Current') == 1
    assert sp.pass_of_channel('Z_P3') == 3 and sp.pass_of_channel('OC M1 Freq. Shift') is None
    assert sp.channel_base('OC M1 Freq. Shift [P2]') == 'OC M1 Freq. Shift'
    assert sp.passes_in_scan(scan) == [1, 2] and sp.is_multipass(scan)


def test_multipass_parameters_respect_overrides():
    params = {p.key: p for p in sp.parameters(multipass_scan())}
    assert params['bias'].value == '−1 V'
    assert params['setpoint'].label == 'I' and params['setpoint'].value == '50 pA'
    # P1 does not override: it inherits the scan bias and setpoint.
    assert params['p1.bias'].value == '−1 V'
    assert params['p1.setpoint'].value == '50 pA'
    # P2 overrides the bias and is lifted by Δz.
    assert params['p2.bias'].value == '500 mV'
    assert params['p2.z_offset'].value == '−300 pm'
    assert params['p2.playback'].value == 'on'


def test_parameter_box_defaults_and_lines():
    scan = multipass_scan()
    assert sp.default_selection(scan, 'Z [P2]') == ['p2.bias', 'p2.setpoint', 'p2.z_offset']
    assert sp.default_selection(scan, 'Z') == ['bias', 'setpoint']
    assert sp.lines_for(scan, ['pass.bias', 'pass.z_offset'], 'Z [P2]') == ['Bias = 500 mV', 'Δz = −300 pm']
    both = sp.lines_for(scan, ['p1.bias', 'p2.bias'], 'Z [P1]')
    assert both == ['P1 · Bias = −1 V', 'P2 · Bias = 500 mV']


def test_scan_without_multipass_and_raw_header_fallback():
    raw = ':BIAS:\n1.5E-1\n:Z-CONTROLLER:\n\tName\ton\tSetpoint\n\tCurrent #3\t1\t2.000E-10 A\n'
    scan = SimpleNamespace(path=Path('a.sxm'), metadata={'raw_header': raw}, channels={'Z': None})
    params = {p.key: p for p in sp.parameters(scan)}
    assert params['bias'].value == '150 mV'
    assert params['setpoint'].value == '200 pA'
    assert not sp.is_multipass(scan)


def test_multipass_profile_is_flagged_and_documented():
    profile = read_json(ROOT / 'customization/profiles/Multipass.json', validate_profile)
    assert profile['multipass'] is True
    assert validate_profile({'schema_version': 1, 'name': 'STM'})['multipass'] is False
    assert '`multipass`' in (ROOT / 'customization/profiles/README.md').read_text()
    source = (ROOT / 'src/spm_studio/ui/main_window.py').read_text()
    assert 'def _apply_multipass_titles' in source and "profile.get('multipass')" in source


def test_export_layout_accepts_parameter_box():
    layout = validate_export_layout({'panels': [{'source': 'channel', 'channel': 'Z [P2]',
                                                 'parameters': {'corner': 'bottom_left',
                                                                'keys': ['p2.bias', 'p2.z_offset']}}]})
    box = layout['panels'][0]['parameters']
    assert box['corner'] == 'bottom_left' and box['keys'] == ['p2.bias', 'p2.z_offset'] and box['enabled']
    with pytest.raises(ValueError):
        validate_export_layout({'panels': [{'parameters': {'corner': 'middle'}}]})
    assert '`parameters`' in (ROOT / 'customization/export_presets/README.md').read_text()


# ------------------------------------------------------------------------------------ spectroscopy
def _sts(i=0):
    x = np.linspace(-1, 1, 301)
    current = 1e-10 * np.sinh(3 * x) * (1 + .3 * i)
    lockin = np.gradient(current, x) * 1e-1
    return Spectrum(Path(f'/tmp/v0010_sts_{i}.dat'), ['Bias calc (V)', 'Current (A)', 'LI Demod 1 X (V)'],
                    np.column_stack([x, current, lockin]))


def test_method_catalogue_and_preferred_channels():
    assert {'bias_kpfm', 'didv', 'iv', 'iz', 'generic'} <= set(sm.METHODS)
    spec = _sts()
    assert sm.preferred_channel(spec, sm.method('didv')) == 'LI Demod 1 X (V)'
    assert sm.preferred_channel(spec, sm.method('iv')) == 'Current (A)'
    assert sm.method('unknown').key == sm.DEFAULT_METHOD


def test_numerical_and_normalised_didv():
    spec = _sts()
    views, label, unit, warnings = sm.process_views(spec, 'Current (A)', {'method': 'didv',
                                                                         'didv_source': 'Numerical d(Current)/dV'})
    x, y = views['Forward']
    expected = 3e-10 * np.cosh(3 * x)
    assert label == 'dI/dV' and unit == 'S' and not warnings
    assert np.allclose(y[20:-20], expected[20:-20], rtol=0.02)
    views, label, unit, _ = sm.process_views(spec, 'LI Demod 1 X (V)', {'method': 'didv', 'normalize': True})
    assert label == '(dI/dV)/(I/V)' and unit == ''
    assert np.isfinite(views['Forward'][1]).all()
    values, shown = sm.convert_y(np.array([2e-9, 3e-9]), 'S')
    assert shown == 'nS' and values[0] == pytest.approx(2.)


def test_distance_spectroscopy_uses_z_axis_in_nm():
    z = np.linspace(0, 5e-10, 50)
    spec = Spectrum(Path('/tmp/v0010_iz.dat'), ['Z rel (m)', 'Current (A)'],
                    np.column_stack([z, 1e-9 * np.exp(-z / 5e-11)]))
    views, *_ = sm.process_views(spec, 'Current (A)', {'method': 'iz'})
    assert views['Forward'][0][-1] == pytest.approx(0.5)
    assert sm.x_label(sm.method('iz')).endswith('(nm)')


def _overlaps(fig):
    """Pairs of overlapping text boxes (titles, labels, tick labels, legend, suptitle)."""
    fig.draw_without_rendering()
    renderer = fig._get_renderer() if hasattr(fig, '_get_renderer') else fig.canvas.get_renderer()
    boxes = []
    for i, ax in enumerate(fig.axes):
        if not ax.get_visible() or getattr(ax, '_spm_inset', False):
            continue
        items = [ax.title, ax._left_title, ax.xaxis.label, ax.yaxis.label]
        for axis in (ax.xaxis, ax.yaxis):
            low, high = sorted(axis.get_view_interval())
            span = (high - low) * 1e-6
            items += [tick.label1 for tick in axis.get_major_ticks()
                      if low - span <= tick.get_loc() <= high + span and tick.label1.get_visible()]
        for t in items:
            if t.get_text() and t.get_visible():
                boxes.append((i, t.get_text(), t.get_window_extent(renderer)))
    texts = {id(t): t for t in list(fig.texts) + ([fig._suptitle] if fig._suptitle else [])}
    for t in texts.values():
        boxes.append((-1, t.get_text(), t.get_window_extent(renderer)))
    for legend in fig.legends:
        boxes.append((-2, 'legend', legend.get_window_extent(renderer)))
    bad = []
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            ia, ta, ba = boxes[a]
            ib, tb, bb = boxes[b]
            if ia == ib and ia >= 0:
                continue      # tick labels of one axis share their axes; different axes must not touch
            if ba.overlaps(bb) and ba.width > 0 and bb.width > 0:
                inter = min(ba.x1, bb.x1) - max(ba.x0, bb.x0), min(ba.y1, bb.y1) - max(ba.y0, bb.y0)
                if inter[0] > 1 and inter[1] > 1:
                    bad.append((ta, tb))
    return bad


@pytest.mark.parametrize('method,channel,extra', [
    ('didv', 'LI Demod 1 X (V)', {}),
    ('didv', 'Current (A)', {'didv_source': 'Numerical d(Current)/dV', 'normalize': True, 'offset': '0.5'}),
    ('iv', 'Current (A)', {'smooth': 7}),
])
def test_composer_figure_has_no_overlapping_text(tmp_path, method, channel, extra):
    import sys
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_v18_bias_figures import synthetic
    from spm_studio.core.bias_figure_render import create_figure
    scan, _folder = synthetic(tmp_path)
    specs = {}
    traces = []
    for i in range(3):
        s = _sts(i)
        s.path = tmp_path / f'sts_{i}.dat'
        s.x_m, s.y_m = 1e-9 * i, 1e-9
        specs[str(s.path)] = s
        traces.append({'path': str(s.path), 'scan': str(scan.path), 'label': f'Site {i + 1} with a long name',
                       'direction': 'Both', 'enabled': True, 'color': ['#C8102E', '#167BA3', '#D39818'][i]})
    image = {'scan': str(scan.path), 'channel': 'Z', 'title': 'Topography of a long molecular island title',
             'direction': 'forward', 'cmap': 'gray', 'processed': False, 'unit': 'Auto', 'markers': True,
             'scalebar': True}
    project = {'options': {'method': method, 'title': 'A long overall figure title to test the layout',
                           'font': 9., 'width': 9., **extra},
               'images': [image, {**image, 'channel': 'OC M1 Excitation', 'title': 'Excitation',
                                  'colorbar': 'Right'}],
               'graphs': [{'title': 'First spectrum graph with a long title', 'channel': channel, 'unit': 'Auto',
                           'traces': traces},
                          {'title': 'Second graph', 'channel': channel, 'unit': 'Auto', 'traces': traces[:1]}]}
    fig, _diag, warnings = create_figure(project, {str(scan.path): scan}, specs)
    assert not [w for w in warnings if 'Layout' in w]
    main = [ax for ax in fig.axes if getattr(ax, '_spm_plot_main', False)]
    assert len(main) == 2 and main[0].get_xlabel() == 'Sample bias (V)'
    assert main[0].get_title(loc='left').startswith('$\\mathbf{c}$')
    assert _overlaps(fig) == []
    fig.savefig(tmp_path / 'figure.pdf')
    assert (tmp_path / 'figure.pdf').stat().st_size > 8000


def test_kpfm_figure_with_height_trend_has_no_overlapping_text(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_v18_bias_figures import synthetic
    from spm_studio.core.bias_figure_analysis import read_spectrum, session_files
    from spm_studio.core.bias_figure_render import create_figure
    scan, folder = synthetic(tmp_path)
    paths = session_files(folder)
    spectra = {str(p): read_spectrum(p) for p in paths}
    traces = [{'path': str(p), 'scan': str(scan.path), 'label': f'Height {i}', 'direction': 'Both',
               'enabled': True, 'color': c, 'fit_enabled': True}
              for i, (p, c) in enumerate(zip(paths, ['#C8102E', '#167BA3', '#D39818', '#367B52']))]
    project = {'options': {'title': 'Title', 'font': 8., 'width': 11},
               'images': [{'scan': str(scan.path), 'channel': 'Z', 'title': 'Topography', 'processed': False,
                           'markers': True, 'scalebar': True, 'parameters': 'Top left'}],
               'graphs': [{'title': 'Kink vs height', 'channel': 'OC M1 Freq. Shift (Hz)', 'unit': 'Auto',
                           'trend': 'Kink vs height', 'trend_direction': 'Forward', 'traces': traces},
                          {'title': 'Zoom', 'channel': 'OC M1 Freq. Shift (Hz)', 'unit': 'Auto', 'traces': traces,
                           'inset': {'enabled': True, 'bounds': None, 'position': [.57, .53, .4, .4]}}]}
    fig, diagnostics, _warnings = create_figure(project, {str(scan.path): scan}, spectra)
    assert _overlaps(fig) == []
    assert any(d.get('kind') == 'kink trend' for d in diagnostics)


def test_composer_offers_the_measurement_type_selector():
    source = (ROOT / 'src/spm_studio/ui/bias_figure_composer.py').read_text()
    assert "QGroupBox('Measurement type')" in source and 'def change_method' in source
    assert 'Spectroscopy figure composer' in (ROOT / 'src/spm_studio/ui/main_window.py').read_text()


# ------------------------------------------------------------------------------------ Qt
@pytest.fixture(scope='module')
def app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def _viewer():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from spm_studio.ui.image_view import ImageView
    from spm_studio.core.models import ImageStyle
    viewer = ImageView()
    viewer.resize(680, 460)
    raster = np.arange(10000, dtype=float).reshape(100, 100)
    img = QImage(100, 100, QImage.Format.Format_RGB888)
    img.fill(Qt.GlobalColor.black)
    viewer.set_scan(img, raster, Geometry((100, 100), (1e-8, 1e-8)), ImageStyle(), (0, 9999), 'Z', 'm')
    viewer.set_roi_tool('line')
    return viewer


def test_shift_click_continues_the_line_with_a_new_segment(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    viewer = _viewer()
    viewer.show(); app.processEvents()
    start = viewer._to_screen((20, 20)).toPoint()
    end = viewer._to_screen((60, 20)).toPoint()
    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewer, end)
    QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
    assert viewer.roi is not None and len(viewer.roi.points_px) == 2
    corner = viewer._to_screen((60, 70)).toPoint()
    QTest.mouseClick(viewer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, corner)
    app.processEvents()
    assert len(viewer.roi.points_px) == 3
    assert abs(viewer.roi.points_px[2][1] - 70) < 2
    absolute, turn = viewer.segment_angles(viewer.roi.points_px)
    assert abs(absolute + 90) < 3 and abs(turn + 90) < 3
    # a vertex in the middle can be dragged
    mid = viewer._to_screen(viewer.roi.points_px[1]).toPoint()
    target = viewer._to_screen((65, 25)).toPoint()
    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=mid)
    QTest.mouseMove(viewer, target)
    QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=target)
    assert len(viewer.roi.points_px) == 3 and abs(viewer.roi.points_px[1][0] - 65) < 2
    viewer.close()


def test_extend_line_follows_kept_lines_and_line_styles(app):
    viewer = _viewer()
    first = ROI('line', ((10., 10.), (30., 10.)))
    viewer.extra_rois = [first]
    viewer._last_line_pts = tuple(map(tuple, first.points_px))
    viewer.line_styles = {tuple(map(tuple, first.points_px)): ('#00ff00', 'L1', 1.)}
    new = viewer.extend_line((30., 40.))
    assert viewer.extra_rois[0] is new and len(new.points_px) == 3
    assert viewer.line_styles[tuple(map(tuple, new.points_px))][1] == 'L1'
    viewer.close()


def test_parameter_box_is_drawn_on_the_export(app, tmp_path):
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtCore import QRectF
    from spm_studio.core.export_layout import _draw_parameter_box
    image = QImage(400, 400, QImage.Format.Format_ARGB32)
    image.fill(QColor('#808080'))
    painter = QPainter(image)
    _draw_parameter_box(painter, QRectF(0, 0, 400, 400), ['P2 · Bias = 500 mV', 'P2 · Δz = −300 pm'],
                        'top_right', 12, '#ffffff', True, 'bottom_right')
    painter.end()
    top_right = image.pixelColor(390, 15)
    bottom_left = image.pixelColor(10, 390)
    assert top_right != QColor('#808080')
    assert bottom_left == QColor('#808080')


def test_parameter_dialog_state_round_trip(app):
    from spm_studio.ui.parameter_box_dialog import ParameterBoxDialog, box_spec, clean_state
    scan = multipass_scan()
    dialog = ParameterBoxDialog(scan, 'Z [P2]', {'enabled': False, 'keys': None}, None)
    dialog._preset('pass3')
    state = dialog.state()
    assert state['enabled'] and set(state['keys']) == {'p1.bias', 'p1.setpoint', 'p1.z_offset',
                                                       'p2.bias', 'p2.setpoint', 'p2.z_offset'}
    spec = box_spec(clean_state(state), scan, 'Z [P2]')
    assert 'P2 · Δz = −300 pm' in spec['lines']
    dialog.close()
