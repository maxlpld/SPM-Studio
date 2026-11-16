# Export profiles — how to build one for SPM Studio

**Read this before creating or changing a file in this folder** (person or AI assistant).

An export profile is one `.json` file here. It sets the page of a figure (size, resolution, font,
margin) and, optionally, the whole figure: how many images, their arrangement, what each one shows
and its options. It is chosen in the figure list of the top bar and in **Export**.

The easy way to make one: open **Export**, choose *Custom*, set everything up, and click
**Save as export profile…**. It is usable at once, without restarting. Edit the saved file only
for what the dialog does not offer.

## Page only (always valid)

```json
{
  "schema_version": 1,
  "name": "my_single_column",
  "width_mm": 86,
  "height_mm": 78,
  "dpi": 1200,
  "font_family": "DejaVu Sans",
  "font_size_pt": 9,
  "margin_mm": 4
}
```

| Key | Meaning |
|---|---|
| `schema_version` | Always `1`. |
| `name` | Same as the file name without `.json`. |
| `width_mm`, `height_mm` | Page size, > 0 and larger than twice the margin. The saved figure is cropped to its content. |
| `dpi` | Resolution of raster output (PNG) and of images inside SVG/PDF. 1200 by default. |
| `font_family`, `font_size_pt` | Titles, units, scale-bar label. |
| `margin_mm` | Outer margin, ≥ 0. |

## Page + figure (`layout`)

```json
{
  "schema_version": 1,
  "name": "kpfm_2x2",
  "width_mm": 178, "height_mm": 160, "dpi": 1200,
  "font_family": "DejaVu Sans", "font_size_pt": 9, "margin_mm": 4,
  "layout": {
    "arrangement": "grid",
    "columns": 2,
    "panel_letters": true,
    "transparent": false,
    "formats": ["svg", "pdf"],
    "panels": [
      {"source": "channel", "channel": "Z", "trace": "forward", "scan": "current",
       "title": "$Z$", "unit": "nm", "show_colorbar": true, "colorbar_position": "below",
       "show_scale_bar": true, "scale_bar_color": "#111111", "scale_bar_position": "bottom_right"},
      {"source": "channel", "channel": "Bias", "trace": "forward", "scan": "current",
       "title": "$V_{CPD}$", "unit": "", "show_colorbar": true, "colorbar_position": "below",
       "show_scale_bar": true, "scale_bar_color": "#ffffff", "scale_bar_position": "bottom_right"},
      {"source": "channel", "channel": "Z", "trace": "forward", "scan": "other_scan_0012.sxm"},
      {"source": "result", "result": "cpd_histogram", "show_colorbar": false}
    ]
  }
}
```

| `layout` key | Values |
|---|---|
| `arrangement` | `grid` (any number of images), `row`, `triangle`, `inverted_triangle` (the last two: exactly 3 images). |
| `columns` | Images per row in a grid; `0` = automatic (near-square). An incomplete last row is centred. |
| `panel_letters` | `true` / `false`: a, b, c… above each image. |
| `transparent` | `true` / `false`: no page background (PNG, SVG, PDF). |
| `formats` | Any of `svg`, `pdf`, `png`, `jpg`. |
| `panels` | 1 to 12 images, in reading order (left → right, top → bottom). |

| Panel key | Values |
|---|---|
| `source` | `channel` (a scan channel) or `result` (an analysis figure or plot). |
| `channel` | Channel name, matched on the scan that is open. An absent channel falls back to the active one. |
| `trace` | `forward` or `backward`. |
| `scan` | `current` (the open scan) or the **file name** of another scan of the list. |
| `result` | For `source: result`: part of the result file name (for example `histogram`). |
| `title` | Colourbar title; LaTeX between `$ $`. Empty = the title set on the scan. |
| `unit` | Unit shown in `[ ]`; empty = automatic SI prefix. |
| `show_colorbar`, `colorbar_position` | `true`/`false`; `below`, `right`, `left`, `none`. |
| `show_scale_bar`, `scale_bar_color`, `scale_bar_position` | `true`/`false`; `#RRGGBB`; `bottom_right`, `bottom_left`, `top_right`, `top_left`. |

Processing, colormap and contrast are **not** stored here: each image uses the display set on its
scan (apply a profile first). Do not add other keys: unknown keys are dropped when the file is read.

## Check

```
python -m json.tool kpfm_2x2.json
```

Then **Settings › Library › Export profiles**: listed without “invalid”. Choose it in the top bar,
click **Export**: the dialog opens with the saved figure.

## Share

**Settings › Library › Export profiles › Export…** → one `.zip`; a colleague uses **Import…**.
