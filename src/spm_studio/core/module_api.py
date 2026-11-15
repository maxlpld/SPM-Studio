"""Tiny typed runtime API exposed to third-party analysis subprocesses."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json, sys
import numpy as np
from .models import Geometry, ROI
from .plot_settings import validate_plot


@dataclass
class ModuleContext:
    scan_path: Path
    channel: str
    direction: str
    data: np.ndarray
    unit: str
    geometry: Geometry
    metadata: dict[str, Any]
    parameters: dict[str, Any]
    output_dir: Path
    source_paths: list[Path]
    arrays: dict[str, np.ndarray]
    roi: ROI | None = None
    processing: list[dict] | None = None
    channel_geometries: dict[str, dict] | None = None
    rois: list[ROI] | None = None
    plot_config: dict | None = None
    plot_formats: tuple[str, ...] = ('png', 'pdf')
    channel_units: dict[str, str] | None = None

    def image(self, channel: str | None = None, direction: str | None = None):
        ch, tr = channel or self.channel, direction or self.direction
        key = f'{ch}|{tr}'
        if key not in self.arrays:
            raise KeyError(f'Image {key} unavailable. Available: {list(self.arrays)}')
        if ch != self.channel and self.channel_geometries:
            other = self.channel_geometries.get(ch)
            if other is not None:
                geometry = Geometry.from_dict(other)
                if geometry.shape != self.geometry.shape or geometry.size_m != self.geometry.size_m or (geometry.center_m is not None and self.geometry.center_m is not None and geometry.center_m != self.geometry.center_m) or (geometry.angle_deg is not None and self.geometry.angle_deg is not None and geometry.angle_deg != self.geometry.angle_deg):
                    raise ValueError(f'Channel {ch} has a different geometry; explicit registration required')
        return self.arrays[key]

    def log(self, message: str, level='info'):
        emit('log', message=str(message), level=level)

    def progress(self, percentage: float, message=''):
        emit('progress', value=max(0., min(100., float(percentage))), message=message)

    def result_file(self, path: str | Path, title: str = ''):
        p = Path(path).resolve()
        if not p.is_relative_to(self.output_dir.resolve()):
            raise ValueError('Result files must live in the allocated run directory')
        emit('result_file', path=str(p), title=title or p.name)

    def result_table(self, columns, rows, title='Results'):
        emit('table', title=title, columns=list(columns), rows=[list(x) for x in rows])

    def overlay(self, primitives):
        emit('overlay', primitives=primitives)


def select_snapshot_arrays(scan, selected_channel, snapshot_channels='selected', extra_channels=()):
    """Prepare references to only the channel rasters requested by the module.

    The caller writes these arrays into its isolated analysis snapshot. The scan
    itself is never modified or eagerly converted to float64.
    """
    if snapshot_channels not in ('selected','all'):
        raise ValueError('Unknown snapshot channel policy')
    requested={selected_channel, *(c for c in extra_channels if c in scan.channels)}
    return {f'{name}|{trace}':array
            for name,channel in scan.channels.items()
            if snapshot_channels=='all' or name in requested
            for trace,array in channel.traces.items()}


def emit(kind, **fields):
    sys.stdout.write('SPM_EVENT ' + json.dumps({'type':kind,**fields}, ensure_ascii=False, default=str) + '\n')
    sys.stdout.flush()


def from_snapshot(context_json: Path) -> ModuleContext:
    info = json.loads(Path(context_json).read_text(encoding='utf8'))
    with np.load(info['array_file'], allow_pickle=False) as archive:
        arrays = {key: np.array(archive[key], copy=True) for key in archive.files}
    roi = info.get('roi')
    all_rois = [ROI(r['kind'], tuple(tuple(p) for p in r['points_px'])) for r in info.get('rois',[])]
    formats = tuple(info.get('plot_formats',['png','pdf']))
    if not formats or any(ext not in ('png','pdf','svg') for ext in formats):   # v36: SVG is a valid script format
        raise ValueError('Invalid requested export formats')
    return ModuleContext(Path(info['scan_path']), info['channel'], info['direction'],
                         arrays[info['selected_key']], info['unit'], Geometry.from_dict(info['geometry']),
                         info.get('metadata',{}), info.get('parameters',{}), Path(info['output_dir']),
                         [Path(p) for p in info.get('source_paths',[])], arrays,
                         ROI(roi['kind'], tuple(tuple(x) for x in roi['points_px'])) if roi else None,
                         info.get('processing',[]),info.get('channel_geometries',{}),all_rois,
         validate_plot(info.get('plot_config',{'schema_version':1})),formats,
         info.get('channel_units',{}))
