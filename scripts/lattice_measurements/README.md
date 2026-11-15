# Lattice measurements (v13)

By default **only the scan you are currently viewing** is used for the lattice FFT.
Tick *Analyze ALL SXM/GWY scans in current folder* in Tool settings to fit
multiple scans (such as for drift). Leave the checkbox off for one scan.

Primitive vectors retain arrows and angle arc on the image. Their **a** and
**b** lengths appear in a corner legend (top left by default). Both vector
colors and the legend corner are editable in Tool settings, and the same
choices appear in PDF/SVG and the PNG used by molecule placement.

Select **Molecule placement (SVG / lattice)** afterwards to add scaled SVG/PNG
molecular artwork on the calibrated lattice; the tool reads `lattice_result.json`
from the output folder for this scan automatically.

---

# Lattice measurements — calibrated ROI export

The unchanged full-scan mode delegates to the original MultiFrame 0.1.2 engine and retains its drift/FFT/bootstrap reports.

For a selected rectangle (Tool settings → Draw region), **primitive_auto** analyzes **only the pixels inside that rectangle**, using the original FFT peak, candidate scoring, and Gauss-reduction functions. This ROI-only mode deliberately does **not** estimate drift or its uncertainties. It does not substitute the full MultiFrame multiframe analysis. Line-selection diagnostics remain available through `profile_fft_diagnostic`.

When finished, results appear beside the scan under `SPM_Studio_Results/<scan>/<run>/`:

- `cropped_scan.npy`: original cropped calibrated channel numbers, with missing values preserved
- `cropped_scan.png`: grayscale reference of exactly that physical ROI
- `lattice_preview.png`: copy annotated with vectors a/b and angle γ
- `lattice_preview.pdf`: when PDF exports are enabled
- `lattice_region.gwy`: physical cropped scan, separate lattice display channel, and native Gwyddion line selections; no original file is modified
- `lattice_result.json`: definitive physical ROI/pixel/vector contract for molecule placement

If no rectangle was selected, the **original full-scan engine** is used before these additional calibrated outputs are produced. The cropped file's scale comes from the original source metadata, not from on-screen DPI or the raster of the PDF export.

The returned vectors are geometrical periodicities, not adsorption sites. Source-array up/down orientation is not automatically flipped; real instrument orientation should be verified separately.

Select **Physically informed placement** afterwards, provide a PNG, and use `lattice_result.json` (or leave its field blank for the most recent lattice run for the active scan).
