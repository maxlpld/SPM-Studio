from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from typing import Any, Callable

import matplotlib.pyplot as plt
import numpy as np

from spm_multiframe import __version__
from spm_multiframe.analysis.quality import robust_noise_sigma
from spm_multiframe.analysis.registration import preprocess_registration_copy, register_physical_images, subtract_robust_plane
from spm_multiframe.config import CalibrationOverride, StackConfig, config_to_dict
from spm_multiframe.exceptions import SPMError, StaleAnalysisError
from spm_multiframe.geometry.coordinates import pixel_to_nominal_xy
from spm_multiframe.geometry.overlap import (
    build_common_masks,
    find_common_crop,
    recommend_initial_inclusion,
)
from spm_multiframe.geometry.timing import pixel_to_acquisition_time
from spm_multiframe.geometry.transforms import corrected_coordinates
from spm_multiframe.io.exports import read_json, write_csv, write_float_tiff, write_json
from spm_multiframe.io.metadata import metadata_for_channel, metadata_from_sxm
from spm_multiframe.io.scan_reader import read_scan
from spm_multiframe.io.sxm_reader import SXMFile
from spm_multiframe.models import CropRegion, GridDefinition, ScanMetadata
from spm_multiframe.plotting.diagnostics import plot_noise_vs_frames, plot_registration_residuals
from spm_multiframe.plotting.display import is_topography_channel
from spm_multiframe.plotting.reports import save_image_figure, write_stack_report
from spm_multiframe.stacking.combine import StackStatistics, combine_frames
from spm_multiframe.stacking.resample import grid_for_crop, resample_to_grid
from spm_multiframe.utils.hashing import dataset_id, sha256_file

STACK_SCHEMA_VERSION = "1.1"


@dataclass
class StackBundle:
    scan_id: str
    relative_path: str
    sxm: SXMFile
    metadata: ScanMetadata
    trace_direction: str
    physical_x_nm: np.ndarray
    physical_y_nm: np.ndarray
    stack_x_nm: np.ndarray
    stack_y_nm: np.ndarray
    manifest_residual_nm: np.ndarray
    fine_shift_nm: np.ndarray
    registration_score: float
    quality_flags: list[str]

    def channel(self, name: str) -> np.ndarray | None:
        directions = self.sxm.channels.get(name)
        if directions is None:
            return None
        return directions.get(self.trace_direction)


@dataclass(frozen=True)
class StackRunResult:
    manifest_path: Path
    report_path: Path
    output_dir: Path
    manifest: dict[str, Any]


