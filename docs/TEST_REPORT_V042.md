# v0.4.2 verification

Executed with the available Python packages in a non-GUI build environment:

```
PYTHONPATH=src pytest -q
53 passed, 1 skipped
```

The skipped suite requires `PySide6` and a running Qt GUI and must be repeated
on the target Ubuntu Wayland/XWayland session. No test with actual instrument
SXM/GWY files or pixel-by-pixel numerical reference output was possible here.

Tests cover the native readers, manifest discovery, ROI geometry, output
format selection, composite CPD masked-image filename, mask pixel inclusion,
Gaussian fits, factory script update hashes and local-edit preservation.

Manual acceptance checklist (Linux workstation):

1. Select CPD histogram, create a named mask, and draw a spatial rectangle;
   drag all eight handles and confirm each moves the intended boundary only.
2. Delete region, Undo, Clear, repeat. Confirm range masks remain untouched
   by removing a spatial selection; click Undo mask edit to reverse range edits.
3. Run CPD on Bias forward/backward and inspect generated figure with the
   source filename and `with_masked_image` suffix. Compare the raw and masked
   populations with original script output on the same scan.
4. Open Flake height, draw multiple lines, drag individual endpoints, delete
   the selected line and run. Compare separate left/right heights.
5. Open KPFM edge and lattice and confirm the same selection toolbar is
   available, without opening other GUI windows.
6. Open Scripts folder, verify the modules and README are present and that
   locally customized module files were not silently replaced.
7. In Options select PNG/PDF/both and first-result display; run a module for
   each configuration and confirm result locations under the scan folder.

Scientific limitations and outstanding ports are listed in
`docs/WORKFLOWS_V042.md`.
