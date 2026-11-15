from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
import logging

import numpy as np
from skimage.feature import peak_local_max

from spm_multiframe.analysis.fft import FFTResult, compute_fft, detect_fft_peaks
from spm_multiframe.analysis.uncertainty import huber_location
from spm_multiframe.config import AnalysisConfig
from spm_multiframe.exceptions import LatticeDetectionError
from spm_multiframe.geometry.overlap import largest_rectangle
from spm_multiframe.geometry.transforms import bounds_from_coordinates, corrected_coordinates
from spm_multiframe.models import (
    DriftFitResult,
    FFTPeak,
    GridDefinition,
    LatticeScanResult,
    LatticeSummary,
    ScanFrame,
)
from spm_multiframe.stacking.resample import resample_to_grid


@dataclass(frozen=True)
class LatticeCandidate:
    reciprocal_basis_cpnm: np.ndarray
    direct_basis_nm: np.ndarray
    score: float
    explained_fraction: float
    mean_residual_cpnm: float
    selection_method: str = "automatic"


def reciprocal_to_direct(g_basis_cpnm: np.ndarray) -> np.ndarray:
    """Convert ordinary reciprocal frequencies (cycles/nm) using ``B = G^{-T}``."""
    g = np.asarray(g_basis_cpnm, dtype=float).reshape(2, 2)
    if abs(np.linalg.det(g)) < 1e-12:
        raise LatticeDetectionError("Reciprocal lattice basis is singular")
    # FFT coordinates are ordinary spatial frequencies (cycles/nm), therefore no 2π.
    return np.linalg.inv(g).T


def lattice_parameters(basis_nm: np.ndarray) -> tuple[float, float, float]:
    b = np.asarray(basis_nm, dtype=float).reshape(2, 2)
    a_vec, b_vec = b[:, 0], b[:, 1]
    a = float(np.linalg.norm(a_vec))
    b_len = float(np.linalg.norm(b_vec))
    cosine = float(np.dot(a_vec, b_vec) / max(a * b_len, np.finfo(float).eps))
    gamma = float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))
    return a, b_len, gamma


