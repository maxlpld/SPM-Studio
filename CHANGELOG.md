# Changelog

All notable changes to SPM Studio. Each `## x.y.z` section is what users see in
*Settings › Check for updates…* and what the release workflow publishes as the GitHub Release notes,
so write it for users. Add new versions **at the top**.

The internal builds that preceded the GitHub project (0.7.0 – 0.8.3) are documented in
[`docs/DEVELOPMENT_HISTORY.md`](docs/DEVELOPMENT_HISTORY.md).

## 0.0.20 — 2026-11-25

### Projects and crash recovery

- **A project is a folder.** *Open project* (Ctrl+Shift+O) opens a folder: its scans are listed and everything you
  do with them is saved in one readable file in that folder, `spm-studio-project.json` — display and colour maps,
  processing steps, crops, visible channels and titles, profiles, masks, drawn lines and regions, the analysis tool
  and its settings. Scan files are never changed. A folder of scans without that file simply becomes a project.
- **New project** chooses (or creates) the folder of a new project; the scans you have open can move into it.
  *Add scans* (Ctrl+O) adds single files to the current project. (*Open* and *Dataset* did the same thing; they
  are replaced by these three buttons.)
- **Several projects at once**: each open project is a tab above the scan list. Switching tabs saves the project
  you leave and brings the other back exactly as it was — nothing is shared between them.
- **Never lose your work**: the project state is saved automatically every 15 s when something changed (in the
  background, so a slow disk never freezes the window). Scans opened without a project are kept as an *unsaved
  session*. When SPM Studio starts again — after closing it, an accidental close or a crash — the projects that were
  open are reopened at the same scan, channel and step. Settings › General › *Projects and recovery* sets the
  interval or turns the reopening off.

### Scan list

- The commands are visible pictogram buttons under the list (no more “…” menu): **copy the scans to a folder**,
  **remove the selected scans**, **clear the list**. Files on disk are never deleted.
- **Select several scans**: hold **Shift**, browse with **↑ / ↓** (each scan is shown as you go, **← / →** still
  move between its channels) and press **Enter** on every scan you want — a check mark appears. Release Shift,
  then **Delete** (or the bin button) removes them all from the list; Esc clears the selection. Ctrl+click and
  Shift+click work too. The scan shown is in bold.
- *Copy scans to a folder* copies only the selected scans when several are selected, and opens the copy as a new
  project tab.

### Smooth channel switching

- Clicking another channel (or ← / →) no longer flashes the previous channel for a moment: the new channel appears
  at once (from its tile, or from memory when you come back to it), the channel you leave keeps its picture in its
  tile, and the strip is redrawn in one go. Switching scans shows an empty frame while reading instead of the old
  scan, and scans you visited before come back instantly.

### Compare results (redesigned)

- **Compare** now answers one question: *what value did the analysis tools measure on each scan?* Pick a quantity
  on the left (grouped by tool, with the number of scans); its value on every scan is listed and **drawn**, with
  the **mean ± standard deviation** band and a summary (n, mean, std, range). Untick a row to leave it out.
- Only the latest (or preferred) run of each scan by default; *This project* or *All scans ever analysed*; index
  columns are no longer mixed in. Values with different units are never put in one chart.
- **Export table** (CSV), **Save chart** (SVG, PDF or 300 dpi PNG), **Open run folder**, **Show scan** (double-click
  a row). It stays open next to the main window. When there is nothing to compare yet, it explains how to get
  results.

### Settings

- The Settings window **opens at once**: a page is built only when you open it.
- The page list on the left is always wide enough for its entries (also with extension pages), with comfortable
  rows.
- **Every option is in exactly one place**: a new *Appearance* page holds the theme, Theme Studio, help texts,
  pop-ups and the outline of the selected channel; *General* keeps projects, scans, logs, keyboard, assistant and
  performance; tools and folders are in *Library* (with *Restore built-in tools* for scripts); updates only in
  *Updates*; the project page and licence in *About*.

### Theme Studio (now for everyone)

- The visual theme editor from the private beta is part of SPM Studio: Settings › Appearance › **Open Theme
  Studio**. Click a control in the window to restyle it (colours with transparency, fonts, borders, corners,
  padding, for each state) with a live preview, undo / redo, save your theme, share it as a package, or import an
  SVG skin. Profiles made with the beta are imported automatically.

### Windows: no more short freezes

- Several things that could block the window for a moment, mostly on Windows (virus scanner, OneDrive or network
  folders), now run in the background or only once: the check of the scripts folder for new tools (it read the
  folder every 2 s), the comparison with the saved run on every change of a tool setting (it re-hashed the tool's
  files each time), indexing large folders (thousands of messages to the window), a settings read for every help
  text shown, and the database set-up on every query.
