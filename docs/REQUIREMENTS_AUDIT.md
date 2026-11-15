> **v0.4.0 update (14 October 2026):** Adds scoped native interaction for multiple flake lines and CPD value masks, per-scan result directories and shared publication presets. The earlier table below documents the original audit; see `WORKFLOWS_V040.md` for updated status. **Full legacy scientific parity, GWY mask round-trip, and Ubuntu/Wayland GUI acceptance remain unverified.**

> **v0.3.2 note (14 October 2026):** Fast first preview, disk-backed SXM rasters and
> nonblocking rendering have been patched. This does **not** change the incomplete
> scientific modules listed below. Real-world GWY decoding and Ubuntu Qt/Wayland
> smoke tests remain outstanding in this offline test environment.

# Specification compliance audit — v0.3.1 (13 October 2026)

Basis: `docs/MASTER_SPECIFICATION.md`, v0.3.0 sources, and original reference
archives included under `legacy_reference/`. This is an implementation audit,
**not a certification of experimentally correct AFM/STM/KPFM results**.

Definitions: **Implemented** = source path exists and has appropriate synthetic
unit tests or direct code inspection; **Partial** = some feature is present but
one or more required behaviors are absent; **Unavailable** = no working engine;
**Unverified** = requires vendor binary files, Qt installation, instrument or
physical validation not present in the build environment.

| Specification requirement | State in v0.3.1 | Audit finding / next acceptance gate |
|---|---|---|
| Small, modular PySide6 shell; offline operation | Implemented; Qt unverified | Single GUI, no hardware startup, manifest-only discovery; PySide6 absent in test environment. |
| Large Qt-native preview, no Matplotlib per channel | Implemented; speed unverified | `core.display`, `core.painting`, `ui.image_view`; performance targets not profiled on Ubuntu/HiDPI. |
| Loading SXM and GWY scans | Patched; real files unverified | Native SXM binary decoder + optional scoped legacy nanonispy reader; GWY installed by default with current `gwyfile`. SXM binary fixtures tested; GWY mocks tested, but no actual user SXM/GWY files available for binary acceptance. |
| All channels, explicit FWD/BWD, missing trace | Implemented for common variants | GX channel title handling improved; incomplete SXM NaNs tested; proprietary variants and source equivalence unverified. |
| Physical orientation, 90°, up/down, calibration | Partial, instrument-unverified | Coordinate transform tested synthetically. Stored arrays are **not flipped automatically**; true physical orientation is unverified pending asymmetric real fiducial tests. Absolute coordinates for GWY not asserted. |
| Physical metadata, original units, no double calibration | Partial | Header values and declared channel units are preserved. GWY XY prefixes converted to metres; arbitrary GWY unit conversions / full metadata and exact scan acquisition time still pending. |
| Non-destructive processing, independent channel styles | Implemented for basic operations | Basic plane, row, line, scar, inversion pipeline; some Gwyddion-specific correction algorithms and parameter editors not included. |
| Fast style changes, bounded cache, responsive workers | Implemented; speed unverified | 384 MiB LRU, Qt rendering, thread pool; no wall-clock performance/peak memory benchmark on representative scans. |
| Zoom, pan, fit, point/line/rect ROI, cursor | Partial | Zoom/pan/fit, line/rectangle and cursor readout implemented. Full interactive point ROI and full physical-selection roundtrip remain limited. |
| Manifest-based add/remove/refresh scripts | Implemented | External `module.json` discovered without running top-level code; subprocess runner and basic schema; sandboxing not provided. |
| Arbitrary `.py` compatibility, live logs, cancel | Partial | QProcess async, unbuffered logs/cancel, legacy compatibility. Terminal `input()` and interactive legacy Tk UI are not integrated; no headless QProcess acceptance. |
| Results pane, logging, error history | Partial | In-app drawer, result files and logs implemented. Full image/plot/array result API and guaranteed cancellation cleanup not tested. |
| Shared publication image export and SI provenance | Partial | PNG/PDF/SVG/JPG and NPY/CSV + sidecar; no 2/4-panel composition, extensive figure settings, or real preview/export pixel/ROI parity suite. |
| STM/KPFM/Multipass profiles, theme, colormaps | Partial | JSON validation, imports and predefined themes/profiles; full profile management/scope and styles (fonts, colorbar placement) incomplete. |
| Batch scan report | Partial | Multipage PDF, matching channels, metadata; old six-panel report layout/algorithm not ported nor numerically compared. |
| Flake height | Partial | Simplified two-terrace/peak version; original ROI terrace/edge fit, uncertainty and FWD/BWD behaviors not ported. |
| CPD histogram | Partial | Histograms, mask and Gaussian fits; historical 8,648-line vs 5,348-line duplicate variants **not audited against each other**. Manual/auto peaks and full comparisons missing. |
| KPFM edge | Partial | Simplified width/gradient analysis; old physical registration, 10–90%, FWHM and absolute-difference parity unverified. |
| Lattice measurements | Partial | Basic image line peaks/FFT diagnostics only; standalone script's Gwyddion profile selection, manual angle pairing, trends, uncertainty/comparison tables not ported. |
| Molecule/lattice overlay | Partial | Parametric footprint outline; source image scaling, independent manual placements and feature detection missing. |
| Physically informed molecular placement | Unavailable | Original reference source **now included for migration** but not adapted as native Qt module. Do not claim DFT quality. |
| Multiframe drift / lattice / stack | Partial; drift unavailable | Simple spatial-coordinate resampling stack + coverage. Original v0.1.2 drift/atom tracking/crop preview, primitive lattice and 2× check not integrated or baseline tested. |
| Amplitude calibration | Correctly excluded | Dangerous instrument controller is inert in `legacy_reference/`, never imported or executed. |
| `.nhf`/`.nid` | Intentionally unsupported | No tested reader; no fake dimensions or fabricated channels. |
| Full integration, reader, geometry, module and GUI tests | Partial | v0.3.1: 35 local automated tests plus 119 original-source AST parses. Real data, PySide6/Ubuntu GUI smoke and original-vs-new numerical baselines missing. |

