from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AtomTrackingHint:
    """External lateral-drift information used as a soft prior for image-based fitting.

    ``correction_velocity_nm_s`` follows the package convention used by
    :func:`spm_multiframe.geometry.transforms.corrected_coordinates`:
    ``r_corr = r_nom + v_c (t - t_ref)``.

    Nanonis ``Piezo.DriftCompGet`` values Vx/Vy are already compensation speeds and map
    directly to ``v_c``.  A tracked atom/tip position slope describes motion of the
    feature in scanner coordinates and is therefore converted to ``v_c = -v_feature``.
    """

    correction_velocity_nm_s: np.ndarray
    source: str
    source_kind: str
    convention: str
    vz_nm_s: float | None = None
    details: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "correction_velocity_nm_s": np.asarray(
                self.correction_velocity_nm_s, dtype=float
            ).tolist(),
            "source": self.source,
            "source_kind": self.source_kind,
            "convention": self.convention,
            "vz_nm_s": self.vz_nm_s,
            "details": self.details,
        }


_ATOM_NAME_RE = re.compile(
    r"(?i)(atom[ _-]*track|drift[ _-]*(?:comp|compensation|velocity|speed|measure|meas)|piezo[ _-]*drift)"
)
_SUPPORTED_SUFFIXES = {".csv", ".tsv", ".txt", ".dat", ".json"}


def discover_atom_tracking_files(dataset_dir: str | Path) -> list[Path]:
    """Return likely atom-tracking/drift log files under a dataset directory.

    Nanonis does not define a dedicated Atom Tracking result-file format in the public TCP
    protocol.  This discovery therefore targets user/TCP-exported text, CSV, DAT or JSON
    logs whose filenames explicitly mention atom tracking or drift compensation.
    """
    root = Path(dataset_dir).expanduser().resolve()
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            continue
        if _ATOM_NAME_RE.search(path.stem):
            found.append(path)
    return sorted(found)


def _norm(text: str) -> str:
    value = text.strip().lower()
    value = value.replace("μ", "u").replace("µ", "u").replace("å", "angstrom")
    return re.sub(r"[^a-z0-9]+", "", value)


def _velocity_unit_factor_to_nm_s(label: str, *, default: float | None = None) -> float | None:
    text = label.lower().replace("μ", "u").replace("µ", "u").replace("å", "angstrom")
    compact = re.sub(r"\s+", "", text)
    # Order matters: nm/s contains m/s as a substring.
    if any(token in compact for token in ("nm/s", "nms-1", "nms^-1", "nmpersec", "nmpersecond")):
        return 1.0
    if any(token in compact for token in ("pm/s", "pms-1", "pms^-1", "pmpersec", "pmpersecond")):
        return 1e-3
    if any(token in compact for token in ("angstrom/s", "angstroms-1", "angstrompersec", "a/s")):
        return 0.1
    if any(token in compact for token in ("um/s", "ums-1", "ums^-1", "umpersec")):
        return 1e3
    if any(token in compact for token in ("m/s", "ms-1", "ms^-1", "mpersec", "mpersecond")):
        return 1e9
    if any(token in compact for token in ("nm/min", "nmmin-1", "nmpermin")):
        return 1.0 / 60.0
    if any(token in compact for token in ("pm/min", "pmmin-1", "pmpermin")):
        return 1e-3 / 60.0
    return default


def _length_unit_factor_to_nm(label: str, *, default: float | None = None) -> float | None:
    text = label.lower().replace("μ", "u").replace("µ", "u").replace("å", "angstrom")
    if "angstrom" in text:
        return 0.1
    if re.search(r"(?:^|[^a-z])pm(?:[^a-z]|$)", text):
        return 1e-3
    if re.search(r"(?:^|[^a-z])nm(?:[^a-z]|$)", text):
        return 1.0
    if re.search(r"(?:^|[^a-z])um(?:[^a-z]|$)", text):
        return 1e3
    if re.search(r"(?:^|[^a-z])m(?:[^a-z]|$)", text):
        return 1e9
    return default


