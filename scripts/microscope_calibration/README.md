# Microscope X/Y calibration (lattice)

Status: **experimental**. It is validated on synthetic lattices with known distortion (see
`test_module.py`); check it on your own reference scans before relying on it.

## 1. What it does

The tool calibrates the lateral (X and Y) piezo scanner from atomic-resolution images of a
crystal whose lattice you know (KBr, NaCl, KCl, HOPG, Au(111) …).

- It uses **every scan open in SPM Studio**, on the channel the tool was started from.
- In each scan it detects the primitive lattice with the FFT engine of the
  *Lattice measurements* tool.
- It reads from each file the **scan angle** (whether the fast axis runs along piezo X or Y),
  the **slow-scan direction** (up/down) and the **piezo calibration constants used for that
  scan** (Nanonis `Piezo Configuration › Calib. X/Y (m/V)`).
- It fits the **new X and Y calibration constants** that make every measured lattice agree
  with the theoretical one.

The output is:

- the new constants with their uncertainties;
- a lattice figure of the active scan, showing **before → after** values and
  **old → new calibration**;
- when several scans are open, a statistics figure showing that the correction is right.

## 2. How it works

### The model

A scan recorded with the previous constants `cx_old`, `cy_old` (m/V) shows a piezo
displacement `p = c_old · V`, where `V` is the voltage on the piezo. The real displacement is
`c_true · V`.

For every lattice vector measured in an image (scan frame: +x along the fast axis, +y up):

1. Rotate it into the piezo frame with the scan angle θ: `v_piezo = R(θ) · v_image`.
2. Convert it to piezo voltages with that scan's own previous constants:
   `Vx = v_piezo,x / cx_old` and `Vy = v_piezo,y / cy_old`.
3. Its real length must equal the theoretical length L:

   `L² = Vx² · cx² + Vy² · cy²   (+ 2 Vx Vy · cxy if axis skew is fitted)`

This equation is **linear in cx², cy² (and cxy)**. Every vector of every scan adds one
equation:

- a and b;
- the two diagonals |a + b| and |a − b|, when the cell angle γ or the diagonal is given.

All equations are solved together by weighted linear least squares. The new constants are
`cx = √(cx²)` and `cy = √(cy²)`. As a correction factor: `new = previous × (L_true / L_measured)`
along each piezo axis.

### Why the diagonals matter

For a square lattice oriented at 45° to the piezo axes, a and b both have equal X and Y
components. They then only give `cx² + cy²`, not the two constants separately. The
diagonals lie along X and Y and make the problem solvable. Always enter γ (90° for
KBr/NaCl, 120° for hexagonal lattices) or the diagonal.

### Several scans

- Scans recorded **with the fast axis along X (θ = 0°) and along Y (θ = 90°)** separate the
  two axes best. They also cancel the systematic difference between the fast and slow axes
  (hysteresis, creep and drift act mostly on the slow axis).
- Scans taken with different previous calibrations can be combined: every equation uses its
  own scan's constants.
- **Up and down** scans of the same area show linear thermal drift with opposite signs, so
  combining them averages it out. Panel f of the statistics figure checks this (see below).

### Thermal drift

**Why drift matters.** A frame takes minutes. If the sample moves relative to the scanner
with a velocity **v** (thermal drift, creep), every point is recorded a little later than the
previous one and is displaced by **v · t**. Inside one image, time grows along the fast axis
(one line) and, much faster per nm, along the slow axis (one line per row). A constant drift
is therefore a linear distortion of the image, exactly like a calibration error. In a single
frame the two cannot be told apart.

**Model.** For each vector of a scan:

`u_true = C · V − v · (g · u)`

- `C` = calibration (what we fit), `V` = the vector divided by the previous calibration.
- `g` = time gradient of the image in s/nm. It comes from the header:
  `SCAN_TIME` (time per forward / backward line), the number of rows, the scan size, the
  slow-scan direction (`SCAN_DIR`: down = time grows towards the bottom, up = towards the
  top) and the trace (backward lines run from right to left).
- `g · u` is the time the tip took to travel along the vector.

**1 — The drift compensation in the header.** Nanonis writes the compensation it applied:
*Piezo Configuration › Drift X/Y (m/s)* and *Drift correction status*. During a compensated
scan the controller moves the tip with **v_comp**, so the image only shows the remaining
drift **v_true − v_comp**. The tool uses these values according to *Thermal drift*:

