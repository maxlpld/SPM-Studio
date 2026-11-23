"""v0.0.17: sharper 3D preview — reliefs sampled from their own grid, smooth text edges, finer grid."""
import numpy as np

from spm_studio.core import print3d_plate as Q


def _plate(**params):
    yy, xx = np.mgrid[0:128, 0:128]
    data = (np.sin(xx / 9.) * np.cos(yy / 11.)) * 1e-10
    return Q.build_plate([Q.Panel(data, (10, 10), 'pm', 1e12, 'Z', colors=('#0000FF', '#FFFF00'))],
                         {'width_mm': 40, 'resolution_mm': .2, 'text_resolution_mm': .05, **params})


def test_preview_grid_is_fine_and_matches_the_relief():
    plate = _plate()
    z, cell = plate.preview
    assert max(z.shape) >= Q.PREVIEW_CELLS - 1
    info = plate.panels[0]
    px, py, iw, ih = info['box']
    W, H = plate.size_mm
    r, c = int((py + ih / 2) / cell), int((px + iw / 2) / cell)          # centre of the scan
    relief = next(b for b in plate.bodies if b.name == 'relief 1').grid['z']
    centre = relief[relief.shape[0] // 2, relief.shape[1] // 2]
    assert abs(z[r, c] - centre) < .5
    base, top = plate.params['base_mm'], plate.params['base_mm'] + plate.params['relief_mm']
    assert z.max() <= top + 1e-6 and z.min() >= base - 1e-6


def test_preview_text_edges_are_smooth_and_coloured():
    plate = _plate(text_color='#FF0000', background_color='#FFFFFF')
    z, _cell = plate.preview
    base, label = plate.params['base_mm'], plate.params['label_mm']
    levels = z[(z > base + 1e-6) & (z < base + label - 1e-6)]
    assert len(levels) > 20                                   # antialiased text edges (not only 0 / full height)
    rgb = plate.preview_rgb
    red = (rgb[..., 0] > .9) & (rgb[..., 1] < .1) & (rgb[..., 2] < .1)
    assert red.sum() > 50 and np.allclose(rgb[0, 0], [1, 1, 1])
    panel = plate.panels[0]
    cell = plate.preview[1]
    px, py, iw, ih = panel['box']
    block = rgb[int(py / cell) + 2:int((py + ih) / cell) - 2, int(px / cell) + 2:int((px + iw) / cell) - 2]
    assert block[..., 2].max() > .5 and block[..., 0].max() > .5           # blue → yellow gradient on the scan