def _time_unit_factor_to_s(label: str, *, default: float | None = None) -> float | None:
    text = label.lower().replace("μ", "u").replace("µ", "u")
    if re.search(r"(?:^|[^a-z])ms(?:[^a-z]|$)", text):
        return 1e-3
    if re.search(r"(?:^|[^a-z])us(?:[^a-z]|$)", text):
        return 1e-6
    if re.search(r"(?:^|[^a-z])min(?:[^a-z]|$)", text):
        return 60.0
    if re.search(r"(?:^|[^a-z])s(?:[^a-z]|$)", text) or "time" in text:
        return 1.0
    return default


def _as_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _dict_lookup(mapping: dict[str, Any], aliases: Iterable[str]) -> tuple[str, Any] | None:
    normalized = {_norm(str(key)): (str(key), value) for key, value in mapping.items()}
    for alias in aliases:
        candidate = normalized.get(_norm(alias))
        if candidate is not None:
            return candidate
    return None


def _hint_from_mapping(mapping: dict[str, Any], source: Path) -> AtomTrackingHint | None:
    # Explicit package-native keys are unambiguous and preferred.
    corr_x = _dict_lookup(mapping, ("correction_vx_nm_s", "correction vx nm s"))
    corr_y = _dict_lookup(mapping, ("correction_vy_nm_s", "correction vy nm s"))
    if corr_x and corr_y:
        vx = _as_float(corr_x[1])
        vy = _as_float(corr_y[1])
        if vx is not None and vy is not None:
            return AtomTrackingHint(
                np.asarray([vx, vy], dtype=float),
                str(source),
                "direct_velocity",
                "correction",
                details="Explicit correction_vx_nm_s/correction_vy_nm_s fields",
            )

    sample_x = _dict_lookup(mapping, ("sample_vx_nm_s", "atom_vx_nm_s", "feature_vx_nm_s"))
    sample_y = _dict_lookup(mapping, ("sample_vy_nm_s", "atom_vy_nm_s", "feature_vy_nm_s"))
    if sample_x and sample_y:
        vx = _as_float(sample_x[1])
        vy = _as_float(sample_y[1])
        if vx is not None and vy is not None:
            return AtomTrackingHint(
                -np.asarray([vx, vy], dtype=float),
                str(source),
                "direct_velocity",
                "sample_motion_converted_to_correction",
                details="Explicit sample/atom velocity fields",
            )

    # Nanonis/TCP-style Piezo.DriftCompGet fields: Vx/Vy are compensation speeds.
    vx_item = _dict_lookup(mapping, ("Vx (m/s)", "Vx", "drift Vx", "compensation Vx"))
    vy_item = _dict_lookup(mapping, ("Vy (m/s)", "Vy", "drift Vy", "compensation Vy"))
    if vx_item and vy_item:
        vx = _as_float(vx_item[1])
        vy = _as_float(vy_item[1])
        if vx is not None and vy is not None:
            label = f"{vx_item[0]} {vy_item[0]}"
            factor = _velocity_unit_factor_to_nm_s(label)
            source_text = " ".join(str(x) for x in mapping.keys()).lower()
            if factor is None and (
                "piezodriftcomp" in _norm(source_text)
                or "driftcomp" in _norm(source.stem)
                or "nanonis" in source_text
            ):
                factor = 1e9
            if factor is not None:
                vz_item = _dict_lookup(mapping, ("Vz (m/s)", "Vz", "drift Vz", "compensation Vz"))
                vz = _as_float(vz_item[1]) if vz_item else None
                if vz is not None:
                    vz *= factor
                return AtomTrackingHint(
                    np.asarray([vx * factor, vy * factor], dtype=float),
                    str(source),
                    "nanonis_drift_compensation",
                    "correction",
                    vz_nm_s=vz,
                    details="Interpreted as Nanonis Piezo.DriftComp compensation speed",
                )
    return None