- If the window still stops responding for more than a second, SPM Studio notes what it was doing in
  `ui_freezes.log` (Settings › General › *Slow moments* › Open report) — please attach it to a bug report.

## 0.0.19 — 2026-11-24

- New built-in themes **Studio Light** and **Studio Dark** (menu View › Theme, or Settings › Appearance): borderless
  rounded cards with tinted neighbours, pill buttons, round step badges, one orange accent. Studio Dark has a new,
  warmer and more readable palette.
- Selected (checked) buttons never turn into a black block any more: soft accent fill with an accent outline, the
  icon and text stay visible.
- Pop-ups: no more green tick / red cross icons on their buttons; message pop-ups have all four corners rounded
  and can be moved by dragging them (Settings › General › Message pop-ups to go back to the system frame).
- Windows and dialogs open large enough for their content (no cut buttons, e.g. the unit buttons of Export
  figure); the side panels and the top bar start wide enough to show everything, and can still be shrunk.
- The README / guide viewer opens at a comfortable size with a wide, centred text column.
- Scan preview: every channel tile has the same size and a centred title (the first channel too); the selected
  channel keeps its place and gets an outline (Settings › General › Selected channel outline: on/off, colour,
  thickness, corner radius). The arrows move the selection from tile to tile.
- To-do & notes: complete redesign — a compact window (like a digital post-it) to keep in a corner or on another
  screen, large title with the open count, Tasks | Notes switch, round check marks, a pin to keep it on top; its
  size and place are remembered.

## 0.0.18 — 2026-11-23

### Ergonomics

- **Scrolling scrolls the panel**: the mouse wheel over a drop-down list, number box or slider no longer changes
  its value while you scroll through a panel; a control reacts to the wheel only after you clicked into it.
- **The Logs panel starts closed.** It opens with its button, or by itself when something fails (a script
  error, a crash). Other important messages put a mark on the Logs button instead. *Settings › General ›
  Logs when a script runs* opens it at every run, as before.
- **Less text**: long grey help texts show only their first sentence; the full text is in the tooltip
  (*Settings › General › Full help texts* shows the long versions again). Shorter beta and to-do texts.
- Windows and pop-ups always fit on the screen; the profile and figure-size lists in the top bar, the sidebar
  tabs and the LaTeX / presentation template lists are never cut off.

### One design everywhere

- **New README viewer** for every README and guide: title and file name, an outline of long documents,
  headings, code blocks and tables in the app's colours, a readable text column, find-in-page (Ctrl+F).
- **Pop-ups look like the rest of the app**: the confirming button of every message box and dialog is the
  primary (accent) button.
- **Numbered steps** in round outlined badges (01, 02, 03 …), first used in Settings › Beta Tester.
- The BETA mark follows the theme instead of its own purple, and the 3D-print preview uses the theme colours
  instead of a white Matplotlib background.

### For developers

- `tools/ui_screenshots.py` and the *UI screenshots* workflow render the main windows and dialogs offscreen
  for design review.
- The application-wide ergonomics filter returns at once for unrelated events; the Windows test runners get
  90 minutes.

## 0.0.17 — 2026-11-23

### 3D print (Tools › 3D print)

- **Sharper live 3D preview**: the plate is shown on a much finer grid (about 260 points along the long side,
  no extra halving), the reliefs are sampled exactly from their own height grid, the text edges are smooth
  and the lighting follows the real scale.
- After saving a Bambu Studio 3MF, the message now reminds that Bambu Studio shows a mixed filament in one
  blended colour in the Prepare view; the gradient is computed when slicing and appears in the Preview tab.

### Maintenance

- The start-up smoke test waits for background network checks to finish before closing, so a slow network
  no longer makes it crash at exit on Linux.

## 0.0.16 — 2026-11-23

### 3D print (Tools › 3D print)

- **Colour bar = image**: new range mode *Same as the image* (default) uses the contrast range of each channel
  in SPM Studio, and the colour-bar labels follow **Fix Zero** (they start at 0 when it is on). A
  *Colour-bar labels* choice forces measured values or 0-based labels.
- **STEP files open in Bambu Studio** (and other OpenCASCADE-based slicers / CAD programs): solids are now
  written as standard B-rep faces with shared edges instead of bare faceted faces, which those programs read
  as "no geometry". Flat areas are merged into single faces and the relief uses a lighter grid in STEP
  (STL and 3MF keep the full quality).
