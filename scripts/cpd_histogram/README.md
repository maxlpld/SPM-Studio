# CPD / Bias histogram (experimental)

Supports explicitly selected forward, backward, or both traces; raw numerical
value-range masks, raw/masked histograms, 1–6 unconstrained Gaussian components,
mask NPY, CSV, publication PNG/PDF/SVG. The optional 180-degree display rotation
applies consistently to image and mask but does not rotate the original data.
**No AIC/BIC/manual peak editor or v9 legacy function-override audit is claimed.**
Gaussian least squares may be unstable for overlapping populations: inspect fits.

## v0.4.2 Studio controls

- Select **Draw region** inside Tool settings and drag the scan. **Delete
  selected** removes the region; **Undo last** and **Clear all** work on all
  selection types. The numerical histogram and color mask overlay refresh as
  the rectangle/handles move. This is separate from deleting a named value
  mask from the mask list.
- In **Named value-range masks**, use New, Delete, Undo mask edit or Reset
  range, plus optional starting means (comma-separated SI values). The mask
  range is inclusive and colored overlays never overwrite the scan data.
- In parameter settings, choose **Raw-only Gaussians** (if you use no masks),
  or select Gaussian counts per mask. **Reuse mask Gaussians in raw fit** fixes
  their measured means and widths while performing a nonnegative-amplitude
  refit of the total raw histogram.
- The **Export masked-image comparison** setting generates the former
  `..._with_masks_<channel>_histogram_<trace>_mask_comparison_with_masked_image`
  PNG/PDF composite with a physically calibrated scan image, mask colors,
  comparison curves and selectable scale-bar color.
- Optional plot title and x/y axis labels use the same global publication
  style as the other modules. Global export formats and automatic result
  opening are in Options → Scientific plots & results.

**Not migrated from the large legacy package:** writable `.gwy` copies with
mask channels, the full advanced multi-initialization fitting/reporting and
uncertainty presentations, and instrument-verified image orientation. Refer
back to `legacy_reference/CPD HISTO.zip` for the exact original scientific
algorithm. This module remains experimental until numerical comparisons
against instrument data are completed.