def find_analysis_manifest(dataset_dir: Path) -> Path | None:
    candidates = [
        dataset_dir / "analysis_results" / "drift_lattice_results.json",
        dataset_dir / "drift_lattice_results.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    found = sorted(dataset_dir.glob("**/drift_lattice_results.json"))
    return found[0] if found else None


def verify_analysis_manifest(dataset_dir: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    required = {"schema_version", "software_version", "dataset_id", "source_files", "drift", "scans"}
    missing = required - set(manifest)
    if missing:
        raise StaleAnalysisError(f"Analysis manifest is missing required keys: {sorted(missing)}")
    current_items: list[tuple[str, str]] = []
    errors: list[str] = []
    for source in manifest["source_files"]:
        rel = source["relative_path"]
        path = dataset_dir / rel
        if not path.exists():
            errors.append(f"missing file: {rel}")
            continue
        current_hash = sha256_file(path)
        current_items.append((rel, current_hash))
        if current_hash != source["sha256"]:
            errors.append(f"hash changed: {rel}")
    current_id = dataset_id(current_items) if current_items else ""
    if current_id != manifest["dataset_id"]:
        errors.append("dataset ID does not match the analysis manifest")
    if errors:
        raise StaleAnalysisError("Analysis is stale: " + "; ".join(errors))
    return manifest


def _calibration_from_manifest(manifest: dict[str, Any]) -> CalibrationOverride:
    raw = manifest.get("calibration_override", {})
    return CalibrationOverride(
        factor_x=float(raw.get("factor_x", 1.0)),
        factor_y=float(raw.get("factor_y", 1.0)),
        factor_z=float(raw.get("factor_z", 1.0)),
    )


def _load_sources(dataset: Path, manifest: dict[str, Any]) -> dict[str, tuple[SXMFile, ScanMetadata]]:
    result: dict[str, tuple[SXMFile, ScanMetadata]] = {}
    for source in manifest["source_files"]:
        rel = source["relative_path"]
        sxm = read_scan(dataset / rel, load_data=True)
        meta = metadata_from_sxm(sxm)
        if meta.nx != int(source["nx"]) or meta.ny != int(source["ny"]):
            raise StaleAnalysisError(f"Dimensions changed for {rel}")
        result[rel] = (sxm, meta)
    return result


def _build_bundles(
    dataset: Path,
    manifest: dict[str, Any],
    sources: dict[str, tuple[SXMFile, ScanMetadata]],
    config: StackConfig,
) -> list[StackBundle]:
    calibration = _calibration_from_manifest(manifest)
    velocity = np.asarray(manifest["drift"]["correction_velocity_nm_s"], dtype=float)
    reference_time = float(manifest["reference_time_s"])
    bundles: list[StackBundle] = []
    for scan in manifest["scans"]:
        rel = scan["relative_path"]
        sxm, current_meta = sources[rel]
        # Preserve the exact time reference used by analysis if REC_DATE/REC_TIME was absent
        # and the dataset has since been copied to a new filesystem.
        direction = scan["trace_direction"]
        registration_channel = str(manifest["registration_channel"])
        meta = metadata_for_channel(sxm, current_meta, registration_channel, direction)
        meta = replace(
            meta,
            start_time_s=float(scan.get("start_time_s", meta.start_time_s)),
            end_time_s=float(scan.get("end_time_s", meta.end_time_s)),
        )
        x_nom, y_nom = pixel_to_nominal_xy(meta, direction, calibration)
        t_s = pixel_to_acquisition_time(meta, direction)
        residual = np.asarray(scan.get("residual_translation_nm", [0.0, 0.0]), dtype=float)
        # Physical footprint selection is anchored to Nanonis scan centre/range/angle and
        # the fitted time-dependent drift.  Image-registration translations are kept
        # separate so they cannot silently move a scan footprint to create a false overlap.
        x_physical, y_physical = corrected_coordinates(
            x_nom,
            y_nom,
            t_s,
            velocity,
            reference_time,
        )
        if config.use_analysis_residual_for_physical_area:
            x_area = x_physical + residual[0]
            y_area = y_physical + residual[1]
        else:
            x_area = x_physical
            y_area = y_physical
        # The stacking coordinates may use the small residual translation estimated in the
        # analysis stage, but the preview/common-region decision remains metadata+drift based.
        x_stack = x_physical + residual[0]
        y_stack = y_physical + residual[1]
        bundles.append(
            StackBundle(
                scan_id=scan["scan_id"],
                relative_path=rel,
                sxm=sxm,
                metadata=meta,
                trace_direction=direction,
                physical_x_nm=x_area,
                physical_y_nm=y_area,
                stack_x_nm=x_stack,
                stack_y_nm=y_stack,
                manifest_residual_nm=residual,
                fine_shift_nm=np.zeros(2),
                registration_score=float(scan.get("registration_score", 0.0)),
                quality_flags=list(scan.get("quality_flags", [])),
            )
        )
    return bundles


def _native_pixel_size(bundles: list[StackBundle]) -> float:
    return float(
        np.median(
            [
                min(bundle.metadata.native_dx_nm, bundle.metadata.native_dy_nm)
                for bundle in bundles
            ]
        )
    )


def _fine_register(
    bundles: list[StackBundle],
    registration_channel: str,
    config: StackConfig,
    logger: logging.Logger | None,
) -> None:
    available = [bundle for bundle in bundles if bundle.channel(registration_channel) is not None]
    if not available:
        raise SPMError(f"Registration channel {registration_channel!r} is absent from every frame")
    reference = max(available, key=lambda bundle: bundle.registration_score)
    ref_data = preprocess_registration_copy(reference.channel(registration_channel))
    pixel_size = _native_pixel_size(bundles)
    for bundle in bundles:
        data = bundle.channel(registration_channel)
        if data is None:
            bundle.quality_flags.append("missing_registration_channel")
            bundle.registration_score = 0.0
            continue
        if bundle is reference:
            bundle.fine_shift_nm[:] = 0.0
            continue
        reg = register_physical_images(
            ref_data,
            reference.stack_x_nm,
            reference.stack_y_nm,
            preprocess_registration_copy(data),
            bundle.stack_x_nm,
            bundle.stack_y_nm,
            pixel_size_nm=pixel_size,
            max_pixels=256,
            upsample_factor=20,
        )
        if reg is None:
            bundle.quality_flags.append("fine_registration_failed")
            bundle.registration_score = 0.0
            continue
        if np.linalg.norm(reg.shift_nm) > config.max_residual_shift_nm:
            bundle.quality_flags.append("large_stack_residual_shift")
            if logger:
                logger.warning(
                    "%s requested %.4g nm fine shift (> %.4g nm); not applied",
                    bundle.scan_id,
                    np.linalg.norm(reg.shift_nm),
                    config.max_residual_shift_nm,
                )
            continue
        bundle.fine_shift_nm = reg.shift_nm
        bundle.stack_x_nm = bundle.stack_x_nm + reg.shift_nm[0]
        bundle.stack_y_nm = bundle.stack_y_nm + reg.shift_nm[1]
        bundle.registration_score = reg.score


def _channel_data_with_calibration(
    bundle: StackBundle,
    channel: str,
    calibration: CalibrationOverride,
) -> np.ndarray | None:
    data = bundle.channel(channel)
    if data is None:
        return None
    arr = np.asarray(data, dtype=float)
    name = channel.lower()
    unit = bundle.metadata.channel_units.get(channel, "").lower()
    if calibration.factor_z != 1.0 and (name in {"z", "height", "topography"} or unit in {"m", "meter", "metre"}):
        arr = arr * calibration.factor_z
    return arr


def _preview_metadata(bundle: StackBundle, manifest: dict[str, Any]) -> dict[str, Any]:
    velocity = np.asarray(manifest["drift"]["correction_velocity_nm_s"], dtype=float)
    t_ref = float(manifest["reference_time_s"])
    drift_mag = float(np.linalg.norm(velocity * (bundle.metadata.midpoint_time_s - t_ref)))
    total_residual = bundle.manifest_residual_nm + bundle.fine_shift_nm
    finite = np.isfinite(bundle.physical_x_nm) & np.isfinite(bundle.physical_y_nm)
    if np.any(finite):
        corrected_center = [
            float(np.nanmean(bundle.physical_x_nm[finite])),
            float(np.nanmean(bundle.physical_y_nm[finite])),
        ]
        physical_bounds = [
            float(np.nanmin(bundle.physical_x_nm[finite])),
            float(np.nanmax(bundle.physical_x_nm[finite])),
            float(np.nanmin(bundle.physical_y_nm[finite])),
            float(np.nanmax(bundle.physical_y_nm[finite])),
        ]
    else:
        corrected_center = [float("nan"), float("nan")]
        physical_bounds = [float("nan")] * 4
    return {
        "acquisition_datetime": bundle.metadata.acquisition_datetime,
        "nx": bundle.metadata.nx,
        "ny": bundle.metadata.ny,
        "width_nm": bundle.metadata.width_nm,
        "height_nm": bundle.metadata.height_nm,
        "center_x_nm": bundle.metadata.center_x_nm,
        "center_y_nm": bundle.metadata.center_y_nm,
        "corrected_center_nm": corrected_center,
        "physical_bounds_nm": physical_bounds,
        "scan_angle_deg": bundle.metadata.scan_angle_deg,
        "frame_direction": bundle.metadata.frame_direction,
        "trace_direction": bundle.trace_direction,
        "drift_correction_magnitude_nm": drift_mag,
        "residual_shift_magnitude_nm": float(np.linalg.norm(total_residual)),
        "registration_score": bundle.registration_score,
    }


def _safe_channel_name(channel: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", channel.strip())
    return safe or "channel"


def _normalize_resampled_frames(
    frames: list[np.ndarray],
    *,
    frame_offset: bool,
    plane: bool,
) -> tuple[list[np.ndarray], list[float]]:
    if not frames:
        return [], []
    processed = [np.asarray(frame, dtype=float).copy() for frame in frames]
    plane_offsets: list[float] = []
    if plane:
        processed = [subtract_robust_plane(frame) for frame in processed]
    if frame_offset:
        reference = processed[0]
        adjusted = [reference]
        plane_offsets.append(0.0)
        for frame in processed[1:]:
            valid = np.isfinite(reference) & np.isfinite(frame)
            offset = float(np.nanmedian(frame[valid] - reference[valid])) if np.any(valid) else 0.0
            adjusted.append(frame - offset)
            plane_offsets.append(offset)
        processed = adjusted
    else:
        plane_offsets = [0.0] * len(processed)
    return processed, plane_offsets


def _save_stack_presentation(
    output: Path,
    channel: str,
    stats: StackStatistics,
    grid: GridDefinition,
    manifest: dict[str, Any],
) -> None:
    safe = _safe_channel_name(channel)
    lattice = manifest["lattice"]
    save_image_figure(
        stats.value,
        grid,
        output / f"stacked_{safe}.png",
        title=f"Stacked {channel}",
        basis_nm=np.asarray(lattice["basis_nm"], dtype=float),
        gamma_deg=float(lattice["gamma_deg"]),
        show_scale_bar=True,
        colorbar_label=channel,
        channel_name=channel,
    )


def run_stack(
    dataset_dir: str | Path,
    *,
    registration_channel: str,
    stack_channels: list[str],
    manifest_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    config: StackConfig | None = None,
    use_gui: bool = True,
    logger: logging.Logger | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> StackRunResult:
    cfg = config or StackConfig()
    dataset = Path(dataset_dir).expanduser().resolve()
    selected_manifest = Path(manifest_path).expanduser().resolve() if manifest_path else find_analysis_manifest(dataset)
    if selected_manifest is None:
        raise StaleAnalysisError("No drift_lattice_results.json was found for this dataset")
    if progress:
        progress(1, 7, "Verifying analysis manifest and source hashes")
    if logger:
        logger.info("[1/7] Verifying analysis manifest and source hashes")
    analysis_manifest = verify_analysis_manifest(dataset, selected_manifest)
    output = Path(output_dir).expanduser().resolve() if output_dir else dataset / "stack_results"
    figures = output / "figures"
    output.mkdir(parents=True, exist_ok=True)
    figures.mkdir(exist_ok=True)

    if progress:
        progress(2, 7, "Loading selected channels and metadata")
    if logger:
        logger.info("[2/7] Loading selected channels and metadata")
    sources = _load_sources(dataset, analysis_manifest)
    bundles = _build_bundles(dataset, analysis_manifest, sources, cfg)
    if registration_channel not in {name for bundle in bundles for name in bundle.sxm.channels}:
        raise SPMError(f"Registration channel {registration_channel!r} was not found")
    if progress:
        progress(3, 7, "Reconstructing metadata + drift physical coordinates")
    if logger:
        logger.info("[3/7] Reconstructing metadata + drift physical coordinates")

    output_pixel = cfg.output_pixel_size_nm or _native_pixel_size(bundles)
    registration_data = [bundle.channel(registration_channel) for bundle in bundles]
    # IMPORTANT: common physical coverage uses metadata-defined scan position/range/angle
    # plus the fitted per-pixel drift only. Registration translations do not decide which
    # physical sample area was actually acquired.
    coordinate_sets = [(bundle.physical_x_nm, bundle.physical_y_nm) for bundle in bundles]
    valid_sources = [
        np.isfinite(data) if data is not None else np.zeros((bundle.metadata.ny, bundle.metadata.nx), dtype=bool)
        for bundle, data in zip(bundles, registration_data, strict=True)
    ]
    if progress:
        progress(4, 7, "Computing absolute physical coverage from scan metadata and drift")
    if logger:
        logger.info("[4/7] Computing absolute physical coverage from scan metadata and drift")
    mask_result = build_common_masks(
        coordinate_sets,
        valid_sources,
        output_pixel,
        max_pixels=cfg.common_mask_max_pixels,
    )

    calibration = _calibration_from_manifest(analysis_manifest)
    preview_channels = list(dict.fromkeys([registration_channel, *stack_channels]))
    included_ids: tuple[str, ...]
    reference_scan_id: str | None = None
    crop: CropRegion | None
    if use_gui:
        try:
            from spm_multiframe.gui.common_region_preview import PreviewItem, run_common_region_preview
        except ImportError as exc:
            raise SPMError("PySide6 GUI could not be imported; rerun with --no-gui") from exc
        items = []
        for bundle in bundles:
            channels: dict[str, np.ndarray] = {}
            for channel in preview_channels:
                data = _channel_data_with_calibration(bundle, channel, calibration)
                if data is not None:
                    channels[channel] = data
            items.append(
                PreviewItem(
                    scan_id=bundle.scan_id,
                    metadata=_preview_metadata(bundle, analysis_manifest),
                    x_nm=bundle.physical_x_nm,
                    y_nm=bundle.physical_y_nm,
                    channels=channels,
                    quality_flags=bundle.quality_flags,
                )
            )
        selection = run_common_region_preview(
            items,
            mask_result.masks,
            mask_result.grid,
            preview_channels,
            initial_pixel_size_nm=output_pixel,
            lattice_basis_nm=np.asarray(analysis_manifest["lattice"]["basis_nm"], dtype=float),
            gamma_deg=float(analysis_manifest["lattice"]["gamma_deg"]),
            snapshot_path=figures / "common_region_preview.png",
        )
        if not selection.accepted:
            raise SPMError("Stacking cancelled in the common-region preview")
        included_ids = selection.included_scan_ids
        crop = selection.crop
        output_pixel = selection.output_pixel_size_nm
        reference_scan_id = selection.reference_scan_id
    else:
        recommended, crop = recommend_initial_inclusion(
            mask_result.masks, mask_result.grid, mode=cfg.crop_mode
        )
        included_ids = tuple(
            bundle.scan_id
            for bundle, keep in zip(bundles, recommended, strict=True)
            if keep
        )
    if crop is None:
        raise SPMError("No common physical region exists for the selected scans")

    included_bundles = [bundle for bundle in bundles if bundle.scan_id in included_ids]
    if progress:
        progress(5, 7, "Fine registration inside the validated physical scan set")
    if logger:
        logger.info("[5/7] Fine registration inside the validated physical scan set")
    if cfg.fine_registration_for_stack:
        _fine_register(included_bundles, registration_channel, cfg, logger)

    final_grid = grid_for_crop(crop, output_pixel)
    excluded_bundles = [bundle for bundle in bundles if bundle.scan_id not in included_ids]
    channel_outputs: dict[str, dict[str, Any]] = {}
    noise_progress_for_registration: list[float] = []

    if progress:
        progress(6, 7, "Stacking selected channels")
    if logger:
        logger.info("[6/7] Stacking selected channels")
    for channel in stack_channels:
        resampled: list[np.ndarray] = []
        weights: list[float] = []
        used_ids: list[str] = []
        missing_ids: list[str] = []
        for bundle in included_bundles:
            data = _channel_data_with_calibration(bundle, channel, calibration)
            if data is None:
                missing_ids.append(bundle.scan_id)
                continue
            resampled.append(resample_to_grid(data, bundle.stack_x_nm, bundle.stack_y_nm, final_grid))
            weights.append(max(bundle.registration_score, 0.05))
            used_ids.append(bundle.scan_id)
        if not resampled:
            if logger:
                logger.warning("No usable frames for channel %s; skipping", channel)
            continue
        is_topography = is_topography_channel(channel)
        normalized, offsets = _normalize_resampled_frames(
            resampled,
            # A constant frame-wise Z offset is a vertical baseline correction, not a
            # lateral/image filter.  It is applied to topography only so Bias/Current/etc.
            # retain their absolute channel values unless a future channel-specific option
            # explicitly requests otherwise.
            frame_offset=bool(cfg.frame_offset_normalization and is_topography),
            plane=bool(cfg.topography_plane_normalization and is_topography),
        )
        stats = combine_frames(
            normalized,
            method=cfg.method,
            weights=np.asarray(weights),
            sigma_clip=cfg.sigma_clip,
        )
        safe = _safe_channel_name(channel)
        np.save(output / f"stacked_{safe}.npy", stats.value)
        np.save(output / f"uncertainty_{safe}.npy", stats.uncertainty)
        np.save(output / f"contribution_count_{safe}.npy", stats.contribution_count)
        write_float_tiff(output / f"stacked_{safe}.tif", stats.value)
        _save_stack_presentation(output, channel, stats, final_grid, analysis_manifest)
        channel_outputs[channel] = {
            "used_scan_ids": used_ids,
            "missing_scan_ids": missing_ids,
            "frame_offsets": offsets,
            "n_frames": len(used_ids),
        }
        if channel == registration_channel:
            for n in range(1, len(normalized) + 1):
                partial = combine_frames(
                    normalized[:n],
                    method=("weighted_mean" if n < 3 and cfg.method == "sigma_clipped_mean" else cfg.method),
                    weights=np.asarray(weights[:n]),
                    sigma_clip=cfg.sigma_clip,
                )
                noise_progress_for_registration.append(robust_noise_sigma(partial.value))
            # Keep the requested presentation filename in addition to the top-level export.
            save_image_figure(
                stats.value,
                final_grid,
                figures / f"stacked_{safe}_with_lattice_and_scale.png",
                title=f"Stacked {channel} with lattice",
                basis_nm=np.asarray(analysis_manifest["lattice"]["basis_nm"], dtype=float),
                gamma_deg=float(analysis_manifest["lattice"]["gamma_deg"]),
                show_scale_bar=True,
                colorbar_label=channel,
                channel_name=channel,
            )

    scan_rows = []
    for bundle in bundles:
        total_shift = bundle.manifest_residual_nm + bundle.fine_shift_nm
        scan_rows.append(
            {
                "scan_id": bundle.scan_id,
                "included": bundle.scan_id in included_ids,
                "registration_score": bundle.registration_score,
                "residual_shift_magnitude_nm": float(np.linalg.norm(total_shift)),
                "fine_dx_nm": float(bundle.fine_shift_nm[0]),
                "fine_dy_nm": float(bundle.fine_shift_nm[1]),
                "flags": ",".join(bundle.quality_flags),
            }
        )
    plot_registration_residuals(scan_rows, figures / "registration_residuals.png")
    plot_noise_vs_frames(noise_progress_for_registration, figures / "noise_vs_number_of_frames.png")

    write_csv(
        output / "included_scans.csv",
        [row for row in scan_rows if row["included"]],
    )
    write_csv(
        output / "excluded_scans.csv",
        [row for row in scan_rows if not row["included"]],
    )
    write_json(output / "common_region.json", crop.to_dict())

    if progress:
        progress(7, 7, "Exporting results and report")
    if logger:
        logger.info("[7/7] Exporting results and report")
    stack_manifest = {
        "schema_version": STACK_SCHEMA_VERSION,
        "software_version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_manifest": str(selected_manifest),
        "analysis_manifest_sha256": sha256_file(selected_manifest),
        "analysis_dataset_id": analysis_manifest["dataset_id"],
        "registration_channel": registration_channel,
        "stack_channels": stack_channels,
        "included_scans": list(included_ids),
        "excluded_scans": [bundle.scan_id for bundle in excluded_bundles],
        "visual_reference_scan": reference_scan_id,
        "common_region_nm": crop.to_dict(),
        "output_pixel_size_nm": output_pixel,
        "output_shape": list(final_grid.shape),
        "stacking": config_to_dict(cfg),
        "channel_outputs": channel_outputs,
        "fine_residual_translations_nm": {
            bundle.scan_id: bundle.fine_shift_nm.tolist() for bundle in bundles
        },
        "lattice": analysis_manifest["lattice"],
        "physical_area_geometry": (
            "metadata_plus_linear_drift_plus_analysis_residual"
            if cfg.use_analysis_residual_for_physical_area
            else "metadata_plus_linear_drift"
        ),
        "stack_alignment_geometry": "physical_area_plus_small_rigid_registration",
        "quantitative_geometry": "linear_drift_plus_rigid_translation_only",
    }
    manifest_out = output / "stack_manifest.json"
    write_json(manifest_out, stack_manifest)
    report_path = output / "stack_report.md"
    write_stack_report(report_path, stack_manifest)
    return StackRunResult(manifest_out, report_path, output, stack_manifest)