## Scientifically significant limitations

1. **SXM orientation is not known to match the sample display convention.**
   One raster-order convention cannot be assumed for all Nanonis scan directions,
   rotations, edited GWY files or hardware setups. Do not interpret overlaid
   molecular sites or stacking alignment until real fiducials validate orientation.
2. **A reader opening an image does not certify its measurements.** Channel
   units, raw-to-SI handling, CPD polarities, image sign, XY calibration and
   uncertainty budgets need comparison to Gwyddion and raw source settings.
3. The CPD, edge, flake, lattice and multiframe modules in this build are
   **exploratory reimplementations**, not faithfully verified ports of the
   corresponding legacy algorithms. Results should not be reported as final
   quantitative scientific findings without cross-checking.
4. In multiframe, simple geometric resampling does **not** estimate drift,
   line-by-line acquisition movement or primitive basis reliably. It is not an
   implementation of the full astrophotography-like stacking request.

## Reproducible checks performed

- Source AST parse: 119 Python files, 0 parse errors (including archives).
- Existing v0.3.0 test suite: 28/28 passed before patch.
- v0.3.1 test suite: 35/35 passed (NumPy/SciPy/Matplotlib/pytest on Linux,
  with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`); real binary SXM test fixtures were
  generated programmatically, not supplied by Nanonis.
- The archived, standalone `spm-multiframe-v0.1.2` source passed 29/29
  own unit tests when run independently; this is not integrated Studio validation.
- GWY tests are parser mocks, **not** actual `.gwy` binary tests.
- PySide6, `gwyfile` and `nanonispy` were unavailable in the current offline
  build container. The UI, full package install, Qt export and GWY decoding
  cannot honestly be stated as tested here.

## Remaining original-spec acceptance gates

Obtain one intact and one incomplete Nanonis SXM, a representative GWY made
from the same acquisition, plus asymmetric 0°, 90°, up/down, forward/backward
fiducials with Gwyddion reference images. Run `spm-studio-check` on each file,
then visually verify stored orientation, `SCAN_RANGE`, physical XY coordinates,
NaN masks, trace matching, channel title mapping and image colorbar. For each
scientific module, port the original implementation and compare per-pixel masks,
profiles, numerical outputs and plots against the legacy baseline (with its
original dependency versions); preserve a golden fixture. Add GUI smoke tests
on Ubuntu/Python 3.14 and high-DPI monitor, run headless Qt export tests and
performance/memory benchmarks before any final release claim.
