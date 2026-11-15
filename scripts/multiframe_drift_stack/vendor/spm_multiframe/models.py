from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class ScanMetadata:
    path: Path
    sha256: str
    nx: int
    ny: int
    width_nm: float
    height_nm: float
    center_x_nm: float
    center_y_nm: float
    scan_angle_deg: float
    frame_direction: str
    start_time_s: float
    end_time_s: float
    line_time_forward_s: float | None
    line_time_backward_s: float | None
    piezo_cal_x_m_per_v: float | None
    piezo_cal_y_m_per_v: float | None
    piezo_cal_z_m_per_v: float | None
    channel_names: tuple[str, ...]
    acquisition_datetime: str | None = None
    bias_v: float | None = None
    setpoint_a: float | None = None
    timing_confidence: str = "unknown"
    channel_units: Mapping[str, str] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_time_s - self.start_time_s)

    @property
    def midpoint_time_s(self) -> float:
        return 0.5 * (self.start_time_s + self.end_time_s)

    @property
    def native_dx_nm(self) -> float:
        return self.width_nm / max(self.nx, 1)

    @property
    def native_dy_nm(self) -> float:
        return self.height_nm / max(self.ny, 1)


@dataclass
class ScanFrame:
    metadata: ScanMetadata
    channel: str
    trace_direction: str
    data: np.ndarray
    x_nom_nm: np.ndarray
    y_nom_nm: np.ndarray
    t_s: np.ndarray
    scan_id: str | None = None

    def __post_init__(self) -> None:
        expected = (self.metadata.ny, self.metadata.nx)
        for name, arr in (
            ("data", self.data),
            ("x_nom_nm", self.x_nom_nm),
            ("y_nom_nm", self.y_nom_nm),
            ("t_s", self.t_s),
        ):
            if arr.shape != expected:
                raise ValueError(f"{name} shape {arr.shape} does not match expected {expected}")
        if self.scan_id is None:
            self.scan_id = f"{self.metadata.path.name}::{self.trace_direction}"


@dataclass(frozen=True)
class GridDefinition:
    x_nm: np.ndarray
    y_nm: np.ndarray

    @property
    def dx_nm(self) -> float:
        return float(np.median(np.diff(self.x_nm))) if len(self.x_nm) > 1 else float("nan")

    @property
    def dy_nm(self) -> float:
        return float(np.median(np.diff(self.y_nm))) if len(self.y_nm) > 1 else float("nan")

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.y_nm), len(self.x_nm))

    @property
    def extent(self) -> tuple[float, float, float, float]:
        return (float(self.x_nm[0]), float(self.x_nm[-1]), float(self.y_nm[0]), float(self.y_nm[-1]))


@dataclass
class PairRegistration:
    i: int
    j: int
    shift_nm: np.ndarray
    score: float
    dt_s: float
    valid: bool = True


@dataclass
class DriftFitResult:
    correction_velocity_nm_s: np.ndarray
    sample_velocity_nm_s: np.ndarray
    sigma_nm_s: np.ndarray
    interval68_nm_s: np.ndarray
    interval95_nm_s: np.ndarray
    reference_time_s: float
    residual_translations_nm: dict[str, np.ndarray]
    registration_scores: dict[str, float]
    pair_registrations: list[PairRegistration]
    objective_value: float
    bootstrap_samples_nm_s: np.ndarray


@dataclass
class FFTPeak:
    gx_cpnm: float
    gy_cpnm: float
    amplitude: float
    snr: float
    sigma_cpnm: float

    @property
    def vector(self) -> np.ndarray:
        return np.asarray([self.gx_cpnm, self.gy_cpnm], dtype=float)


@dataclass
class LatticeScanResult:
    scan_id: str
    reciprocal_basis_cpnm: np.ndarray
    direct_basis_nm: np.ndarray
    a_nm: float
    b_nm: float
    gamma_deg: float
    score: float
    quality_weight: float
    fft_peaks: list[FFTPeak]
    corrected_image: np.ndarray | None = None
    grid: GridDefinition | None = None
    selection_method: str = "automatic"


@dataclass
class LatticeSummary:
    basis_nm: np.ndarray
    a_nm: float
    b_nm: float
    gamma_deg: float
    sigma_a_nm: float
    sigma_b_nm: float
    sigma_gamma_deg: float
    interval68: dict[str, tuple[float, float]]
    interval95: dict[str, tuple[float, float]]
    bootstrap_samples: np.ndarray
    per_scan: list[LatticeScanResult]


@dataclass(frozen=True)
class CropRegion:
    xmin_nm: float
    xmax_nm: float
    ymin_nm: float
    ymax_nm: float

    @property
    def width_nm(self) -> float:
        return self.xmax_nm - self.xmin_nm

    @property
    def height_nm(self) -> float:
        return self.ymax_nm - self.ymin_nm

    def to_dict(self) -> dict[str, float]:
        return {
            "xmin_nm": self.xmin_nm,
            "xmax_nm": self.xmax_nm,
            "ymin_nm": self.ymin_nm,
            "ymax_nm": self.ymax_nm,
        }
