# Verification report — SPM Studio 0.0.1 (2026-11-15, first GitHub release)

0.0.1 is the first release from the GitHub repository: the same application as internal build 0.8.3
(the three 0.8.3 platform archives were byte-identical, 435 files), consolidated into one source tree, with
private-repository support for installs and updates and a tested release workflow. Build sandbox: Linux,
Python 3.13, **no PySide6, no network, no GitHub account**.

| Check | How | Result |
|---|---|---|
| Full test suite, unprivileged user (so installer tests run) | `python -m pytest -q -rs` | **270 passed, 0 failed, 32 skipped** (26 need PySide6/CairoSVG; 6 need developer-only reference data or cover retired 0.5.x code, each with its reason) |
| Same suite as root | | 264 passed, 0 failed (installer tests skip: the scripts refuse root by design) |
| Before the changes (0.8.3 as supplied) | same command | 8 failed: stale module count (6 vs the 7 shipped tools), fixtures from the original developer machine, tests needing PySide6; the old CI also excluded `test_branding_v054.py` |
| Private repository updates | `tests/test_v001_github_private_release.py` with a fake private GitHub API and a separate fake download host | PASS: 404 without sign-in with instructions; token sent only to the API and **not** to the redirect host; API zipball and API changelog for private repos; 401 message; token order (env vars, then `gh auth token`) |
| `get-spm-studio.sh`, private | stubbed `curl`, as a normal user | PASS: authenticated API download; token never on a command line; temporary header file removed; clear message without sign-in; refuses the unconfigured placeholder |
| Release tooling | `set-repo`, `check-repo`, `check-tag`, `check-changelog`, `archive`, `bump` | PASS: one cross-platform `SPM-Studio-<v>.zip`, exec bits kept, no caches/secrets |
| Packaging | `pip wheel --no-build-isolation .` | PASS: `spm_studio-0.0.1`, entry points `spm-studio`, `spm-studio-check`, package data present |
| Imports | every module under `src/spm_studio` | 55 import; 26 need PySide6 (not installable here); 0 other failures |
| Syntax | `compileall` (src, scripts, tests, tools), `bash -n` on all shell scripts, YAML parse of the workflows | PASS |
| Git readiness | `git init && git add -A` on a copy | 438 files tracked, nothing needed ignored, no line-ending warnings |
| Secrets / personal data | pattern search (API keys, tokens, private keys), personal paths, e-mail addresses, data files | none found |

**Not verified here** (needs a real environment; check after the first push):

- the GUI, `--smoke-test` and Qt tests (need PySide6 — they run in GitHub Actions);
- `get-spm-studio.ps1` and the Windows/macOS installers on real systems (PowerShell syntax is parsed in CI);
- the workflows on GitHub itself (YAML parses and the structure is tested, but they have not run on GitHub);
- real downloads from github.com, public or private, and real `gh` sign-ins.

## Internal build 0.8.3 report (2026-11-14)

0.8.3 adds install/update from GitHub. Verified here (no internet, no GitHub account in the build sandbox):

| Check | How | Result |
|---|---|---|
| Update check | `tests/test_v083_updates.py` against a local fake GitHub API: releases (drafts, pre-releases, non-version tags ignored; notes of every newer version), tags-only fallback with CHANGELOG sections, unconfigured repository, CLI `--check`, daily-check state | PASS |
| Download | fake archive served over HTTP: extraction, exec bits kept, version must match the announced tag, path traversal refused | PASS |
| One-line installer (Linux/macOS script) | `get-spm-studio.sh` run end to end with a stubbed `curl`: release tag chosen, archive downloaded and extracted, that version's installer executed with the options; `SPM_VERSION` pinning; no prompt or `sudo` without a keyboard; tag parsing with compact and pretty JSON (rc tags, 0.8.10 > 0.8.9) | PASS |
| Update dialog + startup check | fake-Qt harness: available / up to date / offline states, Install update path, auto-check switch | PASS |
| Release workflow helpers | `tools/release_tools.py check-tag/notes`; all project files are committed by git (nothing needed is in `.gitignore`) | PASS |
| `get-spm-studio.ps1`, real GitHub, real Windows/macOS | not executable here | to check after the first push (see docs/RELEASING.md) |

## 0.8.2 report


Build machine: Linux, Python 3.13, Node.js 22.23, **no PySide6 wheel and no internet for pip/npm**
(so no real Qt window, no real npm/nodejs.org/Ollama download, no real provider account here).

