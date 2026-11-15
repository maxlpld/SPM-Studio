# SPM Studio — development history before the first GitHub release

These are the internal builds (0.7.0 – 0.8.3) that preceded the first GitHub release, **0.0.1**.
The numbering was restarted at 0.0.1 for the GitHub project; the notes below are kept unchanged for reference.
They are deliberately not in `CHANGELOG.md`, because the update check reads release notes from there.

## Internal build 0.8.3 — 2026-11-14

### Install and update from GitHub

- **One-command install / update** per OS from the GitHub repository:
  `curl -fsSL …/get-spm-studio.sh | bash` (Linux, macOS) and `irm …/get-spm-studio.ps1 | iex` (Windows).
  They fetch the newest release (or `SPM_VERSION`), then run that version's own installer; on Ubuntu the
  missing Qt packages are offered via `sudo apt`.
- **Settings › Check for updates…** (also in Help): installed vs. latest version and the release notes of
  every newer version; *Install update* downloads the release and runs its installer in a terminal window
  while you keep working; *Open release page*. Optional quiet check once a day at startup with a
  “⬆ … available — what's new?” button in the status bar.
- `spm-studio --check-update` and `spm-studio --update` on every OS.
- Updates are built and self-tested next to the current version; a failed update never breaks it, and no
  user data is touched.
- Maintainers: `.github/workflows/release.yml` turns a pushed `vX.Y.Z` tag into a GitHub Release (notes from
  this changelog, Ubuntu/Windows/macOS zips, SHA256SUMS); `tools/release_tools.py set-repo OWNER/NAME`
  points the whole project at a repository. See `docs/RELEASING.md`.

## Internal build 0.8.2 — 2026-11-14

### Windows and macOS

- Same application, same AI assistant on Windows 10/11 and macOS 12+ as on Ubuntu.
- New installers with the Ubuntu design (isolated release + venv, offscreen self-test before activation,
  previous release kept, `PruneOld`/`--prune-old`): `install_spm_studio_windows.bat`/`.ps1` (Start-menu and
  desktop shortcuts, no admin rights, offers Python 3.12 via winget) and `install_spm_studio_macos.sh`/`.command`
  (`~/Applications/SPM Studio.app` with icon and microphone description, offers python@3.12 via Homebrew).
  Matching uninstallers (dry run by default; user data always kept).
- Agent executables are started portably: Windows npm `.cmd` shims and `#!/usr/bin/env node` scripts are run as
  `node <entry.js>` (no `cmd.exe` quoting, works with a private Node.js); prompts go through stdin.
- Hardware survey for all systems (RAM; NVIDIA, AMD ROCm, Apple-Silicon unified memory, Windows adapters).
- `pythonw`/app-bundle launches without a console no longer fail on `print`; Windows taskbar identity;
  Gwyddion gradient folders of the Windows/macOS installs are found; HTTPS uses `certifi` (python.org macOS builds).

### Guided, automatic AI setup for new users ("Set up Pi")

- Five starting paths: My Pi · **Set up Pi** (pre-selected when no Pi exists) · Claude Code / Codex · Cloud API · Later.
- Guided wizard: private Node.js LTS (nodejs.org, SHA-256 verified) only if needed → Pi from npm → optional
  `pi-shift-router` + `pi-subagents` → browser sign-in (ChatGPT Plus/Pro, GitHub Copilot) detected automatically,
  or API key stored in Pi's private `auth.json` → model list from `pi --list-models`, Fast/Smart chains with
  fallbacks and Eco/Balanced/Performance → local-Judge question → configuration written per the router's
  documented schema → live test message. All in SPM Studio's own `PI_CODING_AGENT_DIR`; `~/.pi` is never touched.
- Local Judge: three hardware-appropriate profiles (fastest / balanced / higher quality) from a dated catalog
  verified against the Ollama registry (exact download size; cached, labelled offline fallback); Ollama install
  offered per OS; model download with real progress; Fast and Smart test prompts through the router's own
  endpoint with decision, confidence and latency.
- In-app no-thinking Judge proxy (localhost only, lives with SPM Studio): replaces a hand-made systemd service.
- New backends **Claude Code** and **OpenAI Codex CLI** (documented headless JSON modes, their own sign-in,
  session continuity, chat-only vs tools mode, Install… and Sign in… buttons). Development tasks work with them too.
- The answering model and the Judge stay displayed separately; the router line shows Fast/Smart/Judge.

## Internal build 0.8.1 — 2026-11-14

- Assistant (Pi) now works as an agent by default: after a one-time confirmation it starts with Pi's file and
  shell tools in the SPM Studio scripts folder instead of a tool-less chat in `ai/chat_workspace`.
- Pi receives an SPM Studio briefing via `--append-system-prompt` (scripts folder, module contract, working
  example, customization folder, app source location, safety rules: offline analysis only, back up before
  editing). Older Pi without that option: the briefing is sent with the first message.
- Tools button in the Assistant header to switch agent tools off / on (the setting is saved).
- Visible activity: progress bar and "Working… N s · using <tool> / Writing the answer"; the floating
  window title shows the elapsed time; Stop is enabled only while working.
- SPM Studio watches the scripts folder: new, edited or removed tools appear in Tools within ~4 s, without
  restart, keeping the current selection; the Logs say "New tool available in Tools: …".
- Self-test also checks live tool detection.

## Internal build 0.8.0 — 2026-11-14

### Analysis figures = Export… (lattice measurements, molecule placement)

