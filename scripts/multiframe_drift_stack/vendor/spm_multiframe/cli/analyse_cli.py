from __future__ import annotations

import argparse
from pathlib import Path
import sys

from rich.console import Console
from rich.table import Table

from spm_multiframe.analysis.pipeline import run_analysis
from spm_multiframe.config import load_analysis_config
from spm_multiframe.exceptions import SPMError
from spm_multiframe.io.atom_tracking import (
    AtomTrackingHint,
    find_first_atom_tracking_hint,
    load_atom_tracking_hint,
    manual_atom_tracking_hint,
)
from spm_multiframe.io.scan_reader import (
    InputFormat,
    available_scan_formats,
    discover_scan_files,
    read_scan,
)
from spm_multiframe.utils.logging import configure_logging

console = Console()


def _pick_default(channels: list[str]) -> str:
    for preferred in ("Z", "Topography", "Height"):
        for channel in channels:
            if channel.lower() == preferred.lower():
                return channel
    return channels[0]


def _resolve_channel(value: str, channels: list[str]) -> str:
    for channel in channels:
        if channel.lower() == value.lower():
            return channel
    raise SPMError(f"Unknown channel {value!r}. Available: {', '.join(channels)}")


def choose_input_format(
    folder: Path,
    requested: InputFormat = "auto",
    *,
    interactive: bool = False,
) -> InputFormat:
    if requested != "auto":
        return requested
    formats = available_scan_formats(folder, recursive=True)
    has_sxm = bool(formats["sxm"])
    has_gwy = bool(formats["gwy"])
    if has_sxm and has_gwy:
        if interactive:
            entered = input("Both .sxm and .gwy files found. Input format [sxm/gwy] [sxm]: ").strip().lower()
            if entered in {"gwy", ".gwy"}:
                return "gwy"
        return "sxm"
    if has_sxm:
        return "sxm"
    if has_gwy:
        return "gwy"
    return requested


def discover_common_channels(
    folder: Path,
    *,
    input_format: InputFormat = "auto",
) -> tuple[list[Path], list[str]]:
    paths = discover_scan_files(folder, recursive=True, input_format=input_format)
    if not paths:
        raise SPMError(f"No supported .sxm/.gwy files found in {folder}")
    sets = []
    readable_paths = []
    for path in paths:
        try:
            scan = read_scan(path, load_data=False)
        except (SPMError, OSError, ValueError) as exc:
            console.print(f"[yellow]WARNING[/yellow] skipping {path.name}: {exc}")
            continue
        sets.append(set(scan.channels))
        readable_paths.append(path)
    if not readable_paths:
        raise SPMError("No readable SPM files were found")
    paths = readable_paths
    common = sorted(set.intersection(*sets)) if sets else []
    if not common:
        raise SPMError("The selected SPM files have no common data channel")
    return paths, common


def _progress(stage: int, total: int, message: str) -> None:
    console.print(f"[bold cyan][{stage}/{total}][/bold cyan] {message}")


