from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import tomllib


@dataclass
class CalibrationOverride:
    factor_x: float = 1.0
    factor_y: float = 1.0
    factor_z: float = 1.0


@dataclass
class AnnotationConfig:
    label_a: str = "a"
    label_b: str = "b"
    label_gamma: str = "γ"
    color_a: str = "#00B8D9"
    color_b: str = "#FFB000"
    color_gamma: str = "#FFFFFF"
    placement: str = "auto"
    scale_bar_length_nm: float | None = None


@dataclass
class AnalysisConfig:
    calibration_override: CalibrationOverride = field(default_factory=CalibrationOverride)
    annotation: AnnotationConfig = field(default_factory=AnnotationConfig)
    timing_tolerance_fraction: float = 0.01
    trace_direction: str = "forward"
    coarse_grid_max_pixels: int = 160
    phase_upsample_factor: int = 20
    max_pair_count: int = 48
    max_residual_shift_nm: float = 1.0
    max_abs_drift_nm_s: float = 0.05
    drift_coarse_grid_points: int = 7
    drift_coarse_levels: int = 3
    drift_coarse_pair_count: int = 10
    drift_bootstrap_repeats: int = 32
    lattice_bootstrap_repeats: int = 400
    bootstrap_seed: int = 42
    fft_dc_radius_bins: int = 4
    fft_min_peak_distance_bins: int = 4
    fft_max_peaks: int = 32
    fft_partner_tolerance_bins: float = 2.0
    lattice_min_nm: float = 0.15
    lattice_max_nm: float = 5.0
    common_grid_pixel_size_nm: float | None = None
    manual_lattice_fallback: bool = False
    atom_tracking_prior_weight: float = 0.35
    atom_tracking_prior_sigma_nm_s: float = 0.01


@dataclass
class StackConfig:
    method: str = "sigma_clipped_mean"
    sigma_clip: float = 3.0
    trace_direction: str = "forward"
    output_pixel_size_nm: float | None = None
    common_mask_max_pixels: int = 512
    crop_mode: str = "largest_rectangle"
    max_residual_shift_nm: float = 0.5
    use_analysis_residual_for_physical_area: bool = False
    fine_registration_for_stack: bool = True
    frame_offset_normalization: bool = True
    topography_plane_normalization: bool = False


def _merge_dataclass(instance: Any, values: dict[str, Any]) -> Any:
    for key, value in values.items():
        if not hasattr(instance, key):
            continue
        current = getattr(instance, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge_dataclass(current, value)
        else:
            setattr(instance, key, value)
    return instance


def load_analysis_config(path: Path | None) -> AnalysisConfig:
    cfg = AnalysisConfig()
    if path is None:
        return cfg
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    section = raw.get("analysis", raw)
    return _merge_dataclass(cfg, section)


def load_stack_config(path: Path | None) -> StackConfig:
    cfg = StackConfig()
    if path is None:
        return cfg
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    section = raw.get("stack", raw)
    return _merge_dataclass(cfg, section)


def config_to_dict(config: Any) -> dict[str, Any]:
    return asdict(config)
