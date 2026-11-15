from __future__ import annotations

import argparse
from pathlib import Path
import sys

from rich.console import Console
from rich.table import Table

from spm_multiframe.analysis.pipeline import run_analysis
from spm_multiframe.cli.analyse_cli import (
    _pick_default,
    _resolve_channel,
    choose_input_format,
    discover_common_channels,
    resolve_atom_tracking_hint,
)
from spm_multiframe.config import load_analysis_config, load_stack_config
from spm_multiframe.exceptions import SPMError, StaleAnalysisError
from spm_multiframe.io.scan_reader import InputFormat
from spm_multiframe.stacking.stack_pipeline import (
    find_analysis_manifest,
    run_stack,
    verify_analysis_manifest,
)
from spm_multiframe.utils.logging import configure_logging

console = Console()


def _progress(stage: int, total: int, message: str) -> None:
    console.print(f"[bold cyan][{stage}/{total}][/bold cyan] {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spm-stack",
        description="Validate a drift/lattice manifest and stack one or more simultaneously acquired SXM/GWY channels.",
    )
    parser.add_argument("dataset", nargs="?", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--registration-channel")
    parser.add_argument("--channels", nargs="+", help="Output channels to stack")
    parser.add_argument("--output", "-o", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--format", choices=["auto", "sxm", "gwy"], default="auto", help="Input format when a new analysis must be run")
    parser.add_argument("--method", choices=["mean", "weighted_mean", "sigma_clipped_mean", "median"])
    parser.add_argument("--no-gui", action="store_true", help="Accept all scans and largest common region without GUI")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _ensure_analysis(
    dataset: Path,
    manifest_path: Path | None,
    interactive: bool,
    input_format: InputFormat = "auto",
) -> Path:
    selected = manifest_path or find_analysis_manifest(dataset)
    if selected is not None:
        try:
            verify_analysis_manifest(dataset, selected)
            return selected
        except StaleAnalysisError as exc:
            console.print(f"[yellow]{exc}[/yellow]")
    else:
        console.print("[yellow]No valid drift/lattice analysis was found.[/yellow]")
    if not interactive:
        raise StaleAnalysisError("Run spm-drift-lattice first, then rerun spm-stack")
    answer = input("Run drift/lattice analysis now? [Y/n]: ").strip().lower()
    if answer in {"n", "no"}:
        raise StaleAnalysisError("Stacking requires a valid drift/lattice analysis")
    _paths, common = discover_common_channels(dataset, input_format=input_format)
    default = _pick_default(common)
    entered = input(f"Registration/lattice channel [{default}]: ").strip()
    channel = _resolve_channel(entered or default, common)
    output = dataset / "analysis_results"
    logger = configure_logging(output / "run.log")
    atom_hint = resolve_atom_tracking_hint(dataset, interactive=True)
    result = run_analysis(
        dataset,
        registration_channel=channel,
        output_dir=output,
        input_format=input_format,
        atom_tracking_hint=atom_hint,
        config=load_analysis_config(None),
        logger=logger,
        progress=lambda s, t, m: console.print(f"[cyan][analysis {s}/{t}][/cyan] {m}"),
    )
    return result.manifest_path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    interactive = args.dataset is None
    try:
        dataset = args.dataset
        if dataset is None:
            dataset = Path(input("Folder containing .sxm/.gwy files: ").strip()).expanduser()
        dataset = dataset.resolve()
        requested_format = choose_input_format(dataset, args.format, interactive=interactive)
        manifest_path = _ensure_analysis(
            dataset,
            args.manifest.resolve() if args.manifest else None,
            interactive,
            requested_format,
        )
        manifest = verify_analysis_manifest(dataset, manifest_path)
        manifest_format = manifest.get("input_format")
        if manifest_format not in {"sxm", "gwy"}:
            suffixes = {Path(item["relative_path"]).suffix.lower() for item in manifest.get("source_files", [])}
            if suffixes == {".gwy"}:
                manifest_format = "gwy"
            elif suffixes == {".sxm"}:
                manifest_format = "sxm"
            else:
                manifest_format = requested_format
        _paths, common = discover_common_channels(dataset, input_format=manifest_format)
        default_registration = manifest.get("registration_channel") or _pick_default(common)
        if args.registration_channel:
            registration_channel = _resolve_channel(args.registration_channel, common)
        elif interactive:
            entered = input(f"Registration channel [{default_registration}]: ").strip()
            registration_channel = _resolve_channel(entered or default_registration, common)
        else:
            registration_channel = _resolve_channel(default_registration, common)

        table = Table(title="Channels available for stacking")
        table.add_column("Channel")
        table.add_column("Default")
        for channel in common:
            table.add_row(channel, "[x]" if channel == registration_channel else "[ ]")
        console.print(table)
        if args.channels:
            stack_channels = [_resolve_channel(value, common) for value in args.channels]
        elif interactive:
            entered = input(
                f"Channels to stack, comma-separated [{registration_channel}]: "
            ).strip()
            requested = [part.strip() for part in entered.split(",") if part.strip()] if entered else [registration_channel]
            stack_channels = [_resolve_channel(value, common) for value in requested]
        else:
            stack_channels = [registration_channel]
        stack_channels = list(dict.fromkeys(stack_channels))

        cfg = load_stack_config(args.config)
        if args.method:
            cfg.method = args.method
        output = args.output.resolve() if args.output else dataset / "stack_results"
        logger = configure_logging(output / "run.log", verbose=args.verbose)
        console.print("[bold]SPM multi-frame stacking[/bold]")
        result = run_stack(
            dataset,
            registration_channel=registration_channel,
            stack_channels=stack_channels,
            manifest_path=manifest_path,
            output_dir=output,
            config=cfg,
            use_gui=not args.no_gui,
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
