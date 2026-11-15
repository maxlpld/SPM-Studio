# Real-file / GUI acceptance checklist — NOT yet executed

The following tests require actual Nanonis/Gwyddion data and an Ubuntu desktop
with PySide6 and optional packages installed. Mark each Pass/Fail with paths,
dates and screenshots, not assumptions based on synthetic images.

- [ ] Open one SXM with forward/backward Z, Bias, Δf, excitation. Inspect units,
  nan/partial lines, metadata, available actual traces and errors.
- [ ] Open the same source in Gwyddion and Studio. Compare asymmetrical
  fiducial positions (X flip, Y flip, 180° rotation and scan direction).
- [ ] For 0° and 90° and up/down SXM, use stable fiducials to calibrate pixel
  → sample geometry and source acquisition order. Check XY centre and range.
- [ ] Load GWY field/trace naming, offsets, scale, units, masks and Z polarity.
  Verify processed versions are not silently substituted for SXM raw data.
- [ ] Test incomplete and malformed files, missing BWD, NaN/Inf rows, high-DPI
  GNOME scaling and an 11-file folder on a representative Ubuntu workstation.
- [ ] Record cold startup, first preview, repeated palette change (target
  ~100–200 ms), RAM cap, background indexing and responsiveness while running.
- [ ] Compare preview/export same image orientation, field of view, palette,
  contrast bounds, scale bar, colorbar, annotations and ROI in PNG/PDF/SVG.
- [ ] Compare flake terrace heights/uncertainties and stripe maxima/minima
  against verified old routine, including an asymmetric stripe calibration.
- [ ] Compare CPD v9 both-trace raw/masked histograms, original mask rotation,
  per-pixel value correspondence and all Gaussian population fit parameters.
- [ ] Compare KPFM edge 10–90 topography width, CPD FWHM and residual/gradient
  metrics against original datasets and edge fit convention.
- [ ] Reproduce known old lattice vector b ~2× error case; check Gauss reduced
  primitive basis; compare Z and torsional frequency shift on SAME physical ROI.
- [ ] Verify module changes do not require changing main window or unrelated
  scientific modules; import custom external legacy script, inspect log/cancel.
- [ ] Verify real multi-scan drift, atom-tracking hints, shifted/up/down/90°
  source-coordinate mapping and common crop. Current simple stack does **not**
  implement these corrections and must not be accepted as final scientific stack.
- [ ] Instrument `amp_calib.py` cannot run/connect merely by opening Studio;
  future extension requires physical interlocks/state restoration/human review.

Log environment: Python version, PySide6 version, NanonisPy/GWY versions,
Ubuntu version, display scaling, CPU/RAM, input source hashes and expected
numeric tolerances. Do not claim these checks are complete without data.
