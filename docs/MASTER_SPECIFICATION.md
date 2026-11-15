# SPM Modular Studio — Master Development Specification

**Document type:** Technical requirements / implementation prompt (*cahier des charges*)  
**Status:** Specification only; no application is implemented by this document  
**Target platform:** Ubuntu/Linux desktop first; keep cross-platform paths and packaging where practical  
**Primary objective:** A fast, clean SPM image browser with a **small, stable core** and analysis tools added as **independent modules**.

---

## 0. Instructions to the implementing developer / AI

You are building a maintainable scientific desktop application for scanning probe microscopy (SPM: STM, AFM, KPFM and related methods). The user works primarily with Nanonis `.sxm` and Gwyddion `.gwy` data, analyses channels such as Z, Bias/CPD, current, frequency shift and excitation, and needs publication-quality output.

**Read the supplied source projects before modifying or reusing them.** Preserve the scientific behavior of existing algorithms unless a change has been identified, justified, tested and documented. The end result must be an actual working Python package, not mockups or pseudocode. This specification defines the required product; it does not certify existing scientific code as correct.

**Top priority: resist overengineering.** The application is not a replacement for Gwyddion, a workflow server, an IDE or a giant all-in-one analysis program. It is a responsive image preview and module launcher with consistent data, processing, visualization and export services. Modules should be installable, replaceable or removable **without editing the main window or the core**. Do not carry over the old GUI wholesale. A new feature should almost always require editing only that module and, at most, a versioned shared API.

Rules:

1. Keep the default dependency set and startup path small. Load heavy scientific and molecular packages only when their modules are opened.
2. Use one GUI toolkit: **PySide6**. Do not embed a second Tkinter application into Qt. For legacy code, use a documented compatibility subprocess until porting is verified.
3. Never load a whole folder of full-resolution images, create Matplotlib figures for every thumbnail, or repeatedly reread the same image after a style-only change.
4. The UI must stay responsive while loading, analysing or exporting. Offer live progress/logs and cancellation.
5. Separate **raw data**, **processed data**, **display style**, **physical geometry**, **analysis results** and **export settings**.
6. Ensure preview and final export use the **same transformations, coordinates, channel selections and styling definition**; only output resolution/format may differ intentionally.
7. Do not silently flip images, invert Z, substitute another channel/direction, make up missing metadata, fabricate invalid formats or recalculate piezo calibration into already calibrated coordinates.
8. Preserve independent module tests, outputs and algorithms. Remove duplicated *infrastructure*, not scientific features.
9. Write concise professional English code comments/docstrings explaining intent, non-obvious physics, units and assumptions. Avoid filler, changelog-like inline comments and references to AI.
10. Do not call this complete merely because synthetic tests pass. Include a documented real-data validation checklist and explicitly report unverified behavior.

## 1. Source inventory and migration decisions

The following inventory was made from the files actually supplied with this project. All supplied Python files, including Python files inside the three ZIP archives, were statically parsed (119 Python files; no syntax errors). Relevant implementations and documentation were inspected; **full end-to-end GUI and instrument validation was not possible without the user's experimental data/hardware and missing optional packages**. A targeted selection of 27 `spm-multiframe` synthetic/unit tests passed in the review environment.

### 1.1 Supplied loose Python files

| Source | What it does | Decision |
|---|---|---|
| `ImRes_RC5_v02.py` | Historical batch SXM plotting: Z, excitation, Bias, torsional frequency shift and torsional excitation; plane/line correction and metadata panel. | **Reference / replace** with a configurable image-report module using the common reader and exporter. Do not port its hard-coded figures and file assumptions as the new foundation. |
| `ImComp_RC5_v02.py` | Recursively gathers scan files, calls `ImRes_RC5_v02.create_figure_for_file`, adds SXM piezo X/Y/Z calibrations to figure metadata and produces folder PDFs. | **Retain the useful workflow** as an optional Batch Scan Report module; move file paths and report layout into GUI/module settings. |
| `lattice_analysis.py` | Independent profile peak-spacing, lattice-angle and Gwyddion FFT reciprocal-vector analysis with detailed plots/CSVs. | **Keep** as a separate Real-space / FFT Lattice module. Replace terminal questions by declarative GUI parameters while preserving all calculations and export tables. |
| `amp_calib.py` | Connects to a Nanonis TCP endpoint, reads/changes PLL amplitude, Z controller, drift compensation and PLL calibration. | **Do not auto-import or auto-run.** This is **instrument control**, not offline image analysis. Archive in a separate optional hardware tool area, disabled by default; port only with explicit safety controls and testing on the intended instrument. |

Specific legacy concerns: `ImRes_RC5_v02.py` globally assigns deprecated NumPy aliases, applies a hard-coded topography sign inversion, prints extensive debugging information, creates a figure twice, and contains a placeholder `.nhf/.nid` reader with assumed dimensions/data. These are **not** acceptable defaults. Preserve the old report's intended content but replace its fragile input/rendering infrastructure.

### 1.2 `spm_image_selection_gui_v054_physically_informed_molecule_placement.zip`

This is **the main functional reference, not the base application to keep**.

**Reuse/reimplement the valuable pieces:**

- `io/{nanonis_reader,gwyddion_reader,readers}.py`: source-format readers, channel discovery, forward/backward handling and error reporting, after correctness comparison with the multiframe reader.
- `models/data_model.py`: conceptual separation of `ScanFile`, `ChannelData`, `ChannelStyle`, processing steps and style options.
- `processing/{gwyddion_tools,pipeline}.py`: non-destructive plane/line leveling, row alignment, scar correction and processing history. Do not claim numerical identity with Gwyddion without testing.
- `rendering/{ranges,units,colormaps,renderer}.py`: sigma, percentile, robust MAD, manual/full ranges; SI conversions; colormaps; labels/colorbars/scale bars. Retain the behavior, but design a much faster interactive renderer.
- `profiles/profile_manager.py`: STM/KPFM/Multipass profiles and independent per-channel styles.
- `export/{exporter,paper_presets,composer}.py`: export naming, dimensions, DPI, font/colorbar/border controls, PNG/PDF/SVG/JPG, 2/4-panel compositions and JSON provenance.
- `Unibasel_theme.json` and `gui/theme.py`: editable light/dark color tokens and fonts; significantly simplify the visual/stylesheet implementation.
- `scripts/script_registry.py`: the **idea** of automatic discovery, manifest/metadata and adding user scripts independently of the core.
- Bundled functional tools: flake height, CPD histogram, molecule/lattice overlay, physically informed molecule placement.