- New `spm_studio.core.script_figures`: script figures are produced by `export_publication` itself (one
  panel), so the gap between scan and colourbar, scale bar, fonts, tight page crop and DPI are exactly those
  of **Export…**, using the export preset selected in the header (≥ 1200 DPI, as in the dialog).
- The colormap, contrast mode/limits and gamma are those set on the scan in the viewer (custom and Gwyddion
  palettes included, via the viewer LUT). The "use scan display" switch no longer falls back to gray.
- `lattice_preview.png` and `cropped_scan.png` are no longer written; only
  `07_reference_scan_lattice_overlay.svg` (and `lattice_plus_molecules.svg`) is saved by default.
  Settings › Results & figures › *Save results as* adds PDF and/or PNG. Gwyddion `.gwy` copies and the
  full-scan diagnostic figures are opt-in tool parameters.
- The lattice manifest stores the display style; Export… of a lattice result and Molecule placement reuse it.
  The molecule live preview is shown in the scan colormap.
- Results list / preview / Export dialog support SVG and list each figure once (SVG preferred over PDF).
- Installed 0.7.0 copies of the two tools are upgraded automatically (backup kept); edited copies are kept;
  *Analysis › Restore built-in tools…* forces the update.

### Design and ergonomics

- New token-based design system (`shared/appearance.py`): only five colours per theme, every other colour
  derived; optional `font_family`, `font_size`, `radius`. New themes **Graphite** (default) and
  **Porcelain**; bundled Inter font (SIL OFL); theme-coloured line icons; consistent buttons, inputs,
  check boxes, menus, tabs, scroll bars and dialogs.
- Header reduced to one row: Open, Dataset · profile + Apply ▾ · figure preset + Export · Compare, Assistant.
- One image toolbar: Fit · Line, Region, Keep lines · Crop ▾ · Profiles, Molecules · Back · ‹ ›.
- Menus reorganised without duplicates: File, Scan, Selection, Analysis, View, Settings, Help.
- Inspector reordered (Channel → Display → Processing → Previews), help paragraphs moved to tooltips,
  shorter labels everywhere; duplicated buttons removed (sidebar file actions, crop actions in Image tools,
  metadata button); themes import and apply without restart.

### AI assistant

- Pi extension dialogs (`select/confirm/input/editor`) are answered with `cancelled` — they previously
  blocked Pi forever. Extension notifications are shown; `agent_end` accepted for older Pi; prompts handled
  by extension commands no longer leave the panel waiting; model errors are reported.
- Compatibility retry without `--session-id/--no-approve` for Pi versions that reject them.
- Pi installer uses the current package `@earendil-works/pi-coding-agent` (old name deprecated).
- Session switching no longer restarts Pi on every keystroke; Ctrl+Enter sends; Stop / Reconnect buttons;
  floating window restored on a visible screen; Pi processes stopped cleanly on quit.
- Chat / Develop tabs; the development request has its own field; task log line-buffered.
- Direct API: provider error details shown (redacted), leading assistant turns dropped.

### Installer

- Version-agnostic installer (`releases/<version>`), side-by-side upgrade, `--prune-old` to remove previous
  releases after confirmation; the self-test (`--smoke-test`) now checks themes, menus, assistant, options and
  the SVG/PDF/PNG figure renderer and returns a non-zero status on failure.

## Internal build 0.7.0 — 2026-11-14

- Extracted the original SPM Studio source from the supplied Research Studio v36 archive, including scientific modules, GUI and offline tools; excluded all other applications, DeckCraft, Research Studio runtime and launcher.
- Vendored/refactored the four `research_core` services SPM Studio genuinely needs into `spm_studio.shared`; provenance now stores new records under SPM Studio-owned user data, not the legacy Research Studio database. Existing research data remains untouched.
- Replaced the external `research_assistant.gui` launch with a native floating/dockable `AI Assistant` panel.
- Added real Pi RPC subprocess adapter, per-app session dir, textual streaming, model-state display, cancellation and tool-event log. Existing `~/.pi` authentication/settings are preserved and accessed only by Pi itself.
- Added a first-use setup UI with existing Pi, optional app-local npm Pi install, direct API-only, or skip. API support includes OpenAI-compatible, Anthropic, Gemini, OpenRouter and local Ollama via actual HTTPS/loopback endpoints.
- Added provider/model connection list, opt-in fallback chain, opt-in Ollama Judge inspection/benchmark, configured Fast/Smart tier model selection, separate answering-model/Judge status, OS-keyring/session-only credential handling.
- Added supervised background Pi coding tasks in app-owned staging, manifest/Python syntax validation, explicit approval for installation, live module registry refresh, and non-destructive plugin removal function that moves a module to backup.
- Added separate release-specific, isolated two-stage Ubuntu install, conservative old-app inventory/removal, new-app removal and verified headless tests.

### Migration / limitations

- SPM Studio source and standard user scripts remain, but there is intentionally no dependency on Research Studio. Old app provenance is preserved in the old user-data area and not automatically merged.
- Legacy `install.py` now delegates to the Linux clean installer; obsolete patch updater and old desktop packaging tests are excluded. Existing scientific modules/tests remain.
- This build has **not** been run against a real Qt desktop, a real Pi agent/provider account, a microscope, or a three-profile local Judge on the user's computer. Generated plugins are not OS-sandboxed or scientifically verified just by syntax checking. Read `VERIFY_AND_TEST.md`.
