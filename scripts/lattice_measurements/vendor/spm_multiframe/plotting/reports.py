from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from spm_multiframe.config import AnnotationConfig
from spm_multiframe.models import GridDefinition, LatticeSummary
from spm_multiframe.plotting.annotations import add_lattice_overlay
from spm_multiframe.plotting.display import prepare_display_image
from spm_multiframe.plotting.scale_bar import add_scale_bar


def _smart_text_color(cmap, value=0.5):
    rgba = cmap(value) if callable(cmap) else (0.5, 0.5, 0.5, 1.0)
    lum = 0.2126*rgba[0] + 0.7152*rgba[1] + 0.0722*rgba[2]
    return "black" if lum > 0.58 else "white"


def _apply_gwyddion_like_colorbar(fig, ax, im, title, unit, location="right"):
    if location == "below":
        cb = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.045, fraction=0.055)
        cb.set_ticks([im.norm.vmin, im.norm.vmax])
        cb.set_ticklabels([f"{im.norm.vmin:.3g}", f"{im.norm.vmax:.3g}"])
        cb.outline.set_visible(False)
        cb.ax.tick_params(length=0)
        cb.ax.text(0.5, 0.5, f"{title} [{unit}]" if unit else title, ha="center", va="center", transform=cb.ax.transAxes, color=_smart_text_color(im.cmap, 0.5))
    else:
        cb = fig.colorbar(im, ax=ax, pad=0.03, fraction=0.055)
        cb.set_ticks([im.norm.vmax, im.norm.vmin])
        cb.set_ticklabels([f"{im.norm.vmax:.3g}", f"{im.norm.vmin:.3g}"])
        cb.outline.set_visible(False)
        cb.ax.tick_params(length=0)
        cb.ax.text(0.5, 0.5, f"{title} [{unit}]" if unit else title, ha="center", va="center", rotation=90, transform=cb.ax.transAxes, color=_smart_text_color(im.cmap, 0.5))