**Do not reproduce these limitations:**

- `gui/main_window.py` (approximately 1,000 lines) and numerous large dialogs make the original UI too coupled and hard to maintain. Rebuild with small widgets/controllers and a compact inspector.
- The preview uses `render_channel` → Matplotlib figure → PNG in `BytesIO` → `QPixmap`, for each image tile and on grid refresh. **Replace with direct Qt image rendering**; retain Matplotlib only for scientific graphs and final figure export.
- Ordinary scripts run via blocking `subprocess.run(..., capture_output=True, timeout=600)` from the main-window handler. **Replace with asynchronous `QProcess`/workers** and line-by-line visible stdout/stderr.
- The `ChannelData.data()` implementation can silently return forward data when backward was requested (and vice versa). **Do not silently substitute** a missing direction in the new core.
- The script plugin API passes the entire main window into `create_tool(main_window, context)`, binding modules to GUI internals. **Replace with a small documented module context/host API**; keep a compatibility bridge only for migration.
- The old 2/4-panel composer builds raster RGBA composites, including when producing PDF/SVG. In the new application, **PDF/SVG should preserve vector text/lines where possible**, not wrap a large bitmap unnecessarily.
- `.nhf/.nid` support is partial/unverified. Do not advertise these as reliable until a real reader with fixtures is available.

**Bundled modules to retain:** `flake_height_analysis`, `kpfm_cpd_histogram` (wrapper/ideas, not its older duplicate algorithm), `molecule_lattice_overlay`, and `physically_informed_molecule_placement`. The latter has optional RDKit/ASE/Pymatgen/PubChem functionality; none of it belongs in the core startup dependency path. Keep the scientific limitation explicit: ranked geometrical/chemical candidates are **not adsorption-energy or DFT predictions**.

The archive includes a reported prior validation of 29 passed and 1 skipped tests in `TEST_RESULTS_v054.txt`. Treat that as *historical evidence*, not a fresh verified test result.

### 1.3 `CPD HISTO.zip`

- `cpd_histogram_analysis.py` (8,648 lines): potentially more complete standalone value-range-mask / histogram / Gaussian fitting and comparative export code than the **5,348-line copy** bundled in the GUI. Both identify the same internal program version (`2026.07.15-mask-derived-raw-fit-v9`), so **do not infer chronological correctness from the version string**.
- `kpfm_edge_analysis.py` (2,964 lines): line-profile topographic-edge/CPD-residual widths and 2-D topography-gradient vs CPD correlation. **Keep as its own module.**
- `README_CPD_HISTOGRAM.md`, `README(3).md`, `KPFM_edge_analysis_development_prompt(1).md`, `requirements_cpd_histogram.txt`: scientific behavior/documentation/reference requirements.

**Important:** the standalone CPD histogram file has multiple repeated top-level functions/classes, including `GwyMaskEditor`, `analyse_one_file_with_masks`, `plot_mask_comparison_with_image`, and `FinalComparisonExportEditor`. Python uses later definitions, and an apparent original `main()` appears before appended definitions. Before refactoring, identify exactly which implementations run at runtime and what later overrides change. Make behavior-preservation tests and remove duplicates only afterward. Never choose the shorter GUI copy simply because it is shorter.

Avoid importing the Tk-based mask editor into the Qt event loop. Port the selected interaction to Qt using reusable ROI/value-range tools, or temporarily isolate the original tool in its own subprocess with its real logs and outputs linked back into the GUI.

### 1.4 `spm-multiframe-v0.1.2.zip`

The **most useful quantitative reference** for scan geometry, cross-scan consistency, drift and stacking. It already has an appropriately separated package structure:

- `io/`: SXM/GWY readers, metadata and atom-tracking hints.
- `geometry/`: physical pixel coordinates, acquisition timing, transforms and common-region overlap.
- `analysis/`: drift fitting, registration, FFT, lattice and uncertainties.
- `stacking/`: resampling and multi-frame combination.
- `plotting/`: physical scale bars/diagnostics/reports.
- `gui/common_region_preview.py`: per-scan included/excluded and common-region visualization.
- `cli/`: `spm-drift-lattice`, `spm-stack`.
- `tests/`: synthetic geometry, drift, lattice, overlap, stacking, timing and atom tracking.

**Keep this code as an independent optional analysis dependency or adapt its engines behind narrow interfaces. Do not copy its entire dependency tree into the always-loaded GUI core.** Respect its physical-coordinate model, acquisition time, 0°/90° and up/down scans, physical overlap masks, and shared geometry across channels. Keep `B = G^{-T}` for Gwyddion-style FFT spatial frequencies (cycles/length), i.e. no invented `2π` factor.

For lattice fitting, test primitive-basis reduction and the reported risk of one vector being about **2× too long**; explicitly compare the same physical region in Z versus Δf_t. The source contains Gauss reduction/FFT candidate logic and related unit tests, but the previously observed real-image discrepancy remains a **regression case that must be checked, not declared fixed**.

For stacking, preserve the rule that the *same physical sample area* is calculated using scan origin, size, angle, raster timing and estimated drift; the crop must not be merely the same pixel rectangle in each image. Maintain scan inclusion/exclusion and coverage warnings, uncertainty and contribution-count outputs, and provenance. No default non-rigid warp or physically unjustified alignment.

