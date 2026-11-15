# Verification report — v0.3.1 (2026-10-13)

Linux build environment: pytest, NumPy, SciPy, Matplotlib, Python 3.11+.
PySide6, real Gwyddion `gwyfile`, legacy `nanonispy`, and instrument-produced
SXM/GWY datasets were **not** available in the offline test environment.

```
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src python -m pytest -q
```

**35 passed**, 0 failures, using the locally available scientific dependencies.
The existing v0.3.0 baseline of 28 tests still passes. Additional checks:
valid generated SXM binary rasters (big/little-endian floats, FWD/BWD, one-way
channels, geometry/units), truncated payload -> NaNs, malformed DATA_INFO
rejection, GWY test doubles (duplicate names, FWD/BWD, untitled fields), and
a command-line reader health check. All 119 supplied legacy `.py` sources
passed AST parsing (none imported/executed by the application).
Separately, the original `spm-multiframe-v0.1.2` archive passed **29/29**
existing synthetic/geometry/timing/drift/stack unit tests when run with its
original source tree on `PYTHONPATH`. This is not evidence that those engines
are connected to the Studio module.

**Not established:** end-to-end loading on real Nanonis/Gwyddion exports,
physical orientation on real asymmetric 0°/90°/up/down scans, PySide6/HiDPI
window functionality, actual `.gwy` binary decoding, numerical comparison to
historical CPD/flake/edge/lattice/molecule modules, 2× lattice regression on
real measurements, real drift estimation, and full GUI/export parity.

These are scientific acceptance gates, not minor optional style checks. Refer
to `REQUIREMENTS_AUDIT.md` and `REAL_DATA_VALIDATION.md`.