def save_image_figure(
    image: np.ndarray,
    grid: GridDefinition,
    path: Path,
    *,
    title: str,
    basis_nm: np.ndarray | None = None,
    gamma_deg: float | None = None,
    annotation: AnnotationConfig | None = None,
    show_scale_bar: bool = True,
    colorbar_label: str | None = None,
    channel_name: str | None = None,
    robust_display: bool = True,
) -> None:
    fig, ax = plt.subplots(figsize=(6, 5.2))
    extent = [grid.x_nm[0], grid.x_nm[-1], grid.y_nm[0], grid.y_nm[-1]]
    display_channel = channel_name or colorbar_label
    if robust_display:
        display_image, cmap, vmin, vmax, levelled = prepare_display_image(image, display_channel)
    else:
        display_image, cmap, vmin, vmax, levelled = np.asarray(image, dtype=float), None, None, None, False
    im = ax.imshow(
        display_image,
        origin="lower",
        extent=extent,
        aspect="equal",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_title("")
    for spine in ax.spines.values():
        spine.set_visible(False)
    if basis_nm is not None and gamma_deg is not None:
        add_lattice_overlay(
            ax,
            basis_nm,
            gamma_deg,
            image=display_image,
            grid=grid,
            config=annotation,
        )
    if show_scale_bar:
        add_scale_bar(
            ax,
            length_nm=(annotation.scale_bar_length_nm if annotation else None),
            color="black",
        )
    if colorbar_label:
        label = colorbar_label
        unit = "nm" if label == "ΔZ" else ""
        _apply_gwyddion_like_colorbar(fig, ax, im, title=label, unit=unit)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def save_lattice_summary_table(summary: LatticeSummary, path: Path) -> None:
    rows = [
        ["a", f"{summary.a_nm:.6g}", f"{summary.sigma_a_nm:.3g}", "nm"],
        ["b", f"{summary.b_nm:.6g}", f"{summary.sigma_b_nm:.3g}", "nm"],
        ["γ", f"{summary.gamma_deg:.6g}", f"{summary.sigma_gamma_deg:.3g}", "deg"],
    ]
    fig, ax = plt.subplots(figsize=(5.8, 2.4))
    ax.axis("off")
    table = ax.table(
        cellText=rows,
        colLabels=["Parameter", "Estimate", "1σ", "Unit"],
        loc="center",
        cellLoc="center",
    )
    table.scale(1.0, 1.5)
    ax.set_title("Final lattice summary")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def write_analysis_report(path: Path, manifest: dict[str, Any], per_scan_rows: list[dict[str, Any]]) -> None:
    drift = manifest["drift"]
    lattice = manifest["lattice"]
    velocity = drift["correction_velocity_nm_s"]
    sample_velocity = drift["sample_velocity_nm_s"]
    lattice_only = manifest.get("analysis_mode") == "lattice_only" or drift.get("model") == "none"

    lines = [
        "# SPM lattice analysis report" if lattice_only else "# SPM drift + lattice analysis report",
        "",
        f"- Dataset ID: `{manifest['dataset_id']}`",
        f"- Software: SPM MultiFrame {manifest['software_version']}",
        f"- Analysis mode: `{'lattice_only' if lattice_only else 'drift_and_lattice'}`",
        f"- Registration/lattice channel: `{manifest['registration_channel']}`",
        f"- Trace direction mode: `{manifest['trace_direction']}`",
        f"- Number of analyzed frames: {len(manifest['scans'])}",
        "",
    ]

    if lattice_only:
        lines += [
            "## Drift handling",
            "",
            "Drift estimation was disabled by the user. No time-dependent lateral correction or residual frame registration was applied before lattice determination.",
            "",
        ]
    else:
        lines += [
            "## Linear lateral drift",
            "",
            f"- Correction velocity: vx = {velocity[0]:.6g} nm/s, vy = {velocity[1]:.6g} nm/s",
            f"- Inferred sample velocity: vx = {sample_velocity[0]:.6g} nm/s, vy = {sample_velocity[1]:.6g} nm/s",
            f"- Reference time: {manifest['reference_time_s']:.6f} s",
            f"- Total dataset correction vector: {drift['total_correction_nm']}",
            "",
            "The sign convention is `r_corr = r_nom + v_c (t - t_ref) + δ_i`; the reported sample velocity is `-v_c`.",
            "",
        ]
        atom = manifest.get("atom_tracking")
        if atom:
            hint = atom.get("correction_velocity_nm_s", [float("nan"), float("nan")])
            lines += [
                "### Atom Tracking / external drift hint",
                "",
                f"- Source: `{atom.get('source', 'unknown')}`",
                f"- Correction-velocity hint: vx = {float(hint[0]):.6g} nm/s, vy = {float(hint[1]):.6g} nm/s",
                f"- Role: `{atom.get('role', 'soft_prior')}`",
                "",
                "This external value is used as a soft prior/initial seed; it does not replace the image-based drift fit.",
                "",
            ]

    lines += [
        "## Final direct lattice",
        "",
        f"- a = {lattice['a_nm']:.6g} ± {lattice['sigma_a_nm']:.3g} nm (1σ)",
        f"- b = {lattice['b_nm']:.6g} ± {lattice['sigma_b_nm']:.3g} nm (1σ)",
        f"- γ = {lattice['gamma_deg']:.6g} ± {lattice['sigma_gamma_deg']:.3g}° (1σ)",
        "",
        "The reciprocal FFT vectors are expressed in cycles/nm, so the code uses `B = G^{-T}` with no `2π` factor.",
        "Before averaging scans, every direct basis is 2-D Gauss-reduced to remove equivalent sheared representations such as `(a, a+b)`. The reporting convention is a = longer reduced vector, b = shorter reduced vector, with the acute equivalent angle.",
        "",
        "## Per-frame quality",
        "",
        "| frame | registration score | residual shift (nm) | lattice a (nm) | lattice b (nm) | γ (deg) | flags |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in per_scan_rows:
        lines.append(
            "| {scan_id} | {registration_score:.3f} | {residual_shift_magnitude_nm:.4g} | "
            "{lattice_a_nm} | {lattice_b_nm} | {lattice_gamma_deg} | {flags} |".format(**row)
        )
    lines += [
        "",
        "## Reproducibility",
        "",
        "Source hashes, physical geometry, calibration overrides, analysis parameters and bootstrap intervals are stored in `drift_lattice_results.json`.",
        "",
        "## Scientific references",
        "",
        "- Rahe, Bechstein & Kühnle, JVST B 28, C4E31–C4E38 (2010). https://doi.org/10.1116/1.3360909",
        "- Ophus, Ciston & Nelson, Ultramicroscopy 162, 1–9 (2016). https://doi.org/10.1016/j.ultramic.2015.12.002",
        "- Guizar-Sicairos, Thurman & Fienup, Optics Letters 33, 156–158 (2008). https://doi.org/10.1364/OL.33.000156",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_stack_report(path: Path, manifest: dict[str, Any]) -> None:
    crop = manifest["common_region_nm"]
    lines = [
        "# SPM multi-frame stack report",
        "",
        f"- Analysis dataset ID: `{manifest['analysis_dataset_id']}`",
        f"- Included scans: {len(manifest['included_scans'])}",
        f"- Excluded scans: {len(manifest['excluded_scans'])}",
        f"- Registration channel: `{manifest['registration_channel']}`",
        f"- Stacked channels: {', '.join(manifest['stack_channels'])}",
        f"- Combination method: `{manifest['stacking']['method']}`",
        f"- Output pixel size: {manifest['output_pixel_size_nm']:.6g} nm",
        "",
        "## Common physical region",
        "",
        f"- xmin = {crop['xmin_nm']:.6g} nm",
        f"- xmax = {crop['xmax_nm']:.6g} nm",
        f"- ymin = {crop['ymin_nm']:.6g} nm",
        f"- ymax = {crop['ymax_nm']:.6g} nm",
        "",
        "## Quantitative handling",
        "",
        f"Physical-area geometry: `{manifest.get('physical_area_geometry', 'metadata_plus_linear_drift')}`.",
        f"Stack-alignment geometry: `{manifest.get('stack_alignment_geometry', 'physical_area_plus_small_rigid_registration')}`.",
        "The common crop is selected from absolute metadata+drift scan footprints before fine image-registration translations are applied. Therefore registration cannot manufacture a physical overlap that was not actually acquired. The exact same x/y crop is then used for every included frame.",
        "",
        "All output channels from a frame use the same spatial transform determined from the registration channel. No affine or non-rigid deformation is applied during stacking. Numerical NPY files are the primary data products; floating-point TIFF and PNG/PDF files are exports.",
        "",
        "For each channel the output includes a stacked value map, uncertainty/spread map and contribution-count map.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