**Provenance of inspection:** 27 targeted multiframe tests (geometry, synthetic lattice/drift, overlap, stacking, timing, atom tracking) passed in the review environment. PySide6, nanonispy and gwyfile were not installed there, so complete GUI and experimental-file tests remain pending.

### 1.5 Consolidation / de-duplication decisions

- **One** shared scan-data model and coordinate convention; adapt the best existing reader rather than maintain multiple inconsistent SXM parsers indefinitely.
- **One** fast preview renderer and **one** publication export engine consuming the same data/style specification.
- **One** central, non-destructive processing pipeline for general 2-D image corrections.
- **One** registry of available modules; no manual addition to application menus when a module is installed.
- **One** CPD histogram module based on a behavior-tested selection of the two supplied code versions.
- **Two separate lattice workflows:** manually measured profile/angle/FFT analysis (`lattice_analysis.py`) and automatic image-based FFT/lattice/drift analysis (`spm-multiframe`). They answer related but not identical questions and must not be conflated.
- **No** default hardware control, fake `.nhf/.nid` decoder, mandatory molecular modeling stack, duplicate Qt/Tk GUI integration or entire legacy GUI embedded within a new wrapper.

## 2. Product definition

**Working name:** SPM Modular Studio (renameable without affecting code architecture).

The everyday user workflow should take very few actions:

1. Open or drag in a `.sxm`/`.gwy` file, several files, or a dataset folder.
2. Immediately see a fast grayscale **Z** preview (or the first genuinely available channel), file metadata and an unobtrusive list/grid of available files.
3. Switch channel, direction, processing preset or colormap; see the preview update **in place** without blocking or rereading the file unnecessarily.
4. Pick an analysis module from a searchable, compact Tools area, adjust only its relevant settings and run or preview it.
5. See logs and progress **inside the app**, not in a missing external terminal. View numerical outputs, plots and generated images in an integrated results area.
6. Export the current view, selected channels, batch report or analysis plots using shared publication profiles; return to the same session later.

A novice should be able to install a new compatible `.py` module by dropping it into the Scripts folder or using **Import module…**, with **no edit of main-window code**. An arbitrary standalone Python script should still be runnable in *legacy mode*, although it cannot have fully integrated controls/live overlay without adopting the documented module API.

## 3. User interface: deliberately minimal

Use a single main window rather than a startup wizard and numerous nested/modal dialogs. Suggested layout:

```text
┌─────────────────────────────────────────────────────────────────────┐
│ SPM Studio   Open ▾   Dataset …   [profile ▾]    Export   ⋯        │
├─────────────────┬───────────────────────────────┬───────────────────┤
│ FILES / TOOLS   │                               │ INSPECTOR         │
│ Search …        │        IMAGE / PLOT           │ Channel   ▾       │
│ Scan 001        │        live preview           │ FWD / BWD          │
│ Scan 002        │        zoom / pan / ROI        │ Processing ▾      │
│ Scan 003        │                               │ Display ▾         │
│ ──────────────  │                               │ Module settings   │
│ Tools           │                               │ (contextual)      │
│ ▸ Histogram     │                               │                   │
│ ▸ Edge          │                               │                   │
│ ▸ Lattice       │                               │                   │
│ ▸ Stack         │                               │                   │
├─────────────────┴───────────────────────────────┴───────────────────┤
│ Results / Log  ▸  progress, latest outputs, errors, cancellation     │
└─────────────────────────────────────────────────────────────────────┘
```

This is an interaction guideline, not a requirement to fill the interface with frames, borders or visible buttons. Aim for spacious alignment, neutral dark/light palettes, good text contrast and small unobtrusive controls.

**UI rules**

- Default to **one large central image preview**, not a page of individually rendered Matplotlib thumbnails. An optional virtualized filmstrip/grid may show many files/channels.
- Files and Tools can be tabs in the left sidebar; both searchable. Active module highlighted. Hide advanced controls until requested.
- Right inspector is **contextual**: basic Channel/Direction, Processing and Display; selecting a module reveals *only* its declared parameters.
- Bottom Results/Logs drawer is collapsed by default but expands automatically for errors/running modules; preserve scroll and allow copy/save/filter.
- Support mouse-wheel zoom centered on cursor, pan, fit-to-screen, pixel-value cursor readout, physical coordinate readout, optional rectangle/line/point ROI and overlay layers. Preserve scale/rotation after switching channels of the **same acquisition**.
- Keyboard shortcuts: `Ctrl+O` open, `Ctrl+I` import module, `Ctrl+E` export, `Ctrl+R` run, `Esc` cancel current selection or close transient controls, plus documented shortcuts for fit/reset and log drawer. Do not conflict with Ubuntu window-manager shortcuts unnecessarily.
- Add an obvious **Open Scripts Folder** and **Open Customization Folder** action in the application menu.
- Support high-DPI and multi-monitor desktop layouts; avoid fixed giant button/card sizes and tiny text on fractional scaling.
- Remember window geometry, last opened folder/file/channel, selected module, inspector state, recent analysis/export profiles, *without* an intrusive startup dialog.
- Make the app useful offline and never require login, telemetry, cloud services, a database server or internet access.

## 4. Architecture: small core, isolated modules

### 4.1 Non-negotiable separation

- **Core:** file discovery, cached loading, canonical scan data, transforms/units, processing history, rendering API, profile/storage API, module registry and execution/logging.
- **GUI shell:** Qt widgets and user interactions; it delegates all calculations to services/modules. No scientific algorithm embedded in `main_window.py`.
- **Modules:** specialized analysis or overlays; each independently testable and removable.
- **Customization:** themes, colormaps, processing profiles, plot/export presets, key bindings (if needed), general preferences.
- **Runtime state:** cache, temp data, session files, logs and per-run results; never mix with source code.

### 4.2 Recommended project tree

