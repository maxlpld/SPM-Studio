"""Typed, UI-independent scientific data contracts (Module API v1)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import math
import numpy as np


@dataclass(frozen=True)
class Geometry:
    """Raster coordinates. Pixel (row=0,col=0) is top-left of stored array.

    If absolute metadata are known, center_m is the scan center in sample axes,
    size_m is the physical width/height, and angle_deg rotates scan axes CCW.
    Display y increases down, local sample y increases up. SXM readers
    normalize the Nanonis backward X and up-scan Y acquisition ordering before
    creating this geometry; GWY readers preserve the raster already on disk.
    No automatic pixel rotation follows the recorded scan angle.
    """
    shape: tuple[int, int]
    size_m: tuple[float, float] | None = None
    center_m: tuple[float, float] | None = None
    angle_deg: float | None = None
    scan_direction: str | None = None
    source_orientation: str = "stored-array"
    verified_orientation: bool = False

    def __post_init__(self):
        if len(self.shape) != 2 or min(self.shape) < 1:
            raise ValueError("Expected nonempty (rows, columns) image shape")
        if self.size_m is not None and (len(self.size_m) != 2 or not all(math.isfinite(v) and v > 0 for v in self.size_m)):
            raise ValueError("Physical size must be two positive finite lengths in metres")

    @property
    def calibrated(self) -> bool:
        return self.size_m is not None

    def pixel_to_local(self, row: Any, col: Any):
        """Pixel-center indices to sample-local metres (unrotated), or pixels if uncalibrated."""
        ny, nx = self.shape
        sx, sy = self.size_m if self.size_m is not None else (float(nx), float(ny))
        return ((np.asarray(col) + .5) / nx - .5) * sx, (.5 - (np.asarray(row) + .5) / ny) * sy

    def local_to_pixel(self, x: Any, y: Any):
        ny, nx = self.shape
        sx, sy = self.size_m if self.size_m is not None else (float(nx), float(ny))
        return (.5 - np.asarray(y) / sy) * ny - .5, (np.asarray(x) / sx + .5) * nx - .5

    def pixel_to_sample(self, row: Any, col: Any):
        if self.center_m is None or self.size_m is None or self.angle_deg is None:
            raise ValueError("Absolute coordinates unavailable; use pixel_to_local")
        x, y = self.pixel_to_local(row, col)
        t = math.radians(self.angle_deg)
        return self.center_m[0] + x * math.cos(t) - y * math.sin(t), self.center_m[1] + x * math.sin(t) + y * math.cos(t)

    def sample_to_pixel(self, x: Any, y: Any):
        if self.center_m is None or self.size_m is None or self.angle_deg is None:
            raise ValueError("Absolute coordinates unavailable; use local_to_pixel")
        dx, dy = np.asarray(x) - self.center_m[0], np.asarray(y) - self.center_m[1]
        t = math.radians(self.angle_deg)
        return self.local_to_pixel(dx * math.cos(t) + dy * math.sin(t), -dx * math.sin(t) + dy * math.cos(t))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        v = dict(value)
        v['shape'] = tuple(v['shape'])
        for k in ('size_m', 'center_m'):
            if v.get(k) is not None:
                v[k] = tuple(v[k])
        return cls(**v)


@dataclass(frozen=True)
class ProcessingStep:
    operation: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class ImageStyle:
    colormap: str = "gray"
    range_mode: str = "percentile"
    low: float = 1.0
    high: float = 99.0
    gamma: float = 1.0
    scale_bar: bool = True
    colorbar: bool = True


@dataclass
class Channel:
    name: str
    unit: str
    traces: dict[str, np.ndarray]
    geometry: Geometry
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        for k, array in self.traces.items():
            if k not in ("forward", "backward"):
                raise ValueError(f"Unknown trace: {k}")
            if np.asarray(array).shape != self.geometry.shape:
                raise ValueError(f"{self.name}: trace shape and geometry differ")
            # Do not upcast or duplicate native SXM float32 memmaps. Original
            # big-endian float32 is supported by NumPy and preserved losslessly.
            # Dtype conversion would allocate hundreds of MiB during Open.
            raw = np.asarray(array)
            if raw.dtype.kind not in ('f', 'i', 'u'):
                raise ValueError(f'{self.name}: unsupported raster dtype {raw.dtype}')
            if raw.dtype.kind != 'f':
                raw = raw.astype(np.float32)
            raw.setflags(write=False)
            self.traces[k] = raw

    def get(self, direction: str):
        if direction not in self.traces:
            raise KeyError(f"{self.name}: {direction} is not available (available: {', '.join(self.traces)})")
        return self.traces[direction]


@dataclass
class Scan:
    path: Path
    channels: dict[str, Channel]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.path = Path(self.path).resolve()
        if not self.channels:
            raise ValueError("Scan contains no image channels")

    def preferred_channel(self) -> str:
        return next((n for n in self.channels if n.lower() == 'z' or n.lower().startswith('z (')), next(iter(self.channels)))

    def key(self) -> tuple:
        stat = self.path.stat()
        return (str(self.path), stat.st_size, stat.st_mtime_ns)


@dataclass(frozen=True)
class ROI:
    kind: str
    points_px: tuple[tuple[float, float], ...]  # (column, row) in source pixel coordinates

    def to_dict(self):
        return {'kind': self.kind, 'points_px': [list(p) for p in self.points_px]}


UNIT_MULTIPLIERS = {'m': 1, 'nm': 1e-9, 'pm': 1e-12, 'Å': 1e-10, 'V': 1, 'mV': 1e-3,
                    'A': 1, 'nA': 1e-9, 'pA': 1e-12, 'Hz': 1, 'kHz': 1e3, 'deg': 1}


def preferred_display_unit(unit: str, values: np.ndarray) -> tuple[str, float]:
    """Unit display only. Input numerical arrays are never rescaled in-place."""
    base = unit.strip()
    finite = np.asarray(values)[np.isfinite(values)]
    scale = float(np.nanmax(np.abs(finite))) if finite.size else 0
    if base == 'm':
        return ('pm', 1e12) if scale < 1e-9 else ('nm', 1e9) if scale < 1e-6 else ('m', 1)
    if base == 'V' and scale < 1:
        return 'mV', 1e3
    if base == 'A':
        return ('pA', 1e12) if scale < 1e-9 else ('nA', 1e9) if scale < 1e-6 else ('A', 1)
    if base == 'Hz' and scale >= 1000:
        return 'kHz', 1e-3
    return base or 'a.u.', 1.0


_SI_PREFIX={'p':1e-12,'n':1e-9,'u':1e-6,'µ':1e-6,'μ':1e-6,'m':1e-3,'c':1e-2,'k':1e3,'M':1e6,'G':1e9}
_SI_BASES=('m','V','A','Hz','s','N','K','Ω','S','T','deg','°')


def unit_to_si(unit: str):
    """(base unit, factor) so that 1 <unit> = factor <base>; None when unknown.
    'nm' -> ('m', 1e-9), 'Å' -> ('m', 1e-10), 'mV' -> ('V', 1e-3), 'm' -> ('m', 1)."""
    text=(unit or '').strip()
    if not text:
        return None
    if text.casefold() in ('å','angstrom','ångström','ångstrom','aa'):
        return 'm',1e-10
    if text in _SI_BASES:
        return text,1.0
    if len(text)>1 and text[0] in _SI_PREFIX and text[1:] in _SI_BASES:
        return text[1:],_SI_PREFIX[text[0]]
    return None


def display_unit_for(requested: str, base_unit: str, values: np.ndarray) -> tuple[str, float]:
    """Unit label and multiplier for values stored in ``base_unit``.

    Empty or identical request: automatic scale (nm/pm, mV, nA/pA...). A request such as
    'nm', 'Å' or 'mV' converts the displayed numbers accordingly; an unknown unit is shown
    verbatim with the numbers unchanged (as before)."""
    requested=(requested or '').strip()
    base=(base_unit or '').strip()
    if not requested or requested==base:
        return preferred_display_unit(base or requested,values)
    target=unit_to_si(requested)
    source=unit_to_si(base)
    if target and source and target[0]==source[0]:
        return requested,source[1]/target[1]
    return requested,1.0
