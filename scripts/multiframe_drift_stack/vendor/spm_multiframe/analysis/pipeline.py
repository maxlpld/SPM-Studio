from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from spm_multiframe import __version__
from spm_multiframe.analysis.drift import fit_linear_drift
from spm_multiframe.analysis.lattice import analyze_lattice
from spm_multiframe.analysis.quality import invalid_fraction, quality_flags, robust_noise_sigma
from spm_multiframe.config import AnalysisConfig, config_to_dict
from spm_multiframe.exceptions import MissingMetadataError, SPMError
from spm_multiframe.geometry.coordinates import pixel_to_nominal_xy
from spm_multiframe.geometry.timing import pixel_to_acquisition_time
from spm_multiframe.geometry.transforms import corrected_coordinates
from spm_multiframe.io.atom_tracking import AtomTrackingHint
from spm_multiframe.io.exports import write_csv, write_json
from spm_multiframe.io.metadata import metadata_for_channel, metadata_from_sxm
from spm_multiframe.io.scan_reader import InputFormat, discover_scan_files, read_scan, source_format_for_paths
from spm_multiframe.io.sxm_reader import SXMFile, normalize_direction
from spm_multiframe.models import DriftFitResult, LatticeScanResult, ScanFrame, ScanMetadata
from spm_multiframe.plotting.diagnostics import (
    plot_drift_bootstrap,
    plot_drift_fit,
    plot_fft_diagnostic,
    plot_lattice_per_scan,
    plot_registration_residuals,
)
from spm_multiframe.plotting.reports import (
    save_image_figure,
    save_lattice_summary_table,
    write_analysis_report,
)
from spm_multiframe.utils.hashing import dataset_id

SCHEMA_VERSION = "1.1"


@dataclass(frozen=True)
class AnalysisRunResult:
    manifest_path: Path
    report_path: Path
    output_dir: Path
    manifest: dict


def _common_channels(files: list[SXMFile]) -> list[str]:
    if not files:
        return []
    common = set(files[0].channels)
    for sxm in files[1:]:
        common &= set(sxm.channels)
    return sorted(common)


def _actual_directions(sxm: SXMFile, channel: str, requested: str) -> list[str]:
    available = list(sxm.channels[channel])
    requested = normalize_direction(requested)
    if requested == "both":
        return [direction for direction in ("forward", "backward") if direction in available] or available
    if requested in available:
        return [requested]
    if len(available) == 1:
        return available
    raise MissingMetadataError(
        f"{sxm.path.name}: requested {requested!r} trace but {channel!r} has {available}"
    )


def _apply_vertical_override(data: np.ndarray, metadata: ScanMetadata, channel: str, config: AnalysisConfig) -> np.ndarray:
    factor = config.calibration_override.factor_z
    unit = metadata.channel_units.get(channel, "").strip().lower()
    name = channel.strip().lower()
    if factor != 1.0 and (name in {"z", "height", "topography"} or unit in {"m", "meter", "metre"}):
        return np.asarray(data, dtype=float) * factor
    return np.asarray(data, dtype=float)


def _build_frames(
    dataset_dir: Path,
    sxm_files: list[SXMFile],
    metadata: list[ScanMetadata],
    channel: str,
    config: AnalysisConfig,
    *,
    estimate_drift: bool,
) -> list[ScanFrame]:
    frames: list[ScanFrame] = []
    for sxm, meta in zip(sxm_files, metadata, strict=True):
        if channel not in sxm.channels:
            continue
        for direction in _actual_directions(sxm, channel, config.trace_direction):
            # A GWY file can contain cropped/resized channels with a different raster
            # shape and physical extent from the first/original channel.  Bind geometry
            # to the concrete channel before constructing x/y/t arrays.
            frame_meta = metadata_for_channel(sxm, meta, channel, direction)
            x_nom, y_nom = pixel_to_nominal_xy(
                frame_meta, direction, config.calibration_override
            )
            if estimate_drift:
                t_s = pixel_to_acquisition_time(
                    frame_meta,
                    direction,
                    timing_tolerance_fraction=config.timing_tolerance_fraction,
                )
            else:
                # Lattice-only analysis does not need acquisition timing.  A constant
                # map prevents any accidental time-dependent coordinate correction while
                # still satisfying the ScanFrame shape contract.
                t_s = np.full(
                    (frame_meta.ny, frame_meta.nx),
                    frame_meta.midpoint_time_s,
                    dtype=float,
                )
            relative = sxm.path.resolve().relative_to(dataset_dir.resolve()).as_posix()
            frames.append(
                ScanFrame(
                    metadata=frame_meta,
                    channel=channel,
                    trace_direction=direction,
                    data=_apply_vertical_override(
                        sxm.get_channel(channel, direction), frame_meta, channel, config
                    ),
                    x_nom_nm=x_nom,
                    y_nom_nm=y_nom,
                    t_s=t_s,
                    scan_id=f"{relative}::{direction}",
                )
            )
    frames.sort(key=lambda frame: frame.metadata.midpoint_time_s)
    return frames