| Check | How | Result |
|---|---|---|
| Secrets / private data in the release | regex scan of every file for API-key/token/private-key patterns, e-mail addresses, home paths, host name, owner model IDs; `tests/test_v082…::test_release_tree_contains_no_secrets_or_private_state` (also run on the final zips) | **clean** — only the documented dummy `sk-something-should-never-go-in-config` in an older test and `pass@example.com` placeholders |
| Static checks | `python -m compileall`, `ruff --select F821,E9,F63,F7` over `src tests install.py tools`; `bash -n` on all shell scripts | PASS |
| Full suite (as an unprivileged user, so installer tests run) | `python -m pytest -q --ignore=tests/test_branding_v054.py` | **239 passed, 25 skipped, 9 failed** — the 9 are the pre-existing environment failures of 0.8.1 (missing `legacy_reference/*.zip` and demo scans, no CairoSVG/PySide6, two 7-vs-6 module counts) |
| New 0.8.2 tests | `tests/test_v082_ai_setup_cross_platform.py` | **19 passed**: Node LTS selection + Pi minimum, archive path-traversal refusal, Windows `.cmd` shim → `node entry.js`, symlink/shebang resolution, terminal scripts, hardware survey, private `auth.json` (0600, never returned), `--list-models` parser, router JSON per pi-shift-router CONFIG.md schema, config only in the private agent dir with `~/.pi` sentinel unchanged, **end-to-end with a fake Pi CLI run by real Node** (install extensions, list models, smoke test, sign-in script), hardware-aware 3-profile recommendation, offline catalog fallback, **Judge proxy against a fake Ollama server** (think:false, JSON mode, SSE stream + non-stream translation, usage, /v1/models), Claude Code and Codex event parsing + argv, installer presence/safety |
| Real Claude Code CLI | the flags used (`-p --output-format stream-json --verbose --include-partial-messages --permission-mode plan`) checked against `claude --help` and a real run whose JSONL was fed to the parser | flags accepted; `system/init` session/model parsed; an authentication failure (no account in the sandbox) surfaced as an error and the turn ended cleanly |
| Qt glue (setup dialog, wizard, dock) | harness with a stateful PySide6 stand-in: all 5 starting paths, Save validation, the full wizard (install with router → API key → model list → local Judge with 3 profiles → download & test → live test → Finish), saving the managed backend, backend factory for managed Pi / Claude Code / Codex | PASS; found and fixed two real issues (busy state read from `QThread.isRunning`, worker results delivered to closures) |
| macOS installer | executed as an unprivileged user with a stubbed `uname`: `--dry-run`, Python discovery, bash-3.2-safe timeout helper, app bundle (Info.plist parsed with plistlib), uninstaller marker refusal / wrong confirmation / apply | PASS |
| Windows installer | **no PowerShell available here**: reviewed line by line for PowerShell 5.1 compatibility (no `??`/ternary/`&&`), brace/parenthesis balance checked, Windows code paths of the Python side simulated (`pi.cmd` resolution, `.cmd` sign-in script) | reviewed, not executed |

Not verified here and therefore guarded on your machine: `install_spm_studio_*` run the extended
`--smoke-test` (now also building the setup wizard, the Judge proxy and the hardware survey) and must print
`SMOKE PASSED` before anything is activated. Real downloads (nodejs.org, npm, Ollama), a real browser
sign-in, real `pi-shift-router` routing with a GPU Judge, and the Windows/macOS installers on real
machines are the remaining first-run checks.

## 0.8.1 report

0.8.1 additions checked here: 219 passed / 27 skipped / same 8 pre-existing environment failures; with the
PySide6 stand-in, a module folder written into the scripts folder is detected by the live watcher and logged
as "New tool available in Tools: Hello SPM"; the Pi briefing file is generated with the real paths. The
installer self-test now also creates a temporary tool and requires it to appear live. Not run here: a real
Pi session with tools (needs your Pi login).

## 0.8.0 checks

## What was actually executed for 0.8.0 (build machine: Python 3.13, **no PySide6 available, no network**)

| Check | Command / method | Result |
|---|---|---|
| Syntax of all sources | `python -m compileall -q src scripts/lattice_measurements scripts/molecule_placement` | PASS |
| Undefined names / syntax errors | `ruff check --select F821,E9,F63,F7 src scripts/... tests` | PASS (0 findings) |
| Full test suite | `PYTHONPATH=src python -m pytest -q --ignore=tests/test_branding_v054.py` | **217 passed, 27 skipped, 8 failed** |
| New 0.8 tests | `tests/test_v080_export_parity_and_design.py` | 15 passed, 1 skipped (Qt pixel-parity test needs PySide6) |
| Lattice + molecule tools end to end, Qt renderer stubbed | scratch harness running `module.run()` of both tools, `render_molecules`, and `preview_worker.py` as a real subprocess | PASS: only `07_reference_scan_lattice_overlay.svg`, `cropped_scan.npy`, `lattice_result.json` are written; viewer colormap (magma in the test) reaches figure, manifest, molecule figure and live preview; molecule figure uses the requested formats |
| GUI construction logic | `MainWindow()`, theme switching, menus, AssistantDock methods, SetupDialog (4 modes), PlotOptions, PublicationDialog, every module's Tool settings — executed against a permissive **PySide6 stand-in** that raises on any of our own attributes used before assignment | PASS (only stand-in artefacts such as JSON-encoding a stub value) |
| Installer | `bash -n`; `--dry-run` and `--prune-old` executed as an unprivileged user on a fake release tree | PASS: 0.7.0 release removed, active 0.8.0 and user data kept |