| Thermal drift | What is done |
|---|---|
| **Header + fit (default)** | One sample drift **v_true** is fitted for the whole session together with the calibration. Each scan uses its own compensation: effective drift = v_true − v_comp (compensation on) or v_true (off). Scans taken with different compensation values are therefore combined correctly, and the result tells you whether your compensation was right (v_true ≈ v_comp). |
| Header only | Nothing is fitted. A compensated scan is taken as drift-free; for an uncompensated scan the drift values in its header are removed. |
| Fit only | The header is ignored; one effective drift is fitted for all scans. |
| None | Calibration only (previous behaviour). |

**2 — Fitting the drift with the calibration.** Frames with *different time gradients* see the
same drift differently, while the calibration is the same for all of them. Fitting all frames
together therefore separates the two (non-linear least squares with 4 unknowns: cx, cy, vx,
vy). Frames that separate them:

- **up and down** scans (the slow-axis gradient changes sign; this is the strongest case);
- scans at **0° and 90°** (the slow axis is along Y, then along X);
- different **scan speeds** (the gradient changes size).

A single frame, or frames that all share the same gradient, cannot separate drift from
calibration. The tool detects this, writes it in the log and falls back to *Header only*.

**3 — Independent check with up/down pairs.** Two consecutive frames of the same area, one
up and one down, show the *same* lattice distorted by opposite slow-axis drift. Equating them:

`(K − v g_upᵀ) B_up = (K − v g_downᵀ) B_down  →  v · (g_upᵀ B_up − g_downᵀ B_down) = K (B_up − B_down)`

This gives 4 equations for 2 unknowns per pair, solved by least squares. It **does not use
the theoretical lattice constants at all**, and K enters only weakly: with K = 1 the drift
comes out within ~10 %. Pairs are found automatically: same angle, size and trace, opposite
slow direction, centres within 15 % of the scan size, in acquisition-time order.

Two checks follow:

- The residual of the 4 equations says whether a *constant* drift explains the difference
  between the two frames. A large residual means the drift changed during the frame, or
  creep.
- The pair estimates are plotted next to the drift fitted with the calibration and the
  header compensation (panel g). If they agree, the drift model is right and the calibration
  is not biased by drift.

**What is corrected:**
- The new calibration and every "after" value (figures, tables, leave-one-out) are drift
  corrected.
- The before → after figure shows the residual drift of that scan in the calibration corner.
- Panel h shows the length error of every scan with calibration only vs with drift.
- The fitted drift (with its covariance), the header values used for each scan and every
  pair estimate are in `calibration_result.json` (`drift`) and the results table.

**Limits.**
- The drift is assumed **constant during the session**. It is usually slowing down after an
  approach or a large offset, so wait for it to settle, or calibrate on frames taken close
  in time.
- Creep after a large move is not linear in time.
- If `SCAN_TIME` or `SCAN_DIR` is missing from a file, its drift cannot be modelled; the log
  says so.

### Weights and uncertainties

- **Weights.** The detected vector length is limited by the FFT resolution, which is about
  L² / (2W) for an image of size W (half a frequency bin). This sets the a-priori error of
  each vector.
- **Fit errors.** The formal errors are scaled by the observed scatter (Birge ratio) when
  there are more equations than unknowns.
- **Bootstrap (≥ 3 scans).** Whole scans are resampled with replacement, which keeps the
  correlation between the a, b and diagonals of one scan. This gives a 95 % confidence
  interval that does not depend on the error model.
- **Leave-one-out (≥ 2 scans).** Each scan is corrected with the calibration fitted on the
  *other* scans. The "after" values in the figures are an independent prediction, not the
  fit grading itself.

### Conventional or primitive cell?

A lattice constant can be given in two ways:

- the **conventional** constant, e.g. the rock-salt cell edge a = 6.65 Å for KBr;
- the **primitive surface cell** that the image shows, e.g. one ion species on KBr(001):
  a/√2 = 4.70 Å, rotated by 45°. This is also the half diagonal of the 6.65 Å cell.

Both describe the same crystal, so the tool also tries the exact equivalent descriptions of
the value you entered:

- **square cell:** a/√2 and a·√2;
- **hexagonal cell:** a·√3 and a/√3 (the (√3×√3)R30° cell).

It uses the one that matches the detected lattice and writes the choice in the Logs panel
and in `calibration_result.json` (`reference.interpretation`). The choice uses the median
over all scans and is only accepted within the tolerance. These candidates differ from one
another by at least 41 %, far more than any realistic calibration error, so the choice is
unambiguous. Turn *Recognise conventional vs primitive cell* off to use exactly what you
typed.

### Assignment and outliers

- **Assignment.** If a ≠ b, the measured vectors are matched to a and b after correcting with
  the current estimate, and the fit is repeated until the matching stops changing. The short
  and long diagonals are matched the same way.
