# v0.4.2 Workflow and scientific parity audit

The v0.4.2 changes aim to preserve a single responsive Qt interface and
manifest-based modules. **They do not establish full numerical equivalence to
all original standalone programs.** Sources remain under `legacy_reference/`.

| Module | Declarative selection/editing | Scientific status vs legacy |
|---|---|---|
| CPD histogram | Rectangle for spatial ROI, histogram value masks with draggable handles, mask undo/delete; live image overlay | Restored named masks, raw/mask Gaussians, fixed-width mask-derived raw fit, raw-normalized comparison, combined masked-image export, PNG/PDF; GWY mask-channel export and advanced fit uncertainty/full layout still missing |
| Flake/island height | Multiple editable lines, selection list/delete/undo/clear, live profiles | Keeps v0.4.1 two-edge analysis; full legacy baseline still not formally established |
| KPFM edge | Line and rectangle with live profiles | Rectangle may average a selected group of scan rows; original advanced edge workflow not fully migrated |
| Lattice measurements | Multiple lines and optional rectangle; per-line peak spacing CSV | Full profile+angle+FFT manual workflow from original CLI script not migrated; automatic primitive vector selection remains absent |
| Batch scan report | Optional rectangle with live histogram | Crops only the selected source scan, not other unrelated scans; the original metadata-rich figure layout is not fully replicated |
| Molecule lattice overlay | Marked point or rectangle defines footprint center | Rectangular footprint, not molecule placement/physics |
| Molecule placement | No misleading interactive tool; disabled | Original physically informed placement engine not ported |
| Multiframe physical stack | Optional rectangle and preview histogram | Applies reference-grid selection; drift/atomic tracking and lattice engine not ported, no claim of registration equivalence |

## Shared selection contract

`module.json` may declare a `selection` object (`tools`, `multiple`,
`preview`) with line, rectangle or point support. UI selection outputs are
serialized in source pixel coordinates in the module snapshot. `ctx.roi`
is the current/most recently drawn selection; `ctx.rois` lists retained
selections. For module authors, see `scripts/README_SCRIPT.md`.

The CPD image comparison export is named:

`<source>_with_masks_<channel>_histogram_<trace>_mask_comparison_with_masked_image.png/pdf`

It includes the channel image, physical axes where calibrated, a scale bar,
named mask colors, raw image distribution, and count-normalized masks. It
never writes over the original scan. Individual fitted mask plots, saved
Boolean masks (`.npy`), metadata (`.json`), and Gaussian parameter tables are
saved under `SPM_Studio_Results/<source>/<run>/` in the source folder.

## Testing and limitations

Non-GUI tests include synthetic CPD population comparisons, physical ROI
bounds, PNG/PDF-only behavior, manifest validation, and factory migration.
Interactive Qt behavior still requires manual Ubuntu/Wayland acceptance with
real SXM/GWY files; the CI environment cannot verify actual mouse rendering.
Original scientific programs have assumptions and options not described by
these reduced module ports. Consult the archived source rather than assuming
that an available tool reproduces every original function.
