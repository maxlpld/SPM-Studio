# Analysis scripts (tools) — how to build one for SPM Studio

**Read this before creating or changing anything in this folder** — whether you are a person or
the AI assistant. This folder is the *Tools* list of SPM Studio: every sub-folder that contains a
valid `module.json` is one tool. New and changed tools appear in the app within a few seconds,
without restarting.

The complete contract (manifest schema, the `ctx` API, parameter types, selections, results) is in
[`README_SCRIPT.md`](README_SCRIPT.md), in this same folder. This page is the checklist that makes
a tool work the first time.

## A tool is one folder with three files

```
my_analysis/
├── module.json     what the tool is: id, name, parameters (JSON, no comments)
├── module.py       the analysis:  def run(ctx): ...
└── README.md       what it does and how — shown by the “Read me” button of the Analysis panel
```

Helper files (other `.py` files, small data files) may live in the same folder. One folder per
tool; never put a tool's files loose in this folder.

### `module.json` — minimum that is accepted

```json
{
  "api_version": "1.0",
  "id": "my_analysis",
  "name": "My analysis",
  "version": "1.0.0",
  "description": "One sentence: what is measured, and the main limitation.",
  "category": "Analysis",
  "mode": "analysis",
  "status": "experimental",
  "entrypoint": "module:run",
  "interaction": "none",
  "snapshot_channels": "selected",
  "requires": ["numpy"],
  "parameters": {}
}
```

Rules that are checked when the app reads the folder (a tool that breaks one is not listed, and
the reason is written in the Logs panel):

- `api_version` is exactly `"1.0"`.
- `id` is lowercase letters, digits and `_`, starts with a letter, 2–81 characters, and is
  **unique** among all tools. Use the folder name.
- `mode` is `"analysis"`. Instrument control does not exist: tools only read saved data.
- `entrypoint` is `"module:run"` (a function `run` in `module.py`).
- `interaction` is `"none"`, `"line_profiles"` or `"histogram_masks"`.
- `status` is `"operational"` once the tool has been checked on real data, else `"experimental"`.
- `parameters`, `selection` and the other optional keys: exactly as described in
  `README_SCRIPT.md`. Do not invent keys.

### `module.py` — minimum that runs

```python
import numpy as np


def run(ctx):
    data = np.asarray(ctx.data, dtype=float)      # selected channel, SI units (ctx.unit)
    ctx.log(f"shape {data.shape}, unit {ctx.unit}")
    ctx.progress(50, "Computing")
    rms = float(np.sqrt(np.nanmean((data - np.nanmean(data)) ** 2)))
    ctx.result_table(["quantity", "value", "unit"], [["RMS", rms, ctx.unit]])
    ctx.progress(100, "Done")
```

- Read inputs only from `ctx` (`ctx.data`, `ctx.geometry`, `ctx.unit`, `ctx.parameters`,
  selections). Never open the user's scan file yourself and never write next to it.
- Write every output inside `ctx.output_dir` and register it with `ctx.result_file(path)`.
- Report progress with `ctx.progress(percent, "text")`: it drives the progress bar of the
  Analysis panel. Use `ctx.log("text")` for anything the user should read.
- Figures: use the display the user set on the scan and the app's export settings (see
  “Figures” in `README_SCRIPT.md`); save SVG by default.
- No network, no hardware, no installing packages. List every import that is not in the Python
  standard library in `requires`.

### `README.md` — required

The app opens it from the Analysis panel. Write it for a colleague who has never seen the tool:

1. **What it does** — the measured quantity, in one paragraph.
2. **How** — the method, the formulas or the reference, the assumptions.
3. **How to use it** — which channel, which selection to draw, in which order.
4. **Parameters** — one line per parameter: meaning, unit, sensible range.
5. **Outputs** — every file and table it writes, with units.
6. **Limits** — when the result should not be trusted.

## Check before saying it is finished

Run these with the Python that runs SPM Studio (the assistant is given its path), from the tool
folder:

```
python -m json.tool module.json          # valid JSON
python -m py_compile module.py           # valid Python
```

Then, in the app: the tool is in **Tools** (if not, the reason is in the Logs panel), open a scan,
select the tool, click **Run analysis**, and read the Logs panel.

## Changing or sharing a tool

- Changing an existing tool: copy the file to `name.bak` first, and raise `version`.
- Never edit another tool to make yours work.
- Sharing: **Settings › Library › Analysis scripts › Export…** writes one `.zip` that a colleague
  installs with **Import…** in the same place.
