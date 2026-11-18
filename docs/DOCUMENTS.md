# LaTeX editor, presentation editor and Overleaf (SPM Studio 0.0.8)

Both editors are optional. Switch them on in **Settings › Documents**:

* **Show the LaTeX button in the main window** — the *LaTeX* button appears in the header;
* **Show the Slides button in the main window** — the *Slides* button appears in the header.

Each button opens a start screen: **New** (choose a template, a name and where to save it), **Open**,
**Import** (an Overleaf *Download source* `.zip`, a LaTeX folder, a project from Overleaf, or a PowerPoint
file for slides) and **Recent**. The project then opens in its own window; several can be open at once.

## Where projects are saved

Every new project is a **folder with the project name** inside the default folder of *Settings ›
Documents* (`~/Documents/SPM Studio/LaTeX` and `~/Documents/SPM Studio/Presentations` unless you choose
others). The start screen lets you pick another place for each project (*Save in › Change…*). *Menu ›
Save as…* copies a project to any other place under a new name.

| Project | Contains |
|---|---|
| LaTeX | your `.tex`, `.bib`, … files, `figures/` (figures from SPM Studio), `.spm_build/` (compiler output, hidden), `.spm_latex.json` (main document and compiler of this project) |
| Presentation | `<name>.spmdeck` (the slides, JSON) and `media/` (pictures, GIFs, videos) |

## LaTeX editor

* **Left:** project files (new file, new folder, upload; right-click: set as main document, rename,
  delete, insert as figure) and the outline of the open file (click a heading to go there).
