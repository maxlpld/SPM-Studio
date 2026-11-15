"""v29: journal panel letters, overlay GIF sweep and molecule artwork scale."""
from pathlib import Path
import sys
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'molecule_placement'))


def test_panel_letters_only_on_real_panels():
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt
    from spm_studio.core.plots import add_panel_labels, finalize_publication_figure
    fig, axes = plt.subplots(2, 2)
    for ax in axes.flat:
        ax.plot([0, 1], [0, 1])
    im = axes[0, 0].imshow(np.zeros((4, 4)))
    fig.colorbar(im, ax=axes[0, 0])
    finalize_publication_figure(fig)
    letters = sorted(t.get_text() for t in fig.texts if getattr(t, '_spm_panel_label', False))
    assert letters == ['a', 'b', 'c', 'd']
    # Idempotent for live previews.
    add_panel_labels(fig)
    assert len([t for t in fig.texts if getattr(t, '_spm_panel_label', False)]) == 4
    # Journal frame: ticks on all four sides, inward.
    ax = axes[1, 1]
    assert all(s.get_visible() for s in ax.spines.values())
    plt.close(fig)


def test_single_panel_has_no_letter():
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt
    from spm_studio.core.plots import finalize_publication_figure
    fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 0])
    finalize_publication_figure(fig)
    assert not [t for t in fig.texts if getattr(t, '_spm_panel_label', False)]
    plt.close(fig)


def test_publication_dpi_floor():
    from spm_studio.core.plots import publication_dpi
    assert publication_dpi(300) == 600 and publication_dpi(1200) == 1200


def test_sweep_starts_with_base_and_ends_with_top_only():
    from spm_studio.core.channel_overlay import sweep_opacities
    assert sweep_opacities(4, 0) == [1, 0, 0, 0]
    assert sweep_opacities(4, 1) == [1, 1, 1, 1]
    assert sweep_opacities(4, .5) == [1, 1, .5, 0]
    assert sweep_opacities(3, 1, .2, .7) == [1, .7, .7]
    assert sweep_opacities(3, 0, .2, .7) == [1, .2, .2]


def test_gif_export(tmp_path):
    PIL = pytest.importorskip('PIL')
    from PIL import Image
    from spm_studio.core.channel_overlay import Layer, save_overlay_animation
    from spm_studio.core.models import Geometry
    y, x = np.mgrid[0:64, 0:96]
    layers = [Layer('Z', np.sin(x / 5.), 'm', 'gray'), Layer('I', np.cos(y / 4.), 'A', 'inferno'),
              Layer('df', x * 1. + y, 'Hz', 'viridis')]
    files = save_overlay_animation(layers, Geometry(shape=(64, 96), size_m=(6e-9, 4e-9)),
                                   tmp_path / 'o.gif', duration_s=1.5, fps=10, max_px=300)
    im = Image.open(files[0])
    assert im.size == (300, 200)
    total = 0
    for i in range(im.n_frames):
        im.seek(i); total += im.info['duration']
    assert abs(total - 1500) <= 20


def test_molecule_size_refers_to_visible_artwork(tmp_path):
    pytest.importorskip('PIL')
    from PIL import Image
    from placement_engine import prepare_artwork, render_molecules
    art = Image.new('RGBA', (200, 100), (255, 255, 255, 255))
    art.paste((255, 0, 0, 255), (50, 25, 150, 75))
    path = tmp_path / 'm.png'; art.save(path)
    doc = {'roi_geometry': {'size_nm': [15., 10.], 'pixel_size_nm': [.05, .05], 'shape_yx': [200, 300]},
           '_raw_view': np.random.rand(200, 300), 'basis_local_nm': [[6., 0.], [0., 4.]]}
    p = {'molecule_image': str(path), 'molecule_width_nm': 2., 'molecule_height_nm': 0,
         'orientation_mode': 'manual', 'rotation_offset_deg': 0, 'opacity': 1,
         'max_molecules': 50, 'molecule_count': 1}
    im, info = prepare_artwork(str(path), p)
    assert info['trimmed'] and p['molecule_height_nm'] == pytest.approx(1.)
    img, *_ = render_molecules(doc, im, p)
    a = np.asarray(img); red = (a[..., 0] > 250) & (a[..., 1] < 30)
    xs = np.nonzero(red)[1]
    assert xs.max() - xs.min() + 1 == pytest.approx(2 / 15 * img.width, abs=2)


