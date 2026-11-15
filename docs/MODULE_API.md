# Module API v1.0

Native module folders contain `module.json` and the manifest's entrypoint Python
file (default `module.py:run`). `registry.discover_modules()` scans manifest
JSONs **without importing any Python code**. `mode=instrument` is rejected;
independent untrusted Python executes only after run confirmation.

At Run, the host writes a unique directory containing `arrays.npz` and
`context.json`. NPY keys are `channel name|forward/backward`, and the currently
selected key is the only array replaced by user-selected non-destructive
processing; other traces are immutable-source arrays. The context also carries per-channel geometries and refuses cross-channel arrays with differing dimensions/extents. This is a versioned
snapshot, not a writable session model. Do not share it with unknown scripts.

Run subprocess command:

```bash
python -u -m spm_studio.core.module_runner \
  --entry-file /path/to/module.py --function run \
  --context /path/to/run/context.json
```

The imported file runs only inside this separate Python interpreter. The
context is loaded by `spm_studio.core.module_api.from_snapshot()` and passed to
`run(ctx)`. No GUI widgets are provided. See `scripts/README_SCRIPT.md` for
exact fields/methods, schema, and two executable module examples.

The default worker protocol is one event per stdout line:

```text
SPM_EVENT {"type":"progress","value":50,"message":"Fitting"}
SPM_EVENT {"type":"result_file","path":"/absolute/output.png","title":"Fit"}
SPM_EVENT {"type":"table","title":"Results","columns":["A"],"rows":[[42]]}
SPM_EVENT {"type":"overlay","primitives":[{"type":"line","points_px":[[1,2],[3,4]]}]}
SPM_EVENT {"type":"error","message":"Exception type and details"}
SPM_EVENT {"type":"finished","status":"success"}
```

Unstructured stdout/stderr is preserved in the log. Logs are saved as `run.log`
with visible progress and cancellation. A traceback is printed on exception
and the process exits nonzero. Scripts can use `ctx.log()`, `ctx.progress()`,
`ctx.result_file()`, `ctx.result_table()`, `ctx.overlay()` as helpers.

**Limitations in v1.0 implementation:** `preview(ctx)` is a reserved optional
entrypoint, not scheduled automatically; no custom Qt widgets; analysis jobs
run serially in the UI; graceful cancellation sends `terminate()` then `kill()`
after 2 seconds; external script compatibility is not a safe sandbox; run
snapshots include every currently decoded same-scan channel and can be large.
Newer APIs must add features by version rather than silently passing private
window objects into modules.