def resolve_atom_tracking_hint(
    dataset: Path,
    *,
    interactive: bool,
    explicit_path: Path | None = None,
    manual_vx: float | None = None,
    manual_vy: float | None = None,
    manual_unit: str = "nm/s",
    manual_convention: str = "correction",
    disabled: bool = False,
) -> AtomTrackingHint | None:
    """Resolve optional Nanonis atom-tracking/drift-compensation information.

    Automatic files are only accepted when their units/convention can be interpreted
    unambiguously.  Manual interactive entry is offered when no usable file exists.
    """
    if disabled:
        return None
    if explicit_path is not None:
        hint = load_atom_tracking_hint(explicit_path)
        if hint is None:
            raise SPMError(
                f"Could not extract unambiguous X/Y drift information from {explicit_path}"
            )
        console.print(
            f"[green]Atom-tracking hint:[/green] {hint.correction_velocity_nm_s[0]:.6g}, "
            f"{hint.correction_velocity_nm_s[1]:.6g} nm/s from {explicit_path.name}"
        )
        return hint
    if manual_vx is not None or manual_vy is not None:
        if manual_vx is None or manual_vy is None:
            raise SPMError("Both --atom-vx and --atom-vy are required")
        return manual_atom_tracking_hint(
            manual_vx, manual_vy, unit=manual_unit, convention=manual_convention
        )

    hint, candidates = find_first_atom_tracking_hint(dataset)
    if hint is not None:
        console.print(
            f"[green]Atom-tracking/drift file detected:[/green] {Path(hint.source).name} "
            f"→ correction Vx={hint.correction_velocity_nm_s[0]:.6g}, "
            f"Vy={hint.correction_velocity_nm_s[1]:.6g} nm/s"
        )
        return hint
    if candidates:
        console.print(
            "[yellow]Atom-tracking/drift-like files were found, but none contained "
            "unambiguous X/Y values with usable units.[/yellow]"
        )
    if not interactive:
        return None

    answer = input(
        "No usable atom-tracking drift file found. Enter Nanonis atom-tracking drift values manually? [y/N]: "
    ).strip().lower()
    if answer not in {"y", "yes"}:
        return None
    convention_answer = input(
        "Values are [1] Nanonis/piezo compensation Vx,Vy or [2] measured atom/sample motion? [1]: "
    ).strip()
    convention = "sample" if convention_answer == "2" else "correction"
    unit = input("Velocity unit [nm/s] (also m/s, pm/s, nm/min): ").strip() or "nm/s"
    vx = float(input(f"Vx [{unit}]: ").strip())
    vy = float(input(f"Vy [{unit}]: ").strip())
    hint = manual_atom_tracking_hint(vx, vy, unit=unit, convention=convention)
    console.print(
        f"Using soft drift prior Vx={hint.correction_velocity_nm_s[0]:.6g}, "
        f"Vy={hint.correction_velocity_nm_s[1]:.6g} nm/s."
    )
    return hint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spm-drift-lattice",
        description="Quantitative drift correction and lattice determination for Nanonis SXM and Gwyddion GWY scans.",
    )
    parser.add_argument("dataset", nargs="?", type=Path, help="Folder containing repeated .sxm or .gwy scans")
    parser.add_argument("--channel", "-c", help="Registration/lattice channel (default: Z when present)")
    parser.add_argument("--output", "-o", type=Path, help="Analysis output directory")
    parser.add_argument("--reference", type=Path, help="SXM/GWY scan used for the final lattice overlay")
    parser.add_argument("--config", type=Path, help="TOML configuration file")
    parser.add_argument("--format", choices=["auto", "sxm", "gwy"], default="auto", help="Input file format; auto prefers SXM when both exist")
    parser.add_argument("--trace-direction", choices=["forward", "backward", "both"])
    parser.add_argument("--drift-bootstrap", type=int, help="Number of scan-level drift bootstrap refits")
    parser.add_argument("--lattice-bootstrap", type=int, help="Number of lattice bootstrap repetitions")
    parser.add_argument("--seed", type=int, help="Deterministic bootstrap seed")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--lattice-only",
        action="store_true",
        help="Skip drift estimation and determine the lattice directly from physical image geometry",
    )
    mode.add_argument(
        "--estimate-drift",
        action="store_true",
        help="Explicitly enable drift estimation (default for non-interactive runs)",
    )
    parser.add_argument("--manual-lattice-fallback", action="store_true", help="Open an FFT window for manual two-peak selection when automatic lattice detection fails")
    parser.add_argument("--atom-tracking-file", type=Path, help="CSV/TXT/DAT/JSON atom-tracking or drift-compensation log")
    parser.add_argument("--atom-vx", type=float, help="Manual atom-tracking/drift Vx")
    parser.add_argument("--atom-vy", type=float, help="Manual atom-tracking/drift Vy")
    parser.add_argument("--atom-unit", default="nm/s", help="Unit for --atom-vx/--atom-vy (default: nm/s)")
    parser.add_argument("--atom-convention", choices=["correction", "sample"], default="correction", help="Whether manual values are Nanonis compensation speed or measured sample/atom motion")
    parser.add_argument("--no-atom-tracking-hint", action="store_true", help="Disable atom-tracking file discovery/manual drift hint")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    interactive = args.dataset is None
    try:
        dataset = args.dataset
        if dataset is None:
            dataset = Path(input("Folder containing .sxm/.gwy files: ").strip()).expanduser()
        dataset = dataset.resolve()

        if args.lattice_only:
            estimate_drift = False
        elif args.estimate_drift:
            estimate_drift = True
        elif interactive:
            answer = input("Estimate drift before lattice determination? [Y/n]: ").strip().lower()
            estimate_drift = answer not in {"n", "no"}
        else:
            estimate_drift = True

        input_format = choose_input_format(dataset, args.format, interactive=interactive)
        paths, channels = discover_common_channels(dataset, input_format=input_format)
        console.print(f"Found [bold]{len(paths)}[/bold] {input_format.upper()} files.")
        table = Table(title="Common channels")
        table.add_column("Channel")
        for channel in channels:
            table.add_row(channel)
        console.print(table)
        default = _pick_default(channels)
        if args.channel:
            channel = _resolve_channel(args.channel, channels)
        elif interactive:
            entered = input(f"Channel used for drift/lattice registration [{default}]: ").strip()
            channel = _resolve_channel(entered or default, channels)
        else:
            channel = default

        cfg = load_analysis_config(args.config)
        if args.trace_direction:
            cfg.trace_direction = args.trace_direction
        if args.drift_bootstrap is not None:
            cfg.drift_bootstrap_repeats = max(0, args.drift_bootstrap)
        if args.lattice_bootstrap is not None:
            cfg.lattice_bootstrap_repeats = max(0, args.lattice_bootstrap)
        if args.seed is not None:
            cfg.bootstrap_seed = args.seed
        if args.manual_lattice_fallback:
            cfg.manual_lattice_fallback = True

        output = args.output.resolve() if args.output else dataset / "analysis_results"
        reference = args.reference
        if interactive and reference is None:
            entered = input("Optional reference scan for final lattice overlay [automatic]: ").strip()
            reference = Path(entered).expanduser() if entered else None
            answer = input("Run analysis? [Y/n]: ").strip().lower()
            if answer in {"n", "no"}:
                return 0

        atom_hint = None
        if estimate_drift:
            atom_hint = resolve_atom_tracking_hint(
                dataset,
                interactive=interactive,
                explicit_path=(args.atom_tracking_file.expanduser().resolve() if args.atom_tracking_file else None),
                manual_vx=args.atom_vx,
                manual_vy=args.atom_vy,
                manual_unit=args.atom_unit,
                manual_convention=args.atom_convention,
                disabled=args.no_atom_tracking_hint,
            )

        logger = configure_logging(output / "run.log", verbose=args.verbose)
        title = "SPM drift + lattice analysis" if estimate_drift else "SPM lattice-only analysis"
        console.print(f"[bold]{title}[/bold]")
        result = run_analysis(
            dataset,
            registration_channel=channel,
            output_dir=output,
            reference_scan=reference,
            input_format=input_format,
            estimate_drift=estimate_drift,
            atom_tracking_hint=atom_hint,
            config=cfg,
            logger=logger,
            progress=_progress,
        )
        console.print(f"[green]Done.[/green] Manifest: {result.manifest_path}")
        console.print(f"Report: {result.report_path}")
        return 0
    except (SPMError, OSError, ValueError) as exc:
        console.print(f"[bold red]ERROR[/bold red] {exc}")
        return 2
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