- **Outliers.** A scan whose detected cell differs from the reference by more than the
  tolerance (default 25 %) is **not used**, and the Logs panel says why. Typical causes are
  another lattice, a superstructure, an FFT harmonic or a far-off calibration.

## 3. How to use it

1. **Install.** Copy the folder `microscope_calibration` into the Scripts folder
   (**Tools › Open Scripts folder**), next to `lattice_measurements`, which provides the
   lattice detection. The tool appears in the list within a few seconds (or click
   **Refresh modules**).
2. **Open the reference scans** of your calibration crystal (KBr …), as many as you have.
   Ideally include scans at 0° and 90°, and up and down. All of them are used.
3. **Show the channel to analyse** (usually Z, or Δf for AFM) on one of them. This becomes
   the *active scan* for the before/after figure. The processing set on that channel (plane,
   row alignment …) is applied to every scan before the lattice detection. With no
   processing, a plane is removed for the detection only.
4. *Optional:* draw a **rectangle** on the active scan to measure its lattice only there,
   for example avoiding a step edge. The other scans are always used whole.
5. **Select the tool**, then in *Tool settings*:
   - Choose the **reference crystal**, or *Custom* and type a, b, γ and/or the diagonal.
   - Check the **previous calibration**: it is read from the files. If your files do not
     contain it, type it here (nm/V), or leave 0 / 0 to get correction factors.
6. **Run the analysis.** The new constants are in the **Logs** panel and the results table.
7. **Apply them on the microscope** (Nanonis: *Piezo Configuration › Calib. X / Calib. Y*),
   record new reference scans, and run the tool again. The correction should now be 1
   within the uncertainty.

## 4. Parameters

| Parameter | Meaning |
|---|---|
| Reference crystal | Gives a, b, γ and the diagonal; the source is written in the log. The default is **KBr(001): a = 6.65 Å, γ = 90°, diagonal 4.7 Å**, from A. Hinaut, “Non-contact Atomic Force Microscopy and Kelvin Probe Force Microscopy Studies of Triphenylene Derivatives on KBr(001) in Ultra High Vacuum,” Ph.D. thesis, Université Toulouse III – Paul Sabatier (2012). Choose *Custom* to use the four fields below. |
| a, b (Å) — with Custom | Lattice constants. Defaults: KBr a = 6.65 Å; b = 0 means b = a. The conventional cell and the cell seen in the image are both recognised (see above). |
| Cell angle γ (°) | Angle between a and b: 90° square/rectangular, 120° hexagonal. 0 = unknown. |
| Recognise conventional vs primitive cell | On (default): if the image shows a/√2, a·√2 (square) or a·√3, a/√3 (hexagonal) of the value entered, that exact cell is used and the log says so. |
| Diagonal (Å) — with Custom | Full diagonal \|a ± b\| or half diagonal. KBr: 4.7 Å is the half diagonal of the 6.65 Å cell, i.e. the distance between neighbouring ions of the same species. It is checked against a, b and γ: the log says whether it is consistent, and γ wins if not. Without γ, a value shorter than a is taken as the half diagonal. |
| Previous calibration X / Y (nm/V) | Used when the file has no calibration. 0 and 0 → correction factors only. |
| Use these previous values instead of the files' | Ignore the calibration stored in the files. |
| Traces used | Active trace only, or forward and backward as independent measurements. |
| Thermal drift | *Header + fit (recommended)*, *Header only*, *Fit only*, *None* — see **Thermal drift**. |
| Also fit X/Y axis non-orthogonality | Adds the angle between the piezo axes (≠ 90°). Needs vectors in ≥ 3 independent directions. |
| Reject lattices off by more than (%) | Rejects scans whose detected lattice is not the reference. |
| Bootstrap repeats | Resamplings for the confidence interval (needs ≥ 3 scans; 0 = off). |
| Colormap, vector colours, corners, title | Look of the before/after figure. |

## 5. Outputs (in the run folder, shown in Results)

- **`calibration_lattice_overlay.svg`** (and the other formats set in *Options › Results*):
  the active scan, drawn with the **new** physical size.
  - Arrows: the new lattice vectors are solid, in the full colour of a and of b; the old ones
    are pale and dashed, drawn on top. A single lattice vector is only a few pixels on a large
    scan, so the arrows are N × a and N × b (about 20 % of the image); the legend states N.
  - One corner gives *a, b, γ: before → after*.
  - The other corner gives *X, Y calibration: old → new* (in nm/V, or as ×factor when the
    previous calibration is unknown). Old values are in the pale shade of the colour, new
    values in the full (darker) colour, in bold.
  - The figure shows exactly the region that was measured (a drawn rectangle, or the complete
    rows of an aborted scan). If the active scan gave no usable lattice, the first usable scan
    is drawn instead and the log says which.
  - It is drawn with the Export-panel renderer. If that fails, the same figure is drawn with
    Matplotlib, and the reason is written in the log, so the figure is always produced.
