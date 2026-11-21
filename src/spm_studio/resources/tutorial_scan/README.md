# tutorial_scan — KBr Nanonis demo scans for SPM Studio

This folder is for an **interactive, optional in-app guided tutorial** in SPM Studio.
It contains **exactly three unmodified user-supplied `.sxm` files**, plus an informational manifest and SHA-256 checksums. These scans are *training data*, not automated calibrations or scientific reference standards.

## Included demonstrations

| File | Native acquisition metadata | Good tutorial use |
|---|---|---|
| `20261119-KBr001_008.sxm` | 256 × 256 pixels; 10 × 10 nm; 90°; scan direction down | Import and display the scan; choose a real channel and trace direction; apply a profile |
| `20261119-KBr001_009.sxm` | 256 × 256 pixels; 10 × 10 nm; 90°; scan direction up | Compare direction and channel choice against `_008` |
| `20261119-KBr001_015.sxm` | 192 × 192 pixels; 10 × 10 nm; 0°; scan direction down | Inspect different scan metadata/resolution, and show how incomplete data should be handled |

The `_008` and `_009` file headers report the same nominal scan position. Both are separate acquisitions, so don't assume their measured pixels or forward/backward traces are identical.

The `_015` file contains incomplete scan data in the `Z` channel. SPM Studio should **detect and describe** missing/invalid pixels before proposing an autocrop; never silently fill in, manufacture, or overwrite measurements.

## Guidance for implementation

1. Bundle the `tutorial_scan` folder with application resources, and make it available offline on Windows, Linux and macOS. Do not depend on a user's Downloads folder.
2. Use the real SPM Studio `.sxm` loading pipeline and preserve native metadata, units, scan orientation, and channel labels. Never replace the measured values with synthetic pictures.
3. Only copy scans into a user-controlled tutorial workspace when needed. Treat bundled originals as immutable and never edit raw `.sxm` files.
4. Use real UI actions for tutorial completion: import, select a channel, select/apply profile, open Settings → Library, and inspect script/profile README guides.
5. Use `manifest.json` for resource metadata; use `SHA256SUMS.txt` for integrity verification.

## Provenance and redistribution

The files came from the user-provided KBr scan uploads, recorded on 19 November 2026. Raw Nanonis metadata includes original acquisition paths and instrument settings; check these before redistribution if publishing the tutorial dataset in a public release. No data have been anonymized or manipulated.