def _load_dataframe(path: Path) -> pd.DataFrame | None:
    attempts = (
        {"sep": None, "engine": "python", "comment": "#"},
        {"sep": "\t", "engine": "python", "comment": "#"},
        {"sep": r"\s+", "engine": "python", "comment": "#"},
    )
    for kwargs in attempts:
        try:
            frame = pd.read_csv(path, **kwargs)
        except Exception:
            continue
        if frame.shape[1] >= 2 and len(frame) >= 1:
            return frame
    return None


def _find_column(columns: list[str], exact_tokens: tuple[str, ...], contains_tokens: tuple[str, ...]) -> str | None:
    normalized = {_norm(col): col for col in columns}
    for token in exact_tokens:
        if _norm(token) in normalized:
            return normalized[_norm(token)]
    for col in columns:
        n = _norm(col)
        if any(_norm(token) in n for token in contains_tokens):
            return col
    return None


def _median_numeric(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    return float(np.median(values)) if values.size else None


def _hint_from_dataframe(frame: pd.DataFrame, source: Path) -> AtomTrackingHint | None:
    columns = [str(col) for col in frame.columns]

    vx_col = _find_column(
        columns,
        ("Vx (m/s)", "Vx (nm/s)", "correction_vx_nm_s", "sample_vx_nm_s"),
        ("driftvx", "compensationvx", "velocityx", "speedx"),
    )
    vy_col = _find_column(
        columns,
        ("Vy (m/s)", "Vy (nm/s)", "correction_vy_nm_s", "sample_vy_nm_s"),
        ("driftvy", "compensationvy", "velocityy", "speedy"),
    )
    if vx_col and vy_col:
        vx = _median_numeric(frame[vx_col])
        vy = _median_numeric(frame[vy_col])
        if vx is not None and vy is not None:
            labels = f"{vx_col} {vy_col}"
            factor = _velocity_unit_factor_to_nm_s(labels)
            if factor is None:
                # Explicit *_nm_s columns already carry their unit in normalized form.
                normalized_labels = _norm(labels)
                if "nms" in normalized_labels:
                    factor = 1.0
            if factor is not None:
                normalized_labels = _norm(labels)
                is_sample = any(token in normalized_labels for token in ("sample", "atom", "feature"))
                velocity = np.asarray([vx * factor, vy * factor], dtype=float)
                convention = "correction"
                if is_sample:
                    velocity = -velocity
                    convention = "sample_motion_converted_to_correction"
                vz_col = _find_column(
                    columns,
                    ("Vz (m/s)", "Vz (nm/s)", "correction_vz_nm_s", "sample_vz_nm_s"),
                    ("driftvz", "compensationvz", "velocityz", "speedz"),
                )
                vz_nm_s = None
                if vz_col is not None:
                    vz = _median_numeric(frame[vz_col])
                    vz_factor = _velocity_unit_factor_to_nm_s(vz_col, default=factor)
                    if vz is not None and vz_factor is not None:
                        vz_nm_s = float(vz * vz_factor)
                        if is_sample:
                            vz_nm_s = -vz_nm_s
                return AtomTrackingHint(
                    velocity,
                    str(source),
                    "direct_velocity",
                    convention,
                    vz_nm_s=vz_nm_s,
                    details=f"Median of columns {vx_col!r}, {vy_col!r}",
                )

    # Tracking-position logs can be converted to a velocity by fitting X(t), Y(t).
    time_col = _find_column(columns, ("Time (s)", "time_s", "elapsed_s"), ("elapsedtime", "timestamp"))
    x_col = _find_column(columns, ("X (nm)", "x_nm", "Tip X (m)", "Atom X (nm)"), ("tipx", "atomx", "trackedx", "xposition"))
    y_col = _find_column(columns, ("Y (nm)", "y_nm", "Tip Y (m)", "Atom Y (nm)"), ("tipy", "atomy", "trackedy", "yposition"))
    if time_col and x_col and y_col:
        t = pd.to_numeric(frame[time_col], errors="coerce").to_numpy(dtype=float)
        x = pd.to_numeric(frame[x_col], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(frame[y_col], errors="coerce").to_numpy(dtype=float)
        t_factor = _time_unit_factor_to_s(time_col, default=1.0)
        x_factor = _length_unit_factor_to_nm(x_col)
        y_factor = _length_unit_factor_to_nm(y_col)
        valid = np.isfinite(t) & np.isfinite(x) & np.isfinite(y)
        if np.count_nonzero(valid) >= 3 and t_factor is not None and x_factor is not None and y_factor is not None:
            ts = t[valid] * t_factor
            if float(np.ptp(ts)) > 0:
                sx = float(np.polyfit(ts, x[valid] * x_factor, 1)[0])
                sy = float(np.polyfit(ts, y[valid] * y_factor, 1)[0])
                return AtomTrackingHint(
                    -np.asarray([sx, sy], dtype=float),
                    str(source),
                    "tracked_position_slope",
                    "sample_motion_converted_to_correction",
                    details=f"Linear slopes fitted from {time_col!r}, {x_col!r}, {y_col!r}",
                )
    return None


def load_atom_tracking_hint(path: str | Path) -> AtomTrackingHint | None:
    """Parse a conservative atom-tracking/drift sidecar into a correction-velocity hint.

    Supported inputs are JSON mappings, delimited tables containing explicit X/Y drift
    velocities, or time-series tables containing tracked X/Y positions and time.  Ambiguous
    unitless generic values are intentionally rejected instead of guessed.
    """
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() == ".json":
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        candidates: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            candidates.append(raw)
            for value in raw.values():
                if isinstance(value, dict):
                    candidates.append(value)
        elif isinstance(raw, list):
            candidates.extend(item for item in raw if isinstance(item, dict))
        for mapping in candidates:
            hint = _hint_from_mapping(mapping, source)
            if hint is not None:
                return hint
        return None

    frame = _load_dataframe(source)
    if frame is not None:
        hint = _hint_from_dataframe(frame, source)
        if hint is not None:
            return hint

    # Final key=value fallback for hand-exported text logs.
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    mapping: dict[str, Any] = {}
    for line in text.splitlines():
        match = re.match(r"\s*([^:=]+?)\s*[:=]\s*([-+0-9.eE]+)\s*$", line)
        if match:
            mapping[match.group(1).strip()] = match.group(2)
    return _hint_from_mapping(mapping, source) if mapping else None


def find_first_atom_tracking_hint(dataset_dir: str | Path) -> tuple[AtomTrackingHint | None, list[Path]]:
    """Return the first unambiguously parseable candidate plus all discovered candidates."""
    candidates = discover_atom_tracking_files(dataset_dir)
    for path in candidates:
        hint = load_atom_tracking_hint(path)
        if hint is not None:
            return hint, candidates
    return None, candidates


def manual_atom_tracking_hint(
    vx: float,
    vy: float,
    *,
    unit: str = "nm/s",
    convention: str = "correction",
    vz: float | None = None,
) -> AtomTrackingHint:
    """Create a manual hint from Nanonis drift values or measured sample/atom motion."""
    factor = _velocity_unit_factor_to_nm_s(unit)
    if factor is None:
        raise ValueError(f"Unsupported velocity unit {unit!r}")
    vector = np.asarray([float(vx) * factor, float(vy) * factor], dtype=float)
    normalized = convention.strip().lower()
    if normalized in {"sample", "atom", "feature", "sample_motion"}:
        vector = -vector
        stored_convention = "sample_motion_converted_to_correction"
    elif normalized in {"correction", "compensation", "nanonis", "piezo"}:
        stored_convention = "correction"
    else:
        raise ValueError("convention must be 'correction' or 'sample'")
    vz_nm_s = None if vz is None else float(vz) * factor
    return AtomTrackingHint(
        vector,
        "manual_user_entry",
        "manual",
        stored_convention,
        vz_nm_s=vz_nm_s,
        details="Manual drift hint entered at analysis start",
    )