- **`calibration_statistics.svg`**, one panel per test:
  - a — measured/theoretical length vs vector direction in the piezo frame: before (with the
    fitted error model) and after.
  - b — length error of a, b and the diagonals for every scan, before → after, with the RMS
    error and the FFT-resolution band.
  - c — cell angle γ before → after.
  - d, e — X and Y calibration fitted on every scan alone vs all scans together (±1σ and
    bootstrap 95 % CI), with the previous values.
  - f — calibration from subsets of scans (fast axis X vs Y, slow up vs down, forward vs
    backward), as a deviation from the global fit, with the fitted drift removed. Subsets
    that still disagree beyond the uncertainty indicate creep or hysteresis.
  - g — drift estimates (nm/min, piezo frame): header compensation, every up/down pair (no
    reference used), and the drift fitted with the calibration with its 95 % region.
  - h — RMS length error of every scan with calibration only vs calibration + drift (U/D =
    up/down).
  - i — summary of the drift treatment.

  With a single scan, only panels a–c are drawn, and the "after" values are then in-sample.
- **`calibration_result.json`**: the reference, the previous and new constants with σ, the
  bootstrap CI, χ², and for every scan its angle, fast axis, slow direction, previous
  constants and measured basis. It also lists the rejected scans with the reason.
- **`calibration_vectors.csv`**: every vector of every scan, with its theoretical length,
  before, after (all scans) and after (leave-one-out), and its direction in the piezo frame.
- **Results tables**: the calibration summary and the per-vector table.

## 6. Limits — when not to trust the result

- **Linear model.** The tool fits linear constants only. Piezo non-linearity, hysteresis and
  creep make the constant depend on scan size and speed. Calibrate with scan sizes and
  speeds close to those you use, and do not apply a calibration from 10 nm images to
  1 µm images.
- **Thermal drift** is modelled as constant over the session (see **Thermal drift**). Varying
  drift or creep is not; check the up/down pair residuals and panels g–h.
- **Temperature of the lattice constant.** The preset constants are room-temperature values.
  Crystals contract on cooling, by roughly 1 % or less between 300 K and 5 K for alkali
  halides. For the best accuracy, type the lattice constant at your measurement temperature
  from the literature.
- **Atomic resolution required.** Small or noisy images give coarse FFT peaks. The resolution
  band in panel b shows the limit. Use at least ~20 lattice periods per image.
- **Orientation conventions.** The scan-angle sign follows SPM Studio's convention
  (counter-clockwise). For 0° and 90° scans, X and Y do not depend on this sign. For other
  angles combined with *axis skew*, check the result with a 0°/90° pair.
- **Previous calibration unknown.** The tool can only give correction factors, and all scans
  must have been recorded with the same constants.
- **Z (height) calibration** is not covered. Use a step height (e.g. a monatomic step) for Z.

## Test

From the Scripts folder, with the Python that runs SPM Studio:

```
python -m pytest microscope_calibration/test_module.py -q
```

The tests use synthetic lattices at 0°/90°/45°, square, rectangular and hexagonal cells,
different previous calibrations, axis skew, leave-one-out and bootstrap. A full run on four
generated SXM files recovers a known 8 % / −5 % distortion to better than 0.1 %.

## Changes

- **1.3.0:** drift.
  - The drift compensation in the header is taken into account.
  - One session drift is fitted with the calibration when the scans allow it (up/down, 0°/90°,
    different speeds).
  - Up/down pairs give an independent drift estimate that does not use the reference lattice.
  - New statistics panels g–i; drift in the JSON, the table and the before → after figure.

- **1.2.0:**
  - The before → after figure is always produced: it falls back to a Matplotlib version when
    the Export-panel renderer fails, and the error is logged with its traceback.
  - It shows exactly the measured region, uses the first usable scan if the active one was
    rejected, and draws N × a / N × b arrows so they are visible.
  - KBr default: a = 6.65 Å, γ = 90°, diagonal 4.7 Å (Hinaut 2012), with the source in the
    log and in the JSON.
  - The diagonal can be the full or the half diagonal and is checked against a, b and γ.
  - The a/b/γ/diagonal fields are used with *Custom*.

- **1.1.0:** the conventional constant is recognised. Entering, for example, KBr a0 = 6.60 Å
  while the image shows the 4.67 Å surface cell used to reject every scan; the tool now uses
  a0/√2 and says so in the log. When no scan can be used, the error now lists the detected
  cells, the reference and what to check.
- **1.0.0:** first version.
