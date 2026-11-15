# Data, geometry and units

Canonical image: NumPy `[row, column]`, displayed with top-left as array
`(0,0)`, column to the right, row down. **No implicit flipping, mirroring,
180° rotation or Z inversion is performed.** Forward/backward trace is an
independent selection, not synonymous with slow-scan up/down. The vendor
reader's actual pixel acquisition order remains unverified for real files.

For `shape=(ny,nx)`, physical width/height `(sx,sy)` and scan center
`(cx,cy)`, pixel centers in *local scan axes* are:

```text
x_local = ((column+0.5)/nx - 0.5) * sx
y_local = (0.5 - (row+0.5)/ny) * sy
x_sample = cx + cos(theta)*x_local - sin(theta)*y_local
y_sample = cy + sin(theta)*x_local + cos(theta)*y_local
```

`theta` is the scan angle in degrees CCW in this documented **model**.
Absolute sample coordinates require both `center_m` and `angle_deg`, not just
scan size. GWY fields commonly carry `xreal,yreal` but often lack reliable
absolute center/angle; the app explicitly leaves those unknown rather than
inventing them. If size is unknown, local relative values use pixel units.
This model must be checked against your Nanonis acquisition headers, 0°/90°
asymmetric fiducials and Gwyddion displayed orientation before using scan
stacks/overlays to infer absolute sample locations.

`Geometry` methods: `pixel_to_local(row,col)`, `local_to_pixel(x,y)`,
`pixel_to_sample(row,col)`, `sample_to_pixel(x,y)`. The inverse functions are
analytical. One geometry object belongs to one channel and requires an exact
image-shape match. Metadata `SCAN_RANGE` is already in physical units, and is
**never multiplied by piezo sensitivity again**. Calibration metadata is
retained for inspection, not applied twice.

Z (m), bias/CPD (V), current (A), frequency shift (Hz) and other channels are
represented as parser-returned quantitative arrays (expected SI when specified
by the reader); no sign flip is applied automatically. `NaN`/Inf pixels remain
invalid. A separate `ImageStyle` computes display LUT/ranges; NPY/CSV remains
unclipped. A trace requested but not present raises a `KeyError`.

**Remaining critical validation:** real SXM forward/backward conventions,
slow-raster up/down pixel order, scan angle orientation, and GWY processed
channel naming. A verified 180° rotation is different from a mirror.
