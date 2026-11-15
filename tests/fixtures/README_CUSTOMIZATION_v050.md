# WHAT I WANT TO CUSTOMIZE

[USER WRITES THE REQUEST HERE: colors, fonts, image styles,
processing steps, colormap, axes, colorbar, figure sizes, etc.]

---

# INSTRUCTIONS TO A CODING AI — SPM STUDIO CUSTOMIZATION

Create **only** the smallest editable JSON/CSV customization file needed.
Never patch Python GUI/core source or invent unsupported keys. The schema is
version 1. Missing keys fall back to defaults; unknown keys are ignored by
validated profiles (but do not add unknown keys).

User override directory: `~/.config/spm-studio/customization/`.
Packaged defaults → project defaults → **user overrides**. Subfolders:
`profiles/`, `export_presets/`, `themes/`, `colormaps/`. The app's Import menus
can copy and validate files into the correct folder. Changes to display style
do **not** mutate the underlying data or affect instrument calibration.

## 1. Scientific image + processing profile (profiles/STM.json)

```json
{
  "schema_version": 1,
  "name": "STM",
  "channel_contains": "Z",
  "style": {
    "colormap": "gray",
    "range_mode": "percentile",
    "low": 1,
    "high": 99,
    "gamma": 1.0,
    "scale_bar": true,
    "colorbar": true
  },
  "processing": [
    {"operation": "plane", "params": {}, "enabled": false},
    {"operation": "row_median", "params": {}, "enabled": true}
  ]
}
```

Ranges: `full`, `percentile` (0–100), `manual` (raw SI min/max), `sigma`
(mean ± N standard deviations), `mad` (median ± N robust MAD). `low < high`
for percentile/manual. `gamma > 0`. Available colormap names are `gray`,
`gray-inverted`, `viridis`, `magma`, `copper`, or a CSV/TXT filename installed
in the user `colormaps/` folder. Order of steps is meaningful; options:
`plane`, `row_mean`, `row_median`, `line_poly` (degree 0–4), `median_scar`
(threshold as robust multiples), `subtract_median`, `invert`. There is no
unrequested automatic topographic sign inversion.

## 2. Publication figure preset (export_presets/single_column.json)

```json
{
  "schema_version": 1,
  "name": "single_column",
  "width_mm": 86,
  "height_mm": 78,
  "dpi": 300,
  "font_family": "DejaVu Sans",
  "font_size_pt": 9,
  "margin_mm": 4
}
```

Dimensions in millimetres, DPI in dots/inch. Supported output formats: PNG,
PDF, SVG, JPEG (display), NPY and CSV (scientific numeric arrays). Figure
text/scale overlays remain vectors in PDF/SVG where Qt painters support them;
the underlying SPM pixels remain raster. `font_family` and `margin_mm` are
reserved validated fields with partial v0.3 rendering support; do not assume
pixel-perfect margin/font parity without testing. Plot modules use central
Matplotlib style defaults, which have not been fully linked to export presets.

## 3. Application theme (themes/custom.json)

```json
{
  "schema_version": 1,
  "background": "#171b21",
  "surface": "#222831",
  "foreground": "#e9edf1",
  "accent": "#71aee9",
  "muted": "#98a4b3"
}
```

All colors must be `#RRGGBB`; invalid themes revert safely to dark.
This affects **only the application GUI**, never scientific figure appearance.
The defaults are neutral dark, light and University of Basel inspired.
Import a theme and restart to see its Appearance-menu entry.

## 4. Custom colormap (colormaps/my_map.csv)

```text
# Rows are RGB or RGBA components, each in 0..255 (or each in 0..1)
0,0,0
60,75,138
255,255,255
```

At least two rows. RGB interpolation produces a 256-entry LUT. CSV `,` or TXT
whitespace are accepted; all values must be finite. Use **Import colormap…**
to activate it. A numerical CSV/NPY export retains the original raw numbers.

When asking another coding AI for customization, produce a ready-to-copy file
and one install path, not a new code framework. If you need typography/colorbar
positions or physical axes options not exposed in v0.3, propose an explicit
small, versioned Style API addition **instead of inventing JSON keys**.


## Multi-channel display profiles (schema version 1)

A `profiles/*.json` may contain `"visible_channels": ["Z", "Bias"]`.
The entries first match exact channel names, then case-insensitive fragments; missing
channels are skipped. Up to four channels are shown together. The currently active
channel stays editable for ROI operations, and all additional views remain raw
unless a user has explicitly assigned a processing chain to them. Save via
**File → Save current profile**; reload with **Apply profile**.

## Shared output options

**Options → Scientific plots & results** selects a `plot_styles/*.json`
profile, PNG/PDF/both, and automatic first-result preview. These are independent
from GUI themes. Each module must use `ctx.plot_config` and `ctx.plot_formats`
via `spm_studio.core.analysis_utils.save_plot`.

## v0.4.2 — One validated plot style for module figures

Create a new file under `plot_styles/` using this example:

```json
{
  "schema_version": 1,
  "name": "My monochrome plots",
  "font_family": "DejaVu Sans",
  "font_size": 10,
  "title_size": 11,
  "label_size": 10,
  "tick_size": 9,
  "legend_size": 8,
  "line_width": 1.5,
  "marker_size": 4,
  "grid": false,
  "axes_spines": ["left", "bottom"],
  "max_ticks": 5,
  "scientific_notation": true,
  "figure_width_in": 7,
  "figure_height_in": 4.4,
  "dpi": 300,
  "background": "#ffffff",
  "image_colormap": "gray",
  "image_interpolation": "nearest",
  "image_colorbar": true,
  "image_aspect": "equal",
  "auto_limits": true,
  "channel_colormaps": {"Z": "gray", "Bias": "coolwarm"}
}
```

Open **Options → Scientific plots & results**, select your style by filename
stem, and choose `PNG`, `PDF`, or `both` and whether to open the first figure
when an analysis finishes. Do **not** encode these UI preferences inside
individual plot-style JSONs. The global style controls Matplotlib figures
created with the shared module helpers, not GUI widget appearance.

`visible_channels` in scan profiles still controls simultaneous previews,
not which channels a scientific module may load. Module data requirements
must be declared in its `snapshot_channels` manifest property.

Requests for arbitrary freehand mask editors, GWY mask-channel export,
per-mask colorbar geometry or other unsupported functionality must be treated
as explicit scientific/GUI development work; adding nonexistent JSON keys
will not implement it.