def inspect_dataset(
    dataset_dir: Path,
    config: AnalysisConfig,
    *,
    input_format: InputFormat = "auto",
    logger: logging.Logger | None = None,
) -> tuple[list[Path], list[SXMFile], list[ScanMetadata], list[str]]:
    paths = discover_scan_files(dataset_dir, recursive=True, input_format=input_format)
    if not paths:
        raise SPMError(f"No supported .sxm/.gwy files found under {dataset_dir}")
    sxm_files: list[SXMFile] = []
    metadata: list[ScanMetadata] = []
    usable_paths: list[Path] = []
    for path in paths:
        try:
            sxm = read_scan(path, load_data=True)
            meta = metadata_from_sxm(
                sxm, timing_tolerance_fraction=config.timing_tolerance_fraction
            )
        except (SPMError, OSError, ValueError) as exc:
            if logger:
                logger.warning("Skipping unreadable scan %s: %s", path, exc)
            continue
        sxm_files.append(sxm)
        metadata.append(meta)
        usable_paths.append(path)
        if (
            logger
            and meta.extra.get("source_format") == "gwy"
            and not meta.extra.get("gwy_sidecar_geometry_used", False)
        ):
            logger.warning(
                "%s is a GWY without matched SXM geometry metadata; scan angle/offset "
                "may be reduced to what the GWY itself preserves",
                path.name,
            )
    if not sxm_files:
        raise SPMError("No readable SPM scans remained after metadata validation")
    return usable_paths, sxm_files, metadata, _common_channels(sxm_files)


def _lattice_lookup(per_scan: list[LatticeScanResult]) -> dict[str, LatticeScanResult]:
    return {result.scan_id: result for result in per_scan}


def _zero_drift_result(frames: list[ScanFrame]) -> DriftFitResult:
    """Create an explicit no-drift transform for lattice-only analysis."""
    if not frames:
        raise SPMError("At least one usable frame is required for lattice analysis")
    reference_time = float(np.median([frame.metadata.midpoint_time_s for frame in frames]))
    zeros = np.zeros(2, dtype=float)
    return DriftFitResult(
        correction_velocity_nm_s=zeros.copy(),
        sample_velocity_nm_s=zeros.copy(),
        sigma_nm_s=zeros.copy(),
        interval68_nm_s=np.zeros((2, 2), dtype=float),
        interval95_nm_s=np.zeros((2, 2), dtype=float),
        reference_time_s=reference_time,
        residual_translations_nm={str(frame.scan_id): zeros.copy() for frame in frames},
        registration_scores={str(frame.scan_id): 1.0 for frame in frames},
        pair_registrations=[],
        objective_value=0.0,
        bootstrap_samples_nm_s=np.empty((0, 2), dtype=float),
    )


