# WHAT I WANT THIS MODULE TO DO

[USER WRITES THE REQUEST HERE: inputs, analysis, parameters,
expected numerical results, plots, overlays, exports.]

---

# INSTRUCTIONS TO A CODING AI — SPM MODULAR STUDIO NATIVE MODULE

Build **only a new module folder**. Do not modify the core, main window or any
other module. If the API lacks a needed feature, describe the gap and propose a
versioned API extension rather than editing unrelated files. Keep it small.

Target Module API **1.0**, Python **3.11+**. Copy the folder to
`~/.local/share/spm-studio/scripts/my_analysis/` and choose **Refresh modules**.
The module should have: `module.json`, `module.py`, `README.md` and, where
appropriate, `test_module.py`. Other algorithm files may be in the same folder.

## Manifest schema

Use valid JSON (no comments):

```json
{
  "api_version": "1.0",
  "id": "my_analysis",
  "name": "My analysis",
  "version": "1.0.0",
  "description": "Short scientific purpose and limitations",
  "category": "Analysis",
  "mode": "analysis",
  "status": "experimental",
  "entrypoint": "module:run",
  "interaction": "none",
  "snapshot_channels": "selected",
  "requires": ["numpy"],
  "parameters": {
    "threshold_si": {
      "type": "float", "label": "Threshold (SI)",
      "default": 1e-10, "min": 0
    },
    "direction": {
      "type": "choice", "label": "Trace", "default": "forward",
      "choices": ["forward", "backward"]
    }
  }
}
```

Set `snapshot_channels` to `selected` (loads selected channel, both traces; fast) or `all` (requires other simultaneous channels and may allocate much more memory). This is declared by the module itself, not hard-coded in Studio.

### Shared GUI selections (no module-specific Qt code)

Declare the optional `selection` object in `module.json`:

```json
"selection": {
  "tools": ["line", "rectangle", "point"],
  "multiple": true,
  "preview": "profiles"
}
```

- `tools` contains zero or more of `line`, `rectangle`, and `point`.
- `multiple: true` retains completed selections. `false` replaces the last
  selection. These are controls in the **Tool settings** panel, with **Delete
  selected**, **Undo last**, **Clear all**, and **Pan**; individual ROI handles
  can be dragged. The selection list highlights the chosen selection.
- `preview: "profiles"` draws live data profiles for line ROIs and requires
  `line` among `tools`.
- `preview: "histogram"` draws a live, bounded histogram. With
  `interaction: "histogram_masks"`, this also exposes named value-range masks.
- `preview: "none"` provides a selection editor without a chart.

The old `interaction: "line_profiles"` and `interaction: "histogram_masks"`
values remain supported. New modules should include a `selection` declaration
and set `interaction` to `histogram_masks` only if they need the special
named-value-mask editor; other tools may use `"none"`.

For example, to request a rectangular ROI with a live histogram:

```json
"interaction": "none",
"selection": {"tools": ["rectangle"], "multiple": false, "preview": "histogram"}
```

`ctx.roi` is the current/most recently drawn selection; `ctx.rois` is a list
of retained selections (excluding the single primary ROI). A module needing
multiple lines should use `ctx.rois`, appending `ctx.roi` only if it is not
already present. These are source-image pixel coordinates, `(column, row)`,
not window/display coordinates. The core provides reusable
`analysis_utils.rectangle_slices()`, `region_mask()`, and
`profile_between()`; ROI operations do not modify the input scan array.

When `histogram_masks` is used, declare `bins`, `populations`, and
`masks_json` parameters. The mask editor supplies a list of JSON objects:
`name`, `low`, `high`, `color`, `populations`, and optional `peaks` (SI values).
The module controls the actual scientific fit and exports. The GUI does not
magically add missing analysis methods. Avoid importing Tkinter or opening
secondary GUIs. If a new selection type is needed (freehand polygon, nested
region, FFT point), document an API extension instead of inventing a key.

Allowed simple parameter types: `integer`, `float`, `bool`, `string`, `choice`,
`file`, `folder`, `channel`, `direction`, `color`, `region`. Optional `min`,
`max`, `description`, `choices` as relevant; use SI values for quantitative
inputs and include units in labels. No arbitrary executable content in manifest.
Native manifest discovery does **not** import Python code. Place module folders in the directory opened by **Tools → Open Scripts folder** and choose **Refresh modules**. Deleting the folder removes the tool from the sidebar after refresh. Startup copies bundled examples only if missing; local edits are never overwritten.

## Python contract

