# Changelog

All notable changes to SPM Studio. Each `## x.y.z` section is what users see in
*Settings › Check for updates…* and what the release workflow publishes as the GitHub Release notes,
so write it for users. Add new versions **at the top**.

The internal builds that preceded the GitHub project (0.7.0 – 0.8.3) are documented in
[`docs/DEVELOPMENT_HISTORY.md`](docs/DEVELOPMENT_HISTORY.md).

## 0.0.10 — 2026-11-18

### Lines with angles (polylines)

- With the **Line** tool, draw a line as usual, then hold **Shift** and click: the line continues from its last point with a new segment, in any direction. While Shift is held a dashed preview follows the mouse and shows the segment's angle and its turn from the previous segment; hold **Ctrl** as well to snap to 15° steps. Add as many segments as you need.
- Every corner can be dragged afterwards. Profiles follow the whole path (distance measured along the line, exact at the corners): live profile preview, *Line profiles* (the CSV now lists all corners), Line profile and flake-height tools, and the lines drawn on exported images.

### Multipass profile

- The **Multipass** profile reads the Nanonis Multipass configuration of the scan header: for every channel recorded in several passes it shows all of them (`[P1]`, `[P2]` …) side by side, titles them *P1 · Z*, *P2 · Z* …, and the log lists what each pass changed (bias, setpoint, Δz, playback, time per line).
- Profiles accept `"multipass": true` (see `profiles/README.md`).

### Measurement parameters on exported images

- **Export › Measurement parameters…** (for each image): write the acquisition parameters inside the image, in the corner you choose (top/bottom, left/right), with your text colour and an optional semi-transparent box. Tick what to show: scan bias, setpoint, feedback, time per line, size, date … and for Multipass scans every value of every pass — *P1 · Bias*, *P2 · Bias*, setpoint, Δz, playback offset, speed ratio … Quick choices: *Default* (the pass of that channel: bias, setpoint, Δz), *Bias of every pass*, *Bias + setpoint + Δz of every pass*. A corner shared with the scale bar moves off it. Saved in export profiles.

### One spectroscopy figure composer for every method

- The *Bias figure composer* is now the **Spectroscopy figure composer**. Choose the **Measurement type** at the top — Δf(V) KPFM / CPD, **dI/dV (STS)**, I(V), I(z) / Δf(z), or a generic X–Y spectrum — and the axes, labels, default channel, units and available fits follow.
- **dI/dV:** use the lock-in channel or a numerical derivative of the current; optional normalised (dI/dV)/(I/V), Savitzky–Golay smoothing, averaging of forward/backward sweeps and a waterfall offset. Conductance is shown in nS/pS.
- Where each spectrum was measured is marked on the scan exactly as for bias spectra; images can also show the measurement parameters in a corner.
- **New figure layout:** titles, panel letters, axis labels, colourbars, the figure title and the legend are now placed by an automatic layout and never overlap; each colourbar sits right under (or beside) its image and the page height follows the content. CPD / kink fits remain available for Δf(V).

## 0.0.9 — 2026-11-18

### Assistant in a window of its own

- **Detach** (the window button at the top of the assistant) now opens the assistant in an ordinary window of its own: move it to any screen or virtual desktop, minimise it, keep it next to the LaTeX or presentation editor — it stays where you put it and no longer follows or brings back the SPM Studio window. The same button docks it back.
- **Asking the assistant from the LaTeX or presentation editor** (Assistant button, *Ask the assistant to fix*, *Ask the assistant about this*) opens it beside the editor, without switching to the SPM Studio window; the editor stays as it was.

### LaTeX editor

- **Package button** in the toolbar (also *Menu › Add a package…*): type one or more package names (with options if needed); they are added to the preamble, and installed if they are missing on the computer.
- **Missing or outdated packages:** when a compilation stops because a package is not installed (or is too old), the Logs show **Install …** / **Update …** buttons (and *Install all*). SPM Studio installs it with MiKTeX, TeX Live's tlmgr (on Ubuntu/Debian into your own `~/texmf`, no administrator rights), or apt as a last resort, shows the output in the raw log and recompiles. *Menu › Install or update a LaTeX package…* does the same for any package.

