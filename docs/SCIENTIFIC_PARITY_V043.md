# v0.4.3 scientific workflow audit and acceptance checklist

## Source of truth

The original versions are stored under `legacy_reference/`. The Studio module
architecture is a new implementation, not an automatic import of legacy GUI
and processing functions. A matching file name is *not* proof of algorithmic
or visual equivalence. The tests below are synthetic, not experimental
validation with SXM/GWY acquired on the instrument.

## CPD histogram — corrected final figure

Original source: `CPD HISTO.zip/CPD HISTO/cpd_histogram_analysis.py`,
`FinalExportConfig`, `_draw_final_comparison_figure`, and
`plot_mask_comparison_with_image` (final v11 override).

Previous Studio v0.4.2 behavior:

- The `...mask_comparison_with_masked_image` file contained **only one image**
  of the selected analysis channel, plus the histogram.
- The analysis snapshot contained only the selected scan channel. Thus the
  code was unable to show raw topography together with raw Bias.
- Existing tests checked the export name and dimensions but not the identity
  and number of image panels. These tests falsely suggested plot parity.

v0.4.3 behavior:

- **Independent Topography, raw Bias and colored masked-scan image panels** in
  a left-hand vertical stack, with the common comparison histogram spanning
  all rows on the right, matching the original plot's overall geometry.
- Each raw image is read from the **actual chosen scan channel**, not copied
  or relabeled from the analysis channel. Available channels are selectable
  directly in Tool settings. Topography and Bias can have different pixel
  counts because they are independently rendered (not subtracted/overlaid).
- Preserves the existing mask-based Gaussian fits and percentages, shared
  publication style, independent panel titles, optional color scales,
  per-panel colormap overrides, an optional 180-degree legacy display rotation,
  a physical scale bar, PNG/PDF export, and same output stem.
- If a requested channel does not exist, Studio logs a warning and omits that
  panel rather than inventing its data. Choose the channel from the dropdown.
- The combined figure's mask data and histogram bins are not rotated, only the
  displayed scan images, and value masks remain restricted to the chosen ROI.
- Output remains in `SPM_Studio_Results/<source>/<run>/` beside the input scan.

Remaining differences from legacy (do **not** claim full parity):

- The legacy application contains an extensive final comparison *live editor*
  for legend placements and contents, pairwise differences, image border and
  value-scale border/gap/color controls, font-by-panel customizations, and
  precise color schemes. Studio's shared preset + manifest controls do not
  expose all those options yet.
- Native `.gwy` mask-channel export / round-trip and the old multi-stage mask
  editor/advanced Gaussian error analysis remain incomplete.
- Matplotlib's output and source image orientation must be compared with
  a known asymmetrical fiducial from the instrument. The export's
  `Rotate exported images 180°` defaults to legacy behavior; it is an
  explicit *display-only* option and never changes the saved masks.

### CPD acceptance on a real sample

1. Select **Bias** (or the actual CPD channel), choose its forward/backward
   direction, then set the real `Z` channel as the Topography panel source.
2. Create masks and optionally restrict their area using the region rectangle.
   Run and open the combined `...mask_comparison_with_masked_image` figure.
3. Check that the topography is topographic Z contrast, the middle image is
   raw Bias (not Z and not the Boolean mask), the bottom image is colored by
   selected mask, and the right histogram uses the same analysis channel.
4. Check the unit labels, orientation, mask pixel counts and fitted means
   against the original program for the **same** file and same trace.
5. With a 180° export rotation, verify an asymmetric structural feature.
   Switch rotation off if your scan viewer's stored-array orientation is
   already correct; do not apply any additional instrument calibration.

## Module-by-module status

| Studio module | Original reference | Core workflow parity |
|---|---|---|
| CPD histogram | Original `cpd_histogram_analysis.py` in CPD HISTO.zip | Restored **three scan panels + mask histogram** and existing Gaussian processing; complete advanced editor/GWY export still not ported |
| Flake height | `spm_image_selection_gui_v054...zip` flake implementation | Multiple drawn and editable lines, separate left/right apparent heights, stripes; no instrument golden-file equivalence yet |
| KPFM edge | `kpfm_edge_analysis.py` in CPD HISTO.zip | Simplified edge/gradient correlation; extensive legacy analysis and fitting remains unported |
| Lattice measurements | `lattice_analysis.py` | Peak-profile and diagnostic FFT only; old full real-space profile, angle, reciprocal-unit-cell cross-check and statistics remain unported |
| Batch scan report | `ImComp_RC5_v02.py` / `ImRes_RC5_v02.py` | Simple batch channel report; original multi-panel metadata-rich per-image layout not retained completely |
| Molecule lattice overlay | SPM image selection GUI | Rectangular molecular footprint only; no molecule geometry or physical placement equivalence |
| Molecule placement | SPM image selection GUI molecule engine | Disabled because its science engine is **not yet migrated** |
| MultiFrame drift stack | `spm-multiframe-v0.1.2.zip` | Metadata-based resampling when explicitly enabled; no full drift estimation, atom tracking or primitive lattice solver |

The three modules that previously loaded all scan channels unnecessarily
(`KPFM edge`, `Molecule lattice overlay`, `MultiFrame`) now request only
selected channels / declared auxiliary channels. Scientific calculations in
these modules have not changed. Their v0.4.2 manifests are upgraded only when
unchanged; local edits are preserved.

## Tests

The new `test_cpd_legacy_layout_v043.py` checks independent selected channels,
separate (even differently shaped) Z and Bias rasters, panel count, mask
image overlays, histogram span, legacy display orientation, output filename,
PNG-only export and physical source channel units.
`test_factory_upgrade_v043.py` verifies v0.4.2 SHA-256 migration preserving
user-edited files. These automated tests cannot prove visual/numerical parity
of the entire original codebase or Qt behavior on Ubuntu/Wayland.
