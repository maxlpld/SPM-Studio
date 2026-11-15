<p align="center">
  <img src="assets/spm-studio.svg" width="128" height="128" alt="SPM Studio logo: a scanning probe tip above a row of atoms">
</p>

<h1 align="center">SPM Studio</h1>

<p align="center">
  <b>Quick processing and analysis of scanning probe microscopy images — STM · AFM · KPFM —<br>
  with an optional AI assistant that can connect to AI agents.</b>
</p>

<p align="center">
  <img alt="Version 0.0.1" src="https://img.shields.io/badge/version-0.0.1-57758B">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB">
  <img alt="Linux, Windows, macOS" src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-555555">
  <img alt="MIT licence" src="https://img.shields.io/badge/licence-MIT-2E7D32">
</p>

SPM Studio is a desktop application for opening, processing and analysing SPM data quickly. Open a Nanonis
`.sxm` or Gwyddion `.gwy` file, level and filter it, look at every channel and its metadata, run an analysis
tool (lattice, molecules, heights, CPD histograms, KPFM edges, drift-corrected stacks) and export
publication-ready figures — in one window, on your own computer, with no cloud service required.

If you want, an **AI assistant** docks next to your data. It can chat about your analysis and, when you
allow it, write new analysis tools for you. It works with the Pi coding agent, Claude Code, OpenAI Codex
CLI, a direct cloud API, or a local model through Ollama — or not at all: every scientific tool works
without AI.

---

## Contents

