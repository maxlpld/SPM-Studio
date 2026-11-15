from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from spm_multiframe.analysis.fft import compute_fft
from spm_multiframe.models import DriftFitResult, LatticeSummary


def _save(fig: plt.Figure, path: Path, also_pdf: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    if also_pdf:
        fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def plot_drift_fit(drift: DriftFitResult, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    pair_velocities = []
    for pair in drift.pair_registrations:
        if pair.valid and abs(pair.dt_s) > 1e-9:
            pair_velocities.append(pair.shift_nm / pair.dt_s)
    if pair_velocities:
        values = np.asarray(pair_velocities)
        ax.scatter(values[:, 0], values[:, 1], label="pair estimates", alpha=0.7)
    ax.scatter(
        [drift.correction_velocity_nm_s[0]],
        [drift.correction_velocity_nm_s[1]],
        marker="x",
        s=100,
        label="global fit",
    )
    ax.set_xlabel("Correction velocity vx (nm/s)")
    ax.set_ylabel("Correction velocity vy (nm/s)")
    ax.set_title("Linear drift correction")
    ax.legend()
    ax.grid(alpha=0.2)
    _save(fig, output)


def plot_drift_bootstrap(drift: DriftFitResult, output: Path) -> None:
    samples = drift.bootstrap_samples_nm_s
    fig, ax = plt.subplots(figsize=(6, 4))
    if len(samples):
        ax.scatter(samples[:, 0], samples[:, 1], s=16, alpha=0.5)
    ax.axvline(drift.correction_velocity_nm_s[0], ls="--")
    ax.axhline(drift.correction_velocity_nm_s[1], ls="--")
    ax.set_xlabel("vx (nm/s)")
    ax.set_ylabel("vy (nm/s)")
    ax.set_title("Scan-level drift bootstrap")
    _save(fig, output)


def plot_lattice_per_scan(summary: LatticeSummary, field: str, output: Path) -> None:
    values = np.asarray([getattr(result, field) for result in summary.per_scan], dtype=float)
    labels = [result.scan_id for result in summary.per_scan]
    if field == "a_nm":
        mean, sigma, ylabel = summary.a_nm, summary.sigma_a_nm, "a (nm)"
    elif field == "b_nm":
        mean, sigma, ylabel = summary.b_nm, summary.sigma_b_nm, "b (nm)"
    else:
        mean, sigma, ylabel = summary.gamma_deg, summary.sigma_gamma_deg, "γ (deg)"
    fig, ax = plt.subplots(figsize=(max(6, 0.45 * len(values)), 4))
    x = np.arange(len(values))
    ax.plot(x, values, "o")
    ax.axhline(mean, ls="-")
    if np.isfinite(sigma):
        ax.axhspan(mean - sigma, mean + sigma, alpha=0.15)
    ax.set_xticks(x, labels, rotation=70, ha="right", fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{ylabel} per corrected scan")
    _save(fig, output)


def plot_fft_diagnostic(result, output: Path) -> None:
    if result.corrected_image is None or result.grid is None:
        return
    fft = compute_fft(result.corrected_image, result.grid)
    fig, ax = plt.subplots(figsize=(5.5, 5))
    logmag = np.log1p(fft.magnitude)
    extent = [fft.fx_cpnm[0], fft.fx_cpnm[-1], fft.fy_cpnm[0], fft.fy_cpnm[-1]]
    ax.imshow(logmag, origin="lower", extent=extent, aspect="equal")
    g = result.reciprocal_basis_cpnm
    for k in range(2):
        ax.plot([g[0, k], -g[0, k]], [g[1, k], -g[1, k]], "o")
    ax.set_xlabel("kx (cycles/nm)")
    ax.set_ylabel("ky (cycles/nm)")
    ax.set_title(result.scan_id)
    _save(fig, output, also_pdf=False)


def plot_registration_residuals(scan_rows: list[dict], output: Path) -> None:
    labels = [row["scan_id"] for row in scan_rows]
    shifts = np.asarray([row.get("residual_shift_magnitude_nm", np.nan) for row in scan_rows])
    scores = np.asarray([row.get("registration_score", np.nan) for row in scan_rows])
    fig, ax = plt.subplots(figsize=(max(6, 0.45 * len(labels)), 4))
    x = np.arange(len(labels))
    ax.bar(x, shifts, alpha=0.7, label="residual shift (nm)")
    ax2 = ax.twinx()
    ax2.plot(x, scores, "o-", label="correlation")
    ax.set_xticks(x, labels, rotation=70, ha="right", fontsize=8)
    ax.set_ylabel("Residual shift (nm)")
    ax2.set_ylabel("Registration correlation")
    ax.set_title("Residual registration quality")
    _save(fig, output)


def plot_noise_vs_frames(noise_values: list[float], output: Path) -> None:
    if not noise_values:
        return
    values = np.asarray(noise_values, dtype=float)
    n = np.arange(1, len(values) + 1)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(n, values, "o-", label="measured robust noise")
    if np.isfinite(values[0]) and values[0] > 0:
        ax.plot(n, values[0] / np.sqrt(n), "--", label="1/√N reference")
    ax.set_xlabel("Number of stacked frames")
    ax.set_ylabel("Robust noise estimate (channel units)")
    ax.set_title("Noise versus number of frames")
    ax.legend()
    ax.grid(alpha=0.2)
    _save(fig, output)
