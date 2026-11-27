# Microscope X/Y calibration (lattice, Au(111) herringbones) + Z (monatomic steps)

Status: **experimental**. It is validated on synthetic lattices, herringbones and stepped surfaces
with known distortion (see `test_module.py`); check it on your own reference scans before relying
on it.

Three calibrations in one tool (1.4):

- **X/Y from an atomic lattice** (sections 1–2, unchanged);
- **X/Y from the Au(111) herringbone reconstruction** when there is no atomic resolution
  (section 2b);
- **Z from monatomic steps** (section 2c) — run automatically on the topography channel when the
  scans show steps of the reference crystal.

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

### 2b. X/Y from the Au(111) herringbones

**Reference.** The 22×√3 reconstruction of Au(111) shows pairs of corrugation lines every
22 × 2.884 Å = **63.4 Å** along [1-10] (measured 63 Å), and in the herringbone pattern the lines
bend by **120°** every ≈ 250 Å: J. V. Barth, H. Brune, G. Ertl and R. J. Behm, “Scanning tunneling
microscopy observations on the reconstructed Au(111) surface: Atomic structure, long-range
superstructure, rotational domains, and surface defects,” *Phys. Rev. B* **42**, 9307 (1990),
doi:10.1103/PhysRevB.42.9307. The period can be changed in *Herringbone period (Å)*.

**Detection.** On every open scan (same channel as the active one):

1. the plane, the terraces and steps (with the step height of the crystal) and the large-scale
   background are removed, and step edges are masked;
2. the 2-D FFT gives the directions of the two line families: two peaks near 1/63.4 Å whose
   directions differ by 60° (120° between the lines), with a signal-to-noise ratio ≥ 50;
3. the spacing of each family is measured **inside its arms of the zigzag**: each family is
   isolated by a one-sided band-pass, its local wave vector (gradient of the local phase) is
   computed and the median is taken over the pixels well inside that family's domains. The FFT
   peak alone is not used for the spacing: an arm is only ≈ 12 nm wide between two elbows and the
   two families leak into each other's peak (≈ 3 % error on synthetic herringbones); the local
   wave vector reduces this to ≈ 1 %.

If the herringbones are **not found automatically** on a scan, the log says so: **draw around the
herringbones** on the active scan — a rectangle, or a closed line (line tool, Shift+click to add
corners) — and run again. Only the drawn region of the active scan is then used; the other scans
are always used whole.

**Fit.** Each family gives a wave vector k_i (|k_i| = 1/d in reality). A linear distortion of the
image (calibration error and constant drift, u_true = M · u_image) changes it as
k_true = M⁻ᵀ · k_image. The *dual basis* of the two wave vectors (a_i · k_j = δ_ij) therefore
transforms exactly like real lattice vectors, a_true = M · a_image, and in reality it is a hexagonal
cell with a = b = 2d/√3 = 73.2 Å and γ = 120°. This equivalent cell goes into the same fit as an
atomic lattice: previous calibration and scan angle of each file, thermal drift (header, fitted
session drift, up/down pairs), bootstrap, leave-one-out, statistics figure. Nothing of section 2
is changed.

**Accuracy.** ≈ 1–2 %: the herringbone is a weaker standard than an atomic lattice (22 or 23 atoms
per cell, strain near steps and elbows, short arms). Prefer atomic resolution when you can.

With *X/Y calibration with = Automatic* (default), the atomic lattice is tried first; when no scan
shows it and the crystal is Au(111), the herringbones are used and the log says so.

### 2c. Z from monatomic steps

**Reference.** The monatomic step height of the crystal (or *Monatomic step height (Å)*):
Au(111) a/√3 = **2.355 Å** (a = 4.078 Å; Barth et al. 1990 observe ≈ 2.4 Å), Ag(111) 2.359 Å,
Cu(111) 2.087 Å, Si(111) 3.136 Å (bilayer), HOPG 3.354 Å and h-BN 3.33 Å (c/2), KBr(001) 3.325 Å,
NaCl(001) 2.820 Å, KCl(001) 3.147 Å (a/2).

**Model.** A topography recorded with the previous constant cz_old shows z = cz_old · V; a step of
known height h₀ that appears as h_meas gives **cz_new = cz_old · n · h₀ / h_meas** (n = 1 for a
monatomic step). The previous constant is read from the file (Nanonis *Piezo Configuration ›
Calib. Z (m/V)*) or typed in *Previous calibration Z*; without it the result is a correction
factor.

**Measurement**, on the *Topography channel for Z* of every open scan:

1. **Step edges** are the pixels with a large height gradient (threshold from the expected step
   height and from the noise, so a corrugation never makes a step); the **terraces** lie between
   them.
2. **Terrace leveling:** one common plane plus one offset per terrace, then the offset of every
   scan line on the terrace pixels only (line jumps), fitted again. Unlike a plane or a row
   alignment, this neither bends nor erases steps.
3. **Profiles** perpendicular to the step edges (several parallel lines averaged), long enough to
   see both terraces but never crossing another step; *Step profiles per scan* limits their number,
   spread over the different edges.
4. **Height of each step:** the two terraces around the profile are fitted in 2-D within ≈ 12 nm
   (z = a + bx·x + by·y + h·[upper terrace]), which averages the herringbone corrugation (0.2 Å)
   that a single line would pick up. The 1-D profile fit is kept for comparison.
5. A step is used when its height is h₀ within the tolerance (*Reject … off by more than (%)*);
   double/triple steps only with *Also use double / triple steps*.

**Lines drawn across steps** on the active scan (2-point lines) are used as its profiles instead of
the automatic ones.

