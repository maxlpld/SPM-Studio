from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from spm_multiframe.analysis.registration import (
    preprocess_registration_copy,
    register_physical_images,
)
from spm_multiframe.config import AnalysisConfig
from spm_multiframe.exceptions import DriftFitError
from spm_multiframe.geometry.transforms import corrected_coordinates
from spm_multiframe.models import DriftFitResult, PairRegistration, ScanFrame


@dataclass(frozen=True)
class _Pair:
    i: int
    j: int
    priority: float


def _angular_difference_deg(a: float, b: float) -> float:
    diff = abs((a - b) % 180.0)
    return min(diff, 180.0 - diff)


def select_informative_pairs(frames: list[ScanFrame], max_pair_count: int) -> list[_Pair]:
    """Rank scan pairs, prioritizing orthogonal/opposite rasters and temporal separation."""
    if len(frames) < 2:
        return []
    times = np.asarray([frame.metadata.midpoint_time_s for frame in frames], dtype=float)
    span = max(float(np.ptp(times)), 1e-9)
    pairs: list[_Pair] = []
    for i in range(len(frames) - 1):
        for j in range(i + 1, len(frames)):
            angle_diff = _angular_difference_deg(
                frames[i].metadata.scan_angle_deg, frames[j].metadata.scan_angle_deg
            )
            orthogonal_bonus = np.exp(-0.5 * ((angle_diff - 90.0) / 20.0) ** 2)
            opposite_bonus = float(
                frames[i].metadata.frame_direction != frames[j].metadata.frame_direction
            )
            time_bonus = abs(times[j] - times[i]) / span
            priority = 2.0 * orthogonal_bonus + 1.5 * opposite_bonus + time_bonus
            pairs.append(_Pair(i, j, float(priority)))
    pairs.sort(key=lambda item: item.priority, reverse=True)
    if max_pair_count > 0:
        pairs = pairs[:max_pair_count]
    return pairs


def _native_registration_pixel_size(frames: list[ScanFrame]) -> float:
    values = [
        min(frame.metadata.native_dx_nm, frame.metadata.native_dy_nm)
        for frame in frames
        if frame.metadata.native_dx_nm > 0 and frame.metadata.native_dy_nm > 0
    ]
    if not values:
        raise DriftFitError("Cannot determine a physical pixel size for registration")
    return float(np.median(values))


def initial_pair_registrations(
    frames: list[ScanFrame],
    prepared: list[np.ndarray],
    pairs: list[_Pair],
    config: AnalysisConfig,
) -> list[PairRegistration]:
    pixel_size = _native_registration_pixel_size(frames)
    results: list[PairRegistration] = []
    for pair in pairs:
        i, j = pair.i, pair.j
        reg = register_physical_images(
            prepared[i],
            frames[i].x_nom_nm,
            frames[i].y_nom_nm,
            prepared[j],
            frames[j].x_nom_nm,
            frames[j].y_nom_nm,
            pixel_size_nm=pixel_size,
            max_pixels=config.coarse_grid_max_pixels,
            upsample_factor=config.phase_upsample_factor,
        )
        dt = frames[j].metadata.midpoint_time_s - frames[i].metadata.midpoint_time_s
        if reg is None or abs(dt) < 1e-9:
            results.append(PairRegistration(i, j, np.zeros(2), 0.0, dt, valid=False))
            continue
        velocity = reg.shift_nm / dt
        plausible = np.all(np.abs(velocity) <= config.max_abs_drift_nm_s)
        # Correlation can lock to a neighbouring period in highly periodic images. An
        # implausible implied velocity is therefore rejected rather than used as an initial
        # condition for the global physical-coordinate fit.
        valid = bool(plausible and reg.score > 0.05 and np.isfinite(reg.mse))
        results.append(PairRegistration(i, j, reg.shift_nm, reg.score, dt, valid=valid))
    return results


def _initial_velocity(pair_results: list[PairRegistration]) -> np.ndarray:
    velocities = [
        pair.shift_nm / pair.dt_s
        for pair in pair_results
        if pair.valid and abs(pair.dt_s) > 1e-9
    ]
    if not velocities:
        return np.zeros(2, dtype=float)
    return np.median(np.asarray(velocities, dtype=float), axis=0)