```text
spm-modular-studio/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── .gitignore
├── src/spm_studio/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py
│   ├── core/
│   │   ├── models.py             # scan/channel/ROI/geometry contracts
│   │   ├── io.py                 # format adapters and lazy loading
│   │   ├── processing.py         # pure image processing chain
│   │   ├── display.py            # fast Qt-ready preview data
│   │   ├── export.py             # shared figure/image exports
│   │   ├── presets.py            # versioned profile validation
│   │   ├── registry.py           # module discovery/metadata
│   │   └── jobs.py               # nonblocking execution, logs, cancel
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── image_view.py
│   │   ├── browser_panel.py
│   │   ├── inspector_panel.py
│   │   ├── module_panel.py
│   │   └── log_panel.py
│   ├── modules/
│   │   └── README_SCRIPT.md      # required AI-ready module template
│   └── resources/
│       └── icons/                # small built-in assets only
├── scripts/                      # maintained, installable modules
│   ├── README_SCRIPT.md
│   ├── flake_height/
│   ├── cpd_histogram/
│   ├── kpfm_edge/
│   ├── lattice_measurements/
│   ├── batch_scan_report/
│   ├── molecule_lattice_overlay/
│   ├── molecule_placement/
│   └── multiframe_drift_stack/
├── customization/
│   ├── README_CUSTOMIZATION.md   # AI-ready customization template
│   ├── themes/
│   │   ├── default_dark.json
│   │   ├── default_light.json
│   │   └── unibasel.json
│   ├── profiles/
│   │   ├── STM.json
│   │   ├── KPFM.json
│   │   └── Multipass.json
│   ├── export_presets/
│   │   ├── single_column.json
│   │   ├── double_column.json
│   │   └── custom.json
│   ├── colormaps/
│   └── examples/
│       └── README_EXAMPLES.md
├── tests/
│   ├── fixtures/
│   ├── test_readers.py
│   ├── test_geometry.py
│   ├── test_processing.py
│   ├── test_preview_export_parity.py
│   ├── test_registry.py
│   └── test_module_integration.py
└── docs/
    ├── MODULE_API.md
    ├── DATA_COORDINATES.md
    ├── EXPORT_FORMAT.md
    └── MIGRATION_NOTES.md
```

The tree represents responsibilities, **not a mandate for dozens of one-class files**. Merge tiny files where that reduces complexity. Do not create a nested framework inside every module. Store installed/default assets with the package and store user edits **outside installed site-packages**, using standard per-user application directories (e.g. `~/.config/spm-studio/` for editable preferences/themes/modules, `~/.cache/spm-studio/` for thumbnails, `~/.local/share/spm-studio/` for retained user assets). Allow portable/exportable copies under the project `customization/` and `scripts/` folders. Document precedence: user override → project override → packaged default.

**The application must not depend on its current working directory.** `pip install -e .`, running from elsewhere and later normal package installation must behave consistently.

### 4.3 Dependency policy

- **Core:** Python 3.11+, PySide6, NumPy, and the minimum parser required for reliable `.sxm` browsing. Use SciPy only in processing requiring it; scientific plotting through lazy-imported Matplotlib.
- **GWY:** lazily enable `gwyfile` or a verified reader and show a useful diagnostic if missing.
- **Multiframe:** keep scikit-image, shapely, pandas, tifffile and related packages in the module's optional dependency group.
- **Molecular placement:** keep RDKit/ASE/Pymatgen and network-based structure retrieval optional; load only on demand.
- **Old Tk workflows:** separate compatibility mode or tested Qt port. Never introduce an always-imported Tk backend.
- Prefer existing stable scientific libraries; don't build a custom widget framework, plugin dependency solver, script IDE, multiprocessing framework or GPU backend without a measured need.
- Start with a simple Python virtual environment and editable installation. Provide an executable CLI entry point such as `spm-studio`.

## 5. Canonical scan and processing model

A module must receive a stable, documented view of the selected data, not private GUI widget instances.

A `Scan`/`Channel` concept must expose:

- Stable scan identity and original absolute file path; original extension and readable metadata.
- Available *actual* channel names, units and forward/backward traces.
- Raw immutable numerical arrays, invalid-pixel mask and correct shape.
- Scan range, center/offset, scan angle, slow-scan up/down direction and (when available) acquisition timing and instrument calibration.
- Physical sample coordinates and a clearly documented pixel-to-physical transform; indicate when **only relative coordinates** are trustworthy.
- Explicit unit conversions and direction selection; missing metadata remains `None`/unknown with a warning, not a guessed fact.
- Optional read-only or copy-on-write processed array with ordered processing steps.

Scientific requirements:

1. For a given file, normalize the display to one canonical physical orientation **once**, based on tested metadata conventions. Keep forward/backward choice distinct from up/down raster direction and scan rotation. Do not apply a second flip in individual modules.
2. Do not conflate a 180° sample rotation with a horizontal mirror; test with asymmetrical calibration images and 0°/90° scans.
3. Preserve underlying data in SI units; perform display-unit conversions only through explicit shared helpers. Preserve amplitude sign unless the user deliberately chooses an inversion operation.
4. Treat different channels of the same scan as co-registered only when valid metadata support that assumption. Refuse or explicitly warn before aligning mismatched shapes/extents.
5. Support source metadata/piezo calibration inspection and exports; do not apply a second XY scale factor to already calibrated `SCAN_RANGE` values. Allow separately recorded user calibration factors with provenance and clear units.
6. Missing/partial scan lines remain masked/NaN instead of being quietly fabricated.
7. Detect duplicate `.sxm`/`.gwy` versions of the same acquisition without silently discarding access to the other source. Prefer source choice appropriate to the task (e.g. full SXM timing for drift, GWY processing for edited images).
8. Support `.sxm`/`.gwy` first. Add `.nhf/.nid` **only after real fixtures establish valid format handling**.