- **Automatic colour gradient for Bambu Studio**: *Save 3MF (colour gradient)* now writes a Bambu Studio
  project with the printer, nozzle and filaments already set and **one gradient mixed filament per channel**
  (Color Mixing, Gradient mode, low colour → high colour, mixed-colour sublayers on) assigned to the scan and
  its 3D colour bar only. The gradient follows the height, so the colour bar matches the relief. Each channel
  can have its own gradient. Untick *Bambu Studio project…* for the plain 3MF.
- **Printer and nozzle** choice (all current Bambu Lab printers, 0.2 / 0.4 / 0.6 / 0.8 mm): the project uses
  Bambu's own presets for them, the plate size is checked against the bed and the thinnest lines follow the
  nozzle.
- **Text colour** (black by default) for titles, ticks, scale bar and every text, and **background colour**
  (white by default) for the plate; the live preview now shows these colours and the gradients.

## 0.0.15 — 2026-11-22

### 3D print (Tools › 3D print)

- **Much better print quality**: every text, tick and scale bar is now drawn from bold vector font outlines on a
  0.05 mm grid with vertical walls (sharp, printable letters); the relief has Draft / Standard / Fine quality
  presets (the grid can still be set by hand) and the files only keep detail where it is visible.
- **Bigger default text** (5 mm, bold) and higher labels (1 mm).
- **Centred layout**: the plate gets equal margins on all four sides, with or without a title or colour bar.
- **Several channels on one plate**: one, two side by side or stacked, three in a row or as a triangle, four
  (2 × 2 or in a row) or a custom rows × columns grid; each panel has its own channel, range and 3D colour bar.
- **Channel titles** on/off and a **main title** centred on top of the plate.
- **Fridge magnet** option: four round pockets (radius 5.1 mm, 2 mm deep by default, adjustable) under the
  corners for small magnets; the plate is thickened automatically when needed.
- **Save 3MF (colour gradient)**: one part per channel (relief + its 3D colour bar) with its own low → high
  colours, plus the plate & labels part; the gradient recipe for Bambu Studio colour mixing (Gradient mode,
  along the height) is stored inside the file and in a `.colour_gradient.txt` next to it. Each channel can get
  a different gradient. Because the gradient follows the height, the 3D colour bar and the relief show the same
  colour at the same value.
- The plate is made of separate closed solids (plate, reliefs, colour bars, labels); STEP files contain one
  solid per part. The previous single-relief engine stays available in the code.

## 0.0.14 — 2026-11-22

### Simpler to-do list

- One box at the top: type a task, press Enter. Tick it when it is done. A hint explains what to do when the list is empty.
- Click a task to add details (optional) and press **✨ Do it with the assistant**, or **Delete**. Right-click a task for the same actions; double-click to rename; drag to reorder.
- **Tasks** and **Notes** tabs (the number of open tasks is shown on the tab). **✨ Assistant ▾** does all open tasks, makes a plan, or writes a report, a paper draft or slides from your notes.
- Finished tasks: crossed out, normal or hidden. Everything is still saved automatically.

### Beta testers

- The beta service address is built in: just paste your invitation key, name the computer, press **Activate beta access** (three numbered steps). SPM Studio then looks for the private extension by itself.
- Installing a private extension now works like an update: release notes, a progress bar, **Show details** (log), then **Restart now** or **Later**.
- Everything that only beta testers have is marked with a small **BETA** badge (pages in Settings, options and tools of private extensions).

## 0.0.13 — 2026-11-21

### Guided tutorial on real KBr scans

- First start: a small welcome card offers a **10-minute guided tour** (or “La science n’attend pas !” to skip it; it does not come back by itself).
- Twelve lessons on three real KBr(001) nc-AFM scans bundled with SPM Studio (unmodified Nanonis files, checked by SHA-256): open the dataset, open a scan, Z channel and forward/backward traces, apply a profile, duplicate a profile safely, compare an up and a down scan, inspect an incomplete scan, use a tool, read the guides, meet the assistant, export a figure.
- A lesson is completed by doing the real action in SPM Studio (or by **Skip step**), never by Next alone. **Esc** ends the tour at once from anywhere.
- The tour works offline, needs no AI and changes none of your data; the scans are copied to your tutorial folder, the originals stay untouched.
- **Settings › Tutorials** and **Help**: start, resume, replay *what’s new*, reset the progress, open the KBr tutorial scans.

### Updates & Beta Tester settings

- **Settings › Updates**: current version, check for public updates, changelog, daily check on/off.
- **Settings › Beta Tester**: invited testers enter their invitation key once per computer (the same key works on several computers, 5 by default) to receive optional private extensions; see and remove their computers; sign out. Nothing changes for everyone else, and no account is ever needed to use SPM Studio.

### Extensions (for invited testers)