def test_v30_triple_layout_cells():
    from spm_studio.core.export_layout import layout_cells
    tri = layout_cells(3, 1000, 900, 50, 20, 'triangle')
    inv = layout_cells(3, 1000, 900, 50, 20, 'inverted_triangle')
    row = layout_cells(3, 1000, 900, 50, 20, 'row')
    # triangle: one centred on top, two below; reverse: two on top, one centred below
    assert tri[0][1] < tri[1][1] == tri[2][1] and abs(tri[0][0] + tri[0][2] / 2 - 500) < 1
    assert inv[0][1] == inv[1][1] < inv[2][1] and abs(inv[2][0] + inv[2][2] / 2 - 500) < 1
    assert len({c[1] for c in row}) == 1


def test_v30_transparent_plot_export(tmp_path):
    import matplotlib
    matplotlib.use('Agg', force=True)
    from types import SimpleNamespace
    from PIL import Image
    from spm_studio.core.plots import plot_style
    from spm_studio.core.analysis_utils import save_plot
    from spm_studio.core.plot_settings import DEFAULT_PLOT, validate_plot
    cfg = validate_plot(dict(DEFAULT_PLOT, transparent_background=True))
    ctx = SimpleNamespace(plot_config=cfg, plot_formats=('png',), output_dir=tmp_path,
                          result_file=lambda *a: None)
    with plot_style(cfg) as plt:
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        save_plot(ctx, fig, 't')
    a = np.asarray(Image.open(tmp_path / 't.png'))
    assert a.shape[2] == 4 and a[0, 0, 3] == 0


def test_v31_overlay_skips_viewer_channel_picked_again():
    from spm_studio.core.channel_overlay import make_layers
    img = np.zeros((4, 4))
    data = {'A': img, 'B': img, 'C': img}
    skipped = []
    layers = make_layers('A', img, 'V', [], data.__getitem__, {}, {'channel_2': 'A', 'channel_3': 'B'},
                         skip_duplicates=True, skipped=skipped)
    # Viewer channel A is also layer 2 → stack is exactly the chosen layers, nothing "used twice".
    assert [l.name for l in layers] == ['A', 'B'] and skipped == []
    assert layers[0].opacity == 1.0
    layers = make_layers('C', img, 'V', [], data.__getitem__, {}, {'channel_2': 'A', 'channel_3': 'A'},
                         skip_duplicates=True, skipped=skipped)
    assert [l.name for l in layers] == ['C', 'A'] and skipped == ['A']
    with pytest.raises(ValueError, match='two different channels'):
        make_layers('A', img, 'V', [], data.__getitem__, {}, {'channel_2': 'A'}, skip_duplicates=True)


def test_v31_white_page_keyed_out_but_plot_area_kept():
    from spm_studio.core.export_layout import key_out_page_background
    a = np.full((20, 20, 4), 255, np.uint8)
    a[5:15, 5:15, :3] = 0
    a[7:13, 7:13, :3] = 255
    k = key_out_page_background(a)
    assert k[0, 0, 3] == 0 and k[10, 10, 3] == 255 and k[6, 6, 3] == 255


def test_v31_math_detection():
    from spm_studio.core.painting import has_math
    assert has_math('$V_{exc}$') and has_math('$\\Delta f$ [Hz]')
    assert not has_math('V_exc') and not has_math('cost $5')
