# Image export / provenance v1

The same `render_rgb()` + shared `paint_frame()` produces the Qt image preview
and final PNG/PDF/SVG/JPEG. Lower-resolution previews are nearest-stride samples
of the same transformed quantitative data; original full-resolution data feeds
exports. The same source-wide color bounds, colormap, gamma, and geometric
transform are used. PDF/SVG place SPM pixels as raster image with vector Qt
text/scale bar/overlays; NPY/CSV are raw *processed* numeric SI arrays and are
never LUT-clipped. The scale bar is omitted if physical size is unavailable.

An export named `scan_Z_forward.png` creates
`scan_Z_forward.png.provenance.json`:

```json
{
  "schema_version": 1,
  "utc": "<UTC timestamp>",
  "source": "<absolute original scan filename>",
  "fingerprint": {"size_bytes": 0, "mtime_ns": 0, "sha256_first_1MiB": "<hash>"},
  "channel": "Z", "trace": "forward",
  "geometry": {"shape": [512,512], "size_m": [1e-8,1e-8], "center_m": null,
               "angle_deg": null, "scan_direction": null,
               "source_orientation": "stored-array", "verified_orientation": false},
  "unit": "m",
  "processing": [],
  "style": {"colormap":"gray","range_mode":"percentile",
            "low":1,"high":99,"gamma":1,"scale_bar":true,"colorbar":true},
  "export_preset": {"schema_version":1,"name":"single_column",
                    "width_mm":86,"height_mm":78,"dpi":300,
                    "font_family":"DejaVu Sans","font_size_pt":9,"margin_mm":4},
  "warnings":[],"extra":{}
}
```

Collision-safe output filenames gain `_001`, `_002`, etc. Full source SHA256 is
not computed for large scans; first 1 MiB hash **plus file length and nanosecond
mtime** is called a fingerprint, not a full content hash. Analysis output files
may include extra CSVs/NPYs and a copy of the serialized source snapshot in
the run directory. Presets are independently validated.

**Known gaps:** `font_family`/`margin_mm` are accepted but not fully applied
by the Qt painter in v0.3; matplotlib analysis graph exports use shared defaults
rather than selected Qt figure presets; numeric mask/overlay parity and all
requested multipanel composition presets need further development and tests.
