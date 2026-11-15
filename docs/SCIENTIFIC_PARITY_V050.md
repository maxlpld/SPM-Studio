# v0.5.0 audit: original scientific engines and GUI adaptation

## What was actually compared

- **CPD histogram:** final `cpd_histogram_analysis.py` in `legacy_reference/CPD HISTO.zip` (the *last* definitions in the file are the current legacy version). The original final comparison legend reports each named mask's sample count; Gaussian amplitude, x_max/mean, width, parameter uncertainties and R²; and optionally selected absolute peak-position differences. These were missing in Studio v0.4.3. The generated figure now has a dedicated legend column, preserving those information categories, mask colors and the three stacked independent scan panels. Plot spacing and individual text placement are not pixel-identical to the old Tk export editor.
- **Automatic lattice + multiframe:** the original computational **spm-multiframe-v0.1.2** source files in `scripts/lattice_measurements/vendor/spm_multiframe` and `scripts/multiframe_drift_stack/vendor/spm_multiframe` are byte-for-byte unchanged from the archive. Studio modules only choose the scan set, pass parameters, relay progress and register results. They call `analysis.pipeline.run_analysis` and `stacking.stack_pipeline.run_stack` directly in the separate analysis process. This restores the original drift fit, atom-tracking hints, acquisition time reconstruction, FFT reciprocal basis candidate selection, Gauss reduction, bootstrap uncertainties, drift/metadata physical overlap, subpixel registration, combination methods, TIFF/PNG/CSV/JSON/report exports.
- **Data selection:** file discovery is temporarily replaced by the exact list of scans selected in Studio. Nothing else in the scientific engine is modified, and untouched files in the source folder are ignored. The original metadata and source-file SHA-256 checks remain active.
- **User interface:** the original MultiFrame's separate common-region PySide6 dialog is intentionally *not* launched from Studio's isolated worker. The original headless physical-overlap path selects its maximum common rectangle automatically and writes diagnostics for review. **Interactive include/exclude and crop/preview inside Studio still need integration**, so this is not full GUI workflow parity. Do not confuse automatic overlap selection with human-validated crop quality.

## CPD limitations that remain

- Studio uses its existing Gaussian least-squares fitter; it does **not** claim numerical identity with the old curve-fit implementation. Reported parameter errors are local Jacobian/residual covariance estimates; they are unavailable when poorly constrained, and they are NOT equivalent to bootstrap intervals.
- R² is calculated from the mask's normalized *binned* histogram. Empty/failed fits are reported explicitly, not given invented error bars or R².
- Legend texts are auto-generated, colored per mask; they may be overridden using JSON. Differences use the largest-amplitude component's mean x_max (as in the old script). Which pairs to report can be set to all, none, or named pairs.
- Original CPD's interactive final-figure legend dragging, full value-scale border/position controls, native GWY mask-channel export, and every advanced mask editor control remain unfinished. No claim of exact figure/editor parity.

## Other modules: unchanged limitations

- Flake height: preserved v0.4.3 multi-line island edge method, not experimentally compared to the original GUI.
- KPFM edge: remains an abbreviated algorithm, not a complete migration of the legacy KPFM script.
- Batch scan report: simplified preview/report, not all original metadata and scientific panels.
- Molecular overlay and placement: advanced physical placement engine remains unmigrated.
- `lattice_measurements` also has the v0.4.3 manual line-profile diagnostic mode, selectable separately from the original *automatic* primitive lattice engine. The original standalone `lattice_analysis.py` interactive Gwyddion CSV statistical workflow is not reproduced in full.

## Test evidence

- Studio automated suite (pytest): see `tests/test_v050_original_engines_and_legend.py`; asserts byte equality of the original computational engine source, the detailed CPD legend fields, source exclusion and numeric lattice recovery on a deterministic four-scan mixed-up/down/0°/90° SXM dataset.
- Original archive's unit tests: the full suite was run independently (29 passed). Synthetic reference test includes the previously problematic (a, a+b) primitive/sheared-basis ambiguity and a Z/other-channel harmonic-stability test.
- An end-to-end adapter run with linear drift enabled recovered approximately a = 0.9390 nm, b = 0.7710 nm, γ = 66.98° from simulated true 0.94 nm, 0.77 nm, 67° and wrote a two-channel stack.
- **Caution:** On the same small drifted synthetic set, disabling drift yielded a misleading lattice (approximately 0.866 nm, 0.491 nm, 89.57°) when only three frames were selected. Therefore do not assume lattice-only mode gives correct values on appreciably drifted data; compare channels/multiple scans and the diagnostic quality metrics. Scientific QA remains essential.
- No real instrument SXM/GWY golden dataset was supplied for this release. Physical orientation, mask fractions, fitting parity and high-volume performance must still be checked on such data.
- Qt/Wayland smoke testing was unavailable in the build environment (PySide6 cannot be downloaded here). The GUI/Inspector changes have syntax and static checks, but require a real workstation for visual confirmation.

## File placement and outputs

- The editable module folder remains `~/.local/share/spm-studio/scripts/`.
- New engines ship next to each module; they are **not hard-coded in the main Studio package**.
- All analysis and stacking files go under the scan's `SPM_Studio_Results/<scan>/<run>/multiframe_analysis` and `multiframe_stack` directories.
- The original engine reports all outputs through Studio's result drawer. Numerical arrays are not overwritten with the UI preview data.
- The v0.4.3 file-hash migration upgrades untouched module files, backs up originals, leaves customized/removed modules alone, and adds new vendor support files only when absent.