[Installation](#installation) · [Launch](#launch) · [Updating](#updating) · [Uninstall](#uninstall) ·
[Features](#features) · [AI assistant](#ai-assistant-optional) · [Scientific scope](#scientific-scope-and-limitations) ·
[Developers](#developers) · [Help and contributing](#help-bugs-and-contributing)

## Installation

Copy **one** command for your system into a terminal and press Enter. It downloads the newest released
version, installs it **for your user only** (no administrator rights, its own private Python environment),
runs a self-test and creates the app launcher. Run it as your normal user — never with `sudo` or
*Run as administrator*. Running the same command again later updates SPM Studio.

> **The repository is private at the moment?** Then these commands cannot download anything yet — use
> the [private repository](#private-repository-invited-collaborators) instructions just below.

**Ubuntu / Linux** (Terminal):

```bash
curl -fsSL https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.sh | bash
```

**macOS** (Terminal; needs Python 3.11+ from [python.org](https://www.python.org/downloads/macos/) or `brew install python@3.12`):

```bash
curl -fsSL https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.sh | bash
```

**Windows 10 / 11** (PowerShell — Start menu › type *PowerShell*; Python 3.12 is offered via winget if missing):

```powershell
irm https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.ps1 | iex
```

Then open **SPM Studio** from the application menu, the Start menu or `~/Applications`.

On Ubuntu/Debian the script offers to install the few Qt system libraries SPM Studio needs with `sudo apt`
(it asks first; this is the only step that may ask for your password).

A specific version: `curl … | SPM_VERSION=0.0.1 bash` (Windows: `$env:SPM_VERSION='0.0.1'; irm … | iex`).

### Private repository (invited collaborators)

While the repository is private, GitHub only serves its files to signed-in members, so the commands above
fail. Accept the e-mail invitation to the repository, then sign in **once** with the official
[GitHub CLI](https://cli.github.com/):

| System | Install the GitHub CLI | Sign in (opens your browser) |
|---|---|---|
| Ubuntu / Linux | `sudo apt install gh` | `gh auth login` |
| macOS | `brew install gh` | `gh auth login` |
| Windows | `winget install GitHub.cli` (then open a new PowerShell) | `gh auth login` |

Choose *GitHub.com*, *HTTPS* and *Login with a web browser*. Then install with:

**Linux / macOS**

```bash
gh api -H 'Accept: application/vnd.github.raw' repos/maxlpld/SPM-Studio/contents/get-spm-studio.sh | bash
```

**Windows (PowerShell)**

```powershell
gh api -H "Accept: application/vnd.github.raw" repos/maxlpld/SPM-Studio/contents/get-spm-studio.ps1 | Out-String | iex
```

The installer and the in-app update check then use that sign-in automatically (through `gh auth token`).
SPM Studio never stores it, never writes it to a file in the repository, and sends it only to the GitHub API.
Without the GitHub CLI you can put a personal access token in the environment variable
`SPM_STUDIO_GITHUB_TOKEN` instead — see [`SECURITY.md`](SECURITY.md) for which token to create and how to
keep it safe.

**Without any command line tool:** while signed in on github.com, open the repository's **Releases** page,
download `SPM-Studio-<version>.zip`, extract it and run the installer for your system
(`install_spm_studio_clean.sh`, `install_spm_studio_macos.command`, or `install_spm_studio_windows.bat`).
Step-by-step guides: [Ubuntu](INSTALL_README_Ubuntu.md) · [macOS](INSTALL_README_macOS.md) ·
[Windows](INSTALL_README_Windows.md) · [all Linux options](README_INSTALL.md).

### About the one-line commands

`curl … | bash` and `irm … | iex` run a script downloaded from this repository. Read it first if you like:
[`get-spm-studio.sh`](get-spm-studio.sh), [`get-spm-studio.ps1`](get-spm-studio.ps1). They only download the
release archive from GitHub (HTTPS) and start the installer inside it; nothing runs with administrator
rights, and the application's Python packages come from PyPI. Each release also lists `SHA256SUMS.txt` for
its archive.

## Launch

- **Ubuntu / Linux:** application menu › *SPM Studio*, or `spm-studio` in a terminal.
- **macOS:** `~/Applications/SPM Studio.app` (Launchpad / Spotlight), or `~/.local/bin/spm-studio`.
- **Windows:** Start menu or desktop › *SPM Studio*.

Then **File › Open** a `.sxm` or `.gwy` file, or open a folder of scans in the browser panel.

## Updating

- **In the app:** *Settings › Check for updates…* (also in *Help*) shows your version, the newest one and
  **what is new**; *Install update* runs the installer for you. SPM Studio also checks quietly once a day
  (one request to GitHub; nothing about you or your data is sent; switch it off in the same dialog) and
  shows “⬆ … available — what's new?” in the status bar. Nothing is ever installed without you clicking.
- **From a terminal:** `spm-studio --check-update` or `spm-studio --update`
  (Windows: `& "$env:LOCALAPPDATA\SPMStudio\bin\spm-studio.cmd" --update`), or run the install command again.

Each update is built and self-tested **next to** the version you use, and only then switched on; if anything
fails, your current version keeps working. Scans, results, tools, settings, conversations and AI accounts are
never touched. Older versions are kept until you remove them (`--prune-old` on Linux/macOS,
`-Mode PruneOld` on Windows — see the install guides).

Only published releases are offered as updates — ordinary commits to the repository are not.

## Uninstall

The uninstallers default to a **dry run** (they list what they would remove) and always keep your scans,
results, scripts, settings, conversations, AI sign-ins, `~/.pi` and Ollama models. They are inside every
installed version:

```bash
# Ubuntu / Linux
cp ~/.local/share/spm-studio-ai-app/current/app/uninstall_new_spm_studio.sh /tmp/
bash /tmp/uninstall_new_spm_studio.sh            # dry run
bash /tmp/uninstall_new_spm_studio.sh --apply    # asks you to type REMOVE NEW SPM

# macOS
cp ~/Library/Application\ Support/SPMStudio/current/app/uninstall_spm_studio_macos.sh /tmp/
bash /tmp/uninstall_spm_studio_macos.sh --apply
```

```powershell
# Windows (PowerShell)
$v = (Get-Content "$env:LOCALAPPDATA\SPMStudio\current.txt").Trim()
Copy-Item "$env:LOCALAPPDATA\SPMStudio\releases\$v\app\uninstall_spm_studio_windows.ps1" $env:TEMP
powershell -ExecutionPolicy Bypass -File "$env:TEMP\uninstall_spm_studio_windows.ps1" -Apply
```

You can also run the same uninstaller from an extracted release archive. Details and options
(`--remove-ai-runtime` / `-RemoveAiRuntime`): [`README_INSTALL.md`](README_INSTALL.md) and the
[Windows](INSTALL_README_Windows.md) and [macOS](INSTALL_README_macOS.md) guides.

## Features

**Data**
- Native readers for Nanonis **`.sxm`** and Gwyddion **`.gwy`** files: all channels, forward/backward traces,
  physical units and the full header metadata (searchable metadata panel).
- Scan browser for folders of measurements; per-scan display settings are remembered.
- Measurement **profiles** for STM, AFM molecular resolution, AFM dissipation/excitation, KPFM and multipass.

**Processing** (non-destructive, reorderable steps)
- Levelling: plane, three-point plane, path plane, 2-D polynomial, row/column mean, median and polynomial
  line correction, median difference.
- Corrections: scar and stripe removal, spot replacement, zero/mean/median offsets, clipping and thresholds.
- Filters: Gaussian, mean, median, minimum/maximum, high-pass, unsharp mask, difference of Gaussians,
  Laplace and Sobel; arithmetic (invert, absolute, square, square root, multiply, add).
- Cropping with metadata kept consistent; line profiles and multi-profiles; selections and ROIs.

**Analysis tools** (each is a plain Python module you can read, change or add to)

| Tool | What it does |
|---|---|
| Channel overlay | Superimposes several calibrated channels with live opacity and per-channel colour maps. |
| CPD / Bias histogram | Scan panels with mask fitting: amplitude, fitted μ, σ, uncertainties and R² in the legend. |
| Flake / island height | Several line ROIs across an island; left/right edge heights and stripe statistics. |
| KPFM edge analysis | Topography/CPD edge metrics and 2-D gradient correlation (experimental, simplified). |
| Lattice measurements | Primitive lattice vectors measured on the scan. |
| Molecule placement | Molecules drawn at true scale on a lattice result. |
| MultiFrame physical stack | Drift, primitive reciprocal lattice, overlap and stacking engines (SPM MultiFrame 0.1.2). |

**Figures and export**
- Publication exports in **SVG**, PDF and PNG with page presets (single/double column), scale bars,
  colour bars and consistent fonts; analysis figures use the same renderer as *Export…*.
- Optional Gwyddion `.gwy` copies of results.
- Gwyddion colour gradients (also those of your own Gwyddion installation) and Matplotlib colour maps.

**Customisation by importing files** — themes, colour maps, profiles, figure presets, plot styles and
keyboard shortcuts are plain JSON/CSV files (*File › Import*, or *Settings › Open customization folder*).
See [`customization/README_CUSTOMIZATION.md`](customization/README_CUSTOMIZATION.md) and
[`docs/MODULE_API.md`](docs/MODULE_API.md) for writing your own tools.

## AI assistant (optional)

The **Assistant** button in the header (or *View › Assistant*) opens a panel that can dock on the right,
float to another screen and keep its history. The first time, it offers five starting points:

| Choice | For whom | What SPM Studio does |
|---|---|---|
| **Set up Pi** | New to AI agents | Guided setup: private Node.js (if needed), the Pi agent, optional router and sub-agents, browser sign-in (e.g. ChatGPT Plus/Pro, GitHub Copilot) or an API key, model choice, and an optional **local Judge** model through Ollama with three hardware-checked profiles and a live test. Never changes an existing `~/.pi`. |
| **My Pi** | You already use Pi | Uses your Pi exactly as configured. |
| **Claude Code / Codex** | Claude or ChatGPT subscribers | Uses those command-line agents with their own sign-in. |
| **Cloud API** | Chat only | Direct OpenAI-compatible, Anthropic, Gemini, OpenRouter or Ollama chat (not a coding agent). |
| **Later** | | Assistant off; all scientific tools keep working. |

- Ordinary chat starts Pi **without tools**. Writing or changing analysis tools is a separate, explicitly
  authorised task; new tools are staged, checked (manifest and syntax) and only then registered.
- API keys come from environment variables or the operating system's secure keyring; without a keyring they
  stay in memory for the current session only. No key is ever shipped with SPM Studio.
- Optional offline push-to-talk speech input (Vosk), with a one-time, confirmed model download.
- **Limits:** neither Pi's coding tools nor Python plugins are an operating-system sandbox, and a generated
  tool is not scientifically validated by passing a syntax check. Read
  [`SECURITY.md`](SECURITY.md) and [`VERIFY_AND_TEST.md`](VERIFY_AND_TEST.md) before enabling coding tools.

Setup details: [`docs/AI_ASSISTANT_SETUP.md`](docs/AI_ASSISTANT_SETUP.md).

## Scientific scope and limitations

SPM Studio is offline analysis software: it does **not** control a microscope. The readers, processing,
channel tools, analysis scripts, figures and exports were carried forward from earlier laboratory versions;
their scientific validity is subject to the original data-validation constraints described in
[`docs/REAL_DATA_VALIDATION.md`](docs/REAL_DATA_VALIDATION.md) and
[`docs/SCIENTIFIC_PARITY_V050.md`](docs/SCIENTIFIC_PARITY_V050.md). The KPFM edge tool is marked experimental.
Check results on your own data before publishing them.

## Requirements

| | |
|---|---|
| Systems | Ubuntu 24.04+ (other Linux distributions with Qt 6 libraries should work), Windows 10 21H2+ / 11 (64-bit), macOS 12+ (Apple Silicon and Intel) |
| Python | 3.11 or newer (the installers check this; Windows can install 3.12 via winget, macOS via Homebrew) |
| Disk / network | about 1.5 GiB; internet for the one-time download of the Python packages (PySide6, NumPy, SciPy, …) |
| AI assistant | optional; Node.js, Pi, Ollama etc. are installed only if you choose them |

The releases are **source archives**, not compiled programs: the same archive serves every operating system,
and the installer builds a private Python environment on your computer.

## Developers

```bash
git clone https://github.com/maxlpld/SPM-Studio.git     # private: gh repo clone maxlpld/SPM-Studio
cd SPM-Studio
python3 -m venv .venv && . .venv/bin/activate                   # Windows: py -3.12 -m venv .venv; .venv\Scripts\activate
python -m pip install -e '.[all,dev]'
QT_QPA_PLATFORM=offscreen python -m spm_studio --smoke-test      # headless self-test
python -m pytest -q                                              # test suite
python -m spm_studio                                             # run from source
```

Project layout:

```text
src/spm_studio/        the application (core = readers, processing, export, updates; ui = Qt; ai = assistant)
scripts/               the analysis tools shipped to users (copied to their scripts folder on first start)
customization/         themes, colour maps, profiles, presets, shortcuts
tests/                 pytest suite (headless; Qt tests run when PySide6 is installed)
tools/release_tools.py version bump, repository setting, release notes and release archive
install_*/uninstall_*  per-OS installers and uninstallers; get-spm-studio.* = one-line bootstrap
docs/                  specifications, module API, validation reports, releasing guide
```

Publishing a version: `python tools/release_tools.py bump 0.0.2`, write the notes in `CHANGELOG.md`,
commit, then `git tag v0.0.2 && git push origin main v0.0.2`. GitHub Actions tests it and publishes the release;
every installed SPM Studio then offers it. Full guide: [`docs/RELEASING.md`](docs/RELEASING.md).
First upload of this repository: [`GITHUB_FIRST_UPLOAD.md`](GITHUB_FIRST_UPLOAD.md).

## Help, bugs and contributing

- **Bugs and questions:** open an issue on GitHub with your SPM Studio version (*Help › About*), operating
  system, what you did and what happened; attach `~/.cache/spm-studio-ai/crash.log` if there is one.
  Please do not attach unpublished data unless you are allowed to share it.
- **Contributing:** [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Security problems:** please report privately, see [`SECURITY.md`](SECURITY.md).
- **What is new:** [`CHANGELOG.md`](CHANGELOG.md) — the same notes appear in *Check for updates*.
  History of the internal builds before the first GitHub release: [`docs/DEVELOPMENT_HISTORY.md`](docs/DEVELOPMENT_HISTORY.md).

## Licence

[MIT](LICENSE). The bundled Inter fonts are under the SIL Open Font Licence
([`src/spm_studio/resources/fonts/OFL.txt`](src/spm_studio/resources/fonts/OFL.txt)).
