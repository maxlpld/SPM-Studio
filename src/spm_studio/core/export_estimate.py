"""v0.0.21: size of an export before it is written (shown live while the export settings change).

The publication figure is rendered exactly as *Export…* would render it (same renderer, page,
resolution, panels and formats) into a temporary folder, the files are measured and deleted. This is
the true size, not a guess; it runs in a background thread so the dialog stays responsive.
The animated overlay GIF has its own estimator in ``channel_overlay.estimate_overlay_animation_size``.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def human_size(n_bytes) -> str:
    """1 234 567 → '1.2 MB' (decimal units, as file managers show them)."""
    if n_bytes is None:
        return '?'
    n = float(n_bytes)
    for unit in ('B', 'kB', 'MB', 'GB'):
        if n < 1000 or unit == 'GB':
            if unit == 'B':
                return f'{int(n)} B'
            return f'{n:.1f} {unit}' if n < 100 else f'{n:.0f} {unit}'
        n /= 1000.0
    return f'{n:.1f} GB'


def page_pixels(preset) -> tuple[int, int]:
    """Pixel size of the page before the tight crop (upper bound of the PNG size)."""
    dpi = float(preset.get('dpi', 300))
    return (max(96, round(float(preset.get('width_mm', 86)) / 25.4 * dpi)),
            max(96, round(float(preset.get('height_mm', 78)) / 25.4 * dpi)))


def estimate_publication_sizes(scan, panels, preset, formats, **kwargs) -> dict:
    """Render the publication figure in every format into a temporary folder and measure it.

    Returns {'sizes': {fmt: bytes}, 'size_px': [w, h] (after the tight crop), 'size_mm': [w, h]}.
    """
    from .export_layout import export_publication_formats
    from . import paths
    try:
        root = paths.cache_dir()
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        root = None
    out = {'sizes': {}, 'size_px': None, 'size_mm': None}
    with tempfile.TemporaryDirectory(prefix='spm_size_', dir=str(root) if root else None) as tmp:
        written = export_publication_formats(scan, panels, Path(tmp) / 'size_estimate', preset, formats, **kwargs)
        for path in written:
            path = Path(path)
            if not path.is_file():
                continue
            out['sizes'][path.suffix.lower().lstrip('.')] = path.stat().st_size
            try:
                info = json.loads(Path(str(path) + '.provenance.json').read_text(encoding='utf-8'))
                crop = info.get('tight_crop') or {}
                if crop.get('size_px'):
                    out['size_px'] = list(crop['size_px'])
                    out['size_mm'] = list(crop.get('size_mm') or [])
            except Exception:
                pass
    return out


def describe_publication(result, formats=()) -> str:
    """One line for the dialog: 'SVG 2.1 MB · PDF 1.3 MB · PNG 18 MB — 8402 × 5433 px'."""
    sizes = (result or {}).get('sizes') or {}
    order = [f for f in ('svg', 'pdf', 'png', 'jpg') if f in sizes] + [f for f in sizes if f not in
                                                                      ('svg', 'pdf', 'png', 'jpg')]
    text = ' · '.join(f'{f.upper()} {human_size(sizes[f])}' for f in order) or 'nothing to export'
    if len(order) > 1:
        text += f'  (total {human_size(sum(sizes.values()))})'
    px = (result or {}).get('size_px')
    if px:
        text += f' — {px[0]} × {px[1]} px'
    return text


def describe_animation(result) -> str:
    """One line for the GIF panel: 'GIF ≈ 4.2 MB · 150 frames · 1440 × 1080 px · MP4 ≈ 0.8 MB'."""
    if not result:
        return ''
    w, h = result.get('size_px') or (0, 0)
    text = (f'GIF ≈ {human_size(result.get("gif_bytes"))} · {result.get("frames", 0)} frames · '
            f'{w} × {h} px')
    if result.get('mp4_bytes'):
        text += f' · MP4 ≈ {human_size(result["mp4_bytes"])}'
    return text