Processing must be an ordered, non-destructive pipeline with individually enabled steps and parameters. Candidate built-in operations: plane subtraction, mean-plane leveling, polynomial line correction, mean/median row alignment, horizontal scar correction, robust background adjustment and manual invert. The former GUI's `facets_upward` heuristic should be labeled separately from an exact Gwyddion equivalent. Save the steps in profiles and in provenance. Allow module-specific processing without silently changing the global active image.

## 6. Fast preview and real-time interaction

### 6.1 Rendering path

- **Interactive SPM image:** downsample appropriately for viewport → apply selected finite range/LUT → generate QImage/QPixmap (or a similarly fast Qt-native path) → draw annotations in an overlay layer.
- **Plot/figure:** use Matplotlib only when a module explicitly needs axes/curves/errors or final figure composition, and load it lazily; do not make a new Matplotlib canvas for each raw-image thumbnail.
- Render only visible thumbnails (virtualized list/grid) and the active full preview. Favor one main image surface with overlay objects, not hundreds of independent image widgets.
- Use bounded LRU caches keyed by source file identity/mtime, channel, trace, geometry, processing-parameter fingerprint and preview resolution. **Style-only changes** (colormap, labels, font) should not recompute filtering or reread the file.
- Keep full-resolution arrays out of duplicate tile instances; release cached results when the memory limit is reached. Expose an optional cache limit and “Clear cache”.
- Use background loading/processing and cancellation, with generation IDs so stale responses cannot overwrite the newest preview after rapid switching.

### 6.2 "Real time" meaning

- Colormap, range limits, annotations, border/colorbar and viewport changes should update immediately or within a short UI debounce while dragging.
- Lightweight preview processing should update after a brief debounced parameter change; show a temporary lower-resolution result during interaction and full resolution when stable.
- For computationally expensive modules (large fits, segmentation, multiframe drift/stacking), **do not rerun full computations on every keystroke**. Offer an explicit Run/Update action; if the module implements an optional cheaper `preview()` operation, show that automatically. Stream partial outputs/progress when scientifically meaningful.
- Selecting an analysis result plot should display it in the central image/plot viewer without needing to open the exported file in another program.

### 6.3 Performance targets (to verify, not promise blindly)

On a documented representative Linux workstation with warm filesystem caches and typical 256–1024 px scan previews:

- UI input/scroll/zoom should remain responsive and not block for a full dataset load.
- Simple colormap/range adjustments should visually update in approximately **100–200 ms** where practical.
- First preview should be shown before a recursively opened large dataset is fully indexed.
- Indexing a folder should perform metadata-first/lazy data loading; do not decode every channel of every file to build the file list.
- Full-resolution export and heavy analyses may take longer but must show progress and remain cancellable.
- Record cold-start time, first-preview time, repeated-preview time, peak resident memory and output parity in repeatable benchmarks. **Tune after profiling rather than adding premature complexity.**

## 7. Module system: easy to add, safe to maintain

### 7.1 Two import experiences

**A. Quick import — arbitrary script (compatibility mode):**

- Use Import module… to select a `.py` file or a folder, optionally copy it into the user Scripts directory.
- List it under Tools automatically with its filename, dependencies/requirements warning if known, and a minimal Run interface.
- Launch asynchronously in a subprocess, passing a documented context JSON path and a dedicated output directory. Show stdout/stderr in live logs and capture exit code.
- Legacy `input()`-based scripts must not silently hang. Prefer explicit argument capture/terminal mode or mark “needs interactive terminal”; if a terminal is required, still capture/support logs if possible. Do not pretend a legacy script supports native live image previews or noninteractive parameters when it does not.
- Importing/discovering scripts must **never execute their top-level code**.

**B. Native integrated module (recommended):**

- A folder containing `module.json` and `module.py` (and optionally algorithm files, tests and a module README) is detected at startup or when Refresh modules is clicked.
- An unchanged manifest is enough to render parameter controls and register a module; **no manual edit of `main_window.py`**.
- Parameter definitions support simple kinds: integer, float with physical unit, bool, string, choice, file, folder, channel, direction, color, region or image selection. Keep one common panel renderer; custom widgets are an explicit *advanced* extension point.
- The module receives a typed context/snapshot, validated settings, output directory and host services for data, progress, cancellation, overlays and results. Modules must not access main-window private fields.
- Native analysis functions should be pure or near-pure. Background computation runs in a worker/subprocess, never blocking Qt. Native interactive overlays may use small controlled Qt integration hooks, but no module should replace the entire app shell.
- Stable result types: numerical scalars/tables, image arrays with units/geometry, plot/figure specifications, SVG/PNG/PDF exports, geometry overlays and messages. The central viewer can display these; generated files remain accessible from a Run results list.

### 7.2 Example `module.json` (illustrative v1 contract)

```json
{
  "api_version": "1.0",
  "id": "example_profile_analysis",
  "name": "Example profile analysis",
  "version": "1.0.0",
  "description": "Measure a distance profile on the selected channel.",
  "category": "Analysis",
  "entrypoint": "module:run",
  "mode": "analysis",
  "requires": ["numpy"],
  "inputs": ["scan", "channel", "roi_line"],
  "parameters": {
    "smooth_window": {
      "type": "integer", "label": "Smoothing window", "default": 5,
      "min": 1, "max": 101
    }
  }
}
```

This is a **design contract for the implementing developer**, not an existing file from the supplied projects. Finalize and version its exact schema and corresponding Python API **once**, document it and test backward compatibility. Avoid a huge plugin framework.

### 7.3 Execution, logging and safety