**Statistics:** weighted mean of all profiles (profile errors with a 0.5 % floor, scaled by the
scatter), **bootstrap over step edges**, **leave-one-scan-out**, every scan alone, subsets (fast axis,
slow direction, trace), height vs step direction.

**Drift and creep.** Inside a frame, time grows linearly with the position, so a constant Z drift
or creep adds a plane v_z · t(x, y): it is absorbed by the common terrace plane and by the slope
fitted on every profile, and does not bias the heights. **Up/down pairs** measure it: the tilt of
the sample is common while the drift term changes sign, v_z = Δslope / Δ(time gradient) along the
slow axis. The Z drift written in the header is reported. Lateral (X/Y) drift does not change
heights; when the X/Y calibration was fitted in the same run, the distances of the profiles and the
figure are corrected with it (including its drift).

*Z calibration*: **Automatic** (default) — done when monatomic steps are found, otherwise the log
says so and the X/Y result stands alone; **Required** — the run stops when no step is found;
**Off**. With *X/Y calibration with = Off (Z only)*, only Z is calibrated.

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
   for example avoiding a step edge. The other scans are always used whole. Selections are
   kept (1.4): the last rectangle limits the lattice; rectangles and closed lines mark the
   herringbone region; 2-point lines across steps are Z profiles.
5. **Select the tool**, then in *Tool settings*:
   - Choose the **reference crystal**, or *Custom* and type a, b, γ and/or the diagonal.
   - Check the **previous calibration**: it is read from the files. If your files do not
     contain it, type it here (nm/V), or leave 0 / 0 to get correction factors.
6. **Run the analysis.** The new constants are in the **Logs** panel and the results table.
7. **Apply them on the microscope** (Nanonis: *Piezo Configuration › Calib. X / Calib. Y*, and
   *Calib. Z* for Z), record new reference scans, and run the tool again. The correction should
   now be 1 within the uncertainty.

**Au(111) without atomic resolution:** choose *Au(111) (1×1)*, open scans of 50–300 nm showing
herringbones (and steps), show Z, run. X/Y comes from the herringbones and Z from the steps.

## 4. Parameters

| Parameter | Meaning |
|---|---|
| X/Y calibration with | *Automatic* (atomic lattice, else Au(111) herringbones), *Atomic lattice (FFT)*, *Au(111) herringbone reconstruction*, *Off (Z only)*. |
| Z calibration (monatomic steps) | *Automatic* (when steps are found), *Off*, *Required*. |
| Topography channel for Z | The height channel (m) in which steps are measured (default Z). |
| Monatomic step height (Å) | 0 = from the crystal (see 2c). Needed with *Custom*. |
| Herringbone period (Å) | 0 = 63.4 Å (Barth et al. 1990). |
| Previous calibration Z (nm/V) | Used when the file has no Z calibration (or with the override). 0 → correction factor. |
| Step profiles per scan, Step profile length | At most N profiles per scan; length 0 = automatic (≈ 40 px, ≥ 8 nm, never crossing another step). |
| Also use double / triple steps | Count steps of n × h₀ as n layers. |
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
- **`calibration_herringbone_overlay.svg`** (herringbone method): the active scan with its terraces
  flattened so the herringbones are visible, drawn with the new physical size; arrows N × d₁ and
  N × d₂ normal to the two line families (old pale and dashed, new in full colour), the drawn region
  outlined; corners *d₁, d₂, angle between the lines: before → after* (theory 63.4 Å, 120°) and
  *X, Y calibration: old → new*.
- **Z from steps:**
  - **`z_steps_scan.svg`** — the topography drawn exactly like the Export panel (recalibrated
    heights, colour map and colourbar of the viewer) with the numbered, coloured profiles used;
    corners *step: before → after* and *Z: old → new*;
  - **`z_step_profiles.svg`** — the profiles, before (previous Z) and after (new Z), aligned on
    the step edge, with h₀;
  - **`z_calibration_overview.svg`** — the scan and the profiles side by side;
  - **`z_calibration_statistics.svg`** — a every profile before → after (leave-one-scan-out),
    b terrace levels with n × h₀, c every scan alone vs all (±1σ, bootstrap CI), d subsets or
    bootstrap, e height vs step direction, f drift and summary;
  - **`z_calibration_result.json`**, **`z_step_profiles.csv`** and the results tables. A summary
    is also added to `calibration_result.json` (`z_calibration`) when X/Y was calibrated too.
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
- **Z (height) calibration** uses monatomic steps (section 2c). The Z piezo is assumed linear over
  the height range of the steps; a few Å of steps do not test large heights. Strongly tilted or
  bowed images, or steps closer than ≈ 2 nm, give fewer usable profiles.
- **Herringbones** give X/Y to ≈ 1–2 % only (section 2b).

## Test

From the Scripts folder, with the Python that runs SPM Studio:

```
python -m pytest microscope_calibration/test_module.py -q
```

The tests use synthetic lattices at 0°/90°/45°, square, rectangular and hexagonal cells,
different previous calibrations, axis skew, leave-one-out and bootstrap. A full run on four
generated SXM files recovers a known 8 % / −5 % distortion to better than 0.1 %.

## Changes

- **1.4.0:** Au(111) herringbones and Z.
  - X/Y from the Au(111) herringbone reconstruction (63.4 Å, Barth et al. 1990), detected
    automatically or inside a drawn region, fitted as an equivalent cell with the same drift and
    statistics as an atomic lattice; *Automatic* falls back to it when no atomic lattice is found.
  - Z from monatomic steps: terrace leveling, automatic or drawn profiles, 2-D terrace fit, weighted
    fit over all scans with bootstrap, leave-one-out and subsets; Z drift from up/down pairs; scan,
    profile, overview and statistics figures.
  - Selections are kept (rectangles and lines). Every 1.3 option and result is unchanged.

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