- SPM Studio can load optional extensions installed from Settings › Beta Tester. An extension is installed only after you confirm, and only if its signature (pinned key) and checksum are correct; it can be disabled, rolled back or uninstalled at any time without touching your data.

## 0.0.12 — 2026-11-21

### To-do list & notes, connected to the assistant

- New **To-do** button (on by default; Settings › Documents): a to-do list and free notes in their own window, like the LaTeX and presentation editors.
- Add tasks in one line (`Analysis: CPD map of scan 0024` sets the category), describe what you need in the task's details, tick them when done, drag to reorder.
- **Ask the assistant ▾**: do the selected task(s), do every open task, plan the open tasks, or write a **report / paper draft** (LaTeX editor) or a **presentation** (Slides) from your notes and finished tasks. The assistant can also read the list, add tasks, tick a task it has finished and note what it did and where the result is.
- Finished tasks: struck through, normal or hidden (in the window and in Settings › Documents).
- **Erase everything** button (with confirmation; a copy is kept).
- Everything is saved automatically in the to-do folder (`<data>/todo/todo.json`, with a backup) and is still there after closing SPM Studio, restarting or updating.

### The assistant may work everywhere in SPM Studio

- With tools on, Pi, Claude Code and Codex may read and change files in every SPM Studio folder: scripts, profiles and templates, LaTeX projects, presentations, the to-do list, and the app's own source when you ask for a change of the app. They may also run commands. Claude Code and Codex now get these folders and the permissions explicitly, so they no longer refuse.
- **Consensus and Zotero** are on by default. Consensus still needs its sign-in in Settings › Literature; Zotero is found automatically.
- A new setup (Pi wizard, Claude Code, Codex) switches this on at once; the setup window says so. After updating, the assistant asks once at your next message (the tools button in its header switches tools off at any time).
- The assistant's instructions now state its permissions clearly, and tell it what to say when tools are off.

### 3D print: STL / STEP relief with a 3D colour bar

- New tool **3D print (STL / STEP)** in Tools: any channel of the open scan (topography, current, dI/dV map, Δf …), a **Lattice measurements** result (vectors raised on the relief, a, b, γ embossed) or a **Molecule placement** result (molecules raised on the relief) becomes a printable relief.
- **3D colour bar**: a wedge from the lowest value (base) to the highest (base + relief height), with raised ticks and values; place it right, left, top, bottom or not at all.
- **Cut the range** (percentiles or values) so a single high peak does not flatten everything; values outside are printed flat. Optional smoothing, invert, title, scale bar, text and overlay heights.
- **Live 3D preview**, rotatable with the mouse; size, highest point and triangle count shown.
- Exports a watertight binary **STL** and a **STEP** (AP214 faceted solid, grid coarsened automatically to keep CAD imports fast), plus a `.print3d.json` with every parameter.

## 0.0.11 — 2026-11-20

### Delete exactly the line you select

- Click a line (or a region / point) on the scan to select it: it gets a white halo and is selected in the *Selections* list too. Press **Delete** (Suppr) to remove only that one. Before, Delete always removed the most recent line.
- The remaining lines are renumbered (L1, L2 …) in drawing order but **keep their colours**; a custom name given in *Line profiles* is kept. A new line takes a colour that is not already on the scan. The *Line profiles* window follows the deletion.
- With nothing selected, Delete removes nothing (the status bar explains how to select). *Undo last* still removes the most recent line.
- Line colours are now the same on the scan, in the live profile preview and on the exported image.

### New tool: Microscope X/Y calibration (lattice)

- Calibrates the lateral X/Y piezo constants from atomic-resolution images of a known crystal, using **every open scan**: it reads the scan angle, the slow-scan direction and the previous calibration from each file, detects the lattice with the Lattice measurements engine and fits the new constants with their uncertainties (bootstrap and leave-one-out tests).
- **Thermal drift:** the drift compensation written in each file is taken into account, one session drift is fitted with the calibration when the scans allow it (up and down scans, 0°/90°, different speeds), and every up/down pair gives an independent drift estimate that does not use the reference lattice.
- Reference crystals: KBr(001) by default (a = 6.65 Å, γ = 90°, diagonal 4.7 Å — A. Hinaut, Ph.D. thesis, Université Toulouse III, 2012), NaCl, KCl, HOPG, Au/Ag/Cu(111), Si(111)-7×7, h-BN or custom; the conventional and the primitive surface cell are both recognised.
- Results: a before → after lattice figure of the active scan (old values and arrows pale, new ones in full colour; old → new calibration in the other corner), a statistics figure, a JSON and a CSV. See the tool's README.
- Installed automatically for existing users (once; a copy you already imported is left untouched).

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