### Fixes

- The assistant's *insert at the end* and *create a file* actions in the LaTeX editor now always edit the file you have open.
- Check for updates understands hotfix numbers such as 0.0.9.1 for future releases.

## 0.0.8 — 2026-11-17

### LaTeX editor (optional)

- **Switch it on in *Settings › Documents*:** a **LaTeX** button appears in the header. It opens a start screen — *new project from a template*, *open*, *import an Overleaf “Download source” .zip*, *import from Overleaf*, *recent* — and then the project in its own window, in the same design as the scan window.
- **Like Overleaf:** project files and outline on the left; the source in the middle (syntax colours, line numbers, completion of commands, environments, `\ref`, `\cite` and file names, automatic brackets and `\end{…}`, find/replace, comment lines); the **PDF** on the right, kept at the same page when it is rebuilt.
- **Recompile** (Ctrl+Enter) and an **Auto-compile** button that rebuilds the PDF while you type. Choose pdfLaTeX, XeLaTeX, LuaLaTeX, latexmk (BibTeX/Biber automatically) or Tectonic; build files stay in a hidden `.spm_build` folder.
- **Logs:** errors and warnings with their file and line (click to jump, red marks in the margin), the raw log, and *Ask the assistant to fix*.
- A formatting bar for sections, bold/italic, math, equations, a symbol palette (Greek, operators, arrows, `siunitx` units), lists, figures, tables, references and citations.
- Files are saved while you type (can be switched off). *Save as…* copies the project elsewhere; *Download source (.zip)* and *Download PDF*; word count.
- Uses the TeX installation of your computer (TeX Live, MacTeX, MiKTeX); *Settings › Documents* shows what was found and how to install it.

### Presentation editor (optional)

- **Switch it on in *Settings › Documents*:** a **Slides** button appears in the header (new from a template, open, import a .zip or a **PowerPoint .pptx**, recent).
- **Like PowerPoint:** slide thumbnails (drag to reorder, hide), layouts, text boxes with fonts, sizes, colours, bold/italic/underline, alignment and bullets; **pictures, animated GIFs and videos**; shapes and arrows; snapping guides, rotation, opacity, borders; speaker notes; undo/redo for everything.
- **LaTeX boxes:** *Insert › LaTeX* adds a text box in which you write LaTeX (text with `$…$` math or `\[ … \]`); it is compiled and displayed automatically while you type, at any size and colour.
- **Themes:** colours, fonts, title band, footer, slide numbers, background picture, 16:9 / 4:3 / 16:10.
- **Slide show** (F5 / Shift+F5) in full screen with fade and push transitions, videos that play on click or automatically.
- **Export** to PDF, **PowerPoint (.pptx)** (text stays editable, LaTeX boxes become sharp pictures, GIFs stay animated, videos are embedded), PNG images of every slide, or a `.zip` to share.

### From the scan window to your documents — and to Overleaf

- **Export… now asks where the figure goes:** save in a folder (as before), **insert in a LaTeX document** (copied into `figures/`, inserted at the cursor with `\includegraphics`, caption and label; an SVG is converted to a vector PDF), **add to a presentation** (new slide with a title, or the current slide), and/or **upload to Overleaf** (project and folder of your choice) — any combination at once. The choice is remembered.
- Analysis results and graphs of the Logs panel: right-click › *Send to LaTeX / presentation / Overleaf…*. Both editors have a **From SPM Studio** button.
- **Overleaf** through its Git integration: paste a Git token (kept in the system keyring) and your project addresses in *Settings › Documents*; then upload figures, import whole projects into the LaTeX editor, and push/pull your changes from the editor.

### Templates

- New Library sections **LaTeX templates** (Article, Scientific paper, Beamer talk, Report/thesis, Lab notes) and **Presentation templates** (Clean light, Graphite dark, Scientific talk with starter slides, Classic 4:3): import (a `.tex`, a LaTeX folder, an Overleaf .zip, a template .json), *New template…*, edit, duplicate, remove and export them like profiles. Each folder has a `README.md` saying how to build one.
- *Save as template…* in both editors stores the open project (figures / slides optional).