`module.py` must expose `def run(ctx):` (optional `def preview(ctx):`, only to be
used when the host calls it explicitly; automatic preview hooks are not part
of this version). `ctx` is a `spm_studio.core.module_api.ModuleContext`:

- `ctx.scan_path`: `pathlib.Path` of original file.
- `ctx.channel`, `ctx.direction`, `ctx.unit`: requested image and raw SI unit.
- `ctx.data`: selected (possibly processed) 2-D NumPy array; never mutate it.
- `ctx.image(channel=None,direction=None)`: other raw available images of the
  **same** scan, explicit trace; missing requests raise KeyError.
- `ctx.geometry`: `Geometry` with `shape`, `size_m` (x/y), `center_m`,
  `angle_deg`, `scan_direction`, `calibrated`; `pixel_to_local(row,col)`,
  `local_to_pixel(x_m,y_m)`, `pixel_to_sample()` and `sample_to_pixel()`.
  Geometry/angle may be unknown; do not fabricate them.
- `ctx.roi`: optional `ROI(kind, points_px)`; points in `(column,row)` pixels.
- `ctx.rois`: retained ROIs for modules that enable multiple selections.
- `ctx.parameters`: validated settings dict; `ctx.processing`: non-destructive
  processing-step snapshot. `ctx.source_paths`: selected dataset paths.
- `ctx.output_dir`: unique directory for this run.
- `ctx.log(message,level='info')`, `ctx.progress(percent,message='')`,
  `ctx.result_file(path,title='')`, `ctx.result_table(columns,rows,title='')`,
  `ctx.overlay(primitives)`.

Overlay primitives are dicts: `type` = `line`, `rectangle`, `point` or `polygon`,
`points_px` = 1–N `(col,row)` points, `color` = `#RRGGBB`, optional `width`.
Use host primitives to draw against the unchanged image coordinate system.
The core's shared `spm_studio.core.plots.plot_style()` context manager and
`analysis_utils.save_plot(ctx,fig,stem)` produce publication PNG/PDF. For
quantitative numerical outputs use `np.save()`/`np.savetxt()` and
`ctx.result_file()`. Do not clip raw data to display colormap ranges. Save
provenance/assumptions in your README and result tables. The host streams
`SPM_EVENT {JSON}` protocol messages to Qt via QProcess.

### Smallest functional example (`module.py`)

```python
import numpy as np
from spm_studio.core.analysis_utils import save_csv

def run(ctx):
    valid = ctx.data[np.isfinite(ctx.data)]
    if not len(valid):
        raise ValueError('Image has no finite pixels')
    value = float(np.mean(valid))
    ctx.result_table(['metric', 'value_SI', 'unit'],
                     [['mean', value, ctx.unit]], 'Mean')
    save_csv(ctx, 'pixels.csv', ['value_SI'], [valid])
    ctx.progress(100, 'Done')
```

### Optional overlay example (`module.py` alternative)

```python
def run(ctx):
    ny, nx = ctx.data.shape
    ctx.overlay([{'type':'line',
                  'points_px':[[0,ny/2],[nx-1,ny/2]],
                  'color':'#ffc044','width':2}])
    ctx.log('Marked scan-center row')
```

Implement robust exceptions with informative text and units. Declare *every*
optional import in `requires` and import heavyweight dependencies only inside
`run`. No hardware or network access at module import. Do not use `input()` for
native modules or Tk/Tkinter inside the Qt process. No auto instrument connect.

Deliver synthetic tests for numeric results, sign conventions, NaNs, dimensions,
forward/backward behavior and ROI-to-physical coordinates. For scientific
migration from old code, use baseline fixtures; preserve the legacy algorithm
until old/new outputs are compared. Include concise README instructions and a
status (operational/experimental/unavailable) justified by actual validation.

**Deliver only the module folder contents**, ready to drop into Scripts.

## Migration and user-edit policy (v0.4.2)

Bundled scripts are templates installed into `~/.local/share/spm-studio/scripts/`.
Only these directory modules are discovered; Studio does not hard-code their
scientific algorithms. First launch installs missing factory modules. An
upgrade from v0.4.1 updates each *unchanged* factory file using its recorded
SHA-256 baseline; anything you modified is kept, and removed modules stay
removed. Backups of replaced originals go under `.factory_backups_v042/`.
To install a version after making local edits, compare its bundled `module.py`
with your edited copy and merge intentionally rather than overwriting it.

Each analysis must use the shared `save_plot(ctx, fig, stem)` API and respect
`ctx.plot_formats`. Never launch viewers from a module; the app has a separate
"Show result after run" option. Save numerical and figure results only into
`ctx.output_dir` and publish them via `ctx.result_file`.
