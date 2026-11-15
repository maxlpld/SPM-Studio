# SPM Studio 0.0.1 — Ubuntu installation

> Windows: see `INSTALL_README_Windows.md` (installer `install_spm_studio_windows.bat`).
> macOS: see `INSTALL_README_macOS.md` (installer `install_spm_studio_macos.sh`).
> The application and the AI assistant are identical on the three systems.
>
> **One-command install / update from GitHub** (any Linux): 
> `curl -fsSL https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.sh | bash` —
> in the app: **Settings › Check for updates…**; terminal: `spm-studio --update`.

## Requirements

- Ubuntu 24.04 / 26.04, Python **3.11+** with `venv` and pip, run as your normal user (never `sudo`).
- Internet for the first dependency installation (PySide6, NumPy, SciPy, Matplotlib …), about 1 GiB free disk space.
- Qt system libraries, if not already present:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip libxcb-cursor0 libgl1 libegl1 libxkbcommon-x11-0
```

The scientific application needs **no** Pi, Ollama, API key or Node.js.

## Upgrade from 0.7.x / 0.8.x (your current install)

0.0.1 is installed **next to** your current release, self-tested, and only then made active. Your scans, results,
scripts, settings, AI conversations, `~/.pi`, Ollama models and API keys are shared and never deleted.

```bash
cd ~/Downloads
rm -rf SPM-Studio-0.0.1
unzip -q SPM-Studio-0.0.1.zip
cd SPM-Studio-0.0.1

# 1. Build 0.0.1 in its own folder and run the offscreen self-test (current version keeps working)
bash install_spm_studio_clean.sh --stage

# 2. Switch the launcher / menu entry to 0.0.1
bash install_spm_studio_clean.sh --activate

# 3. Start it
~/.local/bin/spm-studio
```

When 0.0.1 works for you, remove the older release folders (asks you to type `REMOVE OLD RELEASES`):

```bash
bash install_spm_studio_clean.sh --prune-old
```

`--stage` prints `SMOKE ok …` lines and `SMOKE PASSED`. If it prints `SMOKE FAILED`, **stop**: 0.7.0 is untouched and
still active; send the printed error.

### Setting up the AI assistant

Open **Assistant** (header) → the first time, a dialog offers five paths:

| Choice | For whom | What SPM Studio does |
|---|---|---|
| **Set up Pi** (pre-selected when no Pi is installed) | New to AI agents | Installs a private Node.js (if needed) + Pi + router/subagents, opens the browser sign-in for ChatGPT Plus/Pro or GitHub Copilot or stores an API key, lists your models, asks whether you want a **free local Judge** (hardware check → 3 model profiles → installs Ollama → downloads → real Fast/Smart test), writes the configuration and sends a test message. Never touches `~/.pi`. |
| **My Pi** (pre-selected when Pi is installed) | You already use Pi | Uses your Pi exactly as configured (router, Judge, logins). Nothing is changed. |
| **Claude / Codex** | Claude Pro/Max or ChatGPT subscribers | Uses Claude Code or OpenAI Codex CLI with their own sign-in; Install… and Sign in… buttons. |
| **Cloud API** | Just want chat | Direct OpenAI / Anthropic / Gemini / OpenRouter / Ollama chat, no agent. |
| **Later** | | Assistant off; all scientific tools work. |

Details: `docs/AI_ASSISTANT_SETUP.md`.

### Assistant that creates tools (0.8.1+)

With Pi, the first time you open the Assistant it asks once whether it may work in your SPM Studio
scripts folder (`~/.local/share/spm-studio-ai/scripts`). Answer **Yes**: Pi then starts with its file/shell
tools in that folder and receives an SPM Studio briefing (where tools live, the module contract, a working
example, safety rules). Any new or edited tool appears in **Tools** within ~4 s, without restart. The tools
button in the Assistant header switches this off/on; a progress bar shows *Working… N s · using <tool>*.


### Check that 0.0.1 is the version in use

```bash
readlink -f ~/.local/share/spm-studio-ai-app/current
~/.local/share/spm-studio-ai-app/current/venv/bin/python -m pip show spm-studio | grep -i version
QT_QPA_PLATFORM=offscreen ~/.local/share/spm-studio-ai-app/current/venv/bin/python -m spm_studio --smoke-test
```

The first line must end in `releases/0.0.1`, the second must show `Version: 0.0.1`.

### What changes in your user folders on first start

- Lattice measurements / Molecule placement scripts in `~/.local/share/spm-studio-ai/scripts/` are updated
  **only if they are the unmodified 0.7.0 files** (backup: `scripts/.factory_backups_v080/`). If you edited them,
  your copy is kept; use **Analysis › Restore built-in tools…** to replace it (a backup is still made).
- The two old factory themes `default_dark.json` / `default_light.json` are moved to
  `~/.config/spm-studio-ai/customization/themes/.factory_backups_v080/` if unmodified, and the new **Graphite**
  (dark) / **Porcelain** (light) themes are added. Personal themes stay.

## Fresh install (no previous SPM Studio)

```bash
cd ~/Downloads
unzip -q SPM-Studio-0.0.1.zip
cd SPM-Studio-0.0.1
bash install_spm_studio_clean.sh          # = --stage then --activate
~/.local/bin/spm-studio
```

Coming from the old **Research Studio**? Inventory first, remove only after review:

```bash
bash uninstall_old_research_studio.sh --dry-run
bash uninstall_old_research_studio.sh --apply      # type: REMOVE OLD APPS
```

## Using the new defaults

- **Analysis figures** (Lattice measurements, Molecule placement) are drawn by the same renderer as
  **Export…**: same page preset (the one selected in the header), scan/colourbar gap, scale bar, fonts, and
  the colormap / contrast set on the scan. Only `…_07_reference_scan_lattice_overlay.svg` (resp.
  `…_lattice_plus_molecules.svg`) is saved by default — no `lattice_preview.png`.
- More formats: **Settings › Results & figures… › Save results as** (SVG / PDF / PNG).
  Gwyddion `.gwy` copies: tick *Also save Gwyddion .gwy* in the tool settings.
- **Assistant**: header button or **View › Assistant**; settings in **Settings › AI assistant…**.
- **Themes**: **View › Theme**, or **File › Import › Theme…** (applied immediately). See
  `customization/README_CUSTOMIZATION.md` for the theme keys (5 colours + optional font, size, radius).

## Remove SPM Studio (application only)

```bash
bash uninstall_new_spm_studio.sh --dry-run
bash uninstall_new_spm_studio.sh --apply           # type: REMOVE NEW SPM
```

Scans, results, scripts, settings, conversations, `~/.pi`, Ollama and credentials are kept.

## Troubleshooting

- **`SMOKE FAILED` during `--stage`:** nothing was switched. Remove the partial folder
  `~/.local/share/spm-studio-ai-app/releases/0.0.1` (`rm -rf` that exact path) after reading the error, and retry.
- **"Partial release … refusing to overwrite":** a previous `--stage` was interrupted; remove that exact
  `releases/0.0.1` folder and run `--stage` again.
- **Qt xcb error:** install `libxcb-cursor0` (see Requirements).
- **Figures still gray / old layout:** your lattice script was customised and therefore kept — use
  **Analysis › Restore built-in tools…**, then run the tool again.
- **Pi does not connect:** **Settings › AI assistant…** → *Existing Pi*, pick the `pi` executable; check
  `pi --version` in a terminal. The status line shows *Pi stopped* with a reconnect button if Pi exits.
- **Crash log:** `~/.cache/spm-studio-ai/crash.log`.