### Assistant

- The assistant now also works **in the LaTeX and presentation editors**, with every assistant and in plain chat: it reads the open document (file, cursor, compile errors; slides and their items), writes and fixes LaTeX, compiles, creates projects and presentations, adds slides, text, LaTeX boxes and notes. Every change can be undone in the editor. The editors' **Assistant** button opens it next to the window; the source's right-click menu has *Ask the assistant about this*.

SPM processing, analysis scripts, existing scans, results, profiles and settings are unchanged. The editors are off until you switch them on. PowerPoint export/import uses the new `python-pptx` dependency, installed by the update.

## 0.0.7 — 2026-11-17

### Literature sources that connect from Settings

- **Zotero works out of the box.** *Settings › Literature › Connect Zotero* finds your library on this computer and reads it directly from Zotero's database (read-only). Nothing has to be enabled in Zotero, every Zotero version works, and Zotero does not need to be running. When the Zotero app (7 or later) answers, it is used as well, so indexed PDFs are searched too. *Advanced* keeps the other ways: the Zotero app only, a data folder in an unusual place, or a zotero.org library with a read-only key.
- **Sign in to Consensus directly in Settings.** *Sign in to Consensus* opens the Consensus page in your browser; sign in with your own account (a university e-mail uses your institution's licence) and the Settings page shows *Connected*. No terminal and no assistant program is involved any more. An API key can be used instead (*Advanced*).
- **They now work with every assistant and in ordinary chat.** In 0.0.5 and 0.0.6 the sources needed an agent with tools switched on, and each agent had to be configured separately — which is why they often looked “not connected”. Now SPM Studio runs the lookup itself when the assistant asks for one, with Pi, Claude Code, Codex or a direct API chat. The chat shows a short line (“Looked up: Zotero search …”).
- **Sign-ins survive a restart on every computer.** The zotero.org key and the Consensus sign-in are kept in the system keyring, or — on computers without one — in a private file of your account, instead of being lost when SPM Studio closes.
- Clear messages when something is missing (Zotero not found, Zotero too old for its app interface, sign-in expired).

### Assistant settings

- **Two pages, like Settings.** *Quick start* shows one card per way of getting an assistant — *Set it up for me* (recommended), *I have a Claude subscription*, *I have a ChatGPT subscription*, *I already use Pi*, *I have an API key*, *No assistant* — each with its status (installed? signed in?) and the one or two buttons it needs, plus a line saying what to do next.
- A finished guided setup is saved and used at once; no extra *Save* click.
- **Advanced** keeps every expert setting: program paths, workspace, API connections and fallbacks, Fast/Smart models, the local Judge, how development tasks are confirmed.

### Updates inside the app

- **No terminal window any more.** *Install update* downloads, builds and tests the new version inside the update window, with a progress bar and the current step. **Show details** shows what the installer prints (and *Copy details* copies it).
- **Restart now or later.** When the new version is installed, choose *Restart now* (SPM Studio closes and opens the new version) or *Later* (it starts the next time you open SPM Studio).
- A failed or cancelled update leaves the current version untouched, says why, and cleans up after itself so that *Try again* works.

SPM processing and the analysis scripts are unchanged; existing scans, results, profiles and settings are kept. Updating from 0.0.6 still uses the previous update window one last time; from 0.0.7 on, updates run inside the app.

## 0.0.6 — 2026-11-16

### Windows installation

- **Fixed the Windows update smoke test failing on Unicode content:** the assistant's generated UTF-8 system context is now decoded explicitly as UTF-8, avoiding `UnicodeDecodeError` under Windows cp1252 locales (including environments based on Anaconda Python).
- **Consistent Unicode startup:** Windows staging checks now set `PYTHONUTF8=1`, and desktop/Start-menu shortcuts and the command launcher start Python in UTF-8 mode. This keeps SPM Studio's generated configuration and assistant content readable on Windows machines regardless of legacy text encoding defaults.
- **Cross-platform regression coverage:** the automated Windows test workflow also runs the application smoke test with Python UTF-8 mode disabled to prevent this issue from returning.

This is a Windows installation and reliability patch. All scientific analysis features and existing user data are unchanged.

## 0.0.5 — 2026-11-16

### Interface

- **The menu bar is gone.** *File · Scan · Selection · Analysis · View · Settings · Help* repeated the buttons of the window. Every keyboard shortcut still works. Commands that had no button are now in **Settings**, opened with the new **gear button** at the right of the top bar. A **Logs** button next to it shows and hides the Logs panel.
- **Close buttons of the Logs and Assistant panels are easy to see and to click** (18 px cross in a 28 px button, instead of a few pixels).
- **Readable progress bars.** While a script runs, a full-width bar with the current step and percentage appears right under *Run analysis*; the bar of the Logs panel is larger; the Assistant shows a full-width “working” strip.
- **Read me button** at the top of the Analysis panel: opens the `README.md` of the selected script (what it does, the method, its parameters and outputs), when the script has one.
- The Tools list no longer shows a dotted ring beside script names. The window title is **SPM Studio**.
- **Copy listed scans to a folder…** now asks where: choose the location and the name of the folder (new or existing). The proposal is still `<dataset>_scan_recap`.

### Settings window

- **General**: theme, results and figures, shortcuts, assistant, updates, tools maintenance, folders, link to the project on GitHub.
- **Library**: one place for analysis scripts, profiles, export profiles, themes, colormaps, plot styles and shortcut files. **Import** a file or a folder, **Edit** (the file is checked before it is saved), **Duplicate**, **Remove** (moved to a `removed` folder, never deleted), and **Export…** the selection as one `.zip` that a colleague installs with *Import file…*. Lists in the main window follow at once; no restart.
- **Literature**: connect **Consensus** and **Zotero** for the assistant (see below).
- **About**: version, author (maxlpld), buttons to open the project on GitHub, report a problem and read the release notes.

### Export

- **Custom figures are fully customisable**: 1 to 12 images, in a row, a triangle or a **grid with the number of columns you choose**; each image can be a channel of the open scan, a channel of **another scan of the list**, or an analysis result / plot, with its own title, unit, colourbar and scale bar.
- **Save as export profile…** stores the whole figure (page, arrangement, every image) under a name. It is in the figure list immediately and rebuilds the same figure on any scan. Export profiles are shared like everything else, from *Settings › Library*.

### Assistant

- **Consensus** ([consensus.app](https://consensus.app/)): the assistant can search the peer-reviewed literature through Consensus’ own connection, signed in with your Consensus account (a university e-mail uses your institution’s licence; a Zotero library linked inside Consensus is used by Consensus). SPM Studio never sees the password.
- **Zotero, directly**: the assistant can search your own library, read abstracts, notes and indexed PDF text — from the Zotero app on this computer (Zotero 7 or later, no account needed, nothing leaves the computer) or from zotero.org with a read-only key kept in the system keyring. It works with or without Consensus, and is strictly read-only.
- Both are off until you enable them in *Settings › Literature*. They need an agent assistant (Pi, Claude Code or Codex); a direct API connection is chat-only.
- **A guide in every folder.** The scripts folder and each customization folder (profiles, export profiles, themes, colormaps, plot styles, shortcuts) now contain a `README.md` that states exactly how its files are built, with a complete example and how to check the result. The assistant is told to read the guide of a folder before it creates or changes anything there, and to write a `README.md` for every script it builds.

### Profiles

- Only one **KPFM** profile remains. Installations that had both *KPFM* and *KPFM v7* keep the current one as *KPFM*; the previous files are saved in `profiles/.profile_backups_v005`.

SPM processing and the analysis scripts are unchanged; existing scans, results, profiles and settings are kept.

## 0.0.4 — 2026-11-16

- **Improved first-time Pi assistant setup:** the Models step now proposes Fast/Smart defaults from models listed by connected providers, prefers subscription authentication, and filters out old GPT-4 models that are incompatible with ChatGPT OAuth. Users can override all choices, keep custom choices on refresh, or restore recommendations.
- **Updated ChatGPT subscription sign-in** to match Pi's current OpenAI login flow. The setup still checks actual model access with a live test, since model listings alone do not guarantee access.
- **Prevented unfinished AI setup:** the Finish button is now disabled until Pi answers a real test successfully, making unsupported model errors clear rather than silently accepting a broken setup.
- **Fixed Git installation during Windows Pi setup:** the wizard explicitly selects the `winget` source to bypass a broken Microsoft Store source (certificate error `0x8a15005e`), with manual installation instructions if necessary.
- SPM processing, scientific analysis modules, and existing user data are unchanged. The update is installed beside previous versions.

## 0.0.3 — 2026-11-16

- **Fixed Windows installation from PowerShell.** Python detection now keeps its interpreter-information hashtable separate from the private virtual environment's `python.exe` path. This resolves the `System.Collections.Hashtable is not recognized` failure when installing with Python 3.12 or 3.13, including Anaconda Python.
- Improved cross-platform Qt GUI test shutdown cleanup on Linux, Windows and macOS, preventing native shutdown crashes after otherwise successful tests.
- Kept SPM analysis tools, the optional AI assistant and user data unchanged. An existing incomplete `0.0.2` installation does not block the new `0.0.3` installation because releases are staged in separate directories.

## 0.0.2 — 2026-11-15

- Fixed installation on macOS by selecting Vosk 0.3.44 (its macOS Universal2 wheel) while retaining Vosk 0.3.45 on other platforms.
- Prefer Python 3.12 on macOS and reject untested Python 3.14+ interpreters, preventing accidental use of Python 3.15.
- Removed obsolete private-repository instructions from the public README.
- Improved Linux GUI test stability and crash diagnostics with Xvfb, Qt XCB, and Python faulthandler. All tests remain enabled.
- Improved release CI diagnostics: allow every platform job to finish even when another platform fails, and upgrade GitHub Actions to Node 24-compatible versions.
- Updated Python package metadata to avoid deprecated license-table warnings.

## 0.0.1 — 2026-11-15

First release of SPM Studio from its GitHub repository. The application is functionally the same as the
last internal build (0.8.3): the same scientific tools and the same optional AI assistant, now from one
shared source tree for Ubuntu/Linux, Windows and macOS.

### Install and update from GitHub

- One-command install or update per OS (`get-spm-studio.sh` for Linux and macOS, `get-spm-studio.ps1` for
  Windows). Each command downloads a released version and runs that version's own installer.
- **Private repositories are supported**: the installers and the in-app *Check for updates* use your GitHub
  sign-in from the GitHub CLI (`gh auth login`) or a read-only token in `SPM_STUDIO_GITHUB_TOKEN`. No
  credential is stored in SPM Studio or in the repository.
- *Settings › Check for updates…* shows the installed and the newest version and what is new; *Install update*
  builds the new version next to the current one and switches only after its self-test passes. User data,
  settings, tools and AI accounts are never touched.
- `spm-studio --check-update` and `spm-studio --update` on every OS.

### For maintainers

- Pushing a `vX.Y.Z` tag runs the tests, then publishes a GitHub Release with these notes, one
  cross-platform source archive and `SHA256SUMS.txt`. The workflow checks that the tag matches
  `pyproject.toml` and that the update repository is configured for this GitHub repository.
- `python tools/release_tools.py set-repo OWNER/SPM-Studio` points the README, installers and update check
  at your repository. See `GITHUB_FIRST_UPLOAD.md` and `docs/RELEASING.md`.

### Note for users of the internal 0.8.x builds

Version numbers restart at 0.0.1, so an internal 0.8.x installation does not offer 0.0.1 as an update.
Run the install command from the README once; it installs 0.0.1 next to the old build, and later
versions then arrive through *Check for updates* as usual.