The 8 failures are **pre-existing and environment-related** (identical on the unmodified 0.7.0 source):
missing `legacy_reference/*.zip` and `~/demo-projects` fixtures, no CairoSVG/PySide6, and two module-count
assertions (7 vs 6) that predate this release.

## Not verified here — verified on your machine by the installer

PySide6 could not be installed in the build sandbox, so **no real Qt window was opened** and the real Qt
renderer was not run here. `install_spm_studio_clean.sh --stage` therefore runs an extended
`--smoke-test` (offscreen, disposable folders) that must print `SMOKE PASSED` before 0.8.0 can be activated:
all bundled themes, all menus, Assistant dock float/re-dock + rendering + setup dialog, Results options, the
Export-panel renderer writing SVG/PDF/PNG with lattice vectors and a decoration layer, and the SVG result
preview. If any check fails the command exits non-zero and 0.7.0 stays active.

Still not covered automatically: visual judgement of the new design, a real Pi 1.5.2 session (RPC flags
`--session-id` / `--no-approve` are taken from the current Pi CLI docs, with an automatic compatibility retry),
real provider accounts, GPU Judge. `tests/test_script_figure_is_pixel_identical_to_export_panel` checks
pixel parity between an analysis figure and a one-panel Export… when PySide6 is installed:
`python -m pytest -q tests/test_v080_export_parity_and_design.py`.

---

# Previous report — SPM Studio 0.7.0

## Origin, isolation and source scope

**Input:** `Research_Studio_v36_Patched.zip` plus `SPM_Studio_AI_Agent_Complete_Implementation_Brief.md`.

The input archive was listed before extraction and examined for dangerous ZIP paths and symlink entries. Only the `apps/spm-studio` application was extracted into the new `SPM_Studio/` source tree. Four imported helpers from `packages/research-core/research_core` were copied under `src/spm_studio/shared/` (appearance, dialogs, UI strings, record store), with imports and the owned record directory updated. The archive's license was retained. No old source tree, virtual environment, token, user state or unrelated Research Studio application has been copied into this release. The original upload was not modified.

GUI: **PySide6 / Qt 6**; source package: `src/spm_studio`; installed entry point: `python -m spm_studio`; scientific module API: manifest `api_version: "1.0"`, `module.json` and `module.py`, registry `spm_studio.core.registry`. Python 3.11+ supported by the package; Ubuntu user installation is the documented deployment target. New config/data names are `spm-studio-ai`, distinct from old `spm-studio`.

## Tests actually performed in the build environment

The available runtime was Python 3.13 with pytest; the runner was an unprivileged user for destructive-script tests.

| Check | Executed command / method | Actual result |
|---|---|---|
| Python syntax | `python -m compileall -q src` | **PASS** |
| Installer and uninstaller shell syntax | `bash -n install_spm_studio_clean.sh uninstall_old_research_studio.sh uninstall_new_spm_studio.sh` | **PASS** |
| New integration, API mock server, cleanup dry-run/apply, existing science regressions | `PYTHONPATH=src python -m pytest tests/test_ai_integration_headless.py tests/test_ai_api_mockserver.py tests/test_ai_cleanup_installer.py tests/test_processing.py tests/test_geometry.py tests/test_registry.py tests/test_readers.py tests/test_reader_binary.py tests/test_export.py tests/test_diagnostics.py -q --disable-warnings` | **36 passed, 1 warning**, 4.93 s |
| Direct API adapters | Real HTTP requests to a *local mock server* (not a cloud account); exercises OpenAI-compatible, Anthropic, Gemini and Ollama JSON parsing | **PASS** within pytest above |
| Module pipeline | Create staged module, syntax/manifest preflight, install into temp user scripts, discover without restart and move to backup | **PASS** within pytest above; **not** a real GUI hot-refresh test |
| Old install cleanup | Temporary simulated Research Studio installation: dry-run leaves it alone; `--apply` with confirmation removes only verified old application and retains dummy `~/.pi` and custom scripts | **PASS** within pytest above |
| Installer dry-run | Actual installer `--dry-run` in temporary HOME | **PASS** within pytest above |
| Scientific logic | Geometry, processing, registry, SXM reader/binary, export, diagnostics | **PASS** for selected 24 baseline test cases |

