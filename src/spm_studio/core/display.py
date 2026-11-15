"""Fast Qt-independent LUT/range computation, identical for preview and exports."""
from __future__ import annotations
import numpy as np
from .models import ImageStyle

# Embedded small stop palettes; avoids import of Matplotlib at application startup.
PALETTES = {
    'gray': ((0, 0, 0), (255, 255, 255)),
    'gray-inverted': ((255, 255, 255), (0, 0, 0)),
    'viridis': ((68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)),
    'magma': ((0, 0, 4), (81, 18, 124), (182, 54, 121), (251, 136, 97), (252, 253, 191)),
    'copper': ((0, 0, 0), (137, 86, 55), (255, 199, 127)),
    # Gold-themed height map; when the user's actual Gwyddion Gold gradient
    # is installed, it takes priority in lut() below.
    'Gold': ((19, 14, 0), (65, 41, 1), (133, 88, 6), (211, 155, 38), (255, 218, 120), (255, 248, 210)),
    'bronze': ((24, 9, 0), (89, 36, 9), (149, 81, 42), (220, 151, 99), (253, 218, 169)),
    'ice': ((1, 5, 25), (15, 51, 113), (43, 126, 189), (124, 207, 222), (242, 255, 255)),
    'ruby': ((19, 0, 10), (110, 10, 51), (200, 29, 68), (247, 141, 124), (255, 245, 220)),
    'forest': ((0, 22, 9), (13, 74, 21), (56, 135, 49), (145, 210, 101), (253, 248, 174)),
    'terrain': ((24, 38, 90), (51, 110, 168), (93, 165, 90), (190, 168, 112), (250, 247, 244)),
    'sunset': ((23, 8, 58), (111, 37, 102), (207, 62, 73), (251, 144, 57), (255, 232, 126)),

    'coolwarm': ((59,76,192),(135,169,249),(221,221,221),(246,148,113),(180,4,38)),
    'inferno': ((0,0,4),(65,9,81),(147,38,103),(222,94,57),(252,255,164)),
    'plasma': ((13,8,135),(126,3,168),(203,71,119),(248,149,64),(240,249,33)),
    'cividis': ((0,32,77),(68,71,108),(124,123,117),(180,176,110),(253,234,69)),
    'Blues': ((247,251,255),(198,219,239),(107,174,214),(33,113,181),(8,48,107)),
    'hot': ((10,0,0),(170,0,0),(255,97,0),(255,255,7),(255,255,255)),
    'bone': ((0,0,0),(55,61,77),(119,145,154),(193,212,211),(255,255,255)),
}


def lut(name: str, custom: np.ndarray | None = None) -> np.ndarray:
    if custom is None and name == 'Gold':
        # Gwyddion's genuine Gold gradient wins over the bundled fallback.
        from .paths import customization_dir
        override = customization_dir() / 'colormaps' / 'Gwy - Gold.csv'
        if override.is_file():
            custom = np.loadtxt(override, delimiter=',', comments='#')
    if custom is None:
        if name not in PALETTES:
            from .paths import customization_dir
            from pathlib import Path
            if Path(name).name != name or not name.endswith(('.csv', '.txt')):
                raise ValueError(f'Unknown palette: {name}')
            target = customization_dir() / 'colormaps' / name
            if not target.is_file():
                raise ValueError(f'Missing custom palette: {name}')
            custom = np.loadtxt(target, delimiter=',' if name.endswith('.csv') else None, comments='#')
        else:
            custom = np.asarray(PALETTES[name], dtype=float)
    else:
        custom = np.asarray(custom, dtype=float)
    if custom.ndim != 2 or custom.shape[1] not in (3, 4) or len(custom) < 2 or not np.isfinite(custom).all():
        raise ValueError('Colormap must be Nx3/Nx4 finite RGB(A) values')
    custom = custom[:, :3]
    if np.max(custom) <= 1:
        custom = custom * 255
    if np.min(custom) < 0 or np.max(custom) > 255:
        raise ValueError('Color components must be in 0–1 or 0–255 range')
    p = np.linspace(0, 1, len(custom))
    return np.rint(np.column_stack([np.interp(np.linspace(0, 1, 256), p, custom[:, i]) for i in range(3)])).astype(np.uint8)


def bounds(data: np.ndarray, style: ImageStyle) -> tuple[float, float]:
    v = np.asarray(data)[np.isfinite(data)]
    if not v.size:
        return 0., 1.
    if style.range_mode == 'manual':
        lo, hi = style.low, style.high
    elif style.range_mode == 'full':
        lo, hi = float(v.min()), float(v.max())
    elif style.range_mode == 'percentile':
        lo, hi = np.percentile(v, (style.low, style.high))
    elif style.range_mode == 'sigma':
        m, s = np.mean(v), np.std(v)
        lo, hi = m - style.low * s, m + style.high * s
    elif style.range_mode == 'mad':
        m = np.median(v)
        mad = 1.4826 * np.median(np.abs(v - m))
        lo, hi = m - style.low * mad, m + style.high * mad
    else:
        raise ValueError(f'Unknown range mode {style.range_mode}')
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return (float(lo), float(lo) + max(abs(float(lo)) * 1e-9, 1e-30))
    return float(lo), float(hi)


def render_rgb(data: np.ndarray, style: ImageStyle, fixed_bounds=None,
               palette: np.ndarray | None = None, max_dimension: int | None = None) -> np.ndarray:
    """Return uint8 RGB; mask invalid pixels; no axis flips or scientific value changes."""
    a = np.asarray(data)
    if a.ndim != 2:
        raise ValueError('Only 2D images supported')
    if max_dimension is not None and max(a.shape) > max_dimension:
        stride = int(np.ceil(max(a.shape) / max_dimension))
        a = a[::stride, ::stride]
    lo, hi = fixed_bounds if fixed_bounds is not None else bounds(data, style)
    norm = np.clip((np.nan_to_num(a.astype(np.float64), nan=lo, posinf=hi, neginf=lo) - lo) / (hi-lo), 0, 1)
    gamma = max(float(style.gamma), 1e-6)
    if gamma != 1:
        norm = norm ** (1 / gamma)
    rgb = lut(style.colormap, palette)[np.rint(norm * 255).astype(np.uint8)]
    rgb[~np.isfinite(a)] = (130, 20, 130)
    return rgb


def read_colormap_csv(path):
    from pathlib import Path
    path = Path(path)
    result = np.loadtxt(path, delimiter=',' if path.suffix.lower() == '.csv' else None, comments='#')
    lut('custom', result)  # validation
    return result


def preview_bounds(data: np.ndarray, style: ImageStyle, max_samples: int = 400_000) -> tuple[float, float]:
    """Fast, bounded-cost preview contrast; exact exported data stay unchanged.

    Only the *contrast estimate* is sampled, not the underlying raster.
    For publication exports the original full-resolution ``bounds`` is used.
    """
    a = np.asarray(data)
    if a.ndim != 2:
        raise ValueError('Only 2D images supported')
    if style.range_mode == 'manual':
        return bounds(a[:1, :1], style)
    stride = max(1, int(np.ceil(np.sqrt(a.size / max(1, max_samples)))))
    return bounds(a[::stride, ::stride], style)