- Use a Qt `QProcess`-based job runner (or equivalent nonblocking process manager) for independent/legacy analysis. Start Python unbuffered and consume stdout and stderr incrementally; permit UTF-8 logs, progress, warnings, errors and result-file notifications.
- For fully integrated modules, define a tiny newline-delimited JSON event protocol or equivalent typed signals: `log`, `progress`, `image`, `plot`, `table`, `result_file`, `error`, `finished`. Keep standard text stdout usable even if a module does not emit structured events.
- Show elapsed time, active run state, cancellation, final status and expandable traceback. Save run metadata and a `run.log`. Never truncate an exception into an unexplained generic message.
- Cancellation should request graceful stop first and then allow process termination after a timeout; clean up temporary files safely and mark partially written results. Use unique per-run folders so simultaneous or repeated runs cannot collide.
- Catch missing optional dependencies *per module* and provide a precise install command instead of crashing the application.
- Script import is not a security sandbox: running an unknown `.py` can access files, network and devices with the user's privileges. Warn before first execution of a non-bundled script.
- Mark modules that communicate with instruments as `instrument`; hide/disable them by default. Require explicit enablement, target address confirmation, interlock/state restoration and hardware-specific review. **Never autoconnect at import/startup.**
- No silent global monkey-patching of NumPy aliases or Matplotlib backends from arbitrary modules during discovery.

### 7.4 Migration rule

For every existing tool, first create an adapter calling the **unchanged scientific functions** through explicit parameters. Add fixture-based baseline comparisons of old vs new numeric outputs and representative figure layout. Refactor underlying algorithms only in a separate reviewable step, with tests showing no unintended changes. Preserve legacy CLI use where possible.

## 8. Standardized images, graphs and exports

All modules must use a common **ImageStyle / FigureStyle / ExportPreset** definition rather than invent their own fonts, figure size, colorbar scale or save calls. The user may override styles per channel, per image, per analysis plot or through a saved profile. Visualization preferences must not silently alter scientific numerical results.

### 8.1 Shared image controls

- **Processing:** ordered non-destructive steps, enabled state, parameters; preview/export parity.
- **Image range:** full, percentile, sigma, robust-MAD, manual min/max; NaN/invalid color; gamma/log scaling only if explicitly chosen and valid.
- **Color:** built-in and imported colormaps, grayscale including invert, optional channel-family defaults; shared and per-channel colormap assignments; special handling for Bias/CPD contrast without hard-coded incorrect polarity.
- **Units:** SI base units, preferred display units and automatic prefixes (m/nm/pm/Å, V/mV, A/pA, Hz/kHz, etc.). Numeric colorbar values and labels must reflect the same conversion as the plotted data.
- **Colorbar:** below/left/right/hidden; positioned flush/aligned where requested; left min, centered channel label/unit and right max where appropriate; editable text colors and border.
- **Physical scaling:** exact non-stretched aspect ratio, physical axes/ticks or optional scale bar; real X/Y extents, correct image orientation, exact ROI coordinates, adjustable bar length/location/thickness/font/contrast.
- **Typography:** family, font sizes for axes, ticks, colorbar, labels, annotations, legends and titles; configurable decimals and scientific notation.
- **Figures:** width and height in physical publication units (inches/mm), DPI, padding/margins, background/transparent, border thickness, figure legend policy and multipanel spacing.
- **Plot styling:** consistent line widths, colors, points, fitted curves, confidence/error bands, labels/ticks/legend placement and export metadata. Preserve module-specific necessary scientific annotations.
- **Export:** PNG, PDF, SVG; JPG optional; CSV/JSON for numbers and NPY/TIFF (or verified GWY writing where available) for raw/processed quantitative arrays. Format availability must be accurate.

### 8.2 Profiles and precedence

Provide manageable profiles for **STM**, **KPFM**, **Multipass**, and user-created modes, migrated from the prior `ProfileManager` behavior. Separate:

1. **Processing profile:** channel selection, trace, ordered data operations.
2. **Image style:** contrast, colormap, axis/scale bar, colorbar, units.
3. **Figure/export preset:** paper width/height, DPI, typography, margins and output formats.
4. **Application theme:** only GUI colors, density and fonts; does not automatically alter exported scientific figures.

Allow users to save, load, duplicate, import, export and delete custom presets with simple GUI actions. Changes to the current view must not rewrite defaults unless the user explicitly selects Save profile. Support "Apply to selected", "Apply to all channels in this scan" and optionally "Apply to dataset" as explicit actions, not automatic propagation. Presets are human-readable **versioned JSON** and validated on load, with graceful fallback for unknown keys/missing fonts.

### 8.3 Export invariants

- Default output path can be the current dataset's `selection/` directory, with configurable global output folder; use meaningful subfolders by export preset and analysis run when appropriate.
- Preserve relative source paths or unique source IDs in collision-safe filenames. Do not overwrite originals or previous outputs silently.
- Every export records source file/channel/trace, source hash or fingerprint, physical geometry, operations/parameters, module/version, display and export profile, units, time and warnings.
- Data and display outputs are distinct: **NPY/TIFF/CSV numerical arrays are not clipped by the display colormap**, unless the export is explicitly described as a display image.
- Figures generated by standalone analyses must go through the same shared figure styling/export utilities. Avoid modules calling arbitrary `plt.savefig` with unrelated hard-coded fonts/DPI in their integrated execution path.
- Preserve genuine vector contents in PDF/SVG where possible. If image pixels are raster data, embedding them as rasters is fine; keep vector text/axes/scale bar/overlays as vector objects when feasible.
- A preset used in preview at lower resolution should produce the **same orientation, data limits, positions, colors and labels** in full-resolution export; compare programmatically.

## 9. Scientific modules to include

The first complete deliverable must include adapters or ported versions of the relevant supplied analysis scripts, **without claiming all heavy modules are part of the always-loaded core**. Each module gets its own `module.json`, `module.py`/algorithm sources, tests, short README, optional dependencies and clear availability status.