A run of the larger original test suite was attempted but timed out before completing; **no result is claimed for that full suite**. No package-dependency downloads were possible from the build runner (outbound package index unavailable), and **PySide6 is not installed in this runner**.

## Explicitly NOT verified here

- Actual Qt desktop launch, docking/undocking and saved window restoration, or automatic `--smoke-test` from a newly installed venv. The Ubuntu installer **does** run the true Qt offscreen smoke before the old app is touched. Treat that result as a mandatory gate, not as an already completed test.
- Connection, streaming, cancellation and session recovery against the owner's real Pi 1.5.2 configuration, real extensions or provider authentication. Pi uses the documented `pi --mode rpc` JSONL protocol, but there was no local Pi binary or authenticated account available to test here.
- Real OpenAI/Anthropic/Gemini/OpenRouter/Ollama request, model catalog, billing, rate-limit failover, live local Judge, GPU capability or local Judge latency/quality. No providers, instruments or real credentials were accessed.
- Real GUI plugin menu refresh after an asynchronously generated plugin; only the underlying manifest registry/installer was verified headlessly.
- Code correctness of an AI-generated scientific module, reliable hardware isolation, and the full end-to-end autonomous developer workflow on a user workstation.
- Actual Ubuntu 24.04 / 26.04 machine install or physical microscope interaction. No hardware was controlled in this build.

## Implemented, with the following scope limits

- **Native Qt chat** dock and floating window, local history, nonblocking Pi QProcess JSONL events, direct API worker, visible status, opt-in scan/file context and task log are implemented but not Qt-runtime tested here.
- **Existing Pi connection** does not edit global `~/.pi` files; existing Pi routing and subagent extensions are Pi-owned, rather than configurable by a fully verified SPM-specific extension API. Pi's TUI-only extension dialogs are not implemented.
- **Optional new Pi install** uses a per-user npm prefix *after consent*. Not end-to-end tested in this runner. Node/npm must be supplied by the user.
- **Direct chat** is asynchronous HTTP request/response; it is not token-streamed and does not offer code editing or file tools by itself. Multiple provider configurations, a bounded fallback chain and manual choices are supported; official OAuth flows / live model discovery are not implemented.
- **Judge** inspects memory, GPU heuristics and locally installed Ollama tags. It does not consult a fresh cloud model catalog, verify three new installable model recommendations, or provide trustworthy benchmark estimates unless an actual local benchmark succeeds.
- **Background coding** is performed using separately approved Pi tools in an app-owned staging directory; source validation checks manifests and Python syntax before user-script registration. This is **NOT an operating-system sandbox**, nor an adequate scientific validation of arbitrary generated code. Pi may have user-level filesystem/process access. Use only with a trusted configuration and reviewed module source. Running any live laboratory hardware command is outside the supported workflow.
- **Hot-loading** means registry discovery plus a UI refresh of the manifest-backed module selector, not in-process hot-swap of the main application's Python/UI classes. A main-framework edit still requires a controlled update/restart. Rollback is a non-destructive move to a backup; there is no elaborate transactional dependency manager.
- **Natural-language settings changes**, a fully verified native routing diagram, rich budget control, fully functional multi-agent orchestration controls and a complete scripted migration of old personal settings are **not implemented**; do not treat the 572-line full specification as wholly passed.

## Safe installation/verification gate on Ubuntu

1. Run `bash uninstall_old_research_studio.sh --dry-run` and review the exact old application paths found.
2. Run `bash install_spm_studio_clean.sh --stage`; it creates an isolated new virtual environment and runs `QT_QPA_PLATFORM=offscreen python -m spm_studio --smoke-test` using *temporary* application config directories. **If this fails, STOP. Keep your old working install.**
3. Only if staging passes, choose whether to run `bash uninstall_old_research_studio.sh --apply` and type `REMOVE OLD APPS`. If no verified old component is found, do not manually force arbitrary deletions.
4. Run `bash install_spm_studio_clean.sh --activate` and launch `~/.local/bin/spm-studio`.
5. Confirm `~/.local/share/spm-studio-ai-app/releases/0.7.0/venv/bin/python -c 'import spm_studio; print(spm_studio.__file__)'` points to the new app, not the Research Studio source tree. Verify core scan viewer and AI panel manually on your own example data.
6. Configure the AI backend only after confirming ordinary scientific functionality; test your Pi or API with a benign prompt before authorizing coding tools.

The cleanup utility intentionally preserves unknown launchers, user content, old `~/.config/spm-studio`, old `~/.local/share/spm-studio`, local Pi/Ollama data, personal credentials and manually checked-out source folders. A generic global pip uninstall or sweeping home-directory deletion would not be safe and is **not** performed.
