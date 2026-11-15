# v0.4.0: native interactive analysis and publication settings

The instrument data and the algorithms used in results must still be checked against reference results from the original standalone programs. This release does NOT claim all legacy analysis features are present.

## Flake / island height workflow

1. Open an SXM/GWY scan and select the intended height channel and trace.
2. Select **Flake / island height** in Tools.
3. Click **Line ROI** in the existing main image toolbar and drag across an island/flake. Repeat: drawn lines remain on the scan and their signals appear **immediately** in the Tool settings preview.
4. Use **Undo line** or **Clear lines** above the image to revise the selection. The main program never opens an additional Tk window.
5. In Tool settings choose forward, backward, both, or selected, then choose **Edge decrease run** and optional stripe detection/prominence.
6. Press Run. You receive individual left- and right-edge heights, means by drawn line, and optional stripe spacings with CSVs and figures.

The new edge estimator reproduces the legacy **endpoint to first sustained-decrease maximum** rule conceptually. It does **not** reproduce every older imported Gwyddion text-profile, line alignment, local-background subtraction and uncertainty mode. In particular, the SD between available FWD/BWD traces should not be interpreted as an instrument accuracy estimate.

## CPD histogram masks workflow

1. Select CPD/Bias (or any supported channel), then **CPD / Bias histogram**.
2. The Tool settings panel displays a live decimated histogram. Use **+ New** to create a named range mask. Drag over the histogram to change the selected mask limits, or type exact SI limits. The coloured image overlay updates without changing raw data.
3. Rename, delete or recolor masks; assign 0–8 Gaussians *per mask*. Use **Save masks…** and **Load masks…** for JSON interchange. Per-channel mask choices are also remembered between Studio sessions.
4. Optionally draw a **Rect ROI** to restrict the histogram to a spatial region; the histogram preview follows the ROI. Use the selected scan direction or both traces.
5. Press Run. Generates raw/individual-mask/comparison figures, masks as `.npy`, mask definition JSON, fit CSV and result table. Mask-density comparison uses the same raw-pixel denominator for all masks.

This is an integrated, native Qt workflow **not full parity** with the much larger original CPD Tk tool: there is no complete undo history, draggable two-handle manipulation, direct export of masks into a new `.gwy`, complete original guided Gaussian peak initialization, AIC/BIC/GMM selection, or all custom annotation and plot-composer settings. Those features need separate verified scientific ports.

**Interactive preview is a bounded-resolution *visualization*; the analysis subprocess operates on full-resolution data.** When the mask and image contrast views differ, check raw units/processing and mask values before interpreting the result.

## Global plot and results preferences

Go to **Tools → Scientific plots & results options…** to select:

- A named publication style loaded from `~/.config/spm-studio/customization/plot_styles/*.json`, including bundled Clean publication and Large presentation presets.
- Figure format: PNG only, PDF only, or both. The multi-file batch report exports PDF and/or per-page PNG accordingly.
- Automatically display the first output figure. PNGs display in Studio; PDF-only results open in the system PDF viewer. Turn the option off to leave all result files closed.

**Create editable copy** creates a distinct JSON preset. Edit it with a text editor and reopen the dialog to load changed settings. **Import JSON…** imports an existing validated preset. The profile governs Matplotlib graph font sizes, legend sizes, line widths, DPI, background, axis grid, tick density, scientific tick notation, automatic axes limits, colormap by channel, image interpolation/aspect and colorbar preference. The Qt image viewer/export also uses configured label font sizes, and for *new* channel styles uses applicable built-in channel colormaps; explicitly configured per-channel inspector settings are retained. App theme and scientific publication style remain separate.

All plots produced through native `plot_style` and `save_plot` use the same validated profile; third-party standalone scripts and externally launched tools do not automatically adopt it. Some specialized built-in analysis outputs still require visual parity review.

## Output location

For `/data/20261008_scan0005.sxm`, results are located at:

```
/data/SPM_Studio_Results/20261008_scan0005/20261014_123456_flake_height_abcdef/
```

No result or original scan is silently overwritten. The per-run folder includes the JSON context, snapshot, output files and `run.log` (processing snapshot can be large). This folder can be deleted after confirming that reports and numerical files were archived elsewhere.

## Remaining module migration status

| Module | v0.4.0 status |
|---|---|
| Flake height | Multi-line Qt workflow and separate edge-height outputs restored in a scoped, experimental implementation. Not numerically compared to every old mode. |
| CPD histogram | Named mask editor, image overlay, independent mask Gaussians and comparison outputs restored in an experimental implementation; full legacy parity absent. |
| KPFM edge | Original v0.3.x simplified analysis; still not legacy-validated. |
| Lattice measurements | Simplified FFT/peak analysis; original multi-profile interactive Gwyddion-export workflows are not migrated. |
| Batch scan report | Basic multi-scan implementation with format switching; original six-panel ImComp layout not fully migrated. |
| Molecule lattice overlay | Basic parametric overlay; original editor and placement workflows not fully migrated. |
| Molecule placement | Still unavailable as a validated native module. Original code retained for later migration. |
| Multiframe | Simplified resampling/stacking; original full drift and primitive-lattice algorithms remain unincluded. |

**Scientific acceptance is pending** real SXM/GWY comparisons, multiple pixel geometries, 0°/90° and up/down scans, manual controls, automated Qt tests on Ubuntu Wayland, and reference-data checks. No hardware functions are enabled.
