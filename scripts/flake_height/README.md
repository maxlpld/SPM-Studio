# Flake / island height (experimental)

Uses the selected line ROI (otherwise column-averaged image profile) and left/right
fractional windows. Reports right minus left in raw SI units and independent-sample
SEM, not structural-layer-height confidence intervals. Optionally detects local extrema
with SciPy prominence. Does **not** reproduce the original GUI's full mask/fit workflow;
real experimental comparison against that source is pending. CSV, PNG, PDF and SVG outputs.