def run_analysis(
    dataset_dir: str | Path,
    *,
    registration_channel: str,
    output_dir: str | Path | None = None,
    reference_scan: str | Path | None = None,
    input_format: InputFormat = "auto",
    estimate_drift: bool = True,
    atom_tracking_hint: AtomTrackingHint | None = None,
    config: AnalysisConfig | None = None,
    logger: logging.Logger | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> AnalysisRunResult:
    cfg = config or AnalysisConfig()
    dataset = Path(dataset_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve() if output_dir else dataset / "analysis_results"
    output.mkdir(parents=True, exist_ok=True)
    figures = output / "figures"
    fft_dir = output / "fft_diagnostics"
    figures.mkdir(exist_ok=True)
    fft_dir.mkdir(exist_ok=True)

    if progress:
        progress(1, 8, "Discovering and reading SPM files")
    if logger:
        logger.info("[1/8] Discovering and reading SPM files")
    paths, sxm_files, metadata, channels = inspect_dataset(
        dataset, cfg, input_format=input_format, logger=logger
    )
    if registration_channel not in channels:
        raise SPMError(
            f"Registration channel {registration_channel!r} is not common to all scans. Common channels: {channels}"
        )
    geometry_stage = (
        "Building physical coordinate/time maps"
        if estimate_drift
        else "Building physical coordinate maps"
    )
    if progress:
        progress(2, 8, geometry_stage)
    if logger:
        logger.info("[2/8] %s", geometry_stage)
    frames = _build_frames(
        dataset,
        sxm_files,
        metadata,
        registration_channel,
        cfg,
        estimate_drift=estimate_drift,
    )
    if not frames:
        raise SPMError("At least one usable frame is required for lattice analysis")
    if estimate_drift and len(frames) < 2:
        raise SPMError(
            "At least two usable frames are required for drift estimation. "
            "Rerun and choose lattice-only analysis for a single scan."
        )

    if estimate_drift:
        if progress:
            progress(3, 8, "Initial pair registration and linear drift fit")
        if logger:
            logger.info("[3/8] Initial pair registration and linear drift fit")
        drift = fit_linear_drift(
            frames,
            cfg,
            logger=logger,
            external_hint_nm_s=(
                None
                if atom_tracking_hint is None
                else atom_tracking_hint.correction_velocity_nm_s
            ),
        )
        if progress:
            progress(4, 8, "Applying corrected geometry and residual translations")
        if logger:
            logger.info("[4/8] Applying corrected geometry and residual translations")
    else:
        if progress:
            progress(3, 8, "Drift estimation disabled — using nominal physical geometry")
        if logger:
            logger.info("[3/8] Drift estimation disabled — lattice-only mode")
        drift = _zero_drift_result(frames)
        if progress:
            progress(4, 8, "Preparing physical geometry for lattice analysis")
        if logger:
            logger.info("[4/8] Preparing physical geometry for lattice analysis")
    if progress:
        progress(5, 8, "Detecting and canonicalizing the lattice")
    if logger:
        logger.info("[5/8] Detecting and canonicalizing the lattice")
    lattice = analyze_lattice(frames, drift, cfg, logger=logger)
    lattice_by_id = _lattice_lookup(lattice.per_scan)

    noise_values = np.asarray([robust_noise_sigma(frame.data) for frame in frames], dtype=float)
    median_noise = float(np.nanmedian(noise_values)) if np.any(np.isfinite(noise_values)) else float("nan")
    scan_rows: list[dict] = []
    scan_manifest: list[dict] = []
    for frame, noise in zip(frames, noise_values, strict=True):
        scan_id = str(frame.scan_id)
        residual = np.asarray(drift.residual_translations_nm.get(scan_id, np.zeros(2)), dtype=float)
        score = float(drift.registration_scores.get(scan_id, 0.0))
        x_corr, y_corr = corrected_coordinates(
            frame.x_nom_nm,
            frame.y_nom_nm,
            frame.t_s,
            drift.correction_velocity_nm_s,
            drift.reference_time_s,
            residual,
        )
        corners = [
            [float(x_corr[0, 0]), float(y_corr[0, 0])],
            [float(x_corr[0, -1]), float(y_corr[0, -1])],
            [float(x_corr[-1, -1]), float(y_corr[-1, -1])],
            [float(x_corr[-1, 0]), float(y_corr[-1, 0])],
        ]
        invalid = invalid_fraction(frame.data)
        flags = quality_flags(
            correlation=score,
            residual_shift_nm=float(np.linalg.norm(residual)),
            noise_sigma=float(noise),
            median_noise_sigma=median_noise,
            invalid_fraction_value=invalid,
            max_shift_nm=cfg.max_residual_shift_nm,
        )
        lres = lattice_by_id.get(scan_id)
        row = {
            "scan_id": scan_id,
            "filename": frame.metadata.path.name,
            "trace_direction": frame.trace_direction,
            "scan_angle_deg": frame.metadata.scan_angle_deg,
            "frame_direction": frame.metadata.frame_direction,
            "registration_score": score,
            "residual_dx_nm": float(residual[0]),
            "residual_dy_nm": float(residual[1]),
            "residual_shift_magnitude_nm": float(np.linalg.norm(residual)),
            "noise_sigma": float(noise),
            "invalid_fraction": invalid,
            "lattice_a_nm": "" if lres is None else f"{lres.a_nm:.8g}",
            "lattice_b_nm": "" if lres is None else f"{lres.b_nm:.8g}",
            "lattice_gamma_deg": "" if lres is None else f"{lres.gamma_deg:.8g}",
            "flags": ",".join(flags),
        }
        scan_rows.append(row)
        relative = frame.metadata.path.resolve().relative_to(dataset).as_posix()
        scan_manifest.append(
            {
                "scan_id": scan_id,
                "path": str(frame.metadata.path),
                "relative_path": relative,
                "sha256": frame.metadata.sha256,
                "included": True,
                "nx": frame.metadata.nx,
                "ny": frame.metadata.ny,
                "width_nm": frame.metadata.width_nm,
                "height_nm": frame.metadata.height_nm,
                "center_nm": [frame.metadata.center_x_nm, frame.metadata.center_y_nm],
                "scan_angle_deg": frame.metadata.scan_angle_deg,
                "frame_direction": frame.metadata.frame_direction,
                "trace_direction": frame.trace_direction,
                "start_time_s": frame.metadata.start_time_s,
                "end_time_s": frame.metadata.end_time_s,
                "timing_confidence": frame.metadata.timing_confidence,
                "residual_translation_nm": residual.tolist(),
                "registration_score": score,
                "quality_flags": flags,
                "corrected_footprint_nm": corners,
                "lattice_a_nm": None if lres is None else lres.a_nm,
                "lattice_b_nm": None if lres is None else lres.b_nm,
                "lattice_gamma_deg": None if lres is None else lres.gamma_deg,
                "lattice_direct_basis_nm": None if lres is None else lres.direct_basis_nm.tolist(),
                "lattice_reciprocal_basis_cpnm": None if lres is None else lres.reciprocal_basis_cpnm.tolist(),
                "lattice_score": None if lres is None else lres.score,
                "lattice_selection_method": None if lres is None else lres.selection_method,
            }
        )

    source_files = []
    for meta in metadata:
        relative = meta.path.resolve().relative_to(dataset).as_posix()
        source_files.append(
            {
                "relative_path": relative,
                "path": str(meta.path),
                "sha256": meta.sha256,
                "nx": meta.nx,
                "ny": meta.ny,
                "channel_names": list(meta.channel_names),
                "acquisition_datetime": meta.acquisition_datetime,
            }
        )
    ds_id = dataset_id([(item["relative_path"], item["sha256"]) for item in source_files])
    tmin = min(float(np.nanmin(frame.t_s)) for frame in frames)
    tmax = max(float(np.nanmax(frame.t_s)) for frame in frames)
    total_correction = drift.correction_velocity_nm_s * (tmax - tmin)

    if progress:
        progress(6, 8, "Writing reproducible numerical tables and manifest")
    if logger:
        logger.info("[6/8] Writing reproducible numerical tables and manifest")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "software_version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_root": str(dataset),
        "dataset_id": ds_id,
        "input_format": source_format_for_paths(paths),
        "source_files": source_files,
        "registration_channel": registration_channel,
        "analysis_mode": "drift_and_lattice" if estimate_drift else "lattice_only",
        "trace_direction": cfg.trace_direction,
        "reference_time_s": drift.reference_time_s,
        "analysis_parameters": config_to_dict(cfg),
        "calibration_override": asdict(cfg.calibration_override),
        "atom_tracking": (
            None
            if atom_tracking_hint is None
            else {
                **atom_tracking_hint.to_dict(),
                "prior_weight": cfg.atom_tracking_prior_weight,
                "prior_sigma_nm_s": cfg.atom_tracking_prior_sigma_nm_s,
                "role": "soft_prior_and_seed_for_image_based_drift_fit",
            }
        ),
        "drift": {
            "model": "linear" if estimate_drift else "none",
            "correction_velocity_nm_s": drift.correction_velocity_nm_s.tolist(),
            "sample_velocity_nm_s": drift.sample_velocity_nm_s.tolist(),
            "sigma_nm_s": drift.sigma_nm_s.tolist(),
            "bootstrap_68_percent": drift.interval68_nm_s.tolist(),
            "bootstrap_95_percent": drift.interval95_nm_s.tolist(),
            "objective_value": drift.objective_value,
            "total_correction_nm": total_correction.tolist(),
            "bootstrap_samples_nm_s": drift.bootstrap_samples_nm_s.tolist(),
        },
        "lattice": {
            "basis_nm": lattice.basis_nm.tolist(),
            "basis_convention": "2D Gauss-reduced primitive cell; a=longer vector, b=shorter vector, acute equivalent angle",
            "a_nm": lattice.a_nm,
            "b_nm": lattice.b_nm,
            "gamma_deg": lattice.gamma_deg,
            "sigma_a_nm": lattice.sigma_a_nm,
            "sigma_b_nm": lattice.sigma_b_nm,
            "sigma_gamma_deg": lattice.sigma_gamma_deg,
            "interval68": lattice.interval68,
            "interval95": lattice.interval95,
            "manual_selection_scan_ids": [
                result.scan_id for result in lattice.per_scan if result.selection_method == "manual"
            ],
        },
        "scans": scan_manifest,
    }
    manifest_path = output / "drift_lattice_results.json"
    write_json(manifest_path, manifest)
    write_csv(output / "per_scan_results.csv", scan_rows)
    write_csv(
        output / "lattice_summary.csv",
        [
            {
                "a_nm": lattice.a_nm,
                "sigma_a_nm": lattice.sigma_a_nm,
                "b_nm": lattice.b_nm,
                "sigma_b_nm": lattice.sigma_b_nm,
                "gamma_deg": lattice.gamma_deg,
                "sigma_gamma_deg": lattice.sigma_gamma_deg,
            }
        ],
    )
    write_csv(
        output / "drift_summary.csv",
        [
            {
                "correction_vx_nm_s": drift.correction_velocity_nm_s[0],
                "correction_vy_nm_s": drift.correction_velocity_nm_s[1],
                "sample_vx_nm_s": drift.sample_velocity_nm_s[0],
                "sample_vy_nm_s": drift.sample_velocity_nm_s[1],
                "sigma_vx_nm_s": drift.sigma_nm_s[0],
                "sigma_vy_nm_s": drift.sigma_nm_s[1],
                "atom_hint_vx_nm_s": (
                    "" if atom_tracking_hint is None else atom_tracking_hint.correction_velocity_nm_s[0]
                ),
                "atom_hint_vy_nm_s": (
                    "" if atom_tracking_hint is None else atom_tracking_hint.correction_velocity_nm_s[1]
                ),
                "atom_hint_source": "" if atom_tracking_hint is None else atom_tracking_hint.source,
            }
        ],
    )

    if progress:
        progress(7, 8, "Rendering diagnostics and FFT plots")
    if logger:
        logger.info("[7/8] Rendering diagnostics and FFT plots")
    if estimate_drift:
        plot_drift_fit(drift, figures / "01_drift_fit.png")
        plot_drift_bootstrap(drift, figures / "02_drift_bootstrap.png")
    plot_lattice_per_scan(lattice, "a_nm", figures / "03_lattice_a_per_scan.png")
    plot_lattice_per_scan(lattice, "b_nm", figures / "04_lattice_b_per_scan.png")
    plot_lattice_per_scan(lattice, "gamma_deg", figures / "05_lattice_gamma_per_scan.png")
    save_lattice_summary_table(lattice, figures / "06_lattice_summary_table.png")
    if estimate_drift:
        plot_registration_residuals(scan_rows, figures / "08_registration_residuals.png")
    for index, result in enumerate(lattice.per_scan, start=1):
        safe_name = Path(result.scan_id.split("::", 1)[0]).stem
        plot_fft_diagnostic(result, fft_dir / f"{index:04d}_{safe_name}_fft.png")

    overlay_result = None
    if reference_scan is not None:
        reference_path = Path(reference_scan).expanduser().resolve()
        for result in lattice.per_scan:
            frame = next((f for f in frames if f.scan_id == result.scan_id), None)
            if frame and frame.metadata.path.resolve() == reference_path:
                overlay_result = result
                break
    if overlay_result is None:
        overlay_result = max(lattice.per_scan, key=lambda result: result.quality_weight)
    if overlay_result.corrected_image is not None and overlay_result.grid is not None:
        save_image_figure(
            overlay_result.corrected_image,
            overlay_result.grid,
            figures / "07_reference_scan_lattice_overlay.png",
            title=f"Corrected lattice overlay — {overlay_result.scan_id}",
            basis_nm=lattice.basis_nm,
            gamma_deg=lattice.gamma_deg,
            annotation=cfg.annotation,
            show_scale_bar=True,
            channel_name=registration_channel,
        )

    if progress:
        progress(8, 8, "Writing final report")
    if logger:
        logger.info("[8/8] Writing final report")
    report_path = output / "analysis_report.md"
    write_analysis_report(report_path, manifest, scan_rows)
    return AnalysisRunResult(manifest_path, report_path, output, manifest)