| Proposed module | Based on | Required behavior / migration concern |
|---|---|---|
| **Batch scan report** | `ImComp_RC5_v02.py` + `ImRes_RC5_v02.py` | Batch selectable channels, metadata panel with piezo calibration, PDF overview/report; remove hard-coded directory/plots/placeholder readers. |
| **Flake / island height** | Old GUI `flake_height_analysis` | Forward/backward Gwyddion profiles, terrace/edge height, stripes, line selection, plots and CSV; preserve uncertainty meanings. |
| **CPD / Bias histogram** | `CPD HISTO/cpd_histogram_analysis.py` and old GUI plugin | FWD/BWD/Both, histogram, Gaussian populations, manual/auto peaks, value-range masks and overlay, raw/masked comparisons, optional common export; audit duplicate definitions first. |
| **KPFM edge analysis** | `CPD HISTO/kpfm_edge_analysis.py` | Synchronized topography/CPD lines, 10–90% topographic edge width, CPD residual FWHM, absolute width difference, 2-D gradient/CPD correlation; explicit registration/units and limitations. |
| **Lattice measurements** | Root `lattice_analysis.py` | Real-space Gwyddion profiles/peaks/spacing/trends, angle pairing, manual FFT vectors, uncertainties, comparisons and CSV/PDF outputs. No `input()` in native GUI execution. |
| **Molecule / lattice overlay** | Old GUI `molecule_lattice_overlay` | Calibrated molecule PNGs, manual placement, vector/angle/size overlay, optional feature detection and independent regions; physical scaling, placement/rotation and exported annotations. |
| **Physically informed molecule placement** | Old GUI `physically_informed_molecule_placement` | Optional structures, substrate sites, registration, candidate generation/scoring and reproducible results; only approximate/ranked candidates, **not DFT validation**; lazy heavy dependencies. |
| **MultiFrame drift, lattice and stack** | `spm-multiframe-v0.1.2` | Reuse its independent engines, optional drift estimation, atom tracking hints, physical crop preview, scan exclusion, multi-channel stacking, uncertainty/count maps, lattice diagnostics and source checks. |
| **Amplitude calibration** | `amp_calib.py` | **Do not include in offline default Tools menu.** Optional separate instrument-control extension only following explicit review and safe state-handling tests. |

**Important scientific acceptance cases:** CPD masks retain the same value-to-pixel correspondence after rotation/trace changes; no unexpected inverted Z/colorbar; extrema detection does not systematically miss valid periodic minima; a 90° scan remains geometrically correct; lattice lengths are not confused with reciprocal radial spacing or higher-order harmonics; a stacked preview shows **one physical crop** correctly located across all scan coordinates.

## 10. Customization system

The directory `customization/` must be simple enough that a user can edit JSON files with a text editor or use the app's limited Settings/Profiles controls.

- Use small, typed/versioned schemas; never demand the user modify Python GUI code for theme, colormap, typography or export presets.
- Retain the useful University of Basel palette and named font tokens from `Unibasel_theme.json`. Ship a simple neutral light/dark default as well.
- Keep display theme independent from image and figure styles. Do not force publication plots into the GUI's dark colors.
- Support custom RGB(A) colormap CSV/text files using floats 0–1 or integers 0–255, matching the prior GUI behavior.
- Validate bad JSON/invalid colors/unavailable fonts with clear warnings and safe fallbacks. Preserve the last known-good settings and offer Reset to default.
- Allow importing/exporting profiles and themes from within the GUI; make the user configuration folders discoverable by a menu action.
- A new module may register namespaced default presets, but must not overwrite user profiles or rewrite global themes.

## 11. Mandatory documentation deliverables

### 11.1 Root `README.md`

Concise, readable, current instructions covering:

- what the application is (and what it is not), supported formats and screenshots if available;
- Linux installation with a virtual environment, exact install/update/run commands and optional dependency groups;
- first use (open dataset → choose channel/direction → processing → module → logs/results → export);
- Scripts, Customization and output folder locations, with how to open them in the GUI;
- the two import modes: arbitrary `.py` compatibility versus manifest-based integrated module;
- how to enable/disable/update/remove modules without editing core code;
- creating/importing Processing, Image, Export and Theme profiles;
- where logs and errors are stored, how to cancel and troubleshoot;
- data orientation/units/processing and scientific limitations, including pending format/hardware validation;
- running tests, minimal troubleshooting and release/version policy.

No advertising language, excessive screenshots, boilerplate or stale commands.

### 11.2 `scripts/README_SCRIPT.md` — **AI-ready module-creation prompt**

This file is an actual copy-paste prompt for another coding AI. It must begin with a very simple, editable section:

```markdown
# WHAT I WANT THIS MODULE TO DO

[USER WRITES THE REQUEST HERE: inputs, analysis, parameters,
expected numerical results, plots, overlays, exports.]
```

After that placeholder, the file must tell the AI precisely how to create a compatible module: API version, minimal folder layout, `module.json` schema, `run()`/optional `preview()` signatures, typed context, channel/ROI/units/geometry access, declarative parameter UI, log/progress/cancellation events, output/result objects, standard figure/processing/export services, dependency declaration, error handling, unit tests, one small README and how to install by copying the folder. Include the smallest working *analysis* module and one optional overlay example, but no giant tutorial. Require the AI to produce **only files belonging to that module**, never patch the main window or core unless the interface itself truly lacks a capability (then explain the gap instead of silently hacking around it).

A user should only need to fill the top request block, send this file to an AI and copy the generated folder into `scripts/`.

### 11.3 `customization/README_CUSTOMIZATION.md` — **AI-ready preset/theme prompt**

This file must likewise begin with:

```markdown
# WHAT I WANT TO CUSTOMIZE

[USER WRITES THE REQUEST HERE: colors, fonts, image styles,
processing steps, colormap, axes, colorbar, figure sizes, etc.]
```

Then provide the supported JSON schemas, precedence, allowed values and units, import destinations, versioning, validation constraints and short examples. Instruct an AI to produce the smallest appropriate customization JSON/CSV file **without modifying Python core**. Distinguish application theme from scientific image/figure export. Mention that unsupported fields must be proposed as explicit API extensions rather than invented keys.

### 11.4 Developer docs

Document one stable Module API with executable examples, one coordinates/orientation/unit convention, one export/provenance schema, and concise migration notes explaining which parts of the old projects were retained, replaced or intentionally retired.

## 12. Tests and scientific quality gates

