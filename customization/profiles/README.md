# Profiles — how to build one for SPM Studio

**Read this before creating or changing a file in this folder** (person or AI assistant).

A profile is one `.json` file here. It says which channels to show and, for each of them, the
processing steps, the colormap, the contrast and the colourbar title. It is chosen in the profile
list of the top bar and applied with **Apply**. It never changes the scan file.

File name = the name shown in the list (`My_STM.json` → “My STM”). Use letters, digits, `-`, `_`.

## Complete example

```json
{
  "schema_version": 1,
  "name": "My_STM",
  "channel_contains": "Z",
  "visible_channels": ["Z", "Current"],
  "auto_crop_incomplete": false,
  "style": {
    "colormap": "gray", "range_mode": "percentile", "low": 1, "high": 99,
    "gamma": 1, "scale_bar": true, "colorbar": true
  },
  "processing": [
    {"operation": "plane", "params": {}, "enabled": true},
    {"operation": "row_median", "params": {}, "enabled": true}
  ],
  "channel_styles": {
    "Z":       {"colormap": "gray",    "range_mode": "percentile", "low": 1, "high": 99, "gamma": 1, "scale_bar": true, "colorbar": true},
    "Current": {"colormap": "viridis", "range_mode": "percentile", "low": 1, "high": 99, "gamma": 1, "scale_bar": true, "colorbar": true}
  },
  "channel_processing": {
    "Z": [
      {"operation": "plane", "params": {}, "enabled": true},
      {"operation": "row_median", "params": {}, "enabled": true},
      {"operation": "fix_zero", "params": {}, "enabled": true}
    ],
    "Current": []
  },
  "channel_titles": {"Z": "$Z$", "Current": "$I$"}
}
```

## Keys

| Key | Required | Meaning |
|---|---|---|
| `schema_version` | yes | Always `1`. |
| `name` | yes | Same as the file name without `.json`. |
| `channel_contains` | no | Channel made active when the profile is applied (fragment of its name). |
| `visible_channels` | no | Channels shown side by side. Names or fragments, in display order. |
| `style` | no | Default display for channels without their own entry. |
| `processing` | no | Default steps for channels without their own entry. |
| `channel_styles` | no | Display per channel. Key = channel name or fragment. |
| `channel_processing` | no | Steps per channel, applied **in the listed order**. `[]` = raw data. |
| `channel_titles` | no | Colourbar title per channel. LaTeX between `$ $`, single backslash once parsed (write `"$\\Delta f$"` in JSON). |
| `auto_crop_incomplete` | no | `true`: crop the unmeasured part of an aborted scan when applying. |
| `multipass` | no | `true` (Nanonis Multipass): every `visible_channels` entry shows **all its passes** (`Z [P1]`, `Z [P2]` …), titles start with `P1 · `, `P2 · `, and the log lists each pass's bias, setpoint, Δz … read from the scan header. Default: on when the name contains “Multipass”. |

Channel fragments are matched without regard to case or punctuation (`"Bias"` matches `Bias (V)`).
Use the channel names of the user's own scans (they are listed in the Inspector).

### Style

- `colormap`: `gray`, `gray-inverted`, `viridis`, `magma`, `copper`, or the **file name** of a
  colormap in the `colormaps` folder next to this one (for example `"Gwy - Caribbean.csv"`).
- `range_mode`: `percentile` (`low`/`high` in 0–100), `full`, `manual` (`low`/`high` in SI units of
  the channel), `sigma` or `mad` (mean/median ± N). For `percentile` and `manual`, `high > low`.
- `gamma` > 0 (1 = linear). `scale_bar`, `colorbar`: `true` / `false`.

### Processing steps

Each step is `{"operation": NAME, "params": {...}, "enabled": true}`. Operations and their params:

| Group | Operations |
|---|---|
| Levelling | `plane`, `polynomial_2d` (`degree` 0–5), `row_mean`, `row_median`, `column_mean`, `column_median`, `line_poly` (`degree` 0–6), `median_difference`, `median_difference_columns` |
| Zero | `fix_zero`, `zero_mean`, `subtract_median` |
| Artefacts | `median_scar` (`threshold`), `remove_stripes` (`sigma`), `despike` (`size`, `threshold`) |
| Filters | `gaussian`, `mean_filter`, `median_filter`, `minimum_filter`, `maximum_filter`, `highpass`, `unsharp` (`amount`), `dog` (`sigma`, `sigma2`), `laplace`, `sobel` |
| Arithmetic | `invert`, `absolute`, `square`, `sqrt`, `multiply` (`factor`), `add` (`value`), `clip` (`low`, `high`), `threshold` (`value`) |

Use only these names: an unknown operation makes the scan fail to display. When in doubt, set the
steps up in the Inspector and use **Apply ▾ › Save current display as profile…**, then edit the
saved file.

## Check

```
python -m json.tool My_STM.json
```

Then **Settings › Library › Profiles**: the file is listed without the word “invalid” (the reason
is shown otherwise). Select it in the top bar and click **Apply** on a scan.

## Share

**Settings › Library › Profiles › Export…** writes one `.zip`; a colleague uses **Import…**. If the
profile uses a colormap file, export that colormap too.
