# Plot styles — how to build one for SPM Studio

**Read this before creating or changing a file in this folder** (person or AI assistant).

A plot style is one `.json` file here. It sets the look of the plots drawn by analysis tools
(histograms, line profiles, fits): fonts, line widths, ticks, size, colours. It is chosen in
**Settings › General › Results & figures…**. It does not affect scan images shown in the viewer.

## Complete example (all keys, with their defaults)

```json
{
  "schema_version": 1,
  "name": "My style",
  "font_family": "DejaVu Sans",
  "font_size": 10, "title_size": 11, "label_size": 10, "tick_size": 9, "legend_size": 8,
  "line_width": 1.5, "marker_size": 4,
  "grid": false,
  "axes_spines": ["left", "right", "top", "bottom"],
  "journal_frame": true, "panel_labels": true, "transparent_background": false,
  "max_ticks": 5, "scientific_notation": true,
  "figure_width_in": 7.0, "figure_height_in": 4.4,
  "dpi": 600, "background": "#ffffff",
  "image_colormap": "gray", "image_interpolation": "nearest",
  "image_colorbar": true, "image_aspect": "equal",
  "auto_limits": true,
  "channel_colormaps": {"Z": "gray", "Bias": "coolwarm", "Current": "viridis", "Excitation": "inferno"},
  "colormap_override": "",
  "show_titles": true,
  "text_replacements": "",
  "colorbar_mode": "auto", "colorbar_size_pct": 5.0,
  "legend_mode": "auto", "legend_frame": false
}
```

Only `schema_version` (always `1`) and `name` are required; a missing key takes the default above.
**An unknown key makes the whole file invalid** — use only the keys listed here.

| Key | Allowed values |
|---|---|
| sizes, `line_width`, `marker_size`, `figure_width_in`, `figure_height_in` | Number > 0 and ≤ 80 (points / inches). |
| `dpi` | Integer 1–2400. |
| `max_ticks` | Integer 2–20. |
| `axes_spines` | Any of `left`, `right`, `top`, `bottom`. |
| `image_interpolation` | `nearest`, `none`, `bilinear`. |
| `image_aspect` | `equal`, `auto`. |
| `colorbar_mode` | `auto`, `hide`, `right`, `left`, `top`, `bottom`. |
| `colorbar_size_pct` | 1–40. |
| `legend_mode` | `auto`, `hide`, `best`, `upper right`, `upper left`, `lower right`, `lower left`, `outside right`. |
| `image_colormap`, `colormap_override`, values of `channel_colormaps` | `gray`, `Greys`, `gray_r`, `viridis`, `plasma`, `inferno`, `magma`, `cividis`, `coolwarm`, `RdBu_r`, `turbo`, `cubehelix`, `Blues`, `Reds`, `Greens`, `Purples`, `Oranges`, `hot`, `bone`, `Spectral`, `seismic`, `YlGnBu`, `nipy_spectral`, `gist_heat`, `afmhot`, `copper`, `twilight`, `PuOr`, `BrBG`, `PiYG`. `colormap_override` may also be `""` (keep each tool's colormap). |
| `text_replacements` | Text, one `old => new` per line: renames a title, axis label or legend entry in every plot. |
| booleans | `true` / `false` only. |

Do not write `viewer_config`: the app fills it at run time.

## Check

```
python -m json.tool my_style.json
```

Then **Settings › Library › Plot styles**: listed without “invalid”. Select it in **Results &
figures…** and run a tool that draws a plot.

## Share

**Settings › Library › Plot styles › Export…** → one `.zip`; a colleague uses **Import…**.