def _candidate_residuals(
    velocity: np.ndarray,
    frames: list[ScanFrame],
    prepared: list[np.ndarray],
    pairs: list[_Pair],
    config: AnalysisConfig,
    reference_time_s: float,
    pair_weights: np.ndarray | None = None,
    external_hint_nm_s: np.ndarray | None = None,
) -> np.ndarray:
    pixel_size = _native_registration_pixel_size(frames)
    corrected: list[tuple[np.ndarray, np.ndarray]] = [
        corrected_coordinates(
            frame.x_nom_nm,
            frame.y_nom_nm,
            frame.t_s,
            velocity,
            reference_time_s,
        )
        for frame in frames
    ]
    residuals: list[float] = []
    weights = np.ones(len(pairs), dtype=float) if pair_weights is None else pair_weights
    for k, pair in enumerate(pairs):
        if weights[k] <= 0:
            continue
        i, j = pair.i, pair.j
        xi, yi = corrected[i]
        xj, yj = corrected[j]
        reg = register_physical_images(
            prepared[i],
            xi,
            yi,
            prepared[j],
            xj,
            yj,
            pixel_size_nm=pixel_size,
            max_pixels=config.coarse_grid_max_pixels,
            upsample_factor=max(5, config.phase_upsample_factor // 2),
            max_shift_nm=None,
        )
        if reg is None or not np.isfinite(reg.mse):
            value = 5.0
        else:
            residual_shift = float(np.linalg.norm(reg.shift_nm))
            shift_penalty = max(
                0.0,
                (residual_shift - config.max_residual_shift_nm)
                / max(config.max_residual_shift_nm, 1e-9),
            )
            # Images are robust-normalized before this stage, so sqrt(MSE) is naturally
            # dimensionless and comparable between scan pairs.
            value = np.sqrt(max(reg.mse, 0.0)) + 0.5 * shift_penalty
        priority_weight = max(pair.priority, 0.25)
        residuals.append(float(value * np.sqrt(priority_weight * weights[k])))
    if external_hint_nm_s is not None and config.atom_tracking_prior_weight > 0:
        hint = np.asarray(external_hint_nm_s, dtype=float).reshape(2)
        sigma = max(float(config.atom_tracking_prior_sigma_nm_s), 1e-9)
        prior = (np.asarray(velocity, dtype=float).reshape(2) - hint) / sigma
        prior *= np.sqrt(float(config.atom_tracking_prior_weight))
        residuals.extend(float(value) for value in prior)
    if not residuals:
        return np.asarray([5.0, 5.0], dtype=float)
    return np.asarray(residuals, dtype=float)


def _fit_velocity(
    frames: list[ScanFrame],
    prepared: list[np.ndarray],
    pairs: list[_Pair],
    config: AnalysisConfig,
    reference_time_s: float,
    x0: np.ndarray,
    *,
    pair_weights: np.ndarray | None = None,
    max_nfev: int = 40,
    coarse_search: bool = True,
    seed_candidates: list[np.ndarray] | None = None,
    external_hint_nm_s: np.ndarray | None = None,
) -> tuple[np.ndarray, float]:
    bound = float(config.max_abs_drift_nm_s)
    start = np.clip(np.asarray(x0, dtype=float), -0.95 * bound, 0.95 * bound)

    # Phase-correlation mismatch is not perfectly smooth because the best residual shift
    # can jump between correlation peaks. A small hierarchical 2-D search gives the local
    # least-squares refinement a physically meaningful basin instead of relying on a
    # derivative at an arbitrary zero-drift start. Only the most informative pairs are
    # used for this coarse stage to keep runtime bounded on large datasets.
    if coarse_search and pair_weights is None:
        coarse_pairs = pairs[: max(1, min(len(pairs), config.drift_coarse_pair_count))]
        centre = start.copy()
        if seed_candidates:
            best_seed_cost = np.inf
            for seed in seed_candidates:
                candidate = np.clip(np.asarray(seed, dtype=float), -bound, bound)
                residual = _candidate_residuals(
                    candidate, frames, prepared, coarse_pairs, config, reference_time_s,
                    external_hint_nm_s=external_hint_nm_s,
                )
                cost = float(np.dot(residual, residual))
                if cost < best_seed_cost:
                    best_seed_cost = cost
                    centre = candidate
        span = bound
        points = max(3, int(config.drift_coarse_grid_points))
        if points % 2 == 0:
            points += 1
        for _ in range(max(1, int(config.drift_coarse_levels))):
            offsets = np.linspace(-span, span, points)
            best_cost = np.inf
            best = centre
            for dx in offsets:
                for dy in offsets:
                    candidate = np.clip(centre + np.asarray([dx, dy]), -bound, bound)
                    residual = _candidate_residuals(
                        candidate, frames, prepared, coarse_pairs, config, reference_time_s,
                        external_hint_nm_s=external_hint_nm_s,
                    )
                    cost = float(np.dot(residual, residual))
                    if cost < best_cost:
                        best_cost = cost
                        best = candidate
            centre = best
            span = max(2.0 * span / (points - 1), bound * 1e-4)
        start = np.clip(centre, -0.99 * bound, 0.99 * bound)

    result = least_squares(
        lambda v: _candidate_residuals(
            v, frames, prepared, pairs, config, reference_time_s, pair_weights, external_hint_nm_s
        ),
        start,
        bounds=(-bound, bound),
        loss="soft_l1",
        f_scale=0.5,
        max_nfev=max_nfev,
        diff_step=0.01,
        xtol=1e-7,
        ftol=1e-7,
        gtol=1e-7,
    )
    if not result.success and result.status <= 0:
        raise DriftFitError(f"Linear drift optimizer failed: {result.message}")
    return np.asarray(result.x, dtype=float), float(2.0 * result.cost)


def _scan_level_bootstrap(
    frames: list[ScanFrame],
    prepared: list[np.ndarray],
    pairs: list[_Pair],
    config: AnalysisConfig,
    reference_time_s: float,
    best_velocity: np.ndarray,
    external_hint_nm_s: np.ndarray | None = None,
) -> np.ndarray:
    repeats = int(config.drift_bootstrap_repeats)
    if repeats <= 0 or len(frames) < 2 or not pairs:
        return np.empty((0, 2), dtype=float)
    rng = np.random.default_rng(config.bootstrap_seed)
    samples: list[np.ndarray] = []
    for _ in range(repeats):
        chosen = rng.integers(0, len(frames), size=len(frames))
        counts = np.bincount(chosen, minlength=len(frames))
        weights = np.asarray(
            [counts[pair.i] * counts[pair.j] for pair in pairs], dtype=float
        )
        if not np.any(weights > 0):
            continue
        try:
            velocity, _ = _fit_velocity(
                frames,
                prepared,
                pairs,
                config,
                reference_time_s,
                best_velocity,
                pair_weights=weights,
                max_nfev=14,
                coarse_search=False,
                external_hint_nm_s=external_hint_nm_s,
            )
        except DriftFitError:
            continue
        samples.append(velocity)
    return np.asarray(samples, dtype=float).reshape(-1, 2)


def _residual_frame_translations(
    frames: list[ScanFrame],
    prepared: list[np.ndarray],
    velocity: np.ndarray,
    reference_time_s: float,
    config: AnalysisConfig,
) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    corrected = [
        corrected_coordinates(
            frame.x_nom_nm,
            frame.y_nom_nm,
            frame.t_s,
            velocity,
            reference_time_s,
        )
        for frame in frames
    ]
    pixel_size = _native_registration_pixel_size(frames)
    # A chronological reference is deterministic and avoids hiding a user choice inside
    # the numerical pipeline. The GUI can later choose a different visual reference.
    ref_index = int(np.argmin([frame.metadata.midpoint_time_s for frame in frames]))
    ref_x, ref_y = corrected[ref_index]
    residuals: dict[str, np.ndarray] = {}
    scores: dict[str, float] = {}
    for index, frame in enumerate(frames):
        scan_id = str(frame.scan_id)
        if index == ref_index:
            residuals[scan_id] = np.zeros(2, dtype=float)
            scores[scan_id] = 1.0
            continue
        x, y = corrected[index]
        reg = register_physical_images(
            prepared[ref_index],
            ref_x,
            ref_y,
            prepared[index],
            x,
            y,
            pixel_size_nm=pixel_size,
            max_pixels=max(config.coarse_grid_max_pixels, 192),
            upsample_factor=config.phase_upsample_factor,
        )
        if reg is None:
            residuals[scan_id] = np.zeros(2, dtype=float)
            scores[scan_id] = 0.0
            continue
        if np.linalg.norm(reg.shift_nm) > config.max_residual_shift_nm:
            # Do not let a large translation silently hide a stale centre, wrong channel or
            # periodic-registration failure. Keep the frame visible but unshifted/flagged.
            residuals[scan_id] = np.zeros(2, dtype=float)
            scores[scan_id] = 0.0
        else:
            residuals[scan_id] = reg.shift_nm
            scores[scan_id] = reg.score
    return residuals, scores


def _pair_velocity_seed_candidates(
    pair_results: list[PairRegistration],
    bound: float,
) -> list[np.ndarray]:
    """Build deterministic coarse-search seeds from plausible pairwise translations.

    Periodic contrast can corrupt a complete 2-D pair shift while one velocity component
    remains useful. Combining observed x/y components gives the global optimizer nearby
    seeds without treating the lattice itself as a drift reference.
    """
    velocities = np.asarray(
        [
            pair.shift_nm / pair.dt_s
            for pair in pair_results
            if pair.valid and abs(pair.dt_s) > 1e-9
        ],
        dtype=float,
    )
    seeds: list[np.ndarray] = [np.zeros(2, dtype=float)]
    if velocities.size == 0:
        return seeds
    seeds.append(np.median(velocities, axis=0))
    seeds.extend(velocities)
    vx_values = np.unique(np.round(velocities[:, 0], decimals=12))
    vy_values = np.unique(np.round(velocities[:, 1], decimals=12))
    # Cap combinatorics while retaining representative components from strongest pairs.
    vx_values = vx_values[:12]
    vy_values = vy_values[:12]
    for vx in vx_values:
        for vy in vy_values:
            candidate = np.asarray([vx, vy], dtype=float)
            if np.all(np.abs(candidate) <= bound):
                seeds.append(candidate)
    unique: list[np.ndarray] = []
    for seed in seeds:
        if not any(np.allclose(seed, existing, atol=1e-12, rtol=0) for existing in unique):
            unique.append(seed)
    return unique


def fit_linear_drift(
    frames: list[ScanFrame],
    config: AnalysisConfig,
    *,
    logger: logging.Logger | None = None,
    external_hint_nm_s: np.ndarray | None = None,
) -> DriftFitResult:
    """Fit the two-parameter constant lateral correction velocity from image consistency."""
    if len(frames) < 2:
        raise DriftFitError("At least two scans are required to estimate drift")
    prepared = [preprocess_registration_copy(frame.data, window=False) for frame in frames]
    pairs = select_informative_pairs(frames, config.max_pair_count)
    if not pairs:
        raise DriftFitError("No compatible scan pairs were available for drift fitting")
    pair_results = initial_pair_registrations(frames, prepared, pairs, config)
    initial = _initial_velocity(pair_results)
    reference_time_s = float(np.median([frame.metadata.midpoint_time_s for frame in frames]))
    if external_hint_nm_s is not None:
        hint = np.asarray(external_hint_nm_s, dtype=float).reshape(2)
        if np.all(np.isfinite(hint)):
            initial = np.clip(hint, -config.max_abs_drift_nm_s, config.max_abs_drift_nm_s)
            if logger:
                logger.info(
                    "Using atom-tracking drift hint as fit seed/prior: vx=%g vy=%g nm/s",
                    *hint,
                )
    if logger:
        logger.info("Initial correction velocity estimate: vx=%g vy=%g nm/s", *initial)
    seeds = _pair_velocity_seed_candidates(pair_results, config.max_abs_drift_nm_s)
    if external_hint_nm_s is not None:
        seeds.insert(0, np.asarray(external_hint_nm_s, dtype=float).reshape(2))
    best, objective = _fit_velocity(
        frames,
        prepared,
        pairs,
        config,
        reference_time_s,
        initial,
        seed_candidates=seeds,
        external_hint_nm_s=external_hint_nm_s,
    )
    if logger:
        logger.info("Global drift fit: vx=%g vy=%g nm/s objective=%g", *best, objective)

    bootstrap = _scan_level_bootstrap(
        frames, prepared, pairs, config, reference_time_s, best, external_hint_nm_s
    )
    if len(bootstrap) >= 2:
        sigma = np.std(bootstrap, axis=0, ddof=1)
        interval68 = np.percentile(bootstrap, [16, 84], axis=0).T
        interval95 = np.percentile(bootstrap, [2.5, 97.5], axis=0).T
    else:
        valid_velocities = np.asarray(
            [p.shift_nm / p.dt_s for p in pair_results if p.valid and abs(p.dt_s) > 1e-9],
            dtype=float,
        )
        if len(valid_velocities) >= 2:
            median = np.median(valid_velocities, axis=0)
            sigma = 1.4826 * np.median(np.abs(valid_velocities - median), axis=0)
        else:
            sigma = np.full(2, np.nan)
        interval68 = np.column_stack((best - sigma, best + sigma))
        interval95 = np.column_stack((best - 1.96 * sigma, best + 1.96 * sigma))

    residuals, scores = _residual_frame_translations(
        frames, prepared, best, reference_time_s, config
    )
    return DriftFitResult(
        correction_velocity_nm_s=best,
        sample_velocity_nm_s=-best,
        sigma_nm_s=np.asarray(sigma, dtype=float),
        interval68_nm_s=np.asarray(interval68, dtype=float),
        interval95_nm_s=np.asarray(interval95, dtype=float),
        reference_time_s=reference_time_s,
        residual_translations_nm=residuals,
        registration_scores=scores,
        pair_registrations=pair_results,
        objective_value=objective,
        bootstrap_samples_nm_s=bootstrap,
    )
