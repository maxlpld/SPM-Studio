<p align="center">
  <img src="assets/spm-studio.svg" width="128" height="128" alt="SPM Studio logo: a scanning probe tip above a row of atoms">
</p>

<h1 align="center">SPM Studio</h1>

<p align="center">
  <b>Quick processing and analysis of scanning probe microscopy images — STM · AFM · KPFM —<br>
  with an optional AI assistant that can connect to AI agents.</b>
</p>

<p align="center">
  <img alt="Version 0.0.20" src="https://img.shields.io/badge/version-0.0.20-57758B">
  <img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-3776AB">
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

[Installation](#installation) · [Launch](#launch) · [Guided tutorial](#guided-tutorial) · [Updating](#updating) · [Uninstall](#uninstall) ·
[Features](#features) · [LaTeX & slides](#writing-papers-and-talks-latex-editor-presentation-editor-overleaf-optional) · [AI assistant](#ai-assistant-optional) · [Scientific scope](#scientific-scope-and-limitations) ·
[Developers](#developers) · [Help and contributing](#help-bugs-and-contributing)

## Installation

Copy **one** command for your system into a terminal and press Enter. It downloads the newest released
version, installs it **for your user only** (no administrator rights, its own private Python environment),
runs a self-test and creates the app launcher. Run it as your normal user — never with `sudo` or
*Run as administrator*. Running the same command again later updates SPM Studio.

**Ubuntu / Linux** (Terminal):

```bash
curl -fsSL https://raw.githubusercontent.com/maxlpld/SPM-Studio/main/get-spm-studio.sh | bash
```

**macOS** (Terminal; Python **3.12 recommended**, install via `brew install python@3.12` or [python.org](https://www.python.org/downloads/macos/). Supported: 3.12+ (subject to available wheels)):

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

### Download the source archive instead

Prefer a ZIP? Download the newest source archive from [GitHub Releases](https://github.com/maxlpld/SPM-Studio/releases), extract it and run the installer for your system (`install_spm_studio_clean.sh`, `install_spm_studio_macos.command`, or `install_spm_studio_windows.bat`). Detailed instructions: [Ubuntu](INSTALL_README_Ubuntu.md) · [macOS](INSTALL_README_macOS.md) · [Windows](INSTALL_README_Windows.md).

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

Then click **Open project** and choose a folder of `.sxm` / `.gwy` scans (or **New project**, then **Add scans**).
Your work on a project — display, processing, crops, selections, tool settings — is saved automatically in
`spm-studio-project.json` inside its folder and comes back the next time you open SPM Studio, even after a crash.
Several projects can be open at once (tabs above the scan list). Everything else is one click away: the
**gear button** at the right of the top bar opens *Settings*.

## Guided tutorial

At the first start SPM Studio offers a 10-minute guided tour (or skip it with *La science n’attend pas !*). It uses
three real KBr(001) nc-AFM scans bundled with the app (`src/spm_studio/resources/tutorial_scan`, unmodified Nanonis
files with their SHA-256 checksums) and the real controls: you open, inspect, apply a profile, duplicate a profile,
compare scans, inspect an incomplete scan, use a tool, read the guides, meet the assistant and export. A lesson
is finished by doing it (or *Skip step*); **Esc** ends the tour at any time. It works offline, needs no AI and
never changes your data. Replay it from *Settings › Tutorials* or *Help › Guided tutorial*.

## Beta testers

Invited testers can receive optional private extensions: *Settings › Beta Tester*, paste the invitation key,
name the computer and press *Activate beta access* — **once on each computer** (the same key works on several
computers, 5 by default). SPM Studio then offers the extension; *Install or update…* shows the release notes, a
progress bar and the details, then *Restart now* (signature and checksum are verified first). Everything that
only beta testers have carries a small **BETA** badge. *My computers…* lists your computers and can
remove an old one; *Sign out* / *Disconnect this computer* leave the beta on this computer. SPM Studio itself is
the same for everyone and never needs an account. A revoked or expired access stops future downloads and
updates; extensions already installed can be disabled or uninstalled, and your data are never touched.

## Updating

- **In the app:** *Settings (gear button) › Check for updates…* shows your version, the newest one and
  **what is new**. *Install update* downloads, builds and tests the new version **inside that window**, with a
  progress bar (*Show details* shows what the installer prints; no terminal opens). When it is done, choose
  **Restart now** or **Later**. A failed or cancelled update leaves your current version untouched.
  SPM Studio also checks quietly once a day (one request to GitHub; nothing about you or your data is sent;
  switch it off in the same window) and shows “⬆ … available — what's new?” in the status bar. Nothing is
  ever installed without you clicking.
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
keyboard shortcuts are plain JSON/CSV files. **Settings › Library** imports a file or a folder, edits,
duplicates and removes them, and **exports** any selection (scripts included) as one `.zip` that a colleague
installs with *Import file…*; nothing needs a restart. Every folder contains a `README.md` guide that says
exactly how its files are built — the assistant reads it before it creates a script or a profile for you.
See [`customization/README_CUSTOMIZATION.md`](customization/README_CUSTOMIZATION.md),
[`scripts/README.md`](scripts/README.md) and [`docs/MODULE_API.md`](docs/MODULE_API.md) for writing your own tools.

**Export profiles** — in *Export*, *Custom* takes 1 to 12 images (channels, other scans of the list, analysis
results and plots) in a row, a triangle or a grid; **Save as export profile…** keeps the whole figure under a
name for later scans.

## Writing papers and talks: LaTeX editor, presentation editor, Overleaf (optional)

Switch them on in **Settings › Documents**; a **LaTeX** and/or a **Slides** button then appears in the header.
Each opens a start screen (*new from a template* · *open* · *import* · *recent*) and then its own window, in
the same design as the scan window. Projects are ordinary folders, created with the project name in a default
place you choose in Settings (and changeable for every project).

- **LaTeX editor** — in the spirit of Overleaf: project files, outline, a source editor with syntax colours,
  completion of commands, `\ref`/`\cite` and file names, brackets and `\begin…\end`, find/replace; a
  formatting bar (sections, bold, math, symbols, lists, figures, tables, references); a **live PDF** next to the
  source, **Recompile** (Ctrl+Enter) and an **Auto-compile** button that rebuilds the PDF while you type;
  errors and warnings with their line (click to jump) and *Ask the assistant to fix*; pdfLaTeX, XeLaTeX,
  LuaLaTeX, latexmk or Tectonic; *Download source (.zip)*, *Download PDF*, *Save as*, *Save as template*.
  Uses the TeX installation of your computer (TeX Live, MacTeX or MiKTeX).
- **Presentation editor** — in the spirit of PowerPoint: slide thumbnails (drag to reorder), layouts, text
  boxes, **LaTeX boxes** (type LaTeX, it is compiled and shown automatically), pictures, **animated GIFs**,
  **videos**, shapes and arrows, themes (colours, fonts, title band, footer, slide numbers), speaker notes,
  undo/redo, full-screen slide show with transitions, export to **PDF**, **PowerPoint (.pptx)** and PNG, import
  of `.pptx` files.
- **Connected to the scan window** — *Export…* asks where the figure goes: a folder, the LaTeX document (copied
  to `figures/`, inserted with `\includegraphics` and a caption), a presentation (new or current slide) and/or
  **Overleaf** (project and folder of your choice) — any combination at once. Analysis results and graphs of the
  Logs panel can be sent the same way (right-click › *Send to…*), and both editors have a *From SPM Studio*
  button.
- **Overleaf** — through Overleaf's Git integration: paste a Git token and the address of your projects in
  Settings, then upload figures into any folder, import a whole project into the LaTeX editor, and push/pull
  your edits.
- **Templates** — LaTeX and presentation templates are imported, created, edited, exported and shared in
  *Settings › Library* like profiles; their folders contain a `README.md` explaining how to build one.
- **The assistant helps here too**: it can read the open document, write and fix LaTeX, compile, build slides,
  add LaTeX boxes and speaker notes — with every assistant, in plain chat too, and every change can be undone.

Guide: [`docs/DOCUMENTS.md`](docs/DOCUMENTS.md).

## AI assistant (optional)

The **Assistant** button in the header opens a panel that can dock on the right,
float to another screen and keep its history. Its settings (*Settings › General › AI assistant…*) have two
pages: **Quick start** — one card per way of getting an assistant, each showing what is done and what is
left to do — and **Advanced**, for people who bring their own AI workflow (program paths, workspace, API
connections and fallbacks, routing, local Judge). The starting points:

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

### Literature: Consensus and Zotero

*Settings › Literature* lets the assistant answer with references instead of from memory. Both sources are
connected in that page, by SPM Studio itself — no terminal, no agent configuration — and then work with every
assistant (Pi, Claude Code, Codex or a direct API chat), in ordinary chat too. Both are read-only and off
until you connect them.

- **Zotero** — click **Connect Zotero**. SPM Studio finds your library on this computer and reads it directly
  (search, abstracts, notes, text of indexed PDFs). Nothing has to be enabled in Zotero, any Zotero version
  works, and nothing leaves the computer. *Advanced* offers the Zotero app's own interface (version 7 or
  later), a data folder in an unusual place, or a library on zotero.org with a read-only key.
- **Consensus** ([consensus.app](https://consensus.app/)) — click **Sign in to Consensus**. The Consensus
  sign-in page opens in your browser; sign in with **your** account (a university e-mail uses your
  institution's licence) and come back: the page says *Connected*. A Zotero library linked inside Consensus
  is used by Consensus. SPM Studio never sees the password; it receives a token limited to searching.

Then simply ask: *“What does my Zotero library say about KPFM on graphene?”* or *“Find papers on tip
functionalisation with CO.”*

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
| Python | 3.12 or newer with venv and ensurepip (installers validate the environment; package availability depends on the Python release and platform) |
| Disk / network | about 1.5 GiB; internet for the one-time download of the Python packages (PySide6, NumPy, SciPy, …) |
| AI assistant | optional; Node.js, Pi, Ollama etc. are installed only if you choose them |
| LaTeX editor | optional; a TeX distribution (TeX Live, MacTeX or MiKTeX) or Tectonic. Overleaf sync needs Git |

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

Publishing a version: `python tools/release_tools.py bump 0.0.7`, write the notes in `CHANGELOG.md`,
commit, then `git tag v0.0.7 && git push origin main v0.0.7`. GitHub Actions tests it and publishes the release;
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
