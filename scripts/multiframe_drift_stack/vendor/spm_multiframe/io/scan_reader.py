from __future__ import annotations

from pathlib import Path
from typing import Literal

from spm_multiframe.exceptions import SPMError
from spm_multiframe.io.gwy_reader import discover_gwy_files, read_gwy
from spm_multiframe.io.sxm_reader import SXMFile, discover_sxm_files, read_sxm

InputFormat = Literal["auto", "sxm", "gwy"]


def available_scan_formats(folder: str | Path, *, recursive: bool = True) -> dict[str, list[Path]]:
    return {
        "sxm": discover_sxm_files(folder, recursive=recursive),
        "gwy": discover_gwy_files(folder, recursive=recursive),
    }


def discover_scan_files(
    folder: str | Path,
    *,
    recursive: bool = True,
    input_format: InputFormat = "auto",
) -> list[Path]:
    formats = available_scan_formats(folder, recursive=recursive)
    if input_format == "sxm":
        return formats["sxm"]
    if input_format == "gwy":
        return formats["gwy"]
    if input_format != "auto":
        raise SPMError(f"Unknown input format {input_format!r}")
    # Raw SXM is preferred automatically because it contains the complete acquisition
    # geometry/timing needed for quantitative drift correction.  Users can force GWY with
    # --format gwy when both representations are present.
    return formats["sxm"] or formats["gwy"]


def read_scan(path: str | Path, *, load_data: bool = True) -> SXMFile:
    scan_path = Path(path)
    suffix = scan_path.suffix.lower()
    if suffix == ".sxm":
        return read_sxm(scan_path, load_data=load_data)
    if suffix == ".gwy":
        return read_gwy(scan_path, load_data=load_data)
    raise SPMError(f"Unsupported scan file extension {scan_path.suffix!r}: {scan_path.name}")


def source_format_for_paths(paths: list[Path]) -> str:
    suffixes = {path.suffix.lower() for path in paths}
    if suffixes == {".sxm"}:
        return "sxm"
    if suffixes == {".gwy"}:
        return "gwy"
    return "mixed"
