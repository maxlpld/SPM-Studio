# v0.4.1 — interactive selections, simultaneous previews and real module folders

## CPD/Bias histogram masks

1. Open the desired scan. Select **CPD / Bias histogram** in the Tools list.
2. **+ New** creates a named mask. Click a mask in the list to edit it.
3. Drag one of the visible **colored handles** in the live histogram to change only that limit. Drag on empty histogram space to redefine the selected interval. A click inside a band does not move it. Numeric min/max fields update the overlay whenever both values are valid.
4. To restrict the image spatially, click **Draw region** in Tool settings. Drag on the image to create a rectangle. Once drawn, move one of its eight visible handles to edit that side/corner without moving the whole ROI. Use **Draw region** again to start a fresh rectangle. Use **Pan** to move the view instead.
5. Live histogram and image overlay use bounded preview samples; the analysis module receives full-resolution data. Choose Gaussians per mask and **Run** when satisfied. Masks can be saved and imported via the existing buttons.

Current mask types are **value intervals**, optionally restricted to a rectangular spatial ROI. The older CPD program had further polygon/mask-to-GWY and statistical selection features; those are **not** silently claimed to be present here.

## Flake height profiles

1. Select **Flake / island height**. The tool automatically enters line mode.
2. Use **Draw line** in **Tool settings** and drag across the island; every completed line remains on the scan.
3. Drag the **yellow circular endpoints** to adjust any retained line without deleting it. The line profile chart refreshes while you move the endpoint.
4. **Undo line**, **Clear lines** and **Pan** are in the same Tool settings panel.
5. Run after checking the lines and analysis parameters. Result files still go into a per-run folder next to the original scan.

## Simultaneous channels (for example KPFM)

1. Open a scan. Under **Inspector → Simultaneous channel previews**, check `Z` and `Bias` (up to four channels).
2. The selected Inspector channel is the **editable main image**; all others appear alongside as read-only channel previews. Different channel names and physical geometries are kept distinct. Other channel images aren't implicitly used as the ROI coordinate system.
3. Choose **KPFM** and **Apply profile** for the bundled two-channel layout, when these channels exist in the scan. Missing channels are skipped.
4. For a custom configuration, check the channels you want, then **File → Save current profile…**. The list is stored as `visible_channels` in your profile JSON. Load it later with **Apply profile**. Exact channel names match first; case-insensitive fragments are supported afterward.

The read-only thumbnails are color-rendered on background workers (at most 850 px per side) and do not make full-sized duplicate copies of every scan channel. The current processing chain applies to the main image, whereas each secondary uses its own saved channel processing if configured.

## Results and publication settings

Under **Options → Scientific plots & results…**, choose:
- PNG only, PDF only, or both;
- whether the **first figure automatically opens after a successful run**;
- a validated, editable scientific plot style JSON.

This option also remains available in the older Tools menu for compatibility. PNG first-results appear inside Studio, PDF-only outputs use the OS viewer. Turn this off to leave all results closed. Full numerical outputs/figures remain saved in:

`<scan folder>/SPM_Studio_Results/<scan filename>/<timestamp>_<tool>_<id>/`

## Scripts folder and extension contract

**Tools → Open Scripts folder** now opens `~/.local/share/spm-studio/scripts/`, containing the eight original *Studio* module folders (`module.json`, `module.py`, `README.md`) plus an editable **README_SCRIPT.md** template. The packaged `scripts/` tree is also complete and portable.

Factory tools are copied to the user folder **once only**, without overwriting existing folders. Delete a module directory and choose **Refresh modules** to remove it (it will not be restored on the next launch). Add a compatible folder containing a `module.json` and `module.py` and refresh to register it. No main window or registry code modification is needed for ordinary modules.

Manifest v1 additions: `interaction` (`none`, `line_profiles`, `histogram_masks`) and `snapshot_channels` (`selected` or `all`). These tell Studio what generic editor to show and what scan data to pass to the analysis. Unknown values are rejected during manifest discovery, without executing the source code. Arbitrary `*.py` standalones still appear in legacy subprocess mode but cannot acquire rich Qt controls without adopting the manifest/context API.

**Tools → Open Customization folder** opens the editable configuration directory and includes **README_CUSTOMIZATION.md** plus sample profiles, themes, colormaps, export presets and plot styles. Existing user edits are never replaced.

### Original scientific algorithms — important limitations

These tools have been moved out of the application core into installable folders and their current functionality retained; **the v0.4.0 analysis algorithms have not been rewritten or silently replaced in v0.4.1**. This update focuses on interactions and extensibility, not numerical equivalence to the original standalone tools.

| Studio module | Scientific migration status |
|---|---|
| `flake_height` | Multi-line edge heights and current settings; not full original Gwyddion profile/file input parity |
| `cpd_histogram` | Named interval masks, Gaussians and saved results; no full legacy polygon editor, mask-to-GWY, GMM/AIC/BIC workflows |
| `kpfm_edge` | Simplified implementation, not baseline-compared with original `kpfm_edge_analysis.py` |
| `lattice_measurements` | Simplified lattice/FFT analysis, not full interactive Gwyddion profile/angle workflows |
| `batch_scan_report` | General configurable reports, not complete original ImComp/ImRes six-panel output parity |
| `molecule_lattice_overlay` | Basic parametric overlays; not old complete editor |
| `molecule_placement` | Experimental/incomplete; original physics-informed candidate implementation not integrated |
| `multiframe_drift_stack` | Simplified registered image stacking, not complete original drift estimation / primitive lattice detection |

The original source files are preserved in **`legacy_reference/`**. `amp_calib.py` is a hardware-controlling script and is *not* activated as an offline analysis module. Full parity requires porting and comparing each source against representative instrument data, including masks, geometry, numerical values and export tables.

### Validation

- Pure Python tests: 46 passed in the build environment.
- Optional Qt GUI interaction smoke tests are included, but **skipped** here because PySide6 is not available in the offline build environment.
- Static Python compilation passed. Actual graphical interaction, real SXM/GWY comparison and scientific algorithm parity must be tested on Ubuntu with the real experimental files.