Minimum automated tests:

1. **Reader tests:** valid/invalid SXM/GWY fixtures, channels/units, missing data, forward/backward, up/down, 0°/90° and source selection; use instrument-specific golden files when supplied.
2. **Geometry tests:** known asymmetric fiducial arrangement, physical pixel coordinates, scale bar, ROI round-trips, correct orientation and no duplicate XY calibration.
3. **Processing tests:** plane/line corrections on synthetic known planes with NaNs; no mutation of raw data; processing-order persistence; no accidental inversion.
4. **Preview/export parity:** same physical field, valid pixels, contrast bounds, label units and ROI positions for preview and export at different pixel resolutions.
5. **Registry tests:** add/remove a module without core modification, load metadata without executing Python top-level code, missing dependency reporting, invalid manifest warnings, imported standalone `.py` launching.
6. **Jobs/logging tests:** nonblocking streamed stdout/stderr, progress, cancel, exception traceback, nonzero exit, conflicting runs and retained run history.
7. **Preset/theme tests:** save/load round-trip, import/export, malformed config, default fallback, explicit scope of Apply to All.
8. **Modules:** baseline comparison with original scientific outputs plus synthetic unit tests and a manual real-data acceptance checklist per module.
9. **Multiframe:** restore its existing tests, check first-order primitive lattice basis, reproduce the 2× vector risk, compare Z/Δf_t consistency, and verify absolute physical crop mapping across shifted/up/down/90° scans with missing overlap.
10. **Performance:** UI responsiveness under rapid channel/style switching and opening a multi-file dataset; repeated preview does not create a new Matplotlib Figure; memory stays within a documented bounded cache policy.

For relevant scientific algorithms, preserve metadata, units, sign conventions and assumptions in both tests and docs. Verify important old vs new result tolerances explicitly; do not change the expected physics merely to satisfy a test. Hardware scripts require independent instrument-side acceptance and state-restoration procedures, **never automated physical execution in CI**.

## 13. Suggested development order / milestones

**M0 — migration baseline and contracts:** inventory existing behavior and effective duplicate implementations, record source versions, specify canonical data and Module API, add fixtures/tests. No giant GUI rewrite at this stage.

**M1 — fast usable core:** PySide6 shell, SXM/GWY selection, canonical geometry, Z preview, channel/trace switch, non-destructive basic processing, compact profile controls, Qt-native rendering, export basics and live log drawer. This must already be pleasant and responsive before adding complex scientific modules.

**M2 — plugins and standardized figures:** declarative manifest registry, Import/Remove/Refresh, compatibility runner, integrated module execution and cancellation, output viewer, shared figure styling, export presets and first simple migrated modules (batch report, flake, lattice measurements).

**M3 — remaining scientific modules:** KPFM edge and CPD histogram, overlays, physically informed placement (optional), multiframe adapter and physical crop preview. Preserve original CLI pathways until module equivalence is verified.

**M4 — polish and validation:** real SXM/GWY test datasets, physical orientation and lattice discrepancy regression, accelerated preview benchmarking, high-DPI clean UI, removal of leftover duplicate code, packaging, README and both prompt templates.

At the end of each milestone, the application should remain installable and functional. Never finish a milestone by leaving half-connected buttons or silently unimplemented modules in the UI. Make explicit what is operational, experimental, or archived.

## 14. Definition of done / acceptance checklist

The implementation is acceptable when all the following are true:

- [ ] The GUI can open a folder or single SXM/GWY and quickly display a correctly oriented Z (or explicitly available substitute) preview.
- [ ] Channel, FWD/BWD, colormap and range changes do not visibly freeze the GUI or require full reloading.
- [ ] A non-destructive processing pipeline, independent image/channel settings and explicit Apply to All work correctly.
- [ ] Scripts can be installed/removed without editing core code; at least one simple new native module works by folder copy alone.
- [ ] An arbitrary legacy `.py` can be imported and run with visible stdout/stderr, even though its native GUI integration may be limited.
- [ ] The user can see logs, progress, results, errors and cancel long-running tasks in the main application.
- [ ] All retained analyses appear under Tools, preserving their intended scientific features and reporting unavailable optional dependencies clearly.
- [ ] Instrument-controlling `amp_calib.py` cannot connect or change an instrument by browsing, launching or importing the offline app.
- [ ] Publication styles, processing profiles, export profiles, GUI themes and custom colormaps can be created/imported/saved as understandable files.
- [ ] Scientific image previews and exports are identical in physical meaning/geometry, and graphs use the standard output styling without erasing required scientific content.
- [ ] Exports preserve numeric data separately from display images, have correct physical bars/labels and include reproducibility metadata.
- [ ] A user can add/patch one module without changing the GUI shell or unrelated modules.
- [ ] A clean `README.md`, `scripts/README_SCRIPT.md`, `customization/README_CUSTOMIZATION.md`, API/coordinate/export docs, tests and an installation command are delivered.
- [ ] Known source uncertainties (CPD duplicate overrides, unverified `.nhf/.nid`, instrument-specific geometry, real-image 2× lattice anomaly) are documented and tested or clearly marked pending.

## 15. Final instructions to the implementing AI

Produce a complete, working, installable source project as a ZIP or repository tree. Start from the smallest viable responsive viewer and add independent modules, rather than creating a heavy monolith that resembles the old selection GUI. Reuse validated source algorithms and scientific logic; modernize wrappers, integration and UI. Keep every module well-organized, with a concise README and practical tests. Provide a short migration report stating for each supplied source **reused / adapted / archived / unverified** and any observed behavior differences.

**Do not conceal gaps**: list any features requiring real Nanonis/Gwyddion examples, optional dependencies or hardware to validate. Do not say a physical issue is fixed solely because a mathematical formula or synthetic unit test looks correct. The governing design principle is:

> **A small, fast, reliable image-viewing core; many optional, independently maintained scientific modules; one shared language for data, coordinates, logs, presets and exports.**