* **Middle:** the source. Syntax colours, line numbers, completion (`\` commands, `\begin{`
  environments, `\ref{` labels, `\cite{` keys of your `.bib` files, file names; *Ctrl+Space* forces it),
  automatic closing of brackets and `$`, `\end{…}` after Enter on a `\begin{…}` line, *Ctrl+/* comments
  lines, *Ctrl+B* / *Ctrl+I* bold / italic, *Ctrl+F* / *Ctrl+H* find / replace.
* **Formatting bar:** undo/redo, sections, bold/italic/underline, inline and display math, numbered
  equation, symbol palette (Greek, operators, relations, arrows, accents, `siunitx` units), lists, figure,
  table, `\ref`, `\cite`, hyperlink, comment.
* **Right:** the PDF (zoom, fit width / page, open in your viewer, save a copy). **Recompile**
  (*Ctrl+Enter*; the arrow chooses the compiler: latexmk, pdfLaTeX, XeLaTeX, LuaLaTeX, Tectonic, or
  recompiles from scratch) and **Auto-compile** (rebuilds the PDF a moment after you stop typing — the
  delay is in *Settings › Documents*). **Logs** lists the errors and warnings with their file and line
  (click to jump; red marks in the margin) and the raw log; *Ask the assistant to fix* sends the errors and
  the surrounding lines to the assistant.
* Files are saved automatically while you type (like Overleaf; can be switched off). Recompile always saves
  first. A file changed by another program (for example by the assistant with file tools) is reloaded.

The editor uses the TeX installation of the computer:

| System | Install |
|---|---|
| Ubuntu | `sudo apt install texlive-latex-extra texlive-science latexmk` (+ `texlive-xetex`, `texlive-luatex`) |
| macOS | MacTeX (https://tug.org/mactex/) or `brew install --cask mactex-no-gui` |
| Windows | MiKTeX (https://miktex.org/download), allow on-the-fly package installation |

*Settings › Documents* shows which compilers were found.

**Packages.** The **Package** button of the toolbar adds `\usepackage{…}` lines to the preamble (several
names separated by commas, with options if needed) and installs a package that is not on the computer. When
a compilation stops because a package is missing or too old, *Logs* shows **Install …** / **Update …**
buttons: SPM Studio uses MiKTeX (for your account), TeX Live's `tlmgr` (on Ubuntu/Debian in user mode, into
`~/texmf`, without administrator rights; on macOS the system asks for your password) or, as a last resort on
Ubuntu, `apt` (asks for your password), shows what it ran in the raw log and recompiles. If nothing works it
shows the command to type in a terminal.

## Presentation editor

* **Slides** on the left (drag to reorder; right-click: new with a layout, duplicate, delete, hide in the
  slide show). **New slide** (*Ctrl+M*; the arrow chooses the layout: title, title and content, two
  columns, section, title only, picture with caption, title and formula, blank).
* **Insert:** *Text* (double-click a box to type), **LaTeX** — a LaTeX text box: write text with `$…$`
  math or `\[ … \]` in the *Format* panel; it is compiled and displayed automatically (*Render
  automatically while typing*), with its size, colour, alignment and background; the packages used by all
  LaTeX boxes are set in *Design*. *Image* (PNG, JPG, SVG, PDF), *GIF* (animated, also while editing),
  *Video* (MP4, MOV, WebM…; double-click to play while editing, click during the slide show; autoplay,
  loop, muted), *Shape* (rectangle, rounded rectangle, ellipse, triangle, line, arrow). Files can also be
  dragged onto the slide; *Ctrl+V* pastes a picture or text.
* **Format bar:** font, size, bold/italic/underline, colour (colour selector), alignment, bullets — on the
  selected words while typing, otherwise on the whole box; bring to front / send to back; align on the
  slide. Items snap to the slide centre, margins and other items (hold *Alt* to place freely); arrows move
  the selection (1 pt, *Shift* 10 pt); *Ctrl+D* duplicates; *Delete* removes. Corner handles of pictures
  keep the proportions (*Shift* to stretch).
* **Format / Slide / Design panels:** position, size, rotation, opacity, borders, fill; the slide's
  layout, background (colour or picture), transition (fade, push) and visibility; the theme (colours, fonts,
  sizes, title band, footer, slide numbers, background picture, slide size, LaTeX packages), *Apply a
  template…* and *Save as template…*.
* **Speaker notes** under the slide. **Undo / redo** for everything (*Ctrl+Z* / *Ctrl+Y*). Saved
  automatically a moment after each change (can be switched off).
* **Present** (*F5* from the start, *Shift+F5* from the current slide): full screen; →, space, click
  next; ← previous; *B* black screen; *Esc* leaves.
* **File › Export:** PDF (one page per slide, vector text), **PowerPoint (.pptx)** — text stays editable
  text, LaTeX boxes become sharp pictures, GIFs stay animated, videos are embedded, shapes stay shapes; PNG
  images of every slide; `.zip` to send the whole presentation. *File › Import a PowerPoint file* reads
  the text boxes, pictures, simple shapes and notes of a `.pptx`.

## From the scan window to the editors (and Overleaf)

When a LaTeX editor, a presentation editor or an Overleaf project is set up, **Export…** asks, after the
figure dialog, **where the figure goes** — tick any combination:

* **Save in a folder** — as before (you choose folder and file name);
* **Insert in a LaTeX document** — an open project or a recent one: the figure is copied into
  `figures/` (PDF; an SVG export is converted to a vector PDF because pdfLaTeX cannot include SVG) and
  inserted at the cursor as a `figure` with `\includegraphics`, caption and label (`\usepackage{graphicx}`
  is added if missing; in a beamer document a new frame is created);
* **Add to a presentation** — on a new slide with a title, or on the current slide (SVG is used when
  exported, so the picture stays sharp at any size);
* **Upload to Overleaf** — choose the project and the folder (*List folders* reads them; type a new name
  to create one).

The choice is remembered for the next export. Results and graphs listed in the **Logs** panel can be sent the
same way (right-click › *Send to LaTeX / presentation / Overleaf…*), and both editors have a **From SPM
Studio** button that opens the export of the open scan aimed at that document.

## Overleaf

Overleaf has no upload interface for other programs, but every Overleaf project is a Git repository.
SPM Studio uses that **Git integration**:

1. On Overleaf: *Account Settings › Git integration › Generate token* (needs an Overleaf plan with Git
   integration — many universities provide Overleaf Professional/Commons — or Overleaf Server Pro).
2. In SPM Studio: *Settings › Documents › Overleaf* — paste the token (**Save**; it is kept in the system
   keyring, or a private file of your account), set the server if your institution runs its own Overleaf,
   and **Add project…** with the project address from the browser
   (`https://www.overleaf.com/project/…`). **Test connection** checks both.
3. Git must be installed (https://git-scm.com).

Then: upload figures from *Export…*, **Import from Overleaf** a whole project into the LaTeX editor, and in
the editor *Overleaf › Push / Pull* (or *Link to an Overleaf project…* for a local project). Changes made
on both sides to different lines are merged; changes to the same lines are refused without losing anything.

## Templates

LaTeX templates live in `<customization>/latex_templates`, presentation templates in
`<customization>/presentation_templates`; each folder has a `README.md` that explains how to build one.
SPM Studio ships *Article*, *Scientific paper (two columns)*, *Beamer talk*, *Report / thesis*, *Lab notes*,
and the presentation themes *Clean light*, *Graphite dark*, *Scientific talk* (with starter slides) and
*Classic 4:3*. **Settings › Library** imports (a `.tex`, a LaTeX folder, an Overleaf `.zip`, a template
`.json`), creates (*New template…*), edits, duplicates, removes and exports them as one `.zip`, like every
other customization. In the editors, *Save as template…* stores the open project.

## The assistant

The assistant works with the editors exactly as with scans, with every assistant (Pi, Claude Code, Codex,
direct API) and also in plain chat: it can read the open document (file, cursor, errors; the slides and
their items), insert or replace LaTeX, create files, compile and read the new errors, create projects and
presentations, add slides, text, LaTeX boxes and shapes, change items and speaker notes. The editors'
**Assistant** button opens it next to the window, in a window of its own (move it to any screen or
desktop; the window button at the top of the assistant docks it back into SPM Studio); *Ask the assistant to fix* (LaTeX logs) and the
right-click *Ask the assistant about this* of the source send the context. Every change can be undone in
the editor (*Ctrl+Z*). The chat shows short notes (“✎ LaTeX: replace …”) instead of the technical
requests; the format is described in `src/spm_studio/documents/protocol.py`.