def _canonical_vector_sign(vector: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Return a deterministic sign for a 2-D lattice vector.

    A lattice basis is unchanged when an individual vector is multiplied by -1.
    Fixing that ambiguity makes independent analyses of different image channels much
    more likely to report the same vector orientation.
    """
    vec = np.asarray(vector, dtype=float).copy()
    if vec[0] < -eps or (abs(vec[0]) <= eps and vec[1] < 0.0):
        vec *= -1.0
    return vec


def reduce_direct_basis(basis_nm: np.ndarray) -> np.ndarray:
    """Gauss-reduce a 2-D direct lattice to a short, deterministic primitive basis.

    FFT peak pairs do not define a unique primitive basis.  For example, ``(a, a+b)``
    describes exactly the same lattice as ``(a, b)`` but makes the second vector look
    much too long and changes the displayed angle.  This function removes those
    unimodular/sheared representations before any cross-scan consensus is computed.

    The returned convention is deterministic for a generic oblique cell: the longer
    reduced vector is labelled ``a``, the shorter one ``b``, and the included angle is
    chosen acute (or 90 degrees).  This convention only fixes representation; it does
    not change the lattice itself.
    """
    basis = np.asarray(basis_nm, dtype=float).reshape(2, 2)
    if not np.all(np.isfinite(basis)) or abs(float(np.linalg.det(basis))) < 1e-12:
        raise LatticeDetectionError("Direct lattice basis is singular or non-finite")

    u = basis[:, 0].copy()
    v = basis[:, 1].copy()

    # Two-dimensional Gauss reduction.  Each operation is unimodular, so it preserves
    # the lattice exactly while removing unnecessarily long combinations such as a+b.
    for _ in range(32):
        if np.dot(v, v) < np.dot(u, u):
            u, v = v, u
        denom = float(np.dot(u, u))
        if denom <= 1e-24:
            raise LatticeDetectionError("Degenerate direct lattice basis")
        mu = int(np.rint(float(np.dot(u, v) / denom)))
        if mu == 0:
            break
        v = v - mu * u
    else:
        raise LatticeDetectionError("Direct lattice basis reduction did not converge")

    if np.dot(v, v) < np.dot(u, u):
        u, v = v, u

    # Gauss reduction leaves u as the shorter vector.  Use a stable public convention
    # with a = longer and b = shorter; this matches the user's existing TClTAP naming
    # and prevents channel-dependent a/b swaps.
    a_vec = _canonical_vector_sign(v)
    b_vec = u.copy()
    # Choose the equivalent sign of b that gives the acute included angle.
    if float(np.dot(a_vec, b_vec)) < 0.0:
        b_vec *= -1.0
    # For an exactly orthogonal cell the dot product cannot fix b's sign.
    if abs(float(np.dot(a_vec, b_vec))) <= 1e-12 * max(
        float(np.linalg.norm(a_vec) * np.linalg.norm(b_vec)), 1.0
    ):
        b_vec = _canonical_vector_sign(b_vec)

    reduced = np.column_stack((a_vec, b_vec))
    if abs(float(np.linalg.det(reduced))) < 1e-12:
        raise LatticeDetectionError("Reduced direct lattice basis is singular")
    return reduced


def _reciprocal_from_direct(basis_nm: np.ndarray) -> np.ndarray:
    """Return ordinary reciprocal frequencies (cycles/nm) for a direct basis."""
    basis = np.asarray(basis_nm, dtype=float).reshape(2, 2)
    return np.linalg.inv(basis).T


def _partnered_representatives(
    peaks: list[FFTPeak], tolerance_cpnm: float
) -> list[FFTPeak]:
    representatives: list[FFTPeak] = []
    vectors = np.asarray([peak.vector for peak in peaks], dtype=float)
    if len(vectors) == 0:
        return []
    for i, peak in enumerate(peaks):
        distances = np.linalg.norm(vectors + peak.vector, axis=1)
        distances[i] = np.inf
        if float(np.min(distances)) > tolerance_cpnm:
            continue
        gx, gy = peak.gx_cpnm, peak.gy_cpnm
        if gx > tolerance_cpnm * 0.1 or (abs(gx) <= tolerance_cpnm * 0.1 and gy > 0):
            representatives.append(peak)
    return representatives


def _candidate_score(
    g_basis: np.ndarray,
    peaks: list[FFTPeak],
    tolerance_cpnm: float,
) -> tuple[float, float, float]:
    vectors = np.asarray([peak.vector for peak in peaks], dtype=float)
    amplitudes = np.asarray([peak.amplitude for peak in peaks], dtype=float)
    try:
        coeff = np.linalg.solve(g_basis, vectors.T).T
    except np.linalg.LinAlgError:
        return -np.inf, 0.0, np.inf
    integer = np.rint(coeff)
    predicted = (g_basis @ integer.T).T
    residual = np.linalg.norm(vectors - predicted, axis=1)
    nonzero = np.linalg.norm(integer, axis=1) > 0
    explained = (residual <= tolerance_cpnm) & nonzero
    if not np.any(explained):
        return -np.inf, 0.0, np.inf
    amp_weights = amplitudes / max(float(np.max(amplitudes)), np.finfo(float).eps)
    explained_weight = float(np.sum(amp_weights[explained]))
    total_weight = float(np.sum(amp_weights))
    explained_fraction = explained_weight / max(total_weight, 1e-12)
    mean_residual = float(
        np.average(residual[explained], weights=amp_weights[explained])
    )
    order = np.sum(np.abs(integer[explained]), axis=1)
    high_order_penalty = float(
        np.average(np.maximum(order - 1.0, 0.0), weights=amp_weights[explained])
    )
    # Favor candidates that explain many *strong* peaks with low residual and low Miller
    # order.  A too-large direct supercell often explains the true first-order FFT peaks
    # only as second/third-order reflections, so the order penalty must be meaningful.
    score = (
        8.0 * explained_fraction
        - 2.0 * mean_residual / max(tolerance_cpnm, 1e-12)
        - 0.75 * high_order_penalty
    )
    return float(score), explained_fraction, mean_residual


def lattice_candidates_from_fft(
    fft: FFTResult,
    peaks: list[FFTPeak],
    config: AnalysisConfig,
    *,
    max_candidates: int = 8,
) -> list[LatticeCandidate]:
    if len(fft.fx_cpnm) < 2 or len(fft.fy_cpnm) < 2:
        return []
    bin_scale = float(
        np.hypot(np.median(np.diff(fft.fx_cpnm)), np.median(np.diff(fft.fy_cpnm)))
    )
    partner_tol = config.fft_partner_tolerance_bins * bin_scale
    reps = _partnered_representatives(peaks, partner_tol)
    reps = reps[: min(len(reps), 16)]
    candidates: list[LatticeCandidate] = []
    for first, second in combinations(reps, 2):
        g = np.column_stack((first.vector, second.vector))
        det = abs(float(np.linalg.det(g)))
        if det < max(bin_scale**2 * 0.5, 1e-8):
            continue
        try:
            # A pair of valid reciprocal peaks can describe a sheared but equivalent
            # direct basis such as (a, a+b).  Reduce it before scoring so that all such
            # representations collapse onto the same short primitive cell.
            direct = reduce_direct_basis(reciprocal_to_direct(g))
            g = _reciprocal_from_direct(direct)
        except (LatticeDetectionError, np.linalg.LinAlgError):
            continue
        a, b, gamma = lattice_parameters(direct)
        if not (
            config.lattice_min_nm <= a <= config.lattice_max_nm
            and config.lattice_min_nm <= b <= config.lattice_max_nm
            and 10.0 <= gamma <= 170.0
        ):
            continue
        score, explained_fraction, residual = _candidate_score(g, peaks, partner_tol)
        if np.isfinite(score):
            candidates.append(
                LatticeCandidate(g, direct, score, explained_fraction, residual)
            )
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates[:max_candidates]


def _signed_permutation_transforms() -> list[np.ndarray]:
    """Transforms that only swap/sign-flip an already reduced basis.

    General unimodular shears are intentionally excluded here.  Allowing them during
    cross-scan canonicalization can turn a correct reduced basis back into (a, a+b),
    recreating an apparently over-long lattice vector.
    """
    transforms: list[np.ndarray] = []
    for swap in (False, True):
        base = np.asarray([[0.0, 1.0], [1.0, 0.0]]) if swap else np.eye(2)
        for s1 in (-1.0, 1.0):
            for s2 in (-1.0, 1.0):
                transforms.append(base @ np.diag([s1, s2]))
    return transforms


_SIGNED_PERMUTATIONS = _signed_permutation_transforms()


def canonicalize_basis_to_reference(basis_nm: np.ndarray, reference_nm: np.ndarray) -> np.ndarray:
    basis = reduce_direct_basis(basis_nm)
    reference = reduce_direct_basis(reference_nm)
    ref_norm = max(float(np.linalg.norm(reference)), 1e-12)
    best = basis
    best_distance = np.inf
    for transform in _SIGNED_PERMUTATIONS:
        candidate = basis @ transform
        # Reapply the deterministic reduced convention after sign/swap alignment.
        try:
            candidate = reduce_direct_basis(candidate)
        except LatticeDetectionError:
            continue
        distance = float(np.linalg.norm(candidate - reference) / ref_norm)
        if distance < best_distance:
            best_distance = distance
            best = candidate
    return best


def _select_global_candidate_set(
    all_candidates: list[list[LatticeCandidate]],
) -> list[LatticeCandidate | None]:
    usable = [index for index, candidates in enumerate(all_candidates) if candidates]
    if not usable:
        return [None] * len(all_candidates)
    ref_index = max(usable, key=lambda idx: all_candidates[idx][0].score)
    reference = all_candidates[ref_index][0].direct_basis_nm
    selected: list[LatticeCandidate | None] = [None] * len(all_candidates)

    for _ in range(4):
        matrices: list[np.ndarray] = []
        weights: list[float] = []
        for index in usable:
            candidates = all_candidates[index]
            scored: list[tuple[float, LatticeCandidate, np.ndarray]] = []
            for candidate in candidates:
                canonical = canonicalize_basis_to_reference(candidate.direct_basis_nm, reference)
                distance = float(np.linalg.norm(canonical - reference) / max(np.linalg.norm(reference), 1e-12))
                consensus_score = candidate.score - 4.0 * distance
                scored.append((consensus_score, candidate, canonical))
            _score, chosen, canonical = max(scored, key=lambda item: item[0])
            selected[index] = LatticeCandidate(
                _reciprocal_from_direct(canonical),
                canonical,
                chosen.score,
                chosen.explained_fraction,
                chosen.mean_residual_cpnm,
                chosen.selection_method,
            )
            matrices.append(canonical)
            weights.append(max(chosen.score, 0.1))
        flat = np.asarray(matrices).reshape(len(matrices), 4)
        reference = np.asarray(huber_location(flat, np.asarray(weights))).reshape(2, 2)
    return selected


def _crop_resampled_to_finite_rectangle(
    image: np.ndarray, grid: GridDefinition
) -> tuple[np.ndarray, GridDefinition]:
    region = largest_rectangle(np.isfinite(image))
    if region is None:
        raise LatticeDetectionError("Corrected scan has no finite rectangular region for FFT")
    r0, r1, c0, c1 = region
    if min(r1 - r0, c1 - c0) < 24:
        raise LatticeDetectionError("Corrected finite region is too small for reliable FFT analysis")
    cropped = image[r0:r1, c0:c1]
    cropped_grid = GridDefinition(grid.x_nm[c0:c1].copy(), grid.y_nm[r0:r1].copy())
    return cropped, cropped_grid


def _corrected_uniform_image(
    frame: ScanFrame,
    drift: DriftFitResult,
) -> tuple[np.ndarray, GridDefinition, np.ndarray, np.ndarray]:
    delta = drift.residual_translations_nm.get(str(frame.scan_id), np.zeros(2))
    x_corr, y_corr = corrected_coordinates(
        frame.x_nom_nm,
        frame.y_nom_nm,
        frame.t_s,
        drift.correction_velocity_nm_s,
        drift.reference_time_s,
        delta,
    )
    xmin, xmax, ymin, ymax = bounds_from_coordinates(x_corr, y_corr)
    pixel_size = float(np.median([frame.metadata.native_dx_nm, frame.metadata.native_dy_nm]))
    nx = max(2, int(np.floor((xmax - xmin) / pixel_size)) + 1)
    ny = max(2, int(np.floor((ymax - ymin) / pixel_size)) + 1)
    grid = GridDefinition(
        x_nm=np.linspace(xmin, xmax, nx),
        y_nm=np.linspace(ymin, ymax, ny),
    )
    image = resample_to_grid(frame.data, x_corr, y_corr, grid)
    cropped, cropped_grid = _crop_resampled_to_finite_rectangle(image, grid)
    return cropped, cropped_grid, x_corr, y_corr


def _autocorrelation_crosscheck(image: np.ndarray, grid: GridDefinition) -> dict[str, float] | None:
    arr = np.asarray(image, dtype=float)
    if not np.all(np.isfinite(arr)):
        arr = np.where(np.isfinite(arr), arr - np.nanmean(arr), 0.0)
    else:
        arr = arr - np.mean(arr)
    fft = np.fft.fft2(arr)
    ac = np.fft.fftshift(np.fft.ifft2(np.abs(fft) ** 2).real)
    cy, cx = np.asarray(ac.shape) // 2
    radius = 2
    ac[max(0, cy - radius) : cy + radius + 1, max(0, cx - radius) : cx + radius + 1] = -np.inf
    peaks = peak_local_max(ac, min_distance=3, num_peaks=20, exclude_border=2)
    vectors: list[np.ndarray] = []
    for row, col in peaks:
        vec = np.asarray([(col - cx) * grid.dx_nm, (row - cy) * grid.dy_nm], dtype=float)
        if np.linalg.norm(vec) > 0:
            vectors.append(vec)
    vectors.sort(key=lambda vec: np.linalg.norm(vec))
    if len(vectors) < 2:
        return None
    first = vectors[0]
    # In 2D, non-collinearity is measured by the scalar determinant
    # x1*y2 - y1*x2.  Do not use np.cross on 2-component vectors here:
    # newer NumPy versions require 3D vectors for cross products.
    first_norm = np.linalg.norm(first)
    second = next(
        (
            vec
            for vec in vectors[1:]
            if abs(first[0] * vec[1] - first[1] * vec[0])
            > 0.1 * first_norm * np.linalg.norm(vec)
        ),
        None,
    )
    if second is None:
        return None
    gamma = np.degrees(
        np.arccos(
            np.clip(
                np.dot(first, second) / (np.linalg.norm(first) * np.linalg.norm(second)),
                -1,
                1,
            )
        )
    )
    return {
        "spacing1_nm": float(np.linalg.norm(first)),
        "spacing2_nm": float(np.linalg.norm(second)),
        "angle_deg": float(gamma),
    }


def analyze_lattice(
    frames: list[ScanFrame],
    drift: DriftFitResult,
    config: AnalysisConfig,
    *,
    logger: logging.Logger | None = None,
) -> LatticeSummary:
    """Determine one globally consistent direct lattice from corrected scan FFTs."""
    corrected_items: list[tuple[np.ndarray, GridDefinition] | None] = []
    fft_items: list[tuple[FFTResult, list[FFTPeak]] | None] = []
    candidate_sets: list[list[LatticeCandidate]] = []
    for frame in frames:
        try:
            image, grid, _x, _y = _corrected_uniform_image(frame, drift)
            fft = compute_fft(image, grid)
            peaks = detect_fft_peaks(
                fft,
                dc_radius_bins=config.fft_dc_radius_bins,
                min_peak_distance_bins=config.fft_min_peak_distance_bins,
                max_peaks=config.fft_max_peaks,
            )
            candidates = lattice_candidates_from_fft(fft, peaks, config)
            if not candidates and config.manual_lattice_fallback:
                from spm_multiframe.gui.fft_peak_selector import select_two_reciprocal_peaks

                manual_g = select_two_reciprocal_peaks(
                    fft, title=f"Manual reciprocal basis — {frame.scan_id}"
                )
                if manual_g is not None:
                    manual_b = reciprocal_to_direct(manual_g)
                    ma, mb, mgamma = lattice_parameters(manual_b)
                    if (
                        config.lattice_min_nm <= ma <= config.lattice_max_nm
                        and config.lattice_min_nm <= mb <= config.lattice_max_nm
                        and 10.0 <= mgamma <= 170.0
                    ):
                        candidates = [LatticeCandidate(manual_g, manual_b, 10.0, 1.0, 0.0, "manual")]
        except (ValueError, LatticeDetectionError, np.linalg.LinAlgError) as exc:
            if logger:
                logger.warning("Lattice preprocessing failed for %s: %s", frame.scan_id, exc)
            corrected_items.append(None)
            fft_items.append(None)
            candidate_sets.append([])
            continue
        corrected_items.append((image, grid))
        fft_items.append((fft, peaks))
        candidate_sets.append(candidates)
        if logger and not candidates:
            logger.warning("No lattice basis candidate found for %s", frame.scan_id)

    selected = _select_global_candidate_set(candidate_sets)
    per_scan: list[LatticeScanResult] = []
    for index, candidate in enumerate(selected):
        if candidate is None or corrected_items[index] is None or fft_items[index] is None:
            continue
        image, grid = corrected_items[index]
        _fft, peaks = fft_items[index]
        a, b, gamma = lattice_parameters(candidate.direct_basis_nm)
        peak_quality = np.median([peak.snr for peak in peaks[:4]]) if peaks else 1.0
        registration_quality = max(
            drift.registration_scores.get(str(frames[index].scan_id), 0.2), 0.05
        )
        quality_weight = float(max(candidate.score, 0.05) * np.sqrt(max(peak_quality, 1.0)) * registration_quality)
        per_scan.append(
            LatticeScanResult(
                scan_id=str(frames[index].scan_id),
                reciprocal_basis_cpnm=candidate.reciprocal_basis_cpnm,
                direct_basis_nm=candidate.direct_basis_nm,
                a_nm=a,
                b_nm=b,
                gamma_deg=gamma,
                score=candidate.score,
                quality_weight=quality_weight,
                fft_peaks=peaks,
                corrected_image=image,
                grid=grid,
                selection_method=candidate.selection_method,
            )
        )
        crosscheck = _autocorrelation_crosscheck(image, grid)
        if logger and crosscheck:
            logger.info("Autocorrelation cross-check %s: %s", frames[index].scan_id, crosscheck)

    if not per_scan:
        raise LatticeDetectionError(
            "Automatic lattice detection failed for all scans. Inspect FFT diagnostics or use manual peak selection."
        )

    matrices = np.asarray([result.direct_basis_nm for result in per_scan], dtype=float)
    weights = np.asarray([result.quality_weight for result in per_scan], dtype=float)
    reference = matrices[int(np.argmax(weights))]
    canonical = np.asarray(
        [canonicalize_basis_to_reference(matrix, reference) for matrix in matrices], dtype=float
    )
    final_basis = np.asarray(huber_location(canonical.reshape(len(canonical), 4), weights)).reshape(2, 2)
    final_basis = reduce_direct_basis(final_basis)
    a, b, gamma = lattice_parameters(final_basis)

    rng = np.random.default_rng(config.bootstrap_seed)
    bootstrap: list[np.ndarray] = []
    repeats = int(config.lattice_bootstrap_repeats)
    for _ in range(max(0, repeats)):
        choice = rng.integers(0, len(canonical), size=len(canonical))
        sample_matrices = canonical[choice]
        sample_weights = weights[choice]
        sample_basis = np.asarray(
            huber_location(sample_matrices.reshape(len(sample_matrices), 4), sample_weights)
        ).reshape(2, 2)
        sample_basis = reduce_direct_basis(sample_basis)
        bootstrap.append(np.asarray(lattice_parameters(sample_basis), dtype=float))
    bootstrap_array = np.asarray(bootstrap, dtype=float).reshape(-1, 3)
    if len(bootstrap_array) >= 2:
        sigma = np.std(bootstrap_array, axis=0, ddof=1)
        q68 = np.percentile(bootstrap_array, [16, 84], axis=0)
        q95 = np.percentile(bootstrap_array, [2.5, 97.5], axis=0)
    else:
        scan_values = np.asarray([[r.a_nm, r.b_nm, r.gamma_deg] for r in per_scan], dtype=float)
        sigma = np.std(scan_values, axis=0, ddof=1) if len(scan_values) >= 2 else np.full(3, np.nan)
        q68 = np.vstack((np.asarray([a, b, gamma]) - sigma, np.asarray([a, b, gamma]) + sigma))
        q95 = np.vstack((np.asarray([a, b, gamma]) - 1.96 * sigma, np.asarray([a, b, gamma]) + 1.96 * sigma))

    return LatticeSummary(
        basis_nm=final_basis,
        a_nm=a,
        b_nm=b,
        gamma_deg=gamma,
        sigma_a_nm=float(sigma[0]),
        sigma_b_nm=float(sigma[1]),
        sigma_gamma_deg=float(sigma[2]),
        interval68={
            "a_nm": (float(q68[0, 0]), float(q68[1, 0])),
            "b_nm": (float(q68[0, 1]), float(q68[1, 1])),
            "gamma_deg": (float(q68[0, 2]), float(q68[1, 2])),
        },
        interval95={
            "a_nm": (float(q95[0, 0]), float(q95[1, 0])),
            "b_nm": (float(q95[0, 1]), float(q95[1, 1])),
            "gamma_deg": (float(q95[0, 2]), float(q95[1, 2])),
        },
        bootstrap_samples=bootstrap_array,
        per_scan=per_scan,
    )
